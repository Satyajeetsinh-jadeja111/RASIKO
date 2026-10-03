import base64
import io

import qrcode
import qrcode.image.svg
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core import audit
from apps.core.ratelimit import ratelimit
from apps.notifications import services as notify

from .forms import AddressForm, LoginForm, OTPForm, ProfileForm, SignupForm
from .models import Address, OneTimeCode, User
from .sms import send_sms

VERIFY_SALT = "rasiko.email-verify"


def _safe_next(request, default):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}, require_https=request.is_secure()):
        return nxt
    return default


@ratelimit("login", limit=10, window=60)
def login_view(request):
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(request, username=form.cleaned_data["username"], password=form.cleaned_data["password"])
        if user is not None:
            login(request, user, backend="apps.accounts.backends.EmailBackend")
            request.session.cycle_key()
            if user.is_dashboard_user:
                audit.log(request, "staff.login", user, f"{user.email} signed in")
                notify.admin_event("security_login", {"user": user.email, "ip": audit.client_ip(request)})
                if user.requires_2fa:
                    has_device = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
                    return redirect("accounts:2fa_verify" if has_device else "accounts:2fa_setup")
            return redirect(_safe_next(request, reverse("storefront:home")))
        audit.log(request, "login.failed", summary=f"Failed login for {form.cleaned_data['username'][:80]}")
        notify.failed_login(form.cleaned_data["username"], audit.client_ip(request))
        messages.error(request, _("Email or password is incorrect."))
    return render(request, "accounts/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("storefront:home")


@ratelimit("signup", limit=5, window=300)
def signup_view(request):
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="apps.accounts.backends.EmailBackend")
        token = signing.dumps(user.pk, salt=VERIFY_SALT)
        verify_url = settings.SITE_URL + reverse("accounts:verify_email", args=[token])
        notify.customer_email(user.email, "welcome", {"user": user, "verify_url": verify_url})
        messages.success(request, _("Welcome to Rasiko! Please check your email to verify your address."))
        return redirect(_safe_next(request, reverse("storefront:home")))
    return render(request, "accounts/signup.html", {"form": form})


def verify_email(request, token):
    try:
        pk = signing.loads(token, salt=VERIFY_SALT, max_age=60 * 60 * 24 * 3)
    except signing.BadSignature:
        messages.error(request, _("This verification link is invalid or has expired."))
        return redirect("storefront:home")
    User.objects.filter(pk=pk).update(email_verified=True)
    messages.success(request, _("Your email is verified. Thank you!"))
    return redirect("storefront:home")


@login_required
def account_home(request):
    from apps.orders.models import Order
    from apps.promotions.models import coin_balance

    orders = Order.objects.filter(user=request.user).order_by("-placed_at")[:20]
    return render(
        request,
        "accounts/account.html",
        {"orders": orders, "coins": coin_balance(request.user), "addresses": request.user.addresses.all()},
    )


@login_required
def profile_edit(request):
    old_phone = request.user.phone
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        if user.phone != old_phone:
            user.phone_verified = False
        user.save()
        messages.success(request, _("Profile saved."))
        return redirect("accounts:home")
    return render(request, "accounts/profile.html", {"form": form})


@login_required
def address_edit(request, public_id=None):
    address = get_object_or_404(Address, public_id=public_id, user=request.user) if public_id else None
    form = AddressForm(request.POST or None, instance=address)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.user = request.user
        obj.save()
        if obj.is_default:
            request.user.addresses.exclude(pk=obj.pk).update(is_default=False)
        messages.success(request, _("Address saved."))
        return redirect(_safe_next(request, reverse("accounts:home")))
    return render(request, "accounts/address_form.html", {"form": form, "address": address})


@login_required
@require_POST
def address_delete(request, public_id):
    get_object_or_404(Address, public_id=public_id, user=request.user).delete()
    messages.success(request, _("Address removed."))
    return redirect("accounts:home")


@login_required
@ratelimit("otp", limit=5, window=600)
def phone_verify(request):
    """Verify the mobile number before a first Cash on Delivery order (SMS if configured, else email)."""
    user = request.user
    if not user.phone:
        messages.info(request, _("Add your mobile number first."))
        return redirect("accounts:profile")
    target = user.phone
    form = OTPForm(request.POST or None)
    if request.method == "POST" and request.POST.get("action") == "send":
        code = OneTimeCode.issue(OneTimeCode.Purpose.PHONE_VERIFY, target)
        if send_sms(user.phone, f"Your Rasiko verification code is {code}", otp=code):
            messages.success(request, _("We sent a code by SMS to your mobile."))
        else:
            notify.customer_email(user.email, "otp", {"user": user, "code": code})
            messages.success(request, _("We emailed you a 6-digit code."))
        return redirect(request.path + "?" + request.GET.urlencode())
    if request.method == "POST" and form.is_valid():
        if OneTimeCode.verify(OneTimeCode.Purpose.PHONE_VERIFY, target, form.cleaned_data["code"]):
            user.phone_verified = True
            user.save(update_fields=["phone_verified"])
            messages.success(request, _("Mobile number verified."))
            return redirect(_safe_next(request, reverse("accounts:home")))
        messages.error(request, _("That code is not right or has expired."))
    return render(request, "accounts/phone_verify.html", {"form": form})


# ---- Two-factor authentication (TOTP) for Owner / Manager ----------------------


@login_required
def twofa_setup(request):
    user = request.user
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first() or TOTPDevice.objects.create(
        user=user, name="Authenticator app", confirmed=False
    )
    form = OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if device.verify_token(form.cleaned_data["code"]):
            device.confirmed = True
            device.save()
            TOTPDevice.objects.filter(user=user).exclude(pk=device.pk).delete()
            otp_login(request, device)
            audit.log(request, "staff.2fa_enabled", user, "2FA enabled")
            messages.success(request, _("Two-factor authentication is on."))
            return redirect("dashboard:home")
        messages.error(request, _("That code did not match. Try the newest code in your app."))
    img = qrcode.make(device.config_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    qr_data = "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()
    secret = base64.b32encode(bytes.fromhex(device.key)).decode()
    return render(request, "accounts/2fa_setup.html", {"form": form, "qr": qr_data, "secret": secret})


@login_required
@ratelimit("2fa", limit=8, window=300)
def twofa_verify(request):
    form = OTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        for device in TOTPDevice.objects.filter(user=request.user, confirmed=True):
            if device.verify_token(form.cleaned_data["code"]):
                otp_login(request, device)
                return redirect(_safe_next(request, reverse("dashboard:home")))
        audit.log(request, "staff.2fa_failed", request.user, "Wrong 2FA code")
        messages.error(request, _("That code did not match."))
    return render(request, "accounts/2fa_verify.html", {"form": form})
