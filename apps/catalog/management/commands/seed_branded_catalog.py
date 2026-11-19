"""Install the explicitly opted-in starter catalog from bundled product photographs."""

import hashlib
import json
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.cache import invalidate_catalog
from apps.catalog.models import Brand, Category, Product, ProductImage, ProductVariant
from apps.core.images import reencode
from apps.core.management.commands.seed_demo import BRANDS, PRODUCTS
from apps.inventory.models import StockMovement
from apps.promotions.models import Combo


class Command(BaseCommand):
    help = "Install real-brand starter products/photos with explicitly acknowledged demo prices."

    def add_arguments(self, parser):
        parser.add_argument("--acknowledge-demo-prices", action="store_true")
        parser.add_argument("--replace-fictional-demo", action="store_true")
        parser.add_argument(
            "--configure-demo-boxes", action="store_true", help="Apply demo box sizes/prices; preserve bottle stock."
        )

    def handle(self, *args, **options):
        if not options["acknowledge_demo_prices"]:
            raise CommandError("Pass --acknowledge-demo-prices; prices, stock, taxes and case sizes need owner review.")
        root = settings.BASE_DIR / "assets" / "starter-catalog"
        rows = json.loads((root / "catalog.json").read_text())
        # Validate all bundled files and categories before touching catalog state.
        photos = {}
        for row in rows:
            path = root / row["image"]
            with path.open("rb") as source:
                photos[row["slug"]] = reencode(ContentFile(source.read(), name=path.name), max_side=900)
        cats = {c.slug: c for c in Category.objects.filter(slug__in={r["category"] for r in rows})}
        if len(cats) != len({r["category"] for r in rows}):
            raise CommandError("Create the starter categories first (seed_demo on a fresh demo database).")
        created_count = 0
        with transaction.atomic():
            if options["replace_fictional_demo"]:
                old = Product.objects.filter(name__in=[r[0] for r in PRODUCTS], brand__name__in=BRANDS)
                old_ids = list(old.values_list("pk", flat=True))
                old.update(is_active=False)
                ProductVariant.objects.filter(product_id__in=old_ids).update(is_active=False)
                Combo.objects.filter(items__variant__product_id__in=old_ids).update(is_active=False)
                for brand in Brand.objects.filter(name__in=BRANDS):
                    if not brand.products.filter(is_active=True).exists():
                        brand.is_active = False
                        brand.save(update_fields=["is_active"])
            for index, row in enumerate(rows):
                brand, _ = Brand.objects.get_or_create(name=row["brand"])
                product, created = Product.objects.get_or_create(
                    slug=row["slug"],
                    defaults={
                        "name": row["name"],
                        "is_active": row["is_active"],
                        "brand": brand,
                        "short_description": "Starter catalog · demo price. Confirm stock and price before launch.",
                        "description": "Check the supplied pack for ingredients, allergens, nutrition and storage instructions."
                        + (" " + row["photo_note"] if row["photo_note"] else "")
                        + (
                            " Jar deposit/return arrangements require owner confirmation."
                            if row["volume_ml"] >= 5000
                            else ""
                        ),
                        "attributes": {"starter_catalog": True, "demo_pricing": True},
                        "is_featured": index < 10 or row["brand"] == "Bailley",
                        "is_new": True,
                        "country_of_origin": "",
                    },
                )
                if created:
                    product.categories.add(cats[row["category"]])
                    ml = row["volume_ml"]
                    label = f"{ml} ml" if ml < 1000 else f"{ml / 1000:g} L"
                    variant = ProductVariant.objects.create(
                        product=product,
                        label=label,
                        sku="STARTER-" + hashlib.sha256(row["slug"].encode()).hexdigest()[:16].upper(),
                        volume_ml=ml,
                        units_per_box=row["units_per_box"],
                        is_active=row["is_active"],
                        price=Decimal(row["price"]),
                        mrp=Decimal(row["price"]),
                        gst_rate=Decimal("0"),
                        hsn_code="",
                        stock_qty=60,
                    )
                    StockMovement.objects.create(
                        variant=variant, delta=60, balance_after=60, reason=StockMovement.Reason.INITIAL
                    )
                    created_count += 1
                if options["configure_demo_boxes"] and product.attributes.get("starter_catalog"):
                    product.is_active = row["is_active"]
                    product.save(update_fields=["is_active"])
                    product.variants.filter(sku__startswith="STARTER-").update(
                        units_per_box=row["units_per_box"],
                        price=Decimal(row["price"]),
                        mrp=Decimal(row["price"]),
                        is_active=row["is_active"],
                    )
                # Ordinary reruns preserve owner-edited prices, stock and photographs.
                if not product.images.exists():
                    alt = (
                        "Bailley Soda range: 300 ml, 600 ml and 750 ml"
                        if row["category"] == "soda-masala" and row["brand"] == "Bailley"
                        else row["name"]
                    )
                    ProductImage.objects.create(product=product, image=photos[row["slug"]], alt=alt)
            invalidate_catalog()
        self.stdout.write(self.style.SUCCESS(f"Created {created_count}; starter catalog has {len(rows)} products."))
