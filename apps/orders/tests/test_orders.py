from decimal import Decimal

import pytest

from apps.cart.cart import DictCart
from apps.orders.models import Order
from apps.orders.pricing import price_cart
from apps.orders.services import CheckoutError, cancel_by_customer, place_order, set_status
from apps.promotions.models import CoinLedger, Coupon, coin_balance

D = Decimal


@pytest.mark.django_db
class TestPlaceOrder:
    def test_cod_order_totals(self, place, variant):
        o = place(qty=3)  # 3 x ₹50 = ₹150
        assert o.status == "placed" and o.payment_status == "cod_due"
        assert o.subtotal == D("150") and o.number.startswith("RSK")
        assert o.total == o.subtotal + o.delivery_fee + o.small_order_fee + o.surcharge_total
        line = o.lines.get()
        assert line.unit_price == D("50") and line.unit_cost == D("35") and line.gst_rate == D("12")
        assert o.events.filter(status="placed").exists()

    def test_same_checkout_token_is_idempotent(self, customer, address, variant):
        cart = DictCart({f"v:{variant.pk}": 3})
        a = place_order(user=customer, cart=cart, address=address, payment_method="cod", checkout_token="tok-1")
        b = place_order(user=customer, cart=cart, address=address, payment_method="cod", checkout_token="tok-1")
        assert a.pk == b.pk and Order.objects.count() == 1

    def test_cod_needs_verified_phone(self, place, customer):
        customer.phone_verified = False
        customer.save()
        with pytest.raises(CheckoutError):
            place(qty=3)

    def test_cod_blocked_customer(self, place, customer):
        customer.cod_blocked = True
        customer.save()
        with pytest.raises(CheckoutError):
            place(qty=3)

    def test_online_needs_enabled_gateway(self, place):
        with pytest.raises(CheckoutError):
            place(qty=3, method="razorpay")

    def test_max_per_order(self, place, variant):
        variant.max_per_order = 2
        variant.save()
        with pytest.raises(CheckoutError):
            place(qty=3)

    def test_prices_come_from_server(self, customer, address, variant):
        cart = DictCart({f"v:{variant.pk}": 4})
        variant.price = D("40")
        variant.save()
        t = price_cart(cart, customer, location=(address.lat, address.lng, address.pincode))
        assert t.subtotal == D("160")


@pytest.mark.django_db
class TestCouponsAndCoins:
    def test_coupon_discount_and_single_use(self, place, customer):
        Coupon.objects.create(code="SHUBH20", kind="flat", value=D("20"), min_order=D("100"))
        o = place(qty=3, coupon_code="SHUBH20")
        assert o.discount == D("20") and o.coupon_code == "SHUBH20"
        with pytest.raises(CheckoutError):
            place(qty=3, coupon_code="SHUBH20")

    def test_coupon_min_order(self, customer, address, variant):
        Coupon.objects.create(code="BIG", kind="percent", value=D("10"), min_order=D("500"))
        t = price_cart(
            DictCart({f"v:{variant.pk}": 3}), customer, "BIG", location=(address.lat, address.lng, address.pincode)
        )
        assert t.discount == 0 and "more" in t.coupon_error

    def test_coins_capped_and_spent(self, place, customer):
        CoinLedger.objects.create(user=customer, delta=500, reason="adjust")
        o = place(qty=4, use_coins=True)  # ₹200, max 20% = ₹40
        assert o.coins_used == 40 and o.coins_value == D("40")
        assert coin_balance(customer) == 460


@pytest.mark.django_db
class TestStatus:
    def test_happy_path_awards_coins(self, place, customer, staff_user):
        o = place(qty=4)
        for s in ["confirmed", "packed", "out_for_delivery", "delivered"]:
            o = set_status(o, s, by=staff_user)
        assert o.status == "delivered" and o.payment_status == "cod_collected" and o.delivered_at
        assert coin_balance(customer) > 0
        assert o.lines.get().variant.product.__class__.objects.get().sold_count == 4

    def test_invalid_transition(self, place):
        o = place(qty=3)
        with pytest.raises(ValueError):
            set_status(o, "delivered")

    def test_cancel_restocks(self, place, variant, staff_user):
        o = place(qty=3)
        set_status(o, "cancelled", by=staff_user, note="Customer asked")
        variant.refresh_from_db()
        assert variant.stock_qty == 20

    def test_customer_cancel_only_early(self, place, staff_user):
        o = place(qty=3)
        cancel_by_customer(o, "Changed my mind")
        o.refresh_from_db()
        assert o.status == "cancelled"
        o2 = place(qty=3)
        set_status(o2, "packed")
        with pytest.raises(ValueError):
            cancel_by_customer(Order.objects.get(pk=o2.pk), "late")
