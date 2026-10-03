from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import FIELD_ENCRYPTION_KEY, SECRET_KEY, env

DEBUG = False
if SECRET_KEY.startswith("dev-") or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured("Set a strong DJANGO_SECRET_KEY (50+ characters).")
if not FIELD_ENCRYPTION_KEY:
    raise ImproperlyConfigured("Set FIELD_ENCRYPTION_KEY (a Fernet key).")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
