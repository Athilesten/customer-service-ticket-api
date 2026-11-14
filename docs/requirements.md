# Requirements and acceptance criteria

**Project:** Customer Service Ticket API · Arrowstack Python Development Internship
**Primary stakeholder:** Service desk lead.
**Decision:** Which unassigned or overdue issues to assign or escalate at shift handoff, and who is accountable for the latest change?

| ID | Requirement | Success measure |
| --- | --- | --- |
| R1 | Reporters can submit and track their own tickets. Creation accepts a client retry key. | Concurrent or repeated submissions with the same actor, key, and normalized body produce one ticket and one creation event. A changed body under that key returns a conflict. |
| R2 | Managers assign active agents, change priority, and reopen resolved work. Assigned agents progress work. | Invalid transitions, forbidden changes, and stale versions leave both ticket and audit state intact. |
| R3 | Staff can search by text and filter by status, priority, assignee, and SLA. Reporters search within their own visibility. | Seeded test results match the expected set, including combined filters and page boundaries. |
| R4 | Compute first-response and resolution SLA outcomes in UTC. | Fixtures cover on-time, due soon, breached, met, and missed, including exact deadlines and priority changes. |
| R5 | Record who changed what, when, and under which request ID. | Every accepted mutation commits exactly one matching event in the same transaction. Audit output omits customer message contents. |
| R6 | Provide data for shift handoff and operational review. | A manager can retrieve the backlog, unassigned count, at-risk tickets, and resolution attainment in one metrics request. Compare it with scanning all tickets in a reproducible synthetic exercise. |
| R7 | Run from environment configuration with documented validation and security boundaries. | A mentor can migrate, provision demo credentials, run tests, and replay the demo from the submission. |

## Inputs and outputs

JSON input includes title, description, priority, assignments, lifecycle commands, and the version last read by the client. Bearer tokens identify actors. The API returns ticket snapshots, a paginated queue, audit events, SLA deadline/status pairs, operational counts, and structured errors with request IDs.

## Scope and operating assumptions

One internal service desk, one tenant, three roles, calendar-hour SLAs, text-only intake, and a controlled demonstration using synthetic data. A reporter starts at normal priority. Managers own triage and may authorize a reporter-submitted ticket's escalation. Staff have shared queue visibility, and only the current assignee or a manager can progress work. An explicit move to in progress represents first staff response. Business calendars, attachments, customer notifications, and public account registration are future work.

The business success target for a real pilot is a 50% reduction in median weekly handoff review time versus manual review, with unchanged breach classification accuracy. The submission measures local response latency and API requests in a synthetic comparison. A deployed pilot would be needed to measure staff time and service outcomes.
