import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.accounts.models import Address, OneTimeCode
from apps.analytics.tracking import track
from apps.cart.cart import Cart
from apps.core.images import reencode
from apps.core.ratelimit import ratelimit
from apps.delivery.models import ServicePincode
from apps.delivery.services import available_slots, check_service_area, eta_text, quote
from apps.notifications import services as notify

from . import services
from .forms import BulkQuoteForm, SubscriptionForm, ThanduForm, TrackForm
from .invoice import invoice_pdf
from .models import Order, Subscription, ThanduComplaint
from .pricing import price_cart


def _own_order(request, public_id):
    return get_object_or_404(Order.objects.select_related("user"), public_id=public_id, user=request.user)


@login_required
def checkout(request):
    cart = Cart(request)
    if not cart.lines():
        messages.info(request, _("Your cart is empty."))
        return redirect("cart:detail")
    addresses = list(request.user.addresses.all())
    if not addresses:
        messages.info(request, _("Add your delivery address to continue."))
        return redirect(f"{reverse('accounts:address_new')}?next={reverse('orders:checkout')}")
    addr_id = request.POST.get("address") or request.GET.get("address")
    address = next((a for a in addresses if str(a.public_id) == addr_id), addresses[0])
    coupon_code = request.session.get("coupon_code", "")
    use_coins = request.session.get("use_coins", False)
    totals = price_cart(cart, request.user, coupon_code, use_coins, (address.lat, address.lng, address.pincode))
    pin = ServicePincode.objects.filter(code=address.pincode).first()
    methods = services.payment_methods_for(request.user, totals.total, pin)
    slots = available_slots()
    if request.method == "POST":
        token = request.POST.get("checkout_token", "")
        if not token or token != request.session.get("checkout_token"):
            messages.error(request, _("Please review your order and try again."))
            return redirect("orders:checkout")
        try:
            order = services.place_order(
                user=request.user,
                cart=cart,
                address=address,
                payment_method=request.POST.get("payment_method", ""),
                checkout_token=token,
                slot=request.POST.get("slot", "asap"),
                coupon_code=coupon_code,
                use_coins=use_coins,
                note=request.POST.get("note", ""),
            )
        except services.CheckoutError as exc:
            messages.error(request, str(exc))
            return redirect(f"{reverse('orders:checkout')}?address={address.public_id}")
        request.session.pop("checkout_token", None)
        track(request, "order")
        cart.clear()
        if order.status == Order.Status.PENDING_PAYMENT:
            return redirect("payments:pay", public_id=order.public_id)
        return redirect("orders:success", public_id=order.public_id)
    request.session["checkout_token"] = request.session.get("checkout_token") or secrets.token_urlsafe(24)
    track(request, "checkout")
    return render(
        request,
        "orders/checkout.html",
        {
            "cart": cart,
            "totals": totals,
            "addresses": addresses,
            "address": address,
            "methods": methods,
            "slots": slots,
            "checkout_token": request.session["checkout_token"],
            "needs_phone": not request.user.phone_verified,
        },
    )


@login_required
def success(request, public_id):
    order = _own_order(request, public_id)
    return render(request, "orders/success.html", {"order": order, "eta": services.eta_for(order)})


@login_required
def detail(request, public_id):
    order = _own_order(request, public_id)
    from apps.reviews.models import Review

    reviewed = set(Review.objects.filter(order_line__order=order).values_list("order_line_id", flat=True))
    return render(
        request,
        "orders/detail.html",
        {
            "order": order,
            "eta": services.eta_for(order),
            "reviewed": reviewed,
            "thandu_form": ThanduForm() if order.status == Order.Status.DELIVERED else None,
            "complaint": ThanduComplaint.objects.filter(order=order).first(),
        },
    )


@login_required
def invoice(request, public_id):
    order = _own_order(request, public_id)
    if order.status in (Order.Status.PENDING_PAYMENT, Order.Status.PAYMENT_FAILED):
        raise Http404
    resp = HttpResponse(invoice_pdf(order), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="Rasiko-invoice-{order.number}.pdf"'
    return resp


@login_required
@require_POST
def cancel(request, public_id):
    order = _own_order(request, public_id)
    try:
        services.cancel_by_customer(order, request.POST.get("reason", "")[:200])
        messages.success(request, _("Your order is cancelled."))
    except (ValueError, Exception) as exc:  # noqa: BLE001
        messages.error(request, str(exc))
    return redirect(order.get_absolute_url())


@login_required
@require_POST
def reorder(request, public_id):
    order = _own_order(request, public_id)
    n = services.reorder_into_cart(order, Cart(request))
    if n:
        messages.success(request, _("Added %(n)s items from your last order.") % {"n": n})
    else:
        messages.error(request, _("Those items are out of stock right now."))
    return redirect("cart:detail")


@login_required
@require_POST
@ratelimit("thandu", limit=3, window=3600)
def thandu(request, public_id):
    order = _own_order(request, public_id)
    if order.status != Order.Status.DELIVERED or hasattr(order, "thandu_complaint"):
        messages.error(request, _("A complaint can be sent once for a delivered order."))
        return redirect(order.get_absolute_url())
    form = ThanduForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            photo = reencode(form.cleaned_data["photo"], max_side=1400)
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
            return redirect(order.get_absolute_url())
        c = ThanduComplaint(order=order, note=form.cleaned_data["note"])
        c.photo.save(photo.name, photo, save=False)
        c.save()
        notify.admin_event("thandu_complaint", {"order": order.number, "note": c.note})
        messages.success(request, _("Sorry about that! We'll review your photo and send a coupon."))
    else:
        messages.error(request, _("Please attach a photo."))
    return redirect(order.get_absolute_url())


@ratelimit("track", limit=8, window=600)
def track_order(request):
    """Guests: order number + registered phone or email, then a one-time code."""
    form = TrackForm(request.POST or None)
    order = None
    verified = request.session.get("tracked_orders", [])
    if request.GET.get("o"):
        order = Order.objects.filter(public_id=request.GET["o"]).first()
        if order and not (order.pk in verified or (request.user.is_authenticated and order.user_id == request.user.pk)):
            order = None
    if request.method == "POST" and form.is_valid():
        number = form.cleaned_data["number"].strip().upper()
        contact = form.cleaned_data["contact"].strip().lower()
        o = Order.objects.filter(number=number).select_related("user").first()
        digits = "".join(c for c in contact if c.isdigit())[-10:]
        matches = o and (contact == o.user.email or (digits and digits in (o.ship_phone, o.user.phone)))
        step = request.POST.get("step", "send")
        if step == "send":
            if matches:
                code = OneTimeCode.issue(OneTimeCode.Purpose.TRACK_ORDER, f"order:{o.pk}")
                notify.customer_email(o.user.email, "otp", {"user": o.user, "code": code})
            # Same message either way, so order numbers can't be probed.
            messages.info(
                request, _("If the details match an order, we emailed a 6-digit code to the registered email.")
            )
            return render(request, "orders/track.html", {"form": form, "ask_code": True})
        if matches and OneTimeCode.verify(OneTimeCode.Purpose.TRACK_ORDER, f"order:{o.pk}", request.POST.get("code")):
            request.session["tracked_orders"] = [*verified, o.pk][-10:]
            return redirect(f"{reverse('orders:track')}?o={o.public_id}")
        messages.error(request, _("That code is not right or has expired."))
        return render(request, "orders/track.html", {"form": form, "ask_code": True})
    return render(
        request, "orders/track.html", {"form": form, "order": order, "eta": services.eta_for(order) if order else None}
    )


@ratelimit("bulk", limit=5, window=3600)
def bulk_quote(request):
    form = BulkQuoteForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        q = form.save(commit=False)
        q.user = request.user if request.user.is_authenticated else None
        q.save()
        notify.admin_event(
            "bulk_quote",
            {
                "name": q.name,
                "phone": q.phone,
                "kind": q.get_kind_display(),
                "date": str(q.event_date),
                "needs": q.requirements[:300],
            },
        )
        notify.customer_email(q.email, "bulk_quote_received", {"quote": q})
        messages.success(request, _("Thank you! Our team will call you with a quote shortly."))
        return redirect("orders:bulk")
    from apps.promotions.models import BulkPriceSlab

    slabs = BulkPriceSlab.objects.select_related("variant__product").order_by("variant__product__name", "min_qty")[:30]
    return render(request, "orders/bulk.html", {"form": form, "slabs": slabs})


@login_required
def subscriptions(request):
    subs = (
        Subscription.objects.filter(user=request.user)
        .exclude(state=Subscription.State.CANCELLED)
        .select_related("variant__product", "address")
    )
    form = SubscriptionForm(request.POST or None, user=request.user, initial={"variant": request.GET.get("variant")})
    if request.method == "POST" and form.is_valid():
        from .subscriptions import first_run

        sub = form.save(commit=False)
        sub.user = request.user
        sub.next_run = first_run(sub.frequency, sub.weekday)
        sub.save()
        messages.success(request, _("Subscription started. First delivery on %(d)s.") % {"d": sub.next_run})
        return redirect("orders:subscriptions")
    return render(request, "orders/subscriptions.html", {"subs": subs, "form": form})


@login_required
@require_POST
def subscription_action(request, public_id):
    sub = get_object_or_404(Subscription, public_id=public_id, user=request.user)
    action = request.POST.get("action")
    if action == "pause":
        sub.state = Subscription.State.PAUSED
    elif action == "resume":
        sub.state = Subscription.State.ACTIVE
    elif action == "cancel":
        sub.state = Subscription.State.CANCELLED
    elif action == "skip":
        sub.skip_dates = sorted({*sub.skip_dates, sub.next_run.isoformat()})
    sub.save()
    messages.success(request, _("Subscription updated."))
    return redirect("orders:subscriptions")


@require_POST
@ratelimit("quote", limit=30, window=60)
def delivery_quote(request):
    """Live fee preview while the customer moves the pin. The order itself is re-checked on the server."""
    lat, lng, pincode = request.POST.get("lat"), request.POST.get("lng"), request.POST.get("pincode", "")
    area = check_service_area(lat, lng, pincode)
    if not area.ok:
        return JsonResponse({"ok": False, "message": area.message})
    cart = Cart(request)
    q = quote(cart.subtotal, lat, lng, pincode)
    return JsonResponse(
        {
            "ok": q.ok,
            "message": q.message,
            "km": str(q.road_km),
            "fee": str(q.total),
            "free": str(q.free_reason),
            "eta": eta_text(area.fast),
        }
    )


@login_required
def address_for_checkout(request, public_id):
    get_object_or_404(Address, public_id=public_id, user=request.user)
    return redirect(f"{reverse('orders:checkout')}?address={public_id}")
