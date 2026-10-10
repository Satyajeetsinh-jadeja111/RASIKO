import hashlib
import hmac
from datetime import timedelta
from unittest import mock

import pytest
from django.db import connection
from django.utils import timezone

from apps.core.models import StoreSettings
from apps.orders.models import Order
from apps.payments.gateways import GatewayError, get_gateway, online_gateway, to_paise
from apps.payments.models import Payment, Refund, WebhookEvent
from apps.payments.services import (
    RefundError,
    create_refund,
    handle_return,
    handle_webhook,
    start_payment,
    submit_refund,
)
from apps.payments.tasks import reconcile_payments
from apps.payments.tests.test_payments import captured, signed

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def online_order(place, razorpay_on):
    order = place(qty=4, method="razorpay")
    payment = Payment.objects.create(order=order, gateway="razorpay", amount=order.total, gateway_order_id="order_X1")
    return order, payment


def test_authorized_return_does_not_fulfill(online_order):
    order, payment = online_order
    signature = hmac.new(b"test_secret", b"order_X1|pay_9", hashlib.sha256).hexdigest()
    with mock.patch("apps.payments.gateways.razorpay_gateway.RazorpayGateway.client") as client:
        client.payment.fetch.return_value = {
            "order_id": "order_X1",
            "amount": to_paise(payment.amount),
            "currency": "INR",
            "status": "authorized",
        }
        assert not handle_return(order, {"razorpay_payment_id": "pay_9", "razorpay_signature": signature})
    order.refresh_from_db()
    assert order.status == Order.Status.PENDING_PAYMENT


def test_webhook_recovers_after_processing_crash(online_order):
    order, payment = online_order
    body, headers = signed(captured(payment))
    with mock.patch("apps.payments.services.mark_paid", side_effect=RuntimeError("crash")):
        with pytest.raises(RuntimeError):
            handle_webhook("razorpay", body, headers)
    event = WebhookEvent.objects.get()
    payment.refresh_from_db()
    assert event.status == "pending" and payment.status == "created"
    assert handle_webhook("razorpay", body, headers) == "payment_succeeded"
    event.refresh_from_db()
    assert event.status == "processed" and event.attempts == 2


def test_late_failure_cannot_overwrite_success(online_order):
    order, payment = online_order
    body, headers = signed(captured(payment))
    handle_webhook("razorpay", body, headers)
    event = captured(payment)
    event["event"] = "payment.failed"
    body, headers = signed(event, event_id="late-failure")
    handle_webhook("razorpay", body, headers)
    order.refresh_from_db()
    payment.refresh_from_db()
    assert payment.status == "succeeded" and order.payment_status == "paid"


def test_currency_mismatch_is_rejected(online_order):
    order, payment = online_order
    event = captured(payment)
    event["payload"]["payment"]["entity"]["currency"] = "USD"
    body, headers = signed(event)
    assert handle_webhook("razorpay", body, headers) == "mismatch"
    assert WebhookEvent.objects.get().status == "rejected"
    order.refresh_from_db()
    assert order.payment_status != "paid"


def test_disabled_gateway_still_processes_historical_webhook(online_order, razorpay_on):
    order, payment = online_order
    razorpay_on.enabled = False
    razorpay_on.save()
    assert online_gateway() is None
    assert get_gateway("razorpay") is None
    body, headers = signed(captured(payment))
    assert handle_webhook("razorpay", body, headers) == "payment_succeeded"


def test_gateway_fallback_requires_opt_in(razorpay_on):
    settings = StoreSettings.load()
    settings.active_gateway = "stripe"
    settings.save()
    assert online_gateway() is None
    settings.gateway_fallback_enabled = True
    settings.save()
    assert online_gateway() == "razorpay"


def test_page_refresh_reuses_razorpay_order(online_order):
    order, payment = online_order
    with mock.patch("apps.payments.gateways.razorpay_gateway.RazorpayGateway.client") as client:
        client.order.fetch.return_value = {
            "id": payment.gateway_order_id,
            "amount": to_paise(payment.amount),
            "currency": "INR",
        }
        start_payment(order)
        start_payment(order)
        client.order.create.assert_not_called()
        assert client.order.fetch.call_count == 2
    assert Payment.objects.filter(order=order).count() == 1


def test_uncertain_creation_is_not_blindly_retried(place, razorpay_on):
    order = place(method="razorpay")
    with mock.patch(
        "apps.payments.gateways.razorpay_gateway.RazorpayGateway.create_payment", side_effect=TimeoutError
    ) as provider:
        with pytest.raises(TimeoutError):
            start_payment(order)
        with pytest.raises(GatewayError):
            start_payment(order)
        assert provider.call_count == 1
    assert Payment.objects.get(order=order).creation_uncertain


def test_unknown_event_can_match_later(online_order):
    order, payment = online_order
    event = captured(payment)
    event["payload"]["payment"]["entity"]["order_id"] = "new-order"
    body, headers = signed(event)
    assert handle_webhook("razorpay", body, headers) == "unknown"
    payment.gateway_order_id = "new-order"
    payment.save()
    assert handle_webhook("razorpay", body, headers) == "payment_succeeded"


def test_refund_timeout_preserves_operation_and_stock(online_order, manager, variant):
    order, payment = online_order
    body, headers = signed(captured(payment))
    handle_webhook("razorpay", body, headers)
    order.refresh_from_db()
    line = order.lines.get()

    def timeout(*args):
        assert not connection.in_atomic_block
        raise TimeoutError

    with mock.patch("apps.payments.gateways.razorpay_gateway.RazorpayGateway.refund", side_effect=timeout) as provider:
        refund = create_refund(order, "10", "Damaged", manager, lines={line.pk: 1}, restock=True)
        submit_refund(refund.pk)
        assert provider.call_count == 1
    refund.refresh_from_db()
    variant.refresh_from_db()
    assert refund.submission_uncertain and refund.status == "pending"
    assert variant.stock_qty == 12
    assert Refund.objects.count() == 1
    with pytest.raises(RefundError):
        create_refund(order, order.total, "Would exceed available amount", manager)


def test_reconciliation_finds_missing_capture(online_order):
    order, payment = online_order
    Payment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(minutes=5))
    from apps.payments.gateways import WebhookResult

    result = WebhookResult(
        "",
        "reconcile",
        "payment_succeeded",
        gateway_order_id=payment.gateway_order_id,
        gateway_payment_id="p-recovered",
        amount=payment.amount,
        currency="INR",
    )
    with mock.patch("apps.payments.gateways.razorpay_gateway.RazorpayGateway.retrieve_payment", return_value=result):
        reconcile_payments()
    order.refresh_from_db()
    assert order.payment_status == "paid"


def test_failed_attempt_can_succeed_on_same_order(online_order, variant):
    order, payment = online_order
    event = captured(payment)
    event["event"] = "payment.failed"
    body, headers = signed(event, event_id="failed-attempt")
    handle_webhook("razorpay", body, headers)
    order.refresh_from_db()
    assert order.status == "pending_payment"
    body, headers = signed(captured(payment), event_id="successful-retry")
    handle_webhook("razorpay", body, headers)
    order.refresh_from_db()
    variant.refresh_from_db()
    assert order.status == "placed" and variant.stock_qty == 12


def test_reconciliation_does_not_starve_unchecked_operations(online_order):
    order, payment = online_order
    Payment.objects.bulk_create(
        [
            Payment(
                order=order,
                gateway="razorpay",
                amount=order.total,
                gateway_order_id=f"old-{i}",
                last_checked_at=timezone.now(),
            )
            for i in range(55)
        ]
    )
    Payment.objects.update(created_at=timezone.now() - timedelta(minutes=5))
    from apps.payments.gateways import WebhookResult

    with mock.patch(
        "apps.payments.gateways.razorpay_gateway.RazorpayGateway.retrieve_payment",
        return_value=WebhookResult("", "reconcile", "ignored"),
    ) as provider:
        reconcile_payments()
    assert provider.call_count == 1
    payment.refresh_from_db()
    assert payment.reconcile_attempts == 1


def test_old_uncertain_stripe_creation_is_not_resubmitted(online_order):
    order, payment = online_order
    from apps.payments.gateways.stripe_gateway import StripeGateway

    payment.gateway = "stripe"
    payment.gateway_order_id = ""
    payment.creation_uncertain = True
    payment.creation_started_at = timezone.now() - timedelta(hours=25)
    gateway = StripeGateway({"secret_key": "sk_test_fake", "publishable_key": "pk_test_fake"})
    with mock.patch("stripe.StripeClient") as provider:
        with pytest.raises(GatewayError):
            gateway.create_payment(order, payment)
        provider.assert_not_called()


def test_cancellation_during_pending_refund_restocks_exactly_once(online_order, manager, variant):
    order, payment = online_order
    body, headers = signed(captured(payment))
    handle_webhook("razorpay", body, headers)
    order.refresh_from_db()
    line = order.lines.get()
    with mock.patch(
        "apps.payments.gateways.razorpay_gateway.RazorpayGateway.refund", return_value=("ref-pending", "pending")
    ):
        refund = create_refund(order, "10", "Damaged", manager, lines={line.pk: 1}, restock=True)
    from apps.orders.services import set_status
    from apps.payments.services import _finish_refund

    set_status(order, Order.Status.CANCELLED, by=manager)
    _finish_refund(refund, False, "Rejected")
    variant.refresh_from_db()
    line.refresh_from_db()
    assert variant.stock_qty == 20 and line.restocked_qty == 4 and line.refunded_qty == 0


def test_concurrent_starts_create_one_provider_attempt(place, razorpay_on):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from django.db import close_old_connections

    order = place(qty=2, method="razorpay")
    entered, release = Event(), Event()

    def provider_create(order, payment):
        entered.set()
        assert release.wait(10)
        payment.gateway_order_id = "one-provider-order"
        payment.save(update_fields=["gateway_order_id"])
        return {"id": payment.gateway_order_id}

    def run():
        close_old_connections()
        try:
            return start_payment(Order.objects.get(pk=order.pk))
        finally:
            close_old_connections()

    gateway = mock.Mock(slug="razorpay", create_payment=provider_create)
    with mock.patch("apps.payments.services.get_gateway", return_value=gateway):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run)
            assert entered.wait(10)
            try:
                with pytest.raises(GatewayError, match="being initialized"):
                    pool.submit(run).result(timeout=10)
            finally:
                release.set()
            first.result(timeout=10)
    assert order.payments.count() == 1


def test_uncollected_cod_cannot_be_refunded(place, manager):
    order = place(qty=2)
    with pytest.raises(RefundError, match="collected"):
        create_refund(order, "10", "Not paid yet", manager, method=Refund.Method.CASH)
    assert not order.refunds.exists()


@pytest.mark.parametrize("partial_status", ["pending", "succeeded"])
def test_customer_cancel_refunds_only_unreserved_balance(online_order, manager, partial_status):
    from apps.orders.services import cancel_by_customer

    order, payment = online_order
    body, headers = signed(captured(payment))
    handle_webhook("razorpay", body, headers)
    order.refresh_from_db()
    with mock.patch(
        "apps.payments.gateways.razorpay_gateway.RazorpayGateway.refund", return_value=("partial", partial_status)
    ):
        create_refund(order, "10", "Partial adjustment", manager)
    order.refresh_from_db()
    with mock.patch(
        "apps.payments.gateways.razorpay_gateway.RazorpayGateway.refund", return_value=("remaining", "pending")
    ):
        cancel_by_customer(order, "Changed my mind")
    order.refresh_from_db()
    assert order.status == Order.Status.CANCELLED
    assert order.refunds.count() == 2
    assert sum(r.amount for r in order.refunds.all()) == order.total
