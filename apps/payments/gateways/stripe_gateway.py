import json
from decimal import Decimal

import stripe

from . import GatewayError, PaymentGateway, WebhookResult, to_paise


class StripeGateway(PaymentGateway):
    slug = "stripe"

    def _client(self):
        return stripe.StripeClient(self.config["secret_key"])

    def create_payment(self, order, payment):
        intent = self._client().v1.payment_intents.create(
            params={
                "amount": to_paise(payment.amount),
                "currency": "inr",
                "automatic_payment_methods": {"enabled": True},
                "description": f"Rasiko order {order.number}",
                "metadata": {"order": order.number, "payment_id": str(payment.pk)},
                "receipt_email": order.user.email,
            },
            options={"idempotency_key": f"pi-{payment.idempotency_key}"},
        )
        payment.gateway_order_id = intent.id
        payment.save(update_fields=["gateway_order_id", "updated_at"])
        return {
            "gateway": "stripe",
            "publishable_key": self.config["publishable_key"],
            "client_secret": intent.client_secret,
        }

    def verify_return(self, payment, data):
        intent = self._client().v1.payment_intents.retrieve(payment.gateway_order_id)
        if intent.status == "succeeded":
            payment.gateway_payment_id = intent.latest_charge or intent.id
            payment.save(update_fields=["gateway_payment_id", "updated_at"])
            return True
        return False

    def parse_webhook(self, body, headers):
        try:
            stripe.Webhook.construct_event(
                body, headers.get("Stripe-Signature", ""), self.config.get("webhook_secret", "")
            )
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise GatewayError("Invalid Stripe webhook signature") from exc
        # Signature verified; read the plain JSON (StripeObjects are not dicts in stripe>=12).
        event = json.loads(body)
        obj = event["data"]["object"]
        etype = event["type"]
        kind = {
            "payment_intent.succeeded": "payment_succeeded",
            "payment_intent.payment_failed": "payment_failed",
            "payment_intent.canceled": "payment_failed",
            "refund.updated": "refund_update",
            "refund.created": "refund_update",
            "charge.refund.updated": "refund_update",
        }.get(etype, "ignored")
        refund_id, reason = "", ""
        if kind == "refund_update":
            refund_id = obj.get("id", "")
            kind = {"succeeded": "refund_succeeded", "failed": "refund_failed", "canceled": "refund_failed"}.get(
                obj.get("status"), "ignored"
            )
        if etype.startswith("payment_intent"):
            err = obj.get("last_payment_error") or {}
            reason = err.get("message", "") if isinstance(err, dict) else ""
        return WebhookResult(
            event_id=event["id"],
            event_type=etype,
            kind=kind,
            gateway_order_id=obj.get("id", "") if etype.startswith("payment_intent") else obj.get("payment_intent", ""),
            gateway_payment_id=obj.get("latest_charge", "") or "",
            gateway_refund_id=refund_id,
            amount=Decimal(obj.get("amount", 0)) / 100 if obj.get("amount") else None,
            reason=reason,
            raw={"id": event["id"], "type": etype},
        )

    def refund(self, payment, amount, idempotency_key, notes):
        r = self._client().v1.refunds.create(
            params={"payment_intent": payment.gateway_order_id, "amount": to_paise(amount), "metadata": notes},
            options={"idempotency_key": f"re-{idempotency_key}"},
        )
        status = {"succeeded": "succeeded", "failed": "failed", "canceled": "failed"}.get(r.status, "pending")
        return r.id, status


def test_connection(config):
    stripe.StripeClient(config["secret_key"]).v1.balance.retrieve()
    mode = "TEST mode" if config["secret_key"].startswith("sk_test") else "LIVE mode"
    if not config["publishable_key"].startswith("pk_"):
        raise GatewayError("The publishable key should start with pk_")
    return True, f"Stripe keys accepted ({mode})."
