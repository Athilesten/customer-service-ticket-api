import re
import secrets

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tickets.models import Actor, Role
from tickets.service import digest


class Command(BaseCommand):
    help = "Provision a bearer token or rotate an existing active actor's token."

    def add_arguments(self, parser):
        parser.add_argument("handle")
        parser.add_argument("role", choices=Role.values)
        parser.add_argument("--rotate", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        handle = options["handle"]
        role = options["role"]
        if not re.fullmatch(r"[a-z0-9_-]{1,50}", handle):
            raise CommandError("Use 1–50 lowercase letters, digits, underscores or hyphens.")

        token = secrets.token_urlsafe(32)
        if options["rotate"]:
            updated = Actor.objects.filter(handle=handle, role=role, active=True).update(
                token_digest=digest(token)
            )
            if updated != 1:
                raise CommandError("Rotation requires an existing active actor with this role.")
        else:
            _, created = Actor.objects.get_or_create(
                handle=handle, defaults={"role": role, "token_digest": digest(token)}
            )
            if not created:
                raise CommandError("Handle already exists. Use --rotate for the same active role.")
        self.stdout.write(token)
