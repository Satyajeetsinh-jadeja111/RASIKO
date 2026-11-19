from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.catalog.models import BackInStockRequest
from apps.inventory.models import StockReservation
from apps.inventory.tasks import expire_reservations, send_back_in_stock
from apps.notifications.models import EmailLog
from apps.orders.models import Order
from apps.orders.services import mark_paid, reorder_into_cart, set_status
from apps.orders.tasks import run_subscriptions, send_rate_email
from apps.payments.models import Payment
from apps.promotions.models import CoinLedger
from apps.promotions.tasks import birthday_coins


@pytest.mark.django_db
def test_rate_email_after_delivery(place):
    o = place(qty=3)
    for s in ["confirmed", "packed", "out_for_delivery", "delivered"]:
        o = set_status(o, s)
    send_rate_email(o.pk)
    send_rate_email(o.pk)  # only once
    assert EmailLog.objects.filter(template="rate_order").count() == 1


@pytest.mark.django_db
def test_back_in_stock_emails(variant):
    variant.manual_out_of_stock = True
    variant.save()
    BackInStockRequest.objects.create(variant=variant, email="fan@example.com")
    assert send_back_in_stock(variant.pk) == 0
    variant.manual_out_of_stock = False
    variant.save()
    assert send_back_in_stock(variant.pk) == 1
    assert send_back_in_stock(variant.pk) == 0


@pytest.mark.django_db
def test_late_payment_after_timeout(place, razorpay_on, variant):
    o = place(qty=4, method="razorpay")
    StockReservation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    expire_reservations()
    o.refresh_from_db()
    assert o.status == "payment_failed"
    mark_paid(o, Payment.objects.create(order=o, gateway="razorpay", amount=o.total))
    o.refresh_from_db()
    variant.refresh_from_db()
    assert o.status == "payment_failed" and o.payment_status == "paid" and variant.stock_qty == 20
    assert "refund required" in o.staff_note


@pytest.mark.django_db(transaction=True)
def test_paid_order_cancelled_by_customer_is_refunded(place, razorpay_on):
    from apps.orders.services import cancel_by_customer

    o = place(qty=4, method="razorpay")
    mark_paid(o, Payment.objects.create(order=o, gateway="razorpay", amount=o.total, status="succeeded"))
    o.refresh_from_db()
    with mock.patch(
        "apps.payments.gateways.razorpay_gateway.RazorpayGateway.refund", return_value=("rfnd_c", "succeeded")
    ):
        cancel_by_customer(o, "Changed plan")
    o.refresh_from_db()
    assert o.status == "refunded" and o.refunded_total == o.total


@pytest.mark.django_db
def test_reorder_skips_unavailable(place, variant):
    from apps.cart.cart import DictCart

    o = place(qty=3)
    variant.is_active = False
    variant.save()
    cart = DictCart({})
    added = reorder_into_cart(Order.objects.get(pk=o.pk), cart)
    assert not cart.data and not added


@pytest.mark.django_db
def test_birthday_coins_once_a_year(customer):
    customer.birthday = timezone.localdate().replace(year=1995)
    customer.save()
    assert birthday_coins() == 1
    assert birthday_coins() == 0
    assert CoinLedger.objects.filter(user=customer, reason="birthday").count() == 1


@pytest.mark.django_db
def test_run_subscriptions_task(customer):
    assert run_subscriptions() == 0
