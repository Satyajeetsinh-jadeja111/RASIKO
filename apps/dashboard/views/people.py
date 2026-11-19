from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.models import User
from apps.analytics.models import CompetitorPrice
from apps.catalog.models import ProductVariant
from apps.core import audit
from apps.notifications import services as notify
from apps.promotions.models import CoinLedger, coin_balance
from apps.reviews.models import Review
from apps.reviews.services import refresh_product_rating
from apps.support.models import ChatMessage, ChatSession, Ticket

from ..permissions import dash

# ---- Customers --------------------------------------------------------------------------------------------------


@dash("manager")
def customers(request):
    qs = (
        User.objects.filter(role="customer")
        .annotate(
            n_orders=Count("orders", filter=Q(orders__status="delivered")),
            spent=Sum("orders__total", filter=Q(orders__status="delivered")),
            last_order=Max("orders__placed_at"),
        )
        .order_by("-last_order", "-date_joined")
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(phone__icontains=q) | Q(first_name__icontains=q))
    return render(
        request, "dashboard/customers.html", {"page": Paginator(qs, 40).get_page(request.GET.get("page")), "q": q}
    )


@dash("manager")
def customer(request, pk):
    user = get_object_or_404(User, pk=pk, role="customer")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "cod":
            user.cod_blocked = not user.cod_blocked
            user.save(update_fields=["cod_blocked"])
            audit.log(
                request, "customer.cod", user, f"{user.email}: COD {'blocked' if user.cod_blocked else 'allowed'}"
            )
            messages.success(request, "Cash on Delivery is now " + ("blocked." if user.cod_blocked else "allowed."))
        elif action == "coins":
            try:
                delta = int(request.POST.get("delta", "0"))
            except ValueError:
                delta = 0
            note = request.POST.get("note", "")[:160]
            if delta and note and coin_balance(user) + delta >= 0:
                CoinLedger.objects.create(user=user, delta=delta, reason=CoinLedger.Reason.ADJUST, note=note)
                audit.log(request, "customer.coins", user, f"{user.email}: {delta:+d} coins ({note})")
                messages.success(request, f"{delta:+d} coins added.")
            else:
                messages.error(request, "Enter a non-zero number and a reason; the balance can't go below zero.")
        elif action == "active":
            user.is_active = not user.is_active
            user.save(update_fields=["is_active"])
            audit.log(request, "customer.active", user, f"{user.email}: {'enabled' if user.is_active else 'disabled'}")
            messages.success(request, "Account " + ("enabled." if user.is_active else "disabled."))
        return redirect("dashboard:customer", pk)
    orders = user.orders.order_by("-placed_at")[:30]
    return render(
        request,
        "dashboard/customer.html",
        {
            "c": user,
            "orders": orders,
            "coins": coin_balance(user),
            "ledger": user.coin_entries.order_by("-created_at")[:20],
            "addresses": user.addresses.filter(is_archived=False),
            "stats": user.orders.filter(status="delivered").aggregate(n=Count("id"), spent=Sum("total")),
        },
    )


# ---- Reviews ----------------------------------------------------------------------------------------------------


@dash("staff")
def reviews(request):
    state = request.GET.get("state", "pending")
    qs = Review.objects.select_related("product", "user").prefetch_related("photos").order_by("-flagged", "-created_at")
    if state != "all":
        qs = qs.filter(state=state)
    if request.method == "POST":
        r = get_object_or_404(Review, pk=request.POST.get("id"))
        action = request.POST.get("action")
        if action in ("approved", "hidden"):
            r.state = action
            r.flagged = False if action == "approved" else r.flagged
        reply = request.POST.get("reply", "").strip()
        if reply != r.reply:
            r.reply = reply[:1000]
            r.replied_at = timezone.now() if reply else None
        r.save()
        refresh_product_rating(r.product_id)
        audit.log(request, "review.moderate", r, f"{r.product.name}: {r.state}")
        messages.success(request, "Review updated.")
        return redirect(request.get_full_path())
    return render(
        request, "dashboard/reviews.html", {"page": Paginator(qs, 20).get_page(request.GET.get("page")), "state": state}
    )


# ---- Support inbox ----------------------------------------------------------------------------------------------


@dash("staff")
def support(request):
    state = request.GET.get("state", "open")
    tickets = Ticket.objects.select_related("user", "order").annotate(last=Max("chat__messages__created_at"))
    if state != "all":
        tickets = tickets.filter(state=state)
    tickets = tickets.order_by("-last", "-created_at")
    return render(
        request,
        "dashboard/support.html",
        {
            "page": Paginator(tickets, 30).get_page(request.GET.get("page")),
            "state": state,
            "states": Ticket.State.choices,
        },
    )


@dash("staff")
def support_ticket(request, public_id):
    ticket = get_object_or_404(Ticket.objects.select_related("user", "order"), public_id=public_id)
    chat = getattr(ticket, "chat", None)
    if request.method == "POST":
        action = request.POST.get("action")
        text = request.POST.get("text", "").strip()[:2000]
        if action == "reply" and text:
            with transaction.atomic():
                if chat is None:
                    chat = ChatSession.objects.create(user=ticket.user, mode=ChatSession.Mode.HUMAN, ticket=ticket)
                ChatMessage.objects.create(session=chat, role=ChatMessage.Role.STAFF, text=text, staff=request.user)
                ticket.state = Ticket.State.WAITING
                ticket.save()
                notify.send_email(ticket.email, "ticket_reply", {"ticket": ticket, "reply": text})
            messages.success(request, "Reply sent. The customer sees it in the chat and by email.")
        elif action in [s for s, _ in Ticket.State.choices]:
            ticket.state = action
            ticket.save(update_fields=["state", "updated_at"])
            if chat and action == "closed":
                chat.mode = ChatSession.Mode.BOT
                chat.save(update_fields=["mode", "updated_at"])
            messages.success(request, f"Marked {ticket.get_state_display().lower()}.")
        return redirect("dashboard:support_ticket", public_id)
    msgs = chat.messages.select_related("staff").order_by("pk") if chat else []
    return render(
        request,
        "dashboard/support_ticket.html",
        {"t": ticket, "msgs": msgs, "chat": chat, "states": Ticket.State.choices},
    )


# ---- Competitor watch -------------------------------------------------------------------------------------------


@dash("manager")
def competitors(request):
    if request.method == "POST":
        v = get_object_or_404(ProductVariant, pk=request.POST.get("variant"))
        try:
            from decimal import Decimal

            price = Decimal(request.POST.get("price", ""))
            if price <= 0:
                raise ValueError
        except Exception:  # noqa: BLE001
            messages.error(request, "Enter the competitor's price as a number.")
            return redirect("dashboard:competitors")
        CompetitorPrice.objects.create(
            variant=v,
            competitor=request.POST.get("competitor", "")[:60] or "Other",
            price=price,
            note=request.POST.get("note", "")[:200],
            noted_by=request.user,
        )
        messages.success(request, "Price noted.")
        return redirect("dashboard:competitors")
    latest = {}
    for cp in CompetitorPrice.objects.select_related("variant__product").order_by("-noted_at")[:500]:
        latest.setdefault((cp.variant_id, cp.competitor.lower()), cp)
    rows = sorted(latest.values(), key=lambda c: (c.variant.product.name, c.competitor))
    for r in rows:
        r.diff = r.variant.price - r.price
    variants = ProductVariant.objects.select_related("product").filter(is_active=True).order_by("product__name")
    return render(request, "dashboard/competitors.html", {"rows": rows, "variants": variants})
