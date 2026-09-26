import json
import logging

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.translation import get_language
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import OneTimeCode
from apps.core.ratelimit import hit
from apps.notifications import services as notify

from . import ai
from .models import ChatMessage, ChatSession, FaqArticle, Ticket

log = logging.getLogger(__name__)


def help_center(request):
    q = request.GET.get("q", "").strip()[:100]
    articles = FaqArticle.objects.filter(is_published=True)
    if q:
        hits = ai.retrieve(q, 10)
        articles = hits or articles.filter(Q(question__icontains=q) | Q(answer__icontains=q))
    topics = {}
    for a in articles:
        topics.setdefault(a.get_topic_display(), []).append(a)
    return render(request, "support/help.html", {"topics": topics, "q": q})


def _session(request, create=True):
    if not request.session.session_key:
        request.session.save()
    key = request.session.session_key
    pid = request.session.get("chat_id")
    chat = None
    if pid:
        chat = ChatSession.objects.filter(public_id=pid).first()
        if chat and not (
            chat.session_key == key or (request.user.is_authenticated and chat.user_id == request.user.pk)
        ):
            chat = None
    if chat is None and create:
        chat = ChatSession.objects.create(
            session_key=key,
            user=request.user if request.user.is_authenticated else None,
            language=(get_language() or "en")[:2],
        )
        request.session["chat_id"] = str(chat.public_id)
    return chat


def _payload(chat, after=0):
    msgs = chat.messages.filter(pk__gt=after).order_by("pk")
    return {"mode": chat.mode, "messages": [{"id": m.pk, "role": m.role, "text": m.text} for m in msgs]}


def _limited(request, scope, limit, window):
    who = (
        request.user.pk
        if request.user.is_authenticated
        else request.session.session_key or request.META.get("REMOTE_ADDR")
    )
    return hit(f"{scope}:{who}", limit, window)


@require_GET
def chat_poll(request):
    chat = _session(request, create=False)
    if chat is None:
        return JsonResponse({"mode": "bot", "messages": []})
    try:
        after = int(request.GET.get("after", 0))
    except ValueError:
        after = 0
    return JsonResponse(_payload(chat, after))


@require_POST
def chat_send(request):
    if _limited(request, "chat", 20, 60):
        return JsonResponse({"error": "Please slow down a little."}, status=429)
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        data = {}
    text = ai.sanitize_input(data.get("text", ""))
    if not text:
        return JsonResponse({"error": "Empty message"}, status=400)
    chat = _session(request)
    if data.get("lang") in ("en", "gu", "hi"):
        chat.language = data["lang"]
        chat.save(update_fields=["language", "updated_at"])
    last = chat.messages.order_by("-pk").values_list("pk", flat=True).first() or 0
    ChatMessage.objects.create(session=chat, role=ChatMessage.Role.USER, text=text)
    if chat.mode == ChatSession.Mode.HUMAN:
        if chat.ticket_id:
            Ticket.objects.filter(pk=chat.ticket_id).exclude(state=Ticket.State.OPEN).update(state=Ticket.State.OPEN)
        _broadcast(chat, text)
    else:
        reply = ai.answer(chat, text, request.user)
        ChatMessage.objects.create(session=chat, role=ChatMessage.Role.ASSISTANT, text=reply[:2000])
    chat.save(update_fields=["updated_at"])
    return JsonResponse(_payload(chat, last))


@require_POST
def chat_handoff(request):
    """'Talk to a person': create a ticket, email the admin, switch this chat to the team inbox."""
    if _limited(request, "handoff", 3, 600):
        return JsonResponse({"error": "Please wait a moment."}, status=429)
    chat = _session(request)
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        data = {}
    email = (request.user.email if request.user.is_authenticated else str(data.get("email", ""))).strip()[:254]
    if "@" not in email:
        return JsonResponse({"error": "email_required"}, status=400)
    if chat.ticket_id is None:
        first = chat.messages.filter(role=ChatMessage.Role.USER).first()
        ticket = Ticket.objects.create(
            user=request.user if request.user.is_authenticated else None,
            email=email,
            name=request.user.first_name if request.user.is_authenticated else str(data.get("name", ""))[:80],
            subject=(first.text if first else "Help request")[:160],
        )
        chat.ticket = ticket
        notify.admin_event("new_ticket", {"subject": ticket.subject, "email": email})
    chat.mode = ChatSession.Mode.HUMAN
    chat.save(update_fields=["ticket", "mode", "updated_at"])
    ChatMessage.objects.create(
        session=chat,
        role=ChatMessage.Role.SYSTEM,
        text="You're now chatting with the Rasiko team. If you leave, we'll reply by email.",
    )
    _broadcast(chat, "Customer asked to talk to a person")
    return JsonResponse(_payload(chat))


@require_POST
def chat_verify_order(request):
    """Prove an order belongs to you (order number + phone/email, then OTP) so the assistant may discuss it."""
    if _limited(request, "chatotp", 6, 600):
        return JsonResponse({"error": "Please wait a few minutes."}, status=429)
    from apps.orders.models import Order

    chat = _session(request)
    try:
        data = json.loads(request.body or "{}")
    except ValueError:
        data = {}
    number = str(data.get("number", "")).strip().upper()[:20]
    contact = str(data.get("contact", "")).strip().lower()[:254]
    order = Order.objects.filter(number=number).select_related("user").first()
    digits = "".join(c for c in contact if c.isdigit())[-10:]
    ok = order and (contact == order.user.email or (digits and digits in (order.ship_phone, order.user.phone)))
    if data.get("code"):
        if ok and OneTimeCode.verify(OneTimeCode.Purpose.TRACK_ORDER, f"order:{order.pk}", str(data["code"])):
            chat.verified_order_ids = sorted({*chat.verified_order_ids, order.pk})[-5:]
            chat.save(update_fields=["verified_order_ids", "updated_at"])
            return JsonResponse({"verified": True})
        return JsonResponse({"verified": False})
    if ok:
        code = OneTimeCode.issue(OneTimeCode.Purpose.TRACK_ORDER, f"order:{order.pk}")
        notify.customer_email(order.user.email, "otp", {"user": order.user, "code": code})
    return JsonResponse({"sent": True})


def _broadcast(chat, text):
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        async_to_sync(get_channel_layer().group_send)(
            "dashboard", {"type": "chat.message", "chat": str(chat.public_id), "text": text}
        )
    except Exception:  # noqa: BLE001
        log.debug("live chat push skipped", exc_info=True)


@login_required
def my_tickets(request):
    tickets = Ticket.objects.filter(user=request.user)
    return render(request, "support/tickets.html", {"tickets": tickets})


@login_required
def ticket_detail(request, public_id):
    ticket = get_object_or_404(Ticket, public_id=public_id, user=request.user)
    msgs = ticket.chat.messages.all() if hasattr(ticket, "chat") else []
    return render(request, "support/ticket.html", {"ticket": ticket, "msgs": msgs})
