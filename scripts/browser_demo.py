"""Open the live ticket console in a browser using a temporary local database."""

import argparse
import os
import sys
import webbrowser
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
from wsgiref.simple_server import WSGIRequestHandler, make_server

BASE_DIR = Path(__file__).resolve().parent.parent


class QuietRequests(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        pass


def seed_demo():
    from django.core.management import call_command
    from django.utils import timezone

    from tickets.models import Actor, Role
    from tickets.schemas import Assignment, TicketCreate, Transition
    from tickets.service import create_ticket, update_ticket

    accounts = {}
    for role, handle in (("manager", "lead"), ("agent", "casey"), ("reporter", "portal")):
        output = StringIO()
        call_command("provision_actor", handle, role, stdout=output)
        accounts[role] = {"handle": handle, "token": output.getvalue().strip()}
    reporter = Actor.objects.get(role=Role.REPORTER)
    lead = Actor.objects.get(role=Role.MANAGER)
    agent = Actor.objects.get(role=Role.AGENT)
    now = timezone.now()
    samples = [
        ("Warehouse label printer offline", "The packing station printer shows a jam code.", 3, "open"),
        ("Invoice export shows blank rows", "The billing export omits three invoice lines.", 25, "active"),
        ("Account confirmation email delayed", "The confirmation arrived after a second request.", 6, "resolved"),
    ]
    for title, description, age, state in samples:
        with patch("django.utils.timezone.now", return_value=now - timedelta(hours=age)):
            ticket, _ = create_ticket(reporter, TicketCreate(title=title, description=description), None, uuid4())
            if state != "open":
                update_ticket(lead, ticket.id, Assignment(assignee="casey", expected_version=1), uuid4())
                update_ticket(agent, ticket.id, Transition(status="in_progress", expected_version=2), uuid4())
                if state == "resolved":
                    update_ticket(agent, ticket.id, Transition(status="resolved", expected_version=3), uuid4())
    return accounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--no-browser", action="store_true")
    options = parser.parse_args()
    sys.path.insert(0, str(BASE_DIR))
    with TemporaryDirectory(prefix=".demo-", dir=BASE_DIR) as folder:
        os.environ.update({
            "DJANGO_SETTINGS_MODULE": "helpdesk.settings",
            "TICKET_DB_BACKEND": "sqlite",
            "TICKET_SQLITE_PATH": str(Path(folder) / "browser.sqlite3"),
            "TICKET_ALLOWED_HOSTS": "127.0.0.1",
            "TICKET_LOG_LEVEL": "WARNING",
        })
        from django.conf import settings
        from django.core.management import call_command
        from django.core.wsgi import get_wsgi_application
        from django.db import connections

        application = get_wsgi_application()
        try:
            call_command("migrate", verbosity=0)
            settings.TICKET_BROWSER_DEMO = seed_demo()
            with make_server("127.0.0.1", options.port, application, handler_class=QuietRequests) as server:
                url = f"http://127.0.0.1:{server.server_port}/"
                print(f"Ticket console: {url}", flush=True)
                print("Press Ctrl+C to stop the demo.", flush=True)
                if not options.no_browser:
                    webbrowser.open(url)
                server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            connections.close_all()


if __name__ == "__main__":
    main()
