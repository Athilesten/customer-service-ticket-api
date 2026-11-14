# API reference

Send `Authorization: Bearer <token>` on versioned routes and `Content-Type: application/json` on writes. Routes omit trailing slashes. Times are UTC. Each response has `X-Request-ID`.

| Method and path | Access | Input or result |
| --- | --- | --- |
| GET /health/live | Public | Process health |
| GET /health/ready | Public | Database and ticket-table availability |
| GET /api/v1/me | All roles | Authenticated actor handle and role |
| POST /api/v1/tickets | All roles | `title` (5–120 characters), `description` (10–5000), optional `priority` and `Idempotency-Key` header |
| GET /api/v1/tickets | All roles | Scoped summaries with filters and pagination |
| GET /api/v1/tickets/{id} | All roles | Scoped details and two SLA clocks |
| POST /api/v1/tickets/{id}/assignment | Manager | `{"assignee":"casey","expected_version":1}` |
| POST /api/v1/tickets/{id}/priority | Manager | `{"priority":"urgent","expected_version":2}` |
| POST /api/v1/tickets/{id}/transition | Assigned agent or manager | `{"status":"in_progress","expected_version":3}` |
| GET /api/v1/tickets/{id}/audit | Manager | Oldest-first events with version, actor, action, changes, and request ID |
| GET /api/v1/metrics/queue | Manager | Backlog, unassigned, urgency, due soon, breached, completed outcomes, and attainment |

Reporters create at normal priority and read their own tickets. Staff see the full queue. Managers assign active agents and can reprioritize unresolved tickets. The lifecycle is `open → in_progress → resolved`, with a manager-only `resolved → open` transition. Starting work requires an assignee. Send the current snapshot's `version` as `expected_version`. After a stale-version conflict, read the latest ticket and review the change before retrying.

Creation returns 201 with a `Location` header. A matching retry returns 200 with the current snapshot and the same location. Keys are case-sensitive, scoped to the creating actor, and support 1–80 letters, digits, dots, underscores, colons or hyphens. A different normalized input under the same key returns 409.

## Queue filters

`q` matches a substring in title or description. Unicode case matching depends on the backend. Filters combine by intersection. Use `priority`, `status`, `assignee`, `assignment=assigned|unassigned`, and `resolution_sla=on_track|due_soon|breached|met|missed`. Use `sort=resolution_due` for earliest resolution deadline first or omit it for newest first. Timestamp ties are resolved using ticket ID.

Lists and audit accept `limit` (default 25, maximum 100) and `offset` (0–100000), and return `items` and `next_offset`. A null offset ends pagination. Concurrent changes can shift rows between requests.

```text
GET /api/v1/tickets?assignment=unassigned&resolution_sla=breached&sort=resolution_due
```

## SLA policy

| Priority | First response | Resolution |
| --- | ---: | ---: |
| Urgent | 1 hour | 4 hours |
| High | 2 hours | 8 hours |
| Normal | 4 hours | 24 hours |
| Low | 8 hours | 72 hours |

Deadlines are calendar hours from creation. The first move to in progress completes first response. Resolving completes resolution. Completion at or before the deadline is `met`, and later completion is `missed`. An open clock becomes `breached` after its deadline. It is `due_soon` within the configured warning window through the deadline and `on_track` earlier.

Reprioritization can tighten incomplete clocks using the original creation time. Reopening uses the existing deadline and preserves the previous resolution in audit history. Attainment is met divided by currently resolved tickets, as a percentage, or null when there are no resolved tickets.

## Errors

Errors follow the shape `{"error":{"code":"version_conflict","message":"Read the current ticket before retrying","request_id":"…"}}`. Validation failures include field and type details.

| Status | Meaning |
| --- | --- |
| 400 | Malformed JSON or invalid request |
| 401 | Missing, disabled, or invalid bearer token |
| 403 | Insufficient permissions |
| 404 | Unknown path or absent/invisible ticket |
| 405 | Unsupported method, with `Allow` |
| 409 | Stale version, invalid transition, no-op, or retry-key conflict |
| 413 / 415 | Body exceeds 32 KiB or unsupported media type |
| 422 | Invalid fields, query, retry key, or assignee |
| 500 / 503 | Unexpected fault or unavailable database operation |
