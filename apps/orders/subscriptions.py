"""Daily/weekly subscriptions (milk, water cans, cold drinks for shops) become Cash on Delivery orders."""

import logging
from datetime import timedelta

from django.utils import timezone

from apps.cart.cart import DictCart
from apps.notifications import services as notify

from .models import Subscription
from .services import CheckoutError, place_order

logger = logging.getLogger(__name__)


def next_date(sub, after):
    if sub.frequency == Subscription.Frequency.DAILY:
        return after + timedelta(days=1)
    days = ((sub.weekday or 0) - after.weekday()) % 7 or 7
    return after + timedelta(days=days)


def run_due(today):
    created = 0
    for sub in Subscription.objects.filter(state=Subscription.State.ACTIVE, next_run__lte=today).select_related(
        "user", "address", "variant"
    ):
        run_date = sub.next_run
        sub.next_run = next_date(sub, max(run_date, today))
        if run_date.isoformat() in (sub.skip_dates or []):
            sub.skip_dates = [d for d in sub.skip_dates if d != run_date.isoformat()]
            sub.save(update_fields=["next_run", "skip_dates"])
            continue
        cart = DictCart({f"v:{sub.variant_id}": sub.qty})
        try:
            order = place_order(
                user=sub.user,
                cart=cart,
                address=sub.address,
                payment_method="cod",
                checkout_token=f"sub-{sub.pk}-{run_date.isoformat()}",
                source="subscription",
                note=f"Subscription delivery around {sub.delivery_time:%I:%M %p}",
            )
            sub.last_order = order
            created += 1
        except CheckoutError as exc:
            logger.warning("Subscription %s skipped: %s", sub.pk, exc)
            notify.customer_email(
                sub.user.email,
                "admin_event",
                {
                    "title": "We couldn't create your subscription delivery",
                    "data": {"product": str(sub.variant), "reason": str(exc)},
                    "subject_vars": {"title": "Subscription delivery skipped"},
                },
            )
        sub.save(update_fields=["next_run", "last_order", "skip_dates"])
    return created


def first_run(frequency, weekday=None):
    today = timezone.localdate()
    if frequency == Subscription.Frequency.DAILY:
        return today + timedelta(days=1)
    days = ((weekday or 0) - today.weekday()) % 7 or 7
    return today + timedelta(days=days)
