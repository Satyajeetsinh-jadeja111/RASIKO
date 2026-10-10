import io
import re
from datetime import time, timedelta
from unittest import mock

import pytest
from django.utils import timezone
from PIL import Image

from apps.accounts.models import OneTimeCode
from apps.orders.models import BulkQuote, Order, Subscription, ThanduComplaint
from apps.orders.services import set_status
from apps.orders.subscriptions import run_due


def add_to_cart(client, variant, qty):
    client.post("/cart/update/", {"key": f"v:{variant.pk}", "qty": qty}, HTTP_ACCEPT="application/json")


def checkout_token(client):
    r = client.get("/orders/checkout/")
    assert r.status_code == 200
    return re.search(r'name="checkout_token" value="([^"]+)"', r.content.decode()).group(1)


@pytest.mark.django_db
class TestCheckoutFlow:
    def test_cod_checkout_end_to_end(self, client, customer, address, variant):
        client.force_login(customer)
        add_to_cart(client, variant, 4)
        token = checkout_token(client)
        r = client.post(
            "/orders/checkout/",
            {"checkout_token": token, "payment_method": "cod", "slot": "asap", "address": str(address.public_id)},
        )
        order = Order.objects.get()
        assert r["Location"] == f"/orders/{order.public_id}/thank-you/"
        assert order.status == "placed" and order.total > 0
        page = client.get(r["Location"]).content.decode()
        assert "Shubh Labh" in page and order.number in page
        assert client.get("/cart/").context["cart"].count == 0
        # the same token cannot place a second order
        r = client.post("/orders/checkout/", {"checkout_token": token, "payment_method": "cod"})
        assert Order.objects.count() == 1

    def test_checkout_needs_address_and_items(self, client, customer, variant):
        client.force_login(customer)
        assert client.get("/orders/checkout/")["Location"] == "/cart/"
        add_to_cart(client, variant, 3)
        assert "/accounts/addresses/new/" in client.get("/orders/checkout/")["Location"]

    def test_online_checkout_goes_to_pay_page(self, client, customer, address, variant, razorpay_on):
        client.force_login(customer)
        add_to_cart(client, variant, 4)
        token = checkout_token(client)
        r = client.post("/orders/checkout/", {"checkout_token": token, "payment_method": "razorpay"})
        order = Order.objects.get()
        assert order.status == "pending_payment" and r["Location"] == f"/payments/pay/{order.public_id}/"
        with mock.patch("razorpay.Client") as rc:
            rc.return_value.order.create.return_value = {
                "id": "order_R1",
                "amount": int(order.total * 100),
                "currency": "INR",
            }
            page = client.get(r["Location"]).content.decode()
        assert "order_R1" in page and "rzp_test_abc" in page and "test_secret" not in page
        r = client.post(f"/payments/pay/{order.public_id}/cancel/")
        order.refresh_from_db()
        variant.refresh_from_db()
        assert order.status == "payment_failed" and variant.reserved_qty == 0

    def test_live_delivery_quote(self, client, variant, address):
        add_to_cart(client, variant, 3)
        r = client.post(
            "/orders/checkout/quote/", {"lat": str(address.lat), "lng": str(address.lng), "pincode": "360005"}
        ).json()
        assert r["ok"] and float(r["km"]) > 0
        r = client.post("/orders/checkout/quote/", {"lat": "23.5", "lng": "72.5", "pincode": "360005"}).json()
        assert not r["ok"]


@pytest.mark.django_db
class TestAfterOrder:
    def test_detail_invoice_cancel_reorder(self, client, customer, place):
        o = place(qty=3)
        client.force_login(customer)
        assert client.get(o.get_absolute_url()).status_code == 200
        r = client.get(f"/orders/{o.public_id}/invoice/")
        assert r["Content-Type"] == "application/pdf" and r.content[:4] == b"%PDF"
        client.post(f"/orders/{o.public_id}/cancel/", {"reason": "Ordered twice"})
        o.refresh_from_db()
        assert o.status == "cancelled"
        client.post(f"/orders/{o.public_id}/reorder/")
        assert client.get("/cart/").context["cart"].count == 3

    def test_thandu_complaint_with_photo(self, client, customer, place):
        o = place(qty=3)
        for s in ["confirmed", "packed", "out_for_delivery", "delivered"]:
            o = set_status(o, s)
        client.force_login(customer)
        buf = io.BytesIO()
        Image.new("RGB", (40, 40), (255, 200, 0)).save(buf, "JPEG")
        buf.name = "warm.jpg"
        buf.seek(0)
        client.post(f"/orders/{o.public_id}/thandu/", {"photo": buf, "note": "Not cold"})
        c = ThanduComplaint.objects.get()
        assert c.state == "pending" and c.photo.name.endswith(".webp")

    def test_guest_tracking_needs_code(self, client, place, customer):
        o = place(qty=3)
        with mock.patch("apps.orders.views.notify.customer_email") as sent:
            r = client.post("/orders/track/", {"number": o.number, "contact": "9876543210", "step": "send"})
        assert r.context["ask_code"]
        code = sent.call_args.args[2]["code"]
        with mock.patch("apps.orders.views.notify.customer_email") as nothing:
            client.post("/orders/track/", {"number": o.number, "contact": "9999999999", "step": "send"})
        nothing.assert_not_called()  # wrong contact: same message, no code sent
        r = client.post("/orders/track/", {"number": o.number, "contact": "9876543210", "step": "verify", "code": code})
        assert r["Location"].endswith(f"?o={o.public_id}")
        assert o.number in client.get(r["Location"]).content.decode()
        other = client.__class__()
        assert other.get(r["Location"]).context["order"] is None

    def test_bulk_quote(self, client):
        r = client.post(
            "/orders/party/",
            {
                "name": "Mehul",
                "phone": "9876500000",
                "email": "m@example.com",
                "kind": "wedding",
                "requirements": "40 crates of cola",
                "event_date": (timezone.localdate() + timedelta(days=10)).isoformat(),
            },
        )
        assert r.status_code == 302 and BulkQuote.objects.get().name == "Mehul"


@pytest.mark.django_db
class TestSubscriptions:
    def test_create_run_skip_and_pause(self, client, customer, address, variant):
        client.force_login(customer)
        client.post(
            "/orders/subscriptions/",
            {"variant": variant.pk, "qty": 3, "frequency": "daily", "address": address.pk, "delivery_time": "07:30"},
        )
        sub = Subscription.objects.get()
        assert sub.state == "active"
        assert run_due(sub.next_run) == 1
        o = Order.objects.get()
        assert o.source == "subscription" and o.payment_method == "cod"
        sub.refresh_from_db()
        client.post(f"/orders/subscriptions/{sub.public_id}/", {"action": "skip"})
        sub.refresh_from_db()
        assert run_due(sub.next_run) == 0
        client.post(f"/orders/subscriptions/{sub.public_id}/", {"action": "pause"})
        sub.refresh_from_db()
        assert sub.state == "paused" and run_due(sub.next_run + timedelta(days=5)) == 0
        assert sub.delivery_time == time(7, 30)


@pytest.mark.django_db
def test_otp_is_hashed(customer):
    OneTimeCode.issue(OneTimeCode.Purpose.PHONE_VERIFY, "9876543210")
    row = OneTimeCode.objects.get()
    assert len(row.code_hash) >= 32 and not row.code_hash.isdigit()
