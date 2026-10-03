from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector, TrigramSimilarity
from django.db.models import Q, Value
from django.db.models.functions import Greatest

from .models import Product


def update_search_vector(product: Product) -> None:
    vector = (
        SearchVector(Value(product.name), weight="A", config="simple")
        + SearchVector(Value(f"{product.name_gu} {product.name_hi}"), weight="A", config="simple")
        + SearchVector(Value(product.brand.name if product.brand_id else ""), weight="B", config="simple")
        + SearchVector(Value(" ".join(product.tags)), weight="B", config="simple")
        + SearchVector(Value(f"{product.short_description} {product.description}"), weight="C", config="simple")
    )
    Product.objects.filter(pk=product.pk).update(search_vector=vector)


def search_products(q: str, qs=None):
    """Full-text search with a trigram fallback so typos like 'lasi' still find 'Lassi'."""
    qs = (qs if qs is not None else Product.objects.live()).with_listing()
    q = (q or "").strip()[:80]
    if not q:
        return qs
    query = SearchQuery(q, search_type="websearch", config="simple") | SearchQuery(
        " & ".join(f"{w}:*" for w in q.split() if w.isalnum()) or q, search_type="raw", config="simple"
    )
    fts = qs.filter(search_vector=query).annotate(rank=SearchRank("search_vector", query)).order_by("-rank")
    if fts.exists():
        return fts
    return (
        qs.annotate(sim=Greatest(TrigramSimilarity("name", q), TrigramSimilarity("brand__name", q)))
        .filter(Q(sim__gt=0.2) | Q(name__icontains=q) | Q(brand__name__icontains=q))
        .order_by("-sim")
    )


def autocomplete(q: str, limit=8):
    return list(search_products(q)[:limit])
