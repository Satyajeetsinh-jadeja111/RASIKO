import csv
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.catalog.models import Product, ProductVariant
from apps.core import audit
from apps.inventory.services import adjust_stock

from .access import require_team

REQUIRED = {"name", "source_language", "sku", "label", "units_per_box", "volume_ml", "price", "mrp", "stock_bottles"}


@transaction.atomic
def import_products(actor, team, upload):
    """Add-only import; never overwrite another seller's globally unique SKU."""
    require_team(actor, team)
    try:
        reader = csv.DictReader(io.StringIO(upload.read().decode("utf-8-sig")))
        if not REQUIRED.issubset(set(reader.fieldnames or [])):
            raise ValidationError("CSV is missing required columns.")
        count = 0
        for index, row in enumerate(reader, 2):
            if index > 1001:
                raise ValidationError("Import at most 1000 rows at a time.")
            language = row["source_language"].strip()
            units, volume, bottles = int(row["units_per_box"]), int(row["volume_ml"]), int(row["stock_bottles"])
            if language not in ("en", "hi", "gu") or units < 2 or volume <= 0 or bottles < 0:
                raise ValidationError(f"Invalid language or box/stock quantity at row {index}.")
            if ProductVariant.objects.filter(sku=row["sku"].strip()).exists():
                raise ValidationError(f"SKU at row {index} is unavailable. Use the stock editor for existing products.")
            product = Product(name=row["name"].strip(), source_language=language, brand=team.brand, seller_team=team)
            product.full_clean(exclude=["slug"])
            product.save()
            variant = ProductVariant(
                product=product,
                sku=row["sku"].strip(),
                label=row["label"].strip(),
                units_per_box=units,
                volume_ml=volume,
                price=Decimal(row["price"]),
                mrp=Decimal(row["mrp"]),
                cost_price=Decimal(row.get("cost_price") or "0"),
            )
            variant.full_clean()
            variant.save()
            if bottles:
                adjust_stock(variant.pk, bottles, "import", user=actor, note="Seller CSV import")
            count += 1
    except (UnicodeDecodeError, ValueError, InvalidOperation, csv.Error) as exc:
        raise ValidationError("Use UTF-8 CSV with valid numbers and the documented columns.") from exc
    audit.log(None, "marketplace.products.imported", team, summary=f"{count} variants", user=actor)
    return count
