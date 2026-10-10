"""One place that decides who gets told about what (email, WhatsApp)."""

import logging
import threading

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _l

from .models import EmailLog, NotificationSettings

logger = logging.getLogger(__name__)

SUBJECTS = {
    # customer
    "welcome": _l("Welcome to Rasiko! Please verify your email"),
    "otp": _l("Your Rasiko verification code"),
    "order_placed": _l("Order {number} placed"),
    "payment_received": _l("Payment received for order {number}"),
    "payment_failed": _l("Payment failed for order {number}"),
    "order_confirmed": _l("Order {number} confirmed"),
    "order_packed": _l("Order {number} is packed"),
    "order_out_for_delivery": _l("Order {number} is out for delivery"),
    "order_delivered": _l("Order {number} delivered. Your invoice is attached"),
    "order_cancelled": _l("Order {number} cancelled"),
    "refund_initiated": _l("Refund started for order {number}"),
    "refund_completed": _l("Refund completed for order {number}"),
    "rate_order": _l("How was your Rasiko order {number}?"),
    "back_in_stock": _l("{product} is back in stock"),
    "thandu_coupon": _l("Sorry it wasn't chilled. Here's a coupon"),
    "ticket_reply": _l("Rasiko Team replied to your question"),
    "bulk_quote_received": _l("We received your party order request"),
    "test": _l("Rasiko test email"),
    "coins_bonus": _l("You got bonus Rasiko Coins"),
    # admin
    "admin_event": _l("[Rasiko] {title}"),
    "admin_summary": _l("[Rasiko] {title}"),
}


def _subject(template, ctx):
    try:
        return str(SUBJECTS.get(template, "Rasiko")).format(**ctx.get("subject_vars", {}))
    except (KeyError, IndexError):
        return str(SUBJECTS.get(template, "Rasiko"))


def render_email(template, ctx):
    from django.conf import settings

    from apps.core.models import StoreSettings

    full = {"store": StoreSettings.load(), "SITE_URL": settings.SITE_URL, **ctx}
    html = render_to_string(f"emails/{template}.html", full)
    try:
        text = render_to_string(f"emails/{template}.txt", full)
    except Exception:  # noqa: BLE001 - fall back to a text version derived from HTML
        from django.utils.html import strip_tags

        text = strip_tags(html)
    return html, text


def send_email(to, template, ctx, attach_invoice_order_id=None):
    """Queue an email through Celery. ``to`` is an address or a list. Safe to call inside transactions."""
    recipients = [to] if isinstance(to, str) else list(to)
    recipients = [r for r in recipients if r]
    if not recipients:
        return None
    subject = _subject(template, ctx)
    html, text = render_email(template, ctx)
    log = EmailLog.objects.create(to=", ".join(recipients)[:500], subject=subject[:200], template=template)
    args = (log.pk, recipients, subject, html, text, attach_invoice_order_id)
    if getattr(settings, "EMAIL_SEND_INLINE", False):
        # Send straight away in a background thread so customers get order updates even when no Celery
        # worker is running; the worker is only needed to retry a send that failed.
        transaction.on_commit(lambda: threading.Thread(target=_send_in_thread, args=args, daemon=True).start())
    else:
        from .tasks import deliver_email

        transaction.on_commit(lambda: deliver_email.delay(*args))
    return log


def _send_in_thread(log_id, recipients, subject, html, text, attach_invoice_order_id=None):
    from django.db import close_old_connections

    from .backends import EmailNotConfigured
    from .tasks import deliver_email, deliver_now, mark_failed

    close_old_connections()
    try:
        log = EmailLog.objects.filter(pk=log_id).first()
        if log is None:
            return
        try:
            deliver_now(log, recipients, subject, html, text, attach_invoice_order_id)
        except EmailNotConfigured as exc:
            mark_failed(log, exc)
        except Exception as exc:  # noqa: BLE001 - network/SMTP hiccup: let the worker retry later
            mark_failed(log, exc)
            try:
                deliver_email.apply_async(
                    (log_id, recipients, subject, html, text, attach_invoice_order_id), countdown=60
                )
            except Exception:  # noqa: BLE001 - broker down too; the failure is already in the error log
                logger.exception("Could not queue a retry for email %s", log_id)
    finally:
        close_old_connections()


def send_email_now(to, template, ctx):
    """Send right away, without the Celery queue (for time-sensitive codes). Returns (sent, error message)."""
    from .tasks import deliver_now, mark_failed

    subject = _subject(template, ctx)
    html, text = render_email(template, ctx)
    log = EmailLog.objects.create(to=to[:500], subject=subject[:200], template=template)
    try:
        deliver_now(log, [to], subject, html, text)
        return True, ""
    except Exception as exc:  # noqa: BLE001 - the caller tells the customer; details go to the error log
        mark_failed(log, exc)
        return False, log.error


def customer_email(to, template, ctx, event_key=None, attach_invoice_order_id=None):
    s = NotificationSettings.load()
    if event_key and not s.is_on(f"c:{event_key}"):
        return None
    return send_email(to, template, ctx, attach_invoice_order_id)


def admin_event(key, data, title=None):
    s = NotificationSettings.load()
    recipients = s.recipients()
    if not recipients or not s.is_on(key):
        return None
    from .models import ADMIN_EVENTS

    title = title or str(ADMIN_EVENTS.get(key, key))
    ctx = {"title": title, "data": data, "subject_vars": {"title": title}, "event": key}
    return send_email(recipients, "admin_event", ctx)


def failed_login(email, ip):
    key = f"failed-logins:{ip}"
    n = cache.get(key, 0) + 1
    cache.set(key, n, 900)
    if n in (3, 10):
        admin_event(
            "security_failed_logins",
            {"email": email, "ip": ip, "attempts_15_min": n},
            title=_("%(n)s failed logins from %(ip)s") % {"n": n, "ip": ip},
        )


ORDER_TEMPLATES = {
    "placed": "order_placed",
    "confirmed": "order_confirmed",
    "packed": "order_packed",
    "out_for_delivery": "order_out_for_delivery",
    "delivered": "order_delivered",
    "cancelled": "order_cancelled",
    "payment_failed": "payment_failed",
}


def order_status_changed(order):
    template = ORDER_TEMPLATES.get(order.status)
    if not template:
        return
    ctx = {"order": order, "subject_vars": {"number": order.number}}
    attach = order.pk if order.status == "delivered" else None
    customer_email(order.user.email, template, ctx, event_key=template, attach_invoice_order_id=attach)
    from .tasks import deliver_whatsapp_update

    transaction.on_commit(lambda: deliver_whatsapp_update.delay(order.pk))
