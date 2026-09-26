from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.views.i18n import set_language

from apps.catalog import views as store_views
from apps.catalog.sitemaps import SITEMAPS

admin.site.site_header = "Rasiko data admin"

urlpatterns = [
    path("", include("apps.catalog.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("cart/", include("apps.cart.urls")),
    path("orders/", include("apps.orders.urls")),
    path("payments/", include("apps.payments.urls")),
    path("reviews/", include("apps.reviews.urls")),
    path("help/", include("apps.support.urls")),
    path(settings.ADMIN_URL, include("apps.dashboard.urls")),
    path(settings.DJANGO_ADMIN_URL, admin.site.urls),
    path("i18n/setlang/", set_language, name="set_language"),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="sitemap"),
    path("robots.txt", store_views.robots),
    path("site.webmanifest", store_views.manifest, name="manifest"),
    path("sw.js", store_views.service_worker, name="sw"),
    path("healthz", store_views.healthz),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
