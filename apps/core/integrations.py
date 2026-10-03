"""Registry of every third-party service that needs an API key.

Each integration is OFF until the Owner switches it on in
Dashboard -> Settings -> Integrations and pastes its keys. While it is off the
site uses the free fallback described in ``fallback``.
"""

from dataclasses import dataclass, field

from django.core.cache import cache
from django.utils.module_loading import import_string

CACHE_KEY = "integration:{slug}"


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
    default: str = ""
    choices: tuple = ()


@dataclass(frozen=True)
class IntegrationSpec:
    slug: str
    name: str
    cost: str
    where: str
    fallback: str
    fields: tuple = field(default_factory=tuple)
    tester: str = ""  # dotted path to fn(config) -> (ok: bool, message: str)


REGISTRY: dict[str, IntegrationSpec] = {
    spec.slug: spec
    for spec in [
        IntegrationSpec(
            slug="razorpay",
            name="Razorpay (UPI, cards, netbanking, wallets)",
            cost="Per-transaction fee, no monthly fee.",
            where="Razorpay Dashboard -> Account & Settings -> API Keys (webhook secret under Webhooks).",
            fallback="Online payment is hidden at checkout; Cash on Delivery only.",
            fields=(
                Field("key_id", "Key ID"),
                Field("key_secret", "Key secret", secret=True),
                Field("webhook_secret", "Webhook secret", secret=True),
            ),
            tester="apps.payments.gateways.razorpay_gateway.test_connection",
        ),
        IntegrationSpec(
            slug="stripe",
            name="Stripe",
            cost="Per-transaction fee. Stripe India accounts are invite-only.",
            where="Stripe Dashboard -> Developers -> API keys, and Developers -> Webhooks.",
            fallback="Stripe is hidden at checkout.",
            fields=(
                Field("publishable_key", "Publishable key"),
                Field("secret_key", "Secret key", secret=True),
                Field("webhook_secret", "Webhook signing secret", secret=True),
            ),
            tester="apps.payments.gateways.stripe_gateway.test_connection",
        ),
        IntegrationSpec(
            slug="whatsapp",
            name="WhatsApp Business (Meta Cloud API)",
            cost="Paid: Meta charges for most business-initiated messages. Check Meta's current India rates.",
            where="Meta for Developers -> your app -> WhatsApp -> API Setup; templates in WhatsApp Manager.",
            fallback="Free click-to-chat 'Order on WhatsApp' link; order updates go by email only.",
            fields=(
                Field("phone_number_id", "Phone number ID"),
                Field("business_account_id", "WhatsApp Business Account ID", required=False),
                Field("access_token", "Permanent access token", secret=True),
                Field("verify_token", "Webhook verify token", secret=True, required=False),
                Field("template_order_update", "Order update template name", default="order_update"),
                Field("template_language", "Template language code", default="en"),
            ),
            tester="apps.notifications.whatsapp.test_connection",
        ),
        IntegrationSpec(
            slug="claude",
            name="Claude AI help chat",
            cost="Pay per use (Anthropic API).",
            where="console.anthropic.com -> API Keys.",
            fallback="The FAQ-matching help bot answers from Help Center articles.",
            fields=(
                Field("api_key", "API key", secret=True),
                Field("model", "Model name", default="claude-haiku-4-5-20251001"),
                Field(
                    "insights_summary",
                    "Also write the daily insights summary (yes/no)",
                    default="no",
                    required=False,
                    choices=("yes", "no"),
                ),
            ),
            tester="apps.support.ai.test_connection",
        ),
        IntegrationSpec(
            slug="sms",
            name="SMS OTP",
            cost="Pay per SMS. Indian SMS needs DLT registration.",
            where="Your SMS provider's dashboard (MSG91 or Twilio).",
            fallback="Phone checks for Cash on Delivery use an email OTP.",
            fields=(
                Field("provider", "Provider", choices=("msg91", "twilio"), default="msg91"),
                Field("api_key", "API key / auth token", secret=True),
                Field("account_sid", "Twilio account SID (Twilio only)", required=False),
                Field("sender_id", "Sender ID / from number"),
                Field("template_id", "DLT template ID (MSG91)", required=False),
            ),
            tester="apps.accounts.sms.test_connection",
        ),
        IntegrationSpec(
            slug="smtp",
            name="Email (SMTP)",
            cost="Free with Gmail (daily sending limits apply).",
            where="Google Account -> Security -> 2-Step Verification -> App passwords.",
            fallback="Emails are saved in the email log but not sent.",
            fields=(
                Field("host", "SMTP host", default="smtp.gmail.com"),
                Field("port", "Port", default="587"),
                Field("use_tls", "Use TLS (yes/no)", default="yes", choices=("yes", "no")),
                Field("username", "Email address / username"),
                Field("password", "App password", secret=True),
                Field("from_name", "Sender name", default="Rasiko"),
                Field("from_email", "Sender email (defaults to username)", required=False),
            ),
            tester="apps.notifications.backends.test_connection",
        ),
        IntegrationSpec(
            slug="s3",
            name="Cloud storage (S3-compatible, optional)",
            cost="Paid by storage used.",
            where="AWS S3, Cloudflare R2, DigitalOcean Spaces, etc.",
            fallback="Uploaded images are stored on the server itself.",
            fields=(
                Field("endpoint_url", "Endpoint URL", required=False),
                Field("bucket", "Bucket name"),
                Field("region", "Region", required=False),
                Field("access_key", "Access key"),
                Field("secret_key", "Secret key", secret=True),
                Field("custom_domain", "Public domain (optional)", required=False),
            ),
            tester="apps.core.storage.test_connection",
        ),
    ]
}


def get_config(slug: str) -> dict | None:
    """Return the decrypted config for an enabled integration, or None when it is off."""
    from .models import Integration

    cached = cache.get(CACHE_KEY.format(slug=slug))
    if cached is not None:
        return cached or None
    row = Integration.objects.filter(slug=slug).first()
    config = row.config() if row and row.enabled else {}
    cache.set(CACHE_KEY.format(slug=slug), config, 300)
    return config or None


def is_enabled(slug: str) -> bool:
    return get_config(slug) is not None


def clear_cache(slug: str) -> None:
    cache.delete(CACHE_KEY.format(slug=slug))


def run_test(slug: str, config: dict) -> tuple[bool, str]:
    spec = REGISTRY[slug]
    if not spec.tester:
        return True, "Saved."
    try:
        return import_string(spec.tester)(config)
    except Exception as exc:  # noqa: BLE001 - surface any provider error to the owner
        return False, f"Connection failed: {exc.__class__.__name__}: {str(exc)[:200]}"
