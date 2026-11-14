# Customer Service Ticket API

Arrowstack Python Development Internship · Advanced project

Ticket Desk gives a support team one place to receive requests, decide what needs attention, assign an owner, and track progress against service-level agreement (SLA) deadlines. It was built for the service desk lead who needs to answer three questions at shift handoff: which tickets need action, who owns them, and what changed?

For example, a warehouse employee reports that a label printer has stopped. The support lead finds the ticket in the queue, assigns it to an agent, and raises its priority because packing is blocked. The agent starts work and resolves the issue. The employee can track their ticket, and the lead can review the audit trail and see whether first response and resolution met their deadlines. The same workflow fits internal IT support, e-commerce customer service, and facilities teams.

Built with Python 3.11, Django 5.2 and Pydantic 2. SQLite supports quick local review. PostgreSQL supports concurrent writers with row locking.

## Run Ticket Desk with your own data

Clone or download this repository, then open Command Prompt in the folder containing `manage.py`. With Python 3.11 installed, run:

```cmd
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
set "TICKET_DB_BACKEND=sqlite"
set "TICKET_SQLITE_PATH=%CD%\helpdesk.sqlite3"
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Keep that window open and visit [Ticket Desk](http://127.0.0.1:8000/). Open a second Command Prompt in the same project folder and run:

```cmd
set "TICKET_DB_BACKEND=sqlite"
set "TICKET_SQLITE_PATH=%CD%\helpdesk.sqlite3"
.venv\Scripts\python.exe manage.py provision_actor lead manager
.venv\Scripts\python.exe manage.py provision_actor casey agent
.venv\Scripts\python.exe manage.py provision_actor portal reporter
```

Each command prints a token once. Paste the token for the role you want to use into **API bearer token** and click **Connect**. Keep the tokens private. Use the handle `casey` when assigning a ticket.

| Role | What to try |
| --- | --- |
| Reporter | Click **New ticket**, enter a title and description, then search for your ticket by title. |
| Manager | Open the ticket, assign it to `casey`, set its priority to **Urgent**, and review both SLA deadlines. |
| Agent | Open the assigned ticket, click **Start work**, then **Resolve ticket**. |
| Manager | Reconnect, open **Audit history**, and review the sequence of changes and the queue metrics. |

This setup keeps accounts, tickets, and audit events in `helpdesk.sqlite3` between restarts. For a Linux or macOS setup, use `python3.11 -m venv .venv` and `.venv/bin/python` in place of the Windows commands. SQLite and the project’s default database path are used when the database environment variables are unset.

## How it works

The browser sends authenticated requests to the Django API. The API checks what each role can do, validates the input, and saves changes to the database. Ticket versions prevent stale edits from overwriting newer ones. Creation requests can carry a retry key so a network retry can return the same ticket. Each accepted change records its actor, time, and changed fields in the same transaction as the ticket update.

Managers can search for tickets, inspect unassigned or overdue work, and use queue metrics during handoff. In the recorded comparison, the metrics endpoint matched eight counts from a 301-ticket scan using one request instead of 13. The comparison uses synthetic data. A real pilot would measure staff handoff time and SLA attainment. [Validation and evidence](docs/validation.md)

Developers can connect an existing portal or internal tool using the [API reference](docs/api.md). Teams can use the local setup to evaluate the workflow with sample data. For a shared deployment, review the identity, TLS, database access, and retention work in the [production roadmap](docs/design.md#limits-and-production-roadmap).

## Open the browser demo

After installing the dependencies, run this in Command Prompt from the project folder:

```cmd
.venv\Scripts\python.exe scripts\browser_demo.py
```

The command opens [Ticket Desk](http://127.0.0.1:8001/) and loads three sample tickets. Keep CMD open while you use the browser. Create a ticket, assign it to `casey`, then switch **Demo role** to **Agent · Casey** to start or resolve it. Switch back to **Manager · Lead** to view its audit history.

The browser demo sends real requests to the API and stores its data in a temporary local database. Press **Ctrl+C** in CMD to stop the demo and discard those changes. For the regular server, open its root URL and connect with a token from `provision_actor`.

## Run the mentor demo

Open PowerShell in this folder with Python 3.11 installed.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py test --verbosity 2
.\.venv\Scripts\python.exe scripts\demo.py
```

On macOS or Linux, use `python3.11 -m venv .venv` and `.venv/bin/python`. If an interpreter already contains the pinned packages, use it directly.

The demo migrates a temporary SQLite database, provisions synthetic actors and exercises the real HTTP handlers using Django’s test client. It prints a checked walkthrough and before-and-after comparison. See the [mentor demo](docs/demo.md) for the presentation sequence.

## Start and call the API

In one PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

In another terminal in the project directory:

```powershell
$lead = .\.venv\Scripts\python.exe manage.py provision_actor lead manager
$agent = .\.venv\Scripts\python.exe manage.py provision_actor casey agent
$reporter = .\.venv\Scripts\python.exe manage.py provision_actor portal reporter
$base = 'http://127.0.0.1:8000/api/v1'
$headers = @{ Authorization = "Bearer $reporter"; 'Idempotency-Key' = 'warehouse-001' }
$body = @{ title = 'Printer offline'; description = 'Warehouse printer displays a jam code.' } | ConvertTo-Json
$ticket = Invoke-RestMethod "$base/tickets" -Method Post -ContentType application/json -Headers $headers -Body $body
$headers = @{ Authorization = "Bearer $lead" }
$body = @{ expected_version = $ticket.version; assignee = 'casey' } | ConvertTo-Json
Invoke-RestMethod "$base/tickets/$($ticket.id)/assignment" -Method Post -ContentType application/json -Headers $headers -Body $body
Invoke-RestMethod "$base/metrics/queue" -Headers $headers
```

Provision once per handle. Use `--rotate` to replace a token for an existing active actor with the same role. The command prints the new token once and stores only its digest. Keep the development server on loopback and use synthetic data.

## PostgreSQL mode

With a running Docker engine, set a password and start the included database. An existing local PostgreSQL server also works via the corresponding environment variables.

```powershell
$env:TICKET_PG_PASSWORD = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(24))"
docker compose up -d --wait postgres
$env:TICKET_DB_BACKEND = 'postgres'
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py test --noinput --verbosity 2
```

The test account needs database creation privileges on a dedicated test instance. Reuse the original password with an existing Compose volume. Set process environment variables using [.env.example](.env.example) as the reference.

## Submission contents

| Artifact | Contents |
| --- | --- |
| [Requirements](docs/requirements.md) | Stakeholder, scope, and acceptance criteria |
| [API reference](docs/api.md) | Routes, examples, roles, SLA rules, and errors |
| [Implementation notes](docs/design.md) | Architecture, review decisions, trade-offs, and roadmap |
| [Validation](docs/validation.md) | Acceptance matrix and dated test evidence |
| [Mentor demo](docs/demo.md) | Four-minute presentation and viva prompts |
| [Source](tickets/) | Validation, business rules, migrations, and API |
| [Tests](tests/) | HTTP workflow and PostgreSQL concurrency |
