"""Bounded recovery for durably received events and ambiguous provider operations."""

import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.orders.models import Order

from .gateways import GatewayError, get_gateway
from .models import Payment, Refund, WebhookEvent
from .services import _finish_refund, apply_result, process_webhook, submit_refund

logger = logging.getLogger(__name__)


def _claim(model, pk):
    """Claim with an order-first lock and a five-minute minimum retry interval."""
    obj = model.objects.get(pk=pk)
    with transaction.atomic():
        Order.objects.select_for_update().get(pk=obj.order_id)
        obj = model.objects.select_for_update().get(pk=pk)
        delay = 300
        if obj.last_checked_at and obj.last_checked_at > timezone.now() - timedelta(seconds=delay):
            return None
        obj.last_checked_at = timezone.now()
        obj.reconcile_attempts += 1
        obj.save(update_fields=["last_checked_at", "reconcile_attempts"])
    return obj


@shared_task
def reconcile_payments():
    cutoff = timezone.now() - timedelta(minutes=2)
    for pk in (
        WebhookEvent.objects.filter(status="pending", received_at__lt=cutoff)
        .order_by("attempts", "received_at")
        .values_list("pk", flat=True)[:100]
    ):
        try:
            process_webhook(pk)
        except Exception:  # noqa: BLE001 - one event must not block the recovery batch
            logger.exception("Webhook recovery failed for event %s", pk)
    due = Q(last_checked_at__isnull=True) | Q(last_checked_at__lte=timezone.now() - timedelta(minutes=5))
    payments = (
        Payment.objects.exclude(status=Payment.Status.SUCCEEDED)
        .filter(created_at__lt=cutoff, created_at__gt=timezone.now() - timedelta(days=7))
        .filter(due)
        .order_by(F("last_checked_at").asc(nulls_first=True), "pk")
    )
    for pk in payments.values_list("pk", flat=True)[:50]:
        try:
            payment = _claim(Payment, pk)
            if payment is None:
                continue
            gw = get_gateway(payment.gateway, historical=True)
            if gw is None:
                raise GatewayError("Saved credentials unavailable")
            if not payment.gateway_order_id:
                if not payment.creation_started_at:
                    continue
                if payment.gateway == "stripe" and payment.creation_started_at < timezone.now() - timedelta(hours=23):
                    raise GatewayError("Expired idempotency window: manual provider lookup required")
                payment.creation_uncertain = True
                gw.create_payment(payment.order, payment)
            apply_result(payment.gateway, gw.retrieve_payment(payment))
        except Exception as exc:  # noqa: BLE001 - retain operation for future reconciliation
            Payment.objects.filter(pk=pk).update(failure_reason=type(exc).__name__)
            logger.warning("Payment reconciliation needs attention: %s (%s)", pk, type(exc).__name__)
    for pk in (
        Refund.objects.filter(status=Refund.Status.PENDING)
        .filter(due)
        .order_by(F("last_checked_at").asc(nulls_first=True), "pk")
        .values_list("pk", flat=True)[:50]
    ):
        try:
            refund = _claim(Refund, pk)
            if refund is None or refund.payment is None:
                continue
            if not refund.submission_started_at:
                submit_refund(pk)
                continue
            gw = get_gateway(refund.payment.gateway, historical=True)
            if gw is None:
                raise GatewayError("Saved credentials unavailable")
            gid, status = gw.retrieve_refund(refund)
            if gid:
                Refund.objects.filter(pk=pk).update(gateway_refund_id=gid, submission_uncertain=False)
                if status != "pending":
                    _finish_refund(refund, status == "succeeded")
        except Exception as exc:  # noqa: BLE001 - uncertain refunds must not be resubmitted
            Refund.objects.filter(pk=pk).update(failure_reason=type(exc).__name__)
            logger.warning("Refund reconciliation needs attention: %s (%s)", pk, type(exc).__name__)
