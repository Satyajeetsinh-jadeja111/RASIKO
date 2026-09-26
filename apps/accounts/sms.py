"""SMS sending through the owner-configured provider (Integration 'sms'). Email OTP is the fallback."""

import logging

import requests

from apps.core.integrations import get_config

logger = logging.getLogger(__name__)


def _normalise(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def send_sms(phone: str, text: str, otp: str | None = None, config=None) -> bool:
    cfg = config or get_config("sms")
    if not cfg:
        return False
    to = _normalise(phone)
    try:
        if cfg.get("provider") == "twilio":
            sid = cfg["account_sid"]
            r = requests.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                data={"To": "+" + to, "From": cfg["sender_id"], "Body": text},
                auth=(sid, cfg["api_key"]),
                timeout=10,
            )
        else:  # msg91 OTP API with a DLT-approved template
            r = requests.post(
                "https://control.msg91.com/api/v5/otp",
                params={"template_id": cfg.get("template_id", ""), "mobile": to, "otp": otp or ""},
                headers={"authkey": cfg["api_key"]},
                timeout=10,
            )
        r.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception("SMS send failed")
        return False


def test_connection(config):
    if config.get("provider") == "twilio":
        sid = config.get("account_sid", "")
        r = requests.get(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json", auth=(sid, config["api_key"]), timeout=10
        )
        return r.ok, "Twilio account reachable." if r.ok else f"Twilio said {r.status_code}."
    r = requests.get(
        "https://control.msg91.com/api/balance.php", params={"authkey": config["api_key"], "type": "4"}, timeout=10
    )
    return r.ok, "MSG91 key accepted." if r.ok else f"MSG91 said {r.status_code}."
