from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import StyledMixin
from apps.catalog.models import ProductVariant

from .models import BulkQuote, Subscription


class TrackForm(StyledMixin, forms.Form):
    number = forms.CharField(
        label=_("Order number"), max_length=20, widget=forms.TextInput(attrs={"placeholder": "RSK000123"})
    )
    contact = forms.CharField(label=_("Registered mobile or email"), max_length=254)


class ThanduForm(StyledMixin, forms.Form):
    photo = forms.ImageField(label=_("Photo of the drink"))
    note = forms.CharField(label=_("What happened? (optional)"), max_length=300, required=False)


class BulkQuoteForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = BulkQuote
        fields = ["name", "phone", "email", "kind", "event_date", "requirements", "budget"]
        widgets = {
            "event_date": forms.DateInput(attrs={"type": "date"}),
            "requirements": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and user.is_authenticated and not self.is_bound:
            self.initial.update(name=user.first_name, email=user.email, phone=user.phone)

    def clean_event_date(self):
        d = self.cleaned_data["event_date"]
        if d < timezone.localdate():
            raise forms.ValidationError(_("Choose a future date."))
        return d


class SubscriptionForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Subscription
        fields = ["variant", "qty", "frequency", "weekday", "address", "delivery_time"]
        widgets = {
            "delivery_time": forms.TimeInput(attrs={"type": "time"}),
            "weekday": forms.Select(
                choices=[
                    ("", "—"),
                    *[
                        (i, d)
                        for i, d in enumerate(
                            ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                        )
                    ],
                ]
            ),
        }
        labels = {"variant": _("Product"), "qty": _("Quantity each time"), "weekday": _("Day (weekly only)")}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["address"].queryset = user.addresses.all()
        self.fields["variant"].queryset = ProductVariant.objects.filter(
            is_active=True, product__is_active=True, product__deleted_at__isnull=True
        ).select_related("product")
        self.fields["variant"].label_from_instance = lambda v: f"{v.product.name} · {v.label} · ₹{v.price}"

    def clean(self):
        data = super().clean()
        if data.get("frequency") == Subscription.Frequency.WEEKLY and data.get("weekday") is None:
            self.add_error("weekday", _("Choose a day for weekly delivery."))
        if data.get("qty") and not (1 <= data["qty"] <= 50):
            self.add_error("qty", _("Choose 1 to 50."))
        return data
