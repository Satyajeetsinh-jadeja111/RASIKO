"""GST tax invoice PDF (ReportLab). Prices include GST; tax is split into CGST + SGST for Gujarat."""

import io
from decimal import Decimal
from html import escape as esc

from django.conf import settings
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.models import StoreSettings

KAJAL = colors.HexColor("#3E2723")
MAROON = colors.HexColor("#7A1F2B")
CHANDAN = colors.HexColor("#FFF4E0")
TULSI_DEEP = colors.HexColor("#1B6E42")
LINE = colors.HexColor("#F3E3CC")

_fonts_ready = False


def _fonts():
    global _fonts_ready
    if not _fonts_ready:
        base = settings.BASE_DIR / "static" / "fonts" / "pdf"
        pdfmetrics.registerFont(TTFont("Dejavu", str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("Dejavu-Bold", str(base / "DejaVuSans-Bold.ttf")))
        _fonts_ready = True


def rs(x):
    return f"₹{Decimal(x):,.2f}"


def invoice_pdf(order) -> bytes:
    _fonts()
    store = StoreSettings.load()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Invoice {order.number}",
        author=store.name,
    )
    body = ParagraphStyle("b", fontName="Dejavu", fontSize=9, leading=12, textColor=KAJAL)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10)
    h = ParagraphStyle("h", parent=body, fontName="Dejavu-Bold", fontSize=16, leading=20, textColor=MAROON)
    bold = ParagraphStyle("bb", parent=body, fontName="Dejavu-Bold")

    logo = settings.BASE_DIR / "static" / "brand" / "rasiko-icon-512.png"
    head_left = [
        Paragraph(esc(store.legal_name), h),
        Paragraph(esc(store.address).replace("\n", "<br/>"), body),
        Paragraph(esc(f"GSTIN: {store.gstin} · FSSAI Lic. No.: {store.fssai_number}"), small),
        Paragraph(esc(f"Phone: {store.phone} · {store.email}"), small),
    ]
    header = Table(
        [
            [
                Image(str(logo), 18 * mm, 18 * mm),
                head_left,
                [
                    Paragraph("TAX INVOICE", h),
                    Paragraph(f"Invoice no: <b>{order.number}</b>", body),
                    Paragraph(f"Date: {timezone.localtime(order.placed_at or order.created_at):%d %b %Y}", body),
                    Paragraph(f"Payment: {order.get_payment_method_display()}", body),
                ],
            ]
        ],
        colWidths=[22 * mm, 92 * mm, 64 * mm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    bill = Table(
        [
            [Paragraph("<b>Bill / ship to</b>", bold)],
            [
                Paragraph(
                    f"{esc(order.ship_name)}<br/>{esc(order.ship_address)}<br/>Phone: {esc(order.ship_phone)}", body
                )
            ],
        ],
        colWidths=[178 * mm],
    )
    bill.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CHANDAN),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    rows = [["Item", "HSN", "Qty", "Rate", "Taxable", "GST %", "CGST", "SGST", "Amount"]]
    tot_taxable = tot_gst = Decimal("0")
    for line in order.lines.all():
        taxable, gst = line.taxable_value, line.gst_amount
        tot_taxable += taxable
        tot_gst += gst
        name = esc(f"{line.product_name} ({line.variant_label})") + (
            f"<br/><font size=7>{esc(line.combo_name)}</font>" if line.combo_name else ""
        )
        rows.append(
            [
                Paragraph(name, small),
                line.hsn_code,
                str(line.qty),
                rs(line.unit_price),
                rs(taxable),
                f"{line.gst_rate.normalize():f}",
                rs(gst / 2),
                rs(gst - gst / 2),
                rs(line.line_total),
            ]
        )
    t = Table(
        rows, colWidths=[52 * mm, 14 * mm, 9 * mm, 17 * mm, 19 * mm, 11 * mm, 17 * mm, 17 * mm, 22 * mm], repeatRows=1
    )
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Dejavu"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, 0), (-1, 0), "Dejavu-Bold"),
                ("TEXTCOLOR", (0, 0), (-1, -1), KAJAL),
                ("BACKGROUND", (0, 0), (-1, 0), CHANDAN),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )

    summary = [["Items total (incl. GST)", rs(order.subtotal)]]
    if order.discount:
        summary.append([f"Coupon {order.coupon_code}", "−" + rs(order.discount)])
    if order.coins_value:
        summary.append([f"Rasiko Coins ({order.coins_used})", "−" + rs(order.coins_value)])
    summary.append(["Delivery fee", rs(order.delivery_fee) if order.delivery_fee else "FREE"])
    if order.small_order_fee:
        summary.append(["Small order fee", rs(order.small_order_fee)])
    for label, amount in order.surcharges:
        summary.append([label, rs(amount)])
    summary.append(["GST included (CGST + SGST)", rs(order.gst_total)])
    summary.append(["Grand total", rs(order.total)])
    if order.refunded_total:
        summary.append(["Refunded", "−" + rs(order.refunded_total)])
    s = Table(summary, colWidths=[60 * mm, 30 * mm], hAlign="RIGHT")
    s.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Dejavu"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, -1), KAJAL),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                (
                    "FONTNAME",
                    (0, -1 if not order.refunded_total else -2),
                    (-1, -1 if not order.refunded_total else -2),
                    "Dejavu-Bold",
                ),
                ("LINEABOVE", (0, -1), (-1, -1), 0.6, MAROON),
            ]
        )
    )
    you_saved = order.savings
    story = [header, Spacer(1, 6 * mm), bill, Spacer(1, 5 * mm), t, Spacer(1, 4 * mm), s, Spacer(1, 4 * mm)]
    if you_saved > 0:
        story.append(Paragraph(f"<font color='#1B6E42'><b>You saved {rs(you_saved)} on this order.</b></font>", body))
    story += [
        Spacer(1, 8 * mm),
        Paragraph(
            f"Taxable value {rs(tot_taxable)} · Total GST on items {rs(tot_gst)} (before discounts). "
            "This is a computer-generated invoice and does not need a signature.",
            small,
        ),
        Paragraph(esc(f"{store.tagline} · {settings.SITE_URL}"), small),
    ]
    doc.build(story)
    return buf.getvalue()
