"""Order receipt PDF generation (ReportLab)."""
import io
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Image as RLImage, HRFlowable)

from .formatting import inr as _inr_str, fmt_dt
from ..models.order import status_label

ACCENT = colors.HexColor("#1B4B8F")
LIGHT = colors.HexColor("#EEF3FB")


def build_receipt_pdf(order, settings: dict) -> bytes:
    """Generate the order receipt as PDF bytes.

    Shows the real payment status - a pending payment is never 'paid'.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            title=f"Receipt {order.order_number}")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ShopTitle", parent=styles["Title"], fontSize=20,
                                 textColor=ACCENT, spaceAfter=2 * mm, alignment=TA_CENTER)
    sub_style = ParagraphStyle("ShopSub", parent=styles["Normal"], fontSize=9.5,
                               textColor=colors.HexColor("#444444"), alignment=TA_CENTER,
                               leading=13)
    head_style = ParagraphStyle("Head", parent=styles["Heading2"], fontSize=13,
                                textColor=ACCENT, spaceBefore=4 * mm, spaceAfter=2 * mm)
    body = styles["Normal"]
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, leading=11,
                           textColor=colors.HexColor("#555555"))

    story = []

    # Header
    story.append(Paragraph(str(settings.get("shop_name", "Digital Seva Kendra")), title_style))
    story.append(Paragraph(str(settings.get("shop_tagline", "")), sub_style))
    contact_bits = []
    if settings.get("shop_mobile"):
        contact_bits.append(f"Phone: {settings['shop_mobile']}")
    if settings.get("shop_email"):
        contact_bits.append(f"Email: {settings['shop_email']}")
    if settings.get("shop_address"):
        contact_bits.append(str(settings["shop_address"]))
    if contact_bits:
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(contact_bits), sub_style))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT))
    story.append(Spacer(1, 3 * mm))

    # Order meta
    customer = order.customer
    meta_rows = [
        ["Receipt No.:", order.order_number, "Date:", fmt_dt(order.submitted_at)],
        ["Customer:", customer.name if customer else "-", "Mobile:", customer.mobile if customer else "-"],
        ["Payment status:", status_label("payment", order.payment_status),
         "Order status:", status_label("order", order.status)],
    ]
    meta_table = Table(meta_rows, colWidths=[28 * mm, 62 * mm, 26 * mm, 62 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), ACCENT),
        ("TEXTCOLOR", (2, 0), (2, -1), ACCENT),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 5 * mm))

    # Services table
    story.append(Paragraph("Selected Services", head_style))
    rows = [["#", "Service", "Service Charge", "Official Fee", "Other", "Line Total"]]
    for idx, item in enumerate(order.items, start=1):
        rows.append([
            str(idx),
            Paragraph(item.service_name_snapshot, styles["Normal"]),
            _inr_str(item.service_charge_snapshot),
            _inr_str(item.official_fee_snapshot),
            _inr_str(item.other_charge_snapshot),
            _inr_str(item.line_total_snapshot),
        ])
    charges_table = Table(rows, colWidths=[8 * mm, 62 * mm, 26 * mm, 24 * mm, 22 * mm, 30 * mm])
    charges_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(charges_table)
    story.append(Spacer(1, 5 * mm))

    # Totals
    totals_rows = [
        ["Service charges", _inr_str(order.service_charges_total)],
        ["Official fees (passed through)", _inr_str(order.official_fees_total)],
        ["Other charges", _inr_str(order.other_charges_total)],
        ["Total payable", _inr_str(order.total_amount)],
    ]
    totals_table = Table(totals_rows, colWidths=[110 * mm, 62 * mm], hAlign="RIGHT")
    totals_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, 3), (-1, 3), ACCENT),
        ("TEXTCOLOR", (0, 3), (-1, 3), colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (0, 0), (-1, 0), 0.7, ACCENT),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 5 * mm))

    # Payment reference
    payment = order.latest_payment
    if payment and payment.upi_transaction_id:
        story.append(Paragraph(
            f"UPI Transaction ID submitted by customer: <b>{payment.upi_transaction_id}</b> "
            f"(status: {status_label('payment', payment.status)})", body))
        story.append(Spacer(1, 2 * mm))
    if payment and payment.status in ("awaiting_payment", "submitted", "pending_verification"):
        story.append(Paragraph(
            "<b>Note:</b> Payment is not verified yet. This receipt is not a payment success proof.",
            ParagraphStyle("warn", parent=body, textColor=colors.HexColor("#8A6100"))))
        story.append(Spacer(1, 2 * mm))

    # Applications with numbers
    story.append(Paragraph("Applications in this order", head_style))
    for app in order.applications:
        story.append(Paragraph(
            f"{app.application_number} - {app.service_name_snapshot} - "
            f"{status_label('application', app.status)}", body))

    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.7, color=ACCENT))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Important terms & conditions", head_style))
    terms = [
        "Charges shown are this centre's service charges plus official fees, clearly separated.",
        "Payment verification is manual; your applications start processing after verification.",
        "Keep this receipt and your tracking details safe. Track your application on our website "
        "using the order number and tracking token/PIN.",
        "We are a private service centre. We do not claim government affiliation unless explicitly stated.",
    ]
    for term in terms:
        story.append(Paragraph(f"&bull; {term}", small))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(str(settings.get("footer_text", "")), small))

    doc.build(story)
    return buf.getvalue()
