"""Bounded operational scans and retention; financial and audit records are never purged."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    DeliveryAssignment,
    Fulfillment,
    MarketplaceOperations,
    OnboardingOperation,
    OperationalAlert,
    RiderAccount,
    RiderEvent,
    RiderInvitation,
    RiderToken,
    Settlement,
    StockBatch,
    TransferReversal,
)


def scan():
    now = timezone.now()
    active_keys = set()

    def alert(kind, identifier, fulfillment=None):
        key = f"{kind}:{identifier}"
        active_keys.add(key)
        OperationalAlert.objects.update_or_create(
            key=key, defaults={"kind": kind, "fulfillment": fulfillment, "resolved_at": None}
        )

    for f in Fulfillment.objects.filter(status="ready", ready_at__lt=now - timedelta(minutes=3)).iterator(
        chunk_size=500
    ):
        alert("unassigned_delivery", f.pk, f)
    for assignment in (
        DeliveryAssignment.objects.filter(active=True).select_related("fulfillment", "rider").iterator(chunk_size=500)
    ):
        if not assignment.rider.last_seen or assignment.rider.last_seen < now - timedelta(seconds=90):
            alert("stale_rider", assignment.pk, assignment.fulfillment)
    for row in Settlement.objects.filter(disputed=True).iterator(chunk_size=500):
        alert("settlement_dispute", row.pk, row.fulfillment)
    for row in TransferReversal.objects.filter(status="uncertain").iterator(chunk_size=500):
        alert("reversal_uncertain", row.pk, row.settlement.fulfillment)
    for row in OnboardingOperation.objects.filter(status="uncertain").iterator(chunk_size=500):
        alert("onboarding_uncertain", row.pk)
    for batch in StockBatch.objects.filter(
        active=True, remaining__gt=0, expires_on__lte=timezone.localdate() + timedelta(days=7)
    ).iterator(chunk_size=500):
        alert("expiring_batch", batch.pk)
    OperationalAlert.objects.filter(resolved_at=None).exclude(kind="failed_job").exclude(key__in=active_keys).update(
        resolved_at=now
    )
    return len(active_keys)


@transaction.atomic
def retain():
    settings = MarketplaceOperations.load()
    now = timezone.now()
    # Presence and precise coordinates are transient; immutable delivery events omit coordinates.
    RiderAccount.objects.filter(last_seen__lt=now - timedelta(days=settings.location_retention_days)).update(
        lat=None, lng=None, location_consent=False, online=False
    )
    removed, _ = RiderEvent.objects.filter(
        kind__in=["online", "offline"], created_at__lt=now - timedelta(days=settings.activity_retention_days)
    ).delete()
    RiderToken.objects.filter(expires_at__lt=now).delete()
    RiderInvitation.objects.filter(accepted_at=None, expires_at__lt=now - timedelta(days=7)).delete()
    return removed
