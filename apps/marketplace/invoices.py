"""Immutable seller invoice snapshots and PDFs; supplier configuration is mandatory."""

import io
import re
from decimal import Decimal
from html import escape

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.orders.invoice import _fonts
from apps.orders.models import Order

from .checkout import allocate
from .models import Fulfillment, InvoiceSequence, Seller, SellerInvoice


@transaction.atomic
def issue(fulfillment):
    Order.objects.select_for_update(of=("self",)).get(pk=fulfillment.order_id)
    f = (
        Fulfillment.objects.select_for_update(of=("self",))
        .select_related("team__seller", "territory", "order")
        .get(pk=fulfillment.pk)
    )
    existing = SellerInvoice.objects.filter(fulfillment=f).first()
    if existing:
        return existing
    if f.status == "cancelled" or (
        f.order.payment_method != "cod" and f.order.payment_status not in ("paid", "partial_refund", "refunded")
    ):
        raise ValidationError("An unpaid or cancelled fulfillment cannot receive a new invoice.")
    seller = Seller.objects.select_for_update(of=("self",)).get(pk=f.team.seller_id)
    if not seller.legal_name or not seller.business_address or not seller.state_code or not seller.signatory:
        raise ValidationError(
            "Complete seller legal name, address, state code and authorized signatory before issuing an invoice."
        )
    if seller.tax_registration in ("regular", "composition") and not seller.gstin:
        raise ValidationError("GST registration details are required for this seller's invoice type.")
    if seller.gstin and seller.gstin[:2] != seller.state_code:
        raise ValidationError("Seller GSTIN and state code must match.")
    if not f.territory:
        raise ValidationError("Place of supply must be configured before invoicing.")
    # Pincodes are canonical service areas; invoice place-of-supply code is explicit.
    destination_code = f.territory.state_code
    if not destination_code:
        raise ValidationError("Configure the delivery territory's GST state code before invoicing.")
    today = timezone.localdate()
    start = today.year if today.month >= 4 else today.year - 1
    fiscal = f"{start % 100:02}{(start + 1) % 100:02}"
    sequence, _ = InvoiceSequence.objects.get_or_create(seller=seller, fiscal_year=fiscal)
    sequence = InvoiceSequence.objects.select_for_update(of=("self",)).get(pk=sequence.pk)
    if sequence.next_number > 999999:
        raise ValidationError("Invoice sequence exhausted for this financial year.")
    number = f"{seller.invoice_prefix}/{fiscal}/{sequence.next_number:06}"
    sequence.next_number += 1
    sequence.save(update_fields=["next_number"])
    rows = list(f.lines.select_related("order_line"))
    weights = {r.pk: r.order_line.line_total for r in rows}
    discounts = allocate(f.discount, weights)
    coins = allocate(f.coins_value, weights)
    gst = allocate(f.tax, weights) if seller.tax_registration == "regular" else {key: Decimal("0") for key in weights}
    items = []
    for row in rows:
        line = row.order_line
        amount = line.line_total - discounts[row.pk] - coins[row.pk]
        items.append(
            {
                "name": line.product_name,
                "label": line.variant_label,
                "hsn": line.hsn_code,
                "quantity": line.qty,
                "unit_price": str(line.unit_price),
                "discount": str(discounts[row.pk]),
                "coins": str(coins[row.pk]),
                "taxable": str(amount - gst[row.pk]),
                "rate": str(line.gst_rate),
                "tax": str(gst[row.pk]),
                "amount": str(amount),
            }
        )
    data = {
        "seller": {
            "name": seller.legal_name,
            "address": seller.business_address,
            "state": seller.state_code,
            "gstin": seller.gstin,
            "fssai": seller.fssai_number,
            "phone": seller.business_phone,
            "signatory": seller.signatory,
        },
        "buyer": {"name": f.order.ship_name, "address": f.order.ship_address, "pincode": f.order.ship_pincode},
        "kind": "Tax invoice" if seller.tax_registration == "regular" else "Bill of supply",
        "issued_on": today.isoformat(),
        "place_of_supply": destination_code,
        "interstate": destination_code != seller.state_code,
        "items": items,
        "subtotal": str(f.subtotal),
        "discount": str(f.discount),
        "coins": str(f.coins_value),
        "delivery": str(f.delivery_fee),
        "total": str(f.total),
        "tax": str(sum(gst.values(), Decimal("0"))),
        "order": f.order.number,
        "payment": f.order.payment_method,
    }
    return SellerInvoice.objects.create(fulfillment=f, number=number, fiscal_year=fiscal, snapshot=data)


def pdf(invoice):
    _fonts()
    for name in ("NotoSansDevanagari", "NotoSansGujarati"):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(settings.BASE_DIR / "static/fonts/pdf" / (name + ".ttf"))))
    data = invoice.snapshot
    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=invoice.number,
    )
    body = ParagraphStyle("body", fontName="Dejavu", fontSize=8, leading=12, shaping=1)
    heading = ParagraphStyle(
        "heading", parent=body, fontName="Dejavu-Bold", fontSize=19, leading=24, textColor=colors.HexColor("#245843")
    )

    def p(value, style=body):
        text = escape(str(value)).replace("\n", "<br/>")
        for pattern, font in [(r"[\u0900-\u097f]+", "NotoSansDevanagari"), (r"[\u0a80-\u0aff]+", "NotoSansGujarati")]:
            text = re.sub(pattern, lambda match, font=font: f'<font name="{font}">{match.group(0)}</font>', text)
        return Paragraph(text, style)

    def rs(value):
        return f"INR {Decimal(value):,.2f}"

    seller = data["seller"]
    flow = [
        p(data["kind"], heading),
        p(f"{invoice.number} | {data['issued_on']} | Order {data['order']}"),
        Spacer(1, 6 * mm),
        p(seller["name"], heading),
        p(seller["address"]),
        p(f"GSTIN: {seller['gstin'] or 'Not registered'} | FSSAI: {seller['fssai'] or 'Not supplied'}"),
        p(f"Supplier state: {seller['state']} | Place of supply: {data['place_of_supply']}"),
        Spacer(1, 5 * mm),
        p("Billed / shipped to"),
        p(data["buyer"]["name"]),
        p(data["buyer"]["address"]),
        Spacer(1, 6 * mm),
    ]
    rows = [[p(x) for x in ["Item / HSN", "Qty", "Box price", "Discount", "Taxable", "Tax", "Amount"]]]
    for item in data["items"]:
        rows.append(
            [
                p(f"{item['name']}\n{item['label']}\nHSN {item['hsn']}"),
                p(item["quantity"]),
                p(rs(item["unit_price"])),
                p(rs(item["discount"])),
                p(rs(item["taxable"])),
                p(f"{item['rate']}%\n{rs(item['tax'])}"),
                p(rs(item["amount"])),
            ]
        )
    table = Table(rows, colWidths=[49 * mm, 12 * mm, 23 * mm, 23 * mm, 24 * mm, 23 * mm, 24 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fff0cc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    flow += [table, Spacer(1, 6 * mm)]
    tax = Decimal(data["tax"])
    if data["kind"] == "Tax invoice":
        if data["interstate"]:
            flow.append(p(f"IGST included: {rs(tax)}"))
        else:
            cgst = (tax / 2).quantize(Decimal("0.01"))
            flow.append(p(f"CGST included: {rs(cgst)} | SGST included: {rs(tax - cgst)}"))
    flow += [
        p(f"Delivery: {rs(data['delivery'])} | Rasiko Coins applied: {rs(data['coins'])}"),
        p(f"Amount payable: {rs(data['total'])}", heading),
        Spacer(1, 8 * mm),
        p(f"Authorized signatory: {seller['signatory']}"),
        p(
            "Issued by the seller through Rasiko. Platform fees and seller settlement deductions do not change this customer bill."
        ),
    ]
    doc.build(flow)
    return out.getvalue()
