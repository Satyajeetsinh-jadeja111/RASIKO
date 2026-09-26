"""All stock changes go through here, inside transactions with row locks (select_for_update),
so two customers can never buy the last bottle at the same time."""

from datetime import timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.catalog.models import ProductVariant

from .models import StockMovement, StockReservation

RESERVATION_MINUTES = 15


class OutOfStock(Exception):
    def __init__(self, variant, available):
        self.variant = variant
        self.available = available
        super().__init__(f"Only {available} left of {variant}")


def _after_change(variant, before_available, user=None):
    from apps.notifications import services as notify

    after = variant.available_qty
    if before_available > 0 and after <= 0:
        transaction.on_commit(lambda: notify.admin_event("out_of_stock", {"variant": str(variant)}))
    elif after > 0 and after <= variant.low_stock_threshold < before_available:
        transaction.on_commit(lambda: notify.admin_event("low_stock", {"variant": str(variant), "qty": after}))
    if before_available <= 0 < after and not variant.manual_out_of_stock:
        from .tasks import send_back_in_stock

        transaction.on_commit(lambda: send_back_in_stock.delay(variant.pk))


@transaction.atomic
def adjust_stock(variant_id, delta, reason, user=None, note="", order=None, set_to=None):
    v = ProductVariant.objects.select_for_update().get(pk=variant_id)
    before = v.available_qty
    if set_to is not None:
        delta = int(set_to) - v.stock_qty
    new_qty = v.stock_qty + int(delta)
    if new_qty < 0:
        raise OutOfStock(v, v.stock_qty)
    v.stock_qty = new_qty
    v.save(update_fields=["stock_qty", "updated_at"])
    StockMovement.objects.create(
        variant=v, delta=delta, balance_after=new_qty, reason=reason, note=note[:200], user=user, order=order
    )
    _after_change(v, before, user)
    return v


def _locked_variants(lines):
    ids = sorted({line.variant_id for line in lines})
    return {v.pk: v for v in ProductVariant.objects.select_for_update().filter(pk__in=ids).order_by("pk")}


@transaction.atomic
def reserve_for_order(order, minutes=RESERVATION_MINUTES):
    lines = list(order.lines.all())
    variants = _locked_variants(lines)
    expires = timezone.now() + timedelta(minutes=minutes)
    for line in lines:
        v = variants[line.variant_id]
        if not v.in_stock or v.available_qty < line.qty:
            raise OutOfStock(v, v.available_qty if v.in_stock else 0)
    for line in lines:
        v = variants[line.variant_id]
        ProductVariant.objects.filter(pk=v.pk).update(reserved_qty=F("reserved_qty") + line.qty)
        StockReservation.objects.create(variant=v, order=order, qty=line.qty, expires_at=expires)


@transaction.atomic
def commit_reservations(order):
    """Payment succeeded: turn reservations into real stock deductions (idempotent)."""
    reservations = list(
        StockReservation.objects.select_for_update().filter(order=order, released=False, committed=False)
    )
    variants = _locked_variants(reservations)
    for r in reservations:
        v = variants[r.variant_id]
        before = v.available_qty
        v.stock_qty -= r.qty
        v.reserved_qty = max(0, v.reserved_qty - r.qty)
        v.save(update_fields=["stock_qty", "reserved_qty", "updated_at"])
        StockMovement.objects.create(
            variant=v, delta=-r.qty, balance_after=v.stock_qty, reason=StockMovement.Reason.SALE, order=order
        )
        r.committed = True
        r.save(update_fields=["committed"])
        _after_change(v, before)


@transaction.atomic
def release_reservations(order):
    """Payment failed, cancelled or timed out: give the held stock back (idempotent)."""
    reservations = list(
        StockReservation.objects.select_for_update().filter(order=order, released=False, committed=False)
    )
    for r in reservations:
        ProductVariant.objects.filter(pk=r.variant_id).update(reserved_qty=F("reserved_qty") - r.qty)
        r.released = True
        r.save(update_fields=["released"])
    ProductVariant.objects.filter(reserved_qty__lt=0).update(reserved_qty=0)


@transaction.atomic
def deduct_for_cod(order):
    lines = list(order.lines.all())
    variants = _locked_variants(lines)
    for line in lines:
        v = variants[line.variant_id]
        if not v.in_stock or v.available_qty < line.qty:
            raise OutOfStock(v, v.available_qty if v.in_stock else 0)
    for line in lines:
        v = variants[line.variant_id]
        before = v.available_qty
        v.stock_qty -= line.qty
        v.save(update_fields=["stock_qty", "updated_at"])
        StockMovement.objects.create(
            variant=v, delta=-line.qty, balance_after=v.stock_qty, reason=StockMovement.Reason.SALE, order=order
        )
        _after_change(v, before)


def restock_lines(order, qty_by_line: dict, reason, user=None):
    for line, qty in qty_by_line.items():
        if qty > 0:
            adjust_stock(line.variant_id, qty, reason, user=user, note=f"Order {order.number}", order=order)


@transaction.atomic
def expire_reservations():
    from apps.orders.models import Order
    from apps.orders.services import mark_payment_failed

    expired_orders = (
        StockReservation.objects.filter(released=False, committed=False, expires_at__lt=timezone.now())
        .values_list("order_id", flat=True)
        .distinct()
    )
    count = 0
    for order in Order.objects.filter(pk__in=list(expired_orders)):
        mark_payment_failed(order, reason="Payment not completed in time")
        count += 1
    return count
