import re
from decimal import Decimal

from django.db.models import Avg, Count

from apps.catalog.models import Product

from .models import Review

BAD_WORDS = {"idiot", "stupid", "fraud", "chor", "bakwas", "gandu", "saala", "bewakoof", "kutta", "harami"}
LINK = re.compile(r"https?://|www\.", re.I)


def looks_abusive(text: str) -> bool:
    words = set(re.findall(r"[a-zA-Z]+", (text or "").lower()))
    return bool(words & BAD_WORDS) or bool(LINK.search(text or ""))


def refresh_product_rating(product_id):
    agg = Review.objects.filter(product_id=product_id, state=Review.State.APPROVED).aggregate(
        a=Avg("stars"), n=Count("pk")
    )
    Product.objects.filter(pk=product_id).update(
        rating_avg=Decimal(str(round(agg["a"] or 0, 2))), rating_count=agg["n"] or 0
    )


def rating_breakdown(product):
    counts = dict(
        Review.objects.filter(product=product, state=Review.State.APPROVED).values_list("stars").annotate(n=Count("pk"))
    )
    total = sum(counts.values()) or 1
    return [(s, counts.get(s, 0), round(counts.get(s, 0) * 100 / total)) for s in (5, 4, 3, 2, 1)]


def can_review(user, product):
    """Return the delivered order lines of this product that this user has not reviewed yet."""
    from apps.orders.models import OrderLine

    if not user.is_authenticated:
        return OrderLine.objects.none()
    return OrderLine.objects.filter(
        order__user=user, order__status="delivered", variant__product=product, review__isnull=True
    )
