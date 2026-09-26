"""Session cart. Stores only ids and quantities; prices are always read fresh from the database."""

from dataclasses import dataclass
from decimal import Decimal

from apps.catalog.models import ProductVariant
from apps.promotions.models import BulkPriceSlab, Combo

SESSION_KEY = "cart"
MAX_LINES = 60
ZERO = Decimal("0")


@dataclass
class CartLine:
    key: str
    kind: str  # "v" variant | "c" combo
    qty: int
    obj: object
    unit_price: Decimal
    unit_mrp: Decimal
    problem: str = ""

    @property
    def line_total(self):
        return self.unit_price * self.qty

    @property
    def line_mrp(self):
        return self.unit_mrp * self.qty

    @property
    def savings(self):
        return max(ZERO, self.line_mrp - self.line_total)

    @property
    def name(self):
        return self.obj.product.local_name if self.kind == "v" else self.obj.name

    @property
    def label(self):
        return self.obj.label if self.kind == "v" else "Combo"

    @property
    def product(self):
        return self.obj.product if self.kind == "v" else None

    @property
    def max_qty(self):
        if self.kind == "v":
            return max(0, self.obj.max_orderable)
        return 10


class Cart:
    def __init__(self, request):
        self.request = request
        self.session = request.session
        data = self.session.get(SESSION_KEY)
        self.data = data if isinstance(data, dict) else {}

    # ---- mutation --------------------------------------------------------------
    def _save(self):
        self.session[SESSION_KEY] = self.data
        self.session.modified = True
        self._lines = None

    def set(self, key: str, qty: int):
        if not key or key[0] not in "vc" or not key[2:].isdigit():
            return
        qty = max(0, min(int(qty), 99))
        if qty == 0:
            self.data.pop(key, None)
        elif key in self.data or len(self.data) < MAX_LINES:
            self.data[key] = qty
        self._save()

    def add(self, key: str, qty: int = 1):
        self.set(key, self.data.get(key, 0) + int(qty))

    def clear(self):
        self.data = {}
        self.session.pop("coupon_code", None)
        self.session.pop("use_coins", None)
        self._save()

    # ---- reading ---------------------------------------------------------------
    def qty_of(self, key):
        return self.data.get(key, 0)

    @property
    def count(self):
        return sum(self.data.values())

    def lines(self) -> list[CartLine]:
        if getattr(self, "_lines", None) is not None:
            return self._lines
        v_ids = [int(k[2:]) for k in self.data if k.startswith("v:")]
        c_ids = [int(k[2:]) for k in self.data if k.startswith("c:")]
        variants = {
            v.pk: v
            for v in ProductVariant.objects.filter(pk__in=v_ids)
            .select_related("product", "product__brand")
            .prefetch_related("product__images")
        }
        combos = {
            c.pk: c
            for c in Combo.objects.filter(pk__in=c_ids, is_active=True).prefetch_related("items__variant__product")
        }
        slabs = {}
        for s in BulkPriceSlab.objects.filter(variant_id__in=v_ids).order_by("-min_qty"):
            slabs.setdefault(s.variant_id, []).append(s)
        lines, dirty = [], False
        for key, qty in list(self.data.items()):
            kind, pk = key[0], int(key[2:])
            if kind == "v":
                v = variants.get(pk)
                if v is None or not v.is_active or not v.product.is_active or v.product.deleted_at:
                    self.data.pop(key)
                    dirty = True
                    continue
                price = v.price
                for s in slabs.get(pk, []):
                    if qty >= s.min_qty:
                        price = min(price, s.unit_price)
                        break
                problem = ""
                if not v.in_stock:
                    problem = "Out of stock"
                elif qty > v.max_orderable:
                    problem = f"Only {v.max_orderable} available"
                lines.append(CartLine(key, "v", qty, v, price, v.mrp, problem))
            else:
                c = combos.get(pk)
                if c is None:
                    self.data.pop(key)
                    dirty = True
                    continue
                lines.append(CartLine(key, "c", qty, c, c.price, c.mrp_total, "" if c.in_stock else "Out of stock"))
        if dirty:
            self._save()
        self._lines = lines
        return lines

    @property
    def subtotal(self):
        return sum((line.line_total for line in self.lines()), ZERO)

    @property
    def mrp_total(self):
        return sum((line.line_mrp for line in self.lines()), ZERO)

    @property
    def has_problems(self):
        return any(line.problem for line in self.lines())

    def variant_quantities(self):
        """{variant_id: qty} including combo components (used for stock checks)."""
        out = {}
        for line in self.lines():
            if line.kind == "v":
                out[line.obj.pk] = out.get(line.obj.pk, 0) + line.qty
            else:
                for item in line.obj.items.all():
                    out[item.variant_id] = out.get(item.variant_id, 0) + item.qty * line.qty
        return out


class DictCart(Cart):
    """A cart that isn't tied to a session (subscriptions, reorders from tasks)."""

    def __init__(self, data: dict):
        self.request = None
        self.session = {}
        self.data = dict(data)
        self._lines = None

    def _save(self):
        self._lines = None
