"""Seller-owned shop workspace; brand/territory approval remains an operator action."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.models import Product
from apps.core import audit

from .access import is_admin
from .extended_views import owned_seller
from .forms import ShopBrandRequestForm, ShopProfileForm
from .models import MarketplaceSettings, Seller, SellerTeam, TerritoryAssignment, TerritoryRequest
from .services import effective_policy
from .views import partner


def operational_teams(seller):
    """Mirror payment/fulfillment eligibility, including Head brand authority."""
    return [
        team
        for team in seller.teams.select_related("seller", "head__user", "brand").prefetch_related("head__brands")
        if team.brand.is_active and effective_policy(team)["operational"]
    ]


def service_assignments(teams):
    return TerritoryAssignment.objects.filter(team__in=teams, active=True, effective_at__lte=timezone.now()).filter(
        Q(team__head__isnull=True) | Q(territory__heads=F("team__head_id"))
    )


@partner
def workspace(request, pk):
    seller = owned_seller(request.user, pk)
    form = ShopProfileForm(request.POST or None, instance=seller)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.log(request, "marketplace.shop.updated", seller)
        messages.success(request, _("Shop details saved."))
        return redirect("marketplace:shop", pk=seller.pk)
    teams = seller.teams.select_related("brand", "head__user").prefetch_related("assignments__territory")
    assignments = service_assignments(operational_teams(seller))
    return render(
        request,
        "marketplace/shop.html",
        {
            "seller": seller,
            "form": form,
            "teams": teams,
            "product_count": Product.objects.filter(seller_team__seller=seller, deleted_at__isnull=True).count(),
            "rider_count": seller.riders.filter(active=True).count(),
            "area_count": assignments.values("territory_id").distinct().count(),
            "public_ready": seller.shop_published and assignments.exists() and MarketplaceSettings.load().enabled,
            "admin": is_admin(request.user),
        },
    )


@partner
def request_brand(request, pk):
    seller = owned_seller(request.user, pk)
    form = ShopBrandRequestForm(seller, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                seller = Seller.objects.select_for_update().get(pk=seller.pk)
                if seller.teams.filter(head__isnull=False, active=True).exists() and not seller.allow_multiple_brands:
                    raise ValidationError(_("Ask admin for multi-brand permission before requesting another brand."))
                team = SellerTeam.objects.create(seller=seller, brand=form.cleaned_data["brand"], active=False)
                TerritoryRequest.objects.bulk_create(
                    [
                        TerritoryRequest(
                            team=team,
                            territory=area,
                            requested_by=request.user,
                            reason="Shop brand and service-area request",
                        )
                        for area in form.cleaned_data["territories"]
                    ]
                )
                audit.log(request, "marketplace.shop.brand_requested", team)
            messages.success(request, _("Brand and service areas submitted for approval."))
            return redirect("marketplace:shop", pk=seller.pk)
        except (ValidationError, IntegrityError) as exc:
            form.add_error(
                None,
                " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else _("This brand is already linked to your shop."),
            )
    return render(
        request, "marketplace/form.html", {"form": form, "kind": _("Request another brand and service areas")}
    )


def public_shop(request, pk):
    if not MarketplaceSettings.load().enabled:
        from django.http import Http404

        raise Http404
    seller = get_object_or_404(
        Seller, pk=pk, status="active", verified=True, shop_published=True, owner__is_active=True
    )
    assignments = service_assignments(operational_teams(seller)).select_related("territory", "team__brand").distinct()
    if not assignments.exists():
        from django.http import Http404

        raise Http404
    products = (
        Product.objects.live()
        .filter(seller_team_id__in=assignments.values("team_id"))
        .select_related("brand")
        .prefetch_related("images", "variants")
        .order_by("name", "pk")
    )
    page = Paginator(products, 24).get_page(request.GET.get("page"))
    # Expose only intentionally public shop fields, never Seller's bank/legal data.
    response = render(
        request,
        "marketplace/public_shop.html",
        {
            "seller_shop_context": True,
            "shop_name": seller.name,
            "shop_description": seller.shop_description,
            "assignments": assignments,
            "page_obj": page,
        },
    )
    response["Cache-Control"] = "no-store"
    return response
