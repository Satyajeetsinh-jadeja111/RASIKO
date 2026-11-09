"""Source-preserving cached translation via optional Google Cloud Translation."""

import hashlib
import json
import re

import requests
from celery import shared_task
from django.utils.translation import get_language

from apps.core.integrations import get_config

from .models import MarketplaceSettings, ProductTranslation

FIELDS = (
    "name",
    "short_description",
    "description",
    "ingredients",
    "allergens",
    "storage_instructions",
    "best_before_note",
)


def protect(text, brand):
    replacements = {}

    def substitute(match):
        marker = f"__RASIKO_{len(replacements)}__"
        replacements[marker] = match.group(0)
        return marker

    pattern = re.compile(re.escape(brand) + r"|[0-9]+(?:[.,][0-9]+)*(?:\s*(?:ml|kg|mg|g|L|l|%))?", re.IGNORECASE)
    return pattern.sub(substitute, text), replacements


def restore(text, replacements):
    for marker, original in replacements.items():
        if text.count(marker) != 1:
            raise ValueError("Translation changed a protected identifier")
        text = text.replace(marker, original)
    return text


def source_content(product):
    return {field: getattr(product, field) for field in FIELDS}


def source_hash(product):
    return hashlib.sha256(
        json.dumps([product.source_language, source_content(product)], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def localized(product, field):
    language = (get_language() or "en")[:2]
    if language == product.source_language:
        return getattr(product, field)
    row = product.translations.filter(language=language, source_hash=source_hash(product), status="ready").first()
    if row and row.content.get(field):
        return row.content[field]
    if field == "name" and language in ("hi", "gu"):
        return getattr(product, f"name_{language}") or product.name
    return getattr(product, field)


@shared_task
def translate_product(product_id):
    from apps.catalog.models import Product

    product = Product.objects.get(pk=product_id)
    if not MarketplaceSettings.load().translations_enabled:
        return
    config = get_config("google_translate")
    digest, content = source_hash(product), source_content(product)
    fields = [field for field in FIELDS if content[field]]
    protected = {field: protect(content[field], product.brand.name) for field in fields}
    for language in {"en", "hi", "gu"} - {product.source_language}:
        row, _ = ProductTranslation.objects.get_or_create(
            product=product, language=language, defaults={"source_hash": digest}
        )
        if row.source_hash == digest and row.status == "ready":
            continue
        row.source_hash, row.status, row.corrected = digest, "pending", False
        row.content = {}
        if not config:
            row.status = "failed"
            row.save()
            continue
        try:
            response = requests.post(
                "https://translation.googleapis.com/language/translate/v2",
                headers={"X-Goog-Api-Key": config["api_key"]},
                json={
                    "q": [protected[f][0] for f in fields],
                    "source": product.source_language,
                    "target": language,
                    "format": "text",
                },
                timeout=15,
            )
            response.raise_for_status()
            values = response.json()["data"]["translations"]
            if len(values) != len(fields):
                raise ValueError("Translation count mismatch")
            import html

            row.content = {
                field: restore(html.unescape(value["translatedText"]), protected[field][1])
                for field, value in zip(fields, values, strict=True)
            }
            # Ingredients/allergens remain original until reviewed by a seller/admin.
            row.status = "review" if content["ingredients"] or content["allergens"] else "ready"
        except (requests.RequestException, KeyError, ValueError):
            row.status = "failed"
        if source_hash(Product.objects.get(pk=product_id)) == digest:
            row.save()
