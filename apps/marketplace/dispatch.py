"""All dispatch mutations serialize on parent order, rider, then fulfillment."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import check_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.orders.models import Order

from .models import (
    DeliveryAssignment,
    DispatchOffer,
    Fulfillment,
    LedgerEntry,
    MarketplaceSettings,
    RiderAccount,
    RiderEvent,
)
from .services import effective_policy, new_delivery_code, record_sale


@transaction.atomic
def heartbeat(user, *, online, consent=False, lat=None, lng=None):
    rider = RiderAccount.objects.select_for_update(of=("self",)).get(user=user, active=True)
    if rider.seller.status != "active" or not user.is_active:
        raise PermissionDenied
    if lat is not None or lng is not None:
        if not consent or lat is None or lng is None:
            raise ValidationError("Location consent and both coordinates are required.")
        lat, lng = Decimal(str(lat)), Decimal(str(lng))
        if not lat.is_finite() or not lng.is_finite() or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValidationError("Invalid coordinates.")
    changed = rider.online != online
    rider.online, rider.location_consent, rider.last_seen = online, consent, timezone.now()
    rider.lat = lat if online and consent else None
    rider.lng = lng if online and consent else None
    rider.save()
    if changed:
        RiderEvent.objects.create(rider=rider, kind="online" if online else "offline")
    return rider


@transaction.atomic
def offer_delivery(fulfillment_id):
    if not MarketplaceSettings.load().dispatch_enabled:
        return []
    f = Fulfillment.objects.select_related("team__seller", "team__head__user", "order").get(pk=fulfillment_id)
    Order.objects.select_for_update(of=("self",)).get(pk=f.order_id)
    f = Fulfillment.objects.select_for_update(of=("self",)).get(pk=f.pk)
    if f.status != "ready" or not effective_policy(f.team)["operational"]:
        return []
    if f.order.payment_method != "cod" and f.order.payment_status != "paid":
        return []
    now = timezone.now()
    if f.offers.filter(status="pending", expires_at__gt=now).exists():
        return []
    f.offers.filter(status="pending").update(status="expired")
    if f.dispatch_attempts >= 3:
        f.intervention_required = True
        f.save(update_fields=["intervention_required"])
        return []
    riders = RiderAccount.objects.filter(
        seller=f.team.seller, active=True, online=True, last_seen__gte=now - timedelta(seconds=90), user__is_active=True
    ).exclude(deliveries__active=True)
    offers = [
        DispatchOffer.objects.create(fulfillment=f, rider=r, expires_at=now + timedelta(seconds=45)) for r in riders
    ]
    f.dispatch_attempts += 1
    f.intervention_required = not offers
    f.save(update_fields=["dispatch_attempts", "intervention_required"])
    from .tasks import send_offer

    for offer in offers:
        transaction.on_commit(lambda pk=offer.pk: send_offer.delay(pk))
    return offers


@transaction.atomic
def accept_offer(user, offer_id):
    offer = DispatchOffer.objects.select_related("fulfillment").get(pk=offer_id, rider__user=user)
    Order.objects.select_for_update(of=("self",)).get(pk=offer.fulfillment.order_id)
    rider = RiderAccount.objects.select_for_update(of=("self",)).select_related("seller").get(user=user)
    f = (
        Fulfillment.objects.select_for_update(of=("self",))
        .select_related("team__seller", "team__head__user")
        .get(pk=offer.fulfillment_id)
    )
    offer = DispatchOffer.objects.select_for_update(of=("self",)).get(pk=offer.pk)
    if (
        offer.status == "accepted"
        and DeliveryAssignment.objects.filter(fulfillment=f, rider=rider, active=True).exists()
    ):
        return f
    if (
        not rider.active
        or not rider.online
        or not user.is_active
        or not rider.last_seen
        or rider.last_seen < timezone.now() - timedelta(seconds=90)
        or rider.seller_id != f.team.seller_id
        or not effective_policy(f.team)["operational"]
    ):
        raise PermissionDenied("Rider is no longer eligible.")
    if (
        offer.status != "pending"
        or offer.expires_at <= timezone.now()
        or f.status != "ready"
        or rider.deliveries.filter(active=True).exists()
    ):
        raise ValidationError("Offer expired or another rider accepted it.")
    DeliveryAssignment.objects.update_or_create(fulfillment=f, defaults={"rider": rider, "active": True})
    offer.status = "accepted"
    offer.save(update_fields=["status"])
    f.offers.filter(status="pending").exclude(pk=offer.pk).update(status="lost")
    f.status, f.intervention_required = "assigned", False
    f.save(update_fields=["status", "intervention_required"])
    RiderEvent.objects.create(rider=rider, fulfillment=f, kind="accepted")
    return f


@transaction.atomic
def delivery_action(user, fulfillment_id, action, otp=""):
    f = Fulfillment.objects.get(pk=fulfillment_id)
    parent = Order.objects.select_for_update(of=("self",)).get(pk=f.order_id)
    rider = RiderAccount.objects.select_for_update(of=("self",)).get(user=user, active=True)
    f = Fulfillment.objects.select_for_update(of=("self",)).get(pk=f.pk)
    assignment = DeliveryAssignment.objects.filter(fulfillment=f, rider=rider).first()
    if assignment is None:
        raise PermissionDenied
    if action == "deliver" and f.status == "delivered":
        return f
    if not assignment.active:
        raise PermissionDenied
    if action == "pickup" and f.status == "assigned":
        f.status = "picked_up"
    elif action == "deliver" and f.status == "picked_up":
        if f.otp_failures >= 5 or not check_password(otp, f.delivery_otp_hash):
            # Return a value so failed-attempt state commits even when the API returns 400.
            f.otp_failures += 1
            f.save(update_fields=["otp_failures"])
            return None
        f.status, f.delivered_at = "delivered", timezone.now()
        f.delivery_otp_encrypted = ""
        assignment.active = False
        assignment.save(update_fields=["active"])
        record_sale(f)
        if parent.payment_method == "cod":
            LedgerEntry.objects.get_or_create(
                key=f"{f.pk}:cod_collected", defaults={"fulfillment": f, "kind": "cod_collected", "amount": f.total}
            )
        from apps.catalog.models import Product

        for row in f.lines.select_related("order_line__variant"):
            Product.objects.filter(pk=row.order_line.variant.product_id).update(
                sold_count=F("sold_count") + row.order_line.qty
            )
    else:
        raise ValidationError("Invalid delivery transition.")
    f.save()
    RiderEvent.objects.create(rider=rider, fulfillment=f, kind=action)
    statuses = list(parent.fulfillments.exclude(status="cancelled").values_list("status", flat=True))
    if statuses and all(s == "delivered" for s in statuses):
        parent.status, parent.delivered_at = "delivered", timezone.now()
        if parent.payment_method == "cod":
            parent.payment_status = "cod_collected"
        parent.save(update_fields=["status", "delivered_at", "payment_status", "updated_at"])
        from apps.orders.models import OrderEvent
        from apps.promotions.services import award_order_coins

        OrderEvent.objects.create(order=parent, status="delivered", by=user)
        award_order_coins(parent)
    elif any(s == "picked_up" for s in statuses):
        parent.status = "out_for_delivery"
        parent.save(update_fields=["status", "updated_at"])
    return f


@transaction.atomic
def mark_ready(actor, fulfillment):
    from .access import fulfillments_for, require_team

    Order.objects.select_for_update(of=("self",)).get(pk=fulfillment.order_id)
    f = Fulfillment.objects.select_for_update(of=("self",)).select_related("team").get(pk=fulfillment.pk)
    require_team(actor, f.team)
    if not fulfillments_for(actor).filter(pk=f.pk).exists():
        raise PermissionDenied
    if f.status not in ("placed", "confirmed"):
        raise ValidationError("Order cannot be marked ready.")
    if f.order.payment_method != "cod" and f.order.payment_status != "paid":
        raise ValidationError("Wait for payment capture.")
    from apps.core.crypto import encrypt_str

    if f.lines.filter(order_line__batch_allocations__batch__expires_on__lt=timezone.localdate()).exists():
        raise ValidationError("Allocated stock has expired. Resolve this order before pickup.")
    code, hashed = new_delivery_code()
    f.delivery_otp_encrypted = encrypt_str(code)
    f.status, f.ready_at, f.delivery_otp_hash = "ready", timezone.now(), hashed
    f.save()
    # Delivery codes belong to buyers, never riders or Heads.
    from .tasks import delivery_code

    transaction.on_commit(lambda: delivery_code.delay(f.pk, code))
    transaction.on_commit(lambda: offer_delivery(f.pk))
    return f
