"""Order lifecycle. Every state change happens inside a transaction with the order row locked."""

import logging
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.models import Product
from apps.core.models import StoreSettings
from apps.delivery.models import DeliverySettings
from apps.delivery.services import delivery_cost, money
from apps.inventory import services as stock
from apps.inventory.models import StockMovement
from apps.notifications import services as notify
from apps.promotions.models import CoinLedger, CouponRedemption
from apps.promotions.services import award_order_coins, refund_used_coins, reverse_order_coins

from .models import Order, OrderEvent, OrderLine
from .pricing import price_cart

logger = logging.getLogger(__name__)
ZERO = Decimal("0")
S = Order.Status

ALLOWED = {
    S.PENDING_PAYMENT: {S.PLACED, S.PAYMENT_FAILED, S.CANCELLED},
    S.PLACED: {S.CONFIRMED, S.PACKED, S.CANCELLED},
    S.CONFIRMED: {S.PACKED, S.OUT_FOR_DELIVERY, S.CANCELLED},
    S.PACKED: {S.OUT_FOR_DELIVERY, S.CANCELLED},
    S.OUT_FOR_DELIVERY: {S.DELIVERED, S.CANCELLED},
    S.DELIVERED: {S.REFUNDED},
    S.PAYMENT_FAILED: {S.PLACED},  # a late successful payment can revive it
    S.CANCELLED: {S.REFUNDED},
    S.REFUNDED: set(),
}


class CheckoutError(Exception):
    pass


def payment_methods_for(user, total, pincode_obj=None):
    """[(value, label, available, reason)] shown at checkout; enforced again in place_order."""
    store = StoreSettings.load()
    dcfg = DeliverySettings.load()
    methods = []
    from apps.payments.gateways import online_gateway

    gw = online_gateway()
    if gw:
        methods.append((gw, Order.PaymentMethod(gw).label, True, ""))
    reason = ""
    if not store.cod_enabled:
        reason = _("Cash on Delivery is not available right now.")
    elif user.cod_blocked or (pincode_obj and pincode_obj.cod_blocked):
        reason = _("Cash on Delivery is not available for this account or area.")
    elif total > dcfg.cod_limit:
        reason = _("Cash on Delivery is available up to ₹%(v)s.") % {"v": dcfg.cod_limit}
    methods.append(("cod", Order.PaymentMethod.COD.label, not reason, reason))
    return methods


def _expand_lines(cart):
    """Yield (variant, qty, unit_price, unit_mrp, combo_name). Combos are split across their items."""
    for line in cart.lines():
        if line.kind == "v":
            yield line.obj, line.qty, line.unit_price, line.unit_mrp, ""
            continue
        combo = line.obj
        items = list(combo.items.select_related("variant__product"))
        regular = sum((i.variant.price * i.qty for i in items), ZERO) or Decimal("1")
        remaining = combo.price
        for n, item in enumerate(items):
            if n == len(items) - 1:
                share = remaining
            else:
                share = (combo.price * item.variant.price * item.qty / regular).quantize(Decimal("0.01"))
                remaining -= share
            unit = (share / item.qty).quantize(Decimal("0.01"), ROUND_HALF_UP)
            yield item.variant, item.qty * line.qty, unit, item.variant.mrp, combo.name


def _event(order, status, by=None, note=""):
    OrderEvent.objects.create(order=order, status=status, by=by, note=note[:300])


@transaction.atomic
def place_order(
    *,
    user,
    cart,
    address,
    payment_method,
    checkout_token,
    slot="asap",
    coupon_code="",
    use_coins=False,
    note="",
    source="web",
):
    existing = Order.objects.filter(checkout_token=checkout_token, user=user).first()
    if existing:
        return existing
    totals = price_cart(cart, user, coupon_code, use_coins, (address.lat, address.lng, address.pincode))
    if not totals.ok:
        raise CheckoutError(" ".join(totals.problems) or totals.delivery.message)
    if coupon_code and totals.coupon_error:
        raise CheckoutError(totals.coupon_error)
    from apps.delivery.models import ServicePincode

    pin = ServicePincode.objects.filter(code=address.pincode).first()
    allowed = {m[0]: m for m in payment_methods_for(user, totals.total, pin)}
    if payment_method not in allowed or not allowed[payment_method][2]:
        raise CheckoutError(allowed.get(payment_method, (0, 0, 0, _("Choose a payment method.")))[3])
    if payment_method == "cod" and not user.phone_verified:
        raise CheckoutError(_("Please verify your mobile number before your first Cash on Delivery order."))

    is_asap, slot_start, slot_label = True, None, _("ASAP %(eta)s") % {"eta": totals.delivery.eta_text}
    if slot and slot != "asap":
        from apps.delivery.services import available_slots

        slots = dict(available_slots())
        if slot not in slots:
            raise CheckoutError(_("That delivery slot is no longer available."))
        is_asap = False
        slot_start = timezone.make_aware(datetime.strptime(slot, "%Y-%m-%dT%H:%M"))
        slot_label = slots[slot]

    d = totals.delivery
    order = Order.objects.create(
        user=user,
        payment_method=payment_method,
        checkout_token=checkout_token,
        ship_name=address.name,
        ship_phone=address.phone,
        ship_address=address.as_text(),
        ship_pincode=address.pincode,
        ship_area=pin.area if pin else "",
        ship_lat=address.lat,
        ship_lng=address.lng,
        road_km=d.road_km,
        is_asap=is_asap,
        slot_start=slot_start,
        slot_label=slot_label,
        fast_promise=d.fast and is_asap,
        mrp_total=totals.mrp_total,
        subtotal=totals.subtotal,
        coupon=totals.coupon,
        coupon_code=totals.coupon_code,
        discount=totals.discount,
        coins_used=totals.coins_used,
        coins_value=totals.coins_value,
        delivery_fee=d.delivery_fee,
        small_order_fee=d.small_order_fee,
        surcharge_total=d.surcharge_total,
        surcharges=[[str(label), str(amount)] for label, amount in d.surcharges],
        total=totals.total,
        delivery_cost=delivery_cost(d.road_km),
        customer_note=note[:300],
        source=source,
    )
    gst = ZERO
    for variant, qty, unit, mrp, combo_name in _expand_lines(cart):
        line = OrderLine.objects.create(
            order=order,
            variant=variant,
            product_name=variant.product.name,
            variant_label=str(variant.box_label)[:40],
            units_per_box=variant.units_per_box,
            sku=variant.sku,
            hsn_code=variant.hsn_code,
            gst_rate=variant.gst_rate,
            qty=qty,
            unit_mrp=mrp,
            unit_price=unit,
            unit_cost=variant.cost_price,
            line_total=unit * qty,
            combo_name=combo_name,
        )
        gst += line.gst_amount
    ratio = (totals.subtotal - totals.discount - totals.coins_value) / totals.subtotal if totals.subtotal else 0
    order.gst_total = money(gst * Decimal(ratio))
    order.save(update_fields=["gst_total"])

    if totals.coupon:
        CouponRedemption.objects.create(coupon=totals.coupon, user=user, order=order, amount=totals.discount)
    if totals.coins_used:
        CoinLedger.objects.create(user=user, delta=-totals.coins_used, reason=CoinLedger.Reason.REDEEMED, order=order)

    try:
        if payment_method == "cod":
            stock.deduct_for_cod(order)
        else:
            stock.reserve_for_order(order)
    except stock.OutOfStock as exc:
        raise CheckoutError(
            _("Sorry, only %(n)s boxes left of %(item)s. Please update your cart.")
            % {"n": exc.available, "item": exc.variant}
        ) from exc

    if payment_method == "cod":
        _confirm_placed(order, Order.PaymentStatus.COD_DUE)
    else:
        _event(order, S.PENDING_PAYMENT)
    return order


def _confirm_placed(order, payment_status):
    order.status = S.PLACED
    order.payment_status = payment_status
    order.placed_at = timezone.now()
    order.save(update_fields=["status", "payment_status", "placed_at", "updated_at"])
    _event(order, S.PLACED)
    notify.order_status_changed(order)
    notify.admin_event(
        "new_order",
        {
            "order": order.number,
            "total": f"₹{order.total}",
            "area": order.ship_area,
            "payment": order.get_payment_method_display(),
        },
    )
    transaction.on_commit(lambda: _broadcast_new_order(order.pk))


def _broadcast_new_order(order_id):
    """Live new-order alert in the dashboard (sound + banner)."""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer:
            async_to_sync(layer.group_send)("dashboard", {"type": "new.order", "order_id": order_id})
    except Exception:  # noqa: BLE001 - alerts are best effort
        logger.warning("Could not broadcast new order alert", exc_info=True)


@transaction.atomic
def mark_paid(order, payment=None):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.payment_status == Order.PaymentStatus.PAID:
        return order  # idempotent (webhook + redirect both arrive)
    if order.status == S.PENDING_PAYMENT:
        stock.commit_reservations(order)
    elif order.status in (S.PAYMENT_FAILED, S.CANCELLED):
        order.payment_status = Order.PaymentStatus.PAID
        order.staff_note += "\nPayment received after cancellation/timeout: refund required; do not fulfill."
        order.save(update_fields=["payment_status", "staff_note"])
        notify.admin_event("payment_succeeded", {"order": order.number, "warning": "Late payment requires refund"})
        return order
    else:
        return order
    notify.admin_event("payment_succeeded", {"order": order.number, "amount": f"₹{order.total}"})
    notify.customer_email(
        order.user.email,
        "payment_received",
        {"order": order, "subject_vars": {"number": order.number}},
        event_key="payment_received",
    )
    _confirm_placed(order, Order.PaymentStatus.PAID)
    return order


@transaction.atomic
def mark_payment_failed(order, reason=""):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != S.PENDING_PAYMENT:
        return order
    stock.release_reservations(order)
    order.status = S.PAYMENT_FAILED
    order.payment_status = Order.PaymentStatus.FAILED
    order.save(update_fields=["status", "payment_status", "updated_at"])
    _event(order, S.PAYMENT_FAILED, note=reason)
    refund_used_coins(order)
    CouponRedemption.objects.filter(order=order).delete()
    notify.order_status_changed(order)
    notify.admin_event("payment_failed", {"order": order.number, "reason": reason})
    return order


@transaction.atomic
def set_status(order, new_status, by=None, note="", rider=None):
    order = Order.objects.select_for_update().get(pk=order.pk)
    new_status = S(new_status)
    if new_status == order.status:
        return order
    if new_status not in ALLOWED.get(order.status, set()):
        raise ValueError(f"Cannot move order from {order.get_status_display()} to {new_status.label}")
    fields = ["status", "updated_at"]
    if rider is not None:
        order.rider = rider
        order.rider_name, order.rider_phone = rider.name, rider.phone
        fields += ["rider", "rider_name", "rider_phone"]
    if new_status == S.DELIVERED:
        order.delivered_at = timezone.now()
        fields.append("delivered_at")
        if order.payment_method == "cod":
            order.payment_status = Order.PaymentStatus.COD_COLLECTED
            fields.append("payment_status")
        for line in order.lines.all():
            Product.objects.filter(pk=line.variant.product_id).update(sold_count=F("sold_count") + line.qty)
    if new_status == S.CANCELLED:
        order.cancelled_at = timezone.now()
        order.cancel_reason = note[:200]
        fields += ["cancelled_at", "cancel_reason"]
        _undo_stock_and_perks(order, by)
    order.status = new_status
    order.save(update_fields=fields)
    _event(order, new_status, by, note)
    if new_status == S.DELIVERED:
        award_order_coins(order)
        from .tasks import send_rate_email

        transaction.on_commit(lambda: send_rate_email.apply_async((order.pk,), countdown=60 * 60 * 24))
    if new_status == S.CANCELLED:
        notify.admin_event("order_cancelled", {"order": order.number, "reason": note})
    notify.order_status_changed(order)
    return order


def _undo_stock_and_perks(order, by):
    if order.status == S.PENDING_PAYMENT:
        stock.release_reservations(order)
    elif order.status != S.PAYMENT_FAILED:
        qty = {line: line.qty - line.restocked_qty for line in order.lines.all()}
        stock.restock_lines(order, qty, StockMovement.Reason.CANCEL_RESTOCK, user=by)
    refund_used_coins(order)
    reverse_order_coins(order)
    CouponRedemption.objects.filter(order=order).delete()


@transaction.atomic
def cancel_by_customer(order, reason=""):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if not order.can_cancel_by_customer:
        raise ValueError(_("This order can no longer be cancelled. Please contact us."))
    order = set_status(order, S.CANCELLED, by=order.user, note=reason or "Cancelled by customer")
    if order.is_online and order.payment_status in (
        Order.PaymentStatus.PAID,
        Order.PaymentStatus.PARTIALLY_REFUNDED,
    ):
        from apps.payments.models import Refund
        from apps.payments.services import RefundError, create_refund

        reserved = order.refunds.exclude(status=Refund.Status.FAILED).aggregate(total=Sum("amount"))["total"] or ZERO
        remaining = order.total - reserved
        if remaining > ZERO:
            try:
                create_refund(order, remaining, reason="Customer cancelled before dispatch", by=None)
            except RefundError as exc:
                raise ValueError(str(exc)) from exc
    return order


def reorder_into_cart(order, cart):
    """'Buy again': add the still-available items of a past order to the cart."""
    added = 0
    for line in order.lines.select_related("variant"):
        v = line.variant
        if v.in_stock and v.is_active:
            cart.add(f"v:{v.pk}", min(line.qty, v.max_orderable))
            added += 1
    return added


def eta_for(order):
    if order.status in (S.DELIVERED, S.CANCELLED, S.PAYMENT_FAILED, S.REFUNDED):
        return None
    if order.slot_start:
        return order.slot_start
    cfg = DeliverySettings.load()
    minutes = cfg.fast_promise_minutes if order.fast_promise else cfg.asap_max_minutes
    return (order.placed_at or order.created_at) + timedelta(minutes=minutes)
