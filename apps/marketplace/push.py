"""FCM HTTP v1. Service-account secrets stay in the encrypted integration store."""

import base64
import json
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from apps.core.integrations import get_config


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=")


def send(device, offer):
    config = get_config("rider_push")
    if not config:
        return False
    account = json.loads(config["service_account"])
    now = int(time.time())
    header = encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claim = encode(
        json.dumps(
            {
                "iss": account["client_email"],
                "scope": "https://www.googleapis.com/auth/firebase.messaging",
                "aud": "https://oauth2.googleapis.com/token",
                "iat": now,
                "exp": now + 3600,
            }
        ).encode()
    )
    unsigned = header + b"." + claim
    key = serialization.load_pem_private_key(account["private_key"].encode(), password=None)
    assertion = (unsigned + b"." + encode(key.sign(unsigned, padding.PKCS1v15(), hashes.SHA256()))).decode()
    auth = requests.post(
        "https://oauth2.googleapis.com/token",
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        timeout=10,
    )
    auth.raise_for_status()
    project = account["project_id"]
    if not project or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in project):
        raise ValueError("Invalid Firebase project")
    response = requests.post(
        f"https://fcm.googleapis.com/v1/projects/{project}/messages:send",
        headers={"Authorization": f"Bearer {auth.json()['access_token']}"},
        json={
            "message": {
                "token": device.token,
                "notification": {
                    "title": "Rasiko delivery available",
                    "body": "Open Rasiko Rider to accept this delivery.",
                },
                "data": {"offer_id": str(offer.pk)},
                "android": {
                    "priority": "high",
                    "ttl": "45s",
                    "notification": {"channel_id": "delivery_offers", "sound": "delivery_offer"},
                },
                "apns": {
                    "headers": {"apns-expiration": str(int(offer.expires_at.timestamp()))},
                    "payload": {"aps": {"sound": "delivery_offer.wav"}},
                },
            }
        },
        timeout=10,
    )
    if response.status_code == 404:
        device.active = False
        device.save(update_fields=["active"])
        return False
    response.raise_for_status()
    return True
