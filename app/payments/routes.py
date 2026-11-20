"""Payment page: dynamic UPI QR per order, proof submission (UTR + screenshot).

Uploading a screenshot NEVER auto-verifies payment - it only moves the
payment to 'pending_verification' for the shop owner to approve manually.
"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, send_file, abort, current_app)

from ..extensions import db, limiter
from ..models import Order, Payment, UploadedDocument
from ..utils.order_ids import verify_tracking
from ..utils.payments import build_upi_intent, generate_qr_png
from ..utils.settings import get_setting
from ..utils.i18n import t
from ..utils.files import validate_upload
from ..utils.dynamic_forms import stage_files
from ..storage.documents import upload_document_record
from ..notifications.service import event_payment_proof_received

payments_bp = Blueprint("payments", __name__, url_prefix="/pay")

PROOF_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}


def _load_order_for_payment(order_number: str, token: str) -> Order | None:
    order = Order.query.filter_by(order_number=order_number).first()
    if not order or not verify_tracking(order_number, token, order):
        return None
    return order


@payments_bp.route("/<order_number>")
def pay(order_number):
    token = request.args.get("token", "")
    order = _load_order_for_payment(order_number, token)
    if order is None:
        abort(404)

    payment = order.latest_payment
    upi_id = get_setting("upi_id")
    merchant = get_setting("upi_merchant_name") or get_setting("shop_name")
    intent = build_upi_intent(order.total_amount, upi_id, merchant, order.order_number,
                              note=order.service_names_snapshot[:40])
    qr_path = generate_qr_png(intent, order.order_number)

    return render_template("payments/pay.html", order=order, payment=payment,
                           token=token, upi_id=upi_id,
                           instructions=get_setting("payment_instructions")
                           if request.args.get("lang") != "hi" else get_setting("payment_instructions_hi")
                           or get_setting("payment_instructions"),
                           support_info=get_setting("payment_support_info"),
                           qr_url=url_for("payments.qr_image", order_number=order.order_number,
                                          token=token))


@payments_bp.route("/<order_number>/qr.png")
def qr_image(order_number):
    token = request.args.get("token", "")
    order = _load_order_for_payment(order_number, token)
    if order is None:
        abort(404)
    payment = order.latest_payment
    upi_id = get_setting("upi_id")
    merchant = get_setting("upi_merchant_name") or get_setting("shop_name")
    intent = build_upi_intent(order.total_amount, upi_id, merchant, order.order_number)
    qr_path = generate_qr_png(intent, order.order_number)
    return send_file(qr_path, mimetype="image/png")


@payments_bp.route("/<order_number>/submit", methods=["POST"])
@limiter.limit("10 per hour", methods=["POST"])
def submit_proof(order_number):
    token = request.form.get("token", "")
    order = _load_order_for_payment(order_number, token)
    if order is None:
        abort(404)

    payment = order.latest_payment
    if payment is None:
        abort(404)
    if payment.status == "verified":
        flash(t("Payment for this order is already verified.",
                "इस ऑर्डर का भुगतान पहले ही सत्यापित हो चुका है।"), "info")
        return redirect(url_for("orders.order_status_by_token",
                                order_number=order.order_number, token=token))
    if payment.status == "refunded":
        flash(t("This order was refunded. Please contact the shop.",
                "इस ऑर्डर की धनवापसी हो चुकी है। कृपया दुकान से संपर्क करें।"), "warning")
        return redirect(url_for("payments.pay", order_number=order.order_number, token=token))

    utr = (request.form.get("utr") or "").strip()
    remarks = (request.form.get("remarks") or "").strip()
    screenshot = request.files.get("screenshot")

    errors = []
    if not utr or len(utr) < 8 or len(utr) > 60:
        errors.append(t("Please enter a valid UPI transaction ID (UTR).",
                        "कृपया मान्य UPI ट्रांज़ैक्शन आईडी (UTR) दर्ज करें।"))
    if screenshot is None or not screenshot.filename:
        errors.append(t("Please attach the payment screenshot.",
                        "कृपया भुगतान का स्क्रीनशॉट संलग्न करें।"))
    else:
        ok, err = validate_upload(screenshot.stream, screenshot.filename,
                                  PROOF_EXTENSIONS,
                                  current_app.config["UPLOAD_DEFAULT_MAX_MB"])
        if not ok:
            errors.append(t("Payment screenshot must be JPG/PNG/PDF under the size limit.",
                            "भुगतान स्क्रीनशॉट JPG/PNG/PDF होना चाहिए और आकार सीमा के भीतर।"))
    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("payments.pay", order_number=order.order_number, token=token))

    # Stage + upload to the order's Payment_Proof folder.
    screenshot.stream.seek(0)
    staged = stage_files([(screenshot, None)], "Payment Screenshot")[0]
    doc = upload_document_record(order, staged, payment=payment, purpose="payment_proof")

    payment.upi_transaction_id = utr
    payment.amount_submitted = order.total_amount  # customer pays the exact amount
    payment.customer_remarks = remarks or None
    payment.screenshot_document_id = doc.id
    from ..utils.status import set_payment_status, set_order_status
    new_status = "pending_verification" if doc.upload_status == "uploaded" else "submitted"
    set_payment_status(payment, new_status,
                       customer_remark=t("Payment proof received. Verification usually completes within a few hours.",
                                         "भुगतान प्रमाण प्राप्त हुआ। सत्यापन आमतौर पर कुछ घंटों में पूरा हो जाता है।"))
    order.payment_status = new_status
    set_order_status(order, "payment_verification")
    db.session.commit()

    event_payment_proof_received(order)
    if doc.upload_status == "pending":
        flash(t("Payment details saved. The screenshot is queued for secure upload - the shop can still see your UTR.",
                "भुगतान विवरण सुरक्षित कर लिए गए। स्क्रीनशॉट सुरक्षित अपलोड के लिए कतार में है - दुकान आपका UTR देख सकती है।"), "warning")
    flash(t("Payment submitted for verification. Thank you!",
            "भुगतान सत्यापन के लिए जमा कर दिया गया। धन्यवाद!"), "success")
    return redirect(url_for("orders.order_status_by_token",
                            order_number=order.order_number, token=token))
