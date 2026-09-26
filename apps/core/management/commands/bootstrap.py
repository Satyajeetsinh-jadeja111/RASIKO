"""First-run setup for a real shop (safe to run on every deploy).

Creates the Owner account from OWNER_EMAIL / OWNER_PASSWORD if it doesn't exist, makes sure the settings rows exist,
and sends admin emails to the Owner by default. Demo products are NOT added; use `seed_demo` for that.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.core.models import StoreSettings
from apps.delivery.models import DeliverySettings, StoreHours
from apps.notifications.models import NotificationSettings


class Command(BaseCommand):
    help = "Create the Owner account and default settings (idempotent)."

    def handle(self, *args, **opts):
        StoreSettings.load()
        DeliverySettings.load()
        for day in range(7):
            StoreHours.objects.get_or_create(weekday=day)
        ns = NotificationSettings.load()
        email, pw = settings.OWNER_EMAIL, settings.OWNER_PASSWORD
        if email and not ns.admin_recipients:
            ns.admin_recipients = email
            ns.save()
        if email and pw and not User.objects.filter(email=email.lower()).exists():
            User.objects.create_superuser(email=email.lower(), password=pw, first_name="Owner")
            self.stdout.write(
                self.style.SUCCESS(
                    f"Owner account created for {email}. Remove OWNER_PASSWORD from .env "
                    "now; change the password after your first sign in."
                )
            )
        else:
            self.stdout.write("Owner account already exists (or OWNER_EMAIL/OWNER_PASSWORD not set).")
