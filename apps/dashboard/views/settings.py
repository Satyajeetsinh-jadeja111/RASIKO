from django import forms
from django.conf import settings as dj_settings
from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.core import audit, crypto
from apps.core.integrations import REGISTRY, clear_cache, run_test
from apps.core.models import AuditLog, Integration, StoreSettings
from apps.core.ratelimit import hit
from apps.delivery.models import DeliverySettings, FeeSlab, Holiday, Rider, ServicePincode, StoreHours
from apps.notifications import services as notify
from apps.notifications.models import ADMIN_EVENTS, CUSTOMER_EVENTS, EmailLog, NotificationSettings

from ..permissions import dash
from .catalog import _style

DT = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


def _changed(form):
    return {k: str(form.cleaned_data.get(k))[:80] for k in form.changed_data}


# ---- Store ------------------------------------------------------------------------------------------------------


class StoreForm(forms.ModelForm):
    class Meta:
        model = StoreSettings
        exclude = ["id"]  # noqa: DJ006 - every setting is editable here
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
            "launch_at": DT,
            "meta_description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _style(self)


@dash("owner")
def store_settings(request):
    obj = StoreSettings.load()
    form = StoreForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        changes = _changed(form)
        form.save()
        cache.delete("org_jsonld")
        audit.log(request, "settings.store", obj, "Store settings changed", changes)
        notify.admin_event(
            "security_settings", {"by": request.user.email, "section": "Store", "fields": ", ".join(changes)}
        )
        messages.success(request, "Store settings saved.")
        return redirect("dashboard:store_settings")
    return render(request, "dashboard/store_settings.html", {"form": form})


# ---- Delivery ---------------------------------------------------------------------------------------------------


class DeliveryForm(forms.ModelForm):
    class Meta:
        model = DeliverySettings
        exclude = ["id", "polygon"]  # noqa: DJ006 - polygon is drawn on the map
        widgets = {
            "store_lat": forms.NumberInput(attrs={"step": "0.000001"}),
            "store_lng": forms.NumberInput(attrs={"step": "0.000001"}),
            "late_night_after": forms.TimeInput(attrs={"type": "time"}),
        }

    polygon_json = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        import json

        self.fields["polygon_json"].initial = json.dumps(self.instance.polygon or [])
        _style(self)

    def clean_polygon_json(self):
        import json

        raw = self.cleaned_data.get("polygon_json") or "[]"
        try:
            pts = json.loads(raw)
            pts = [[round(float(a), 6), round(float(b), 6)] for a, b in pts][:200]
        except (ValueError, TypeError):
            raise forms.ValidationError("The drawn area could not be read. Draw it again.") from None
        if pts and len(pts) < 3:
            raise forms.ValidationError("An area needs at least 3 points.")
        return pts


HoursFormSet = forms.modelformset_factory(
    StoreHours,
    fields=["opens", "closes", "is_closed"],
    extra=0,
    widgets={
        "opens": forms.TimeInput(attrs={"type": "time", "class": "input"}),
        "closes": forms.TimeInput(attrs={"type": "time", "class": "input"}),
    },
)


@dash("manager")
def delivery_settings(request):
    cfg = DeliverySettings.load()
    for d in range(7):
        StoreHours.objects.get_or_create(weekday=d)
    form = DeliveryForm(request.POST or None, instance=cfg)
    hours = HoursFormSet(request.POST or None, queryset=StoreHours.objects.order_by("weekday"), prefix="h")
    if request.method == "POST" and form.is_valid() and hours.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.polygon = form.cleaned_data["polygon_json"]
            obj.save()
            hours.save()
        cache.delete("org_jsonld")
        audit.log(request, "settings.delivery", obj, "Delivery settings changed", _changed(form))
        messages.success(request, "Delivery settings saved.")
        return redirect("dashboard:delivery_settings")
    return render(
        request,
        "dashboard/delivery_settings.html",
        {
            "form": form,
            "hours": hours,
            "slabs": FeeSlab.objects.order_by("min_km"),
            "pincodes": ServicePincode.objects.order_by("code"),
            "holidays": Holiday.objects.order_by("date"),
            "riders": Rider.objects.order_by("name"),
        },
    )


# ---- Integrations (Owner only) ---------------------------------------------------------------------------------


def _card(spec, row):
    cfg = row.config() if row else {}
    fields = []
    for f in spec.fields:
        value = cfg.get(f.name, "")
        fields.append(
            {
                "name": f.name,
                "label": f.label,
                "secret": f.secret,
                "required": f.required,
                "help": f.help,
                "choices": f.choices,
                "value": "" if f.secret else (value or f.default),
                "is_set": bool(value),
                "masked": crypto.mask(value) if f.secret else "",
            }
        )
    return {
        "spec": spec,
        "row": row,
        "fields": fields,
        "enabled": bool(row and row.enabled),
        "missing": row.missing_required() if row else [f.label for f in spec.fields if f.required],
    }


@dash("owner")
def integrations(request):
    rows = {r.slug: r for r in Integration.objects.all()}
    cards = [_card(spec, rows.get(slug)) for slug, spec in REGISTRY.items()]
    return render(
        request,
        "dashboard/integrations.html",
        {"cards": cards, "site_url": dj_settings.SITE_URL, "store": StoreSettings.load()},
    )


@dash("owner")
@require_POST
def integration_save(request, slug):
    spec = REGISTRY.get(slug)
    if spec is None:
        return redirect("dashboard:integrations")
    if hit(f"integration:{request.user.pk}", 30, 600):
        messages.error(request, "Too many changes in a short time. Please wait a few minutes.")
        return redirect("dashboard:integrations")
    row, _ = Integration.objects.get_or_create(slug=slug)
    action = request.POST.get("action", "save")
    if action == "clear":
        row.data_encrypted, row.enabled, row.last_test_ok, row.last_test_message = "", False, None, ""
        row.updated_by = request.user
        row.save()
        clear_cache(slug)
        audit.log(request, "integration.clear", row, f"{spec.name}: saved keys removed and switched off")
        notify.admin_event(
            "security_settings", {"by": request.user.email, "integration": spec.name, "change": "keys removed"}
        )
        messages.success(request, f"{spec.name}: keys removed and switched off.")
        return redirect(f"/{dj_settings.ADMIN_URL}settings/integrations/#{slug}")

    values = {f.name: request.POST.get(f.name, "")[:500] for f in spec.fields}
    for f in spec.fields:
        if f.choices and values[f.name] and values[f.name] not in f.choices:
            values[f.name] = f.default
    changed = row.update_values(values)
    want_on = request.POST.get("enabled") == "on"
    missing = row.missing_required()
    if want_on and missing:
        want_on = False
        messages.error(request, f"{spec.name} stays off until these are filled: {', '.join(missing)}.")
    toggled = want_on != row.enabled
    row.enabled = want_on
    row.updated_by = request.user
    if changed:
        row.last_test_ok, row.last_test_message = None, ""
    row.save()
    clear_cache(slug)
    if slug == "s3":
        from apps.core.storage import reset_storage

        reset_storage()
    # Only field names are logged, never values.
    audit.log(
        request,
        "integration.update",
        row,
        f"{spec.name}: {'on' if row.enabled else 'off'}",
        {"fields_changed": changed, "enabled": row.enabled},
    )
    if changed or toggled:
        notify.admin_event(
            "security_settings",
            {
                "by": request.user.email,
                "integration": spec.name,
                "switched": "on" if row.enabled else "off",
                "fields_changed": ", ".join(changed) or "none",
                "ip": audit.client_ip(request),
            },
        )
    if action == "test":
        if missing:
            messages.error(request, "Fill the required fields before testing.")
        else:
            ok, msg = run_test(slug, row.config())
            row.last_test_ok, row.last_test_message = ok, msg[:300]
            row.save(update_fields=["last_test_ok", "last_test_message", "updated_at"])
            (messages.success if ok else messages.error)(request, f"{spec.name}: {msg}")
    elif not (want_on is False and request.POST.get("enabled") == "on"):
        messages.success(request, f"{spec.name} saved{' and switched on' if row.enabled else ''}.")
    return redirect(f"/{dj_settings.ADMIN_URL}settings/integrations/#{slug}")


# ---- Emails -----------------------------------------------------------------------------------------------------


@dash("manager")
def email_settings(request):
    ns = NotificationSettings.load()
    if request.method == "POST":
        if request.POST.get("action") == "test":
            to = request.POST.get("test_to", "").strip() or request.user.email
            if hit(f"testmail:{request.user.pk}", 5, 600):
                messages.error(request, "Please wait a few minutes before sending more test emails.")
            elif "@" not in to:
                messages.error(request, "Enter a valid email address.")
            else:
                notify.send_email(to, "test", {})
                messages.success(request, f"Test email queued for {to}. Check the log below in a minute.")
            return redirect("dashboard:email_settings")
        emails = [e.strip() for e in request.POST.get("admin_recipients", "").replace(",", "\n").splitlines()]
        bad = [e for e in emails if e and ("@" not in e or " " in e)]
        if bad:
            messages.error(request, "These don't look like email addresses: " + ", ".join(bad[:5]))
            return redirect("dashboard:email_settings")
        ns.admin_recipients = "\n".join(e for e in emails if e)[:2000]
        ns.toggles = {
            **{k: f"t_{k}" in request.POST for k in ADMIN_EVENTS},
            **{f"c:{k}": f"t_c:{k}" in request.POST for k in CUSTOMER_EVENTS},
        }
        ns.save()
        audit.log(request, "settings.emails", ns, "Email notification settings changed")
        messages.success(request, "Email settings saved.")
        return redirect("dashboard:email_settings")
    logs = EmailLog.objects.order_by("-created_at")
    status = request.GET.get("status")
    if status:
        logs = logs.filter(status=status)
    from apps.core.integrations import is_enabled

    return render(
        request,
        "dashboard/email_settings.html",
        {
            "ns": ns,
            "admin_events": [(k, v, ns.is_on(k)) for k, v in ADMIN_EVENTS.items()],
            "customer_events": [(k, v, ns.is_on(f"c:{k}")) for k, v in CUSTOMER_EVENTS.items()],
            "page": Paginator(logs, 30).get_page(request.GET.get("page")),
            "smtp_on": is_enabled("smtp"),
            "statuses": EmailLog.Status.choices,
        },
    )


# ---- Staff (Owner only) ----------------------------------------------------------------------------------------


class StaffForm(forms.Form):
    email = forms.EmailField()
    first_name = forms.CharField(max_length=60, label="Name")
    role = forms.ChoiceField(choices=[("staff", "Staff"), ("manager", "Manager"), ("owner", "Owner")])
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="At least 12 characters. They can change it later.",
    )

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _style(self)

    def clean_password(self):
        from django.contrib.auth import password_validation

        pw = self.cleaned_data["password"]
        if len(pw) < 12:
            raise forms.ValidationError("Use at least 12 characters for staff accounts.")
        password_validation.validate_password(pw)
        return pw


@dash("owner")
def staff(request):
    form = StaffForm(request.POST or None)
    if request.method == "POST" and request.POST.get("action") == "create" and form.is_valid():
        d = form.cleaned_data
        user = User.objects.filter(email__iexact=d["email"]).first()
        if user is None:
            user = User.objects.create_user(
                email=d["email"].lower(), password=d["password"], first_name=d["first_name"]
            )
        else:
            user.set_password(d["password"])
        user.role = d["role"]
        user.is_active = True
        user.save()
        audit.log(request, "staff.create", user, f"{user.email} is now {user.get_role_display()}")
        notify.admin_event("security_settings", {"by": request.user.email, "staff": user.email, "role": d["role"]})
        messages.success(request, f"{user.email} can now sign in to the dashboard.")
        return redirect("dashboard:staff")
    if request.method == "POST" and request.POST.get("action") in ("role", "deactivate", "reset_2fa"):
        user = get_object_or_404(User, pk=request.POST.get("id"))
        if user == request.user:
            messages.error(request, "You can't change your own access here.")
            return redirect("dashboard:staff")
        act = request.POST["action"]
        if act == "role" and request.POST.get("role") in ("customer", "staff", "manager", "owner"):
            user.role = request.POST["role"]
            user.save()
            summary = f"{user.email} role → {user.role}"
        elif act == "deactivate":
            user.role = "customer"
            user.save()
            summary = f"{user.email} removed from the dashboard"
        else:
            from django_otp.plugins.otp_totp.models import TOTPDevice

            TOTPDevice.objects.filter(user=user).delete()
            summary = f"{user.email} two-factor reset"
        audit.log(request, f"staff.{act}", user, summary)
        notify.admin_event("security_settings", {"by": request.user.email, "change": summary})
        messages.success(request, summary)
        return redirect("dashboard:staff")
    people = User.objects.filter(Q(role__in=["staff", "manager", "owner"]) | Q(is_superuser=True)).order_by("role")
    return render(request, "dashboard/staff.html", {"people": people, "form": form})


@dash("owner")
def audit_log(request):
    qs = AuditLog.objects.select_related("user").order_by("-created_at")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(action__icontains=q) | Q(summary__icontains=q) | Q(user__email__icontains=q))
    return render(
        request, "dashboard/audit.html", {"page": Paginator(qs, 50).get_page(request.GET.get("page")), "q": q}
    )
