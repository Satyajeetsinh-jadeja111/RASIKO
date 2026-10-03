from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import StoreSettings

from .models import CoinLedger, Coupon, CouponRedemption, coin_balance

ZERO = Decimal("0")


class CouponError(Exception):
    pass


def validate_coupon(code, user, subtotal: Decimal):
    code = (code or "").strip().upper()
    if not code:
        return None, ZERO
    coupon = Coupon.objects.filter(code=code, is_active=True).first()
    now = timezone.now()
    if coupon is None or coupon.starts_at > now or (coupon.expires_at and coupon.expires_at <= now):
        raise CouponError(_("This coupon is not valid."))
    if coupon.only_user_id and (not user.is_authenticated or coupon.only_user_id != user.pk):
        raise CouponError(_("This coupon is not valid."))
    if subtotal < coupon.min_order:
        raise CouponError(
            _("Add items worth ₹%(v)s more to use %(c)s.") % {"v": coupon.min_order - subtotal, "c": code}
        )
    if coupon.usage_limit is not None and coupon.redemptions.count() >= coupon.usage_limit:
        raise CouponError(_("This coupon has been fully used."))
    if user.is_authenticated:
        used = CouponRedemption.objects.filter(coupon=coupon, user=user).count()
        if used >= coupon.per_user_limit:
            raise CouponError(_("You have already used this coupon."))
        if coupon.first_order_only and user.orders.exclude(status__in=["pending_payment", "payment_failed"]).exists():
            raise CouponError(_("This coupon is for your first order only."))
    return coupon, coupon.discount_for(subtotal)


def coins_redeemable(user, amount_after_discount: Decimal):
    """(coins, rupee value) the user may spend on this order."""
    if not user.is_authenticated:
        return 0, ZERO
    s = StoreSettings.load()
    balance = coin_balance(user)
    if balance <= 0 or s.coin_value_rupees <= 0:
        return 0, ZERO
    cap_value = (amount_after_discount * s.max_coin_redeem_percent / 100).quantize(Decimal("0.01"), ROUND_DOWN)
    cap_coins = int(cap_value / s.coin_value_rupees)
    coins = max(0, min(balance, cap_coins))
    return coins, (s.coin_value_rupees * coins).quantize(Decimal("0.01"))


@transaction.atomic
def award_order_coins(order):
    """Coins on delivery (+ referral and festival bonuses). Idempotent per order."""
    from .models import Campaign

    if CoinLedger.objects.filter(order=order, reason=CoinLedger.Reason.EARNED).exists():
        return 0
    s = StoreSettings.load()
    base = order.total - order.delivery_fee - order.small_order_fee - order.surcharge_total
    coins = int((base * s.coins_earn_percent / 100) / (s.coin_value_rupees or 1))
    if coins > 0:
        CoinLedger.objects.create(user=order.user, delta=coins, reason=CoinLedger.Reason.EARNED, order=order)
        type(order).objects.filter(pk=order.pk).update(coins_earned=coins)
    campaign = Campaign.current()
    if campaign and campaign.bonus_coins:
        CoinLedger.objects.create(
            user=order.user,
            delta=campaign.bonus_coins,
            reason=CoinLedger.Reason.FESTIVAL,
            order=order,
            note=campaign.name,
        )
    # Referral: both people get coins on the referred customer's first delivered order.
    user = order.user
    delivered = user.orders.filter(status="delivered").aggregate(n=Count("pk"))["n"]
    if user.referred_by_id and delivered == 1 and s.referral_coins:
        note = f"Referral: {user.email}"
        CoinLedger.objects.create(user=user, delta=s.referral_coins, reason=CoinLedger.Reason.REFERRAL, note=note)
        CoinLedger.objects.create(
            user=user.referred_by, delta=s.referral_coins, reason=CoinLedger.Reason.REFERRAL, note=note
        )
    return coins


def reverse_order_coins(order):
    earned = CoinLedger.objects.filter(order=order, reason=CoinLedger.Reason.EARNED).first()
    if earned and not CoinLedger.objects.filter(order=order, reason=CoinLedger.Reason.REVERSED, delta__lt=0).exists():
        CoinLedger.objects.create(user=order.user, delta=-earned.delta, reason=CoinLedger.Reason.REVERSED, order=order)


def refund_used_coins(order):
    if (
        order.coins_used
        and not CoinLedger.objects.filter(order=order, reason=CoinLedger.Reason.REVERSED, delta__gt=0).exists()
    ):
        CoinLedger.objects.create(
            user=order.user,
            delta=order.coins_used,
            reason=CoinLedger.Reason.REVERSED,
            order=order,
            note="Coins returned",
        )


def make_personal_coupon(user, amount, prefix="THANDU", days=30, note=""):
    import secrets

    return Coupon.objects.create(
        code=f"{prefix}{secrets.token_hex(3).upper()}",
        description=note or "Personal coupon",
        kind=Coupon.Kind.FLAT,
        value=amount,
        min_order=amount * 2,
        only_user=user,
        per_user_limit=1,
        usage_limit=1,
        expires_at=timezone.now() + timedelta(days=days),
    )
