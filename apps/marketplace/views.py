import csv
import secrets
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core import audit

from . import forms, services
from .access import fulfillments_for, is_admin, require_team, teams_for
from .models import (
    Head,
    LedgerEntry,
    MarketplaceSettings,
    Notice,
    RiderAccount,
    Seller,
    SellerTeam,
    Settlement,
    TerritoryPincode,
    TerritoryRequest,
)


def partner(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), "/accounts/login/")
        if not user.is_active or not (is_admin(user) or user.role in ("head", "seller")):
            raise PermissionDenied
        if user.role == "head" and not Head.objects.filter(user=user, active=True).exists():
            raise PermissionDenied
        if not user.is_verified():
            from django_otp.plugins.otp_totp.models import TOTPDevice

            target = "verify" if TOTPDevice.objects.filter(user=user, confirmed=True).exists() else "setup"
            return redirect(f"/accounts/2fa/{target}/?next={request.path}")
        response = view(request, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    return wrapped


@partner
def dashboard(request):
    teams = teams_for(request.user)
    orders = fulfillments_for(request.user).select_related("team__seller", "team__brand", "territory", "order")
    for field in ("state", "region"):
        if request.GET.get(field):
            orders = orders.filter(**{f"territory__{field}": request.GET[field]})
    if request.GET.get("area"):
        orders = orders.filter(territory__name=request.GET["area"])
    if request.GET.get("team"):
        orders = orders.filter(team_id=request.GET["team"]) if request.GET["team"].isdigit() else orders.none()
    delivered = orders.filter(status="delivered")
    stats = {
        "total": delivered.aggregate(n=Sum("total"))["n"] or 0,
        "cod": delivered.filter(order__payment_method="cod").aggregate(n=Sum("total"))["n"] or 0,
        "online": delivered.exclude(order__payment_method="cod").aggregate(n=Sum("total"))["n"] or 0,
        "delivered": delivered.count(),
        "cancelled": orders.filter(status="cancelled").count(),
        "discount": delivered.aggregate(n=Sum("discount"))["n"] or 0,
        "fees": delivered.aggregate(n=Sum("platform_fee"))["n"] or 0,
    }
    ledger = LedgerEntry.objects.filter(fulfillment__in=orders)
    collected = ledger.filter(kind="cod_collected").aggregate(n=Sum("amount"))["n"] or 0
    remitted = ledger.filter(kind="cod_remitted").aggregate(n=Sum("amount"))["n"] or 0
    stats["cash_due"] = collected - remitted
    stats["refunds"] = abs(ledger.filter(kind="refund").aggregate(n=Sum("amount"))["n"] or 0)
    stats["pending_payout"] = (
        Settlement.objects.filter(fulfillment__in=orders).exclude(status="settled").aggregate(n=Sum("amount"))["n"] or 0
    )
    stats["settled"] = (
        Settlement.objects.filter(fulfillment__in=orders, status="settled").aggregate(n=Sum("amount"))["n"] or 0
    )
    trends = (
        delivered.annotate(day=TruncDate("delivered_at"))
        .values("day")
        .annotate(revenue=Sum("total"), orders=Count("pk"))
        .order_by("-day")[:30]
    )
    stats["fulfillment_time"] = delivered.exclude(ready_at=None).aggregate(
        value=Avg(F("delivered_at") - F("ready_at"))
    )["value"]
    comparison = (
        orders.values("team__seller__name", "team__brand__name", "territory__state", "territory__region")
        .annotate(
            orders=Count("pk"),
            delivered=Count("pk", filter=Q(status="delivered")),
            revenue=Sum("total", filter=Q(status="delivered")),
        )
        .order_by("team__seller__name")
    )
    # A Head sees shared riders' availability only; never other-brand routes or activity history.
    riders = (
        RiderAccount.objects.filter(seller__teams__in=teams, active=True).select_related("user", "seller").distinct()
    )
    for r in riders:
        r.availability = (
            "online" if r.online and r.last_seen and (timezone.now() - r.last_seen).total_seconds() <= 90 else "offline"
        )
        if r.online and r.availability == "offline":
            r.availability = "stale"
    notices = Notice.objects.filter(seller__owner=request.user).order_by("-created_at")[:20]
    requests = TerritoryRequest.objects.filter(team__in=teams, status="pending").select_related("team", "territory")
    return render(
        request,
        "marketplace/dashboard.html",
        {
            "teams": teams,
            "orders": orders.order_by("-created_at")[:100],
            "stats": stats,
            "trends": trends,
            "comparison": comparison,
            "riders": riders,
            "notices": notices,
            "requests": requests,
            "admin": is_admin(request.user),
            "manager": is_admin(request.user) or request.user.role == "head",
            "heads": Head.objects.all() if is_admin(request.user) else [],
            "enabled": MarketplaceSettings.load().enabled,
            "owned_shops": Seller.objects.filter(owner=request.user),
        },
    )


@partner
def setup(request, kind):
    admin = is_admin(request.user)
    if kind in ("head", "area", "policy") and not admin:
        raise PermissionDenied
    if kind in ("team", "seller", "assignment", "campaign") and not (admin or request.user.role == "head"):
        raise PermissionDenied
    mapping = {
        "head": forms.HeadForm,
        "area": forms.TerritoryForm,
        "team": forms.TeamForm,
        "seller": forms.SellerForm,
        "assignment": forms.AssignmentForm,
        "request": forms.RequestForm,
        "campaign": forms.CampaignForm,
        "policy": forms.PolicyForm,
    }
    if kind not in mapping:
        raise PermissionDenied
    kwargs = {"data": request.POST or None}
    if kind == "team" and request.GET.get("id"):
        kwargs["instance"] = get_object_or_404(teams_for(request.user), pk=request.GET["id"])
    if kind == "head" and request.GET.get("id"):
        kwargs["instance"] = get_object_or_404(Head, pk=request.GET["id"])
    if kind == "policy":
        kwargs["instance"] = MarketplaceSettings.load()
    form = (
        mapping[kind](request.user, **kwargs)
        if kind in ("team", "seller", "assignment", "request", "campaign")
        else mapping[kind](**kwargs)
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                data = form.cleaned_data
                if kind == "assignment":
                    services.assign_territory(request.user, data["team"], data["territory"])
                elif kind == "seller":
                    user = get_user_model().objects.create_user(
                        email=data["email"].lower(), password=secrets.token_urlsafe(48), role="seller"
                    )
                    seller = Seller.objects.create(name=data["name"], owner=user, status="active")
                    SellerTeam.objects.create(seller=seller, brand=data["brand"], head=data["head"])
                    reset = PasswordResetForm({"email": user.email})
                    if reset.is_valid():
                        transaction.on_commit(
                            lambda: reset.save(
                                request=request,
                                use_https=request.is_secure(),
                                email_template_name="emails/password_reset.txt",
                                subject_template_name="emails/password_reset_subject.txt",
                            )
                        )
                    services.notice(
                        seller,
                        "Seller account created",
                        "Complete verification with Rasiko before taking orders. Set your password using the emailed link.",
                    )
                    audit.log(request, "marketplace.seller.created", seller)
                elif kind == "campaign":
                    coupon = form.save()
                    services.create_campaign(request.user, data["head"], coupon, data["teams"], data["territories"])
                else:
                    obj = form.save(commit=False)
                    if kind == "request":
                        require_team(request.user, obj.team)
                        obj.requested_by = request.user
                    if kind == "policy" and obj.payouts_enabled and not settings.MARKETPLACE_ROUTE_APPROVED:
                        raise ValidationError(
                            "Automatic payouts remain locked until provider sandbox reconciliation and refund recovery are verified."
                        )
                    obj.save()
                    if hasattr(form, "save_m2m"):
                        form.save_m2m()
                    if kind == "head":
                        obj.user.role = "head"
                        obj.user.save(update_fields=["role"])
                    if kind == "area":
                        TerritoryPincode.objects.bulk_create(
                            [TerritoryPincode(territory=obj, code=c) for c in data["codes"]]
                        )
                    audit.log(request, f"marketplace.{kind}.saved", obj)
            messages.success(request, _("Saved successfully."))
            return redirect("marketplace:dashboard")
        except (ValidationError, IntegrityError) as exc:
            form.add_error(
                None,
                " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else _("This conflicts with an existing record."),
            )
    return render(request, "marketplace/form.html", {"form": form, "kind": kind})


@partner
@require_POST
def action(request, kind, pk):
    reason = request.POST.get("reason", "").strip()
    try:
        if kind in ("online", "suspend", "activate", "verify"):
            team = get_object_or_404(teams_for(request.user), pk=pk)
            if kind == "online":
                services.set_online(request.user, team, request.POST.get("enabled") == "true")
            elif kind == "verify":
                if not is_admin(request.user):
                    raise PermissionDenied
                team.seller.verified = True
                team.seller.save(update_fields=["verified", "updated_at"])
                audit.log(request, "marketplace.seller.verified", team.seller)
            else:
                services.set_team_status(request.user, team, kind == "activate", reason)
        elif kind == "ready":
            from .dispatch import mark_ready

            f = get_object_or_404(fulfillments_for(request.user), pk=pk)
            mark_ready(request.user, f)
        elif kind == "cod":
            f = get_object_or_404(fulfillments_for(request.user), pk=pk)
            services.acknowledge_cod(request.user, f)
        elif kind == "decision":
            services.decide_territory(request.user, pk, request.POST.get("approve") == "true", reason)
        elif kind == "rider-invite":
            seller = get_object_or_404(Seller.objects.filter(teams__in=teams_for(request.user)).distinct(), pk=pk)
            email_form = forms.SellerForm.base_fields["email"]
            email = email_form.clean(request.POST.get("email"))
            invitation, token = services.invite_rider(request.user, seller, email)
            # Token is shown once to the authorized inviter, never stored in logs.
            return render(request, "marketplace/invitation.html", {"token": token, "invitation": invitation})
        elif kind == "rider-suspend":
            services.suspend_rider(request.user, get_object_or_404(RiderAccount, pk=pk), reason)
        elif kind == "fee":
            effective = parse_datetime(request.POST.get("effective_at", ""))
            if effective is None:
                raise ValidationError("Enter an effective date and time.")
            if timezone.is_naive(effective):
                effective = timezone.make_aware(effective)
            services.schedule_fee(
                request.user,
                Decimal(request.POST.get("percent", "0")),
                request.POST.get("enabled") == "true",
                effective,
            )
        elif kind == "head-suspend":
            if not is_admin(request.user) or not reason:
                raise PermissionDenied
            head = get_object_or_404(Head, pk=pk)
            head.active, head.reason = False, reason[:300]
            head.save()
            audit.log(request, "marketplace.head.suspended", head, changes={"reason": reason[:300]})
        else:
            raise PermissionDenied
        messages.success(request, _("Saved successfully."))
    except (ValidationError, ValueError) as exc:
        messages.error(request, " ".join(exc.messages) if isinstance(exc, ValidationError) else _("Invalid request."))
    return redirect("marketplace:dashboard")


@partner
def export(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="rasiko-team-orders.csv"'
    writer = csv.writer(response)
    writer.writerow(["Order", "Seller", "Brand", "Status", "Total", "Discount", "Platform fee"])
    for f in fulfillments_for(request.user).select_related("team__seller", "team__brand", "order").iterator():

        def cell(value):
            text = str(value)
            return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text

        writer.writerow(
            [
                cell(v)
                for v in (
                    f.order.number,
                    f.team.seller.name,
                    f.team.brand.name,
                    f.status,
                    f.total,
                    f.discount,
                    f.platform_fee,
                )
            ]
        )
    return response


@partner
def products(request):
    from apps.catalog.models import Product

    rows = (
        Product.objects.filter(seller_team__in=teams_for(request.user))
        .select_related("seller_team__seller", "seller_team__brand")
        .prefetch_related("variants")
    )
    return render(request, "marketplace/products.html", {"products": rows})


@partner
def product_edit(request, pk=None):
    from apps.catalog.models import Product

    instance = get_object_or_404(Product, pk=pk, seller_team__in=teams_for(request.user)) if pk else None
    original_team_id = instance.seller_team_id if instance else None
    form = forms.ProductForm(request.user, request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            product = form.save(commit=False)
            if instance and original_team_id != form.cleaned_data["seller_team"].pk:
                raise PermissionDenied("Create a separate product for another team.")
            product.brand = form.cleaned_data["seller_team"].brand
            product.save()
            form.save_m2m()
            audit.log(request, "marketplace.product.saved", product)
        return redirect("marketplace:products")
    return render(request, "marketplace/form.html", {"form": form, "kind": _("Product")})


@partner
def variant_edit(request, product_id, pk=None):
    from apps.catalog.models import Product, ProductVariant

    product = get_object_or_404(Product, pk=product_id, seller_team__in=teams_for(request.user))
    instance = get_object_or_404(ProductVariant, product=product, pk=pk) if pk else None
    form = forms.VariantForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.product = product
        obj.save()
        audit.log(request, "marketplace.variant.saved", obj)
        return redirect("marketplace:products")
    return render(request, "marketplace/form.html", {"form": form, "kind": _("Box variant")})


@partner
@require_POST
def adjust_stock(request, pk):
    from apps.catalog.models import ProductVariant
    from apps.inventory.services import OutOfStock, adjust_stock

    variant = get_object_or_404(ProductVariant, pk=pk, product__seller_team__in=teams_for(request.user))
    try:
        if variant.batch_tracking:
            raise ValidationError("Use batch receipt or quarantine for tracked stock.")
        delta = int(request.POST.get("delta", ""))
        reason = request.POST.get("reason", "").strip()
        if not reason or not delta:
            raise ValueError
        adjust_stock(variant.pk, delta, "manual", user=request.user, note=reason[:300])
        messages.success(request, _("Saved successfully."))
    except (ValueError, ValidationError, OutOfStock):
        messages.error(request, _("Enter a valid stock adjustment and reason."))
    return redirect("marketplace:products")


@partner
def verify_seller(request, pk):
    if not is_admin(request.user):
        raise PermissionDenied
    seller = get_object_or_404(Seller, pk=pk)
    form = forms.SellerVerificationForm(request.POST or None, instance=seller)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.log(request, "marketplace.seller.onboarding", seller)
        return redirect("marketplace:dashboard")
    return render(request, "marketplace/form.html", {"form": form, "kind": _("Seller verification and linked account")})


@partner
def translation_edit(request, pk, language):
    from apps.catalog.models import Product

    from .models import ProductTranslation
    from .translations import FIELDS, source_hash

    if language not in ("en", "hi", "gu"):
        raise PermissionDenied
    product = get_object_or_404(Product, pk=pk, seller_team__in=teams_for(request.user))
    row = ProductTranslation.objects.filter(product=product, language=language).first()
    initial = {**(row.content if row else {}), "source_hash": source_hash(product)}
    form = forms.TranslationForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["source_hash"] != source_hash(product):
            form.add_error(None, _("Product content changed. Reload and review the latest version."))
        else:
            row, created = ProductTranslation.objects.update_or_create(
                product=product,
                language=language,
                defaults={
                    "source_hash": source_hash(product),
                    "content": {field: form.cleaned_data[field] for field in FIELDS},
                    "status": "ready",
                    "corrected": True,
                },
            )
            audit.log(request, "marketplace.translation.reviewed", row)
            return redirect("marketplace:products")
    return render(request, "marketplace/form.html", {"form": form, "kind": f"{product.name} · {language}"})


@partner
def import_catalog(request):
    from .importing import import_products

    form = forms.ImportForm(request.user, request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            import_products(request.user, form.cleaned_data["team"], form.cleaned_data["file"])
            messages.success(request, _("Saved successfully."))
            return redirect("marketplace:products")
        except (ValidationError, IntegrityError) as exc:
            form.add_error(
                None,
                " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else _("This conflicts with an existing record."),
            )
    return render(request, "marketplace/form.html", {"form": form, "kind": _("Import new products from CSV")})


@login_required
def apply_seller(request):
    if request.user.role not in ("customer", "seller") or Seller.objects.filter(owner=request.user).exists():
        return redirect("marketplace:dashboard")
    form = forms.SellerApplicationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if Seller.objects.filter(owner=request.user).exists():
                return redirect("marketplace:dashboard")
            seller = Seller.objects.create(name=form.cleaned_data["name"], owner=request.user)
            for brand in form.cleaned_data["brand"]:
                team = SellerTeam.objects.create(seller=seller, brand=brand, active=False)
                TerritoryRequest.objects.bulk_create(
                    [
                        TerritoryRequest(
                            team=team, territory=area, requested_by=request.user, reason="Seller application"
                        )
                        for area in form.cleaned_data["territory"]
                    ]
                )
            request.user.role = "seller"
            request.user.save(update_fields=["role"])
            services.notice(
                seller,
                "Application received",
                "Admin approval and verification are required before your store can accept orders.",
            )
            audit.log(request, "marketplace.seller.applied", seller)
        return redirect("marketplace:shop", pk=seller.pk)
    return render(request, "marketplace/application.html", {"form": form})
