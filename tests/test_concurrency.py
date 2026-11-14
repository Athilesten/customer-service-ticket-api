from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.db import connections
from django.test import Client, TransactionTestCase

from tickets.models import Actor, AuditEvent, Role, Ticket
from tickets.service import digest

ROOT = "/api/v1/tickets"


class ConcurrentWrites(TransactionTestCase):
    def setUp(self):
        self.token = "manager".ljust(32, "-")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        Actor.objects.create(handle="manager", role=Role.MANAGER, token_digest=digest(self.token))
        self.payload = {"title": "Delayed shipment", "description": "Synthetic shipment issue."}

    def parallel_posts(self, path, payloads, headers):
        barrier = Barrier(len(payloads), timeout=10)

        def post(payload):
            try:
                barrier.wait()
                return Client().post(path, payload, content_type="application/json", headers=headers).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
            return sorted(pool.map(post, payloads))

    def test_postgres_concurrent_retries_create_one_ticket(self):
        if connections["default"].vendor != "postgresql":
            self.skipTest("Requires PostgreSQL; SQLite in-memory test tables use shared-cache locks")
        statuses = self.parallel_posts(ROOT, [self.payload, self.payload],
                                       {**self.headers, "Idempotency-Key": "same-submission"})
        self.assertEqual(statuses, [200, 201])
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 1)

    def test_postgres_concurrent_edits_have_one_winner(self):
        if connections["default"].vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row locks")
        created = Client().post(ROOT, self.payload, content_type="application/json", headers=self.headers)
        self.assertEqual(created.status_code, 201, created.content)
        statuses = self.parallel_posts(created["Location"] + "/priority", [
            {"expected_version": 1, "priority": "high"},
            {"expected_version": 1, "priority": "urgent"},
        ], self.headers)
        self.assertEqual(statuses, [200, 409])
        self.assertEqual(Ticket.objects.get().version, 2)
        self.assertEqual(list(AuditEvent.objects.values_list("version", flat=True)), [1, 2])
