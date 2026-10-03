"""Tiny cache-backed fixed-window rate limiter used on login, OTP, checkout, chat, reviews and coupons."""

import functools

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse

from .audit import client_ip


def hit(key: str, limit: int, window: int) -> bool:
    """Record one hit; return True when the caller is over the limit."""
    if not getattr(settings, "RATELIMIT_ENABLED", True):
        return False
    full = f"rl:{key}"
    added = cache.add(full, 1, window)
    if added:
        return False
    try:
        count = cache.incr(full)
    except ValueError:
        cache.set(full, 1, window)
        return False
    return count > limit


def ratelimit(scope: str, limit: int = 10, window: int = 60, methods=("POST",)):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method in methods:
                who = request.user.pk if request.user.is_authenticated else client_ip(request)
                if hit(f"{scope}:{who}", limit, window):
                    msg = "Too many attempts. Please wait a minute and try again."
                    if request.headers.get("Accept", "").startswith("application/json"):
                        return JsonResponse({"error": msg}, status=429)
                    return HttpResponse(msg, status=429)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
