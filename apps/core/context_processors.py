import json

from django.conf import settings
from django.core.cache import cache

from .integrations import is_enabled
from .models import Page, StoreSettings


def _menu():
    from apps.catalog.models import Category

    menu = cache.get("menu_categories")
    if menu is None:
        menu = list(Category.objects.active().filter(show_in_menu=True).only("name", "name_gu", "name_hi", "slug"))
        cache.set("menu_categories", menu, 300)
    return menu


def _org_jsonld(store, cfg):
    """LocalBusiness structured data for Google (store name, address, geo, phone, hours)."""
    from apps.delivery.models import StoreHours

    data = {
        "@context": "https://schema.org",
        "@type": "ConvenienceStore",
        "name": store.name,
        "url": settings.SITE_URL + "/",
        "logo": settings.SITE_URL + "/static/brand/rasiko-icon-512.png",
        "telephone": store.phone,
        "priceRange": "₹",
        "currenciesAccepted": "INR",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": store.address,
            "addressLocality": "Rajkot",
            "addressRegion": "Gujarat",
            "addressCountry": "IN",
        },
        "geo": {"@type": "GeoCoordinates", "latitude": float(cfg.store_lat), "longitude": float(cfg.store_lng)},
        "areaServed": {
            "@type": "GeoCircle",
            "geoMidpoint": {
                "@type": "GeoCoordinates",
                "latitude": float(cfg.store_lat),
                "longitude": float(cfg.store_lng),
            },
            "geoRadius": f"{cfg.radius_km} km",
        },
    }
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    data["openingHoursSpecification"] = [
        {
            "@type": "OpeningHoursSpecification",
            "dayOfWeek": days[h.weekday],
            "opens": h.opens.strftime("%H:%M"),
            "closes": h.closes.strftime("%H:%M"),
        }
        for h in StoreHours.objects.filter(is_closed=False)
    ]
    # Escape "<" so no value can close the <script> tag.
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def store(request):
    if request.path.startswith(("/static/", "/media/")):
        return {}
    from apps.delivery.models import DeliverySettings
    from apps.promotions.models import Campaign, coin_balance

    user = getattr(request, "user", None)
    store_settings = StoreSettings.load()
    cfg = DeliverySettings.load()
    org = cache.get("org_jsonld")
    if org is None:
        org = _org_jsonld(store_settings, cfg)
        cache.set("org_jsonld", org, 600)
    return {
        "store": store_settings,
        "delivery_cfg": cfg,
        "org_jsonld": org,
        "footer_pages": Page.objects.filter(show_in_footer=True).only("slug", "title"),
        "menu_categories": _menu(),
        "campaign": Campaign.current(),
        "coins": coin_balance(user) if user and user.is_authenticated else None,
        "whatsapp_api_on": is_enabled("whatsapp"),
        "ADMIN_URL": settings.ADMIN_URL,
        "SITE_URL": settings.SITE_URL,
    }
