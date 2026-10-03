import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum

from apps.core import audit
from apps.inventory.models import StockMovement
from apps.inventory.services import restock_lines
from apps.notifications import services as notify
from apps.orders.models import Order, OrderLine
from apps.orders.services import mark_paid, mark_payment_failed

from .gateways import GatewayError, get_gateway
from .models import Payment, Refund, WebhookEvent

logger = logging.getLogger(__name__)
ZERO = Decimal("0")


def start_payment(order):
    gw = get_gateway(order.payment_method)
    if gw is None:
        raise GatewayError("Online payment is switched off. Please choose Cash on Delivery.")
    payment = order.payments.filter(status=Payment.Status.CREATED, gateway=gw.slug).first()
    if payment is None:
        payment = Payment.objects.create(order=order, gateway=gw.slug, amount=order.total)
    return payment, gw.create_payment(order, payment)


def handle_return(order, data):
    """Browser came back from the gateway. We verify, but the webhook remains the source of truth."""
    payment = order.payments.filter(gateway=order.payment_method).order_by("-created_at").first()
    gw = get_gateway(order.payment_method)
    if not payment or gw is None:
        return False
    if gw.verify_return(payment, data):
        _payment_succeeded(payment)
        return True
    return False


@transaction.atomic
def _payment_succeeded(payment, gateway_payment_id=""):
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if gateway_payment_id and not payment.gateway_payment_id:
        payment.gateway_payment_id = gateway_payment_id
    payment.status = Payment.Status.SUCCEEDED
    payment.save(update_fields=["status", "gateway_payment_id", "updated_at"])
    mark_paid(payment.order, payment)


def handle_webhook(gateway_slug, body: bytes, headers):
    gw = get_gateway(gateway_slug)
    if gw is None:
        raise GatewayError("Gateway not enabled")
    result = gw.parse_webhook(body, headers)  # raises on bad signature
    try:
        with transaction.atomic():
            WebhookEvent.objects.create(
                gateway=gateway_slug, event_id=result.event_id, event_type=result.event_type, payload=result.raw
            )
    except IntegrityError:
        return "duplicate"
    if result.kind in ("payment_succeeded", "payment_failed"):
        payment = Payment.objects.filter(gateway=gateway_slug, gateway_order_id=result.gateway_order_id).first()
        if payment is None:
            logger.warning("Webhook for unknown payment %s", result.gateway_order_id)
            return "unknown"
        if result.kind == "payment_succeeded":
            if result.amount is not None and result.amount != payment.amount:
                logger.error("Amount mismatch on %s: %s vs %s", payment, result.amount, payment.amount)
                notify.admin_event("payment_failed", {"order": payment.order.number, "reason": "Amount mismatch"})
                return "mismatch"
            _payment_succeeded(payment, result.gateway_payment_id)
        else:
            with transaction.atomic():
                Payment.objects.filter(pk=payment.pk).update(
                    status=Payment.Status.FAILED, failure_reason=result.reason[:300]
                )
                mark_payment_failed(payment.order, reason=result.reason or "Payment failed")
        return result.kind
    if result.kind in ("refund_succeeded", "refund_failed") and result.gateway_refund_id:
        refund = Refund.objects.filter(gateway_refund_id=result.gateway_refund_id).first()
        if refund:
            _finish_refund(refund, result.kind == "refund_succeeded", result.reason)
        return result.kind
    return "ignored"


# ---- Refunds -------------------------------------------------------------------


class RefundError(Exception):
    pass


@transaction.atomic
def create_refund(
    order, amount, reason, by, lines=None, restock=False, method=Refund.Method.GATEWAY, reference="", request=None
):
    """Full or partial refund. ``lines`` = {OrderLine id: qty}. Owner/Manager permission is checked by the view."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if not reason.strip():
        raise RefundError("A reason is required.")
    pending = order.refunds.exclude(status=Refund.Status.FAILED).aggregate(s=Sum("amount"))["s"] or ZERO
    if amount <= 0 or amount > order.total - pending:
        raise RefundError(f"Refund must be between ₹0.01 and ₹{order.total - pending}.")
    lines = {int(k): int(v) for k, v in (lines or {}).items() if int(v) > 0}
    order_lines = {ln.pk: ln for ln in OrderLine.objects.select_for_update().filter(order=order, pk__in=lines)}
    for lid, qty in lines.items():
        if lid not in order_lines or qty > order_lines[lid].refundable_qty:
            raise RefundError("Selected quantities are more than what can be refunded.")

    online = order.is_online and order.payment_status in (
        Order.PaymentStatus.PAID,
        Order.PaymentStatus.PARTIALLY_REFUNDED,
    )
    if method == Refund.Method.GATEWAY and not online:
        raise RefundError("This order was not paid online. Record a manual refund (UPI / cash / bank).")
    payment = order.payments.filter(status=Payment.Status.SUCCEEDED).first() if online else None
    refund = Refund.objects.create(
        order=order,
        payment=payment,
        amount=amount,
        lines=lines,
        reason=reason[:300],
        method=method,
        reference=reference[:100],
        restock=restock,
        created_by=by,
    )
    for lid, qty in lines.items():
        OrderLine.objects.filter(pk=lid).update(refunded_qty=order_lines[lid].refunded_qty + qty)
    if restock and lines:
        restock_lines(
            order, {order_lines[lid]: q for lid, q in lines.items()}, StockMovement.Reason.REFUND_RESTOCK, user=by
        )
    audit.log(
        request,
        "refund.create",
        order,
        f"₹{amount} {method}: {reason[:120]}",
        {"amount": str(amount), "lines": lines, "method": method},
        user=by,
    )

    if method == Refund.Method.GATEWAY:
        gw = get_gateway(payment.gateway) if payment else None
        if gw is None:
            raise RefundError("The payment gateway for this order is switched off; enable it to refund.")
        try:
            gid, status = gw.refund(
                payment, amount, str(refund.idempotency_key), {"order": order.number, "refund": str(refund.public_id)}
            )
        except Exception as exc:  # noqa: BLE001
            raise RefundError(f"Gateway refused the refund: {exc}") from exc
        refund.gateway_refund_id = gid
        refund.save(update_fields=["gateway_refund_id"])
        _notify_refund(refund, "refund_initiated")
        if status != "pending":
            refund = _finish_refund(refund, status == "succeeded")
    else:
        refund = _finish_refund(refund, True)
    return refund


@transaction.atomic
def _finish_refund(refund, ok, reason=""):
    refund = Refund.objects.select_for_update().get(pk=refund.pk)
    if refund.status != Refund.Status.PENDING:
        return refund
    refund.status = Refund.Status.SUCCEEDED if ok else Refund.Status.FAILED
    refund.failure_reason = reason[:300]
    refund.save(update_fields=["status", "failure_reason", "updated_at"])
    if not ok:
        for lid, qty in refund.lines.items():
            line = OrderLine.objects.filter(pk=int(lid)).first()
            if line:
                OrderLine.objects.filter(pk=line.pk).update(refunded_qty=max(0, line.refunded_qty - int(qty)))
        notify.admin_event("refund_issued", {"order": refund.order.number, "status": "FAILED", "reason": reason})
        return refund
    order = Order.objects.select_for_update().get(pk=refund.order_id)
    order.refunded_total += refund.amount
    full = order.refunded_total >= order.total
    order.payment_status = Order.PaymentStatus.REFUNDED if full else Order.PaymentStatus.PARTIALLY_REFUNDED
    fields = ["refunded_total", "payment_status", "updated_at"]
    if full and order.status in (Order.Status.DELIVERED, Order.Status.CANCELLED):
        order.status = Order.Status.REFUNDED
        fields.append("status")
    order.save(update_fields=fields)
    if full:
        from apps.promotions.services import reverse_order_coins

        reverse_order_coins(order)
    _notify_refund(refund, "refund_completed")
    notify.admin_event(
        "refund_issued",
        {
            "order": order.number,
            "amount": f"₹{refund.amount}",
            "method": refund.get_method_display(),
            "reason": refund.reason,
        },
    )
    return refund


def _notify_refund(refund, template):
    notify.customer_email(
        refund.order.user.email,
        template,
        {"order": refund.order, "refund": refund, "subject_vars": {"number": refund.order.number}},
        event_key=template,
    )
