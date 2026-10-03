from django.conf import settings
from django.db import models


class StockMovement(models.Model):
    class Reason(models.TextChoices):
        INITIAL = "initial", "Initial stock"
        SALE = "sale", "Sale"
        REFUND_RESTOCK = "refund", "Refund restock"
        CANCEL_RESTOCK = "cancel", "Cancelled order restock"
        MANUAL = "manual", "Manual adjustment"
        IMPORT = "import", "CSV import"
        DAMAGE = "damage", "Damaged / expired"

    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="movements")
    delta = models.IntegerField()
    balance_after = models.IntegerField()
    reason = models.CharField(max_length=10, choices=Reason.choices)
    note = models.CharField(max_length=200, blank=True)
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class StockReservation(models.Model):
    """Stock held while an online payment is in progress; released by Celery when it expires."""

    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE, related_name="reservations")
    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="reservations")
    qty = models.PositiveIntegerField()
    expires_at = models.DateTimeField(db_index=True)
    released = models.BooleanField(default=False)
    committed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
