"""Sales numbers used by the dashboard, the exports, the insights engine and the summary emails.

Revenue counts orders that were placed and not cancelled or failed; refunds are shown separately.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay, TruncDate
from django.utils import timezone

from apps.orders.models import Order, OrderLine

ZERO = Decimal("0")
COUNTED = ["placed", "confirmed", "packed", "out_for_delivery", "delivered", "refunded"]


@dataclass
class Period:
    start: datetime
    end: datetime

    @property
    def days(self):
        return max(1, (self.end - self.start).days)

    def previous(self):
        length = self.end - self.start
        return Period(self.start - length, self.start)

    @classmethod
    def last_days(cls, days, now=None):
        now = timezone.localtime(now or timezone.now())
        end = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo)
        return cls(end - timedelta(days=days), end)

    @classmethod
    def between(cls, start: date, end: date):
        tz = timezone.get_current_timezone()
        return cls(
            datetime.combine(start, time.min, tzinfo=tz), datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
        )


def orders_in(p: Period):
    return Order.objects.filter(placed_at__gte=p.start, placed_at__lt=p.end)


def lines_in(p: Period):
    return OrderLine.objects.filter(
        order__placed_at__gte=p.start, order__placed_at__lt=p.end, order__status__in=COUNTED
    )


def pct(new, old):
    if not old:
        return None
    return round(float((Decimal(new) - Decimal(old)) / Decimal(old) * 100), 1)


def kpis(p: Period) -> dict:
    all_orders = orders_in(p).exclude(status="pending_payment")
    counted = all_orders.filter(status__in=COUNTED)
    agg = counted.aggregate(
        n=Count("id"),
        revenue=Sum("total"),
        delivery_fees=Sum("delivery_fee"),
        small_fees=Sum("small_order_fee"),
        surcharges=Sum("surcharge_total"),
        discount=Sum("discount"),
        coins=Sum("coins_value"),
        delivery_cost=Sum("delivery_cost"),
        gst=Sum("gst_total"),
    )
    n = agg["n"] or 0
    revenue = agg["revenue"] or ZERO
    margin_expr = ExpressionWrapper(
        (F("unit_price") - F("unit_cost")) * (F("qty") - F("refunded_qty")),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    gross = lines_in(p).filter(unit_cost__gt=0).aggregate(m=Sum(margin_expr))["m"] or ZERO
    customers = counted.values("user").distinct().count()
    repeat = counted.values("user").annotate(c=Count("id")).filter(c__gt=1).count()
    new_customers = counted.filter(user__date_joined__gte=p.start).values("user").distinct().count()
    cancelled = all_orders.filter(status="cancelled").count()
    from apps.payments.models import Refund

    refunds = (
        Refund.objects.filter(created_at__gte=p.start, created_at__lt=p.end, status="succeeded").aggregate(
            s=Sum("amount")
        )["s"]
        or ZERO
    )
    fees = (agg["delivery_fees"] or ZERO) + (agg["small_fees"] or ZERO) + (agg["surcharges"] or ZERO)
    return {
        "orders": n,
        "revenue": revenue,
        "aov": (revenue / n).quantize(Decimal("0.01")) if n else ZERO,
        "gross_margin": gross,
        "customers": customers,
        "new_customers": new_customers,
        "repeat_rate": round(repeat * 100 / customers, 1) if customers else 0,
        "cancel_rate": round(cancelled * 100 / all_orders.count(), 1) if all_orders.count() else 0,
        "cancelled": cancelled,
        "refunds": refunds,
        "discounts": (agg["discount"] or ZERO) + (agg["coins"] or ZERO),
        "delivery_fees": fees,
        "delivery_cost": agg["delivery_cost"] or ZERO,
        "delivery_net": fees - (agg["delivery_cost"] or ZERO),
        "gst": agg["gst"] or ZERO,
    }


def compare(p: Period) -> dict:
    now, before = kpis(p), kpis(p.previous())
    return {
        k: {"value": v, "before": before[k], "change": pct(v, before[k]) if isinstance(v, (int, Decimal)) else None}
        for k, v in now.items()
    }


def daily(p: Period):
    rows = (
        orders_in(p)
        .filter(status__in=COUNTED)
        .annotate(day=TruncDate("placed_at"))
        .values("day")
        .annotate(orders=Count("id"), revenue=Sum("total"))
        .order_by("day")
    )
    by_day = {r["day"]: r for r in rows}
    out, d = [], timezone.localtime(p.start).date()
    while d < timezone.localtime(p.end).date():
        r = by_day.get(d, {})
        out.append({"day": d, "orders": r.get("orders", 0), "revenue": r.get("revenue") or ZERO})
        d += timedelta(days=1)
    return out


def top_products(p: Period, limit=15):
    return list(
        lines_in(p)
        .values("variant__product__name", "variant_label")
        .annotate(qty=Sum(F("qty") - F("refunded_qty")), revenue=Sum("line_total"))
        .order_by("-revenue")[:limit]
    )


def by_category(p: Period):
    rows = (
        lines_in(p)
        .values("variant__product__categories__name")
        .annotate(revenue=Sum("line_total"), qty=Sum("qty"))
        .order_by("-revenue")
    )
    return [
        {
            "category": r["variant__product__categories__name"] or "Uncategorised",
            "revenue": r["revenue"],
            "qty": r["qty"],
        }
        for r in rows
    ]


def by_payment(p: Period):
    return list(
        orders_in(p)
        .filter(status__in=COUNTED)
        .values("payment_method")
        .annotate(orders=Count("id"), revenue=Sum("total"))
        .order_by("-revenue")
    )


def by_area(p: Period, limit=20):
    return list(
        orders_in(p)
        .filter(status__in=COUNTED)
        .values("ship_pincode", "ship_area")
        .annotate(
            orders=Count("id"),
            revenue=Sum("total"),
            fees=Sum("delivery_fee"),
            cost=Sum("delivery_cost"),
            km=Sum("road_km"),
        )
        .order_by("-orders")[:limit]
    )


def heatmap(p: Period):
    """orders[weekday 1-7][hour 0-23]"""
    grid = [[0] * 24 for _ in range(7)]
    rows = (
        orders_in(p)
        .filter(status__in=COUNTED)
        .annotate(wd=ExtractIsoWeekDay("placed_at"), hr=ExtractHour("placed_at"))
        .values("wd", "hr")
        .annotate(n=Count("id"))
    )
    for r in rows:
        grid[r["wd"] - 1][r["hr"]] = r["n"]
    peak = max((max(row) for row in grid), default=0)
    return grid, peak


def coupons(p: Period):
    from apps.promotions.models import CouponRedemption

    return list(
        CouponRedemption.objects.filter(created_at__gte=p.start, created_at__lt=p.end)
        .values("coupon__code")
        .annotate(uses=Count("id"), discount=Sum("amount"), sales=Sum("order__total"))
        .order_by("-uses")
    )


def funnel(p: Period):
    from .models import ProductView

    rows = dict(
        ProductView.objects.filter(created_at__gte=p.start, created_at__lt=p.end)
        .values("step")
        .annotate(n=Count("session_key", distinct=True))
        .values_list("step", "n")
    )
    steps = [
        ("view", "Viewed a product"),
        ("cart", "Added to cart"),
        ("checkout", "Reached checkout"),
        ("order", "Placed order"),
    ]
    top = rows.get("view") or 1
    return [
        {"step": label, "sessions": rows.get(k, 0), "pct": round(rows.get(k, 0) * 100 / top, 1)} for k, label in steps
    ]


def not_selling(p: Period, limit=15):
    from apps.catalog.models import ProductVariant

    sold = lines_in(p).values_list("variant_id", flat=True).distinct()
    return list(
        ProductVariant.objects.filter(
            is_active=True, product__is_active=True, product__deleted_at__isnull=True, stock_qty__gt=0
        )
        .exclude(pk__in=sold)
        .select_related("product")
        .order_by("-stock_qty")[:limit]
    )


def stock_risks(p: Period, limit=10):
    """Best sellers that will run out within 3 days at the current sales rate."""
    from apps.catalog.models import ProductVariant

    rates = {r["variant_id"]: r["q"] / p.days for r in lines_in(p).values("variant_id").annotate(q=Sum("qty"))}
    risks = []
    for v in ProductVariant.objects.filter(pk__in=rates, is_active=True).select_related("product"):
        rate = rates[v.pk]
        if rate > 0 and v.available_qty / rate < 3:
            risks.append((v, round(v.available_qty / rate, 1), round(rate, 1)))
    return sorted(risks, key=lambda r: r[1])[:limit]


def slow_confirm(p: Period):
    """Orders that took more than 10 minutes from placed to confirmed."""
    from apps.orders.models import OrderEvent

    confirmed = {e.order_id: e.at for e in OrderEvent.objects.filter(status="confirmed", at__gte=p.start, at__lt=p.end)}
    slow = 0
    for o in Order.objects.filter(pk__in=confirmed).only("pk", "placed_at"):
        if o.placed_at and (confirmed[o.pk] - o.placed_at) > timedelta(minutes=10):
            slow += 1
    return slow, len(confirmed)
