"""A small generic list / create / edit / delete for the simple dashboard tables.

Each entry says which model, which fields the form shows, which columns the list shows and who may use it.
Every save and delete is written to the audit log.
"""

from dataclasses import dataclass, field

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import models as dj_models
from django.db.models import ProtectedError, Q
from django.forms import inlineformset_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.catalog.models import Brand, Category
from apps.core import audit
from apps.core.images import reencode
from apps.core.models import Page
from apps.delivery.models import FeeSlab, Holiday, Rider, ServicePincode
from apps.promotions.models import BulkPriceSlab, Campaign, Combo, ComboItem, Coupon
from apps.support.models import FaqArticle

from .permissions import can


@dataclass
class Crud:
    model: type
    title: str
    singular: str
    fields: list
    columns: list
    role: str = "manager"
    search: list = field(default_factory=list)
    ordering: tuple = ()
    widgets: dict = field(default_factory=dict)
    help: str = ""
    inline: tuple | None = None  # (model, fk_name, fields)
    image_fields: tuple = ()
    back: str = ""  # url name to return to after save (defaults to the list)
    can_delete: bool = True


DATE = forms.DateInput(attrs={"type": "date"})
DT = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
TEXT = forms.Textarea(attrs={"rows": 3})
LONG = forms.Textarea(attrs={"rows": 12})
COLOR = forms.TextInput(attrs={"type": "color"})

REGISTRY: dict[str, Crud] = {
    "categories": Crud(
        Category,
        "Categories",
        "category",
        [
            "name",
            "name_gu",
            "name_hi",
            "slug",
            "parent",
            "tile_color",
            "icon",
            "image",
            "sort_order",
            "is_active",
            "show_in_menu",
            "seo_title",
            "seo_description",
        ],
        ["name", "parent", "sort_order", "is_active", "show_in_menu"],
        search=["name", "slug"],
        ordering=("sort_order", "name"),
        widgets={"tile_color": COLOR, "seo_description": TEXT},
        image_fields=("image",),
    ),
    "brands": Crud(
        Brand,
        "Brands",
        "brand",
        ["name", "slug", "logo", "description", "is_active"],
        ["name", "slug", "is_active"],
        search=["name"],
        ordering=("name",),
        widgets={"description": TEXT},
        image_fields=("logo",),
    ),
    "coupons": Crud(
        Coupon,
        "Coupons",
        "coupon",
        [
            "code",
            "description",
            "kind",
            "value",
            "max_discount",
            "min_order",
            "starts_at",
            "expires_at",
            "usage_limit",
            "per_user_limit",
            "first_order_only",
            "is_active",
            "show_on_home",
        ],
        ["code", "kind", "value", "min_order", "expires_at", "is_active", "show_on_home"],
        search=["code", "description"],
        ordering=("-created_at",),
        widgets={"starts_at": DT, "expires_at": DT},
        help="Coupons are checked again on the server at checkout. Personal Thandu coupons are made automatically.",
    ),
    "campaigns": Crud(
        Campaign,
        "Festival campaigns",
        "campaign",
        [
            "name",
            "theme",
            "starts_at",
            "ends_at",
            "show_overlay",
            "banner_title",
            "banner_text",
            "coupon",
            "bonus_coins",
            "is_active",
        ],
        ["name", "theme", "starts_at", "ends_at", "is_active"],
        ordering=("-starts_at",),
        widgets={"starts_at": DT, "ends_at": DT, "banner_text": TEXT},
        help="Themes: Diwali, Navratri, Uttarayan, Holi and summer. The toran and banner show only between the dates.",
    ),
    "combos": Crud(
        Combo,
        "Combos",
        "combo",
        ["name", "description", "price", "is_active", "show_on_home"],
        ["name", "price", "is_active", "show_on_home"],
        ordering=("name",),
        widgets={"description": TEXT},
        inline=(ComboItem, "combo", ["variant", "qty"]),
    ),
    "bulk-prices": Crud(
        BulkPriceSlab,
        "Bulk price slabs",
        "bulk price slab",
        ["variant", "min_qty", "unit_price"],
        ["variant", "min_qty", "unit_price"],
        ordering=("variant__product__name", "min_qty"),
        search=["variant__product__name", "variant__sku"],
    ),
    "faq": Crud(
        FaqArticle,
        "Help articles",
        "help article",
        ["topic", "question", "answer", "keywords", "is_published", "sort_order"],
        ["question", "topic", "is_published"],
        search=["question", "answer"],
        ordering=("topic", "sort_order"),
        widgets={"answer": LONG},
        help="The help chat answers from these articles, so keep them short and exact.",
    ),
    "pages": Crud(
        Page,
        "Pages",
        "page",
        ["title", "slug", "body", "show_in_footer", "sort_order"],
        ["title", "slug", "show_in_footer"],
        ordering=("sort_order",),
        widgets={"body": LONG},
        help="Plain text. Blank lines start a new paragraph.",
    ),
    "fee-slabs": Crud(
        FeeSlab,
        "Delivery fee slabs",
        "fee slab",
        ["min_km", "max_km", "fee"],
        ["min_km", "max_km", "fee"],
        ordering=("min_km",),
        back="dashboard:delivery_settings",
    ),
    "pincodes": Crud(
        ServicePincode,
        "Pincodes",
        "pincode",
        ["code", "area", "is_active", "fast_delivery", "cod_blocked"],
        ["code", "area", "is_active", "fast_delivery", "cod_blocked"],
        search=["code", "area"],
        ordering=("code",),
        back="dashboard:delivery_settings",
    ),
    "holidays": Crud(
        Holiday,
        "Holidays",
        "holiday",
        ["date", "note"],
        ["date", "note"],
        ordering=("date",),
        widgets={"date": DATE},
        back="dashboard:delivery_settings",
    ),
    "riders": Crud(
        Rider,
        "Riders",
        "rider",
        ["name", "phone", "is_active"],
        ["name", "phone", "is_active"],
        role="manager",
        ordering=("name",),
        back="dashboard:delivery_settings",
    ),
}


def _form_class(cfg: Crud):
    widgets = dict(cfg.widgets)

    class F(forms.ModelForm):
        class Meta:
            model = cfg.model
            fields = cfg.fields

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            for name, f in self.fields.items():
                if name in widgets:
                    f.widget = widgets[name]
                if not isinstance(f.widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                    f.widget.attrs.setdefault("class", "input")

        def clean(self):
            data = super().clean()
            for name in cfg.image_fields:
                f = self.files.get(name)
                if f:
                    data[name] = reencode(f)
            return data

    return F


def _get(slug, user):
    cfg = REGISTRY.get(slug)
    if cfg is None:
        raise Http404
    if not can(user, cfg.role):
        raise PermissionDenied
    return cfg


def cell(obj, name):
    value = getattr(obj, name)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    display = getattr(obj, f"get_{name}_display", None)
    if display:
        return display()
    return "" if value is None else value


def crud_list(request, slug):
    cfg = _get(slug, request.user)
    qs = cfg.model.objects.all()
    if cfg.ordering:
        qs = qs.order_by(*cfg.ordering)
    q = request.GET.get("q", "").strip()
    if q and cfg.search:
        cond = Q()
        for s in cfg.search:
            cond |= Q(**{f"{s}__icontains": q})
        qs = qs.filter(cond)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    headers = [cfg.model._meta.get_field(c).verbose_name for c in cfg.columns]
    rows = [(o, [cell(o, c) for c in cfg.columns]) for o in page]
    return render(
        request,
        "dashboard/crud_list.html",
        {"cfg": cfg, "slug": slug, "page": page, "rows": rows, "headers": headers, "q": q},
    )


def crud_edit(request, slug, pk=None):
    cfg = _get(slug, request.user)
    obj = get_object_or_404(cfg.model, pk=pk) if pk else None
    Form = _form_class(cfg)
    form = Form(request.POST or None, request.FILES or None, instance=obj)
    formset = None
    if cfg.inline:
        model, fk, fields = cfg.inline
        FS = inlineformset_factory(cfg.model, model, fk_name=fk, fields=fields, extra=2, can_delete=True)
        formset = FS(request.POST or None, instance=obj or cfg.model())
        for f in formset.forms:
            for fld in f.fields.values():
                if not isinstance(fld.widget, forms.CheckboxInput):
                    fld.widget.attrs.setdefault("class", "input")
    if request.method == "POST" and form.is_valid() and (formset is None or formset.is_valid()):
        changes = {k: str(form.cleaned_data.get(k))[:80] for k in form.changed_data}
        saved = form.save()
        if formset is not None:
            formset.instance = saved
            formset.save()
        audit.log(request, f"{slug}.{'update' if obj else 'create'}", saved, str(saved), changes)
        messages.success(request, f"Saved {cfg.singular} “{saved}”.")
        return redirect(reverse(cfg.back) if cfg.back else reverse("dashboard:crud_list", args=[slug]))
    return render(
        request, "dashboard/crud_form.html", {"cfg": cfg, "slug": slug, "form": form, "formset": formset, "obj": obj}
    )


def crud_delete(request, slug, pk):
    cfg = _get(slug, request.user)
    obj = get_object_or_404(cfg.model, pk=pk)
    if request.method == "POST" and cfg.can_delete:
        label = str(obj)
        try:
            obj.delete()
        except ProtectedError:
            messages.error(request, f"“{label}” is used by orders, so it can't be deleted. Switch it off instead.")
            return redirect("dashboard:crud_edit", slug, pk)
        audit.log(request, f"{slug}.delete", None, label)
        messages.success(request, f"Deleted “{label}”.")
    return redirect(reverse(cfg.back) if cfg.back else reverse("dashboard:crud_list", args=[slug]))


_ = dj_models  # keep import for type hints in editors
