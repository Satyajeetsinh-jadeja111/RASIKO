from datetime import time
from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import SingletonModel

D = Decimal


class DeliverySettings(SingletonModel):
    # Store / warehouse and service boundary
    store_lat = models.DecimalField(max_digits=9, decimal_places=6, default=D("22.303894"))
    store_lng = models.DecimalField(max_digits=9, decimal_places=6, default=D("70.802160"))
    radius_km = models.DecimalField(max_digits=5, decimal_places=2, default=D("15"))
    polygon = models.JSONField(
        default=list, blank=True, help_text=_("Optional service boundary: list of [lat, lng] points")
    )
    enforce_pincodes = models.BooleanField(default=True)
    road_factor = models.DecimalField(max_digits=4, decimal_places=2, default=D("1.30"))

    # Order value rules
    min_order_value = models.DecimalField(max_digits=8, decimal_places=2, default=D("99"))
    small_order_below = models.DecimalField(max_digits=8, decimal_places=2, default=D("199"))
    small_order_fee = models.DecimalField(max_digits=6, decimal_places=2, default=D("15"))
    free_near_threshold = models.DecimalField(max_digits=8, decimal_places=2, default=D("499"))
    free_near_max_km = models.DecimalField(max_digits=5, decimal_places=2, default=D("6"))
    free_anywhere_threshold = models.DecimalField(max_digits=8, decimal_places=2, default=D("799"))
    cod_limit = models.DecimalField(max_digits=8, decimal_places=2, default=D("2000"))

    # Surcharges (shown clearly to the customer)
    late_night_enabled = models.BooleanField(default=False)
    late_night_after = models.TimeField(default=time(22, 0))
    late_night_fee = models.DecimalField(max_digits=6, decimal_places=2, default=D("10"))
    rain_peak_enabled = models.BooleanField(default=False, help_text=_("Switch on during rain or peak hours"))
    rain_peak_fee = models.DecimalField(max_digits=6, decimal_places=2, default=D("10"))

    # Speed promise and slots
    asap_min_minutes = models.PositiveSmallIntegerField(default=30)
    asap_max_minutes = models.PositiveSmallIntegerField(default=60)
    fast_promise_minutes = models.PositiveSmallIntegerField(default=30)
    slot_minutes = models.PositiveSmallIntegerField(default=60)
    slot_days_ahead = models.PositiveSmallIntegerField(default=2)
    delivery_otp_enabled = models.BooleanField(default=True)

    # Delivery economics (real cost per delivery)
    rider_pay_per_order = models.DecimalField(max_digits=6, decimal_places=2, default=D("25"))
    fuel_cost_per_km = models.DecimalField(max_digits=5, decimal_places=2, default=D("3.50"))
    packaging_per_order = models.DecimalField(max_digits=5, decimal_places=2, default=D("5"))

    cache_key = "delivery_settings"

    class Meta:
        verbose_name = _("Delivery settings")

    def __str__(self):
        return "Delivery settings"


class FeeSlab(models.Model):
    min_km = models.DecimalField(max_digits=5, decimal_places=2)
    max_km = models.DecimalField(max_digits=5, decimal_places=2)
    fee = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        ordering = ["min_km"]

    def __str__(self):
        return f"{self.min_km}–{self.max_km} km: ₹{self.fee}"


class ServicePincode(models.Model):
    code = models.CharField(max_length=6, unique=True)
    area = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    fast_delivery = models.BooleanField(default=False, help_text=_("Eligible for the 30-minute promise"))
    cod_blocked = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.area}".strip()


class StoreHours(models.Model):
    weekday = models.PositiveSmallIntegerField(
        unique=True,
        choices=[
            (i, d) for i, d in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
        ],
    )
    opens = models.TimeField(default=time(8, 0))
    closes = models.TimeField(default=time(23, 0))
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ["weekday"]
        verbose_name_plural = "store hours"


class Holiday(models.Model):
    date = models.DateField(unique=True)
    note = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["date"]


class Rider(models.Model):
    name = models.CharField(max_length=80)
    phone = models.CharField(max_length=15)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.phone})"
