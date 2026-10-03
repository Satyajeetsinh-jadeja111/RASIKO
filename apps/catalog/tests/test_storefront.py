import json

import pytest


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "/",
        "/brands/",
        "/search/?q=mango",
        "/offers/",
        "/cart/",
        "/help/",
        "/accounts/login/",
        "/accounts/signup/",
        "/orders/track/",
        "/orders/party/",
        "/robots.txt",
        "/sitemap.xml",
        "/site.webmanifest",
        "/healthz",
    ],
)
def test_public_pages(client, variant, url):
    assert client.get(url).status_code == 200


@pytest.mark.django_db
def test_product_page_and_cart_flow(client, variant):
    r = client.get(variant.product.get_absolute_url())
    assert r.status_code == 200 and "Mango Lassi" in r.content.decode()
    r = client.post("/cart/update/", {"key": f"v:{variant.pk}", "qty": 2}, HTTP_ACCEPT="application/json")
    data = json.loads(r.content)
    assert data["qty"] == 2 and data["count"] == 2
    r = client.post("/cart/update/", {"key": f"v:{variant.pk}", "qty": 50}, HTTP_ACCEPT="application/json")
    assert json.loads(r.content)["qty"] <= variant.max_per_order


@pytest.mark.django_db
def test_robots_hides_private_paths(client):
    body = client.get("/robots.txt").content.decode()
    assert "Disallow: /manage/" not in body  # the dashboard address is not advertised
    assert "Disallow: /cart/" in body


@pytest.mark.django_db
def test_security_headers(client):
    r = client.get("/")
    assert "frame-ancestors 'none'" in r["Content-Security-Policy"]
    assert r["X-Content-Type-Options"] == "nosniff"


@pytest.mark.django_db
def test_launch_mode_hides_shop(client, variant, staff_user):
    from datetime import timedelta

    from django.utils import timezone

    from apps.core.models import StoreSettings

    s = StoreSettings.load()
    s.launch_at = timezone.now() + timedelta(days=2)
    s.save()
    assert client.get("/").status_code == 503
    client.force_login(staff_user)
    assert client.get("/").status_code == 200
