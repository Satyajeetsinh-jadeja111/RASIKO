from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.core.models import Page
from apps.delivery.models import ServicePincode

from .models import Brand, Category, Product
from .seo import LANDINGS


class StaticSitemap(Sitemap):
    priority = 0.8

    def items(self):
        return ["storefront:home", "storefront:offers", "storefront:brands", "support:help", "orders:bulk"]

    def location(self, item):
        return reverse(item)


class ProductSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.9

    def items(self):
        return Product.objects.live()

    def lastmod(self, obj):
        return obj.updated_at


class CategorySitemap(Sitemap):
    def items(self):
        return Category.objects.active()


class BrandSitemap(Sitemap):
    def items(self):
        return Brand.objects.active()


class PageSitemap(Sitemap):
    def items(self):
        return Page.objects.all()

    def location(self, obj):
        return reverse("storefront:page", args=[obj.slug])


class LandingSitemap(Sitemap):
    priority = 0.7

    def items(self):
        return list(LANDINGS) + [f"delivery-in-{p.code}" for p in ServicePincode.objects.filter(is_active=True)]

    def location(self, item):
        return reverse("storefront:landing", args=[item])


SITEMAPS = {
    "static": StaticSitemap,
    "products": ProductSitemap,
    "categories": CategorySitemap,
    "brands": BrandSitemap,
    "pages": PageSitemap,
    "local": LandingSitemap,
}
