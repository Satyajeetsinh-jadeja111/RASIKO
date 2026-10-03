import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Exists, F, Max, Min, OuterRef, Prefetch, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from apps.analytics.tracking import track
from apps.core.models import Page, StoreSettings
from apps.core.ratelimit import ratelimit
from apps.promotions.models import Combo, Coupon, HeroSlide

from .models import BackInStockRequest, Brand, Category, Product, ProductVariant, RecentlyViewed, Wishlist
from .search import autocomplete, search_products

SORTS = {
    "popular": ("-is_bestseller", "-sold_count", "name"),
    "price_asc": ("min_price", "name"),
    "price_desc": ("-min_price", "name"),
    "rating": ("-rating_avg", "-rating_count"),
    "new": ("-created_at",),
}


def _listing_qs():
    return (
        Product.objects.live()
        .select_related("brand")
        .prefetch_related("images", Prefetch("variants", queryset=ProductVariant.objects.filter(is_active=True)))
        .annotate(min_price=Min("variants__price", filter=Q(variants__is_active=True)))
    )


def _recent(request):
    ids = request.session.get("recent", [])[:8]
    if not ids:
        return []
    by_id = {p.pk: p for p in _listing_qs().filter(pk__in=ids)}
    return [by_id[i] for i in ids if i in by_id]


def home(request):
    live = _listing_qs()
    best = list(live.filter(is_bestseller=True).order_by("-sold_count")[:8]) or list(live.order_by("-sold_count")[:8])
    fresh = list(live.filter(is_new=True).order_by("-created_at")[:6])
    ctx = {
        "slides": HeroSlide.live(),
        "tiles": Category.objects.active().filter(show_in_menu=True)[:12],
        "best": best,
        "fresh": fresh,
        "featured": list(live.filter(is_featured=True)[:8]),
        "brands": Brand.objects.active()[:12],
        "combos": Combo.objects.filter(is_active=True, show_on_home=True).prefetch_related("items__variant__product")[
            :4
        ],
        "home_coupon": Coupon.objects.filter(is_active=True, show_on_home=True, only_user__isnull=True).first(),
        "recent": _recent(request),
    }
    return render(request, "storefront/home.html", ctx)


def _apply_filters(request, qs):
    g = request.GET
    brands = [b for b in g.getlist("brand") if b]
    if brands:
        qs = qs.filter(brand__slug__in=brands)
    sizes = [s for s in g.getlist("size") if s]
    if sizes:
        qs = qs.filter(variants__label__in=sizes, variants__is_active=True)
    if g.get("veg") == "1":
        qs = qs.filter(diet=Product.Diet.VEG)
    if g.get("instock") == "1":
        qs = qs.filter(
            Exists(
                ProductVariant.objects.filter(
                    product=OuterRef("pk"), is_active=True, manual_out_of_stock=False, stock_qty__gt=F("reserved_qty")
                )
            )
        )
    try:
        if g.get("min"):
            qs = qs.filter(min_price__gte=int(g["min"]))
        if g.get("max"):
            qs = qs.filter(min_price__lte=int(g["max"]))
        if g.get("rating"):
            qs = qs.filter(rating_avg__gte=float(g["rating"]))
    except ValueError:
        pass
    return qs.distinct()


def _render_listing(request, qs, ctx, template="storefront/listing.html"):
    base = qs
    qs = _apply_filters(request, qs)
    sort = request.GET.get("sort", "popular")
    if sort in SORTS:
        qs = qs.order_by(*SORTS[sort])
    page = Paginator(qs, 24).get_page(request.GET.get("page"))
    ids = base.values("pk")
    facet_brands = Brand.objects.filter(products__pk__in=ids).distinct()
    facet_sizes = (
        ProductVariant.objects.filter(product__pk__in=ids, is_active=True)
        .values_list("label", flat=True)
        .distinct()
        .order_by("label")
    )
    prices = base.aggregate(lo=Min("variants__price"), hi=Max("variants__price"))
    ctx.update(
        {
            "page": page,
            "products": page.object_list,
            "sort": sort,
            "facet_brands": facet_brands,
            "facet_sizes": list(facet_sizes)[:20],
            "prices": prices,
            "sel_brands": request.GET.getlist("brand"),
            "sel_sizes": request.GET.getlist("size"),
        }
    )
    if request.htmx:
        return render(request, "storefront/_results.html", ctx)
    return render(request, template, ctx)


def category(request, slug):
    cat = get_object_or_404(Category.objects.active(), slug=slug)
    qs = _listing_qs().filter(categories__in=cat.descendant_ids())
    return _render_listing(
        request, qs, {"category": cat, "title": cat.local_name, "children": cat.children.filter(is_active=True)}
    )


def brand(request, slug):
    b = get_object_or_404(Brand.objects.active(), slug=slug)
    return _render_listing(request, _listing_qs().filter(brand=b), {"brand": b, "title": b.name})


def brands(request):
    return render(request, "storefront/brands.html", {"brands": Brand.objects.active().annotate(n=Count("products"))})


def search(request):
    q = request.GET.get("q", "").strip()
    qs = search_products(q, _listing_qs()) if q else _listing_qs()
    return _render_listing(
        request, qs, {"q": q, "title": _("Results for “%(q)s”") % {"q": q} if q else _("All products")}
    )


def suggest(request):
    q = request.GET.get("q", "").strip()
    items = autocomplete(q) if len(q) >= 2 else []
    return render(request, "storefront/_suggest.html", {"items": items, "q": q})


def product(request, slug):
    p = get_object_or_404(
        Product.objects.live()
        .select_related("brand")
        .prefetch_related("images", "variants", "categories", "variants__bulk_slabs"),
        slug=slug,
    )
    variants = p.active_variants()
    selected = next((v for v in variants if str(v.pk) == request.GET.get("v")), None) or p.default_variant
    recent = [i for i in request.session.get("recent", []) if i != p.pk]
    request.session["recent"] = [p.pk, *recent][:12]
    if request.user.is_authenticated:
        RecentlyViewed.objects.update_or_create(user=request.user, product=p)
    track(request, "view", p)
    from apps.delivery.services import eta_text
    from apps.reviews.models import Review
    from apps.reviews.services import rating_breakdown

    reviews = (
        Review.objects.filter(product=p, state=Review.State.APPROVED)
        .select_related("user")
        .prefetch_related("photos")[:20]
    )
    related = list(_listing_qs().filter(categories__in=p.categories.all()).exclude(pk=p.pk).distinct()[:8])
    from apps.analytics.suggestions import frequently_bought_together

    together = frequently_bought_together(p, limit=4)
    in_wishlist = request.user.is_authenticated and Wishlist.objects.filter(user=request.user, product=p).exists()
    return render(
        request,
        "storefront/product.html",
        {
            "p": p,
            "variants": variants,
            "selected": selected,
            "reviews": reviews,
            "related": related,
            "together": together,
            "breakdown": rating_breakdown(p),
            "eta": eta_text(False),
            "in_wishlist": in_wishlist,
            "jsonld": product_jsonld(request, p, variants),
        },
    )


def product_jsonld(request, p, variants):
    img = p.primary_image.image.url if p.primary_image else static("brand/rasiko-icon-512.png")
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": p.name,
        "sku": variants[0].sku if variants else "",
        "brand": {"@type": "Brand", "name": p.brand.name},
        "description": p.short_description or p.description[:300],
        "image": request.build_absolute_uri(img),
        "offers": [
            {
                "@type": "Offer",
                "priceCurrency": "INR",
                "price": str(v.price),
                "sku": v.sku,
                "availability": "https://schema.org/InStock" if v.in_stock else "https://schema.org/OutOfStock",
                "url": request.build_absolute_uri(p.get_absolute_url()),
            }
            for v in variants
        ],
    }
    if p.rating_count:
        data["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": str(p.rating_avg),
            "reviewCount": p.rating_count,
        }
    return json.dumps(data).replace("<", "\\u003c")


def offers(request):
    from django.utils import timezone

    now = timezone.now()
    coupons = Coupon.objects.filter(is_active=True, only_user__isnull=True, starts_at__lte=now).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    )
    deals = [p for p in _listing_qs()[:200] if p.default_variant and p.default_variant.discount_percent >= 5][:24]
    combos = Combo.objects.filter(is_active=True).prefetch_related("items__variant__product")
    return render(request, "storefront/offers.html", {"coupons": coupons, "deals": deals, "combos": combos})


def page(request, slug):
    pg = get_object_or_404(Page, slug=slug)
    return render(request, "storefront/page.html", {"page": pg})


@login_required
@require_POST
def wishlist_toggle(request, pk):
    p = get_object_or_404(Product.objects.live(), pk=pk)
    obj, created = Wishlist.objects.get_or_create(user=request.user, product=p)
    if not created:
        obj.delete()
    if request.headers.get("Accept", "").startswith("application/json"):
        return JsonResponse({"saved": created})
    return redirect(p.get_absolute_url())


@login_required
def wishlist(request):
    items = _listing_qs().filter(pk__in=Wishlist.objects.filter(user=request.user).values("product"))
    return render(request, "storefront/wishlist.html", {"products": items})


@require_POST
@ratelimit("stockalert", limit=10, window=600)
def back_in_stock(request, pk):
    v = get_object_or_404(ProductVariant, pk=pk)
    email = (request.user.email if request.user.is_authenticated else request.POST.get("email", "")).strip().lower()
    if "@" in email and len(email) < 254:
        BackInStockRequest.objects.get_or_create(variant=v, email=email)
        messages.success(request, _("We'll email you when it's back in stock."))
    else:
        messages.error(request, _("Enter a valid email."))
    return redirect(v.product.get_absolute_url())


# ---- SEO / PWA ---------------------------------------------------------------------


@cache_control(max_age=3600)
def robots(request):
    # The dashboard address is deliberately not listed here: robots.txt is public. Dashboard pages send noindex.
    lines = [
        "User-agent: *",
        "Disallow: /accounts/",
        "Disallow: /cart/",
        "Disallow: /orders/",
        "Disallow: /payments/",
        f"Sitemap: {settings.SITE_URL}/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


@cache_control(max_age=86400)
def manifest(request):
    s = StoreSettings.load()
    return JsonResponse(
        {
            "name": f"{s.name}: {s.tagline_en}",
            "short_name": s.name,
            "start_url": "/",
            "display": "standalone",
            "background_color": "#FFF4E0",
            "theme_color": "#1B6E42",
            "lang": "en-IN",
            "icons": [
                {
                    "src": static(f"favicons/icon-{n}.png"),
                    "sizes": f"{n}x{n}",
                    "type": "image/png",
                    "purpose": "any maskable",
                }
                for n in (192, 512)
            ],
        }
    )


def service_worker(request):
    body = (
        "const C='rasiko-static-v1';\n"
        "self.addEventListener('install',e=>{self.skipWaiting();});\n"
        "self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C)"
        ".map(k=>caches.delete(k)))));});\n"
        "self.addEventListener('fetch',e=>{const u=new URL(e.request.url);"
        "if(e.request.method!=='GET'||u.origin!==location.origin||!u.pathname.startsWith('/static/'))return;"
        "e.respondWith(caches.open(C).then(c=>c.match(e.request).then(r=>r||fetch(e.request).then(res=>{"
        "if(res.ok)c.put(e.request,res.clone());return res;}))));});\n"
    )
    resp = HttpResponse(body, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


def local_landing(request, slug):
    """Local SEO pages: 'cold drinks delivery in Rajkot', 'juice home delivery Rajkot', one per area."""
    from apps.delivery.models import ServicePincode

    from .seo import LANDINGS

    data = LANDINGS.get(slug)
    area = None
    if data is None:
        area = ServicePincode.objects.filter(is_active=True, code=slug.removeprefix("delivery-in-")).first()
        if area is None:
            raise Http404
        data = {
            "title": _("Cold drinks & juice delivery in %(a)s, Rajkot") % {"a": area.area or area.code},
            "intro": _("Chilled beverages delivered to %(a)s (%(c)s) in 30 to 60 minutes.")
            % {"a": area.area or "your area", "c": area.code},
            "category": None,
        }
    qs = _listing_qs()
    if data.get("category"):
        qs = qs.filter(categories__slug=data["category"])
    return render(
        request,
        "storefront/landing.html",
        {
            "data": data,
            "area": area,
            "products": qs.order_by("-sold_count")[:12],
            "canonical": reverse("storefront:landing", args=[slug]),
        },
    )
