# Mentor demonstration

**Audience** Internship mentor and service desk lead
**Duration** About four minutes

Run `python scripts/demo.py` from the project directory or open the [retained demo output](../evidence/2026-11-15/demo.json).

| Time | Show | Explain |
| --- | --- | --- |
| 0:00–0:40 | Handoff problem and roles | A lead needs to find overdue or unassigned tickets, act on them, and see who changed each case. |
| 0:40–1:30 | Create, retry, reporter isolation, assignment, and conflict | A repeated request preserves one ticket. An unrelated reporter cannot read it. A manager acts from a versioned snapshot. |
| 1:30–2:20 | Urgent reprioritization, first response, breach, and resolution | Creation anchors both clocks. Casey responds in time and resolves after the deadline. |
| 2:20–3:00 | Five audit events and matching request ID | Trace creation through resolution and correlate the first write. |
| 3:00–4:00 | Queue metrics, tests, and roadmap | Compare equal counts from the page scan and aggregate. Discuss the PostgreSQL race tests and how a pilot would measure handoff time. |

## Viva prompts

- **Why use both version checks and row locks?** The lock serializes writers. The version shows whether the client reviewed the winning state.
- **How did you verify integrity?** The suite forces audit write failures, races edits and retries, checks reporter isolation, and tests the SLA boundary.
- **Which design decision has the biggest business effect?** Priority and reopen actions preserve the original elapsed time. Leads can see the impact of a late escalation and audit who made it.
- **What would change at 10×?** Profile search, pagination and metrics on PostgreSQL under representative data and traffic. Add identity integration and retention controls during deployment preparation.
