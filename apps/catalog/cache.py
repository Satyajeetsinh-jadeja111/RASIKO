"""Public catalog fragments only; never store request/cart/customer state here."""

from django.core.cache import cache
from django.db import transaction

KEYS = ("catalog_home", "menu_categories", "footer_pages", "current_campaign")


def invalidate_catalog():
    cache.delete_many(KEYS)
    # Invalidate again after commit to discard reads made during an open transaction.
    transaction.on_commit(lambda: cache.delete_many(KEYS))


def public_fragment(key, loader, ttl=30):
    value = cache.get(key)
    if value is None:
        value = loader()
        cache.set(key, value, ttl)
    return value
