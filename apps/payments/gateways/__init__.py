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
    currency: str = ""
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

    def retrieve_payment(self, payment) -> WebhookResult:
        """Fetch authoritative provider status without creating a payment."""
        raise NotImplementedError

    def retrieve_refund(self, refund) -> tuple[str, str]:
        """Find a submitted refund by provider ID or persisted operation reference."""
        raise NotImplementedError

    def refund(self, payment, amount: Decimal, idempotency_key: str, notes: dict) -> tuple[str, str]:
        """Return (gateway_refund_id, status: pending|succeeded|failed)."""
        raise NotImplementedError


def to_paise(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).quantize(Decimal("1")))


def online_gateway() -> str | None:
    """Use the owner's selected gateway, with cross-gateway fallback only when explicitly enabled.
    An unavailable gateway or "None" selection leaves Cash on Delivery available."""
    from apps.core.integrations import is_enabled
    from apps.core.models import StoreSettings

    store = StoreSettings.load()
    chosen = store.active_gateway
    if chosen not in ("razorpay", "stripe"):
        return None
    candidates = (
        (chosen, "stripe" if chosen == "razorpay" else "razorpay") if store.gateway_fallback_enabled else (chosen,)
    )
    for slug in candidates:
        if is_enabled(slug):
            return slug
    return None


def get_gateway(slug: str | None = None, *, historical=False) -> PaymentGateway | None:
    from apps.core.integrations import get_config

    slug = slug or online_gateway()
    cfg = get_config(slug, allow_disabled=historical) if slug in ("razorpay", "stripe") else None
    if not cfg:
        return None
    if slug == "razorpay":
        from .razorpay_gateway import RazorpayGateway

        return RazorpayGateway(cfg)
    from .stripe_gateway import StripeGateway

    return StripeGateway(cfg)
