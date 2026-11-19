"""Conservative Route adapter: claim once, then recover by source-payment lookup."""

from decimal import Decimal

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.integrations import get_config
from apps.delivery.services import money
from apps.payments.models import Payment, Refund

from .checkout import allocate
from .models import LedgerEntry, MarketplaceSettings, Settlement, TransferReversal


class RouteClient:
    def __init__(self):
        config = get_config("razorpay", allow_disabled=True)
        if not config:
            raise ValidationError("Razorpay credentials unavailable.")
        self.auth = (config["key_id"], config["key_secret"])

    def request(self, method, path, data=None):
        response = requests.request(
            method, "https://api.razorpay.com/v1/" + path, auth=self.auth, json=data, timeout=15
        )
        response.raise_for_status()
        return response.json()

    def collection(self, path):
        items = []
        for skip in range(0, 10000, 100):
            page = self.request("GET", f"{path}?count=100&skip={skip}").get("items", [])
            items.extend(page)
            if len(page) < 100:
                return items
        raise ValidationError("Provider collection exceeds the safe reconciliation limit.")

    def transfers(self, payment_id):
        return self.collection(f"payments/{payment_id}/transfers")

    def transfer(self, transfer_id):
        return self.request("GET", f"transfers/{transfer_id}?expand[]=recipient_settlement")

    def reversals(self, transfer_id):
        return self.collection(f"transfers/{transfer_id}/reversals")

    def reverse(self, transfer_id, amount, key):
        return self.request(
            "POST",
            f"transfers/{transfer_id}/reversals",
            {"amount": int(amount * 100), "notes": {"rasiko_reversal": str(key)}},
        )

    def create(self, payment_id, account, amount, key):
        return self.request(
            "POST",
            f"payments/{payment_id}/transfers",
            {
                "transfers": [
                    {
                        "account": account,
                        "amount": int(amount * 100),
                        "currency": "INR",
                        "notes": {"rasiko_settlement": str(key)},
                    }
                ]
            },
        ).get("items", [])


def submit(settlement_id, client=None):
    if not MarketplaceSettings.load().payouts_enabled or not getattr(settings, "MARKETPLACE_ROUTE_APPROVED", False):
        return None
    client = client or RouteClient()
    row = Settlement.objects.select_related("fulfillment__order", "fulfillment__team__seller").get(pk=settlement_id)
    from apps.orders.models import Order

    with transaction.atomic():
        Order.objects.select_for_update(of=("self",)).get(pk=row.fulfillment.order_id)
        row = (
            Settlement.objects.select_for_update(of=("self",))
            .select_related("fulfillment__order", "fulfillment__team__seller")
            .get(pk=row.pk)
        )
        f = row.fulfillment
        if (
            row.status not in ("eligible", "uncertain")
            or row.disputed
            or f.status != "delivered"
            or f.order.payment_method != "razorpay"
            or row.amount <= 0
        ):
            return row
        if f.order.refunds.filter(status=Refund.Status.PENDING).exists():
            return row
        if not f.team.seller.payments_ready or not f.team.seller.linked_account_id:
            return row
        payment = Payment.objects.filter(order=f.order, gateway="razorpay", status=Payment.Status.SUCCEEDED).first()
        if not payment or not payment.gateway_payment_id:
            return row
        # Check the entire checkout, including teams that have not delivered yet.
        # Otherwise an early team could consume funds reserved for later teams.
        total_entitlement = sum(
            (
                seller_balance(
                    child, -(child.ledger.filter(kind="refund").aggregate(n=Sum("amount"))["n"] or Decimal("0"))
                )
                for child in f.order.fulfillments.all()
            ),
            Decimal("0"),
        )
        if total_entitlement > payment.amount:
            row.disputed = True
            row.save(update_fields=["disputed"])
            return row
        recovery_only = row.status == "uncertain" or row.attempts > 0
        row.status, row.attempts, row.last_checked = "submitting", row.attempts + 1, timezone.now()
        row.save()
    try:
        matches = [
            t
            for t in client.transfers(payment.gateway_payment_id)
            if (t.get("notes") or {}).get("rasiko_settlement") == str(row.key)
        ]
        if not matches and not recovery_only:
            matches = client.create(payment.gateway_payment_id, f.team.seller.linked_account_id, row.amount, row.key)
        if len(matches) != 1:
            Settlement.objects.filter(pk=row.pk).update(status="uncertain")
            return row
        transfer = matches[0]
        if (
            transfer.get("recipient") != f.team.seller.linked_account_id
            or transfer.get("amount") != int(row.amount * 100)
            or transfer.get("currency") != "INR"
        ):
            Settlement.objects.filter(pk=row.pk).update(status="uncertain", disputed=True)
            return row
        with transaction.atomic():
            Order.objects.select_for_update(of=("self",)).get(pk=f.order_id)
            row = Settlement.objects.select_for_update(of=("self",)).get(pk=row.pk)
            row.provider_id, row.status = transfer["id"], "transferred"
            row.provider_status = transfer.get("status", "")
            row.save()
            LedgerEntry.objects.get_or_create(
                key=f"{row.pk}:transfer",
                defaults={"fulfillment": f, "kind": "transfer", "amount": row.amount, "reference": row.provider_id},
            )
    except (requests.RequestException, KeyError, ValueError):
        Settlement.objects.filter(pk=row.pk).update(status="uncertain")
    return row


def record_refund(refund):
    """Called under parent-order lock on confirmed refund only."""
    fulfillments = list(refund.order.fulfillments.all())
    if not fulfillments:
        return
    weights = refund_weights(fulfillments, refund.lines)
    shares = allocate(refund.amount, weights)
    for f in fulfillments:
        amount = shares.get(f.pk, Decimal("0"))
        if amount <= 0:
            continue
        LedgerEntry.objects.get_or_create(
            key=f"refund:{refund.pk}:{f.pk}",
            defaults={"fulfillment": f, "kind": "refund", "amount": -amount, "reference": str(refund.public_id)},
        )
        refunded_cash = -(f.ledger.filter(kind="refund").aggregate(n=Sum("amount"))["n"] or Decimal("0"))
        expected_adjustment = seller_balance(f, refunded_cash) - (
            f.total + f.coins_value - f.platform_fee - refunded_cash
        )
        previous_adjustment = f.ledger.filter(kind="adjustment", key__startswith="refund-adjust:").aggregate(
            n=Sum("amount")
        )["n"] or Decimal("0")
        LedgerEntry.objects.get_or_create(
            key=f"refund-adjust:{refund.pk}:{f.pk}",
            defaults={
                "fulfillment": f,
                "kind": "adjustment",
                "amount": expected_adjustment - previous_adjustment,
                "reference": str(refund.public_id),
            },
        )
        row = Settlement.objects.select_for_update(of=("self",)).filter(fulfillment=f).first()
        if row:
            if row.provider_id or row.status in ("submitting", "uncertain", "transferred", "settled"):
                row.disputed = True
                row.save(update_fields=["disputed"])
            else:
                refunded = -(f.ledger.filter(kind="refund").aggregate(n=Sum("amount"))["n"] or Decimal("0"))
                row.amount = seller_balance(f, refunded)
                row.save(update_fields=["amount"])


def validate_refund_allocation(order, amount, lines):
    """Prevent a seller's refundable balance from being consumed by another team."""
    fulfillments = list(order.fulfillments.all())
    if not fulfillments:
        return
    capacities = {f.pk: f.total for f in fulfillments}
    refunds = order.refunds.exclude(status=Refund.Status.FAILED)
    for refund in refunds:
        weights = refund_weights(fulfillments, refund.lines)
        for pk, share in allocate(refund.amount, weights).items():
            capacities[pk] -= share
    shares = allocate(amount, refund_weights(fulfillments, lines))
    if any(share > capacities[pk] for pk, share in shares.items()):
        raise ValidationError(
            "Refund exceeds a seller team's remaining balance. Review the selected lines and previous refunds."
        )


def refund_weights(fulfillments, lines):
    weights = {}
    for f in fulfillments:
        if lines:
            weight = sum(
                (
                    row.order_line.unit_price * int(lines.get(str(row.order_line_id), lines.get(row.order_line_id, 0)))
                    for row in f.lines.select_related("order_line")
                ),
                Decimal("0"),
            )
        else:
            weight = f.total
        if weight > 0:
            weights[f.pk] = weight
    return weights


def seller_balance(fulfillment, refunded):
    from apps.delivery.services import money

    f = fulfillment
    entitlement = f.total + f.coins_value - f.platform_fee
    if not f.total:
        return max(Decimal("0"), entitlement)
    return max(Decimal("0"), money(entitlement * (f.total - refunded) / f.total))


@transaction.atomic
def prepare_reversals(settlement):
    from apps.orders.models import Order

    Order.objects.select_for_update().get(pk=settlement.fulfillment.order_id)
    row = Settlement.objects.select_for_update().select_related("fulfillment").get(pk=settlement.pk)
    if not row.provider_id:
        return
    cumulative, previous = Decimal("0"), Decimal("0")
    for entry in row.fulfillment.ledger.filter(kind="refund").order_by("created_at", "pk"):
        refund_id = int(entry.key.split(":")[1])
        cumulative -= entry.amount
        target = max(Decimal("0"), row.amount - seller_balance(row.fulfillment, cumulative))
        amount = money(max(Decimal("0"), target - previous))
        if amount:
            TransferReversal.objects.get_or_create(settlement=row, refund_id=refund_id, defaults={"amount": amount})
        previous = target
    if previous:
        row.disputed = row.reversals.exclude(status="succeeded").exists()
        row.save(update_fields=["disputed"])


def reconcile_transfer(settlement_id, client=None):
    row = Settlement.objects.select_related("fulfillment__order", "fulfillment__team__seller").get(pk=settlement_id)
    if not row.provider_id:
        return row
    client = client or RouteClient()
    data = client.transfer(row.provider_id)
    f = row.fulfillment
    payment = Payment.objects.filter(order=f.order, gateway="razorpay", status=Payment.Status.SUCCEEDED).first()
    if (
        not payment
        or data.get("id") != row.provider_id
        or data.get("recipient") != f.team.seller.linked_account_id
        or data.get("source") != payment.gateway_payment_id
        or data.get("currency") != "INR"
        or data.get("amount") != int(row.amount * 100)
    ):
        Settlement.objects.filter(pk=row.pk).update(disputed=True)
        raise ValidationError("Transfer identity or amount mismatch.")
    from apps.orders.models import Order

    with transaction.atomic():
        Order.objects.select_for_update().get(pk=f.order_id)
        row = Settlement.objects.select_for_update().get(pk=row.pk)
        row.last_checked, row.provider_status = timezone.now(), data.get("status", "")
        if data.get("settlement_status") == "settled" and data.get("recipient_settlement_id"):
            row.status, row.recipient_settlement_id = "settled", data["recipient_settlement_id"]
            settlement_data = data.get("recipient_settlement") or {}
            row.bank_reference = settlement_data.get("utr", "")
            row.settled_at = row.settled_at or timezone.now()
            LedgerEntry.objects.get_or_create(
                key=f"{row.pk}:settled",
                defaults={
                    "fulfillment": f,
                    "kind": "settlement",
                    "amount": row.amount,
                    "reference": row.recipient_settlement_id,
                },
            )
        elif data.get("status") == "failed":
            row.status, row.disputed = "failed", True
        row.save()
        prepare_reversals(row)
    return row


def submit_reversal(reversal_id, client=None):
    if not MarketplaceSettings.load().payouts_enabled or not settings.MARKETPLACE_ROUTE_APPROVED:
        return None
    from apps.orders.models import Order

    reversal = TransferReversal.objects.select_related("settlement__fulfillment").get(pk=reversal_id)
    with transaction.atomic():
        Order.objects.select_for_update().get(pk=reversal.settlement.fulfillment.order_id)
        reversal = TransferReversal.objects.select_for_update().select_related("settlement").get(pk=reversal.pk)
        if reversal.status not in ("pending", "uncertain"):
            return reversal
        recovery_only = reversal.attempts > 0
        reversal.status, reversal.last_checked = "submitting", timezone.now()
        reversal.attempts += 1
        reversal.save()
    client = client or RouteClient()
    try:
        matches = [
            item
            for item in client.reversals(reversal.settlement.provider_id)
            if (item.get("notes") or {}).get("rasiko_reversal") == str(reversal.key)
        ]
        if not matches and not recovery_only:
            matches = [client.reverse(reversal.settlement.provider_id, reversal.amount, reversal.key)]
        if len(matches) != 1:
            TransferReversal.objects.filter(pk=reversal.pk).update(status="uncertain")
            return reversal
        data = matches[0]
        if (
            data.get("transfer_id") != reversal.settlement.provider_id
            or data.get("amount") != int(reversal.amount * 100)
            or data.get("currency") != "INR"
            or not data.get("id")
        ):
            raise ValidationError("Reversal identity mismatch.")
        with transaction.atomic():
            Order.objects.select_for_update().get(pk=reversal.settlement.fulfillment.order_id)
            reversal = TransferReversal.objects.select_for_update().get(pk=reversal.pk)
            reversal.provider_id, reversal.status = data["id"], "succeeded"
            reversal.save()
            LedgerEntry.objects.get_or_create(
                key=f"reversal:{reversal.pk}",
                defaults={
                    "fulfillment_id": reversal.settlement.fulfillment_id,
                    "kind": "transfer_reversal",
                    "amount": reversal.amount,
                    "reference": data["id"],
                },
            )
            prepare_reversals(reversal.settlement)
    except (requests.RequestException, KeyError, ValueError, ValidationError) as exc:
        TransferReversal.objects.filter(pk=reversal.pk).update(status="uncertain", error=type(exc).__name__)
    return reversal
