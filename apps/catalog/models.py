from datetime import timedelta
from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from apps.core.images import RandomUploadPath
from apps.core.models import TimeStamped


def unique_slug(model, text, instance_pk=None, field="slug"):
    base = slugify(text)[:60] or "item"
    slug, n = base, 2
    while model.objects.filter(**{field: slug}).exclude(pk=instance_pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


class ActiveQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class Category(TimeStamped):
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    name = models.CharField(max_length=80)
    name_gu = models.CharField(max_length=80, blank=True)
    name_hi = models.CharField(max_length=80, blank=True)
    slug = models.SlugField(unique=True, blank=True)
    image = models.ImageField(upload_to=RandomUploadPath("categories"), blank=True)
    tile_color = models.CharField(
        max_length=10,
        default="haldi",
        choices=[
            ("haldi", "Light haldi"),
            ("kamal", "Kamal"),
            ("chandan", "Chandan"),
            ("mitti", "Mitti"),
            ("tulsi", "Light tulsi"),
            ("white", "White"),
        ],
    )
    icon = models.CharField(max_length=20, default="bottle", help_text=_("Illustration used when there is no image"))
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    show_in_menu = models.BooleanField(default=True)
    seo_title = models.CharField(max_length=70, blank=True)
    seo_description = models.CharField(max_length=160, blank=True)

    objects = ActiveQuerySet.as_manager()

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return f"{self.parent} → {self.name}" if self.parent_id else self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Category, self.name, self.pk)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("storefront:category", args=[self.slug])

    @property
    def local_name(self):
        lang = (get_language() or "en")[:2]
        if lang in ("gu", "hi"):
            return getattr(self, f"name_{lang}") or self.name
        return self.name

    def descendant_ids(self):
        ids, frontier = [self.pk], [self.pk]
        while frontier:
            frontier = list(Category.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
            ids += frontier
        return ids


class Brand(TimeStamped):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    logo = models.ImageField(upload_to=RandomUploadPath("brands"), blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    objects = ActiveQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Brand, self.name, self.pk)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("storefront:brand", args=[self.slug])


class ProductQuerySet(models.QuerySet):
    def live(self):
        return self.filter(is_active=True, deleted_at__isnull=True, brand__is_active=True)

    def with_listing(self):
        return self.select_related("brand").prefetch_related("images", "variants")


class Product(TimeStamped):
    class Diet(models.TextChoices):
        VEG = "veg", _("Veg")
        NON_VEG = "nonveg", _("Non-veg")

    name = models.CharField(max_length=120)
    name_gu = models.CharField(_("Name in Gujarati"), max_length=120, blank=True)
    name_hi = models.CharField(_("Name in Hindi"), max_length=120, blank=True)
    slug = models.SlugField(unique=True, blank=True, max_length=80)
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="products")
    categories = models.ManyToManyField(Category, related_name="products")
    short_description = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    diet = models.CharField(max_length=6, choices=Diet.choices, default=Diet.VEG)
    ingredients = models.TextField(blank=True)
    allergens = models.CharField(max_length=200, blank=True)
    nutrition = models.JSONField(default=dict, blank=True, help_text=_('e.g. {"Energy": "45 kcal", "Sugar": "10 g"}'))
    shelf_life = models.CharField(max_length=80, blank=True)
    storage_instructions = models.CharField(max_length=200, blank=True)
    best_before_note = models.CharField(max_length=120, blank=True)
    country_of_origin = models.CharField(max_length=60, default="India")
    tags = ArrayField(models.CharField(max_length=30), default=list, blank=True)
    attributes = models.JSONField(default=dict, blank=True, help_text=_('Flexible, e.g. {"sugar_free": true}'))
    illustration = models.CharField(
        max_length=20, default="bottle", help_text=_("Drink illustration used until a photo is uploaded")
    )
    illustration_color = models.CharField(max_length=7, default="#F4B400")
    is_featured = models.BooleanField(default=False)
    is_bestseller = models.BooleanField(default=False)
    is_new = models.BooleanField(default=False, help_text=_("Shown in Fresh Picks"))
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    seo_title = models.CharField(max_length=70, blank=True)
    seo_description = models.CharField(max_length=160, blank=True)
    rating_avg = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal("0"))
    rating_count = models.PositiveIntegerField(default=0)
    sold_count = models.PositiveIntegerField(default=0)
    search_vector = SearchVectorField(null=True, editable=False)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        indexes = [GinIndex(fields=["search_vector"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Product, self.name, self.pk)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("storefront:product", args=[self.slug])

    @property
    def local_name(self):
        lang = (get_language() or "en")[:2]
        if lang in ("gu", "hi"):
            return getattr(self, f"name_{lang}") or self.name
        return self.name

    @property
    def primary_image(self):
        imgs = list(self.images.all())
        return imgs[0] if imgs else None

    def active_variants(self):
        return [v for v in self.variants.all() if v.is_active]

    @property
    def default_variant(self):
        vs = self.active_variants()
        in_stock = [v for v in vs if v.in_stock]
        return (in_stock or vs or [None])[0]

    @property
    def in_stock(self):
        return any(v.in_stock for v in self.active_variants())


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=RandomUploadPath("products"))
    alt = models.CharField(max_length=120, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    responsive_images = models.JSONField(default=dict, blank=True, editable=False)

    class Meta:
        ordering = ["sort_order", "pk"]

    def save(self, *args, **kwargs):
        uploaded = bool(self.image and not self.image._committed)
        super().save(*args, **kwargs)
        if uploaded:
            self.build_responsive_images()

    def build_responsive_images(self):
        from apps.core.images import reencode

        from .cache import invalidate_catalog

        variants = {}
        for width in (320, 640):
            with self.image.storage.open(self.image.name, "rb") as source:
                content = reencode(source, max_side=width)
                from PIL import Image

                actual_width = str(Image.open(content).width)
                content.seek(0)
                if actual_width in variants:
                    continue
                name = self.image.storage.save("products/responsive/" + content.name, content)
                variants[actual_width] = name
        self.responsive_images = variants
        type(self).objects.filter(pk=self.pk).update(responsive_images=variants)
        invalidate_catalog()

    @property
    def srcset(self):
        return ", ".join(f"{self.image.storage.url(name)} {width}w" for width, name in self.responsive_images.items())


class ProductVariant(TimeStamped):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    label = models.CharField(_("Bottle size"), max_length=40, help_text=_("Size of one bottle, e.g. 250 ml, 1 L"))
    # The shop sells whole boxes only. Prices are per box; stock is counted in bottles.
    units_per_box = models.PositiveSmallIntegerField(
        _("Bottles per box"), default=1, validators=[MinValueValidator(1)], help_text=_("e.g. 24")
    )
    sku = models.CharField(max_length=40, unique=True)
    barcode = models.CharField(max_length=40, blank=True)
    mrp = models.DecimalField(
        _("Box MRP"), max_digits=9, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    price = models.DecimalField(
        _("Box price"), max_digits=9, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    cost_price = models.DecimalField(_("Box cost price"), max_digits=9, decimal_places=2, default=Decimal("0"))
    previous_price = models.DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    price_changed_at = models.DateTimeField(null=True, blank=True)
    gst_rate = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("12.00"))
    hsn_code = models.CharField(max_length=8, default="2202")
    volume_ml = models.PositiveIntegerField(null=True, blank=True)
    weight_g = models.PositiveIntegerField(null=True, blank=True)
    stock_qty = models.IntegerField(_("Stock (bottles)"), default=0, validators=[MinValueValidator(0)])
    reserved_qty = models.PositiveIntegerField(default=0, editable=False)
    low_stock_threshold = models.PositiveIntegerField(_("Low stock alert (bottles)"), default=10)
    max_per_order = models.PositiveSmallIntegerField(_("Max boxes per order"), default=24)
    manual_out_of_stock = models.BooleanField(default=False, help_text=_("Force 'Out of stock' even with quantity"))
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "price"]

    def __str__(self):
        return f"{self.product.name} · {self.box_label}"

    @property
    def box_label(self):
        """What the customer buys, e.g. "Box of 24 × 500 ml"."""
        if self.units_per_box > 1:
            return _("Box of %(n)s × %(size)s") % {"n": self.units_per_box, "size": self.label}
        return self.label

    @property
    def price_per_bottle(self):
        return (self.price / self.units_per_box).quantize(Decimal("0.01"))

    @property
    def available_qty(self):
        """Bottles free to sell (stock minus bottles held for unpaid orders)."""
        return max(0, self.stock_qty - self.reserved_qty)

    @property
    def available_boxes(self):
        return self.available_qty // self.units_per_box if self.units_per_box >= 2 else 0

    @property
    def in_stock(self):
        return self.is_active and not self.manual_out_of_stock and self.available_boxes > 0

    @property
    def is_low_stock(self):
        return self.in_stock and self.available_qty <= self.low_stock_threshold

    @property
    def savings(self):
        return max(Decimal("0"), self.mrp - self.price)

    @property
    def discount_percent(self):
        if self.mrp and self.mrp > self.price:
            return int(round((1 - self.price / self.mrp) * 100))
        return 0

    @property
    def price_dropped(self):
        return bool(
            self.previous_price
            and self.previous_price > self.price
            and self.price_changed_at
            and self.price_changed_at > timezone.now() - timedelta(days=14)
        )

    @property
    def max_orderable(self):
        """Most boxes one order can take."""
        return min(self.max_per_order, self.available_boxes)

    def set_price(self, new_price):
        if new_price != self.price:
            self.previous_price = self.price
            self.price_changed_at = timezone.now()
            self.price = new_price


class RecentlyViewed(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="recently_viewed")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "product")]
        ordering = ["-viewed_at"]


class Wishlist(models.Model):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="wishlist")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "product")]


class BackInStockRequest(models.Model):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="stock_alerts")
    email = models.EmailField()
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("variant", "email")]
