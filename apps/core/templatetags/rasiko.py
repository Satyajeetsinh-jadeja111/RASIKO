import re
from decimal import Decimal

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _shine(x, y, h):
    return f'<rect x="{x}" y="{y}" width="5" height="{h}" rx="2.5" fill="#FFFFFF" opacity=".45"/>'


def _bottle(body, cap, label="#FFF4E0"):
    return (
        f'<rect x="21" y="2" width="18" height="14" rx="4" fill="{cap}"/>'
        f'<path d="M23 16h14v10c0 6 15 14 15 30v70a10 10 0 0 1-10 10H18A10 10 0 0 1 8 126V56c0-16 15-24 15-30Z" '
        f'fill="{body}"/><rect x="8" y="72" width="44" height="30" fill="{label}"/>' + _shine(14, 50, 20)
    )


def _glass(body, cap, label="#F3E2C3"):
    return (
        f'<rect x="23" y="2" width="14" height="10" rx="3" fill="{cap}"/>'
        f'<path d="M24 12h12v22c0 8 14 12 14 26v66a10 10 0 0 1-10 10H20a10 10 0 0 1-10-10V60c0-14 14-18 14-26Z" '
        f'fill="{body}"/><rect x="10" y="76" width="40" height="26" fill="{label}"/>' + _shine(15, 58, 14)
    )


def _can(body, band="#FFF4E0", top="#F3E2C3"):
    return (
        f'<rect x="10" y="18" width="40" height="10" rx="5" fill="{top}"/>'
        f'<rect x="8" y="24" width="44" height="104" rx="9" fill="{body}"/>'
        f'<rect x="8" y="62" width="44" height="26" fill="{band}"/>' + _shine(14, 34, 80)
    )


def _lassi(body="#FFF9EE", rim="#F4B400"):
    return (
        '<rect x="33" y="8" width="5" height="50" rx="2.5" fill="#E53935" transform="rotate(12 35 30)"/>'
        f'<path d="M8 42h44l-6 86a8 8 0 0 1-8 7H22a8 8 0 0 1-8-7Z" fill="{body}" stroke="#F3E2C3" stroke-width="2"/>'
        f'<path d="M9 42h42l-1 12H10Z" fill="{rim}"/>'
        '<circle cx="22" cy="80" r="3" fill="#FB8C00" opacity=".7"/><circle cx="36" cy="96" r="2.5" fill="#2FA05A" opacity=".6"/>'
        + _shine(15, 60, 50)
    )


def _cup(body="#B71C2C", tea="#8A5A00"):
    return (
        '<path d="M22 36c-4-8 4-12 0-20M32 36c-4-8 4-12 0-20" fill="none" stroke="#FB8C00" stroke-width="3" '
        'stroke-linecap="round" opacity=".7"/>'
        f'<path d="M6 50h40v44a20 20 0 0 1-20 20h0A20 20 0 0 1 6 94Z" fill="{body}"/>'
        f'<path d="M46 60h4a8 8 0 0 1 0 16h-4" fill="none" stroke="{body}" stroke-width="5"/>'
        f'<ellipse cx="26" cy="51" rx="19" ry="4" fill="{tea}"/><rect x="2" y="116" width="48" height="8" rx="4" fill="#F3E2C3"/>'
    )


PRESETS = {
    "mango": lambda c: _bottle("#F4B400", "#2FA05A"),
    "cola": lambda c: _bottle("#E53935", "#1B6E42"),
    "lemon": lambda c: _can("#2FA05A", "#FFF4E0"),
    "soda": lambda c: _glass("#7A1F2B", "#1B6E42"),
    "kesar": lambda c: _bottle("#FFE3A3", "#E53935", "#FFFFFF"),
    "energy": lambda c: _can("#FB8C00", "#F4B400", "#FDE7E4"),
    "water": lambda c: _bottle("#DDF3E4", "#2FA05A", "#FFFFFF"),
    "lassi": lambda c: _lassi(),
    "kokum": lambda c: _glass("#B71C2C", "#F4B400", "#FDE7E4"),
    "chaas": lambda c: _bottle("#FFF9EE", "#2FA05A", "#EAF7EE"),
    "tea": lambda c: _cup(),
    "bottle": lambda c: _bottle(c, "#1B6E42"),
    "glass": lambda c: _glass(c, "#1B6E42"),
    "can": lambda c: _can(c),
    "cup": lambda c: _cup(c),
}
ILLUSTRATIONS = list(PRESETS)


@register.simple_tag
def drink(kind="bottle", color="#F4B400", css_class=""):
    """Inline SVG drink illustration used until a real photo is uploaded. Palette colours only."""
    color = color if isinstance(color, str) and HEX.match(color) else "#F4B400"
    fn = PRESETS.get(kind, PRESETS["bottle"])
    # Safe: colour is hex-validated, the class is escaped and the SVG paths are constants.
    return mark_safe(  # nosec B308 B703
        f'<svg viewBox="0 0 60 140" class="{escape(css_class)}" aria-hidden="true" focusable="false">{fn(color)}</svg>'
    )  # noqa: S308 - built from constants and a validated hex colour


@register.filter
def rupee(value):
    try:
        d = Decimal(value)
    except Exception:  # noqa: BLE001
        return value
    if d == d.to_integral():
        return f"₹{int(d):,}"
    return f"₹{d:,.2f}"


@register.filter
def star_text(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    full = int(round(v))
    return "★" * full + "☆" * (5 - full)


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Rebuild the current query string with some keys changed (filters, sorting, paging)."""
    q = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            q.pop(k, None)
        else:
            q[k] = v
    q.pop("page", None) if "page" not in kwargs else None
    return "?" + q.urlencode() if q else "?"


@register.simple_tag(takes_context=True)
def nav_current(context, prefix, exact=False):
    path = context["request"].path
    hit = path == prefix if exact else path.startswith(prefix)
    return mark_safe('aria-current="page"') if hit else ""  # nosec B308


@register.filter
def status_chip(status):
    return {
        "delivered": "chip--green",
        "placed": "chip--gold",
        "confirmed": "chip--gold",
        "packed": "chip--orange",
        "out_for_delivery": "chip--orange",
        "cancelled": "chip--red",
        "payment_failed": "chip--red",
        "refunded": "chip--maroon",
        "pending_payment": "",
        "paid": "chip--green",
        "cod_due": "chip--gold",
        "cod_collected": "chip--green",
        "failed": "chip--red",
        "partial_refund": "chip--maroon",
        "succeeded": "chip--green",
        "pending": "chip--gold",
        "approved": "chip--green",
        "hidden": "chip--red",
        "sent": "chip--green",
        "not_sent": "chip--gold",
        "queued": "",
        "open": "chip--gold",
        "closed": "",
    }.get(str(status), "")


@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except AttributeError:
        return None


@register.filter
def mul(a, b):
    try:
        return Decimal(a) * Decimal(b)
    except Exception:  # noqa: BLE001
        return ""


@register.simple_tag
def veg_mark(diet):
    cls = "veg" if diet == "veg" else "veg veg--non"
    label = "Vegetarian" if diet == "veg" else "Non-vegetarian"
    return format_html('<span class="{0}" title="{1}" aria-label="{1}"></span>', cls, label)


@register.filter
def split(value, sep=","):
    return [x.strip() for x in str(value or "").split(sep) if x.strip()][:4]
