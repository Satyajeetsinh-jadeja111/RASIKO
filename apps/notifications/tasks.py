import logging

from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from .backends import DashboardSMTPBackend, EmailNotConfigured, from_address
from .models import EmailLog

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=4, default_retry_delay=60)
def deliver_email(self, log_id, recipients, subject, html, text, attach_invoice_order_id=None):
    log = EmailLog.objects.filter(pk=log_id).first()
    if log is None:
        return
    log.attempts += 1
    try:
        from django.conf import settings

        from apps.core.integrations import get_config

        if settings.EMAIL_BACKEND.endswith("DashboardSMTPBackend"):
            connection = DashboardSMTPBackend()
            sender = from_address(get_config("smtp"))
        else:  # tests / custom backends
            from django.core.mail import get_connection

            connection = get_connection()
            sender = settings.DEFAULT_FROM_EMAIL
        msg = EmailMultiAlternatives(subject, text, sender, recipients, connection=connection)
        msg.attach_alternative(html, "text/html")
        if attach_invoice_order_id:
            from apps.orders.invoice import invoice_pdf
            from apps.orders.models import Order

            order = Order.objects.get(pk=attach_invoice_order_id)
            msg.attach(f"Rasiko-invoice-{order.number}.pdf", invoice_pdf(order), "application/pdf")
        msg.send()
        log.status = EmailLog.Status.SENT
        log.sent_at = timezone.now()
        log.error = ""
        log.save(update_fields=["status", "sent_at", "attempts", "error"])
    except EmailNotConfigured as exc:
        log.status = EmailLog.Status.NOT_SENT
        log.error = str(exc)[:500]
        log.save(update_fields=["status", "attempts", "error"])
    except Exception as exc:  # noqa: BLE001 - retry any transport failure
        log.status = EmailLog.Status.FAILED
        log.error = f"{exc.__class__.__name__}: {exc}"[:500]
        log.save(update_fields=["status", "attempts", "error"])
        raise self.retry(exc=exc) from exc
