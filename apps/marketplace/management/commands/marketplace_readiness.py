"""Read-only deployment gates. Never contacts a provider or prints integration secrets."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.core.integrations import get_config
from apps.marketplace.models import MarketplaceOperations, MarketplaceSettings, Seller, Territory


class Command(BaseCommand):
    help = "Report marketplace release prerequisites without enabling features or contacting providers."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true")

    def handle(self, *args, **options):
        cfg = MarketplaceSettings.objects.first() or MarketplaceSettings()
        operations = MarketplaceOperations.objects.first() or MarketplaceOperations()
        checks = {
            "route_approved": bool(getattr(settings, "MARKETPLACE_ROUTE_APPROVED", False)),
            "razorpay_configured": bool(get_config("razorpay", allow_disabled=True)),
            "translation_configured": bool(get_config("google_translate")),
            "seller_profiles_complete": not Seller.objects.filter(status="active")
            .filter(Q(legal_name="") | Q(business_address="") | Q(state_code="") | Q(signatory=""))
            .exists(),
            "territory_state_codes_complete": not Territory.objects.filter(state_code="").exists(),
            "grievance_contact_configured": bool(operations.grievance_name and operations.grievance_email),
            "privacy_and_terms_configured": bool(operations.privacy_notice and operations.seller_terms),
        }
        self.stdout.write(
            json.dumps(
                {
                    "enabled": cfg.enabled,
                    "checks": checks,
                    "device_tests": "Must be recorded separately on physical Android/iPhone devices.",
                },
                indent=2,
            )
        )
        if options["strict"] and not all(checks.values()):
            raise CommandError("Release prerequisites are incomplete; no settings were changed.")
