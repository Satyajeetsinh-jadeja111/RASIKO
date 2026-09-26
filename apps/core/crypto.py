"""Symmetric encryption for secrets stored in the database (integration keys, SMTP password)."""

import base64
import hashlib
import json
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    key = settings.FIELD_ENCRYPTION_KEY
    if not key:
        if not settings.DEBUG:
            raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be set outside DEBUG.")
        # Dev only: derive a stable key from SECRET_KEY so local setups just work.
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_str(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt_str(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        logger.error("Could not decrypt a stored secret; was FIELD_ENCRYPTION_KEY changed?")
        return ""


def encrypt_json(data: dict) -> str:
    return encrypt_str(json.dumps(data or {}))


def decrypt_json(token: str) -> dict:
    raw = decrypt_str(token)
    return json.loads(raw) if raw else {}


def mask(value: str) -> str:
    if not value:
        return ""
    return "•••• " + value[-4:] if len(value) > 6 else "••••"
