"""Expiry-aware free stock. Reservations allocate batches before payment capture."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import ProductVariant
from apps.core import audit
from apps.inventory.models import StockMovement
from apps.inventory.services import OutOfStock, adjust_stock

from .access import require_team
from .models import BatchAllocation, StockBatch


@transaction.atomic
def receive(actor, variant, code, expires_on, quantity, *, opening=False):
    v = ProductVariant.objects.select_for_update(of=("self",)).select_related("product__seller_team").get(pk=variant.pk)
    require_team(actor, v.product.seller_team)
    if quantity <= 0 or expires_on < timezone.localdate() or not code.strip():
        raise ValidationError("Provide a batch code, a future expiry and positive bottle quantity.")
    if v.reserved_qty:
        raise ValidationError("Resolve unpaid stock reservations before changing batch configuration.")
    if not v.batch_tracking and v.stock_qty:
        if not opening or quantity != v.stock_qty or v.batches.exists():
            raise ValidationError("Allocate all existing bottles to an opening batch before receiving more stock.")
    elif opening:
        raise ValidationError("Opening stock has already been configured.")
    batch = StockBatch(variant=v, code=code.strip(), expires_on=expires_on, remaining=quantity)
    batch.full_clean()
    batch.save()
    v.batch_tracking = True
    v.save(update_fields=["batch_tracking", "updated_at"])
    if not opening:
        adjust_stock(v.pk, quantity, StockMovement.Reason.INITIAL, user=actor, note=f"Batch {code}")
    audit.log(None, "marketplace.batch.received", batch, summary=f"{quantity} bottles", user=actor)
    return batch


def allocate_order(order):
    for line in order.lines.select_related("variant").order_by("variant_id", "pk"):
        v = line.variant
        if not v.batch_tracking or line.batch_allocations.exists():
            continue
        needed = line.qty * line.units_per_box
        batches = list(
            StockBatch.objects.select_for_update(of=("self",))
            .filter(variant=v, active=True, expires_on__gte=timezone.localdate(), remaining__gt=0)
            .order_by("expires_on", "pk")
        )
        if sum(b.remaining for b in batches) < needed:
            raise OutOfStock(v, sum(b.remaining for b in batches) // line.units_per_box)
        for batch in batches:
            quantity = min(needed, batch.remaining)
            batch.remaining -= quantity
            batch.save(update_fields=["remaining", "updated_at"])
            BatchAllocation.objects.create(order_line=line, batch=batch, quantity=quantity)
            needed -= quantity
            if not needed:
                break


def restore_line(line, bottles):
    for allocation in (
        BatchAllocation.objects.select_for_update(of=("self",))
        .filter(order_line=line)
        .select_related("batch")
        .order_by("pk")
    ):
        count = min(bottles, allocation.quantity - allocation.restored)
        if count:
            batch = StockBatch.objects.select_for_update(of=("self",)).get(pk=allocation.batch_id)
            batch.remaining += count
            batch.save(update_fields=["remaining", "updated_at"])
            allocation.restored += count
            allocation.save(update_fields=["restored"])
            bottles -= count
        if not bottles:
            break


@transaction.atomic
def quarantine(actor, batch, reason):
    v = ProductVariant.objects.select_for_update(of=("self",)).get(pk=batch.variant_id)
    require_team(actor, v.product.seller_team)
    batch = StockBatch.objects.select_for_update(of=("self",)).get(pk=batch.pk)
    if not reason.strip():
        raise ValidationError("A quarantine reason is required.")
    if v.reserved_qty:
        raise ValidationError("Resolve reservations before quarantining stock.")
    if not batch.active:
        return
    adjust_stock(v.pk, -batch.remaining, StockMovement.Reason.DAMAGE, user=actor, note=reason)
    batch.remaining, batch.active = 0, False
    batch.save()
    audit.log(None, "marketplace.batch.quarantined", batch, summary=reason, user=actor)


def free_bottles(variant):
    return (
        variant.batches.filter(active=True, expires_on__gte=timezone.localdate()).aggregate(n=Sum("remaining"))["n"]
        or 0
    )
