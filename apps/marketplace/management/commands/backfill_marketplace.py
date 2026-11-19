"""Opt-in legacy ownership backfill. Historical financial rows are never rewritten."""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.catalog.models import Product
from apps.marketplace.checkout import allocate
from apps.marketplace.models import Fulfillment, FulfillmentLine, Seller, SellerTeam
from apps.orders.models import Order


class Command(BaseCommand):
    help = "Preview legacy marketplace ownership; use --apply after backup to attach the Rasiko-owned seller."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--owner-email", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        owner = User.objects.filter(email__iexact=options["owner_email"], role="owner").first()
        if not owner:
            raise CommandError("An existing owner account is required.")
        count = Product.objects.filter(seller_team__isnull=True).count()
        self.stdout.write(
            f"Unassigned products: {count}; orders without fulfillment records: {Order.objects.filter(fulfillments__isnull=True).count()}"
        )
        if not options["apply"]:
            self.stdout.write("Preview only. No changes made.")
            return
        seller, _ = Seller.objects.get_or_create(
            legacy_store=True, defaults={"name": "Rasiko", "owner": owner, "status": "active", "verified": True}
        )
        for product in Product.objects.filter(seller_team__isnull=True).iterator():
            team, _ = SellerTeam.objects.get_or_create(seller=seller, brand=product.brand)
            Product.objects.filter(pk=product.pk).update(seller_team=team)
        for order in Order.objects.filter(fulfillments__isnull=True).iterator():
            lines = list(order.lines.select_related("variant__product"))
            if not lines:
                continue
            weights = {}
            for line in lines:
                pk = line.variant.product.seller_team_id
                weights[pk] = weights.get(pk, Decimal("0")) + line.line_total
            discounts, coins = allocate(order.discount, weights), allocate(order.coins_value, weights)
            delivery = allocate(order.delivery_fee + order.small_order_fee + order.surcharge_total, weights)
            taxes = allocate(order.gst_total, weights)
            status = {
                "packed": "ready",
                "out_for_delivery": "confirmed",
                "delivered": "delivered",
                "cancelled": "cancelled",
                "refunded": "delivered",
            }.get(order.status, "placed")
            for team_id, subtotal in weights.items():
                f = Fulfillment.objects.create(
                    order=order,
                    team_id=team_id,
                    status=status,
                    subtotal=subtotal,
                    discount=discounts[team_id],
                    coins_value=coins[team_id],
                    delivery_fee=delivery[team_id],
                    tax=taxes[team_id],
                    total=subtotal - discounts[team_id] - coins[team_id] + delivery[team_id],
                    delivered_at=order.delivered_at,
                    policy={"legacy": True},
                    intervention_required=order.status not in ("delivered", "cancelled", "refunded"),
                )
                FulfillmentLine.objects.bulk_create(
                    [
                        FulfillmentLine(fulfillment=f, order_line=line)
                        for line in lines
                        if line.variant.product.seller_team_id == team_id
                    ]
                )
            if sum((f.total for f in order.fulfillments.all()), Decimal("0")) != order.total:
                raise CommandError(f"Order {order.number} does not reconcile; transaction rolled back.")
        self.stdout.write(
            self.style.SUCCESS(
                "Ownership backfilled; old orders/totals retained. Review open legacy orders before dispatch."
            )
        )
