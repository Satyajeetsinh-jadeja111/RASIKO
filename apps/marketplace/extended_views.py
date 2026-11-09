from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.catalog.models import ProductVariant
from apps.core import audit
from apps.core.crypto import encrypt_json

from . import forms
from .access import fulfillments_for, is_admin, teams_for
from .models import (
    CaseMessage,
    Fulfillment,
    MarketplaceOperations,
    OperationalAlert,
    Seller,
    SellerCase,
    StockBatch,
    TerritoryAssignment,
)
from .views import partner


def owned_seller(user, pk):
    return get_object_or_404(Seller.objects.all() if is_admin(user) else Seller.objects.filter(owner=user), pk=pk)


@partner
def business(request, pk):
    seller = owned_seller(request.user, pk)
    form = forms.BusinessForm(request.POST or None, instance=seller)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.log(request, "marketplace.seller.business_updated", seller)
        return redirect("marketplace:dashboard")
    return render(request, "marketplace/form.html", {"form": form, "kind": _("Business and invoice details")})


@partner
def batch_receive(request, pk):
    from .batches import receive

    variant = get_object_or_404(ProductVariant, pk=pk, product__seller_team__in=teams_for(request.user))
    form = forms.BatchForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            d = form.cleaned_data
            receive(request.user, variant, d["code"], d["expires_on"], d["quantity"], opening=d["opening"])
            return redirect("marketplace:products")
        except (ValidationError, IntegrityError) as exc:
            form.add_error(
                None, " ".join(exc.messages) if isinstance(exc, ValidationError) else _("Batch code already exists.")
            )
    return render(request, "marketplace/form.html", {"form": form, "kind": _("Receive expiry-tracked stock")})


@partner
@require_POST
def operate(request, action, pk):
    reason = request.POST.get("reason", "").strip()
    try:
        if action in ("reset-code", "release", "cancel"):
            from .operations import cancel_fulfillment, release_delivery, reset_delivery_code

            f = get_object_or_404(fulfillments_for(request.user), pk=pk)
            {"reset-code": reset_delivery_code, "release": release_delivery, "cancel": cancel_fulfillment}[action](
                request.user, f, reason
            )
        elif action == "remove-area":
            from .operations import remove_territory

            assignment = get_object_or_404(TerritoryAssignment, pk=pk, team__in=teams_for(request.user))
            remove_territory(request.user, assignment, reason)
        elif action == "quarantine":
            from .batches import quarantine

            batch = get_object_or_404(StockBatch, pk=pk, variant__product__seller_team__in=teams_for(request.user))
            quarantine(request.user, batch, reason)
        else:
            raise PermissionDenied
        messages.success(request, _("Saved successfully."))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("marketplace:dashboard")


@partner
@transaction.atomic
def onboard(request, pk):
    seller = owned_seller(request.user, pk)
    seller = Seller.objects.select_for_update().get(pk=seller.pk)
    form = forms.OnboardingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not seller.legal_name or not seller.business_phone:
            form.add_error(None, _("Complete business details before onboarding."))
        elif seller.onboarding_operations.exclude(status="pending").exists():
            form.add_error(None, _("An onboarding submission already exists. Use refresh or ask admin to recover it."))
        else:
            payload = form.cleaned_data.copy()
            payload.pop("accept_terms")
            payload["consented_at"] = timezone.now().isoformat()
            seller.onboarding_encrypted = encrypt_json(payload)
            seller.onboarding_status, seller.payments_ready = "queued", False
            seller.save(update_fields=["onboarding_encrypted", "onboarding_status", "payments_ready", "updated_at"])
            audit.log(request, "marketplace.onboarding.submitted", seller)
            from .tasks import onboard_seller

            transaction.on_commit(lambda: onboard_seller.delay(seller.pk))
            messages.success(
                request, _("Onboarding submitted. Provider verification may require additional documents.")
            )
            return redirect("marketplace:dashboard")
    return render(request, "marketplace/onboarding.html", {"form": form, "seller": seller})


@partner
@require_POST
def refresh_onboarding(request, pk):
    from .onboarding import refresh

    seller = owned_seller(request.user, pk)
    try:
        refresh(seller.pk)
        messages.success(request, _("Provider status refreshed."))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    except Exception:  # noqa: BLE001 - never expose provider credentials or banking details
        messages.error(request, _("Provider status could not be verified. Try again later."))
    return redirect("marketplace:dashboard")


@partner
def operations_settings(request):
    if not is_admin(request.user):
        raise PermissionDenied
    form = forms.OperationsForm(request.POST or None, instance=MarketplaceOperations.load())
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        audit.log(request, "marketplace.operations.updated", obj)
        return redirect("marketplace:dashboard")
    return render(
        request, "marketplace/form.html", {"form": form, "kind": _("Privacy, retention and grievance settings")}
    )


@partner
def alerts(request):
    qs = OperationalAlert.objects.filter(resolved_at=None)
    if not is_admin(request.user):
        qs = qs.filter(fulfillment__in=fulfillments_for(request.user))
    return render(request, "marketplace/alerts.html", {"alerts": qs.order_by("-updated_at")[:200]})


@partner
def cases(request):
    return render(
        request,
        "marketplace/cases.html",
        {
            "cases": SellerCase.objects.filter(fulfillment__in=fulfillments_for(request.user))
            .select_related("fulfillment__team")
            .order_by("-updated_at")[:100]
        },
    )


def can_case(user, fulfillment):
    return fulfillment.order.user_id == user.pk or (
        getattr(user, "is_verified", lambda: False)() and fulfillments_for(user).filter(pk=fulfillment.pk).exists()
    )


@login_required
def case_create(request, pk):
    f = get_object_or_404(Fulfillment.objects.select_related("order"), pk=pk)
    if not can_case(request.user, f):
        raise PermissionDenied
    form = forms.CaseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            case = SellerCase.objects.create(
                fulfillment=f, created_by=request.user, subject=form.cleaned_data["subject"]
            )
            CaseMessage.objects.create(case=case, author=request.user, text=form.cleaned_data["text"])
        return redirect("marketplace:case", pk=case.pk)
    return render(request, "marketplace/customer_form.html", {"form": form, "title": _("Contact seller support")})


@login_required
def case_detail(request, pk):
    case = get_object_or_404(SellerCase.objects.select_related("fulfillment__order"), pk=pk)
    if not can_case(request.user, case.fulfillment):
        raise PermissionDenied
    form = forms.MessageForm(request.POST or None, initial={"status": case.status})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            case = SellerCase.objects.select_for_update().get(pk=pk)
            CaseMessage.objects.create(case=case, author=request.user, text=form.cleaned_data["text"])
            case.status = form.cleaned_data["status"]
            case.save(update_fields=["status", "updated_at"])
        return redirect("marketplace:case", pk=case.pk)
    response = render(request, "marketplace/case.html", {"case": case, "form": form})
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def invoice(request, pk):
    from .invoices import pdf

    f = get_object_or_404(Fulfillment.objects.select_related("order"), pk=pk)
    if not can_case(request.user, f):
        raise PermissionDenied
    if f.order.payment_method != "cod" and f.order.payment_status not in ("paid", "partial_refund", "refunded"):
        return HttpResponse(_("Invoice is available after payment capture."), status=409)
    try:
        record = getattr(f, "invoice", None)
        if record is None:
            # Issuance is an explicit business action, never a side effect of a buyer download.
            return HttpResponse(_("The seller has not issued this invoice yet."), status=409)
        response = HttpResponse(pdf(record), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="invoice-{record.pk}.pdf"'
        response["Cache-Control"] = "private, no-store"
        return response
    except ValidationError as exc:
        return HttpResponse(" ".join(exc.messages), status=409)


@partner
@require_POST
def issue_invoice(request, pk):
    from .invoices import issue

    f = get_object_or_404(fulfillments_for(request.user), pk=pk)
    try:
        issue(f)
        messages.success(request, _("Invoice issued."))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("marketplace:dashboard")


def policies(request):
    return render(request, "marketplace/policies.html", {"operations": MarketplaceOperations.load()})


@partner
@require_POST
def recover_onboarding(request, pk):
    if not is_admin(request.user):
        raise PermissionDenied
    seller = owned_seller(request.user, pk)
    try:
        from .onboarding import recover

        recover(request.user, seller, request.POST.get("step", ""), request.POST.get("provider_id", "").strip())
        from .tasks import onboard_seller

        transaction.on_commit(lambda: onboard_seller.delay(seller.pk))
        messages.success(request, _("Provider reference verified; onboarding resumed."))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    except Exception:  # noqa: BLE001 - redact provider payload
        messages.error(request, _("Recovery could not be verified. Check the provider reference."))
    return redirect("marketplace:onboard", pk=pk)


@partner
@require_POST
def resume_onboarding(request, pk):
    seller = owned_seller(request.user, pk)
    from .tasks import onboard_seller

    transaction.on_commit(lambda: onboard_seller.delay(seller.pk))
    messages.success(request, _("Onboarding queued for reconciliation."))
    return redirect("marketplace:onboard", pk=pk)


@partner
def product_photo(request, pk):
    from apps.catalog.models import Product, ProductImage

    product = get_object_or_404(Product, pk=pk, seller_team__in=teams_for(request.user))
    form = forms.ProductPhotoForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        ProductImage.objects.create(product=product, image=form.cleaned_data["image"], alt=form.cleaned_data["alt"])
        audit.log(request, "marketplace.product.photo_added", product)
        return redirect("marketplace:products")
    return render(request, "marketplace/form.html", {"form": form, "kind": _("Product photo")})
