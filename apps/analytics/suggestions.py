"""'Frequently bought together' and 'Goes well with', from real order data."""

from django.core.cache import cache
from django.db.models import Count

from apps.catalog.models import Product


def frequently_bought_together(product, limit=4):
    key = f"fbt:{product.pk}"
    ids = cache.get(key)
    if ids is None:
        from apps.orders.models import OrderLine

        orders = OrderLine.objects.filter(variant__product=product, order__status="delivered").values("order_id")
        ids = list(
            OrderLine.objects.filter(order_id__in=orders)
            .exclude(variant__product=product)
            .values("variant__product")
            .annotate(n=Count("order", distinct=True))
            .order_by("-n")
            .values_list("variant__product", flat=True)[:limit]
        )
        cache.set(key, ids, 3600)
    if not ids:
        return []
    by_id = {p.pk: p for p in Product.objects.live().filter(pk__in=ids).prefetch_related("variants", "images")}
    return [by_id[i] for i in ids if i in by_id]


def pairs(limit=10, days=60):
    """Top product pairs bought together (for combo suggestions in the insights report)."""
    from datetime import timedelta
    from itertools import combinations

    from django.utils import timezone

    from apps.orders.models import OrderLine

    since = timezone.now() - timedelta(days=days)
    baskets = {}
    for oid, pname in OrderLine.objects.filter(order__placed_at__gte=since, order__status="delivered").values_list(
        "order_id", "product_name"
    ):
        baskets.setdefault(oid, set()).add(pname)
    counts = {}
    for items in baskets.values():
        for a, b in combinations(sorted(items), 2):
            counts[(a, b)] = counts.get((a, b), 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
