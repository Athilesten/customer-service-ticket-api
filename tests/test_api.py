import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, OperationalError
from django.test import Client, TestCase, override_settings

from tickets.models import Actor, AuditEvent, Role, Ticket
from tickets.service import digest

ROOT = "/api/v1/tickets"
START = datetime(2026, 11, 14, 9, tzinfo=UTC)


class TicketAPI(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tokens = {}
        for handle, role in [
            ("customer", Role.REPORTER), ("other", Role.REPORTER), ("lead", Role.MANAGER),
            ("agent", Role.AGENT), ("alternate", Role.AGENT), ("disabled", Role.AGENT),
        ]:
            token = handle.ljust(32, "-")
            cls.tokens[handle] = token
            Actor.objects.create(handle=handle, role=role, token_digest=digest(token),
                                 active=handle != "disabled")

    def setUp(self):
        self.client = Client()
        clock = patch("django.utils.timezone.now", return_value=START)
        self.clock = clock.start()
        self.addCleanup(clock.stop)

    def auth(self, handle):
        return {"Authorization": f"Bearer {self.tokens[handle]}"}

    def get(self, handle, path=ROOT, **query):
        return self.client.get(path, query, headers=self.auth(handle))

    def post(self, handle, path, payload, **headers):
        return self.client.post(path, payload, content_type="application/json",
                                headers={**self.auth(handle), **headers})

    def create(self, handle="customer", title="Delivery label fails", **extra):
        response = self.post(handle, ROOT, {
            "title": title, "description": "The printer returns an error.", **extra,
        })
        self.assertEqual(response.status_code, 201, response.content)
        return response["Location"], response

    def update(self, handle, path, action, version, expected=200, **values):
        response = self.post(handle, f"{path}/{action}", {"expected_version": version, **values})
        self.assertEqual(response.status_code, expected, response.content)
        return response.json()

    def advance(self, path):
        self.update("lead", path, "assignment", 1, assignee="agent")
        return self.update("agent", path, "transition", 2, status="in_progress")

    def test_lifecycle_and_audit_correlation(self):
        path, creation = self.create()
        self.assertEqual(creation.json()["version"], 1)
        started = self.advance(path)
        self.assertEqual(started["sla"]["first_response"]["status"], "met")
        resolved = self.update("agent", path, "transition", 3, status="resolved")
        self.assertEqual(resolved["sla"]["resolution"]["status"], "met")
        reopened = self.update("lead", path, "transition", 4, status="open")
        self.assertIsNone(reopened["sla"]["resolution"]["completed_at"])
        self.assertEqual(reopened["sla"]["resolution"]["due_at"], resolved["sla"]["resolution"]["due_at"])
        self.assertEqual(reopened["sla"]["first_response"], resolved["sla"]["first_response"])
        events = self.get("lead", path + "/audit", limit=2).json()
        tail = self.get("lead", path + "/audit", offset=events["next_offset"]).json()
        trail = events["items"] + tail["items"]
        self.assertEqual([event["version"] for event in trail], [1, 2, 3, 4, 5])
        self.assertEqual(trail[0]["request_id"], creation["X-Request-ID"])
        self.assertEqual(trail[-1]["action"], "reopened")
        self.assertEqual(trail[1]["changes"]["assignee"], {"from": None, "to": "agent"})
        self.assertNotIn("printer", json.dumps(trail))

    def test_idempotency_normalizes_and_scopes_keys(self):
        payload = {"title": "  Same title  ", "description": "A detailed description"}
        header = {"Idempotency-Key": "portal-01"}
        first = self.post("customer", ROOT, payload, **header)
        same = self.post("customer", ROOT, {**payload, "title": "Same title", "priority": "normal"}, **header)
        different = self.post("customer", ROOT, {**payload, "title": "Different title"}, **header)
        other = self.post("other", ROOT, payload, **header)
        self.assertEqual([first.status_code, same.status_code, different.status_code, other.status_code],
                         [201, 200, 409, 201])
        self.assertEqual(first["Location"], same["Location"])
        self.assertNotEqual(first["Location"], other["Location"])
        self.assertEqual(AuditEvent.objects.count(), 2)
        self.update("lead", first["Location"], "assignment", 1, assignee="agent")
        replay = self.post("customer", ROOT, payload, **header)
        self.assertEqual(replay.json()["version"], 2)
        self.assertEqual(AuditEvent.objects.count(), 3)

    def test_permissions_and_reporter_visibility(self):
        path, creation = self.create()
        self.assertNotIn("reporter", creation.json())
        self.assertEqual(self.get("other", path).status_code, 404)
        self.assertEqual(self.get("other").json()["items"], [])
        self.assertEqual(self.get("customer", path + "/audit").status_code, 403)
        self.assertEqual(self.get("agent", "/api/v1/metrics/queue").status_code, 403)
        self.assertEqual(self.get("disabled", path).status_code, 401)
        self.assertEqual(self.client.get(ROOT)["WWW-Authenticate"], "Bearer")
        self.update("agent", path, "assignment", 1, expected=403, assignee="agent")
        self.update("lead", path, "assignment", 1, assignee="agent")
        self.update("alternate", path, "transition", 2, expected=403, status="in_progress")
        self.update("customer", path, "transition", 2, expected=403, status="in_progress")
        result = self.post("customer", ROOT, {"title": "A new issue", "description": "Enough text here",
                                            "priority": "urgent"})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(AuditEvent.objects.count(), 2)

    def test_conflicts_and_invalid_assignees_do_not_increment_version(self):
        path, _ = self.create()
        self.update("lead", path, "transition", 1, expected=409, status="in_progress")
        self.update("lead", path, "transition", 1, expected=409, status="resolved")
        for assignee in ("customer", "disabled", "unknown"):
            self.update("lead", path, "assignment", 1, expected=422, assignee=assignee)
        self.update("lead", path, "assignment", 1, assignee="agent")
        stale = self.update("lead", path, "priority", 1, expected=409, priority="high")
        self.assertEqual(stale["error"]["code"], "version_conflict")
        self.update("lead", path, "assignment", 2, expected=409, assignee="agent")
        self.update("lead", path, "priority", 2, expected=409, priority="normal")
        self.assertEqual(Ticket.objects.get().version, 2)
        self.assertEqual(AuditEvent.objects.count(), 2)

    def test_failed_audit_write_rolls_back_creation_and_update(self):
        with patch("tickets.service.record_event", side_effect=IntegrityError("synthetic failure")):
            failed = self.post("customer", ROOT, {"title": "A new issue", "description": "Enough text here"})
            self.assertEqual(failed.status_code, 500)
            self.assertNotIn("synthetic failure", failed.content.decode())
        self.assertFalse(Ticket.objects.exists())
        path, _ = self.create()
        with patch("tickets.service.record_event", side_effect=IntegrityError("synthetic failure")):
            self.update("lead", path, "assignment", 1, expected=500, assignee="agent")
        ticket = Ticket.objects.get()
        self.assertIsNone(ticket.assignee)
        self.assertEqual(ticket.version, 1)
        self.assertEqual(AuditEvent.objects.count(), 1)

    def test_priority_tightens_clocks_and_retains_completed_response(self):
        path, _ = self.create()
        previous = self.advance(path)
        escalated = self.update("lead", path, "priority", 3, priority="urgent")
        self.assertEqual(escalated["sla"]["first_response"], previous["sla"]["first_response"])
        self.assertEqual(escalated["sla"]["resolution"]["due_at"], "2026-11-14T13:00:00Z")
        downgraded = self.update("lead", path, "priority", 4, priority="low")
        self.assertEqual(escalated["sla"], downgraded["sla"])

    def test_overdue_escalation_tightens_both_open_clocks(self):
        path, _ = self.create()
        self.clock.return_value = START + timedelta(hours=5)
        escalated = self.update("lead", path, "priority", 1, priority="urgent")
        self.assertEqual(escalated["sla"]["first_response"]["status"], "breached")
        self.assertEqual(escalated["sla"]["resolution"]["status"], "breached")

    def test_exact_deadline_is_due_soon_until_passed_and_completion_at_it_is_met(self):
        path, _ = self.create("lead", priority="urgent")
        self.advance(path)
        self.clock.return_value = START + timedelta(hours=4)
        self.assertEqual(self.get("lead", path).json()["sla"]["resolution"]["status"], "due_soon")
        self.assertEqual(len(self.get("lead", resolution_sla="due_soon").json()["items"]), 1)
        self.assertEqual(len(self.get("lead", resolution_sla="breached").json()["items"]), 0)
        resolved = self.update("agent", path, "transition", 3, status="resolved")
        self.assertEqual(resolved["sla"]["resolution"]["status"], "met")

    def test_sla_filter_and_metrics_match_at_fixed_time(self):
        missed_path, _ = self.create("lead", priority="urgent")
        met_path, _ = self.create("lead", priority="urgent")
        self.create("lead", priority="urgent")
        self.create("lead", priority="high")
        self.create()
        self.advance(missed_path)
        self.advance(met_path)
        self.update("agent", met_path, "transition", 3, status="resolved")
        self.clock.return_value = START + timedelta(hours=7, minutes=30)
        self.update("agent", missed_path, "transition", 3, status="resolved")
        metrics = self.get("lead", "/api/v1/metrics/queue").json()
        self.assertEqual(
            {key: metrics[key] for key in ("total", "backlog", "unassigned", "urgent_backlog",
                                           "breached", "due_soon", "met", "missed", "attainment_percent")},
            {"total": 5, "backlog": 3, "unassigned": 3, "urgent_backlog": 1,
             "breached": 1, "due_soon": 1, "met": 1, "missed": 1, "attainment_percent": 50.0},
        )
        for state in ("breached", "due_soon", "met", "missed", "on_track"):
            matching = self.get("lead", resolution_sla=state).json()["items"]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["sla"]["resolution"]["status"], state)

    def test_search_combines_filters_and_stably_pages_ties(self):
        first, _ = self.create("lead", "Invoice lookup fails", priority="high")
        self.create("other", "Invoice spelling error")
        self.create("lead", "Unrelated support issue", priority="high")
        self.advance(first)
        matched = self.get("lead", q="INVOICE", priority="high", assignee="agent", status="in_progress")
        items = matched.json()["items"]
        self.assertEqual([str(item["id"]) for item in items], [first.rsplit("/", 1)[1]])
        self.assertNotIn("description", items[0])
        one = self.get("lead", limit=1).json()
        two = self.get("lead", offset=one["next_offset"]).json()
        self.assertEqual(len({item["id"] for item in one["items"] + two["items"]}), 3)
        self.assertIsNone(two["next_offset"])
        self.assertEqual(self.get("lead", q="%").json()["items"], [])

    def test_unassigned_queue_orders_by_deadline(self):
        self.create("lead", "Later deadline ticket", priority="low")
        _, urgent = self.create("lead", "Earlier deadline ticket", priority="urgent")
        assigned, _ = self.create("lead", "Already assigned ticket", priority="urgent")
        self.advance(assigned)
        queue = self.get("lead", assignment="unassigned", sort="resolution_due").json()["items"]
        self.assertEqual([row["title"] for row in queue], [urgent.json()["title"], "Later deadline ticket"])

    def test_malformed_invalid_and_oversize_requests(self):
        cases = [
            ("{missing", 400), ('{"title":"abc","title":"second"}', 400), ('{"x":NaN}', 400),
            ({"title": "   ", "description": "too short", "unknown": True}, 422),
            ({"title": "Hello\x00 world", "description": "Enough text here"}, 422),
            ({"title": "Hello\ud800 world", "description": "Enough text here"}, 422),
            ({"title": "x" * 33_000}, 413),
        ]
        for payload, status in cases:
            with self.subTest(status=status):
                response = self.post("customer", ROOT, payload)
                self.assertEqual(response.status_code, status, response.content)
                self.assertEqual(response.json()["error"]["request_id"], response["X-Request-ID"])
        wrong_type = self.client.post(ROOT, "ticket", content_type="text/plain", headers=self.auth("customer"))
        self.assertEqual(wrong_type.status_code, 415)
        self.assertEqual(self.get("lead", limit=101).status_code, 422)
        self.assertEqual(self.get("lead", q=["first", "second"]).status_code, 422)
        self.assertEqual(self.get("lead", unknown="value").status_code, 422)
        self.assertEqual(self.client.delete(ROOT)["Allow"], "GET, POST")
        self.assertFalse(Ticket.objects.exists())

    @override_settings(DEBUG=False)
    def test_health_and_error_serialization(self):
        self.assertEqual(self.client.get("/health/live").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/health/ready").json(), {"status": "ready"})
        self.assertEqual(self.client.get("/nonsense").json()["error"]["code"], "not_found")
        with patch("tickets.views.Ticket.objects.exists", side_effect=OperationalError("hidden")):
            result = self.client.get("/health/ready")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result["Retry-After"], "1")
        self.assertEqual(result["Cache-Control"], "no-store")
        self.assertNotIn("hidden", result.content.decode())

    def test_token_rotation_invalidates_old_token(self):
        output = StringIO()
        call_command("provision_actor", "new-agent", "agent", stdout=output)
        token = output.getvalue().strip()
        output = StringIO()
        call_command("provision_actor", "new-agent", "agent", "--rotate", stdout=output)
        self.assertEqual(self.client.get(ROOT, headers={"Authorization": f"Bearer {token}"}).status_code, 401)
        self.assertEqual(self.client.get(
            ROOT, headers={"Authorization": f"Bearer {output.getvalue().strip()}"}
        ).status_code, 200)
