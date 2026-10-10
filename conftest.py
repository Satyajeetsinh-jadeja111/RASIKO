"""Shared pytest fixtures: a small Rajkot shop with one delivery zone, products, a customer and staff users."""

import uuid
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.accounts.models import Address, User
from apps.catalog.models import Brand, Category, Product, ProductVariant
from apps.delivery.models import DeliverySettings, FeeSlab, ServicePincode, StoreHours

LAT, LNG = Decimal("22.303894"), Decimal("70.802160")


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def shop(db):
    cfg = DeliverySettings.load()
    cfg.store_lat, cfg.store_lng, cfg.radius_km = LAT, LNG, 15
    cfg.save()
    for lo, hi, fee in [(0, 3, 25), (3, 6, 35), (6, 10, 45), (10, 15, 60)]:
        FeeSlab.objects.create(min_km=lo, max_km=hi, fee=fee)
    ServicePincode.objects.create(code="360005", area="Kalawad Road", fast_delivery=True)
    ServicePincode.objects.create(code="360001", area="Old city")
    for d in range(7):
        StoreHours.objects.get_or_create(weekday=d, defaults={"opens": "00:00", "closes": "23:59"})
    return cfg


@pytest.fixture
def variant(shop):
    brand = Brand.objects.create(name="Gir Dairy", slug="gir-dairy")
    cat = Category.objects.create(name="Juices", slug="juices")
    p = Product.objects.create(name="Mango Lassi", slug="mango-lassi", brand=brand)
    p.categories.add(cat)
    return ProductVariant.objects.create(
        product=p,
        label="500 ml",
        sku="ML-500",
        units_per_box=2,
        volume_ml=500,
        mrp=Decimal("60"),
        price=Decimal("50"),
        cost_price=Decimal("35"),
        gst_rate=Decimal("12"),
        hsn_code="0403",
        stock_qty=20,
        max_per_order=12,
    )


@pytest.fixture
def customer(db):
    u = User.objects.create_user(
        email="asha@example.com", password="Kesar-Lassi-2026!", first_name="Asha", phone="9876543210"
    )
    u.phone_verified = True
    u.save()
    return u


@pytest.fixture
def address(customer, shop):
    return Address.objects.create(
        user=customer,
        name="Asha",
        phone="9876543210",
        line1="12 Kalawad Road",
        pincode="360005",
        lat=LAT + Decimal("0.01"),
        lng=LNG,
    )


def make_staff(role, email=None):
    return User.objects.create_user(
        email=email or f"{role}@rasiko.test", password="Staff-Pass-2026!!", first_name=role.title(), role=role
    )


@pytest.fixture
def owner(db):
    return make_staff("owner")


@pytest.fixture
def manager(db):
    return make_staff("manager")


@pytest.fixture
def staff_user(db):
    return make_staff("staff")


def dash_client(client, user):
    """Signed-in dashboard client with two-factor already passed."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    client.force_login(user)
    dev = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    s = client.session
    s["otp_device_id"] = dev.persistent_id
    s.save()
    return client


@pytest.fixture
def place(customer, address, variant):
    """place(qty=3, method="cod", **kw) -> Order"""
    from apps.cart.cart import DictCart
    from apps.orders.services import place_order

    def _place(qty=3, method="cod", v=None, **kw):
        return place_order(
            user=customer,
            cart=DictCart({f"v:{(v or variant).pk}": qty}),
            address=address,
            payment_method=method,
            checkout_token=uuid.uuid4().hex,
            **kw,
        )

    return _place


@pytest.fixture
def razorpay_on(db):
    from apps.core.integrations import clear_cache
    from apps.core.models import Integration, StoreSettings

    row = Integration.objects.create(slug="razorpay", enabled=True)
    row.update_values({"key_id": "rzp_test_abc", "key_secret": "test_secret", "webhook_secret": "whsec"})
    row.save()
    s = StoreSettings.load()
    s.active_gateway = "razorpay"
    s.save()
    clear_cache("razorpay")
    return row
