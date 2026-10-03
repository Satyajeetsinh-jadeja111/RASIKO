"""Payment gateways behind one interface. Only one online gateway is active at a time
(StoreSettings.active_gateway), and each must be switched on with keys in Settings -> Integrations."""

from dataclasses import dataclass, field
from decimal import Decimal


class GatewayError(Exception):
    pass


@dataclass
class WebhookResult:
    event_id: str
    event_type: str
    kind: str  # payment_succeeded | payment_failed | refund_succeeded | refund_failed | ignored
    gateway_order_id: str = ""
    gateway_payment_id: str = ""
    gateway_refund_id: str = ""
    amount: Decimal | None = None
    reason: str = ""
    raw: dict = field(default_factory=dict)


class PaymentGateway:
    slug = ""

    def __init__(self, config: dict):
        self.config = config

    def create_payment(self, order, payment) -> dict:
        """Create the gateway-side payment; return data the checkout page needs."""
        raise NotImplementedError

    def verify_return(self, payment, data: dict) -> bool:
        """Verify the browser's return/callback (the webhook stays the source of truth)."""
        raise NotImplementedError

    def parse_webhook(self, body: bytes, headers) -> WebhookResult:
        """Verify the signature and normalise the event. Raise GatewayError when invalid."""
        raise NotImplementedError

    def refund(self, payment, amount: Decimal, idempotency_key: str, notes: dict) -> tuple[str, str]:
        """Return (gateway_refund_id, status: pending|succeeded|failed)."""
        raise NotImplementedError


def to_paise(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).quantize(Decimal("1")))


def get_gateway(slug: str | None = None) -> PaymentGateway | None:
    from apps.core.integrations import get_config
    from apps.core.models import StoreSettings

    slug = slug or StoreSettings.load().active_gateway
    cfg = get_config(slug) if slug in ("razorpay", "stripe") else None
    if not cfg:
        return None
    if slug == "razorpay":
        from .razorpay_gateway import RazorpayGateway

        return RazorpayGateway(cfg)
    from .stripe_gateway import StripeGateway

    return StripeGateway(cfg)
