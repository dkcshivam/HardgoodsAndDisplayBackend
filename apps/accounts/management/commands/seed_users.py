"""
One login per role for trying the app, all with the same published password.
Safe to re-run: it puts the three back as they were, and touches no one else.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role

PASSWORD = "demo-pass-123"

# Not "admin": that is the name most people give their own superuser.
USERS = [
    ("demo-admin", "Asha", "Rao", Role.ADMIN),
    ("demo-senior", "Vikram", "Mehta", Role.SENIOR_MERCHANT),
    ("demo-merchant", "Ravi", "Kumar", Role.MERCHANT),
]


class Command(BaseCommand):
    help = "Create or reset one demo user per role."

    @transaction.atomic
    def handle(self, *args, **options):
        # The password is in the repository: on a server it would be a way in.
        if not settings.DEBUG:
            raise CommandError("Demo users are for development; DEBUG is off.")

        for username, first_name, last_name, role in USERS:
            user, _ = get_user_model().objects.get_or_create(username=username)
            user.first_name = first_name
            user.last_name = last_name
            user.email = f"{username}@example.com"
            user.is_active = True
            user.set_password(PASSWORD)
            user.save()
            user.profile.role = role
            user.profile.save()
            self.stdout.write(f"  {username:<14} {role.label}")

        self.stdout.write(self.style.SUCCESS(f"Password for each: {PASSWORD}"))
