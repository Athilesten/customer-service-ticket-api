import hashlib
from collections.abc import Mapping
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .errors import APIError
from .models import Actor, AuditEvent, Priority, Role, Status, Ticket
from .schemas import Assignment, Reprioritize, Transition
from .sla import deadlines, resolution_filter

TRANSITIONS = {
    Status.OPEN: {Status.IN_PROGRESS},
    Status.IN_PROGRESS: {Status.RESOLVED},
    Status.RESOLVED: {Status.OPEN},
}
TRACKED_FIELDS = (
    "status", "priority", "assignee_id", "response_due_at", "resolution_due_at",
    "first_response_at", "resolved_at",
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_manager(actor: Actor) -> None:
    if actor.role != Role.MANAGER:
        raise APIError(403, "forbidden", "This operation requires a manager")


def visible_tickets(actor: Actor):
    tickets = Ticket.objects.all()
    if actor.role == Role.REPORTER:
        tickets = tickets.filter(reporter=actor)
    return tickets


def get_ticket(actor: Actor, ticket_id: UUID, *, lock=False) -> Ticket:
    tickets = visible_tickets(actor)
    if lock:
        tickets = tickets.select_for_update()
    else:
        tickets = tickets.select_related("reporter", "assignee")
    try:
        return tickets.get(pk=ticket_id)
    except Ticket.DoesNotExist as exc:
        raise APIError(404, "ticket_not_found", "Ticket not found") from exc


def record_event(ticket, actor, request_id, action, changes):
    AuditEvent.objects.create(
        ticket=ticket, actor=actor, version=ticket.version, action=action,
        occurred_at=ticket.updated_at, request_id=request_id, changes=changes,
    )


@transaction.atomic
def create_ticket(actor, data, key, request_id):
    if actor.role == Role.REPORTER and data.priority != Priority.NORMAL:
        raise APIError(403, "forbidden_priority", "Reporters submit tickets at normal priority")

    fingerprint = digest(data.model_dump_json()) if key else ""
    now = timezone.now()
    response_due, resolution_due = deadlines(now, data.priority)
    values = {
        **data.model_dump(),
        "payload_digest": fingerprint,
        "created_at": now,
        "updated_at": now,
        "response_due_at": response_due,
        "resolution_due_at": resolution_due,
    }
    if key:
        ticket, created = Ticket.objects.get_or_create(reporter=actor, retry_key=key, defaults=values)
        if not created:
            if ticket.payload_digest != fingerprint:
                raise APIError(409, "idempotency_conflict", "Retry key already represents another input")
            return ticket, False
    else:
        ticket = Ticket.objects.create(reporter=actor, **values)

    record_event(ticket, actor, request_id, "created", {
        "status": ticket.status, "priority": ticket.priority,
        "response_due_at": response_due.isoformat(), "resolution_due_at": resolution_due.isoformat(),
    })
    return ticket, True


def assign(ticket, handle):
    if ticket.status == Status.RESOLVED:
        raise APIError(409, "ticket_resolved", "Reopen the ticket before assigning it")
    assignee = Actor.objects.filter(handle=handle, active=True, role=Role.AGENT).first()
    if assignee is None:
        raise APIError(422, "invalid_assignee", "Assignee must be an active agent")
    ticket.assignee = assignee


def reprioritize(ticket, priority):
    if ticket.status == Status.RESOLVED:
        raise APIError(409, "ticket_resolved", "Reopen the ticket before changing priority")
    if ticket.priority == priority:
        return
    ticket.priority = priority
    response_due, resolution_due = deadlines(ticket.created_at, priority)
    if ticket.first_response_at is None:
        ticket.response_due_at = min(ticket.response_due_at, response_due)
    ticket.resolution_due_at = min(ticket.resolution_due_at, resolution_due)


def transition(ticket, target, now):
    if target not in TRANSITIONS[ticket.status]:
        raise APIError(409, "invalid_transition", "The requested status change is not allowed")
    if target == Status.IN_PROGRESS:
        if ticket.assignee_id is None:
            raise APIError(409, "assignment_required", "Assign an agent before starting work")
        if ticket.first_response_at is None:
            ticket.first_response_at = now
    ticket.resolved_at = now if target == Status.RESOLVED else None
    ticket.status = target


def audit_values(ticket, fields):
    values = {}
    for field in fields:
        value = getattr(ticket, field)
        if field == "assignee_id":
            values["assignee"] = ticket.assignee.handle if value else None
        else:
            values[field] = value.isoformat() if hasattr(value, "isoformat") else value
    return values


@transaction.atomic
def update_ticket(actor, ticket_id, command, request_id):
    if isinstance(command, (Assignment, Reprioritize)):
        require_manager(actor)
    ticket = get_ticket(actor, ticket_id, lock=True)
    if isinstance(command, Transition) and actor.role != Role.MANAGER and (
        actor.role != Role.AGENT or actor.id != ticket.assignee_id or command.status == Status.OPEN
    ):
        raise APIError(403, "forbidden", "Only the assigned agent or manager may progress work")
    if command.expected_version != ticket.version:
        raise APIError(409, "version_conflict", "Read the current ticket before retrying")

    now = timezone.now()
    before = audit_values(ticket, TRACKED_FIELDS)
    if isinstance(command, Assignment):
        assign(ticket, command.assignee)
        action = "assigned"
    elif isinstance(command, Reprioritize):
        reprioritize(ticket, command.priority)
        action = "reprioritized"
    else:
        transition(ticket, command.status, now)
        action = "reopened" if ticket.status == Status.OPEN else "status_changed"

    after = audit_values(ticket, TRACKED_FIELDS)
    changes = {
        field: {"from": old_value, "to": after[field]}
        for field, old_value in before.items() if old_value != after[field]
    }
    if not changes:
        raise APIError(409, "no_change", "The command would leave the ticket unchanged")

    ticket.updated_at = now
    ticket.version += 1
    ticket.save(update_fields=[*TRACKED_FIELDS, "updated_at", "version"])
    record_event(ticket, actor, request_id, action, changes)
    return ticket


def search_tickets(actor, filters, now):
    results = visible_tickets(actor).select_related("reporter", "assignee")
    for name in ("status", "priority"):
        value = getattr(filters, name)
        if value is not None:
            results = results.filter(**{name: value})
    if filters.assignee:
        results = results.filter(assignee__handle=filters.assignee)
    if filters.assignment is not None:
        results = results.filter(assignee__isnull=filters.assignment == "unassigned")
    if filters.q:
        results = results.filter(Q(title__icontains=filters.q) | Q(description__icontains=filters.q))
    if filters.resolution_sla:
        results = results.filter(resolution_filter(filters.resolution_sla, now))
    if filters.sort == "resolution_due":
        return results.order_by("resolution_due_at", "-created_at", "-id")
    return results.order_by("-created_at", "-id")


def queue_metrics(actor, now):
    require_manager(actor)
    unresolved = Q(resolved_at__isnull=True)
    counts: Mapping[str, int] = Ticket.objects.aggregate(
        total=Count("id"),
        backlog=Count("id", filter=unresolved),
        unassigned=Count("id", filter=unresolved & Q(assignee__isnull=True)),
        urgent_backlog=Count("id", filter=unresolved & Q(priority=Priority.URGENT)),
        due_soon=Count("id", filter=resolution_filter("due_soon", now)),
        breached=Count("id", filter=resolution_filter("breached", now)),
        met=Count("id", filter=resolution_filter("met", now)),
        missed=Count("id", filter=resolution_filter("missed", now)),
    )
    completed = counts["met"] + counts["missed"]
    return {
        **counts,
        "resolved": completed,
        "attainment_percent": round(100 * counts["met"] / completed, 2) if completed else None,
        "as_of": now,
    }
