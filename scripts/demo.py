"""Run the reviewer workflow through Django's HTTP test client on an isolated SQLite file."""

import argparse
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from statistics import median, quantiles
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
API = "/api/v1/tickets"
METRICS = "/api/v1/metrics/queue"
START = datetime(2026, 11, 14, 9, tzinfo=UTC)


class Demo:
    def __init__(self):
        from django.core.management import call_command
        from django.test import Client

        call_command("migrate", verbosity=0)
        self.client = Client(HTTP_HOST="localhost")
        self.tokens = {}
        for handle, role in (("reviewer", "manager"), ("casey", "agent"), ("portal", "reporter"),
                             ("other", "reporter")):
            output = StringIO()
            call_command("provision_actor", handle, role, stdout=output)
            self.tokens[handle] = output.getvalue().strip()

    def request(self, user, method, path, expected=200, body=None, **headers):
        request = getattr(self.client, method)
        options = {"headers": {"Authorization": f"Bearer {self.tokens[user]}", **headers}}
        if body is not None:
            options["data"] = body
            options["content_type"] = "application/json"
        response = request(path, **options)
        if response.status_code != expected:
            raise RuntimeError(f"{method} {path}: expected {expected}, got {response.status_code}")
        return response.json(), response.headers

    def create(self, title, user="reviewer", expected=201, **extra):
        return self.request(user, "post", API, expected, {
            "title": title, "description": "Synthetic incident for the mentor demonstration.",
        }, **extra)

    def change(self, user, path, command, version, expected=200, **values):
        result, _ = self.request(user, "post", f"{path}/{command}", expected,
                                 {"expected_version": version, **values})
        return result

    def walkthrough(self, clock):
        ticket, headers = self.create("Warehouse label printer offline", "portal",
                                      **{"Idempotency-Key": "demo-001"})
        path = headers["Location"]
        replay, _ = self.create("Warehouse label printer offline", "portal", 200,
                                **{"Idempotency-Key": "demo-001"})
        assert replay["id"] == ticket["id"]
        self.request("other", "get", path, 404)
        self.change("reviewer", path, "assignment", 1, assignee="casey")
        conflict = self.change("reviewer", path, "priority", 1, 409, priority="urgent")
        assert conflict["error"]["code"] == "version_conflict"
        urgent = self.change("reviewer", path, "priority", 2, priority="urgent")
        reviewed, _ = self.request("reviewer", "get",
                                   API + "?q=label&priority=urgent&assignee=casey&sort=resolution_due")
        assert [row["id"] for row in reviewed["items"]] == [ticket["id"]]

        clock.return_value = START + timedelta(minutes=30)
        started = self.change("casey", path, "transition", 3, status="in_progress")
        clock.return_value = START + timedelta(hours=4, minutes=15)
        overdue, _ = self.request("reviewer", "get", API + "?resolution_sla=breached")
        assert [row["id"] for row in overdue["items"]] == [ticket["id"]]
        resolved = self.change("casey", path, "transition", 4, status="resolved")
        audit, _ = self.request("reviewer", "get", path + "/audit")
        assert [event["version"] for event in audit["items"]] == [1, 2, 3, 4, 5]
        assert audit["items"][0]["request_id"] == headers["X-Request-ID"]
        assert started["sla"]["first_response"]["status"] == "met"
        assert resolved["sla"]["resolution"]["status"] == "missed"
        return {
            "idempotent_replay": "same ticket",
            "other_reporter_visibility": 404,
            "stale_write": conflict["error"]["code"],
            "urgent_resolution_due_at": urgent["sla"]["resolution"]["due_at"],
            "first_response": started["sla"]["first_response"]["status"],
            "before_resolution": overdue["items"][0]["sla"]["resolution"]["status"],
            "after_resolution": resolved["sla"]["resolution"]["status"],
            "audit_actions": [event["action"] for event in audit["items"]],
            "creation_request_id_matches_audit": True,
        }

    def seed(self, count, clock):
        for index in range(count):
            clock.return_value = START - timedelta(hours=(index % 30))
            _, headers = self.create(f"Synthetic service request {index + 1}")
            path = headers["Location"]
            version = 1
            if index % 4 == 0:
                version = self.change("reviewer", path, "priority", version,
                                      priority="urgent")["version"]
            if index % 3 == 0:
                self.change("reviewer", path, "assignment", version, assignee="casey")
            if index % 6 == 0:
                clock.return_value += timedelta(hours=index % 29)
                self.change("casey", path, "transition", version + 1, status="in_progress")
                self.change("casey", path, "transition", version + 2, status="resolved")
        clock.return_value = START + timedelta(hours=4, minutes=15)

    def baseline(self, now):
        """Scan the full queue and calculate SLA counts client-side from timestamps."""
        count = dict.fromkeys(("total", "backlog", "unassigned", "urgent_backlog",
                              "due_soon", "breached", "met", "missed"), 0)
        requests = 0
        offset = 0
        while offset is not None:
            page, _ = self.request("reviewer", "get", API + f"?limit=25&offset={offset}")
            requests += 1
            offset = page["next_offset"]
            for ticket in page["items"]:
                count["total"] += 1
                resolution = ticket["sla"]["resolution"]
                due = datetime.fromisoformat(resolution["due_at"])
                completed = resolution["completed_at"]
                if completed:
                    count["met" if datetime.fromisoformat(completed) <= due else "missed"] += 1
                    continue
                count["backlog"] += 1
                count["urgent_backlog"] += ticket["priority"] == "urgent"
                count["unassigned"] += ticket["assignee"] is None
                if now > due:
                    count["breached"] += 1
                elif due - now <= timedelta(hours=1):
                    count["due_soon"] += 1
        return count, requests

    def compare(self, now, runs):
        baseline_times = []
        summary_times = []
        for _ in range(runs):
            started = perf_counter()
            expected, requests = self.baseline(now)
            baseline_times.append((perf_counter() - started) * 1000)
            started = perf_counter()
            result, _ = self.request("reviewer", "get", METRICS)
            summary_times.append((perf_counter() - started) * 1000)
            assert {key: result[key] for key in expected} == expected
        return {
            "tickets": result["total"],
            "runs": runs,
            "matching_counts": len(expected),
            "counts": {key: result[key] for key in expected},
            "resolution_attainment_percent": result["attainment_percent"],
            "page_scan": timings(baseline_times, requests),
            "queue_metrics": timings(summary_times, 1),
            "request_reduction_percent": round(100 * (1 - 1 / requests), 2),
        }


def timings(samples, requests):
    return {
        "api_requests": requests,
        "median_ms": round(median(samples), 2),
        "p95_ms": round(quantiles(samples, n=20, method="inclusive")[18], 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickets", type=int, default=300, help="Additional synthetic tickets")
    parser.add_argument("--runs", type=int, default=20, help="Number of measurement pairs")
    args = parser.parse_args()
    if not 1 <= args.tickets <= 2_000 or not 2 <= args.runs <= 100:
        parser.error("Use 1–2000 tickets and 2–100 runs")

    sys.path.insert(0, str(BASE_DIR))
    with TemporaryDirectory(prefix=".demo-", dir=BASE_DIR) as folder:
        os.environ.update({
            "DJANGO_SETTINGS_MODULE": "helpdesk.settings",
            "TICKET_DB_BACKEND": "sqlite",
            "TICKET_SQLITE_PATH": str(Path(folder) / "demo.sqlite3"),
            "TICKET_LOG_LEVEL": "CRITICAL",
            "TICKET_ALLOWED_HOSTS": "localhost",
            "TICKET_SLA_WARNING_MINUTES": "60",
        })
        for priority, response, resolution in (
            ("URGENT", 1, 4), ("HIGH", 2, 8), ("NORMAL", 4, 24), ("LOW", 8, 72),
        ):
            os.environ[f"TICKET_SLA_{priority}_RESPONSE_HOURS"] = str(response)
            os.environ[f"TICKET_SLA_{priority}_RESOLUTION_HOURS"] = str(resolution)
        import django
        from django.db import connections

        django.setup()
        try:
            with patch("django.utils.timezone.now", return_value=START) as clock:
                demo = Demo()
                walkthrough = demo.walkthrough(clock)
                demo.seed(args.tickets, clock)
                comparison = demo.compare(clock.return_value, args.runs)
            print(json.dumps({"walkthrough": walkthrough, "comparison": comparison}, indent=2))
        finally:
            connections.close_all()


if __name__ == "__main__":
    main()
