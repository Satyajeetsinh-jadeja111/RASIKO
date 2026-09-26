from django import forms
from django.contrib.auth import password_validation
from django.utils.translation import gettext_lazy as _

from apps.delivery.services import check_service_area

from .models import Address, User

INPUT = "input"


class StyledMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", INPUT)


class LoginForm(StyledMixin, forms.Form):
    username = forms.EmailField(label=_("Email"), widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(
        label=_("Password"), widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )


class SignupForm(StyledMixin, forms.ModelForm):
    password1 = forms.CharField(label=_("Password"), widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    referral = forms.CharField(label=_("Referral code (optional)"), required=False, max_length=12)

    class Meta:
        model = User
        fields = ["first_name", "email", "phone"]
        labels = {"first_name": _("Your name")}

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(_("An account with this email already exists."))
        return email

    def clean_phone(self):
        phone = "".join(c for c in self.cleaned_data.get("phone", "") if c.isdigit())[-10:]
        if phone and len(phone) != 10:
            raise forms.ValidationError(_("Enter a 10-digit mobile number."))
        return phone

    def clean_password1(self):
        pw = self.cleaned_data["password1"]
        password_validation.validate_password(pw, User(email=self.cleaned_data.get("email", "")))
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        code = (self.cleaned_data.get("referral") or "").strip().upper()
        if code:
            user.referred_by = User.objects.filter(referral_code=code).first()
        if commit:
            user.save()
        return user


class ProfileForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone", "birthday", "preferred_language", "marketing_opt_in"]
        widgets = {"birthday": forms.DateInput(attrs={"type": "date"})}


class AddressForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Address
        fields = ["label", "name", "phone", "line1", "line2", "pincode", "lat", "lng", "is_default"]
        widgets = {"lat": forms.HiddenInput(), "lng": forms.HiddenInput()}

    def clean(self):
        data = super().clean()
        if data.get("lat") is not None and data.get("lng") is not None and data.get("pincode"):
            result = check_service_area(data["lat"], data["lng"], data["pincode"])
            if not result.ok:
                raise forms.ValidationError(result.message)
        return data


class OTPForm(StyledMixin, forms.Form):
    code = forms.CharField(
        label=_("6-digit code"),
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}),
    )
