import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.orders.models import Order
from apps.orders.services import mark_payment_failed

from . import services
from .gateways import GatewayError

logger = logging.getLogger(__name__)


@login_required
def pay(request, public_id):
    order = get_object_or_404(Order, public_id=public_id, user=request.user)
    if order.status != Order.Status.PENDING_PAYMENT:
        return redirect(order.get_absolute_url())
    try:
        payment, client = services.start_payment(order)
    except Exception:  # noqa: BLE001 - show a friendly error; stock is released by the timeout task
        logger.exception("Could not start payment")
        messages.error(request, _("We couldn't start the online payment. Please try again or choose Cash on Delivery."))
        return redirect(order.get_absolute_url())
    return render(request, "payments/pay.html", {"order": order, "client": client, "payment": payment})


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
