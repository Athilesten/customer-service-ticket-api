import uuid

from django.db import models


class Role(models.TextChoices):
    REPORTER = "reporter", "Reporter"
    AGENT = "agent", "Agent"
    MANAGER = "manager", "Manager"


class Priority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class Status(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In progress"
    RESOLVED = "resolved", "Resolved"


class Actor(models.Model):
    handle = models.SlugField(max_length=50, unique=True)
    role = models.CharField(max_length=12, choices=Role)
    token_digest = models.CharField(max_length=64, unique=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(role__in=Role.values),
                                              name="actor_known_role")]


class Ticket(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=120)
    description = models.TextField()
    priority = models.CharField(max_length=8, choices=Priority)
    status = models.CharField(max_length=14, choices=Status, default=Status.OPEN)
    reporter = models.ForeignKey(Actor, on_delete=models.PROTECT, related_name="reported")
    assignee = models.ForeignKey(Actor, null=True, on_delete=models.PROTECT, related_name="assigned")
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    response_due_at = models.DateTimeField()
    resolution_due_at = models.DateTimeField()
    first_response_at = models.DateTimeField(null=True)
    resolved_at = models.DateTimeField(null=True)
    retry_key = models.CharField(max_length=80, null=True)
    payload_digest = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["reporter", "retry_key"], name="ticket_reporter_retry"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="ticket_version_positive"),
            models.CheckConstraint(condition=models.Q(priority__in=Priority.values),
                                   name="ticket_known_priority"),
            models.CheckConstraint(
                condition=(
                    models.Q(status=Status.OPEN, resolved_at__isnull=True)
                    | models.Q(status=Status.IN_PROGRESS, assignee__isnull=False,
                               first_response_at__isnull=False, resolved_at__isnull=True)
                    | models.Q(status=Status.RESOLVED, assignee__isnull=False,
                               first_response_at__isnull=False, resolved_at__isnull=False)
                ),
                name="ticket_valid_state",
            ),
        ]
        indexes = [
            models.Index(fields=["-created_at", "-id"], name="ticket_queue_order"),
            models.Index(fields=["status", "resolution_due_at"], name="ticket_resolution_queue"),
        ]


class AuditEvent(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(Actor, on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=20)
    occurred_at = models.DateTimeField()
    request_id = models.UUIDField()
    changes = models.JSONField()

    class Meta:
        ordering = ["version"]
        constraints = [models.UniqueConstraint(fields=["ticket", "version"],
                                               name="audit_ticket_version")]
