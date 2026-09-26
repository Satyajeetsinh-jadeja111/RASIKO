from celery import shared_task
from django.utils import timezone


@shared_task
def expire_reservations():
    from .services import expire_reservations as run

    return run()


@shared_task
def send_back_in_stock(variant_id):
    from apps.catalog.models import BackInStockRequest, ProductVariant
    from apps.notifications import services as notify

    v = ProductVariant.objects.select_related("product").filter(pk=variant_id).first()
    if not v or not v.in_stock:
        return 0
    sent = 0
    for req in BackInStockRequest.objects.filter(variant=v, notified_at__isnull=True):
        notify.customer_email(
            req.email,
            "back_in_stock",
            {"variant": v, "product": v.product, "subject_vars": {"product": v.product.name}},
            event_key="back_in_stock",
        )
        req.notified_at = timezone.now()
        req.save(update_fields=["notified_at"])
        sent += 1
    return sent
