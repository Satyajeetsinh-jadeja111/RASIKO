"""Service area checks and the delivery fee engine. Always run on the server; the browser only displays."""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.utils import timezone
from django.utils.translation import gettext as _

from .models import DeliverySettings, FeeSlab, Holiday, ServicePincode, StoreHours

ZERO = Decimal("0")
OUTSIDE_MSG = "We deliver only within Rajkot city. Please choose an address inside our delivery area."


def money(x) -> Decimal:
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---- Distance ------------------------------------------------------------------


class DistanceProvider:
    """Swap for a routing API (e.g. OSRM) later by implementing road_km."""

    def road_km(self, lat1, lng1, lat2, lng2) -> Decimal:
        raise NotImplementedError


class HaversineDistance(DistanceProvider):
    def __init__(self, road_factor: Decimal):
        self.road_factor = Decimal(road_factor)

    @staticmethod
    def straight_km(lat1, lng1, lat2, lng2) -> float:
        r = 6371.0088
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dp = p2 - p1
        dl = math.radians(float(lng2) - float(lng1))
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    def road_km(self, lat1, lng1, lat2, lng2) -> Decimal:
        return (Decimal(str(self.straight_km(lat1, lng1, lat2, lng2))) * self.road_factor).quantize(Decimal("0.01"))


def distance_provider(cfg=None) -> DistanceProvider:
    cfg = cfg or DeliverySettings.load()
    return HaversineDistance(cfg.road_factor)


def point_in_polygon(lat, lng, polygon) -> bool:
    x, y = float(lng), float(lat)
    inside = False
    n = len(polygon)
    for i in range(n):
        y1, x1 = map(float, polygon[i])
        y2, x2 = map(float, polygon[(i + 1) % n])
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            inside = not inside
    return inside


# ---- Service area --------------------------------------------------------------


@dataclass
class AreaResult:
    ok: bool
    message: str = ""
    road_km: Decimal = ZERO
    pincode: ServicePincode | None = None

    @property
    def fast(self):
        return bool(self.pincode and self.pincode.fast_delivery)


def check_service_area(lat, lng, pincode) -> AreaResult:
    cfg = DeliverySettings.load()
    try:
        lat, lng = Decimal(str(lat)), Decimal(str(lng))
    except (InvalidOperation, TypeError, ValueError):
        return AreaResult(False, _("Please drop a pin on the map."))
    if not (Decimal("-90") <= lat <= Decimal("90") and Decimal("-180") <= lng <= Decimal("180")):
        return AreaResult(False, _("Please drop a pin on the map."))
    pin = ServicePincode.objects.filter(code=str(pincode).strip()).first()
    if cfg.enforce_pincodes and (pin is None or not pin.is_active):
        return AreaResult(False, _(OUTSIDE_MSG))
    straight = HaversineDistance.straight_km(cfg.store_lat, cfg.store_lng, lat, lng)
    if straight > float(cfg.radius_km):
        return AreaResult(False, _(OUTSIDE_MSG))
    if cfg.polygon and len(cfg.polygon) >= 3 and not point_in_polygon(lat, lng, cfg.polygon):
        return AreaResult(False, _(OUTSIDE_MSG))
    road = distance_provider(cfg).road_km(cfg.store_lat, cfg.store_lng, lat, lng)
    return AreaResult(True, "", road, pin)


# ---- Fees ----------------------------------------------------------------------


@dataclass
class DeliveryQuote:
    ok: bool
    message: str = ""
    road_km: Decimal = ZERO
    slab_fee: Decimal = ZERO
    delivery_fee: Decimal = ZERO
    small_order_fee: Decimal = ZERO
    surcharges: list = field(default_factory=list)  # [(label, amount)]
    free_reason: str = ""
    amount_for_free: Decimal = ZERO
    fast: bool = False
    eta_text: str = ""

    @property
    def surcharge_total(self):
        return sum((a for _, a in self.surcharges), ZERO)

    @property
    def total(self):
        return money(self.delivery_fee + self.small_order_fee + self.surcharge_total)


def slab_fee_for(road_km: Decimal, slabs=None) -> Decimal | None:
    slabs = slabs if slabs is not None else list(FeeSlab.objects.all())
    for s in slabs:
        if s.min_km <= road_km < s.max_km or (road_km == s.max_km and s is slabs[-1]):
            return s.fee
    return None


def compute_fee(subtotal: Decimal, road_km: Decimal, cfg, slabs, now=None) -> DeliveryQuote:
    """Pure fee rules (also used by the what-if calculator)."""
    subtotal = money(subtotal)
    q = DeliveryQuote(ok=True, road_km=road_km)
    if subtotal < cfg.min_order_value:
        return DeliveryQuote(False, _("Minimum order is ₹%(v)s.") % {"v": cfg.min_order_value}, road_km)
    fee = slab_fee_for(road_km, slabs)
    if fee is None:
        return DeliveryQuote(False, _(OUTSIDE_MSG), road_km)
    q.slab_fee = fee
    if subtotal >= cfg.free_anywhere_threshold:
        q.free_reason = _("Free delivery on orders above ₹%(v)s") % {"v": cfg.free_anywhere_threshold}
    elif subtotal >= cfg.free_near_threshold and road_km <= cfg.free_near_max_km:
        q.free_reason = _("Free delivery above ₹%(v)s nearby") % {"v": cfg.free_near_threshold}
    else:
        q.delivery_fee = fee
        target = cfg.free_near_threshold if road_km <= cfg.free_near_max_km else cfg.free_anywhere_threshold
        q.amount_for_free = money(target - subtotal)
    if subtotal < cfg.small_order_below:
        q.small_order_fee = cfg.small_order_fee
    now = timezone.localtime(now or timezone.now())
    if cfg.late_night_enabled and now.time() >= cfg.late_night_after:
        q.surcharges.append((_("Late-night delivery"), cfg.late_night_fee))
    if cfg.rain_peak_enabled:
        q.surcharges.append((_("Rain / peak hours"), cfg.rain_peak_fee))
    return q


def quote(subtotal, lat, lng, pincode, now=None) -> DeliveryQuote:
    area = check_service_area(lat, lng, pincode)
    if not area.ok:
        return DeliveryQuote(False, area.message)
    cfg = DeliverySettings.load()
    q = compute_fee(Decimal(subtotal), area.road_km, cfg, list(FeeSlab.objects.all()), now)
    q.fast = area.fast
    q.eta_text = eta_text(area.fast, cfg)
    return q


def delivery_cost(road_km: Decimal, cfg=None) -> Decimal:
    """What one delivery really costs the business (for the economics report)."""
    cfg = cfg or DeliverySettings.load()
    return money(cfg.rider_pay_per_order + cfg.packaging_per_order + cfg.fuel_cost_per_km * road_km * 2)


def eta_text(fast: bool, cfg=None) -> str:
    cfg = cfg or DeliverySettings.load()
    if fast:
        return _("in %(m)s min") % {"m": cfg.fast_promise_minutes}
    return _("in %(a)s–%(b)s min") % {"a": cfg.asap_min_minutes, "b": cfg.asap_max_minutes}


# ---- Hours and slots -----------------------------------------------------------


def hours_for(day):
    if Holiday.objects.filter(date=day).exists():
        return None
    h = StoreHours.objects.filter(weekday=day.weekday()).first()
    if h is None:
        return (datetime.min.time().replace(hour=8), datetime.min.time().replace(hour=23))
    if h.is_closed:
        return None
    return (h.opens, h.closes)


def is_open(now=None) -> bool:
    now = timezone.localtime(now or timezone.now())
    hours = hours_for(now.date())
    return bool(hours and hours[0] <= now.time() < hours[1])


def available_slots(now=None):
    """[(value 'YYYY-MM-DDTHH:MM', label)] for scheduled delivery, starting at least 1 hour from now."""
    cfg = DeliverySettings.load()
    now = timezone.localtime(now or timezone.now())
    earliest = now + timedelta(hours=1)
    slots = []
    for d in range(cfg.slot_days_ahead + 1):
        day = (now + timedelta(days=d)).date()
        hours = hours_for(day)
        if not hours:
            continue
        tz = now.tzinfo
        start = datetime.combine(day, hours[0], tzinfo=tz)
        end = datetime.combine(day, hours[1], tzinfo=tz)
        cur = start
        while cur + timedelta(minutes=cfg.slot_minutes) <= end:
            if cur >= earliest:
                label_day = _("Today") if d == 0 else (_("Tomorrow") if d == 1 else cur.strftime("%a %d %b"))
                nxt = cur + timedelta(minutes=cfg.slot_minutes)
                slots.append((cur.strftime("%Y-%m-%dT%H:%M"), f"{label_day}, {cur:%I:%M %p}–{nxt:%I:%M %p}"))
            cur += timedelta(minutes=cfg.slot_minutes)
    return slots
