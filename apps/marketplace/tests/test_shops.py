import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import Brand
from apps.marketplace.models import Head, MarketplaceSettings, Seller, SellerTeam, Territory, TerritoryRequest
from apps.marketplace.services import assign_territory, invite_rider
from conftest import dash_client

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop_bundle(owner, variant):
    user = User.objects.create_user(email="shop_bundle-owner@example.test", role="seller")
    seller = Seller.objects.create(
        name="Test shop_bundle", owner=user, status="active", verified=True, shop_published=True
    )
    team = SellerTeam.objects.create(seller=seller, brand=variant.product.brand)
    area = Territory.objects.create(state="Gujarat", region="Rajkot", name="West")
    assign_territory(owner, team, area)
    variant.product.seller_team = team
    variant.product.save()
    cfg = MarketplaceSettings.load()
    cfg.enabled = True
    cfg.save()
    return seller, team, area


def test_application_creates_shop_with_multiple_brands_and_areas(client, customer, variant):
    second = Brand.objects.create(name="Second", slug="second-shop_bundle")
    a = Territory.objects.create(state="Gujarat", region="Rajkot", name="North")
    b = Territory.objects.create(state="Gujarat", region="Ahmedabad", name="South")
    client.force_login(customer)
    response = client.post(
        reverse("marketplace:apply"),
        {"name": "New shop_bundle", "brand": [variant.product.brand_id, second.pk], "territory": [a.pk, b.pk]},
    )
    seller = Seller.objects.get(owner=customer)
    assert response.url == reverse("marketplace:shop", args=[seller.pk])
    assert seller.teams.count() == 2
    assert not seller.teams.filter(active=True).exists()
    assert TerritoryRequest.objects.filter(team__seller=seller).count() == 4
    assert client.get(reverse("seller_shop", args=[seller.pk])).status_code == 404


def test_profile_is_owned_and_cannot_self_approve(client, shop_bundle, owner):
    seller, team, _ = shop_bundle
    dash_client(client, owner)
    assert client.get(reverse("marketplace:shop", args=[seller.pk])).status_code == 200
    unrelated = User.objects.create_user(email="other-shop_bundle@example.test", role="seller")
    dash_client(client, unrelated)
    assert client.get(reverse("marketplace:shop", args=[seller.pk])).status_code == 404
    head = Head.objects.create(user=unrelated)
    head.brands.add(team.brand)
    unrelated.role = "head"
    unrelated.save()
    dash_client(client, unrelated)
    assert client.post(reverse("marketplace:shop", args=[seller.pk]), {"name": "Stolen"}).status_code == 404
    dash_client(client, seller.owner)
    response = client.post(
        reverse("marketplace:shop", args=[seller.pk]),
        {
            "name": "Updated shop_bundle",
            "shop_description": "Local drinks",
            "shop_published": "on",
            "allow_multiple_brands": "on",
            "linked_account_id": "acc_forged",
        },
    )
    assert response.status_code == 302
    seller.refresh_from_db()
    assert seller.name == "Updated shop_bundle"
    assert not seller.allow_multiple_brands
    assert seller.linked_account_id == ""


def test_public_shop_respects_gates_and_escapes_text(client, shop_bundle):
    seller, team, _ = shop_bundle
    seller.shop_description = '<script>alert("test")</script>'
    seller.save()
    url = reverse("seller_shop", args=[seller.pk])
    response = client.get(url)
    assert response.status_code == 200
    assert b"Delivery in " not in response.content
    assert b"Free delivery above" not in response.content
    assert b"&lt;script&gt;" in response.content
    assert b"linked_account_id" not in response.content
    team.active = False
    team.save()
    assert client.get(url).status_code == 404
    team.active = True
    team.save()
    seller.shop_published = False
    seller.save()
    assert client.get(url).status_code == 404


def test_brand_request_needs_approval_and_head_permission(client, shop_bundle, owner):
    seller, team, area = shop_bundle
    new = Brand.objects.create(name="New", slug="new-request")
    dash_client(client, seller.owner)
    url = reverse("marketplace:shop_brand", args=[seller.pk])
    response = client.post(url, {"brand": new.pk, "territories": [area.pk]})
    assert response.status_code == 302
    assert not seller.teams.get(brand=new).active
    assert TerritoryRequest.objects.filter(team__seller=seller, team__brand=new).count() == 1
    head = Head.objects.create(user=owner)
    head.brands.add(team.brand)
    team.head = head
    team.save()
    other = Brand.objects.create(name="Other", slug="request-denied")
    response = client.post(url, {"brand": other.pk, "territories": [area.pk]})
    assert response.status_code == 200
    assert b"multi-brand permission" in response.content
    assert not seller.teams.filter(brand=other).exists()
    seller.allow_multiple_brands = True
    seller.save()
    assert client.post(url, {"brand": other.pk, "territories": [area.pk]}).status_code == 302


def test_multiple_regions_and_rider_api_share_shop(client, shop_bundle, owner):
    seller, team, _ = shop_bundle
    other = Territory.objects.create(state="Gujarat", region="Ahmedabad", name="East")
    assign_territory(owner, team, other)
    _, token = invite_rider(owner, seller, "rider-shop_bundle@example.test")
    response = client.post(
        "/api/v1/rider/register/",
        {"email": "rider-shop_bundle@example.test", "password": "Test-rider-secret-823!", "invitation": token},
        content_type="application/json",
    )
    assert response.status_code == 201
    authorization = {"HTTP_AUTHORIZATION": "Bearer " + response.json()["token"]}
    assert client.get("/api/v1/rider/offers/", **authorization).json() == []
    assert client.get("/api/v1/rider/deliveries/", **authorization).json() == []
    assert (
        client.post(
            "/api/v1/rider/heartbeat/",
            {"online": True, "consent": False},
            content_type="application/json",
            **authorization,
        ).status_code
        == 200
    )
    assert seller.riders.get().online
    dash_client(client, seller.owner)
    response = client.get(reverse("marketplace:shop", args=[seller.pk]))
    assert response.context["area_count"] == 2
    assert response.context["rider_count"] == 1


def test_head_can_manage_multiple_brands_across_states(shop_bundle, owner):
    seller, first_team, first_area = shop_bundle
    seller.allow_multiple_brands = True
    seller.save()
    user = User.objects.create_user(email="multi-state-head@example.test", role="head")
    head = Head.objects.create(user=user)
    second_brand = Brand.objects.create(name="Second managed brand", slug="second-managed")
    second_area = Territory.objects.create(state="Maharashtra", region="Mumbai", name="Central")
    head.brands.add(first_team.brand, second_brand)
    head.territories.add(first_area, second_area)
    first_team.head = head
    first_team.save()
    second_team = SellerTeam.objects.create(seller=seller, brand=second_brand, head=head)
    assign_territory(user, second_team, second_area)
    assign_territory(user, second_team, first_area)
    from apps.marketplace.access import teams_for

    assert set(teams_for(user).values_list("pk", flat=True)) == {first_team.pk, second_team.pk}
    assert second_team.assignments.filter(active=True).count() == 2
    assert head.territories.values("state").distinct().count() == 2
