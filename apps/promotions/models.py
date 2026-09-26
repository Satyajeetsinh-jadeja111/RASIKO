from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.images import RandomUploadPath
from apps.core.models import TimeStamped

ZERO = Decimal("0")


class Coupon(TimeStamped):
    class Kind(models.TextChoices):
        PERCENT = "percent", _("Percentage")
        FLAT = "flat", _("Flat ₹")

    code = models.CharField(max_length=30, unique=True)
    description = models.CharField(max_length=160, blank=True)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.FLAT)
    value = models.DecimalField(max_digits=8, decimal_places=2)
    max_discount = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    min_order = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text=_("Total uses allowed"))
    per_user_limit = models.PositiveSmallIntegerField(default=1)
    only_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        help_text=_("Personal coupon (e.g. Thandu guarantee)"),
    )
    first_order_only = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    show_on_home = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def discount_for(self, subtotal: Decimal) -> Decimal:
        if self.kind == self.Kind.PERCENT:
            d = (subtotal * self.value / 100).quantize(Decimal("0.01"))
            if self.max_discount:
                d = min(d, self.max_discount)
        else:
            d = self.value
        return min(d, subtotal)

    @property
    def label(self):
        if self.kind == self.Kind.PERCENT:
            return f"{self.value.normalize():f}% off"
        return f"₹{self.value.normalize():f} off"


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    order = models.OneToOneField("orders.Order", on_delete=models.CASCADE, related_name="coupon_redemption")
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)


class Combo(TimeStamped):
    """A simple bundle: fixed price for a set of variants (e.g. 'Party pack: 6 colas + 2 soda')."""

    name = models.CharField(max_length=80)
    description = models.CharField(max_length=200, blank=True)
    price = models.DecimalField(max_digits=9, decimal_places=2)
    is_active = models.BooleanField(default=True)
    show_on_home = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    @property
    def mrp_total(self):
        return sum((i.variant.mrp * i.qty for i in self.items.all()), ZERO)

    @property
    def regular_total(self):
        return sum((i.variant.price * i.qty for i in self.items.all()), ZERO)

    @property
    def in_stock(self):
        return all(i.variant.in_stock and i.variant.available_qty >= i.qty for i in self.items.all())


class ComboItem(models.Model):
    combo = models.ForeignKey(Combo, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE)
    qty = models.PositiveSmallIntegerField(default=1)


class BulkPriceSlab(models.Model):
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="bulk_slabs")
    min_qty = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=9, decimal_places=2)

    class Meta:
        ordering = ["variant", "min_qty"]
        unique_together = [("variant", "min_qty")]


class HeroSlide(TimeStamped):
    """Home page slider. Recommended 1920×720 (8:3) desktop and 1080×1080 mobile; any ratio still fits."""

    heading = models.CharField(max_length=80)
    heading_accent = models.CharField(max_length=80, blank=True, help_text=_("Second line in the sunrise gradient"))
    subtext = models.CharField(max_length=160, blank=True)
    badge = models.CharField(max_length=60, blank=True)
    button_text = models.CharField(max_length=30, default="Shop now")
    button_link = models.CharField(max_length=200, default="/")
    image = models.ImageField(upload_to=RandomUploadPath("slides"), blank=True)
    mobile_image = models.ImageField(upload_to=RandomUploadPath("slides"), blank=True)
    image_width = models.PositiveIntegerField(null=True, blank=True, editable=False)
    image_height = models.PositiveIntegerField(null=True, blank=True, editable=False)
    blur_color = models.CharField(max_length=7, blank=True, editable=False)
    focal_x = models.PositiveSmallIntegerField(default=50, help_text=_("Focal point % from left"))
    focal_y = models.PositiveSmallIntegerField(default=50, help_text=_("Focal point % from top"))
    fit = models.CharField(
        max_length=8,
        default="contain",
        choices=[("contain", "Show whole image"), ("cover", "Fill (crop around focal point)")],
    )
    art = models.CharField(
        max_length=40,
        default="mango,cola,lemon",
        blank=True,
        help_text=_("Drink illustrations shown when there is no image"),
    )
    theme = models.CharField(
        max_length=8, default="sunrise", choices=[("sunrise", "Sunrise"), ("green", "Tulsi"), ("pink", "Kamal")]
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "pk"]

    def __str__(self):
        return self.heading

    @classmethod
    def live(cls):
        now = timezone.now()
        return cls.objects.filter(is_active=True).filter(
            models.Q(starts_at__isnull=True) | models.Q(starts_at__lte=now),
            models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=now),
        )


class Campaign(TimeStamped):
    class Theme(models.TextChoices):
        DIWALI = "diwali", "Diwali (diyas)"
        NAVRATRI = "navratri", "Navratri (garba)"
        UTTARAYAN = "uttarayan", "Uttarayan / Makar Sankranti (kites)"
        HOLI = "holi", "Holi"
        JANMASHTAMI = "janmashtami", "Janmashtami"
        SUMMER = "summer", "Summer (cold drinks peak)"

    name = models.CharField(max_length=80)
    theme = models.CharField(max_length=12, choices=Theme.choices)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    show_overlay = models.BooleanField(default=True, help_text=_("Toran-style decoration; layout never changes"))
    banner_title = models.CharField(max_length=80)
    banner_text = models.CharField(max_length=160, blank=True)
    coupon = models.ForeignKey(Coupon, null=True, blank=True, on_delete=models.SET_NULL)
    bonus_coins = models.PositiveIntegerField(default=0, help_text=_("Festival bonus coins on delivered orders"))
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-starts_at"]

    def __str__(self):
        return self.name

    @classmethod
    def current(cls):
        now = timezone.now()
        return cls.objects.filter(is_active=True, starts_at__lte=now, ends_at__gt=now).select_related("coupon").first()


class CoinLedger(models.Model):
    class Reason(models.TextChoices):
        EARNED = "earned", _("Earned on order")
        REDEEMED = "redeemed", _("Used at checkout")
        REFERRAL = "referral", _("Referral bonus")
        BIRTHDAY = "birthday", _("Birthday bonus")
        FESTIVAL = "festival", _("Festival bonus")
        REVERSED = "reversed", _("Reversed (refund/cancel)")
        ADJUST = "adjust", _("Adjustment")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coin_entries")
    delta = models.IntegerField()
    reason = models.CharField(max_length=10, choices=Reason.choices)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


def coin_balance(user) -> int:
    if not user or not user.is_authenticated:
        return 0
    return CoinLedger.objects.filter(user=user).aggregate(s=Sum("delta"))["s"] or 0
