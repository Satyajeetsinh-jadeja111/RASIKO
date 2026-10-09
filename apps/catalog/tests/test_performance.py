import io

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.catalog.cache import public_fragment
from apps.catalog.models import ProductImage


@pytest.mark.django_db
def test_catalog_write_invalidates_shared_fragment(variant):
    assert public_fragment("catalog_home", lambda: {"price": str(variant.price)}) == {"price": "50"}
    variant.price = 55
    variant.save()
    assert cache.get("catalog_home") is None
    assert public_fragment("catalog_home", lambda: {"price": str(variant.price)}) == {"price": "55"}


@pytest.mark.django_db
def test_portrait_srcset_uses_actual_pixel_width(variant, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    source = io.BytesIO()
    Image.new("RGB", (800, 1600), "white").save(source, format="PNG")
    photo = ProductImage.objects.create(
        product=variant.product,
        image=SimpleUploadedFile("portrait.png", source.getvalue(), content_type="image/png"),
    )
    photo.refresh_from_db()
    assert set(photo.responsive_images) == {"160", "320"}
    for width, name in photo.responsive_images.items():
        with photo.image.storage.open(name) as content:
            image = Image.open(content)
            assert image.width == int(width) and image.format == "WEBP"
    assert "160w" in photo.srcset and "320w" in photo.srcset


@pytest.mark.django_db
def test_catalog_html_is_private_but_assets_are_separate(client, variant):
    assert client.get("/")["Cache-Control"] == "private, no-store"
    assert client.get("/cart/")["Cache-Control"] == "private, no-store"
