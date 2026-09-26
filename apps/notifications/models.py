from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import SingletonModel

ADMIN_EVENTS = {
    "new_order": _("New order"),
    "payment_succeeded": _("Payment success"),
    "payment_failed": _("Payment failure"),
    "order_cancelled": _("Order cancelled"),
    "out_of_stock": _("Product out of stock"),
    "low_stock": _("Low stock"),
    "product_added": _("Product added"),
    "product_updated": _("Product updated"),
    "product_removed": _("Product removed"),
    "price_changed": _("Price changed"),
    "refund_issued": _("Refund issued"),
    "new_review": _("New review"),
    "new_ticket": _("New support ticket"),
    "bulk_quote": _("New party / bulk order request"),
    "thandu_complaint": _("Thandu guarantee complaint"),
    "daily_summary": _("Daily sales summary"),
    "weekly_summary": _("Weekly / monthly summary"),
    "security_login": _("New admin login"),
    "security_failed_logins": _("Failed logins"),
    "security_settings": _("Settings changed"),
}

CUSTOMER_EVENTS = {
    "welcome": _("Welcome + email verification"),
    "order_placed": _("Order placed"),
    "payment_received": _("Payment received"),
    "payment_failed": _("Payment failed"),
    "order_confirmed": _("Order confirmed"),
    "order_packed": _("Order packed"),
    "order_out_for_delivery": _("Out for delivery"),
    "order_delivered": _("Delivered + invoice"),
    "order_cancelled": _("Order cancelled"),
    "refund_initiated": _("Refund initiated"),
    "refund_completed": _("Refund completed"),
    "rate_order": _("Rate your order"),
    "back_in_stock": _("Back in stock"),
}


def default_toggles():
    return {k: True for k in [*ADMIN_EVENTS, *[f"c:{k}" for k in CUSTOMER_EVENTS]]}


class NotificationSettings(SingletonModel):
    admin_recipients = models.TextField(blank=True, help_text=_("One email per line"))
    toggles = models.JSONField(default=default_toggles)

    cache_key = "notification_settings"

    def recipients(self):
        return [line.strip() for line in self.admin_recipients.splitlines() if "@" in line]

    def is_on(self, key):
        return self.toggles.get(key, True)


class EmailLog(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")
        NOT_SENT = "not_sent", _("Not sent (email not set up)")

    to = models.CharField(max_length=500)
    subject = models.CharField(max_length=200)
    template = models.CharField(max_length=60)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
