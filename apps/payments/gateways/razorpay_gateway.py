import hashlib
import hmac
import json
from decimal import Decimal

import razorpay
import requests

from . import GatewayError, PaymentGateway, WebhookResult, to_paise


class TimeoutSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", (5, 15))
        return super().request(method, url, **kwargs)


class RazorpayGateway(PaymentGateway):
    slug = "razorpay"

    @property
    def client(self):
        return razorpay.Client(auth=(self.config["key_id"], self.config["key_secret"]), session=TimeoutSession())

    def create_payment(self, order, payment):
        if payment.gateway_order_id:
            rp_order = self.client.order.fetch(payment.gateway_order_id)
        else:
            receipt = "p-" + str(payment.idempotency_key).replace("-", "")
            if payment.creation_uncertain:
                matches = self.client.order.all({"receipt": receipt, "count": 100}).get("items", [])
                rp_order = next((o for o in matches if o.get("receipt") == receipt), None)
                if rp_order is None:
                    raise GatewayError("Payment creation is being reconciled. Please wait or contact support.")
            else:
                rp_order = self.client.order.create(
                    {
                        "amount": to_paise(payment.amount),
                        "currency": payment.currency,
                        "receipt": receipt,
                        "notes": {"order": order.number, "idempotency_key": str(payment.idempotency_key)},
                    }
                )
            payment.gateway_order_id = rp_order["id"]
            payment.creation_uncertain = False
            payment.save(update_fields=["gateway_order_id", "creation_uncertain", "updated_at"])
        if (
            rp_order.get("amount") != to_paise(payment.amount)
            or rp_order.get("currency", "").upper() != payment.currency
        ):
            raise GatewayError("Provider order does not match the payment.")
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
        if not pid or not hmac.compare_digest(expected, sig):
            return False
        pay = self.client.payment.fetch(pid)
        if (
            pay.get("order_id") != payment.gateway_order_id
            or pay.get("amount") != to_paise(payment.amount)
            or pay.get("currency", "").upper() != payment.currency
            or pay.get("status") != "captured"
        ):
            return False
        payment.gateway_payment_id = pid
        payment.save(update_fields=["gateway_payment_id", "updated_at"])
        return True

    def retrieve_payment(self, payment):
        items = self.client.order.payments(payment.gateway_order_id).get("items", [])
        pay = next((p for p in items if p.get("status") == "captured"), None)
        if not pay:
            return WebhookResult("", "reconcile", "ignored")
        return WebhookResult(
            "",
            "reconcile",
            "payment_succeeded",
            gateway_order_id=pay.get("order_id", ""),
            gateway_payment_id=pay["id"],
            amount=Decimal(pay["amount"]) / 100,
            currency=pay.get("currency", ""),
        )

    def retrieve_refund(self, refund):
        if refund.gateway_refund_id:
            item = self.client.refund.fetch(refund.gateway_refund_id)
        else:
            # Search every page: never resubmit an uncertain non-idempotent refund.
            skip = 0
            while True:
                items = self.client.payment.fetch_multiple_refund(
                    refund.payment.gateway_payment_id, {"count": 100, "skip": skip}
                ).get("items", [])
                item = next((i for i in items if i.get("notes", {}).get("refund") == str(refund.public_id)), None)
                if item or len(items) < 100:
                    break
                skip += 100
            if not item:
                return "", "pending"
        if item.get("payment_id") != refund.payment.gateway_payment_id or item.get("amount") != to_paise(refund.amount):
            raise GatewayError("Refund does not match the operation.")
        return item["id"], {"processed": "succeeded", "failed": "failed"}.get(item.get("status"), "pending")

    def parse_webhook(self, body, headers):
        secret = self.config.get("webhook_secret", "")
        sig = headers.get("X-Razorpay-Signature", "")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(expected, sig):
            raise GatewayError("Invalid Razorpay webhook signature")
        data = json.loads(body)
        etype = data.get("event", "")
        event_id = headers.get("X-Razorpay-Event-Id") or hashlib.sha256(body).hexdigest()
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
            currency=pay.get("currency", ""),
            raw={"event": etype},
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
    if not config["key_id"].startswith(("rzp_test_", "rzp_live_")):
        raise GatewayError("Expected a Razorpay test or live key ID.")
    client = razorpay.Client(auth=(config["key_id"], config["key_secret"]), session=TimeoutSession())
    client.order.all({"count": 1})
    mode = "TEST mode" if config["key_id"].startswith("rzp_test") else "LIVE mode"
    return True, f"Razorpay keys accepted ({mode})."
