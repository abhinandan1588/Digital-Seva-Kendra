"""Admin payment verification queue. Manual verification only in v1; the
structure is gateway-ready (see models/payment.py gateway_reference)."""
from flask import render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from . import admin_bp
from ..extensions import db
from ..models import Order, Payment, UploadedDocument, StatusHistory
from ..utils.status import set_payment_status, set_order_status, set_application_status
from ..utils.audit import log_admin_action
from ..notifications.service import event_payment_verified, event_payment_rejected
from ..utils.i18n import t


@admin_bp.route("/payments")
@login_required
def payments_queue():
    status_filter = (request.args.get("status") or "pending_verification").strip()
    page = request.args.get("page", 1, type=int)
    query = Payment.query
    if status_filter != "all":
        query = query.filter(Payment.status == status_filter)
    pagination = query.order_by(Payment.updated_at.desc()).paginate(
        page=page, per_page=20, error_out=False)
    return render_template("admin/payments_queue.html", pagination=pagination,
                           status_filter=status_filter)


@admin_bp.route("/payments/<int:payment_id>")
@login_required
def payment_review(payment_id):
    payment = db.session.get(Payment, payment_id) or abort(404)
    screenshot = payment.screenshot
    history = (StatusHistory.query.filter_by(payment_id=payment.id)
               .order_by(StatusHistory.created_at.desc()).all())
    return render_template("admin/payment_review.html", payment=payment,
                           screenshot=screenshot, history=history)


def _verify_common(payment):
    if payment.status == "verified":
        flash("Payment is already verified.", "warning")
        return False
    return True


@admin_bp.route("/payments/<int:payment_id>/approve", methods=["POST"])
@login_required
def payment_approve(payment_id):
    payment = db.session.get(Payment, payment_id) or abort(404)
    if not _verify_common(payment):
        return redirect(url_for("admin.payment_review", payment_id=payment.id))

    from datetime import datetime, timezone
    previous = payment.status
    payment.verified_by_admin_id = current_user.id
    payment.verified_at = datetime.now(timezone.utc)
    set_payment_status(payment, "verified",
                       customer_remark=t("Payment verified. Your applications will be processed now.",
                                         "भुगतान सत्यापित हो गया। आपके आवेदन अब प्रक्रिया में लाए जाएँगे।"),
                       admin=current_user)
    order = payment.order
    payment.order.payment_status = "verified"
    if order.status in ("submitted", "awaiting_payment", "payment_verification"):
        set_order_status(order, "confirmed",
                         customer_remark=t("Payment confirmed. Processing started.",
                                           "भुगतान पुष्ट हुआ। प्रक्रिया शुरू हो गई है।"),
                         admin=current_user)
    # Applications move to payment_verified
    for app in order.applications:
        if app.status in ("submitted", "awaiting_payment"):
            set_application_status(app, "payment_verified",
                                   customer_remark=None, admin=current_user)
    db.session.commit()
    event_payment_verified(order)
    log_admin_action(current_user, "payment_approved", "payment", payment.id,
                     {"order": order.order_number, "from": previous})
    db.session.commit()
    flash("Payment approved. Customer notified on their tracking page.", "success")
    return redirect(url_for("admin.payment_review", payment_id=payment.id))


@admin_bp.route("/payments/<int:payment_id>/reject", methods=["POST"])
@login_required
def payment_reject(payment_id):
    payment = db.session.get(Payment, payment_id) or abort(404)
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("A rejection reason is mandatory.", "danger")
        return redirect(url_for("admin.payment_review", payment_id=payment.id))
    if payment.status == "verified":
        flash("Verified payments cannot be rejected here.", "danger")
        return redirect(url_for("admin.payment_review", payment_id=payment.id))

    previous = payment.status
    payment.rejection_reason = reason
    payment.verified_by_admin_id = current_user.id
    set_payment_status(payment, "rejected",
                       customer_remark=reason, admin=current_user)
    set_order_status(payment.order, "awaiting_payment",
                     customer_remark=t("Payment rejected. Please submit correct payment proof.",
                                       "भुगतान अस्वीकृत। कृपया सही भुगतान प्रमाण जमा करें।"),
                     admin=current_user)
    payment.order.payment_status = "rejected"
    db.session.commit()
    event_payment_rejected(payment.order, reason)
    log_admin_action(current_user, "payment_rejected", "payment", payment.id,
                     {"order": payment.order.order_number, "from": previous, "reason": reason})
    db.session.commit()
    flash("Payment rejected with reason. Customer can resubmit.", "warning")
    return redirect(url_for("admin.payment_review", payment_id=payment.id))


@admin_bp.route("/payments/<int:payment_id>/request-proof", methods=["POST"])
@login_required
def payment_request_proof(payment_id):
    """Ask the customer for corrected payment proof (soft rejection)."""
    payment = db.session.get(Payment, payment_id) or abort(404)
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("Please describe what is wrong with the proof.", "danger")
        return redirect(url_for("admin.payment_review", payment_id=payment.id))
    payment.rejection_reason = reason
    set_payment_status(payment, "pending_verification",
                       customer_remark=t("Please submit a corrected payment proof: ",
                                         "कृपया संशोधित भुगतान प्रमाण जमा करें: ") + reason,
                       admin=current_user)
    payment.order.payment_status = "pending_verification"
    db.session.commit()
    log_admin_action(current_user, "payment_proof_requested", "payment", payment.id,
                     {"order": payment.order.order_number})
    db.session.commit()
    flash("Customer asked for corrected payment proof.", "success")
    return redirect(url_for("admin.payment_review", payment_id=payment.id))
