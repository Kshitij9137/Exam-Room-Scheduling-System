"""Idempotently create the documented dashboard role groups."""

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the five documented dashboard role groups."

    def handle(self, *args, **options):
        for name in (
            settings.ROLE_LEARNER,
            settings.ROLE_INSTRUCTOR,
            settings.ROLE_ADMINISTRATOR,
            settings.ROLE_SUPPORT,
            settings.ROLE_PLATFORM_ADMIN,
        ):
            group, created = Group.objects.get_or_create(name=name)
            status = "CREATED" if created else "exists"
            self.stdout.write(f"{status:7} {group.name}")
