from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Brand
from apps.promotions.models import Coupon

from .access import is_admin, teams_for
from .models import Head, MarketplaceSettings, Seller, SellerTeam, Territory, TerritoryPincode, TerritoryRequest


class HeadForm(forms.ModelForm):
    class Meta:
        model = Head
        fields = ["user", "brands", "territories", "active", "reason"]
        widgets = {
            "brands": forms.CheckboxSelectMultiple,
            "territories": forms.CheckboxSelectMultiple,
        }
        help_texts = {
            "user": _("Choose a separate registered account for this Head."),
            "brands": _("Select one or more brands using the checkboxes."),
            "territories": _("Select the areas this Head may manage. Create an area first if none are listed."),
        }
        labels = {
            "user": _("Account"),
            "brands": _("Brands"),
            "territories": _("Territories"),
            "active": _("Active"),
            "reason": _("Reason"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = get_user_model().objects.filter(role__in=["customer", "head"], is_active=True)

    def clean(self):
        data = super().clean()
        if self.instance.pk and data.get("user") and data["user"].pk != self.instance.user_id:
            self.add_error("user", _("Create a separate Head account instead of changing its identity."))
        if not data.get("active") and not data.get("reason", "").strip():
            self.add_error("reason", _("A suspension reason is required."))
        return data


class TerritoryForm(forms.ModelForm):
    codes = forms.CharField(
        label=_("Pincodes"), help_text=_("Comma-separated six-digit pincodes. Each pincode belongs to one area.")
    )

    class Meta:
        model = Territory
        fields = ["state", "state_code", "region", "name"]

    def clean_codes(self):
        codes = {c.strip() for c in self.cleaned_data["codes"].split(",")}
        validator = TerritoryPincode._meta.get_field("code").validators
        for code in codes:
            for validate in validator:
                validate(code)
        if TerritoryPincode.objects.filter(code__in=codes).exists():
            raise forms.ValidationError(_("A pincode already belongs to an area."))
        return sorted(codes)


class TeamForm(forms.ModelForm):
    class Meta:
        model = SellerTeam
        fields = ["seller", "brand", "head", "delivery_fee", "estimated_minutes"]

    def __init__(self, actor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not is_admin(actor):
            head = Head.objects.get(user=actor, active=True)
            self.fields["head"].queryset = Head.objects.filter(pk=head.pk)
            self.fields["head"].initial = head
            self.fields["head"].required = True
            self.fields["brand"].queryset = head.brands.all()
            self.fields["seller"].queryset = Seller.objects.filter(teams__head=head).distinct()

        if self.instance.pk:
            self.fields["seller"].disabled = True
            self.fields["brand"].disabled = True

    def clean(self):
        data = super().clean()
        if data.get("head") and data.get("brand") and not data["head"].brands.filter(pk=data["brand"].pk).exists():
            raise forms.ValidationError(_("Brand is outside this Head's authority."))
        return data


class SellerForm(forms.Form):
    name = forms.CharField(max_length=120, label=_("Seller name"))
    email = forms.EmailField(label=_("Seller email"))
    brand = forms.ModelChoiceField(queryset=Brand.objects.all(), label=_("Brand"))
    head = forms.ModelChoiceField(queryset=Head.objects.filter(active=True), required=False, label=_("Head"))

    def __init__(self, actor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not is_admin(actor):
            head = Head.objects.get(user=actor, active=True)
            self.fields["brand"].queryset = head.brands.all()
            self.fields["head"].queryset = Head.objects.filter(pk=head.pk)
            self.fields["head"].initial = head
            self.fields["head"].required = True

    def clean(self):
        data = super().clean()
        if data.get("head") and data.get("brand") and not data["head"].brands.filter(pk=data["brand"].pk).exists():
            raise forms.ValidationError(_("Brand is outside this Head's authority."))
        if data.get("email") and get_user_model().objects.filter(email__iexact=data["email"]).exists():
            raise forms.ValidationError(
                _("Use a new seller email. Existing sellers must be linked by admin after consent.")
            )
        return data


class AssignmentForm(forms.Form):
    team = forms.ModelChoiceField(queryset=SellerTeam.objects.none(), label=_("Seller team"))
    territory = forms.ModelChoiceField(queryset=Territory.objects.none(), label=_("Territory"))

    def __init__(self, actor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"].queryset = teams_for(actor)
        self.fields["territory"].queryset = (
            Territory.objects.all()
            if is_admin(actor)
            else Territory.objects.filter(heads__user=actor, heads__active=True)
        )


class RequestForm(forms.ModelForm):
    class Meta:
        model = TerritoryRequest
        fields = ["team", "territory", "reason"]

    def __init__(self, actor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"].queryset = teams_for(actor)


class CampaignForm(forms.ModelForm):
    teams = forms.ModelMultipleChoiceField(queryset=SellerTeam.objects.none(), label=_("Seller teams"))
    territories = forms.ModelMultipleChoiceField(
        queryset=Territory.objects.none(), required=False, label=_("Territories")
    )
    head = forms.ModelChoiceField(queryset=Head.objects.none(), label=_("Head"))

    class Meta:
        model = Coupon
        fields = [
            "code",
            "description",
            "kind",
            "value",
            "max_discount",
            "min_order",
            "starts_at",
            "expires_at",
            "usage_limit",
            "per_user_limit",
        ]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }

    def __init__(self, actor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["teams"].queryset = teams_for(actor).filter(head__isnull=False)
        self.fields["head"].queryset = (
            Head.objects.filter(active=True) if is_admin(actor) else Head.objects.filter(user=actor, active=True)
        )
        self.fields["territories"].queryset = (
            Territory.objects.all() if is_admin(actor) else Territory.objects.filter(heads__user=actor)
        )

    def clean_value(self):
        value = self.cleaned_data["value"]
        if value <= 0 or (self.data.get("kind") == "percent" and value > 100):
            raise forms.ValidationError(_("Enter a valid positive discount."))
        return value


class PolicyForm(forms.ModelForm):
    class Meta:
        model = MarketplaceSettings
        fields = [
            "enabled",
            "dispatch_enabled",
            "payouts_enabled",
            "translations_enabled",
            "online_override",
            "cod_override",
            "campaigns_enabled",
        ]


class ProductForm(forms.ModelForm):
    class Meta:
        from apps.catalog.models import Product

        model = Product
        fields = [
            "seller_team",
            "name",
            "source_language",
            "categories",
            "short_description",
            "description",
            "ingredients",
            "allergens",
            "storage_instructions",
            "is_active",
        ]

    def __init__(self, actor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["seller_team"].queryset = teams_for(actor).filter(active=True)
        self.fields["seller_team"].required = True


class VariantForm(forms.ModelForm):
    class Meta:
        from apps.catalog.models import ProductVariant

        model = ProductVariant
        fields = [
            "label",
            "sku",
            "volume_ml",
            "units_per_box",
            "price",
            "mrp",
            "cost_price",
            "gst_rate",
            "hsn_code",
            "max_per_order",
            "is_active",
        ]

    def clean_units_per_box(self):
        value = self.cleaned_data["units_per_box"]
        if value < 2:
            raise forms.ValidationError(_("At least two bottles per box are required."))
        return value


class SellerVerificationForm(forms.ModelForm):
    class Meta:
        model = Seller
        fields = ["status", "verified", "allow_multiple_brands", "linked_account_id", "payments_ready", "reason"]
        labels = {"allow_multiple_brands": _("Allow multiple brands for this Head-managed seller")}
        help_texts = {
            "allow_multiple_brands": _("Admin permission only. Independent sellers can already sell multiple brands.")
        }

    def clean(self):
        data = super().clean()
        if data.get("status") == "suspended" and not data.get("reason", "").strip():
            self.add_error("reason", _("A suspension reason is required."))
        if data.get("payments_ready") and (
            not data.get("verified") or not data.get("linked_account_id", "").startswith("acc_")
        ):
            raise forms.ValidationError(_("Verify the seller and approved linked account before enabling payments."))
        return data


class TranslationForm(forms.Form):
    source_hash = forms.CharField(widget=forms.HiddenInput)
    name = forms.CharField(max_length=120)
    short_description = forms.CharField(max_length=200, required=False)
    description = forms.CharField(widget=forms.Textarea, required=False)
    ingredients = forms.CharField(widget=forms.Textarea, required=False)
    allergens = forms.CharField(required=False)
    storage_instructions = forms.CharField(required=False)
    best_before_note = forms.CharField(required=False)
    reviewed = forms.BooleanField(label=_("I checked quantities, ingredients and allergens against the original."))


class ImportForm(forms.Form):
    team = forms.ModelChoiceField(queryset=SellerTeam.objects.none(), label=_("Seller team"))
    file = forms.FileField(label=_("CSV file"))

    def __init__(self, actor, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"].queryset = teams_for(actor).filter(active=True)

    def clean_file(self):
        file = self.cleaned_data["file"]
        if file.size > 2 * 1024 * 1024:
            raise forms.ValidationError(_("CSV files must be smaller than 2 MB."))
        return file


class SellerApplicationForm(forms.Form):
    name = forms.CharField(max_length=120, label=_("Seller name"))
    brand = forms.ModelMultipleChoiceField(
        queryset=Brand.objects.filter(is_active=True), widget=forms.CheckboxSelectMultiple, label=_("Brands")
    )
    territory = forms.ModelMultipleChoiceField(
        queryset=Territory.objects.all(), widget=forms.CheckboxSelectMultiple, label=_("Requested service areas")
    )


class OperationalLabels:
    labels = {
        "legal_name": _("Legal name"),
        "business_address": _("Business address"),
        "state_code": _("GST state code"),
        "gstin": _("GSTIN"),
        "fssai_number": _("FSSAI number"),
        "business_phone": _("Business phone"),
        "tax_registration": _("Tax registration"),
        "invoice_prefix": _("Invoice prefix"),
        "signatory": _("Authorized signatory"),
        "business_type": _("Business type"),
        "street1": _("Registered street address"),
        "street2": _("Address line 2"),
        "city": _("City"),
        "state": _("State"),
        "postal_code": _("Pincode"),
        "stakeholder_name": _("Authorized person's PAN name"),
        "business_pan": _("Business PAN"),
        "stakeholder_pan": _("Authorized person's PAN"),
        "bank_account": _("Bank account number"),
        "ifsc": _("IFSC"),
        "beneficiary_name": _("Bank beneficiary name"),
        "location_retention_days": _("Location retention days"),
        "activity_retention_days": _("Activity retention days"),
        "grievance_name": _("Grievance contact name"),
        "grievance_email": _("Grievance email"),
        "grievance_phone": _("Grievance phone"),
        "privacy_notice": _("Privacy notice"),
        "seller_terms": _("Seller terms"),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, label in self.labels.items():
            if name in self.fields:
                self.fields[name].label = label


class BusinessForm(OperationalLabels, forms.ModelForm):
    class Meta:
        model = Seller
        fields = [
            "legal_name",
            "business_address",
            "state_code",
            "gstin",
            "fssai_number",
            "business_phone",
            "tax_registration",
            "invoice_prefix",
            "signatory",
        ]

    def clean(self):
        data = super().clean()
        if data.get("gstin") and data.get("state_code") and not data["gstin"].startswith(data["state_code"]):
            self.add_error("gstin", _("GSTIN and state code must match."))
        if data.get("tax_registration") in ("regular", "composition") and not data.get("gstin"):
            self.add_error("gstin", _("GSTIN is required for this registration type."))
        return data


class BatchForm(forms.Form):
    code = forms.CharField(max_length=80, label=_("Batch code"))
    expires_on = forms.DateField(label=_("Expiry date"), widget=forms.DateInput(attrs={"type": "date"}))
    quantity = forms.IntegerField(min_value=1, label=_("Bottles received"))
    opening = forms.BooleanField(required=False, label=_("Assign all existing stock to this opening batch"))


class CaseForm(forms.Form):
    subject = forms.CharField(max_length=160, label=_("Subject"))
    text = forms.CharField(max_length=2000, widget=forms.Textarea, label=_("Message"))


class MessageForm(forms.Form):
    text = forms.CharField(max_length=2000, widget=forms.Textarea, label=_("Message"))
    status = forms.ChoiceField(
        choices=[("open", _("Open")), ("waiting", _("Waiting")), ("closed", _("Closed"))], label=_("Status")
    )


class OnboardingForm(OperationalLabels, forms.Form):
    business_type = forms.ChoiceField(
        choices=[
            (value, value.replace("_", " ").title())
            for value in (
                "proprietorship",
                "partnership",
                "private_limited",
                "llp",
                "public_limited",
                "not_yet_registered",
            )
        ]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["business_type"].choices = [
            ("proprietorship", _("Proprietorship")),
            ("partnership", _("Partnership")),
            ("private_limited", _("Private limited company")),
            ("llp", _("Limited liability partnership")),
            ("public_limited", _("Public limited company")),
            ("not_yet_registered", _("Not yet registered")),
        ]
        for name, field in self.fields.items():
            field.widget.attrs["autocomplete"] = (
                "new-password" if name in ("business_pan", "stakeholder_pan", "bank_account") else "off"
            )

    category = forms.CharField(max_length=80, label=_("Razorpay business category"))
    subcategory = forms.CharField(max_length=80, label=_("Razorpay business subcategory"))
    street = forms.CharField(max_length=200, label=_("Registered street address"))
    city = forms.CharField(max_length=80, label=_("City"))
    state = forms.CharField(max_length=80, label=_("State"))
    postal_code = forms.RegexField(r"^[1-9][0-9]{5}$", label=_("Pincode"))
    stakeholder_name = forms.CharField(max_length=120, label=_("Authorized person's PAN name"))
    business_pan = forms.RegexField(r"^[A-Z]{5}[0-9]{4}[A-Z]$", widget=forms.PasswordInput, label=_("Business PAN"))
    stakeholder_pan = forms.RegexField(
        r"^[A-Z]{5}[0-9]{4}[A-Z]$", widget=forms.PasswordInput, label=_("Authorized person's PAN")
    )
    bank_account = forms.RegexField(r"^[0-9]{6,20}$", widget=forms.PasswordInput, label=_("Bank account number"))
    ifsc = forms.RegexField(r"^[A-Z]{4}0[A-Z0-9]{6}$", label=_("IFSC"))
    beneficiary_name = forms.CharField(max_length=120, label=_("Bank beneficiary name"))
    accept_terms = forms.BooleanField(
        label=_("I am authorized for this business and accept Razorpay's linked-account terms.")
    )


class OperationsForm(OperationalLabels, forms.ModelForm):
    class Meta:
        from .models import MarketplaceOperations

        model = MarketplaceOperations
        fields = [
            "location_retention_days",
            "activity_retention_days",
            "grievance_name",
            "grievance_email",
            "grievance_phone",
            "privacy_notice",
            "seller_terms",
        ]


class ProductPhotoForm(forms.Form):
    image = forms.ImageField(label=_("Product photo"))
    alt = forms.CharField(max_length=120, required=False, label=_("Image description"))

    def clean_image(self):
        from apps.core.images import reencode

        return reencode(self.cleaned_data["image"])


class ShopProfileForm(forms.ModelForm):
    class Meta:
        model = Seller
        fields = ["name", "shop_description", "shop_published"]
        labels = {
            "name": _("Shop name"),
            "shop_description": _("About your shop"),
            "shop_published": _("Show my approved shop to buyers"),
        }
        help_texts = {
            "shop_published": _(
                "Your shop is visible only after seller verification, brand approval and service-area assignment."
            )
        }
        widgets = {"shop_description": forms.Textarea(attrs={"rows": 4})}


class ShopBrandRequestForm(forms.Form):
    brand = forms.ModelChoiceField(queryset=Brand.objects.filter(is_active=True), label=_("Brand"))
    territories = forms.ModelMultipleChoiceField(
        queryset=Territory.objects.all(), widget=forms.CheckboxSelectMultiple, label=_("Requested service areas")
    )

    def __init__(self, seller, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seller = seller
        self.fields["brand"].queryset = self.fields["brand"].queryset.exclude(seller_teams__seller=seller)

    def clean(self):
        data = super().clean()
        if self.seller.teams.filter(head__isnull=False, active=True).exists() and not self.seller.allow_multiple_brands:
            raise forms.ValidationError(_("Ask admin for multi-brand permission before requesting another brand."))
        return data
