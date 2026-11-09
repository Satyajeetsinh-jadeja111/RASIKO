"""Marketplace pricing and policy checks shared by preview, checkout and payment creation."""

from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from apps.delivery.services import DeliveryQuote, money

from .models import FeePolicy, Fulfillment, FulfillmentLine, HeadCampaign, MarketplaceSettings, TerritoryAssignment
from .services import effective_policy

ZERO = Decimal("0")


def cart_groups(cart):
    from apps.orders.services import _expand_lines

    groups = {}
    for variant, qty, price, _mrp, _combo in _expand_lines(cart):
        team = variant.product.seller_team
        if team is None:
            raise ValidationError("A product has no seller team. Contact Rasiko support.")
        if team.brand_id != variant.product.brand_id:
            raise ValidationError("Product brand does not match its seller team.")
        group = groups.setdefault(team.pk, {"team": team, "subtotal": ZERO})
        group["subtotal"] += price * qty
    return groups


def validate_groups(groups, pincode):
    for group in groups.values():
        team = group["team"]
        policy = effective_policy(team)
        if not policy["operational"]:
            raise ValidationError("A seller team is unavailable. Update your cart.")
        assignment = TerritoryAssignment.objects.filter(
            team=team,
            brand_id=team.brand_id,
            active=True,
            effective_at__lte=timezone.now(),
            territory__pincodes__code=pincode,
        )
        if team.head_id:
            assignment = assignment.filter(territory__heads=team.head)
        area = assignment.first()
        if area is None:
            raise ValidationError(f"{team.seller.name} does not serve this address for {team.brand.name}.")
        group["territory"] = area.territory
        group["policy"] = policy
    return groups


def quote_cart(cart, pincode):
    groups = validate_groups(cart_groups(cart), pincode)
    minutes = max((g["team"].estimated_minutes for g in groups.values()), default=60)
    return DeliveryQuote(
        ok=True,
        delivery_fee=sum((g["team"].delivery_fee for g in groups.values()), ZERO),
        fast=False,
        eta_text=f"approximately {minutes} minutes",
    ), groups


def coupon_subtotal(coupon, groups):
    campaign = HeadCampaign.objects.filter(coupon=coupon).select_related("head").first()
    if campaign is None:
        return sum((g["subtotal"] for g in groups.values()), ZERO), set(groups)
    if not MarketplaceSettings.load().campaigns_enabled or not campaign.active or not campaign.head.active:
        raise ValidationError("This Head offer is unavailable.")
    team_ids = set(campaign.teams.values_list("pk", flat=True))
    territory_ids = set(campaign.territories.values_list("pk", flat=True))
    eligible = {
        pk
        for pk, g in groups.items()
        if pk in team_ids
        and g["team"].head_id == campaign.head_id
        and campaign.head.brands.filter(pk=g["team"].brand_id).exists()
        and (not territory_ids or (g.get("territory") and g["territory"].pk in territory_ids))
    }
    subtotal = sum((g["subtotal"] for pk, g in groups.items() if pk in eligible), ZERO)
    if not eligible or subtotal <= ZERO:
        raise ValidationError("This offer does not apply to these products or address.")
    return subtotal, eligible


def payment_methods(methods, groups):
    all_online = all(g["policy"]["online"] for g in groups.values())
    all_cod = all(g["policy"]["cod"] for g in groups.values())
    result = []
    for value, label, available, reason in methods:
        permitted = all_cod if value == "cod" else all_online and value == "razorpay"
        if not permitted:
            reason = (
                "These sellers require COD. Separate incompatible items if COD is unavailable."
                if value != "cod"
                else "COD is unavailable for part of this checkout. Separate or remove incompatible items."
            )
        result.append((value, label, available and permitted, reason))
    return result


def allocate(amount, weights):
    """Largest-remainder allocation, with no negative shares even for tiny amounts."""
    from decimal import ROUND_DOWN

    amount = money(amount)
    if amount < 0 or any(w < 0 for w in weights.values()):
        raise ValidationError("Allocation cannot be negative.")
    total = sum(weights.values(), ZERO)
    if not total:
        if amount:
            raise ValidationError("Cannot allocate money without a positive subtotal.")
        return {key: ZERO for key in weights}
    exact = {key: amount * weight / total for key, weight in weights.items()}
    result = {key: value.quantize(Decimal("0.01"), rounding=ROUND_DOWN) for key, value in exact.items()}
    pennies = int((amount - sum(result.values(), ZERO)) * 100)
    ranked = sorted(weights, key=lambda key: (-(exact[key] - result[key]), key))
    for key in ranked[:pennies]:
        result[key] += Decimal("0.01")
    return result


def split_order(order, groups):
    if order.fulfillments.exists():
        return
    lines = defaultdict(list)
    for line in order.lines.select_related("variant__product"):
        lines[line.variant.product.seller_team_id].append(line)
    weights = {pk: sum((line.line_total for line in rows), ZERO) for pk, rows in lines.items()}
    eligible = set(weights)
    if order.coupon_id:
        _, eligible = coupon_subtotal(order.coupon, groups)
    discounts = allocate(order.discount, {pk: value for pk, value in weights.items() if pk in eligible})
    coins = allocate(order.coins_value, weights)
    policy = FeePolicy.objects.filter(effective_at__lte=timezone.now()).order_by("-effective_at", "-pk").first()
    for team_id, rows in lines.items():
        g = groups[team_id]
        subtotal = weights[team_id]
        discount, coin = discounts.get(team_id, ZERO), coins[team_id]
        tax = (
            money(sum((line.gst_amount for line in rows), ZERO) * (subtotal - discount - coin) / subtotal)
            if subtotal
            else ZERO
        )
        if g["team"].seller.tax_registration != "regular":
            tax = ZERO
        fee = money(max(ZERO, subtotal - discount - tax) * policy.percent / 100) if policy and policy.enabled else ZERO
        f = Fulfillment.objects.create(
            order=order,
            team=g["team"],
            territory=g["territory"],
            subtotal=subtotal,
            discount=discount,
            coins_value=coin,
            tax=tax,
            delivery_fee=g["team"].delivery_fee,
            total=money(subtotal - discount - coin + g["team"].delivery_fee),
            platform_fee=fee,
            fee_policy=policy,
            policy=g["policy"],
        )
        FulfillmentLine.objects.bulk_create([FulfillmentLine(fulfillment=f, order_line=line) for line in rows])
    order.gst_total = order.fulfillments.aggregate(total=Sum("tax"))["total"] or ZERO
    order.save(update_fields=["gst_total"])
    child_total = order.fulfillments.aggregate(total=Sum("total"))["total"]
    if child_total != order.total:
        raise ValidationError("Seller order totals do not reconcile. Checkout was rolled back.")


def revalidate_online_order(order):
    if not order.fulfillments.exists():
        return
    for f in order.fulfillments.select_related("team__seller", "team__head__user"):
        if not effective_policy(f.team)["online"]:
            raise ValidationError("Online payment has been disabled for a seller. Start a new checkout.")
