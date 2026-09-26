from datetime import timedelta

import pytest
from django.utils import timezone

from apps.inventory.models import StockMovement, StockReservation
from apps.inventory.services import OutOfStock, adjust_stock, expire_reservations
from apps.orders.services import CheckoutError


@pytest.mark.django_db
class TestStock:
    def test_adjust_logs_movement(self, variant, owner):
        adjust_stock(variant.pk, 5, StockMovement.Reason.MANUAL, user=owner)
        variant.refresh_from_db()
        assert variant.stock_qty == 25
        m = StockMovement.objects.get()
        assert m.delta == 5 and m.balance_after == 25 and m.user == owner

    def test_set_to_and_never_negative(self, variant):
        adjust_stock(variant.pk, 0, StockMovement.Reason.MANUAL, set_to=7)
        variant.refresh_from_db()
        assert variant.stock_qty == 7
        with pytest.raises(OutOfStock):
            adjust_stock(variant.pk, -8, StockMovement.Reason.DAMAGE)

    def test_cod_order_deducts(self, place, variant):
        place(qty=3)
        variant.refresh_from_db()
        assert variant.stock_qty == 17 and variant.reserved_qty == 0

    def test_cannot_oversell(self, place, variant):
        variant.stock_qty = 2
        variant.save()
        with pytest.raises(CheckoutError):
            place(qty=3)
        variant.refresh_from_db()
        assert variant.stock_qty == 2

    def test_manual_out_of_stock_blocks_checkout(self, place, variant):
        variant.manual_out_of_stock = True
        variant.save()
        with pytest.raises(CheckoutError):
            place(qty=3)

    def test_online_order_reserves_then_expires(self, place, variant, razorpay_on):
        order = place(qty=4, method="razorpay")
        variant.refresh_from_db()
        assert order.status == "pending_payment"
        assert variant.stock_qty == 20 and variant.reserved_qty == 4 and variant.available_qty == 16
        StockReservation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        expire_reservations()
        variant.refresh_from_db()
        order.refresh_from_db()
        assert variant.reserved_qty == 0 and order.status == "payment_failed"

    def test_reservations_block_others(self, place, variant, razorpay_on):
        variant.stock_qty = 5
        variant.save()
        place(qty=4, method="razorpay")
        with pytest.raises(CheckoutError):
            place(qty=2)
