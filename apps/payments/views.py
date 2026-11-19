import json
import logging

import razorpay
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.orders.models import Order
from apps.orders.services import mark_payment_failed

from . import services
from .gateways import GatewayError

logger = logging.getLogger(__name__)


def _checkout_page(request, context):
    response = render(request, "payments/pay.html", context)
    # Payment/bank popups need to retain their opener reference during authentication.
    response["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    return response


@login_required
def pay(request, public_id):
    order = get_object_or_404(Order, public_id=public_id, user=request.user)
    if order.status != Order.Status.PENDING_PAYMENT:
        return redirect(order.get_absolute_url())
    if order.payment_method == "razorpay":
        return _checkout_page(request, {"order": order, "client": {"gateway": "razorpay"}})
    try:
        payment, client = services.start_payment(order)
    except Exception:  # noqa: BLE001 - show a friendly error; stock is released by the timeout task
        logger.exception("Could not start payment")
        messages.error(request, _("We couldn't start the online payment. Please try again or choose Cash on Delivery."))
        return redirect(order.get_absolute_url())
    return _checkout_page(request, {"order": order, "client": client, "payment": payment})


@login_required
@require_POST
def razorpay_return(request, public_id):
    order = get_object_or_404(Order, public_id=public_id, user=request.user)
    try:
        ok = services.handle_return(order, request.POST.dict())
    except Exception:  # noqa: BLE001 - provider outage is reconciled later
        logger.warning("Payment return awaiting reconciliation for order %s", order.pk)
        ok = False
    if ok:
        return redirect("orders:success", public_id=order.public_id)
    messages.error(request, _("Payment could not be verified. If money was taken it will be confirmed automatically."))
    return redirect(order.get_absolute_url())


@login_required
def stripe_return(request, public_id):
    order = get_object_or_404(Order, public_id=public_id, user=request.user)
    try:
        ok = services.handle_return(order, {})
    except Exception:  # noqa: BLE001 - provider outage is reconciled later
        logger.warning("Payment return awaiting reconciliation for order %s", order.pk)
        ok = False
    if ok:
        return redirect("orders:success", public_id=order.public_id)
    messages.info(request, _("We're confirming your payment. This page will update shortly."))
    return redirect(order.get_absolute_url())


@login_required
@require_POST
def cancel_payment(request, public_id):
    order = get_object_or_404(Order, public_id=public_id, user=request.user)
    mark_payment_failed(order, reason="Customer cancelled payment")
    messages.info(request, _("Payment cancelled. Your items are back in stock; you can order again anytime."))
    return redirect("cart:detail")


@csrf_exempt
@require_POST
def webhook(request, gateway):
    if gateway not in ("razorpay", "stripe"):
        return HttpResponseBadRequest()
    try:
        result = services.handle_webhook(gateway, request.body, request.headers)
    except GatewayError as exc:
        logger.warning("Rejected %s webhook: %s", gateway, exc)
        return HttpResponseBadRequest("invalid")
    return HttpResponse(result, status=202 if result == "unknown" else 200)


@require_POST
def create_order(request, public_id):
    """Create/reuse a provider order for an owned shop order; never trust browser totals."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in before paying."}, status=401)
    order = get_object_or_404(Order, public_id=public_id, user=request.user)
    if order.payment_method != "razorpay" or order.total < 1:
        return JsonResponse({"error": "Choose Razorpay for an order of at least ₹1."}, status=400)
    try:
        _, client = services.start_payment(order)
    except GatewayError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    except Exception as exc:  # noqa: BLE001 - do not expose provider response or credentials
        # Razorpay reports invalid API credentials as BadRequestError rather than a dedicated auth type.
        auth = isinstance(exc, razorpay.errors.BadRequestError) and "authentication" in str(exc).lower()
        logger.warning("Razorpay order creation failed (%s)", type(exc).__name__)
        return JsonResponse(
            {"error": "Could not initialize payment. Please retry or contact support."}, status=401 if auth else 500
        )
    response = JsonResponse(client)
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
def verify_payment(request, public_id):
    """Verify Checkout signature and captured provider amount/currency before fulfillment."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Sign in before verifying payment."}, status=401)
    order = get_object_or_404(Order, public_id=public_id, user=request.user)
    if order.payment_method != "razorpay":
        return JsonResponse({"error": "This order does not use Razorpay."}, status=400)
    try:
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST.dict()
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid payment response."}, status=400)
    fields = ("razorpay_payment_id", "razorpay_order_id", "razorpay_signature")
    if not isinstance(data, dict) or any(
        not isinstance(data.get(k), str) or not data[k] or len(data[k]) > 256 for k in fields
    ):
        return JsonResponse({"error": "All three payment verification fields are required."}, status=400)
    try:
        verified = services.handle_return(order, data)
    except Exception:  # noqa: BLE001 - reconcile interrupted provider verification later
        logger.warning("Razorpay verification pending for order %s", order.pk)
        return JsonResponse(
            {"error": "Payment confirmation is pending. Do not pay again if money was deducted."}, status=503
        )
    if not verified:
        return JsonResponse(
            {"error": "Payment is not verified as captured. If debited, wait for confirmation."}, status=400
        )
    order.refresh_from_db()
    if order.payment_status != Order.PaymentStatus.PAID:
        return JsonResponse({"error": "Payment received; this order needs staff review."}, status=409)
    return JsonResponse(
        {"success": True, "redirect_url": reverse("orders:success", kwargs={"public_id": order.public_id})}
    )
