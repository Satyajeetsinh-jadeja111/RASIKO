import hashlib
import hmac
import json
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest

from apps.core.integrations import clear_cache
from apps.core.models import Integration, StoreSettings
from apps.payments.gateways import GatewayError, get_gateway
from apps.payments.models import Payment
from apps.payments.services import handle_webhook


@pytest.fixture
def stripe_on(db):
    row = Integration.objects.create(slug="stripe", enabled=True)
    row.update_values({"publishable_key": "pk_test_1", "secret_key": "sk_test_1", "webhook_secret": "whsec_s"})
    row.save()
    s = StoreSettings.load()
    s.active_gateway = "stripe"
    s.save()
    clear_cache("stripe")
    return row


def stripe_signed(event, secret="whsec_s"):
    payload = json.dumps(event).encode()
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return payload, {"Stripe-Signature": f"t={ts},v1={sig}"}


@pytest.mark.django_db
def test_stripe_payment_flow(place, stripe_on, variant):
    order = place(qty=4, method="stripe")
    gw = get_gateway("stripe")
    payment = Payment.objects.create(order=order, gateway="stripe", amount=order.total)
    with mock.patch("stripe.StripeClient") as sc:
        sc.return_value.v1.payment_intents.create.return_value = SimpleNamespace(id="pi_1", client_secret="cs_1")
        data = gw.create_payment(order, payment)
    kwargs = sc.return_value.v1.payment_intents.create.call_args.kwargs
    assert kwargs["params"]["amount"] == int(order.total * 100) and kwargs["params"]["currency"] == "inr"
    assert data == {"gateway": "stripe", "publishable_key": "pk_test_1", "client_secret": "cs_1"}
    event = {
        "id": "evt_s1",
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_1",
                "object": "payment_intent",
                "amount": int(order.total * 100),
                "latest_charge": "ch_1",
            }
        },
    }
    body, headers = stripe_signed(event)
    assert handle_webhook("stripe", body, headers) == "payment_succeeded"
    order.refresh_from_db()
    assert order.payment_status == "paid"

    with mock.patch("stripe.StripeClient") as sc:
        sc.return_value.v1.refunds.create.return_value = SimpleNamespace(id="re_1", status="pending")
        rid, status = gw.refund(Payment.objects.get(pk=payment.pk), Decimal("10"), "k1", {})
    assert (rid, status) == ("re_1", "pending")


@pytest.mark.django_db
def test_stripe_bad_signature(stripe_on):
    body, headers = stripe_signed({"id": "evt", "type": "x", "data": {"object": {}}}, secret="nope")
    with pytest.raises(GatewayError):
        handle_webhook("stripe", body, headers)


@pytest.mark.django_db
def test_stripe_return_checks_intent(place, stripe_on, client, customer):
    order = place(qty=4, method="stripe")
    Payment.objects.create(order=order, gateway="stripe", amount=order.total, gateway_order_id="pi_2")
    client.force_login(customer)
    with mock.patch("stripe.StripeClient") as sc:
        sc.return_value.v1.payment_intents.retrieve.return_value = SimpleNamespace(
            status="processing", latest_charge=None, id="pi_2"
        )
        r = client.get(f"/payments/pay/{order.public_id}/stripe/")
    assert r["Location"] == order.get_absolute_url()
    with mock.patch("stripe.StripeClient") as sc:
        sc.return_value.v1.payment_intents.retrieve.return_value = SimpleNamespace(
            status="succeeded", latest_charge="ch_2", id="pi_2"
        )
        r = client.get(f"/payments/pay/{order.public_id}/stripe/")
    assert r["Location"].endswith("/thank-you/")
