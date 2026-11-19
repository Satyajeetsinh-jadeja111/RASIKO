import hashlib
import hmac
from decimal import Decimal
from unittest.mock import patch

import pytest
import razorpay
from django.urls import reverse

from apps.accounts.models import User
from apps.core.integrations import get_config
from apps.payments.gateways import to_paise
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


@pytest.fixture
def online_order(place, razorpay_on):
    order = place(qty=4, method="razorpay")
    payment = Payment.objects.create(order=order, gateway="razorpay", amount=order.total, gateway_order_id="order_X1")
    return order, payment


def checkout_data(payment):
    return {
        "razorpay_order_id": payment.gateway_order_id,
        "razorpay_payment_id": "pay_verified",
        "razorpay_signature": hmac.new(
            b"test_secret", f"{payment.gateway_order_id}|pay_verified".encode(), hashlib.sha256
        ).hexdigest(),
    }


def test_create_reuses_provider_order_and_ignores_browser_total(client, customer, online_order):
    order, payment = online_order
    client.force_login(customer)
    with patch("apps.payments.gateways.razorpay_gateway.RazorpayGateway.client") as provider:
        provider.order.fetch.return_value = {
            "id": payment.gateway_order_id,
            "amount": to_paise(order.total),
            "currency": "INR",
        }
        url = reverse("payments:create_order", args=[order.public_id])
        for _ in range(2):
            result = client.post(url, {"amount": 100, "currency": "USD"})
            assert result.status_code == 200
            assert result.json()["amount"] == to_paise(order.total)
            assert result.json()["order_id"] == payment.gateway_order_id
            assert "key_secret" not in result.json()
        provider.order.create.assert_not_called()
    assert order.payments.count() == 1


def test_create_requires_login_owner_post_and_minimum(client, customer, online_order):
    order, _ = online_order
    url = reverse("payments:create_order", args=[order.public_id])
    assert client.post(url).status_code == 401
    client.force_login(User.objects.create_user(email="other@example.com"))
    assert client.post(url).status_code == 404
    client.force_login(customer)
    assert client.get(url).status_code == 405
    order.total = Decimal("0.99")
    order.save()
    assert client.post(url).status_code == 400


@pytest.mark.parametrize(
    "failure,status",
    [(razorpay.errors.BadRequestError("Authentication failed"), 401), (RuntimeError("unavailable"), 500)],
)
def test_create_provider_errors_are_safe(client, customer, online_order, failure, status):
    order, _ = online_order
    client.force_login(customer)
    with patch("apps.payments.services.start_payment", side_effect=failure):
        response = client.post(reverse("payments:create_order", args=[order.public_id]))
    assert response.status_code == status
    assert str(failure) not in response.json()["error"]


@pytest.mark.parametrize("payload", [{}, [], {"razorpay_payment_id": "p"}, {"razorpay_payment_id": 1}])
def test_verify_requires_all_three_strings(client, customer, online_order, payload):
    order, _ = online_order
    client.force_login(customer)
    response = client.post(
        reverse("payments:verify_payment", args=[order.public_id]), payload, content_type="application/json"
    )
    assert response.status_code == 400
    order.refresh_from_db()
    assert order.payment_status != "paid"


@pytest.mark.parametrize(
    "change", [{"status": "authorized"}, {"amount": 100}, {"currency": "USD"}, {"order_id": "order_wrong"}, {}]
)
def test_verify_only_fulfills_matching_captured_payment(client, customer, online_order, change):
    order, payment = online_order
    client.force_login(customer)
    payload = {
        "id": "pay_verified",
        "order_id": payment.gateway_order_id,
        "amount": to_paise(order.total),
        "currency": "INR",
        "status": "captured",
    }
    payload.update(change)
    with patch("apps.payments.gateways.razorpay_gateway.RazorpayGateway.client") as provider:
        provider.payment.fetch.return_value = payload
        result = client.post(
            reverse("payments:verify_payment", args=[order.public_id]),
            checkout_data(payment),
            content_type="application/json",
        )
    order.refresh_from_db()
    assert result.status_code == (400 if change else 200)
    assert (order.payment_status == "paid") == (not change)


@pytest.mark.parametrize("field,value", [("razorpay_signature", "bad"), ("razorpay_order_id", "order_wrong")])
def test_signature_mismatch_never_fetches_or_marks_paid(client, customer, online_order, field, value):
    order, payment = online_order
    client.force_login(customer)
    data = checkout_data(payment)
    data[field] = value
    with patch("apps.payments.gateways.razorpay_gateway.RazorpayGateway.client") as provider:
        result = client.post(
            reverse("payments:verify_payment", args=[order.public_id]), data, content_type="application/json"
        )
        provider.payment.fetch.assert_not_called()
    assert result.status_code == 400


def test_environment_credentials_require_explicit_enable_and_respect_disable(settings, razorpay_on):
    settings.RAZORPAY_KEY_ID = "rzp_test_environment"
    settings.RAZORPAY_KEY_SECRET = "environment-secret"
    assert get_config("razorpay")["key_id"] == "rzp_test_environment"
    razorpay_on.enabled = False
    razorpay_on.save()
    settings.RAZORPAY_ENABLED = True
    assert get_config("razorpay") is None
    assert get_config("razorpay", allow_disabled=True)["key_id"] == "rzp_test_environment"
    razorpay_on.delete()
    settings.RAZORPAY_ENABLED = False
    assert get_config("razorpay") is None
    settings.RAZORPAY_ENABLED = True
    assert get_config("razorpay")["key_id"] == "rzp_test_environment"


def test_checkout_page_does_not_create_provider_order(client, customer, online_order):
    order, _ = online_order
    client.force_login(customer)
    with patch("apps.payments.services.start_payment") as start:
        response = client.get(reverse("payments:pay", args=[order.public_id]))
    assert response.status_code == 200
    assert response["Cross-Origin-Opener-Policy"] == "same-origin-allow-popups"
    assert client.get("/")["Cross-Origin-Opener-Policy"] == "same-origin"
    start.assert_not_called()


def test_checkout_posts_require_csrf(customer, online_order):
    from django.test import Client

    order, _ = online_order
    browser = Client(enforce_csrf_checks=True)
    browser.force_login(customer)
    for endpoint in ("create_order", "verify_payment"):
        assert browser.post(reverse(f"payments:{endpoint}", args=[order.public_id])).status_code == 403


def test_verification_outage_does_not_mark_paid(client, customer, online_order):
    order, payment = online_order
    client.force_login(customer)
    with patch("apps.payments.services.handle_return", side_effect=RuntimeError("provider unavailable")):
        response = client.post(
            reverse("payments:verify_payment", args=[order.public_id]),
            checkout_data(payment),
            content_type="application/json",
        )
    assert response.status_code == 503
    order.refresh_from_db()
    assert order.payment_status != "paid"
