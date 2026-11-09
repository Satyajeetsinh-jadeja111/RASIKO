import secrets
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.images import RandomUploadPath
from apps.core.models import TimeStamped

ZERO = Decimal("0")


class Order(TimeStamped):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", _("Awaiting payment")
        PLACED = "placed", _("Placed")
        CONFIRMED = "confirmed", _("Confirmed")
        PACKED = "packed", _("Packed")
        OUT_FOR_DELIVERY = "out_for_delivery", _("Out for delivery")
        DELIVERED = "delivered", _("Delivered")
        CANCELLED = "cancelled", _("Cancelled")
        PAYMENT_FAILED = "payment_failed", _("Payment failed")
        REFUNDED = "refunded", _("Refunded")

    class PaymentMethod(models.TextChoices):
        COD = "cod", _("Cash on Delivery")
        RAZORPAY = "razorpay", _("Razorpay (UPI / cards / netbanking)")
        STRIPE = "stripe", _("Card (Stripe)")

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        PAID = "paid", _("Paid")
        FAILED = "failed", _("Failed")
        COD_DUE = "cod_due", _("Cash due on delivery")
        COD_COLLECTED = "cod_collected", _("Cash collected")
        PARTIALLY_REFUNDED = "partial_refund", _("Partially refunded")
        REFUNDED = "refunded", _("Refunded")

    TIMELINE = [Status.PLACED, Status.CONFIRMED, Status.PACKED, Status.OUT_FOR_DELIVERY, Status.DELIVERED]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    number = models.CharField(max_length=20, unique=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    payment_status = models.CharField(max_length=15, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    checkout_token = models.CharField(max_length=64, unique=True, help_text="Prevents double submission")

    # Address snapshot
    ship_name = models.CharField(max_length=80)
    ship_phone = models.CharField(max_length=15)
    ship_address = models.CharField(max_length=400)
    ship_pincode = models.CharField(max_length=6, db_index=True)
    ship_area = models.CharField(max_length=120, blank=True)
    ship_lat = models.DecimalField(max_digits=9, decimal_places=6)
    ship_lng = models.DecimalField(max_digits=9, decimal_places=6)
    road_km = models.DecimalField(max_digits=6, decimal_places=2, default=ZERO)

    # Slot
    is_asap = models.BooleanField(default=True)
    slot_start = models.DateTimeField(null=True, blank=True)
    slot_label = models.CharField(max_length=80, blank=True)
    fast_promise = models.BooleanField(default=False)

    # Money (all recalculated on the server at checkout; GST is included in prices)
    mrp_total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    coupon = models.ForeignKey("promotions.Coupon", null=True, blank=True, on_delete=models.SET_NULL)
    coupon_code = models.CharField(max_length=30, blank=True)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    coins_used = models.PositiveIntegerField(default=0)
    coins_value = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    delivery_fee = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    small_order_fee = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    surcharge_total = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    surcharges = models.JSONField(default=list, blank=True)
    gst_total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    refunded_total = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    delivery_cost = models.DecimalField(max_digits=8, decimal_places=2, default=ZERO)
    coins_earned = models.PositiveIntegerField(default=0)

    # Fulfilment
    rider = models.ForeignKey("delivery.Rider", null=True, blank=True, on_delete=models.SET_NULL)
    rider_name = models.CharField(max_length=80, blank=True)
    rider_phone = models.CharField(max_length=15, blank=True)
    delivery_otp = models.CharField(max_length=4, blank=True)
    customer_note = models.CharField(max_length=300, blank=True)
    staff_note = models.TextField(blank=True)
    placed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    source = models.CharField(max_length=15, default="web", help_text="web / subscription / reorder / bulk")
    rate_email_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "placed_at"])]

    def __str__(self):
        return self.number or str(self.public_id)

    def save(self, *args, **kwargs):
        if not self.delivery_otp:
            self.delivery_otp = f"{secrets.randbelow(10000):04d}"
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"RSK{self.pk:06d}"
            Order.objects.filter(pk=self.pk).update(number=self.number)

    def get_absolute_url(self):
        return reverse("orders:detail", args=[self.public_id])

    @property
    def savings(self):
        return max(ZERO, self.mrp_total - self.subtotal) + self.discount + self.coins_value

    @property
    def is_online(self):
        return self.payment_method != self.PaymentMethod.COD

    @property
    def is_open(self):
        return self.status in {
            self.Status.PLACED,
            self.Status.CONFIRMED,
            self.Status.PACKED,
            self.Status.OUT_FOR_DELIVERY,
        }

    @property
    def can_cancel_by_customer(self):
        return self.status in {self.Status.PLACED, self.Status.CONFIRMED, self.Status.PENDING_PAYMENT}

    @property
    def refundable_amount(self):
        return max(ZERO, self.total - self.refunded_total)

    def timeline(self):
        """[(label, event_or_None, state)] where state is done / current / todo."""
        events = {e.status: e for e in self.events.all()}
        current = self.TIMELINE.index(self.status) if self.status in self.TIMELINE else -1
        steps = []
        for i, st in enumerate(self.TIMELINE):
            state = "done" if i < current else ("current" if i == current else "todo")
            if st == self.Status.DELIVERED and i == current:
                state = "done"
            steps.append((st.label, events.get(st), state))
        return steps


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.PROTECT, related_name="order_lines")
    product_name = models.CharField(max_length=120)
    variant_label = models.CharField(max_length=40)
    sku = models.CharField(max_length=40)
    hsn_code = models.CharField(max_length=8)
    gst_rate = models.DecimalField(max_digits=4, decimal_places=2)
    qty = models.PositiveIntegerField()  # boxes
    units_per_box = models.PositiveSmallIntegerField(default=1)  # bottles per box when ordered (for restocking)
    unit_mrp = models.DecimalField(max_digits=9, decimal_places=2)
    unit_price = models.DecimalField(max_digits=9, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=9, decimal_places=2, default=ZERO)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)
    combo_name = models.CharField(max_length=80, blank=True)
    refunded_qty = models.PositiveIntegerField(default=0)
    restocked_qty = models.PositiveIntegerField(default=0, editable=False)

    def __str__(self):
        return f"{self.qty} × {self.product_name} {self.variant_label}"

    @property
    def taxable_value(self):
        return (self.line_total * 100 / (100 + self.gst_rate)).quantize(Decimal("0.01"))

    @property
    def gst_amount(self):
        return self.line_total - self.taxable_value

    @property
    def refundable_qty(self):
        return self.qty - self.refunded_qty


class OrderEvent(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20, choices=Order.Status.choices)
    note = models.CharField(max_length=300, blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at"]


class Subscription(TimeStamped):
    class Frequency(models.TextChoices):
        DAILY = "daily", _("Every day")
        WEEKLY = "weekly", _("Every week")

    class State(models.TextChoices):
        ACTIVE = "active", _("Active")
        PAUSED = "paused", _("Paused")
        CANCELLED = "cancelled", _("Cancelled")

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE)
    qty = models.PositiveSmallIntegerField(default=1)
    frequency = models.CharField(max_length=6, choices=Frequency.choices, default=Frequency.DAILY)
    weekday = models.PositiveSmallIntegerField(null=True, blank=True, help_text="0=Monday for weekly")
    address = models.ForeignKey("accounts.Address", on_delete=models.PROTECT)
    delivery_time = models.TimeField(help_text="Preferred delivery time")
    state = models.CharField(max_length=10, choices=State.choices, default=State.ACTIVE)
    skip_dates = models.JSONField(default=list, blank=True)
    next_run = models.DateField()
    last_order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")


class BulkQuote(TimeStamped):
    class Kind(models.TextChoices):
        WEDDING = "wedding", _("Wedding / function")
        OFFICE = "office", _("Office")
        SHOP = "shop", _("Shop / resale")
        OTHER = "other", _("Other")

    class State(models.TextChoices):
        NEW = "new", _("New")
        QUOTED = "quoted", _("Quoted")
        WON = "won", _("Confirmed")
        LOST = "lost", _("Closed")

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=80)
    phone = models.CharField(max_length=15)
    email = models.EmailField()
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.WEDDING)
    event_date = models.DateField()
    requirements = models.TextField(help_text=_("What do you need? e.g. 20 crates of soft drinks, 300 lassi"))
    budget = models.CharField(max_length=40, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.NEW)
    quoted_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    staff_note = models.TextField(blank=True)


class ThanduComplaint(TimeStamped):
    """'Thandu guarantee': drink arrived warm -> photo complaint -> admin approves a coupon."""

    class State(models.TextChoices):
        PENDING = "pending", _("Pending review")
        APPROVED = "approved", _("Approved: coupon sent")
        REJECTED = "rejected", _("Rejected")

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="thandu_complaint")
    photo = models.ImageField(upload_to=RandomUploadPath("complaints"))
    note = models.CharField(max_length=300, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    coupon = models.ForeignKey("promotions.Coupon", null=True, blank=True, on_delete=models.SET_NULL)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
