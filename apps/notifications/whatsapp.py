"""WhatsApp order updates through the Meta Cloud API, only when the Owner has switched it on.

When off, the storefront still shows a free click-to-chat link (StoreSettings.whatsapp_link).
"""

import logging

import requests

from apps.core.integrations import get_config

logger = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v21.0"


def _to(phone):
    digits = "".join(c for c in phone if c.isdigit())
    return "91" + digits if len(digits) == 10 else digits


def send_template(phone, params, config=None):
    cfg = config or get_config("whatsapp")
    if not cfg:
        return False
    payload = {
        "messaging_product": "whatsapp",
        "to": _to(phone),
        "type": "template",
        "template": {
            "name": cfg.get("template_order_update") or "order_update",
            "language": {"code": cfg.get("template_language") or "en"},
            "components": [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}],
        },
    }
    try:
        r = requests.post(
            f"{GRAPH}/{cfg['phone_number_id']}/messages",
            json=payload,
            headers={"Authorization": f"Bearer {cfg['access_token']}"},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception("WhatsApp send failed")
        return False


def send_order_update(order_id):
    from apps.orders.models import Order

    if not get_config("whatsapp"):
        return False
    order = Order.objects.filter(pk=order_id).first()
    if not order:
        return False
    return send_template(order.ship_phone, [order.ship_name, order.number, order.get_status_display()])


def test_connection(config):
    r = requests.get(
        f"{GRAPH}/{config['phone_number_id']}",
        headers={"Authorization": f"Bearer {config['access_token']}"},
        timeout=10,
    )
    if r.ok:
        return True, f"Connected to WhatsApp number {r.json().get('display_phone_number', '')}."
    return False, f"Meta said {r.status_code}: {r.text[:150]}"
