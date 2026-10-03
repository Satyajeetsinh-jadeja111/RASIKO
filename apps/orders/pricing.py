"""Server-side order pricing. The browser never sends prices; everything is recalculated here."""

from dataclasses import dataclass, field
from decimal import Decimal

from apps.delivery.services import DeliveryQuote, money, quote
from apps.promotions.services import CouponError, coins_redeemable, validate_coupon

ZERO = Decimal("0")


@dataclass
class Totals:
    mrp_total: Decimal = ZERO
    subtotal: Decimal = ZERO
    coupon: object = None
    coupon_code: str = ""
    coupon_error: str = ""
    discount: Decimal = ZERO
    coins_available: int = 0
    coins_used: int = 0
    coins_value: Decimal = ZERO
    delivery: DeliveryQuote | None = None
    problems: list = field(default_factory=list)

    @property
    def delivery_total(self):
        return self.delivery.total if self.delivery and self.delivery.ok else ZERO

    @property
    def total(self):
        return money(max(ZERO, self.subtotal - self.discount - self.coins_value) + self.delivery_total)

    @property
    def savings(self):
        return money(max(ZERO, self.mrp_total - self.subtotal) + self.discount + self.coins_value)

    @property
    def ok(self):
        return not self.problems and (self.delivery is None or self.delivery.ok)


def price_cart(cart, user, coupon_code="", use_coins=False, location=None, now=None) -> Totals:
    """location = (lat, lng, pincode) or None when the address isn't chosen yet."""
    t = Totals(mrp_total=money(cart.mrp_total), subtotal=money(cart.subtotal))
    if not cart.lines():
        t.problems.append("Your cart is empty.")
    for line in cart.lines():
        if line.problem:
            t.problems.append(f"{line.name}: {line.problem}")
    if coupon_code:
        try:
            t.coupon, t.discount = validate_coupon(coupon_code, user, t.subtotal)
            t.coupon_code = t.coupon.code if t.coupon else ""
        except CouponError as exc:
            t.coupon_error = str(exc)
    after_discount = t.subtotal - t.discount
    t.coins_available, max_value = coins_redeemable(user, after_discount)
    if use_coins and t.coins_available:
        t.coins_used, t.coins_value = t.coins_available, max_value
    if location:
        # Delivery rules use the item value after coupon (not coins) for thresholds.
        t.delivery = quote(after_discount, *location, now=now)
    return t
