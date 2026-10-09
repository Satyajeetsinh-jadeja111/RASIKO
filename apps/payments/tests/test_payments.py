import hashlib
import hmac
import json
from decimal import Decimal
from unittest import mock

import pytest

from apps.inventory.models import StockMovement
from apps.orders.models import Order
from apps.orders.services import set_status
from apps.payments.gateways import GatewayError, to_paise
from apps.payments.models import Payment, Refund, WebhookEvent
from apps.payments.services import RefundError, create_refund, handle_return, handle_webhook

D = Decimal


def signed(body: dict, secret="whsec", event_id="evt_1"):
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id}


@pytest.fixture
def online_order(place, razorpay_on):
    order = place(qty=4, method="razorpay")
    payment = Payment.objects.create(order=order, gateway="razorpay", amount=order.total, gateway_order_id="order_X1")
    return order, payment


def captured(payment, amount=None):
    return {
        "event": "payment.captured",
        "created_at": 1,
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_1",
                    "order_id": payment.gateway_order_id,
                    "amount": amount or to_paise(payment.amount),
                    "currency": "INR",
                }
            }
        },
    }


@pytest.mark.django_db
class TestWebhooks:
    def test_payment_captured_marks_paid_once(self, online_order, variant):
        order, payment = online_order
        body, headers = signed(captured(payment))
        assert handle_webhook("razorpay", body, headers) == "payment_succeeded"
        assert handle_webhook("razorpay", body, headers) == "duplicate"
        order.refresh_from_db()
        variant.refresh_from_db()
        assert order.status == "placed" and order.payment_status == "paid"
        assert variant.stock_qty == 12 and variant.reserved_qty == 0
        assert WebhookEvent.objects.count() == 1
        assert StockMovement.objects.filter(order=order).count() == 1

    def test_bad_signature_rejected(self, online_order):
        _, payment = online_order
        body, headers = signed(captured(payment), secret="wrong")
        with pytest.raises(GatewayError):
            handle_webhook("razorpay", body, headers)
        assert not WebhookEvent.objects.exists()

    def test_amount_mismatch_not_paid(self, online_order):
        order, payment = online_order
        body, headers = signed(captured(payment, amount=100))
        assert handle_webhook("razorpay", body, headers) == "mismatch"
        order.refresh_from_db()
        assert order.payment_status != "paid"

    def test_failed_attempt_keeps_reservation_for_retry(self, online_order, variant):
        order, payment = online_order
        body, headers = signed(
            {
                "event": "payment.failed",
                "created_at": 2,
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_2",
                            "order_id": payment.gateway_order_id,
                            "error_description": "Bank declined",
                        }
                    }
                },
            },
            event_id="evt_2",
        )
        assert handle_webhook("razorpay", body, headers) == "payment_failed"
        order.refresh_from_db()
        variant.refresh_from_db()
        assert order.status == "pending_payment" and variant.reserved_qty == 8

    def test_browser_return_signature(self, online_order):
        order, payment = online_order
        sig = hmac.new(b"test_secret", b"order_X1|pay_9", hashlib.sha256).hexdigest()
        assert not handle_return(order, {"razorpay_payment_id": "pay_9", "razorpay_signature": "bad"})
        with mock.patch("apps.payments.gateways.razorpay_gateway.RazorpayGateway.client") as client:
            client.payment.fetch.return_value = {
                "id": "pay_9",
                "order_id": "order_X1",
                "amount": to_paise(payment.amount),
                "currency": "INR",
                "status": "captured",
            }
            assert handle_return(order, {"razorpay_payment_id": "pay_9", "razorpay_signature": sig})
        order.refresh_from_db()
        assert order.payment_status == "paid"

    def test_webhook_view_rejects_unsigned(self, client, online_order):
        r = client.post("/payments/webhooks/razorpay/", data=b"{}", content_type="application/json")
        assert r.status_code == 400


@pytest.fixture
def paid_order(online_order):
    order, payment = online_order
    body, headers = signed(captured(payment))
    handle_webhook("razorpay", body, headers)
    order.refresh_from_db()
    return order


@pytest.mark.django_db(transaction=True)
class TestRefunds:
    def test_full_refund_through_gateway(self, paid_order, manager):
        with mock.patch(
            "apps.payments.gateways.razorpay_gateway.RazorpayGateway.refund", return_value=("rfnd_1", "succeeded")
        ) as gw:
            r = create_refund(paid_order, paid_order.total, "Damaged bottle", manager)
        gw.assert_called_once()
        assert gw.call_args.args[2] == str(r.idempotency_key)
        paid_order.refresh_from_db()
        assert r.status == "succeeded" and paid_order.refunded_total == paid_order.total
        assert paid_order.payment_status == "refunded"

    def test_partial_refund_by_lines_restocks(self, paid_order, manager, variant):
        line = paid_order.lines.get()
        with mock.patch(
            "apps.payments.gateways.razorpay_gateway.RazorpayGateway.refund", return_value=("rfnd_2", "pending")
        ):
            r = create_refund(paid_order, D("50"), "One bottle leaked", manager, lines={line.pk: 1}, restock=True)
        line.refresh_from_db()
        variant.refresh_from_db()
        assert r.status == "pending" and line.refunded_qty == 1 and variant.stock_qty == 12
        body, headers = signed(
            {
                "event": "refund.processed",
                "created_at": 3,
                "payload": {"refund": {"entity": {"id": "rfnd_2", "payment_id": "pay_1"}}},
            },
            event_id="evt_r2",
        )
        handle_webhook("razorpay", body, headers)
        r.refresh_from_db()
        paid_order.refresh_from_db()
        assert r.status == "succeeded" and paid_order.payment_status == "partial_refund"
        variant.refresh_from_db()
        assert variant.stock_qty == 14

    def test_cannot_refund_more_than_paid(self, paid_order, manager):
        with pytest.raises(RefundError):
            create_refund(paid_order, paid_order.total + 1, "Too much", manager)

    def test_reason_required(self, paid_order, manager):
        with pytest.raises(RefundError):
            create_refund(paid_order, D("10"), "  ", manager)

    def test_line_qty_limit(self, paid_order, manager):
        line = paid_order.lines.get()
        with pytest.raises(RefundError):
            create_refund(paid_order, D("10"), "x", manager, lines={line.pk: 99}, method=Refund.Method.UPI)

    def test_manual_refund_for_cod(self, place, manager, staff_user):
        o = place(qty=3)
        for s in ["confirmed", "packed", "out_for_delivery", "delivered"]:
            o = set_status(o, s, by=staff_user)
        with pytest.raises(RefundError):
            create_refund(o, D("10"), "Gateway on COD", manager)
        r = create_refund(o, D("10"), "Short by one", manager, method=Refund.Method.UPI, reference="UPI123")
        assert r.status == "succeeded"
        assert Order.objects.get(pk=o.pk).refunded_total == D("10")


@pytest.mark.django_db
def test_webhook_view_and_return_view(client, customer, online_order):
    order, payment = online_order
    body, headers = signed(captured(payment), event_id="evt_view")
    r = client.post(
        "/payments/webhooks/razorpay/",
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=headers["X-Razorpay-Signature"],
        HTTP_X_RAZORPAY_EVENT_ID="evt_view",
    )
    assert r.status_code == 200
    assert client.post("/payments/webhooks/paypal/", data=b"{}", content_type="application/json").status_code == 400
    client.force_login(customer)
    r = client.post(
        f"/payments/pay/{order.public_id}/razorpay/", {"razorpay_payment_id": "p", "razorpay_signature": "x"}
    )
    assert r.status_code == 302
    assert client.get(f"/payments/pay/{order.public_id}/")["Location"] == order.get_absolute_url()  # already paid
