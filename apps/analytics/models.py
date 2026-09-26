from django.conf import settings
from django.db import models


class InsightReport(models.Model):
    generated_at = models.DateTimeField(auto_now_add=True, db_index=True)
    period_days = models.PositiveSmallIntegerField(default=30)
    going_well = models.JSONField(default=list)
    can_be_better = models.JSONField(default=list)
    actions = models.JSONField(default=list)
    ai_summary = models.TextField(blank=True)

    class Meta:
        ordering = ["-generated_at"]


class CompetitorPrice(models.Model):
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="competitor_prices")
    competitor = models.CharField(max_length=60)
    price = models.DecimalField(max_digits=9, decimal_places=2)
    note = models.CharField(max_length=160, blank=True)
    noted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    noted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-noted_at"]


class ProductView(models.Model):
    """Lightweight funnel tracking (views -> cart -> checkout -> order) for the abandonment funnel."""

    class Step(models.TextChoices):
        VIEW = "view"
        CART = "cart"
        CHECKOUT = "checkout"
        ORDER = "order"

    step = models.CharField(max_length=8, choices=Step.choices, db_index=True)
    session_key = models.CharField(max_length=64, blank=True)
    product = models.ForeignKey("catalog.Product", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
