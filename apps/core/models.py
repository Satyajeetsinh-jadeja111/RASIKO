from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from . import crypto


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SingletonModel(models.Model):
    """A settings table with exactly one row (pk=1), cached in Redis."""

    cache_key = ""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.cache_key or self.__class__.__name__)

    def delete(self, *args, **kwargs):  # pragma: no cover - never delete settings
        return None

    @classmethod
    def load(cls):
        key = cls.cache_key or cls.__name__
        obj = cache.get(key)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(key, obj, 300)
        return obj


class StoreSettings(SingletonModel):
    class Mark(models.TextChoices):
        SHUBH_LABH = "shubh_labh", "शुभ लाभ (Shubh Labh)"
        OM = "om", "ॐ (Om)"
        NONE = "none", _("Off")

    class Gateway(models.TextChoices):
        RAZORPAY = "razorpay", "Razorpay"
        STRIPE = "stripe", "Stripe"
        NONE = "none", _("None (Cash on Delivery only)")

    name = models.CharField(max_length=80, default="Rasiko")
    tagline = models.CharField(max_length=160, default="Rajkot no swaad, tamare ghare.")
    tagline_en = models.CharField(max_length=160, default="Rajkot's taste, at your doorstep.")
    phone = models.CharField(max_length=20, default="+91 00000 00000")
    email = models.EmailField(default="hello@example.com")
    whatsapp_number = models.CharField(
        max_length=20, blank=True, help_text=_("Shop WhatsApp number with country code, digits only, e.g. 919800000000")
    )
    address = models.TextField(default="Rajkot, Gujarat")
    fssai_number = models.CharField(max_length=20, default="XXXXXXXXXXXXXX")
    gstin = models.CharField(max_length=15, default="24XXXXXXXXXXXXX")
    legal_name = models.CharField(max_length=120, default="Rasiko")
    state_code = models.CharField(max_length=2, default="24", help_text=_("GST state code (Gujarat = 24)"))

    # Payments
    active_gateway = models.CharField(max_length=10, choices=Gateway.choices, default=Gateway.RAZORPAY)
    gateway_fallback_enabled = models.BooleanField(
        default=False, help_text=_("Allow the other enabled gateway when the selected gateway is disabled.")
    )
    cod_enabled = models.BooleanField(default=True)

    # Auspicious elements (Store settings -> Auspicious elements)
    auspicious_mark = models.CharField(max_length=12, choices=Mark.choices, default=Mark.SHUBH_LABH)
    show_success_blessing = models.BooleanField(default=True)
    launch_at = models.DateTimeField(
        null=True, blank=True, help_text=_("Muhurat go-live. Before this time visitors see the coming soon page.")
    )
    launch_message = models.CharField(max_length=200, blank=True, default="Opening on an auspicious day")

    # Loyalty
    coins_earn_percent = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("2.00"))
    coin_value_rupees = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"))
    max_coin_redeem_percent = models.PositiveSmallIntegerField(default=20)
    referral_coins = models.PositiveIntegerField(default=50)
    birthday_coins = models.PositiveIntegerField(default=50)
    thandu_coupon_amount = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("30.00"))

    # SEO
    meta_description = models.CharField(
        max_length=300,
        default="Chilled juices, soft drinks, lassi and masala soda delivered across Rajkot in 30 to 60 minutes.",
    )

    cache_key = "store_settings"

    class Meta:
        verbose_name = _("Store settings")

    def __str__(self):
        return "Store settings"

    @property
    def is_launched(self):
        return self.launch_at is None or timezone.now() >= self.launch_at

    @property
    def whatsapp_link(self):
        digits = "".join(ch for ch in self.whatsapp_number if ch.isdigit())
        return f"https://wa.me/{digits}" if digits else ""


class Integration(TimeStamped):
    """Encrypted configuration for one third-party service. See integrations.REGISTRY."""

    slug = models.SlugField(unique=True)
    enabled = models.BooleanField(default=False)
    data_encrypted = models.TextField(blank=True, default="")
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_message = models.CharField(max_length=300, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return self.slug

    def config(self) -> dict:
        return crypto.decrypt_json(self.data_encrypted)

    def update_values(self, values: dict) -> list[str]:
        """Merge new values; blank secret fields keep their stored value. Returns changed field names."""
        from .integrations import REGISTRY

        spec = REGISTRY[self.slug]
        current = self.config()
        changed = []
        for f in spec.fields:
            new = (values.get(f.name) or "").strip()
            if f.secret and not new:
                continue
            if current.get(f.name, "") != new:
                current[f.name] = new
                changed.append(f.name)
        self.data_encrypted = crypto.encrypt_json(current)
        return changed

    def missing_required(self) -> list[str]:
        from .integrations import REGISTRY

        cfg = self.config()
        return [f.label for f in REGISTRY[self.slug].fields if f.required and not cfg.get(f.name)]


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    summary = models.CharField(max_length=300, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"


class Page(TimeStamped):
    """Editable policy/content pages: terms, privacy, refund, delivery, about."""

    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=120)
    body = models.TextField(help_text=_("Plain text. Blank lines start new paragraphs."))
    show_in_footer = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "title"]

    def __str__(self):
        return self.title
