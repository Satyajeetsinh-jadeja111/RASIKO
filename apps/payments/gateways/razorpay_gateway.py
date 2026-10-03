import hashlib
import hmac
import json
from decimal import Decimal

import razorpay

from . import GatewayError, PaymentGateway, WebhookResult, to_paise


class RazorpayGateway(PaymentGateway):
    slug = "razorpay"

    @property
    def client(self):
        return razorpay.Client(auth=(self.config["key_id"], self.config["key_secret"]))

    def create_payment(self, order, payment):
        rp_order = self.client.order.create(
            {
                "amount": to_paise(payment.amount),
                "currency": "INR",
                "receipt": order.number,
                "notes": {"order": order.number, "idempotency_key": str(payment.idempotency_key)},
            }
        )
        payment.gateway_order_id = rp_order["id"]
        payment.raw = {"order": rp_order}
        payment.save(update_fields=["gateway_order_id", "raw", "updated_at"])
        return {
            "gateway": "razorpay",
            "key_id": self.config["key_id"],
            "order_id": rp_order["id"],
            "amount": to_paise(payment.amount),
            "currency": "INR",
            "name": "Rasiko",
            "description": f"Order {order.number}",
            "prefill": {"name": order.ship_name, "email": order.user.email, "contact": order.ship_phone},
        }

    def verify_return(self, payment, data):
        pid = data.get("razorpay_payment_id", "")
        sig = data.get("razorpay_signature", "")
        msg = f"{payment.gateway_order_id}|{pid}".encode()
        expected = hmac.new(self.config["key_secret"].encode(), msg, hashlib.sha256).hexdigest()
        if pid and hmac.compare_digest(expected, sig):
            payment.gateway_payment_id = pid
            payment.save(update_fields=["gateway_payment_id", "updated_at"])
            return True
        return False

    def parse_webhook(self, body, headers):
        secret = self.config.get("webhook_secret", "")
        sig = headers.get("X-Razorpay-Signature", "")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(expected, sig):
            raise GatewayError("Invalid Razorpay webhook signature")
        data = json.loads(body)
        etype = data.get("event", "")
        event_id = headers.get("X-Razorpay-Event-Id") or f"{etype}:{data.get('created_at')}"
        payload = data.get("payload", {})
        pay = payload.get("payment", {}).get("entity", {})
        ref = payload.get("refund", {}).get("entity", {})
        kind = "ignored"
        if etype in ("payment.captured", "order.paid"):
            kind = "payment_succeeded"
        elif etype == "payment.failed":
            kind = "payment_failed"
        elif etype == "refund.processed":
            kind = "refund_succeeded"
        elif etype == "refund.failed":
            kind = "refund_failed"
        return WebhookResult(
            event_id=event_id,
            event_type=etype,
            kind=kind,
            gateway_order_id=pay.get("order_id", ""),
            gateway_payment_id=pay.get("id", "") or ref.get("payment_id", ""),
            gateway_refund_id=ref.get("id", ""),
            amount=Decimal(pay.get("amount", 0)) / 100 if pay.get("amount") else None,
            reason=pay.get("error_description", "") or "",
            raw=data,
        )

    def refund(self, payment, amount, idempotency_key, notes):
        if not payment.gateway_payment_id:
            raise GatewayError("No Razorpay payment id on record")
        r = self.client.payment.refund(
            payment.gateway_payment_id,
            {"amount": to_paise(amount), "speed": "normal", "notes": notes, "receipt": idempotency_key[:40]},
        )
        status = {"processed": "succeeded", "failed": "failed"}.get(r.get("status"), "pending")
        return r["id"], status


def test_connection(config):
    client = razorpay.Client(auth=(config["key_id"], config["key_secret"]))
    client.order.all({"count": 1})
    mode = "TEST mode" if config["key_id"].startswith("rzp_test") else "LIVE mode"
    return True, f"Razorpay keys accepted ({mode})."
