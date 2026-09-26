from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.shortcuts import render
from django.utils import timezone

from apps.catalog.models import ProductVariant
from apps.core.integrations import is_enabled
from apps.core.models import StoreSettings
from apps.orders.models import Order, ThanduComplaint
from apps.reviews.models import Review
from apps.support.models import ChatSession, Ticket

from ..permissions import can, dash

OPEN = ["placed", "confirmed", "packed", "out_for_delivery"]
COUNTED = ["placed", "confirmed", "packed", "out_for_delivery", "delivered"]


def sales_between(start, end):
    qs = Order.objects.filter(placed_at__gte=start, placed_at__lt=end, status__in=COUNTED)
    agg = qs.aggregate(n=Count("id"), revenue=Sum("total"))
    n, revenue = agg["n"] or 0, agg["revenue"] or Decimal("0")
    return {"orders": n, "revenue": revenue, "aov": (revenue / n).quantize(Decimal("1")) if n else Decimal("0")}


@dash("staff")
def home(request):
    now = timezone.localtime()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    t = sales_between(today, today + timedelta(days=1))
    y = sales_between(today - timedelta(days=1), today - timedelta(days=1) + (now - today))  # same time yesterday
    low = ProductVariant.objects.filter(
        is_active=True,
        product__is_active=True,
        product__deleted_at__isnull=True,
        stock_qty__lte=F("reserved_qty") + F("low_stock_threshold"),
    )
    alerts = []
    oos = low.filter(stock_qty__lte=F("reserved_qty")).count()
    if oos:
        alerts.append(("bad", f"{oos} item(s) are out of stock", "dashboard:stock", "?filter=out"))
    if low.count() - oos:
        alerts.append(("", f"{low.count() - oos} item(s) are running low", "dashboard:stock", "?filter=low"))
    stuck = Order.objects.filter(status="placed", placed_at__lt=now - timedelta(minutes=10)).count()
    if stuck:
        alerts.append(
            (
                "bad",
                f"{stuck} order(s) waiting more than 10 minutes to be confirmed",
                "dashboard:orders",
                "?status=placed",
            )
        )
    waiting_chat = ChatSession.objects.filter(mode="human", ticket__state="open").count()
    if waiting_chat:
        alerts.append(("", f"{waiting_chat} customer(s) asked to talk to a person", "dashboard:support", ""))
    pending_reviews = Review.objects.filter(state="pending").count()
    if pending_reviews:
        alerts.append(("", f"{pending_reviews} review(s) to approve", "dashboard:reviews", ""))
    thandu = ThanduComplaint.objects.filter(state="pending").count()
    if thandu and can(request.user, "manager"):
        alerts.append(("", f"{thandu} Thandu guarantee complaint(s) to check", "dashboard:thandu", ""))
    if can(request.user, "owner"):
        if not (is_enabled("razorpay") or is_enabled("stripe")):
            alerts.append(
                ("", "Online payments are off. Only Cash on Delivery shows at checkout.", "dashboard:integrations", "")
            )
        if not is_enabled("smtp"):
            alerts.append(("", "Email is not set up, so customers get no order emails.", "dashboard:integrations", ""))
        if not StoreSettings.load().is_launched:
            alerts.append(("", "The shop is in Coming Soon mode for customers.", "dashboard:store_settings", ""))
    recent = Order.objects.exclude(status="pending_payment").select_related("user").order_by("-placed_at")[:10]
    ctx = {
        "t": t,
        "y": y,
        "alerts": alerts,
        "recent": recent,
        "open_orders": Order.objects.filter(status__in=OPEN).count(),
        "open_tickets": Ticket.objects.filter(state="open").count(),
    }
    return render(request, "dashboard/home.html", ctx)
