from celery import shared_task
from django.utils import timezone


@shared_task
def send_rate_email(order_id):
    from apps.notifications import services as notify

    from .models import Order

    order = Order.objects.filter(pk=order_id, status=Order.Status.DELIVERED, rate_email_sent=False).first()
    if not order:
        return False
    notify.customer_email(
        order.user.email,
        "rate_order",
        {"order": order, "subject_vars": {"number": order.number}},
        event_key="rate_order",
    )
    Order.objects.filter(pk=order.pk).update(rate_email_sent=True)
    return True


@shared_task
def run_subscriptions():
    from .subscriptions import run_due

    return run_due(timezone.localdate())
