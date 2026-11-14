# Validation and acceptance review

Evidence captured on 15 November 2026 using Python 3.11, Django 5.2.14, Pydantic 2.13.4, SQLite 3.45.1 and native PostgreSQL 18.4 on Windows. Compose and CI are supplied as reproducible configurations for PostgreSQL 17. The recorded database tests ran on the native instance.

| Requirement | Evidence |
| --- | --- |
| R1 · Creation and retries | Normalized retry and cross-actor checks; simultaneous PostgreSQL submissions yield one ticket and one audit event. |
| R2 · Assignment and workflow | Role, inactivity, lifecycle, stale version and no-change checks; concurrent PostgreSQL edits yield one success and one conflict. |
| R3 · Search | Combined filter results, literal wildcard search, timestamp tie pagination, reporter visibility, and unassigned deadline sort. |
| R4 · SLA | Fixed UTC time for all five states, exact-deadline completion, escalation, downgrade, and reopen behavior. |
| R5 · Audit integrity | Versioned history, actor, request ID and before/after values. Forced audit failures roll back creation and assignment. |
| R6 · Operations and comparison | Health checks, queue aggregation and synthetic before-and-after comparison. |
| R7 · Reproducibility | README commands, migration, environment example, CI matrix, and rerunnable demo. |

- [SQLite output](../evidence/2026-11-15/sqlite-tests.txt) · 14 passed, 2 PostgreSQL concurrency cases skipped.
- [PostgreSQL output](../evidence/2026-11-15/postgres-tests.txt) · all 16 passed, including both race tests.
- [Demo output](../evidence/2026-11-15/demo.json) · complete workflow and measured comparison.
- [Project checks](../evidence/2026-11-15/project-checks.txt) · framework configuration and migration consistency.

- [Loopback HTTP smoke test](../evidence/2026-11-15/http-smoke.txt) · migrated a fresh database and verified readiness, creation, assignment, metrics, and audit over the running server.

## Handoff measurement

For 301 synthetic tickets and 20 repetitions, the page-scan client fetched 25 tickets per request and computed eight counts independently from timestamps. The aggregate returned the same eight counts in every repetition using one request instead of 13, a 92.31% reduction in API requests. Median local time was 80.57 ms for the page scan and 6.14 ms for the aggregate. P95 was 144.08 ms and 10.09 ms, respectively.

Timings use an in-process HTTP test client and a temporary SQLite file. They describe this dataset and host. Staff handoff time, deployment capacity, and actual SLA improvement require a pilot.
