from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.promotions.models import Coupon
from apps.promotions.services import CouponError, make_personal_coupon, validate_coupon

D = Decimal


@pytest.mark.django_db
class TestCoupons:
    def test_percent_with_cap(self, customer):
        Coupon.objects.create(code="SWAAD10", kind="percent", value=D("10"), max_discount=D("30"))
        assert validate_coupon("swaad10", customer, D("500"))[1] == D("30")

    def test_expired(self, customer):
        Coupon.objects.create(code="OLD", kind="flat", value=D("10"), expires_at=timezone.now() - timedelta(days=1))
        with pytest.raises(CouponError):
            validate_coupon("OLD", customer, D("500"))

    def test_personal_coupon_only_for_owner(self, customer, django_user_model):
        c = make_personal_coupon(customer, D("30"))
        assert validate_coupon(c.code, customer, D("100"))[1] == D("30")
        other = django_user_model.objects.create_user(email="o@example.com", password="Other-Pass-2026!")
        with pytest.raises(CouponError):
            validate_coupon(c.code, other, D("100"))

    def test_first_order_only(self, customer, place):
        Coupon.objects.create(code="FIRST", kind="flat", value=D("25"), first_order_only=True)
        place(qty=3)
        with pytest.raises(CouponError):
            validate_coupon("FIRST", customer, D("200"))
