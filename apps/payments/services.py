import logging
from dataclasses import asdict
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.core import audit
from apps.inventory.models import StockMovement
from apps.inventory.services import restock_lines
from apps.notifications import services as notify
from apps.orders.models import Order, OrderLine
from apps.orders.services import mark_paid, mark_payment_failed

from .gateways import GatewayError, WebhookResult, get_gateway, online_gateway
from .models import Payment, Refund, WebhookEvent

logger = logging.getLogger(__name__)
ZERO = Decimal("0")


def start_payment(order):
    if online_gateway() != order.payment_method:
        raise GatewayError("This gateway is no longer selected for checkout. Please create a new order.")
    gw = get_gateway(order.payment_method)
    if gw is None:
        raise GatewayError("Online payment is switched off. Please choose Cash on Delivery.")
    # The order lock serializes local attempt creation, not the provider network call.
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status != Order.Status.PENDING_PAYMENT:
            raise GatewayError("This order is no longer awaiting payment.")
        payment = order.payments.filter(gateway=gw.slug).order_by("-created_at").first()
        if payment is None:
            payment = Payment.objects.create(order=order, gateway=gw.slug, amount=order.total)
        if not payment.gateway_order_id:
            if payment.creation_started_at:
                # A crashed/in-flight create is ambiguous. Razorpay must be looked up, never blindly retried.
                if (timezone.now() - payment.creation_started_at).total_seconds() < 60:
                    raise GatewayError("Payment is being initialized. Please wait before retrying.")
                payment.creation_uncertain = True
            payment.creation_started_at = payment.creation_started_at or timezone.now()
            payment.save(update_fields=["creation_started_at", "creation_uncertain", "updated_at"])
    try:
        client = gw.create_payment(order, payment)
    except Exception:
        Payment.objects.filter(pk=payment.pk).update(creation_uncertain=True)
        raise
    Payment.objects.filter(pk=payment.pk).update(creation_uncertain=False)
    return payment, client


def handle_return(order, data):
    payment = order.payments.filter(gateway=order.payment_method).order_by("-created_at").first()
    gw = get_gateway(order.payment_method, historical=True)
    if not payment or gw is None or not payment.gateway_order_id:
        return False
    if gw.verify_return(payment, data):
        _payment_succeeded(payment, payment.gateway_payment_id)
        return True
    return False


@transaction.atomic
def _payment_succeeded(payment, gateway_payment_id=""):
    # Every payment/refund mutation locks the order first, then child records.
    order = Order.objects.select_for_update().get(pk=payment.order_id)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == Payment.Status.SUCCEEDED:
        return
    if gateway_payment_id:
        payment.gateway_payment_id = gateway_payment_id
    payment.status = Payment.Status.SUCCEEDED
    payment.save(update_fields=["status", "gateway_payment_id", "updated_at"])
    if order.payment_status in (
        Order.PaymentStatus.PAID,
        Order.PaymentStatus.PARTIALLY_REFUNDED,
        Order.PaymentStatus.REFUNDED,
    ):
        order.staff_note += "\nAdditional payment received: review and refund the duplicate payment."
        order.save(update_fields=["staff_note"])
        notify.admin_event("payment_succeeded", {"order": order.number, "warning": "Additional payment needs review"})
        return
    mark_paid(order, payment)


def handle_webhook(gateway_slug, body: bytes, headers):
    gw = get_gateway(gateway_slug, historical=True)
    if gw is None:
        raise GatewayError("Gateway credentials unavailable")
    try:
        result = gw.parse_webhook(body, headers)
    except (ValueError, KeyError, TypeError) as exc:
        raise GatewayError("Malformed webhook") from exc
    payload = asdict(result)
    payload["amount"] = str(result.amount) if result.amount is not None else None
    payload["raw"] = {}  # retain normalized financial identifiers, not customer/provider raw data
    event, _ = WebhookEvent.objects.get_or_create(
        gateway=gateway_slug,
        event_id=result.event_id,
        defaults={"event_type": result.event_type, "payload": payload},
    )
    return process_webhook(event.pk)


def process_webhook(event_id):
    WebhookEvent.objects.filter(pk=event_id, status="pending").update(attempts=F("attempts") + 1)
    try:
        with transaction.atomic():
            event = WebhookEvent.objects.select_for_update().get(pk=event_id)
            if event.status != "pending":
                return "duplicate"
            if "kind" not in event.payload:
                # Pre-migration processed rows are marked processed by the data migration.
                raise GatewayError("Webhook lacks normalized payload")
            result = WebhookResult(**event.payload)
            if result.amount is not None:
                result.amount = Decimal(result.amount)
            outcome = apply_result(event.gateway, result)
            if outcome == "unknown":
                event.last_error = "Waiting for matching provider operation"
                event.save(update_fields=["last_error"])
                return outcome
            event.status = "rejected" if outcome == "mismatch" else "processed"
            event.processed_at = timezone.now()
            event.last_error = "Amount, currency, or identity mismatch" if outcome == "mismatch" else ""
            event.save(update_fields=["status", "processed_at", "last_error"])
            return outcome
    except Exception as exc:
        WebhookEvent.objects.filter(pk=event_id).update(last_error=type(exc).__name__)
        raise


def apply_result(gateway_slug, result):
    if result.kind in ("payment_succeeded", "payment_failed", "payment_cancelled"):
        payment = Payment.objects.filter(gateway=gateway_slug, gateway_order_id=result.gateway_order_id).first()
        if payment is None:
            return "unknown"
        with transaction.atomic():
            Order.objects.select_for_update().get(pk=payment.order_id)
            payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if result.kind == "payment_succeeded":
                if (
                    result.amount != payment.amount
                    or result.currency.upper() != payment.currency
                    or not result.gateway_payment_id
                ):
                    logger.error("Rejected payment mismatch for payment %s", payment.pk)
                    return "mismatch"
                _payment_succeeded(payment, result.gateway_payment_id)
            elif payment.status != Payment.Status.SUCCEEDED:
                payment.status, payment.failure_reason = Payment.Status.FAILED, result.reason[:300]
                payment.save(update_fields=["status", "failure_reason", "updated_at"])
                if result.kind == "payment_cancelled":
                    mark_payment_failed(payment.order, reason=result.reason or "Payment cancelled")
        return result.kind
    if result.kind in ("refund_succeeded", "refund_failed") and result.gateway_refund_id:
        refund = Refund.objects.filter(
            payment__gateway=gateway_slug, gateway_refund_id=result.gateway_refund_id
        ).first()
        if not refund:
            return "unknown"
        _finish_refund(refund, result.kind == "refund_succeeded", result.reason)
        return result.kind
    return "ignored"


# ---- Refunds -------------------------------------------------------------------


class RefundError(Exception):
    pass


@transaction.atomic
def _reserve_refund(
    order, amount, reason, by, lines=None, restock=False, method=Refund.Method.GATEWAY, reference="", request=None
):
    """Full or partial refund. ``lines`` = {OrderLine id: qty}. Owner/Manager permission is checked by the view."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    if order.payment_status not in (
        Order.PaymentStatus.PAID,
        Order.PaymentStatus.COD_COLLECTED,
        Order.PaymentStatus.PARTIALLY_REFUNDED,
    ):
        raise RefundError("Payment must be collected before a refund can be recorded.")
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
    audit.log(
        request,
        "refund.create",
        order,
        f"₹{amount} {method}: {reason[:120]}",
        {"amount": str(amount), "lines": lines, "method": method},
        user=by,
    )

    if method == Refund.Method.GATEWAY:
        if payment is None or get_gateway(payment.gateway, historical=True) is None:
            raise RefundError("Saved gateway credentials are required to refund this payment.")
    return refund


def create_refund(
    order, amount, reason, by, lines=None, restock=False, method=Refund.Method.GATEWAY, reference="", request=None
):
    refund = _reserve_refund(order, amount, reason, by, lines, restock, method, reference, request)
    if method != Refund.Method.GATEWAY:
        return _finish_refund(refund, True)
    # Must run after the caller's transaction too (e.g. cancellation flows).
    transaction.on_commit(lambda: submit_refund(refund.pk))
    refund.refresh_from_db()
    return refund


def submit_refund(refund_id):
    refund = Refund.objects.select_related("payment", "order").get(pk=refund_id)
    with transaction.atomic():
        Order.objects.select_for_update().get(pk=refund.order_id)
        refund = Refund.objects.select_for_update(of=("self",)).select_related("payment", "order").get(pk=refund_id)
        if refund.status != Refund.Status.PENDING or refund.submission_started_at:
            return refund
        refund.submission_started_at = timezone.now()
        refund.save(update_fields=["submission_started_at"])
    gw = get_gateway(refund.payment.gateway, historical=True)
    if gw is None:
        Refund.objects.filter(pk=refund.pk).update(
            submission_uncertain=True, failure_reason="Saved gateway credentials unavailable"
        )
        return refund
    try:
        gid, status = gw.refund(
            refund.payment,
            refund.amount,
            str(refund.idempotency_key),
            {"order": refund.order.number, "refund": str(refund.public_id)},
        )
    except Exception as exc:  # noqa: BLE001 - preserve ambiguous provider outcomes
        # A timeout may hide a successful refund. Hold the amount until reconciliation.
        Refund.objects.filter(pk=refund.pk).update(submission_uncertain=True, failure_reason=type(exc).__name__)
        logger.warning("Refund %s requires reconciliation (%s)", refund.pk, type(exc).__name__)
        return refund
    Refund.objects.filter(pk=refund.pk).update(gateway_refund_id=gid, submission_uncertain=False)
    refund.refresh_from_db()
    _notify_refund(refund, "refund_initiated")
    if status != "pending":
        refund = _finish_refund(refund, status == "succeeded")
    return refund


@transaction.atomic
def _finish_refund(refund, ok, reason=""):
    Order.objects.select_for_update().get(pk=refund.order_id)
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
    if refund.restock and refund.lines and not refund.restocked:
        order_lines = {line.pk: line for line in OrderLine.objects.filter(order=order, pk__in=refund.lines)}
        restock_lines(
            order, {order_lines[int(k)]: int(q) for k, q in refund.lines.items()}, StockMovement.Reason.REFUND_RESTOCK
        )
        refund.restocked = True
        refund.save(update_fields=["restocked"])
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
