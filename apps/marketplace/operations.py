from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.crypto import encrypt_str
from apps.orders.models import Order

from .access import fulfillments_for, require_territory
from .models import DeliveryAssignment, DispatchOffer, Fulfillment, RiderAccount, RiderEvent, TerritoryAssignment
from .services import new_delivery_code, notice


@transaction.atomic
def reset_delivery_code(actor, fulfillment, reason):
    Order.objects.select_for_update(of=("self",)).get(pk=fulfillment.order_id)
    f = Fulfillment.objects.select_for_update(of=("self",)).get(pk=fulfillment.pk)
    if not fulfillments_for(actor).filter(pk=f.pk).exists():
        raise PermissionDenied
    if f.status not in ("ready", "assigned", "picked_up") or not reason.strip():
        raise ValidationError("A live delivery and reset reason are required.")
    if f.last_otp_reset and f.last_otp_reset > timezone.now() - timedelta(minutes=1):
        raise ValidationError("Wait one minute before requesting another delivery code.")
    code, hashed = new_delivery_code()
    f.delivery_otp_hash, f.delivery_otp_encrypted = hashed, encrypt_str(code)
    f.otp_failures, f.last_otp_reset = 0, timezone.now()
    f.save()
    audit.log(None, "marketplace.delivery.code_reset", f, summary=reason, user=actor)
    from .tasks import delivery_code

    transaction.on_commit(lambda: delivery_code.delay(f.pk, code))


@transaction.atomic
def release_delivery(actor, fulfillment, reason):
    Order.objects.select_for_update(of=("self",)).get(pk=fulfillment.order_id)
    assignment = DeliveryAssignment.objects.filter(fulfillment=fulfillment, active=True).first()
    if assignment:
        RiderAccount.objects.select_for_update(of=("self",)).get(pk=assignment.rider_id)
    f = Fulfillment.objects.select_for_update(of=("self",)).get(pk=fulfillment.pk)
    if not fulfillments_for(actor).filter(pk=f.pk).exists():
        raise PermissionDenied
    if f.status != "assigned" or not reason.strip() or not assignment:
        raise ValidationError("Only an assigned delivery awaiting pickup can be released, with a reason.")
    assignment.active = False
    assignment.save(update_fields=["active"])
    RiderEvent.objects.create(
        rider=assignment.rider, fulfillment=f, kind="released", details={"reason": reason[:300], "by": actor.pk}
    )
    f.status, f.dispatch_attempts, f.intervention_required = "ready", 0, False
    f.save()
    DispatchOffer.objects.filter(fulfillment=f, status="pending").update(status="expired")
    audit.log(None, "marketplace.delivery.released", f, summary=reason, user=actor)
    from .dispatch import offer_delivery

    transaction.on_commit(lambda: offer_delivery(f.pk))


@transaction.atomic
def cancel_fulfillment(actor, fulfillment, reason):
    parent = Order.objects.select_for_update(of=("self",)).get(pk=fulfillment.order_id)
    f = Fulfillment.objects.select_for_update(of=("self",)).select_related("team__seller").get(pk=fulfillment.pk)
    if not fulfillments_for(actor).filter(pk=f.pk).exists():
        raise PermissionDenied
    if f.status == "cancelled":
        return f
    if f.status in ("picked_up", "delivered") or not reason.strip():
        raise ValidationError("Resolve dispatched deliveries through a support case; cancellation requires a reason.")
    from apps.inventory.models import StockMovement
    from apps.inventory.services import restock_lines

    lines = {
        row.order_line: row.order_line.qty - row.order_line.restocked_qty
        for row in f.lines.select_related("order_line")
    }
    if parent.payment_method == "cod" or parent.payment_status in ("paid", "partial_refund"):
        restock_lines(parent, lines, StockMovement.Reason.CANCEL_RESTOCK, user=actor)
    else:
        raise ValidationError(
            "Cancel the unpaid checkout as a whole so its payment reservation can be released safely."
        )
    if parent.payment_method != "cod":
        from apps.payments.services import create_refund

        reserved = -sum((entry.amount for entry in f.ledger.filter(kind="refund")), 0)
        remaining = f.total - reserved
        if remaining > 0:
            create_refund(
                parent,
                remaining,
                reason,
                actor,
                lines={line.pk: line.qty - line.refunded_qty for line in lines if line.qty > line.refunded_qty},
            )
    f.status, f.delivery_otp_encrypted = "cancelled", ""
    f.save()
    DeliveryAssignment.objects.filter(fulfillment=f).update(active=False)
    DispatchOffer.objects.filter(fulfillment=f, status="pending").update(status="expired")
    if not parent.fulfillments.exclude(status="cancelled").exists():
        parent.status, parent.cancelled_at = "cancelled", timezone.now()
        parent.save(update_fields=["status", "cancelled_at", "updated_at"])
    notice(f.team.seller, "Seller order cancelled", reason)
    audit.log(None, "marketplace.fulfillment.cancelled", f, summary=reason, user=actor)
    return f


@transaction.atomic
def remove_territory(actor, assignment, reason):
    require_territory(actor, assignment.team, assignment.territory)
    if not reason.strip():
        raise ValidationError("An area removal reason is required.")
    type(assignment.territory).objects.select_for_update(of=("self",)).get(pk=assignment.territory_id)
    assignment = TerritoryAssignment.objects.select_for_update(of=("self",)).get(pk=assignment.pk)
    if (
        assignment.team.fulfillments.filter(territory=assignment.territory)
        .exclude(status__in=["cancelled", "delivered"])
        .exists()
    ):
        raise ValidationError("Complete or cancel open deliveries in this area before reassignment.")
    assignment.active = False
    assignment.save(update_fields=["active", "updated_at"])
    audit.log(None, "marketplace.territory.removed", assignment, summary=reason, user=actor)
    notice(assignment.team.seller, "Service area removed", reason)
