import csv
import io
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.forms import inlineformset_factory
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from PIL import Image

from apps.catalog.models import Brand, Category, Product, ProductImage, ProductVariant
from apps.core import audit
from apps.core.images import reencode
from apps.core.templatetags.rasiko import ILLUSTRATIONS
from apps.inventory.models import StockMovement
from apps.inventory.services import OutOfStock, adjust_stock
from apps.notifications import services as notify
from apps.promotions.models import HeroSlide

from ..permissions import can, dash
from .orders import _safe

R = StockMovement.Reason


def _style(form):
    for f in form.fields.values():
        if not isinstance(f.widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
            f.widget.attrs.setdefault("class", "input")


# ---- Products ---------------------------------------------------------------------------------------------------


class ProductForm(forms.ModelForm):
    nutrition_text = forms.CharField(
        required=False,
        label="Nutrition",
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="One per line, like: Energy: 45 kcal",
    )

    class Meta:
        model = Product
        fields = [
            "name",
            "name_gu",
            "name_hi",
            "slug",
            "brand",
            "categories",
            "short_description",
            "description",
            "diet",
            "ingredients",
            "allergens",
            "shelf_life",
            "storage_instructions",
            "best_before_note",
            "country_of_origin",
            "tags",
            "illustration",
            "illustration_color",
            "is_active",
            "is_featured",
            "is_bestseller",
            "is_new",
            "seo_title",
            "seo_description",
        ]
        widgets = {
            "categories": forms.CheckboxSelectMultiple,
            "description": forms.Textarea(attrs={"rows": 4}),
            "ingredients": forms.Textarea(attrs={"rows": 2}),
            "seo_description": forms.Textarea(attrs={"rows": 2}),
            "illustration": forms.Select(choices=[(k, k.title()) for k in ILLUSTRATIONS]),
            "illustration_color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields["slug"].required = False
        self.fields["categories"].queryset = Category.objects.order_by("sort_order", "name")
        if self.instance.pk and self.instance.nutrition:
            self.fields["nutrition_text"].initial = "\n".join(f"{k}: {v}" for k, v in self.instance.nutrition.items())
        _style(self)

    def clean_slug(self):
        slug = self.cleaned_data.get("slug") or slugify(self.cleaned_data.get("name", ""))[:140]
        if Product.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
            raise ValidationError("Another product already uses this web address.")
        return slug

    def save(self, commit=True):
        obj = super().save(commit=False)
        nutrition = {}
        for line in self.cleaned_data.get("nutrition_text", "").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                if k.strip():
                    nutrition[k.strip()[:40]] = v.strip()[:40]
        obj.nutrition = nutrition
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class VariantForm(forms.ModelForm):
    add_stock = forms.IntegerField(
        required=False,
        label="Add stock in bottles (+/-)",
        help_text="Count bottles, e.g. 2 boxes of 24 = 48. Changes are logged in stock movements.",
    )

    class Meta:
        model = ProductVariant
        fields = [
            "label",
            "units_per_box",
            "sku",
            "barcode",
            "mrp",
            "price",
            "cost_price",
            "gst_rate",
            "hsn_code",
            "volume_ml",
            "low_stock_threshold",
            "max_per_order",
            "manual_out_of_stock",
            "is_active",
            "sort_order",
        ]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _style(self)
        self.fields["cost_price"].help_text = "Cost of one box. Only managers and owners see profit."
        self.fields["price"].help_text = "What the customer pays for one whole box."
        self.fields["units_per_box"].min_value = 2
        self.fields["units_per_box"].widget.attrs["min"] = 2
        self.fields["units_per_box"].initial = None
        self.fields["volume_ml"].required = True
        self.fields["volume_ml"].min_value = 1
        self.fields["volume_ml"].label = "Volume of one bottle (ml)"
        self.fields["units_per_box"].help_text = "Customers buy whole boxes only. Stock below is counted in bottles."

    def clean(self):
        data = super().clean()
        if data.get("units_per_box") is not None and data["units_per_box"] < 2:
            self.add_error("units_per_box", "Enter at least 2 bottles per box; individual bottles are not sold.")
        if data.get("volume_ml") is not None and data["volume_ml"] < 1:
            self.add_error("volume_ml", "Enter the volume of one bottle in ml.")
        mrp, price = data.get("mrp"), data.get("price")
        if mrp is not None and price is not None and price > mrp:
            raise ValidationError("Selling price can't be more than MRP.")
        add = data.get("add_stock") or 0
        if add < 0 and (self.instance.stock_qty or 0) + add < 0:
            self.add_error("add_stock", f"Only {self.instance.stock_qty or 0} in stock; can't remove {-add}.")
        return data


VariantFormSet = inlineformset_factory(Product, ProductVariant, form=VariantForm, extra=1, can_delete=False)


@dash("staff")
def product_list(request):
    qs = Product.objects.select_related("brand").prefetch_related("variants", "images").order_by("name")
    state = request.GET.get("state", "live")
    qs = qs.filter(deleted_at__isnull=state != "deleted")
    if state == "hidden":
        qs = qs.filter(is_active=False)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(variants__sku__icontains=q) | Q(brand__name__icontains=q)).distinct()
    if request.GET.get("category"):
        qs = qs.filter(categories=request.GET["category"])
    if request.GET.get("brand"):
        qs = qs.filter(brand=request.GET["brand"])
    if request.method == "POST":
        return _bulk_action(request)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(
        request,
        "dashboard/products.html",
        {
            "page": page,
            "q": q,
            "state": state,
            "categories": Category.objects.order_by("name"),
            "brands": Brand.objects.order_by("name"),
            "not_boxed": ProductVariant.objects.filter(
                units_per_box=1, is_active=True, product__deleted_at__isnull=True
            ).count(),
        },
    )


def _bulk_action(request):
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    action = request.POST.get("action")
    qs = Product.objects.filter(pk__in=ids)
    updates = {
        "activate": {"is_active": True},
        "deactivate": {"is_active": False},
        "feature": {"is_featured": True},
        "unfeature": {"is_featured": False},
        "bestseller": {"is_bestseller": True},
        "delete": {"deleted_at": timezone.now(), "is_active": False},
        "restore": {"deleted_at": None},
    }.get(action)
    if not ids or updates is None:
        messages.error(request, "Pick at least one product and an action.")
    elif action == "delete" and not can(request.user, "manager"):
        messages.error(request, "Only a manager or owner can remove products.")
    else:
        n = qs.update(**updates)
        audit.log(request, f"product.bulk_{action}", None, f"{n} products: {action}", {"ids": ids})
        if action == "delete":
            notify.admin_event("product_removed", {"products": ", ".join(qs.values_list("name", flat=True)[:20])})
        messages.success(request, f"Updated {n} product(s).")
    return redirect(request.get_full_path())


@dash("staff")
def product_edit(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else None
    form = ProductForm(request.POST or None, instance=product)
    formset = VariantFormSet(request.POST or None, instance=product or Product(), prefix="v")
    if not can(request.user, "manager"):
        for f in formset.forms + [formset.empty_form]:
            f.fields.pop("cost_price", None)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            saved = form.save()
            price_changes = []
            for vf in formset.forms:
                if not vf.has_changed() and vf.instance.pk:
                    continue
                if not vf.instance.pk and not vf.has_changed():
                    continue
                v = vf.save(commit=False)
                v.product = saved
                if v.pk and "price" in vf.changed_data:
                    old = vf.initial.get("price")
                    new = v.price
                    v.price = old
                    v.set_price(new)
                    price_changes.append(f"{v.label}: ₹{old} → ₹{new}")
                v.save()
                delta = vf.cleaned_data.get("add_stock") or 0
                if delta:
                    adjust_stock(
                        v.pk, delta, R.MANUAL if pk else R.INITIAL, user=request.user, note="From product editor"
                    )
            _save_images(request, saved)
        audit.log(
            request,
            "product.update" if product else "product.create",
            saved,
            saved.name,
            {k: str(form.cleaned_data.get(k))[:80] for k in form.changed_data},
        )
        notify.admin_event("product_updated" if product else "product_added", {"product": saved.name})
        if price_changes:
            notify.admin_event("price_changed", {"product": saved.name, "changes": "; ".join(price_changes)})
        messages.success(request, f"Saved “{saved.name}”.")
        return redirect("dashboard:product_edit", saved.pk)
    return render(
        request,
        "dashboard/product_form.html",
        {
            "form": form,
            "formset": formset,
            "product": product,
            "images": product.images.all() if product else [],
        },
    )


def _save_images(request, product):
    order = request.POST.get("image_order", "")
    if order:
        for i, pid in enumerate(x for x in order.split(",") if x.isdigit()):
            ProductImage.objects.filter(pk=int(pid), product=product).update(sort_order=i)
    for key, val in request.POST.items():
        if key.startswith("alt_") and key[4:].isdigit():
            ProductImage.objects.filter(pk=int(key[4:]), product=product).update(alt=val[:120])
    for pid in request.POST.getlist("delete_image"):
        if pid.isdigit():
            ProductImage.objects.filter(pk=int(pid), product=product).delete()
    start = product.images.count()
    for i, f in enumerate(request.FILES.getlist("new_images")[:8]):
        try:
            processed = reencode(f, max_side=1400)
        except ValidationError as exc:
            messages.error(request, f"{f.name}: {exc.messages[0]}")
            continue
        img = ProductImage(product=product, alt=product.name, sort_order=start + i)
        img.image.save(processed.name, processed, save=True)


# ---- Quick stock ------------------------------------------------------------------------------------------------


def _stock_qs(request):
    qs = (
        ProductVariant.objects.select_related("product", "product__brand")
        .filter(product__deleted_at__isnull=True)
        .order_by("product__name", "sort_order")
    )
    f = request.GET.get("filter", "")
    if f == "out":
        qs = qs.filter(Q(stock_qty__lte=F("reserved_qty")) | Q(manual_out_of_stock=True))
    elif f == "low":
        qs = qs.filter(stock_qty__lte=F("reserved_qty") + F("low_stock_threshold"), stock_qty__gt=F("reserved_qty"))
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(product__name__icontains=q) | Q(sku__icontains=q) | Q(barcode=q))
    if request.GET.get("category"):
        qs = qs.filter(product__categories=request.GET["category"])
    return qs


@dash("staff")
def stock(request):
    page = Paginator(_stock_qs(request), 60).get_page(request.GET.get("page"))
    return render(
        request,
        "dashboard/stock.html",
        {
            "page": page,
            "filter": request.GET.get("filter", ""),
            "q": request.GET.get("q", ""),
            "categories": Category.objects.order_by("name"),
            "reasons": [(R.MANUAL, "Recount"), (R.DAMAGE, "Damaged / expired")],
        },
    )


@dash("staff")
@require_POST
def stock_update(request, pk):
    """HTMX: toggle out-of-stock / active, or set a counted quantity. Returns the refreshed row."""
    v = get_object_or_404(ProductVariant.objects.select_related("product"), pk=pk)
    action = request.POST.get("action")
    error = ""
    if action == "toggle_oos":
        v.manual_out_of_stock = not v.manual_out_of_stock
        v.save(update_fields=["manual_out_of_stock", "updated_at"])
        audit.log(request, "stock.toggle", v, f"{v}: {'out of stock' if v.manual_out_of_stock else 'back in stock'}")
        if not v.manual_out_of_stock:
            from apps.inventory.tasks import send_back_in_stock

            transaction.on_commit(lambda: send_back_in_stock.delay(v.pk))
    elif action == "toggle_active":
        v.is_active = not v.is_active
        v.save(update_fields=["is_active", "updated_at"])
    elif action == "set_qty":
        try:
            qty = int(request.POST.get("qty", ""))
            if qty < 0:
                raise ValueError
            reason = request.POST.get("reason") if request.POST.get("reason") in (R.MANUAL, R.DAMAGE) else R.MANUAL
            with transaction.atomic():
                v = adjust_stock(v.pk, 0, reason, user=request.user, set_to=qty, note="Quick stock")
        except (ValueError, OutOfStock):
            error = "Enter a whole number, 0 or more."
    v.refresh_from_db()
    return render(request, "dashboard/_stock_row.html", {"v": v, "error": error, "saved": not error})


@dash("staff")
def movements(request):
    qs = StockMovement.objects.select_related("variant__product", "user", "order").order_by("-created_at")
    if request.GET.get("variant"):
        qs = qs.filter(variant_id=request.GET["variant"])
    return render(request, "dashboard/movements.html", {"page": Paginator(qs, 60).get_page(request.GET.get("page"))})


# ---- CSV import / export ----------------------------------------------------------------------------------------

CSV_COLUMNS = [
    "sku",
    "product_name",
    "brand",
    "categories",
    "variant_label",
    "units_per_box",
    "volume_ml",
    "mrp",
    "price",
    "cost_price",
    "gst_rate",
    "hsn_code",
    "stock_qty",
    "low_stock_threshold",
    "max_per_order",
    "is_active",
    "diet",
    "illustration",
    "short_description",
]


@dash("manager")
def products_export(request):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="rasiko-products.csv"'
    resp.write("﻿")  # Excel opens UTF-8 correctly with a BOM
    w = csv.writer(resp)
    w.writerow(CSV_COLUMNS)
    for v in (
        ProductVariant.objects.select_related("product__brand")
        .prefetch_related("product__categories")
        .filter(product__deleted_at__isnull=True)
        .order_by("product__name", "sort_order")
    ):
        p = v.product
        w.writerow(
            [
                _safe(x)
                for x in [
                    v.sku,
                    p.name,
                    p.brand.name,
                    "|".join(c.slug for c in p.categories.all()),
                    v.label,
                    v.units_per_box,
                    v.volume_ml,
                    v.mrp,
                    v.price,
                    v.cost_price,
                    v.gst_rate,
                    v.hsn_code,
                    v.stock_qty,
                    v.low_stock_threshold,
                    v.max_per_order,
                    "yes" if (v.is_active and p.is_active) else "no",
                    p.diet,
                    p.illustration,
                    p.short_description,
                ]
            ]
        )
    return resp


def _dec(row, key, errors, line, required=True):
    raw = (row.get(key) or "").strip()
    if not raw and not required:
        return None
    try:
        val = Decimal(raw)
        if val < 0:
            raise InvalidOperation
        return val
    except InvalidOperation:
        errors.append(f"Line {line}: {key} must be a number (got “{raw[:20]}”).")
        return None


@dash("manager")
def products_import(request):
    report = None
    if request.method == "POST" and request.FILES.get("file"):
        f = request.FILES["file"]
        if f.size > 2 * 1024 * 1024:
            messages.error(request, "The file is bigger than 2 MB. Split it into smaller files.")
            return redirect("dashboard:products_import")
        text = f.read().decode("utf-8-sig", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
        errors, parsed = [], []
        missing = [
            c
            for c in ("sku", "product_name", "brand", "variant_label", "mrp", "price")
            if c not in (rows[0].keys() if rows else [])
        ]
        if missing:
            errors.append("Missing columns: " + ", ".join(missing))
        for i, row in enumerate(rows[:5000] if not missing else [], start=2):
            sku = (row.get("sku") or "").strip()[:40]
            if not sku:
                errors.append(f"Line {i}: sku is empty.")
                continue
            mrp, price = _dec(row, "mrp", errors, i), _dec(row, "price", errors, i)
            if mrp is not None and price is not None and price > mrp:
                errors.append(f"Line {i}: price is more than MRP.")
            for field, minimum in (("units_per_box", 2), ("volume_ml", 1)):
                value = (row.get(field) or "").strip()
                if not value.isdigit() or int(value) < minimum:
                    errors.append(f"Line {i}: {field} must be a whole number of at least {minimum}.")
            qty = (row.get("stock_qty") or "").strip()
            if qty and not qty.isdigit():
                errors.append(f"Line {i}: stock_qty must be a whole number.")
            parsed.append((i, sku, row, mrp, price))
        dry = request.POST.get("dry_run") == "1"
        created = updated = 0
        if not errors and not dry:
            with transaction.atomic():
                for i, sku, row, mrp, price in parsed:
                    c, u = _import_row(request, sku, row, mrp, price, errors, i)
                    created += c
                    updated += u
                if errors:
                    transaction.set_rollback(True)
                    created = updated = 0
        report = {"rows": len(parsed), "errors": errors[:100], "created": created, "updated": updated, "dry": dry}
        if not errors and not dry:
            audit.log(request, "product.import", None, f"CSV import: {created} new, {updated} updated")
            messages.success(request, f"Imported: {created} new variants, {updated} updated.")
    return render(request, "dashboard/products_import.html", {"report": report, "columns": CSV_COLUMNS})


def _import_row(request, sku, row, mrp, price, errors, line):
    name = row["product_name"].strip()[:120]
    brand, _ = Brand.objects.get_or_create(
        name=row["brand"].strip()[:80] or "Other", defaults={"slug": slugify(row["brand"])[:90] or "other"}
    )
    v = ProductVariant.objects.select_related("product").filter(sku=sku).first()
    product = v.product if v else Product.objects.filter(name=name, brand=brand).first()
    if product is None:
        slug = slugify(name)[:130] or sku.lower()
        if Product.objects.filter(slug=slug).exists():
            slug = f"{slug}-{slugify(sku)}"[:140]
        product = Product.objects.create(name=name, slug=slug, brand=brand)
    product.short_description = (row.get("short_description") or product.short_description)[:200]
    if row.get("diet") in ("veg", "nonveg"):
        product.diet = row["diet"]
    if row.get("illustration") in ILLUSTRATIONS:
        product.illustration = row["illustration"]
    product.save()
    if row.get("categories"):
        cats = Category.objects.filter(slug__in=[s.strip() for s in row["categories"].split("|")])
        product.categories.set(cats)
    active = (row.get("is_active") or "yes").strip().lower() in ("yes", "y", "1", "true")
    fields = {"label": (row.get("variant_label") or "").strip()[:40], "mrp": mrp, "is_active": active}
    for key in ("cost_price", "gst_rate"):
        val = _dec(row, key, errors, line, required=False)
        if val is not None:
            fields[key] = val
    for key in ("units_per_box", "volume_ml", "low_stock_threshold", "max_per_order"):
        if (row.get(key) or "").strip().isdigit():
            fields[key] = int(row[key])
    if (row.get("hsn_code") or "").strip():
        fields["hsn_code"] = row["hsn_code"].strip()[:8]
    created = v is None
    if created:
        v = ProductVariant(product=product, sku=sku, price=price, **fields)
    else:
        for k, val in fields.items():
            setattr(v, k, val)
        v.set_price(price)
    v.save()
    qty = (row.get("stock_qty") or "").strip()
    if qty.isdigit() and int(qty) != v.stock_qty:
        adjust_stock(v.pk, 0, R.IMPORT, user=request.user, set_to=int(qty), note="CSV import")
    return (1, 0) if created else (0, 1)


# ---- Hero slider ------------------------------------------------------------------------------------------------


class HeroForm(forms.ModelForm):
    class Meta:
        model = HeroSlide
        fields = [
            "heading",
            "heading_accent",
            "subtext",
            "badge",
            "button_text",
            "button_link",
            "image",
            "mobile_image",
            "fit",
            "focal_x",
            "focal_y",
            "art",
            "theme",
            "starts_at",
            "ends_at",
            "is_active",
        ]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "focal_x": forms.NumberInput(attrs={"type": "range", "min": 0, "max": 100}),
            "focal_y": forms.NumberInput(attrs={"type": "range", "min": 0, "max": 100}),
            "image": forms.ClearableFileInput(attrs={"accept": "image/*", "data-preview": "desktop"}),
            "mobile_image": forms.ClearableFileInput(attrs={"accept": "image/*", "data-preview": "mobile"}),
        }

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        _style(self)

    def clean_button_link(self):
        link = self.cleaned_data["button_link"].strip()
        if not (link.startswith("/") and not link.startswith("//")) and not link.startswith("https://"):
            raise ValidationError("Use a link on this site (starting with /) or a full https:// address.")
        return link


def _process_slide_image(upload):
    """WebP, max 2400 px, plus size and average colour for a blurred placeholder."""
    out = reencode(upload, max_side=2400, quality=80)
    img = Image.open(io.BytesIO(out.read()))
    out.seek(0)
    r, g, b = img.convert("RGB").resize((1, 1), Image.LANCZOS).getpixel((0, 0))
    return out, img.width, img.height, f"#{r:02X}{g:02X}{b:02X}"


@dash("manager")
def hero(request):
    if request.method == "POST" and request.POST.get("order"):
        for i, pk in enumerate(p for p in request.POST["order"].split(",") if p.isdigit()):
            HeroSlide.objects.filter(pk=int(pk)).update(sort_order=i)
        return JsonResponse({"ok": True})
    return render(request, "dashboard/hero.html", {"slides": HeroSlide.objects.all()})


@dash("manager")
def hero_edit(request, pk=None):
    slide = get_object_or_404(HeroSlide, pk=pk) if pk else None
    form = HeroForm(request.POST or None, request.FILES or None, instance=slide)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        try:
            if "image" in request.FILES:
                f, w, h, color = _process_slide_image(request.FILES["image"])
                obj.image.save(f.name, f, save=False)
                obj.image_width, obj.image_height, obj.blur_color = w, h, color
            if "mobile_image" in request.FILES:
                f, *_ = _process_slide_image(request.FILES["mobile_image"])
                obj.mobile_image.save(f.name, f, save=False)
        except ValidationError as exc:
            form.add_error(None, exc.messages[0])
        if not form.errors:
            if not obj.pk:
                obj.sort_order = HeroSlide.objects.count()
            obj.save()
            audit.log(request, "hero.save", obj, obj.heading)
            messages.success(request, "Slide saved.")
            return redirect("dashboard:hero")
    return render(request, "dashboard/hero_form.html", {"form": form, "slide": slide})


@dash("manager")
@require_POST
def hero_delete(request, pk):
    slide = get_object_or_404(HeroSlide, pk=pk)
    audit.log(request, "hero.delete", slide, slide.heading)
    slide.delete()
    messages.success(request, "Slide deleted.")
    return redirect("dashboard:hero")
