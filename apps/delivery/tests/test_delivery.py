from datetime import datetime, time
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.delivery.models import DeliverySettings, FeeSlab, Holiday, ServicePincode, StoreHours
from apps.delivery.services import (
    HaversineDistance,
    available_slots,
    check_service_area,
    compute_fee,
    delivery_cost,
    is_open,
    point_in_polygon,
    quote,
)
from conftest import LAT, LNG

D = Decimal
NOON = timezone.make_aware(datetime(2026, 9, 26, 13, 0))


def fee(shop, subtotal, km, now=NOON):
    return compute_fee(D(subtotal), D(km), shop, list(FeeSlab.objects.order_by("min_km")), now)


@pytest.mark.django_db
class TestFees:
    def test_minimum_order(self, shop):
        q = fee(shop, 80, 2)
        assert not q.ok and "Minimum order" in str(q.message)

    def test_slab_fee_and_small_order_fee(self, shop):
        q = fee(shop, 120, 2)
        assert q.ok and q.delivery_fee == D("25")
        assert q.small_order_fee == shop.small_order_fee  # below ₹149 by default
        assert q.amount_for_free == shop.free_near_threshold - D("120")

    def test_free_nearby_above_threshold(self, shop):
        q = fee(shop, shop.free_near_threshold, 4)
        assert q.delivery_fee == 0 and q.free_reason

    def test_far_needs_higher_threshold(self, shop):
        q = fee(shop, shop.free_near_threshold, 8)
        assert q.delivery_fee == D("45")
        q2 = fee(shop, shop.free_anywhere_threshold, 12)
        assert q2.delivery_fee == 0

    def test_outside_slabs(self, shop):
        assert not fee(shop, 500, 20).ok

    def test_late_night_and_rain_surcharges(self, shop):
        shop.late_night_enabled, shop.late_night_after, shop.late_night_fee = True, time(22, 0), D("20")
        shop.rain_peak_enabled, shop.rain_peak_fee = True, D("15")
        q = fee(shop, 300, 2, timezone.make_aware(datetime(2026, 9, 26, 22, 30)))
        assert q.surcharge_total == D("35") and q.total == q.delivery_fee + D("35")

    def test_delivery_cost(self, shop):
        shop.rider_pay_per_order, shop.packaging_per_order, shop.fuel_cost_per_km = D("20"), D("3"), D("2.5")
        assert delivery_cost(D("4"), shop) == D("43.00")


@pytest.mark.django_db
class TestArea:
    def test_inside_radius_and_known_pincode(self, shop):
        r = check_service_area(LAT + D("0.01"), LNG, "360005")
        assert r.ok and r.fast and D("1") < r.road_km < D("2")

    def test_outside_radius(self, shop):
        r = check_service_area(LAT + D("0.5"), LNG, "360005")
        assert not r.ok

    def test_unknown_pincode_when_enforced(self, shop):
        shop.enforce_pincodes = True
        shop.save()
        assert not check_service_area(LAT, LNG, "999999").ok

    def test_inactive_pincode(self, shop):
        ServicePincode.objects.filter(code="360001").update(is_active=False)
        DeliverySettings.objects.update(enforce_pincodes=True)
        assert not check_service_area(LAT, LNG, "360001").ok

    def test_polygon(self, shop):
        square = [[22.2, 70.7], [22.2, 70.9], [22.4, 70.9], [22.4, 70.7]]
        assert point_in_polygon(22.3, 70.8, square)
        assert not point_in_polygon(22.5, 70.8, square)
        shop.polygon = [[22.35, 70.85], [22.35, 70.9], [22.4, 70.9], [22.4, 70.85]]
        shop.save()
        assert not check_service_area(LAT, LNG, "360005").ok

    def test_quote_combines_area_and_fees(self, shop):
        q = quote(shop.free_near_threshold, LAT + D("0.01"), LNG, "360005", now=NOON)
        assert q.ok and q.delivery_fee == 0 and q.eta_text

    def test_haversine_road_factor(self):
        km = HaversineDistance(D("1.3")).road_km(22.3, 70.8, 22.31, 70.8)
        assert D("1.4") < km < D("1.5")


@pytest.mark.django_db
class TestHours:
    def test_closed_day_and_holiday(self, shop):
        now = timezone.make_aware(datetime(2026, 9, 26, 13, 0))
        assert is_open(now)
        Holiday.objects.create(date=now.date(), note="Diwali")
        assert not is_open(now)

    def test_slots_skip_closed_days(self, shop):
        now = timezone.make_aware(datetime(2026, 9, 26, 13, 0))
        StoreHours.objects.filter(weekday=now.weekday()).update(is_closed=True)
        slots = available_slots(now)
        assert slots and all(not s[0].startswith("2026-09-26") for s in slots)
