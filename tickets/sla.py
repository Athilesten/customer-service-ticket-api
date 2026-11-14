from datetime import timedelta

from django.conf import settings
from django.db.models import F, Q


def deadlines(created_at, priority):
    response, resolution = settings.SLA_HOURS[priority]
    return created_at + timedelta(hours=response), created_at + timedelta(hours=resolution)


def warning_end(now):
    return now + timedelta(minutes=settings.SLA_WARNING_MINUTES)


def clock_status(due, completed, now):
    if completed is not None:
        return "met" if completed <= due else "missed"
    if now > due:
        return "breached"
    if due <= warning_end(now):
        return "due_soon"
    return "on_track"


def resolution_filter(state, now):
    open_clock = Q(resolved_at__isnull=True)
    if state == "on_track":
        return open_clock & Q(resolution_due_at__gt=warning_end(now))
    if state == "due_soon":
        return open_clock & Q(resolution_due_at__range=(now, warning_end(now)))
    if state == "breached":
        return open_clock & Q(resolution_due_at__lt=now)
    if state == "met":
        return Q(resolved_at__lte=F("resolution_due_at"))
    return Q(resolved_at__gt=F("resolution_due_at"))
