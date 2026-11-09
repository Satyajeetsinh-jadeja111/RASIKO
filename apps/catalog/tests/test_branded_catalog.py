import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.models import Brand, Category, Product, ProductImage


@pytest.mark.django_db
def test_starter_catalog_requires_demo_acknowledgement():
    with pytest.raises(CommandError, match="acknowledge-demo-prices"):
        call_command("seed_branded_catalog")
    assert not Product.objects.exists()


@pytest.mark.django_db
def test_starter_photos_and_bailley_range_are_repeatable(settings):
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    rows = json.loads((settings.BASE_DIR / "assets/starter-catalog/catalog.json").read_text())
    for slug in {r["category"] for r in rows}:
        Category.objects.create(name=slug, slug=slug)
    fictional = Brand.objects.create(name="Gir Dairy")
    old = Product.objects.create(name="Sweet Lassi", brand=fictional)
    call_command("seed_branded_catalog", acknowledge_demo_prices=True, replace_fictional_demo=True)
    old.refresh_from_db()
    assert not old.is_active
    assert Product.objects.filter(is_active=True).count() == 28
    assert ProductImage.objects.count() == 32
    assert all(p.primary_image.responsive_images for p in Product.objects.filter(is_active=True))
    water = Product.objects.filter(brand__name="Bailley", categories__slug="water")
    assert set(water.values_list("variants__volume_ml", flat=True)) == {250, 500, 1000, 2000, 5000, 10000, 20000}
    assert Product.objects.filter(brand__name="Bailley", categories__slug="soda-masala").count() == 3
    product = Product.objects.filter(is_active=True).first()
    variant = product.variants.get()
    variant.price = 123
    variant.stock_qty = 17
    variant.save()
    original_photo = product.primary_image.image.name
    call_command("seed_branded_catalog", acknowledge_demo_prices=True, replace_fictional_demo=True)
    variant.refresh_from_db()
    assert variant.price == 123 and variant.stock_qty == 17
    assert product.primary_image.image.name == original_photo
    assert ProductImage.objects.count() == 32
    assert Product.objects.count() == 33  # Historical demo product remains stored.


@pytest.mark.django_db
def test_single_bottle_variants_cannot_be_bought(variant):
    variant.units_per_box = 1
    variant.save()
    assert variant.available_boxes == 0
    assert not variant.in_stock
    assert variant.max_orderable == 0


@pytest.mark.django_db
def test_dashboard_requires_box_count_and_bottle_volume(variant):
    from django.forms.models import model_to_dict

    from apps.dashboard.views.catalog import VariantForm

    data = model_to_dict(variant)
    data.update(units_per_box=1, volume_ml="")
    form = VariantForm(data=data, instance=variant)
    assert not form.is_valid()
    assert "units_per_box" in form.errors and "volume_ml" in form.errors
    data.update(units_per_box=24, volume_ml=500)
    form = VariantForm(data=data, instance=variant)
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_box_checkout_deducts_bottles_and_preserves_snapshot(place, variant):
    variant.units_per_box = 24
    variant.stock_qty = 60
    variant.save()
    order = place(qty=2)
    variant.refresh_from_db()
    assert variant.stock_qty == 12
    line = order.lines.get()
    assert line.qty == 2 and line.units_per_box == 24
    assert "Box of 24" in line.variant_label


@pytest.mark.django_db
def test_single_bottle_checkout_blocked(place, variant):
    from apps.orders.services import CheckoutError

    variant.units_per_box = 1
    variant.save()
    with pytest.raises(CheckoutError):
        place(qty=1)
