import csv
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.delivery.models import Rider
from apps.orders import services as order_services
from apps.orders.invoice import invoice_pdf
from apps.orders.models import BulkQuote, Order, Subscription, ThanduComplaint
from apps.payments.models import Refund
from apps.payments.services import RefundError, create_refund

from ..permissions import can, dash

S = Order.Status


@dash("staff")
def order_list(request):
    qs = Order.objects.select_related("user").order_by("-placed_at", "-created_at")
    status = request.GET.get("status", "")
    if status == "open":
        qs = qs.filter(status__in=["placed", "confirmed", "packed", "out_for_delivery"])
    elif status:
        qs = qs.filter(status=status)
    else:
        qs = qs.exclude(status="pending_payment")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(number__icontains=q)
            | Q(ship_phone__icontains=q)
            | Q(ship_name__icontains=q)
            | Q(user__email__icontains=q)
            | Q(ship_pincode=q)
        )
    if request.GET.get("export") == "csv" and can(request.user, "manager"):
        return _export(qs)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "dashboard/orders.html", {"page": page, "status": status, "q": q, "statuses": S.choices})


def _export(qs):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="rasiko-orders.csv"'
    w = csv.writer(resp)
    w.writerow(
        [
            "Order",
            "Placed",
            "Status",
            "Payment",
            "Payment status",
            "Customer",
            "Phone",
            "Pincode",
            "Items",
            "Subtotal",
            "Discount",
            "Delivery",
            "Total",
            "Refunded",
        ]
    )
    for o in qs.prefetch_related("lines")[:10000]:
        w.writerow(
            [
                o.number,
                o.placed_at,
                o.get_status_display(),
                o.payment_method,
                o.payment_status,
                _safe(o.ship_name),
                o.ship_phone,
                o.ship_pincode,
                sum(ln.qty for ln in o.lines.all()),
                o.subtotal,
                o.discount + o.coins_value,
                o.delivery_fee + o.small_order_fee + o.surcharge_total,
                o.total,
                o.refunded_total,
            ]
        )
    return resp


def _safe(value):
    """Stop spreadsheet formula injection in CSV exports."""
    value = str(value)
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


class RefundForm(forms.Form):
    amount = forms.DecimalField(
        min_value=Decimal("0.01"), decimal_places=2, widget=forms.NumberInput(attrs={"class": "input", "step": "0.01"})
    )
    reason = forms.CharField(max_length=300, widget=forms.TextInput(attrs={"class": "input"}))
    method = forms.ChoiceField(choices=Refund.Method.choices, widget=forms.Select(attrs={"class": "input"}))
    reference = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "UPI / bank reference for manual refunds"}),
    )
    restock = forms.BooleanField(required=False, label="Put refunded items back in stock")


@dash("staff")
def order_detail(request, number):
    order = get_object_or_404(Order.objects.select_related("user", "rider", "coupon"), number=number)
    nexts = [(s, S(s).label) for s in order_services.ALLOWED.get(order.status, set()) if s != S.REFUNDED]
    order_flow = [s for s, _ in S.choices]
    nexts.sort(key=lambda x: order_flow.index(x[0]))
    refund_form = None
    if can(request.user, "manager") and order.payment_status in (
        Order.PaymentStatus.PAID,
        Order.PaymentStatus.COD_COLLECTED,
        Order.PaymentStatus.PARTIALLY_REFUNDED,
    ):
        refund_form = RefundForm(
            initial={
                "amount": order.refundable_amount,
                "method": Refund.Method.GATEWAY if order.is_online else Refund.Method.UPI,
            }
        )
    return render(
        request,
        "dashboard/order_detail.html",
        {
            "order": order,
            "nexts": nexts,
            "riders": Rider.objects.filter(is_active=True),
            "events": order.events.select_related("by").order_by("at"),
            "refund_form": refund_form,
            "refunds": order.refunds.all().order_by("-created_at"),
            "lines": order.lines.all(),
            "payments": order.payments.all() if can(request.user, "manager") else [],
        },
    )


@dash("staff")
@require_POST
def order_status(request, number):
    order = get_object_or_404(Order, number=number)
    new = request.POST.get("status", "")
    rider = None
    if request.POST.get("rider"):
        rider = get_object_or_404(Rider, pk=request.POST["rider"], is_active=True)
    note = request.POST.get("note", "")[:200]
    if new == S.CANCELLED and not note:
        messages.error(request, "Please write why the order is cancelled. The customer sees this.")
        return redirect("dashboard:order", number)
    if new == S.DELIVERED and order.delivery_otp and request.POST.get("otp", "").strip() != order.delivery_otp:
        if not can(request.user, "manager"):
            messages.error(request, "Enter the 4-digit delivery code the customer shows the rider.")
            return redirect("dashboard:order", number)
        note = (note + " (delivered without the customer's code; marked by a manager)").strip()
    try:
        with transaction.atomic():
            order_services.set_status(order, new, by=request.user, note=note, rider=rider)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        audit.log(request, "order.status", order, f"{order.number} → {new}")
        messages.success(request, f"Order {order.number} is now {S(new).label}.")
    return redirect("dashboard:order", number)


@dash("staff")
@require_POST
def order_note(request, number):
    order = get_object_or_404(Order, number=number)
    order.staff_note = request.POST.get("staff_note", "")[:2000]
    if request.POST.get("rider"):
        r = get_object_or_404(Rider, pk=request.POST["rider"])
        order.rider, order.rider_name, order.rider_phone = r, r.name, r.phone
    order.save(update_fields=["staff_note", "rider", "rider_name", "rider_phone", "updated_at"])
    messages.success(request, "Saved.")
    return redirect("dashboard:order", number)


@dash("manager")
@require_POST
def order_refund(request, number):
    order = get_object_or_404(Order, number=number)
    form = RefundForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Check the refund amount and reason.")
        return redirect("dashboard:order", number)
    lines = {}
    for key, val in request.POST.items():
        if key.startswith("line_") and val.strip():
            try:
                lines[int(key[5:])] = int(val)
            except ValueError:
                continue
    d = form.cleaned_data
    try:
        with transaction.atomic():
            refund = create_refund(
                order,
                d["amount"],
                d["reason"],
                request.user,
                lines=lines,
                restock=d["restock"],
                method=d["method"],
                reference=d["reference"],
                request=request,
            )
    except (RefundError, InvalidOperation) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Refund of ₹{refund.amount} is {refund.get_status_display().lower()}.")
    return redirect("dashboard:order", number)


@dash("staff")
def order_invoice(request, number):
    order = get_object_or_404(Order, number=number)
    resp = HttpResponse(invoice_pdf(order), content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="Rasiko-invoice-{order.number}.pdf"'
    return resp


@dash("staff")
def packing_slip(request, number):
    order = get_object_or_404(Order, number=number)
    return render(request, "dashboard/packing_slip.html", {"order": order, "lines": order.lines.all()})


# ---- Party quotes, subscriptions, Thandu guarantee --------------------------------------------------------------


@dash("staff")
def bulk_quotes(request):
    if request.method == "POST":
        q = get_object_or_404(BulkQuote, pk=request.POST.get("id"))
        q.state = request.POST.get("state", q.state)
        amount = request.POST.get("quoted_amount", "").strip()
        try:
            q.quoted_amount = Decimal(amount) if amount else None
        except InvalidOperation:
            messages.error(request, "Quoted amount must be a number.")
            return redirect("dashboard:bulk_quotes")
        q.staff_note = request.POST.get("staff_note", "")[:1000]
        q.save()
        messages.success(request, f"Saved quote for {q.name}.")
        return redirect("dashboard:bulk_quotes")
    qs = BulkQuote.objects.order_by("-created_at")
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "dashboard/bulk_quotes.html", {"page": page, "states": BulkQuote.State.choices})


@dash("manager")
def subscriptions(request):
    if request.method == "POST":
        sub = get_object_or_404(Subscription, pk=request.POST.get("id"))
        action = request.POST.get("action")
        if action in ("active", "paused", "cancelled"):
            sub.state = action
            sub.save(update_fields=["state", "updated_at"])
            audit.log(request, "subscription.state", sub, f"{sub.user.email}: {action}")
            messages.success(request, "Subscription updated.")
        return redirect("dashboard:subscriptions")
    qs = Subscription.objects.select_related("user", "variant__product", "address").order_by("state", "next_run")
    return render(
        request, "dashboard/subscriptions.html", {"page": Paginator(qs, 40).get_page(request.GET.get("page"))}
    )


@dash("manager")
def thandu(request):
    from apps.core.models import StoreSettings
    from apps.notifications import services as notify
    from apps.promotions.services import make_personal_coupon

    if request.method == "POST":
        c = get_object_or_404(
            ThanduComplaint.objects.select_related("order__user"), pk=request.POST.get("id"), state="pending"
        )
        if request.POST.get("action") == "approve":
            amount = StoreSettings.load().thandu_coupon_amount
            with transaction.atomic():
                coupon = make_personal_coupon(c.order.user, amount, note=f"Thandu guarantee {c.order.number}")
                c.coupon, c.state, c.reviewed_by = coupon, "approved", request.user
                c.save()
                notify.customer_email(c.order.user.email, "thandu_coupon", {"coupon": coupon, "order": c.order})
            audit.log(request, "thandu.approve", c.order, f"{c.order.number}: coupon {coupon.code}")
            messages.success(request, f"Approved. Coupon {coupon.code} was emailed to the customer.")
        elif request.POST.get("action") == "reject":
            c.state, c.reviewed_by = "rejected", request.user
            c.save()
            messages.success(request, "Marked as rejected.")
        return redirect("dashboard:thandu")
    qs = ThanduComplaint.objects.select_related("order__user", "coupon").order_by("state", "-created_at")
    return render(request, "dashboard/thandu.html", {"page": Paginator(qs, 30).get_page(request.GET.get("page"))})
