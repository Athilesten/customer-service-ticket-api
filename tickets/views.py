from datetime import datetime

from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone

from . import service
from .http import endpoint, read_body, read_query, retry_key
from .models import Role, Ticket
from .schemas import Assignment, Page, Reprioritize, Search, TicketCreate, Transition
from .sla import clock_status


class APIEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, datetime):
            return value.isoformat().replace("+00:00", "Z")
        return super().default(value)


def json_response(data, **kwargs):
    return JsonResponse(data, encoder=APIEncoder, **kwargs)


def clock(due, completed, now):
    return {"due_at": due, "completed_at": completed, "status": clock_status(due, completed, now)}


def ticket_data(ticket, actor, now, *, include_description=True):
    response = {
        "id": ticket.id,
        "title": ticket.title,
        "priority": ticket.priority,
        "status": ticket.status,
        "assignee": ticket.assignee.handle if ticket.assignee_id else None,
        "version": ticket.version,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
        "sla": {
            "first_response": clock(ticket.response_due_at, ticket.first_response_at, now),
            "resolution": clock(ticket.resolution_due_at, ticket.resolved_at, now),
        },
    }
    if actor.role != Role.REPORTER:
        response["reporter"] = ticket.reporter.handle
    if include_description:
        response["description"] = ticket.description
    return response


def page_data(queryset, page, serialize):
    rows = list(queryset[page.offset:page.offset + page.limit + 1])
    return json_response({
        "items": [serialize(item) for item in rows[:page.limit]],
        "next_offset": page.offset + page.limit if len(rows) > page.limit else None,
    })


@endpoint(get=False)
def live(request, actor):
    return json_response({"status": "ok"})


@endpoint(get=False)
def ready(request, actor):
    Ticket.objects.exists()
    return json_response({"status": "ready"})


@endpoint(get=True, post=True)
def tickets(request, actor):
    if request.method == "POST":
        command = read_body(request, TicketCreate)
        ticket, created = service.create_ticket(actor, command, retry_key(request), request.request_id)
        response = json_response(ticket_data(ticket, actor, timezone.now()), status=201 if created else 200)
        response["Location"] = reverse("ticket-detail", kwargs={"ticket_id": ticket.id})
        return response
    filters = read_query(request, Search)
    now = timezone.now()
    return page_data(service.search_tickets(actor, filters, now), filters,
                     lambda ticket: ticket_data(ticket, actor, now, include_description=False))


@endpoint(get=True)
def identity(request, actor):
    return json_response({"handle": actor.handle, "role": actor.role})


@endpoint(get=True)
def ticket_detail(request, actor, ticket_id):
    ticket = service.get_ticket(actor, ticket_id)
    return json_response(ticket_data(ticket, actor, timezone.now()))


def mutation(schema):
    @endpoint(post=True)
    def execute(request, actor, ticket_id):
        command = read_body(request, schema)
        ticket = service.update_ticket(actor, ticket_id, command, request.request_id)
        return json_response(ticket_data(ticket, actor, timezone.now()))

    return execute


assign = mutation(Assignment)
reprioritize = mutation(Reprioritize)
transition = mutation(Transition)


@endpoint(get=True)
def audit(request, actor, ticket_id):
    service.require_manager(actor)
    page = read_query(request, Page)
    ticket = service.get_ticket(actor, ticket_id)
    return page_data(ticket.events.select_related("actor"), page, lambda event: {
        "version": event.version,
        "action": event.action,
        "actor": event.actor.handle,
        "occurred_at": event.occurred_at,
        "request_id": event.request_id,
        "changes": event.changes,
    })


@endpoint(get=True)
def metrics(request, actor):
    return json_response(service.queue_metrics(actor, timezone.now()))
