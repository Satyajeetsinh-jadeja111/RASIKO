from celery import shared_task
from django.utils import timezone


@shared_task
def retry_dispatch():
    from .dispatch import offer_delivery
    from .models import Fulfillment, MarketplaceSettings

    if MarketplaceSettings.load().dispatch_enabled:
        for pk in Fulfillment.objects.filter(status="ready").values_list("pk", flat=True)[:100]:
            offer_delivery(pk)


@shared_task
def send_offer(offer_id):
    from .models import DispatchOffer

    offer = DispatchOffer.objects.select_related("rider").get(pk=offer_id)
    if offer.status != "pending" or offer.expires_at <= timezone.now():
        return
    import logging

    from .push import send

    for device in offer.rider.devices.filter(active=True):
        try:
            send(device, offer)
        except Exception as exc:  # noqa: BLE001 - redact provider tokens and credentials
            logging.getLogger(__name__).warning("Rider push failed for offer %s (%s)", offer.pk, type(exc).__name__)
    # No customer data in notification payload. Mobile clients retrieve details after acceptance.
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    async_to_sync(get_channel_layer().group_send)(
        f"rider_{offer.rider.user_id}",
        {"type": "delivery.offer", "offer_id": offer.pk, "expires_at": offer.expires_at.isoformat()},
    )


@shared_task
def delivery_code(fulfillment_id, code):
    from apps.notifications.services import send_email

    from .models import Fulfillment

    f = Fulfillment.objects.select_related("order__user", "team__brand").get(pk=fulfillment_id)
    send_email(f.order.user.email, "marketplace_delivery", {"code": code, "brand": f.team.brand.name})


@shared_task
def email_notice(notice_id):
    from apps.notifications.services import send_email

    from .models import Notice

    row = Notice.objects.select_related("seller__owner").get(pk=notice_id)
    send_email(
        row.seller.owner.email,
        "partner_notice",
        {"title": row.title, "message": row.message, "subject_vars": {"title": row.title}},
    )


@shared_task
def reconcile_settlements():
    from datetime import timedelta

    from .models import MarketplaceSettings, Settlement
    from .settlements import reconcile_transfer, submit, submit_reversal

    if not MarketplaceSettings.load().payouts_enabled:
        return
    # Recover interrupted claims by lookup only; never blindly submit a second transfer.
    Settlement.objects.filter(status="submitting", last_checked__lt=timezone.now() - timedelta(minutes=5)).update(
        status="uncertain"
    )
    for pk in (
        Settlement.objects.filter(status__in=["eligible", "uncertain"], disputed=False)
        .order_by("last_checked", "pk")
        .values_list("pk", flat=True)[:100]
    ):
        submit(pk)

    for pk in (
        Settlement.objects.exclude(provider_id="").order_by("last_checked", "pk").values_list("pk", flat=True)[:100]
    ):
        try:
            reconcile_transfer(pk)
        except Exception as exc:  # noqa: BLE001 - retain status and redact provider details
            import logging

            logging.getLogger(__name__).warning("Transfer reconciliation %s failed (%s)", pk, type(exc).__name__)
    from .models import TransferReversal

    TransferReversal.objects.filter(status="submitting", last_checked__lt=timezone.now() - timedelta(minutes=5)).update(
        status="uncertain"
    )
    for pk in (
        TransferReversal.objects.filter(status__in=["pending", "uncertain"])
        .order_by("last_checked", "pk")
        .values_list("pk", flat=True)[:100]
    ):
        submit_reversal(pk)


@shared_task
def monitor_marketplace():
    from .monitoring import retain, scan

    scan()
    retain()


@shared_task
def onboard_seller(seller_id):
    import logging

    from django.core.exceptions import ValidationError

    from .onboarding import run

    try:
        run(seller_id)
    except ValidationError:
        logging.getLogger(__name__).warning("Seller %s onboarding requires review", seller_id)
