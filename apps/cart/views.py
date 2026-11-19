from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.analytics.tracking import track
from apps.catalog.models import ProductVariant
from apps.core.ratelimit import ratelimit
from apps.core.utils import safe_next
from apps.orders.pricing import price_cart
from apps.promotions.models import Combo

from .cart import Cart


def _wants_json(request):
    return request.headers.get("Accept", "").startswith("application/json")


def _summary(request, cart):
    return price_cart(
        cart, request.user, request.session.get("coupon_code", ""), request.session.get("use_coins", False)
    )


def detail(request):
    cart = Cart(request)
    return render(request, "cart/cart.html", {"cart": cart, "totals": _summary(request, cart)})


def drawer(request):
    cart = Cart(request)
    return render(request, "cart/_drawer.html", {"cart": cart, "totals": _summary(request, cart)})


@require_POST
def update(request):
    """Add or set a line. POST key=v:<id>|c:<id>, qty=<n>, mode=add|set."""
    cart = Cart(request)
    key = request.POST.get("key", "")
    try:
        qty = int(request.POST.get("qty", 1))
    except ValueError:
        qty = 1
    kind, _sep, pk = key.partition(":")
    if kind == "v":
        v = get_object_or_404(ProductVariant, pk=pk, is_active=True)
        limit = v.max_orderable
        if not v.in_stock and qty > 0 and request.POST.get("mode") != "set":
            return JsonResponse({"error": _("Sorry, this is out of stock.")}, status=409)
        name = f"{v.product.local_name} {v.box_label}"
    elif kind == "c":
        c = get_object_or_404(Combo, pk=pk, is_active=True)
        limit, name = 10, c.name
    else:
        return JsonResponse({"error": "bad item"}, status=400)
    if request.POST.get("mode") == "set":
        new_qty = qty
    else:
        new_qty = cart.qty_of(key) + qty
    capped = min(max(new_qty, 0), max(limit, 0))
    cart.set(key, capped)
    if qty > 0:
        track(request, "cart", v.product if kind == "v" else None)
    msg = _("%(name)s added to cart") % {"name": name} if qty > 0 else _("Cart updated")
    if new_qty > capped:
        msg = _("Only %(n)s available") % {"n": capped}
    if _wants_json(request):
        return JsonResponse(
            {"count": cart.count, "qty": cart.qty_of(key), "message": msg, "subtotal": str(cart.subtotal)}
        )
    if request.htmx:
        return drawer(request)
    return redirect(safe_next(request, "cart:detail"))


@require_POST
@ratelimit("coupon", limit=10, window=60)
def apply_coupon(request):
    code = request.POST.get("code", "").strip().upper()[:30]
    cart = Cart(request)
    if request.POST.get("remove"):
        request.session.pop("coupon_code", None)
    else:
        totals = price_cart(cart, request.user, code)
        if totals.coupon_error:
            messages.error(request, totals.coupon_error)
        elif totals.coupon:
            request.session["coupon_code"] = code
            messages.success(request, _("Coupon %(c)s applied: you save ₹%(d)s") % {"c": code, "d": totals.discount})
    return redirect(safe_next(request, "cart:detail"))


@require_POST
def toggle_coins(request):
    request.session["use_coins"] = request.POST.get("use") == "1"
    return redirect(safe_next(request, "cart:detail"))
