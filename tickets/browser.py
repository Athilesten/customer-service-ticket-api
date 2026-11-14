from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.utils.html import json_script
from django.views.decorators.http import require_safe

BROWSER_DIR = Path(__file__).with_name("browser")
ASSETS = {"console.css": "text/css", "console.js": "text/javascript"}


@require_safe
def console(request):
    page = (BROWSER_DIR / "index.html").read_text(encoding="utf-8")
    roles = getattr(settings, "TICKET_BROWSER_DEMO", {})
    response = HttpResponse(page.replace("<!-- DEMO ACTORS -->", json_script(roles, "demo-actors")))
    response["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    response["Referrer-Policy"] = "no-referrer"
    return response


@require_safe
def asset(request, name):
    if name not in ASSETS:
        raise Http404
    return FileResponse((BROWSER_DIR / name).open("rb"), content_type=ASSETS[name])
