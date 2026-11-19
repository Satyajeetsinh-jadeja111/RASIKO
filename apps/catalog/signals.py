from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Product
from .search import update_search_vector


@receiver(post_save, sender=Product)
def refresh_search(sender, instance, **kwargs):
    update_search_vector(instance)


# Shared public fragments include stock/price snapshots, so invalidate on all catalog writes.
from django.db.models.signals import post_delete  # noqa: E402

from apps.core.models import Page  # noqa: E402
from apps.promotions.models import Campaign, Combo, ComboItem, Coupon, HeroSlide  # noqa: E402

from .cache import invalidate_catalog  # noqa: E402
from .models import Brand, Category, ProductImage, ProductVariant  # noqa: E402


def invalidate_public_catalog(sender, **kwargs):
    invalidate_catalog()


for model in (
    Product,
    ProductVariant,
    ProductImage,
    Brand,
    Category,
    Page,
    Campaign,
    Combo,
    ComboItem,
    Coupon,
    HeroSlide,
):
    post_save.connect(invalidate_public_catalog, sender=model, weak=False)
    post_delete.connect(invalidate_public_catalog, sender=model, weak=False)
