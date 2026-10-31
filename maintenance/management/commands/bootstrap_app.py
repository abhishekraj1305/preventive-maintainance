import os
from django.contrib.auth.password_validation import validate_password
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
from maintenance.models import User


class Command(BaseCommand):
    help = "Create the initial administrator from environment variables; never overwrite an existing account."

    def handle(self, *args, **options):
        if User.objects.filter(is_superuser=True, is_active=True).exists():
            self.stdout.write("Administrator already configured; existing accounts unchanged.")
            return
        username = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "").strip()
        password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
        if not username:
            if User.objects.filter(is_superuser=True, is_active=True).exists():
                self.stdout.write("Administrator already configured.")
                return
            raise CommandError("Set BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD for first startup.")
        if User.objects.filter(username=username).exists():
            if not User.objects.filter(username=username, is_superuser=True, is_active=True).exists():
                raise CommandError(
                    "Bootstrap username already belongs to a non-admin or inactive account. Choose another ID."
                )
            self.stdout.write("Administrator already configured; credentials unchanged.")
            return
        if not password:
            raise CommandError("BOOTSTRAP_ADMIN_PASSWORD is required for a new administrator.")
        try:
            validate_password(password, User(username=username))
        except ValidationError as exc:
            raise CommandError("Initial password does not meet the password requirements.") from exc
        with transaction.atomic():
            User.objects.create_superuser(username=username, password=password, must_change_password=True)
        self.stdout.write("Administrator created. A password change is required at first login.")
