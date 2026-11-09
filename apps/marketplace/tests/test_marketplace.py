from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import Brand
from apps.marketplace import dispatch, services
from apps.marketplace.access import teams_for
from apps.marketplace.checkout import allocate, coupon_subtotal, payment_methods
from apps.marketplace.models import (
    DeliveryAssignment,
    DispatchOffer,
    Head,
    LedgerEntry,
    MarketplaceSettings,
    RiderAccount,
    Seller,
    SellerTeam,
    Territory,
    TerritoryPincode,
)
from apps.promotions.models import Coupon
from conftest import dash_client

pytestmark = pytest.mark.django_db


@pytest.fixture
def market(owner, variant):
    cfg = MarketplaceSettings.load()
    cfg.enabled = True
    cfg.dispatch_enabled = True
    cfg.save()
    user = User.objects.create_user(email="head@example.test", password="Head-password-123!", role="head")
    head = Head.objects.create(user=user)
    head.brands.add(variant.product.brand)
    area = Territory.objects.create(state="Gujarat", region="Rajkot", name="West")
    TerritoryPincode.objects.create(territory=area, code="360005")
    head.territories.add(area)
    seller_user = User.objects.create_user(email="seller@example.test", password="Seller-password-123!", role="seller")
    seller = Seller.objects.create(name="Bailley Rajkot", owner=seller_user, status="active", verified=True)
    team = SellerTeam.objects.create(seller=seller, brand=variant.product.brand, head=head, delivery_fee=25)
    services.assign_territory(user, team, area)
    variant.product.seller_team = team
    variant.product.save()
    return head, team, area


def test_brand_scope_and_no_staff_access(market, owner):
    head, team, area = market
    team.seller.allow_multiple_brands = True
    team.seller.save(update_fields=["allow_multiple_brands"])
    other_brand = Brand.objects.create(name="Other", slug="other-brand")
    other = SellerTeam.objects.create(seller=team.seller, brand=other_brand)
    assert list(teams_for(head.user)) == [team]
    assert not teams_for(head.user).filter(pk=other.pk).exists()
    assert not head.user.is_dashboard_user
    assert head.user.requires_2fa
    with pytest.raises(PermissionDenied):
        services.set_online(head.user, other, False)
    with pytest.raises(PermissionDenied):
        services.assign_territory(team.seller.owner, team, area)


def test_exclusive_territory_and_jurisdiction(market, owner):
    head, team, area = market
    seller = Seller.objects.create(name="Other seller", owner=owner, status="active")
    team2 = SellerTeam.objects.create(seller=seller, brand=team.brand, head=head)
    with pytest.raises(ValidationError):
        services.assign_territory(head.user, team2, area)
    outside = Territory.objects.create(state="Maharashtra", region="Pune", name="North")
    with pytest.raises(PermissionDenied):
        services.assign_territory(head.user, team, outside)


def test_cod_default_and_global_override(market):
    _, team, _ = market
    assert services.effective_policy(team)["cod"]
    assert not services.effective_policy(team)["online"]
    assert not services.effective_policy(team)["fast"]
    cfg = MarketplaceSettings.load()
    cfg.cod_override = False
    cfg.save()
    assert not services.effective_policy(team)["cod"]
    cfg.cod_override = None
    cfg.save()
    assert services.effective_policy(team)["cod"]


def test_checkout_split_and_no_fast_promise(market, place):
    _, team, _ = market
    order = place()
    f = order.fulfillments.get()
    assert f.team == team
    assert f.total == order.total
    assert not order.fast_promise
    assert f.policy["cod"]
    assert f.platform_fee == 0


def test_payment_policy_mixed_cod():
    groups = {1: {"policy": {"online": True, "cod": True}}, 2: {"policy": {"online": False, "cod": True}}}
    methods = payment_methods([("razorpay", "Online", True, ""), ("cod", "COD", True, "")], groups)
    assert not methods[0][2]
    assert methods[1][2]


def test_allocation_reconciles():
    shares = allocate(Decimal("1.00"), {1: Decimal("1"), 2: Decimal("1"), 3: Decimal("1")})
    assert sum(shares.values()) == Decimal("1.00")


def test_coupon_scopes_and_seller_funding(market):
    head, team, area = market
    coupon = Coupon.objects.create(code="HEAD10", kind="percent", value=Decimal("10"))
    campaign = services.create_campaign(head.user, head, coupon, [team], [area])
    subtotal, ids = coupon_subtotal(coupon, {team.pk: {"team": team, "territory": area, "subtotal": Decimal("100")}})
    assert subtotal == 100 and ids == {team.pk}
    assert campaign.funding == "seller"
    assert team.seller.notices.filter(title="Seller-funded offer").exists()


def test_suspension_requires_reason_and_is_brand_specific(market, owner):
    head, team, _ = market
    team.seller.allow_multiple_brands = True
    team.seller.save(update_fields=["allow_multiple_brands"])
    brand = Brand.objects.create(name="Another", slug="another")
    other = SellerTeam.objects.create(seller=team.seller, brand=brand)
    with pytest.raises(ValidationError):
        services.set_team_status(head.user, team, False, "")
    services.set_team_status(head.user, team, False, "Contract ended")
    other.refresh_from_db()
    assert other.active
    assert not services.effective_policy(SellerTeam.objects.get(pk=team.pk))["operational"]


def test_fee_notice_period_and_permissions(market, owner):
    head, team, _ = market
    with pytest.raises(PermissionDenied):
        services.schedule_fee(head.user, Decimal("2"), True, timezone.now() + timedelta(days=8))
    with pytest.raises(ValidationError):
        services.schedule_fee(owner, Decimal("2"), True, timezone.now() + timedelta(days=1))
    policy = services.schedule_fee(owner, Decimal("2"), True, timezone.now() + timedelta(days=8))
    assert policy.enabled
    assert team.seller.notices.filter(title="Platform fee change").exists()


def make_rider(seller, suffix):
    user = User.objects.create_user(email=f"rider{suffix}@example.test", password="Rider-password-123!", role="rider")
    return RiderAccount.objects.create(user=user, seller=seller, online=True, last_seen=timezone.now())


def test_first_acceptance_wins_and_rider_delivery(market, place):
    _, team, _ = market
    order = place()
    f = order.fulfillments.get()
    r1, r2 = make_rider(team.seller, "1"), make_rider(team.seller, "2")
    with patch("apps.marketplace.tasks.delivery_code.delay"), patch("apps.marketplace.tasks.send_offer.delay"):
        dispatch.mark_ready(team.seller.owner, f)
        offers = dispatch.offer_delivery(f.pk)
    assert len(offers) == 2
    dispatch.accept_offer(r1.user, next(o.pk for o in offers if o.rider_id == r1.pk))
    with pytest.raises(ValidationError):
        dispatch.accept_offer(r2.user, next(o.pk for o in offers if o.rider_id == r2.pk))
    dispatch.delivery_action(r1.user, f.pk, "pickup")
    assert dispatch.delivery_action(r1.user, f.pk, "deliver", "wrong") is None
    f.refresh_from_db()
    assert f.otp_failures == 1
    from django.contrib.auth.hashers import make_password

    f.delivery_otp_hash = make_password("123456")
    f.save()
    dispatch.delivery_action(r1.user, f.pk, "deliver", "123456")
    assert not DeliveryAssignment.objects.get(fulfillment=f).active
    assert LedgerEntry.objects.filter(fulfillment=f, kind="cod_collected").count() == 1
    services.acknowledge_cod(team.seller.owner, f)
    services.acknowledge_cod(team.seller.owner, f)
    assert LedgerEntry.objects.filter(fulfillment=f, kind="cod_remitted").count() == 1


def test_expired_offer_and_suspended_rider(market, place):
    _, team, _ = market
    order = place()
    f = order.fulfillments.get()
    f.status = "ready"
    f.save()
    rider = make_rider(team.seller, "1")
    offer = DispatchOffer.objects.create(fulfillment=f, rider=rider, expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(ValidationError):
        dispatch.accept_offer(rider.user, offer.pk)
    with pytest.raises(ValidationError):
        services.suspend_rider(team.seller.owner, rider, "")
    services.suspend_rider(team.seller.owner, rider, "Left employment")
    with pytest.raises(PermissionDenied):
        dispatch.accept_offer(rider.user, offer.pk)


def test_invitation_email_and_single_affiliation(market, customer):
    head, team, _ = market
    invitation, token = services.invite_rider(head.user, team.seller, customer.email)
    rider = services.accept_invitation(customer, token)
    assert rider.seller == team.seller
    with pytest.raises(ValidationError):
        services.accept_invitation(customer, token)
    assert token not in invitation.token_hash


def test_portal_enforces_mfa_and_head_scope(client, market):
    head, team, _ = market
    client.force_login(head.user)
    assert client.get("/partners/").status_code == 302
    dash_client(client, head.user)
    assert client.get("/partners/").status_code == 200
    assert client.get("/partners/setup/head/").status_code == 403
    from django.urls import reverse

    assert client.get(reverse("dashboard:home")).status_code in (302, 403)


def test_rider_api_requires_registration_and_cannot_leak_offers(client, market):
    _, team, _ = market
    rider = make_rider(team.seller, "1")
    response = client.post(
        "/api/v1/rider/login/",
        {"email": rider.user.email, "password": "Rider-password-123!"},
        content_type="application/json",
    )
    assert response.status_code == 200
    token = response.json()["token"]
    assert client.get("/api/v1/rider/offers/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 200
    response = client.post(
        "/api/v1/rider/heartbeat/",
        {"online": "false"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 400
    services.suspend_rider(team.seller.owner, rider, "Left")
    assert client.get("/api/v1/rider/offers/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401


def test_head_coupon_rejected_outside_marketplace(market, customer):
    from apps.promotions.services import CouponError, validate_coupon

    head, team, _ = market
    coupon = Coupon.objects.create(code="SCOPED", kind="percent", value=Decimal("10"))
    services.create_campaign(head.user, head, coupon, [team])
    with pytest.raises(CouponError):
        validate_coupon(coupon.code, customer, Decimal("100"))


def test_small_allocation_has_no_negative_shares():
    shares = allocate(Decimal("0.02"), {i: Decimal("1") for i in range(7)})
    assert sum(shares.values()) == Decimal("0.02")
    assert min(shares.values()) >= 0


def test_seller_cannot_use_other_seller_product_forms(client, market, owner, variant):
    head, team, _ = market
    other = Seller.objects.create(name="Another business", owner=owner)
    other_team = SellerTeam.objects.create(seller=other, brand=team.brand)
    dash_client(client, team.seller.owner)
    response = client.get(f"/partners/products/{variant.product_id}/")
    assert response.status_code == 200
    variant.product.seller_team = other_team
    variant.product.save()
    assert client.get(f"/partners/products/{variant.product_id}/").status_code == 404


def test_new_rider_registration_requires_invitation(client, market):
    head, team, _ = market
    _, token = services.invite_rider(head.user, team.seller, "newrider@example.test")
    response = client.post(
        "/api/v1/rider/register/",
        {"email": "newrider@example.test", "password": "Strong-rider-pass-2026!", "invitation": token},
        content_type="application/json",
    )
    assert response.status_code == 201
    assert RiderAccount.objects.get(user__email="newrider@example.test").seller == team.seller
    assert (
        client.post(
            "/api/v1/rider/register/",
            {"email": "intruder@example.test", "password": "Strong-rider-pass-2026!"},
            content_type="application/json",
        ).status_code
        == 404
    )


def test_policy_change_blocks_payment_initialization(market, place, razorpay_on):
    from apps.marketplace.checkout import revalidate_online_order

    head, team, _ = market
    team.seller.payments_ready, team.seller.linked_account_id = True, "acc_example"
    team.seller.save()
    services.set_online(head.user, team, True)
    order = place(method="razorpay")
    services.set_online(head.user, team, False)
    with pytest.raises(ValidationError):
        revalidate_online_order(order)
    assert order.fulfillments.get().policy["online"] is True


def test_two_brand_checkout_splits_exactly(market, customer, address, variant, owner):
    import uuid

    from apps.cart.cart import DictCart
    from apps.catalog.models import Product, ProductVariant
    from apps.orders.services import place_order

    head, team, area = market
    team.seller.allow_multiple_brands = True
    team.seller.save(update_fields=["allow_multiple_brands"])
    brand = Brand.objects.create(name="Other brand", slug="second-brand")
    head.brands.add(brand)
    team2 = SellerTeam.objects.create(seller=team.seller, brand=brand, head=head, delivery_fee=Decimal("15"))
    services.assign_territory(head.user, team2, area)
    p = Product.objects.create(name="Second drink", brand=brand, seller_team=team2)
    v = ProductVariant.objects.create(
        product=p,
        label="500ml",
        sku="SECOND",
        units_per_box=2,
        volume_ml=500,
        price=Decimal("75"),
        mrp=Decimal("80"),
        stock_qty=20,
    )
    order = place_order(
        user=customer,
        cart=DictCart({f"v:{variant.pk}": 2, f"v:{v.pk}": 2}),
        address=address,
        payment_method="cod",
        checkout_token=uuid.uuid4().hex,
    )
    assert order.fulfillments.count() == 2
    assert sum(f.total for f in order.fulfillments.all()) == order.total
    assert order.delivery_fee == Decimal("40")


def test_refund_adjusts_untransferred_seller_balance(market, place):
    from apps.marketplace.models import Settlement
    from apps.marketplace.settlements import record_refund
    from apps.payments.models import Refund

    _, team, _ = market
    order = place()
    f = order.fulfillments.get()
    row = Settlement.objects.create(fulfillment=f, amount=f.total)
    refund = Refund.objects.create(
        order=order, amount=Decimal("25"), reason="Partial refund", method="cash", status="succeeded"
    )
    record_refund(refund)
    record_refund(refund)
    row.refresh_from_db()
    assert row.amount == f.total - Decimal("25")
    assert f.ledger.filter(kind="refund").count() == 1


def test_route_uncertain_recovery_never_resubmits(market, place, settings):
    from apps.marketplace.models import Settlement
    from apps.marketplace.settlements import submit
    from apps.payments.models import Payment

    head, team, _ = market
    order = place()
    order.payment_method, order.payment_status = "razorpay", "paid"
    order.save()
    f = order.fulfillments.get()
    f.status = "delivered"
    f.save()
    team.seller.payments_ready, team.seller.linked_account_id = True, "acc_example"
    team.seller.save()
    cfg = MarketplaceSettings.load()
    cfg.payouts_enabled = True
    cfg.save()
    settings.MARKETPLACE_ROUTE_APPROVED = True
    Payment.objects.create(
        order=order, gateway="razorpay", gateway_payment_id="pay_example", amount=order.total, status="succeeded"
    )
    row = Settlement.objects.create(fulfillment=f, amount=f.total, status="uncertain", attempts=1)
    from unittest.mock import Mock

    client = Mock()
    client.transfers.return_value = []
    submit(row.pk, client=client)
    client.create.assert_not_called()
    row.refresh_from_db()
    assert row.status == "uncertain"


def test_removed_head_blocks_team_checkout(market):
    head, team, _ = market
    head.active = False
    head.save()
    assert not services.effective_policy(team)["operational"]
    assert not teams_for(head.user).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_acceptance_has_one_winner(market, place):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections

    _, team, _ = market
    order = place()
    f = order.fulfillments.get()
    f.status = "ready"
    f.save()
    r1, r2 = make_rider(team.seller, "race1"), make_rider(team.seller, "race2")
    offers = [
        DispatchOffer.objects.create(fulfillment=f, rider=r, expires_at=timezone.now() + timedelta(seconds=45))
        for r in (r1, r2)
    ]
    barrier = Barrier(2)

    def attempt(rider_id, offer_id):
        close_old_connections()
        try:
            user = User.objects.get(pk=rider_id)
            barrier.wait(timeout=10)
            dispatch.accept_offer(user, offer_id)
            return True
        except ValidationError:
            return False
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: attempt(*pair), [(r1.user_id, offers[0].pk), (r2.user_id, offers[1].pk)]))
    assert results.count(True) == 1
    assert DeliveryAssignment.objects.filter(fulfillment=f, active=True).count() == 1


def test_delivery_code_only_on_owned_order(client, market, place, customer):
    from django.urls import reverse

    from apps.core.crypto import encrypt_str

    _, team, _ = market
    order = place()
    f = order.fulfillments.get()
    f.status, f.delivery_otp_encrypted = "ready", encrypt_str("123456")
    f.save()
    client.force_login(customer)
    response = client.get(reverse("orders:detail", args=[order.public_id]))
    assert b"123456" in response.content
    client.force_login(team.seller.owner)
    assert client.get(reverse("orders:detail", args=[order.public_id])).status_code == 404


def test_csv_import_is_scoped_and_atomic(market):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.catalog.models import Product
    from apps.marketplace.importing import import_products

    _, team, _ = market
    csv_data = b"name,source_language,sku,label,units_per_box,volume_ml,price,mrp,stock_bottles\nNew drink,en,NEW-CSV,500ml,12,500,500,600,120\n"
    assert import_products(team.seller.owner, team, SimpleUploadedFile("products.csv", csv_data)) == 1
    assert Product.objects.get(name="New drink").seller_team == team
    before = Product.objects.count()
    invalid = csv_data.replace(b"NEW-CSV", b"NEW-CSV-2") + b"Invalid drink,en,BAD,500ml,1,500,500,600,120\n"
    with pytest.raises(ValidationError):
        import_products(team.seller.owner, team, SimpleUploadedFile("invalid.csv", invalid))
    assert Product.objects.count() == before


def test_translation_review_is_scoped_and_rejects_stale_source(client, market, variant):
    from apps.marketplace.translations import source_hash

    _, team, _ = market
    dash_client(client, team.seller.owner)
    p = variant.product
    digest = source_hash(p)
    data = {"source_hash": digest, "name": "Translated drink", "reviewed": True}
    path = f"/partners/products/{p.pk}/translations/hi/"
    assert client.post(path, data).status_code == 302
    assert p.translations.get(language="hi").corrected
    p.description = "New source text"
    p.save()
    response = client.post(path, data)
    assert response.status_code == 200
    assert b"Product content changed" in response.content


def test_full_refund_reverses_coin_subsidy_and_fee(market, place):
    from apps.marketplace.settlements import seller_balance

    _, team, _ = market
    f = place().fulfillments.get()
    f.coins_value, f.platform_fee = Decimal("10"), Decimal("5")
    assert seller_balance(f, f.total) == Decimal("0")


def test_head_loses_order_visibility_when_area_grant_is_removed(market, place):
    from apps.marketplace.access import fulfillments_for

    head, team, area = market
    order = place()
    assert fulfillments_for(head.user).filter(order=order).exists()
    head.territories.remove(area)
    assert not fulfillments_for(head.user).filter(order=order).exists()


def test_seller_application_is_pending_until_admin_verifies(client, customer, market):
    head, team, area = market
    client.force_login(customer)
    response = client.post(
        "/partners/apply/", {"name": "Applicant store", "brand": team.brand_id, "territory": area.pk}
    )
    assert response.status_code == 302
    seller = Seller.objects.get(owner=customer)
    assert seller.status == "pending" and not seller.verified
    assert not seller.teams.get().active
    assert not services.effective_policy(seller.teams.get())["operational"]


def test_legacy_backfill_preserves_totals_and_is_preview_first(owner, variant, place):
    from io import StringIO

    from django.core.management import call_command

    from apps.marketplace.models import Settlement

    order = place()
    original_total = order.total
    call_command("backfill_marketplace", owner_email=owner.email, stdout=StringIO())
    variant.product.refresh_from_db()
    assert variant.product.seller_team_id is None
    call_command("backfill_marketplace", owner_email=owner.email, apply=True, stdout=StringIO())
    order.refresh_from_db()
    assert order.total == original_total
    assert sum(f.total for f in order.fulfillments.all()) == original_total
    assert not Settlement.objects.filter(fulfillment__order=order).exists()


def test_translation_preserves_brand_and_quantities():
    from apps.marketplace.translations import protect, restore

    text, tokens = protect("Bailley water 500 ml / 24 bottles", "Bailley")
    assert "Bailley" not in text and "500 ml" not in text
    assert restore(text, tokens) == "Bailley water 500 ml / 24 bottles"
    with pytest.raises(ValueError):
        restore(text.replace("__RASIKO_0__", "changed"), tokens)
