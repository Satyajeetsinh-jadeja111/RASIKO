"""Tenant boundaries and immutable fulfillment/financial snapshots for the marketplace."""

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.models import SingletonModel, TimeStamped

MONEY = {"max_digits": 12, "decimal_places": 2, "default": Decimal("0")}


class MarketplaceSettings(SingletonModel):
    enabled = models.BooleanField(default=False)
    dispatch_enabled = models.BooleanField(default=False)
    payouts_enabled = models.BooleanField(default=False)
    translations_enabled = models.BooleanField(default=False)
    # Null means inherit; explicit booleans are forced global policy.
    online_override = models.BooleanField(null=True, blank=True)
    cod_override = models.BooleanField(null=True, blank=True)
    campaigns_enabled = models.BooleanField(default=True)


class Seller(TimeStamped):
    name = models.CharField(max_length=120)
    shop_description = models.CharField(max_length=600, blank=True)
    shop_published = models.BooleanField(default=False)
    legal_name = models.CharField(max_length=200, blank=True)
    business_address = models.TextField(blank=True)
    state_code = models.CharField(max_length=2, blank=True, validators=[RegexValidator(r"^[0-9]{2}$")])
    gstin = models.CharField(max_length=15, blank=True, validators=[RegexValidator(r"^[0-9]{2}[A-Z0-9]{13}$")])
    fssai_number = models.CharField(max_length=14, blank=True, validators=[RegexValidator(r"^[0-9]{14}$")])
    business_phone = models.CharField(max_length=15, blank=True)
    tax_registration = models.CharField(
        max_length=12,
        default="unregistered",
        choices=[("regular", "Regular GST"), ("composition", "Composition"), ("unregistered", "Unregistered")],
    )
    invoice_prefix = models.CharField(max_length=4, default="RS", validators=[RegexValidator(r"^[A-Z0-9]{1,4}$")])
    signatory = models.CharField(max_length=120, blank=True)
    onboarding_encrypted = models.TextField(blank=True)
    onboarding_status = models.CharField(max_length=20, default="not_started")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="seller_accounts")
    status = models.CharField(
        max_length=12,
        choices=[("pending", "Pending"), ("active", "Active"), ("suspended", "Suspended")],
        default="pending",
    )
    allow_multiple_brands = models.BooleanField(default=False)
    verified = models.BooleanField(default=False)
    linked_account_id = models.CharField(max_length=80, blank=True)
    payments_ready = models.BooleanField(default=False)
    reason = models.CharField(max_length=300, blank=True)
    legacy_store = models.BooleanField(default=None, unique=True, null=True)

    def clean(self):
        super().clean()
        if self.pk and not self.allow_multiple_brands:
            active = self.teams.filter(active=True)
            if active.filter(head__isnull=False).exists() and active.values("brand_id").distinct().count() > 1:
                raise ValidationError(
                    {"allow_multiple_brands": "Deactivate extra brand teams before removing multi-brand permission."}
                )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                Seller.objects.select_for_update().get(pk=self.pk)
            self.clean()
            return super().save(*args, **kwargs)

    @property
    def onboarding_label(self):
        from django.utils.translation import gettext_lazy as _

        return {
            "not_started": _("Not started"),
            "queued": _("Queued for verification"),
            "submitted": _("Submitted for verification"),
            "activated": _("Approved"),
            "needs_clarification": _("Additional details needed"),
            "under_review": _("Under review"),
            "requested": _("Verification requested"),
        }.get(self.onboarding_status, _("Pending review"))

    def __str__(self):
        return self.name


class Territory(TimeStamped):
    state_code = models.CharField(max_length=2, blank=True, validators=[RegexValidator(r"^[0-9]{2}$")])

    """Canonical, non-overlapping pincode areas; parent fields group reports."""

    state = models.CharField(max_length=80)
    region = models.CharField(max_length=80)
    name = models.CharField(max_length=120)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["state", "region", "name"], name="market_area_unique")]

    def __str__(self):
        return f"{self.state} / {self.region} / {self.name}"


class TerritoryPincode(models.Model):
    territory = models.ForeignKey(Territory, on_delete=models.CASCADE, related_name="pincodes")
    code = models.CharField(max_length=6, unique=True, validators=[RegexValidator(r"^[1-9][0-9]{5}$")])


class Head(TimeStamped):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="brand_head")
    brands = models.ManyToManyField("catalog.Brand", related_name="heads")
    territories = models.ManyToManyField(Territory, related_name="heads")
    active = models.BooleanField(default=True)
    reason = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return str(self.user)


class SellerTeam(TimeStamped):
    seller = models.ForeignKey(Seller, on_delete=models.PROTECT, related_name="teams")
    brand = models.ForeignKey("catalog.Brand", on_delete=models.PROTECT, related_name="seller_teams")
    head = models.ForeignKey(Head, null=True, blank=True, on_delete=models.PROTECT, related_name="teams")
    active = models.BooleanField(default=True)
    online_enabled = models.BooleanField(default=False)
    cod_enabled = models.BooleanField(default=True)
    delivery_fee = models.DecimalField(**MONEY, validators=[MinValueValidator(0)])
    estimated_minutes = models.PositiveIntegerField(default=60, validators=[MinValueValidator(1)])
    reason = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["seller", "brand"], name="market_seller_brand_unique")]

    def validate_brand_permission(self, seller=None):
        seller = seller or self.seller
        if not self.active or seller.allow_multiple_brands:
            return
        others = SellerTeam.objects.filter(seller_id=self.seller_id, active=True).exclude(pk=self.pk)
        if (self.head_id or others.filter(head__isnull=False).exists()) and others.exclude(
            brand_id=self.brand_id
        ).exists():
            raise ValidationError("A seller managed by a Head needs admin permission to sell multiple brands.")

    def clean(self):
        super().clean()
        if self.seller_id and self.brand_id:
            self.validate_brand_permission()

    def save(self, *args, **kwargs):
        with transaction.atomic():
            seller = Seller.objects.select_for_update().get(pk=self.seller_id)
            self.validate_brand_permission(seller)
            return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.seller} · {self.brand}"


class TerritoryAssignment(TimeStamped):
    team = models.ForeignKey(SellerTeam, on_delete=models.PROTECT, related_name="assignments")
    brand = models.ForeignKey("catalog.Brand", on_delete=models.PROTECT)
    territory = models.ForeignKey(Territory, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)
    effective_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "territory"], condition=Q(active=True), name="market_brand_area_exclusive"
            ),
            models.UniqueConstraint(
                fields=["team", "territory"], condition=Q(active=True), name="market_team_area_unique"
            ),
        ]


class TerritoryRequest(TimeStamped):
    team = models.ForeignKey(SellerTeam, on_delete=models.PROTECT)
    territory = models.ForeignKey(Territory, on_delete=models.PROTECT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="territory_requests"
    )
    reason = models.CharField(max_length=300)
    status = models.CharField(
        max_length=12,
        default="pending",
        choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="territory_decisions"
    )
    decision_reason = models.CharField(max_length=300, blank=True)
    effective_at = models.DateTimeField(null=True)


class Notice(TimeStamped):
    seller = models.ForeignKey(Seller, on_delete=models.CASCADE, related_name="notices")
    title = models.CharField(max_length=160)
    message = models.TextField()
    read_at = models.DateTimeField(null=True, blank=True)


class HeadCampaign(TimeStamped):
    head = models.ForeignKey(Head, on_delete=models.PROTECT)
    coupon = models.OneToOneField("promotions.Coupon", on_delete=models.PROTECT, related_name="head_campaign")
    teams = models.ManyToManyField(SellerTeam, related_name="head_campaigns")
    territories = models.ManyToManyField(Territory, blank=True)
    active = models.BooleanField(default=True)
    # Always seller funded in v1. This is deliberately not client-selectable.
    funding = models.CharField(max_length=12, default="seller", editable=False)


class FeePolicy(TimeStamped):
    percent = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    enabled = models.BooleanField(default=False)
    effective_at = models.DateTimeField()
    notified_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class Fulfillment(TimeStamped):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="fulfillments")
    team = models.ForeignKey(SellerTeam, on_delete=models.PROTECT, related_name="fulfillments")
    territory = models.ForeignKey(Territory, null=True, on_delete=models.PROTECT)
    status = models.CharField(
        max_length=20,
        default="placed",
        choices=[
            (s, s.replace("_", " ").title())
            for s in ("placed", "confirmed", "ready", "assigned", "picked_up", "delivered", "cancelled")
        ],
    )
    subtotal = models.DecimalField(**MONEY)
    discount = models.DecimalField(**MONEY)
    coins_value = models.DecimalField(**MONEY)
    delivery_fee = models.DecimalField(**MONEY)
    tax = models.DecimalField(**MONEY)
    platform_fee = models.DecimalField(**MONEY)
    total = models.DecimalField(**MONEY)
    fee_policy = models.ForeignKey(FeePolicy, null=True, on_delete=models.PROTECT)
    policy = models.JSONField(default=dict)
    delivered_at = models.DateTimeField(null=True)
    ready_at = models.DateTimeField(null=True)
    dispatch_attempts = models.PositiveSmallIntegerField(default=0)
    intervention_required = models.BooleanField(default=False)
    delivery_otp_hash = models.CharField(max_length=128, blank=True)
    delivery_otp_encrypted = models.TextField(blank=True)
    otp_failures = models.PositiveSmallIntegerField(default=0)
    last_otp_reset = models.DateTimeField(null=True)

    @property
    def buyer_delivery_code(self):
        from apps.core.crypto import decrypt_str

        return decrypt_str(self.delivery_otp_encrypted) if self.status in ("ready", "assigned", "picked_up") else ""

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order", "team"], name="market_order_team_unique")]


class FulfillmentLine(models.Model):
    fulfillment = models.ForeignKey(Fulfillment, on_delete=models.PROTECT, related_name="lines")
    order_line = models.OneToOneField("orders.OrderLine", on_delete=models.PROTECT, related_name="fulfillment_line")


class RiderAccount(TimeStamped):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="rider_account")
    seller = models.ForeignKey(Seller, on_delete=models.PROTECT, related_name="riders")
    active = models.BooleanField(default=True)
    online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True)
    location_consent = models.BooleanField(default=False)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    reason = models.CharField(max_length=300, blank=True)


class RiderInvitation(TimeStamped):
    seller = models.ForeignKey(Seller, on_delete=models.PROTECT)
    email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class RiderEvent(TimeStamped):
    rider = models.ForeignKey(RiderAccount, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=40)
    fulfillment = models.ForeignKey(Fulfillment, null=True, on_delete=models.PROTECT)
    details = models.JSONField(default=dict)


class DispatchOffer(TimeStamped):
    fulfillment = models.ForeignKey(Fulfillment, on_delete=models.PROTECT, related_name="offers")
    rider = models.ForeignKey(RiderAccount, on_delete=models.PROTECT, related_name="offers")
    expires_at = models.DateTimeField()
    status = models.CharField(
        max_length=12,
        default="pending",
        choices=[(s, s.title()) for s in ("pending", "accepted", "expired", "lost", "declined")],
    )


class DeliveryAssignment(TimeStamped):
    fulfillment = models.OneToOneField(Fulfillment, on_delete=models.PROTECT, related_name="delivery_assignment")
    rider = models.ForeignKey(RiderAccount, on_delete=models.PROTECT, related_name="deliveries")
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["rider"], condition=Q(active=True), name="market_rider_one_delivery")
        ]


class LedgerEntry(TimeStamped):
    fulfillment = models.ForeignKey(Fulfillment, on_delete=models.PROTECT, related_name="ledger")
    kind = models.CharField(
        max_length=30,
        choices=[
            (s, s.replace("_", " ").title())
            for s in (
                "sale",
                "discount",
                "platform_fee",
                "refund",
                "cod_collected",
                "cod_remitted",
                "transfer",
                "settlement",
                "adjustment",
                "transfer_reversal",
            )
        ],
    )
    amount = models.DecimalField(**MONEY)
    key = models.CharField(max_length=160, unique=True)
    reference = models.CharField(max_length=120, blank=True)


class Settlement(TimeStamped):
    fulfillment = models.OneToOneField(Fulfillment, on_delete=models.PROTECT, related_name="settlement")
    amount = models.DecimalField(**MONEY)
    status = models.CharField(
        max_length=20,
        default="held",
        choices=[
            (s, s.title()) for s in ("held", "eligible", "submitting", "uncertain", "transferred", "settled", "failed")
        ],
    )
    provider_id = models.CharField(max_length=100, blank=True)
    recipient_settlement_id = models.CharField(max_length=100, blank=True)
    bank_reference = models.CharField(max_length=120, blank=True)
    settled_at = models.DateTimeField(null=True)
    provider_status = models.CharField(max_length=30, blank=True)
    key = models.UUIDField(default=uuid.uuid4, unique=True)
    attempts = models.PositiveIntegerField(default=0)
    last_checked = models.DateTimeField(null=True)
    disputed = models.BooleanField(default=False)


class ProductTranslation(TimeStamped):
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=2, choices=[("en", "English"), ("hi", "Hindi"), ("gu", "Gujarati")])
    source_hash = models.CharField(max_length=64)
    content = models.JSONField(default=dict)
    status = models.CharField(
        max_length=12, default="pending", choices=[(s, s.title()) for s in ("pending", "ready", "failed", "review")]
    )
    corrected = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "language"], name="market_product_language")]


class RiderToken(TimeStamped):
    rider = models.ForeignKey(RiderAccount, on_delete=models.CASCADE, related_name="tokens")
    digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()


class RiderDevice(TimeStamped):
    rider = models.ForeignKey(RiderAccount, on_delete=models.CASCADE, related_name="devices")
    token = models.TextField()
    platform = models.CharField(max_length=7, choices=[("android", "Android"), ("ios", "iOS")])
    active = models.BooleanField(default=True)


class TransferReversal(TimeStamped):
    settlement = models.ForeignKey(Settlement, on_delete=models.PROTECT, related_name="reversals")
    refund = models.ForeignKey("payments.Refund", on_delete=models.PROTECT)
    amount = models.DecimalField(**MONEY)
    key = models.UUIDField(default=uuid.uuid4, unique=True)
    status = models.CharField(max_length=20, default="pending")
    provider_id = models.CharField(max_length=100, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_checked = models.DateTimeField(null=True)
    error = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["settlement", "refund"], name="market_reversal_refund_unique")]


class OnboardingOperation(TimeStamped):
    seller = models.ForeignKey(Seller, on_delete=models.PROTECT, related_name="onboarding_operations")
    step = models.CharField(max_length=20)
    key = models.UUIDField(default=uuid.uuid4, unique=True)
    status = models.CharField(max_length=20, default="pending")
    provider_id = models.CharField(max_length=100, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=80, blank=True)
    last_checked = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["seller", "step"], name="market_onboard_step_unique")]


class StockBatch(TimeStamped):
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.PROTECT, related_name="batches")
    code = models.CharField(max_length=80)
    expires_on = models.DateField()
    remaining = models.PositiveIntegerField()
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["variant", "code"], name="market_batch_code_unique")]


class BatchAllocation(models.Model):
    order_line = models.ForeignKey("orders.OrderLine", on_delete=models.PROTECT, related_name="batch_allocations")
    batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    restored = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order_line", "batch"], name="market_line_batch_unique")]


class SellerInvoice(TimeStamped):
    fulfillment = models.OneToOneField(Fulfillment, on_delete=models.PROTECT, related_name="invoice")
    number = models.CharField(max_length=16)
    fiscal_year = models.CharField(max_length=4)
    snapshot = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["fulfillment", "number"], name="market_invoice_unique")]


class InvoiceSequence(models.Model):
    seller = models.ForeignKey(Seller, on_delete=models.PROTECT)
    fiscal_year = models.CharField(max_length=4)
    next_number = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["seller", "fiscal_year"], name="market_invoice_sequence_unique")]


class SellerCase(TimeStamped):
    fulfillment = models.ForeignKey(Fulfillment, on_delete=models.PROTECT, related_name="cases")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    subject = models.CharField(max_length=160)
    status = models.CharField(
        max_length=12, default="open", choices=[("open", "Open"), ("waiting", "Waiting"), ("closed", "Closed")]
    )


class CaseMessage(TimeStamped):
    case = models.ForeignKey(SellerCase, on_delete=models.PROTECT, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    text = models.TextField(max_length=2000)


class OperationalAlert(TimeStamped):
    key = models.CharField(max_length=160, unique=True)
    kind = models.CharField(max_length=40)
    fulfillment = models.ForeignKey(Fulfillment, null=True, on_delete=models.PROTECT)
    resolved_at = models.DateTimeField(null=True)


class MarketplaceOperations(SingletonModel):
    location_retention_days = models.PositiveSmallIntegerField(
        default=7, validators=[MinValueValidator(1), MaxValueValidator(90)]
    )
    activity_retention_days = models.PositiveSmallIntegerField(
        default=90, validators=[MinValueValidator(7), MaxValueValidator(730)]
    )
    grievance_name = models.CharField(max_length=120, blank=True)
    grievance_email = models.EmailField(blank=True)
    grievance_phone = models.CharField(max_length=20, blank=True)
    privacy_notice = models.TextField(blank=True)
    seller_terms = models.TextField(blank=True)
