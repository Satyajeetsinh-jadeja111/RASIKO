import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStamped


class Payment(TimeStamped):
    class Status(models.TextChoices):
        CREATED = "created", _("Created")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="payments")
    gateway = models.CharField(max_length=10)
    gateway_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    gateway_payment_id = models.CharField(max_length=100, blank=True, db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED)
    idempotency_key = models.CharField(max_length=64, unique=True, default=uuid.uuid4)
    failure_reason = models.CharField(max_length=300, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.gateway} {self.gateway_order_id} {self.status}"


class Refund(TimeStamped):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")

    class Method(models.TextChoices):
        GATEWAY = "gateway", _("Original payment method")
        UPI = "upi", _("UPI (manual)")
        CASH = "cash", _("Cash (manual)")
        BANK = "bank", _("Bank transfer (manual)")

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="refunds")
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="refunds")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    lines = models.JSONField(default=dict, blank=True, help_text="{order_line_id: qty}")
    reason = models.CharField(max_length=300)
    method = models.CharField(max_length=8, choices=Method.choices, default=Method.GATEWAY)
    reference = models.CharField(max_length=100, blank=True, help_text="UPI / bank reference for manual refunds")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    gateway_refund_id = models.CharField(max_length=100, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=64, unique=True, default=uuid.uuid4)
    restock = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    failure_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund ₹{self.amount} on {self.order}"


class WebhookEvent(models.Model):
    """Every processed webhook, so a replayed event is ignored (idempotency)."""

    gateway = models.CharField(max_length=10)
    event_id = models.CharField(max_length=120)
    event_type = models.CharField(max_length=80)
    received_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField(default=dict)

    class Meta:
        unique_together = [("gateway", "event_id")]


ZERO = Decimal("0")
