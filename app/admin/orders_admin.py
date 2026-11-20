"""Admin order & application management with independent status control."""
import io

from flask import (render_template, request, redirect, url_for, flash, abort,
                   send_file, current_app)
from flask_login import login_required, current_user
from sqlalchemy import or_

import os

from . import admin_bp
from ..extensions import db
from ..models import (Order, Application, ApplicationFieldValue, StatusHistory,
                      UploadedDocument, ServiceDocumentRequirement, Service)
from ..models.order import APPLICATION_STATUSES
from ..utils.status import set_order_status, set_application_status
from ..utils.audit import log_admin_action
from ..notifications.service import (event_application_status, event_documents_required)
from ..utils.i18n import t


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------

@admin_bp.route("/orders")
@login_required
def orders_list():
    page = request.args.get("page", 1, type=int)
    q = (request.args.get("q") or "").strip()
    payment_status = (request.args.get("payment_status") or "").strip()
    order_status = (request.args.get("order_status") or "").strip()
    service_id = request.args.get("service_id", type=int)
    date_from = (request.args.get("from") or "").strip()
    date_to = (request.args.get("to") or "").strip()

    query = Order.query
    if q:
        like = f"%{q}%"
        query = query.join(Order.customer).filter(or_(
            Order.order_number.ilike(like),
            Order.customer.has(name__ilike=like),
            Order.customer.has(mobile__ilike=like),
        ))
    if payment_status:
        query = query.filter(Order.payment_status == payment_status)
    if order_status:
        query = query.filter(Order.status == order_status)
    if service_id:
        query = query.join(Order.items).filter(OrderItem_id(service_id))
    if date_from:
        query = query.filter(Order.submitted_at >= _parse_date(date_from))
    if date_to:
        query = query.filter(Order.submitted_at < _parse_date(date_to, end=True))

    pagination = query.order_by(Order.submitted_at.desc()).paginate(
        page=page, per_page=20, error_out=False)
    services = Service.query.order_by(Service.name_en).all()
    return render_template("admin/orders_list.html", pagination=pagination,
                           services=services, q=q,
                           payment_status=payment_status, order_status=order_status,
                           service_id=service_id, date_from=date_from, date_to=date_to)


def OrderItem_id(service_id):
    from ..models import OrderItem
    return OrderItem.service_id == service_id


def _parse_date(value, end=False):
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt + timedelta(days=1) if end else dt


@admin_bp.route("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = db.session.get(Order, order_id) or abort(404)
    history = (StatusHistory.query.filter_by(order_id=order.id)
               .order_by(StatusHistory.created_at.desc()).all())
    payment = order.latest_payment
    screenshot = payment.screenshot if payment else None
    pending_docs = [d for d in order.documents if d.upload_status == "pending"] \
        if hasattr(order, "documents") else []
    from ..models import UploadedDocument as _Doc
    pending_docs = _Doc.query.filter_by(order_id=order.id, upload_status="pending").all()
    return render_template("admin/order_detail.html", order=order, history=history,
                           payment=payment, screenshot=screenshot,
                           pending_docs=pending_docs)


@admin_bp.route("/orders/<int:order_id>/status", methods=["POST"])
@login_required
def order_set_status(order_id):
    order = db.session.get(Order, order_id) or abort(404)
    new_status = request.form.get("status")
    if new_status not in ("submitted", "awaiting_payment", "payment_verification",
                          "confirmed", "partially_completed", "completed", "cancelled"):
        flash("Invalid status.", "danger")
        return redirect(url_for("admin.order_detail", order_id=order.id))
    remark = (request.form.get("customer_remark") or "").strip() or None
    internal = (request.form.get("internal_note") or "").strip() or None
    set_order_status(order, new_status, customer_remark=remark, internal_note=internal,
                     admin=current_user)
    db.session.commit()
    log_admin_action(current_user, "order_status_changed", "order", order.id,
                     {"from": order.status, "to": new_status})
    db.session.commit()
    flash("Order status updated.", "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


@admin_bp.route("/orders/<int:order_id>/receipt.pdf")
@login_required
def receipt_pdf(order_id):
    """Admin-generated/printable receipt PDF."""
    from ..utils.receipts import build_receipt_pdf
    from ..utils.settings import load_all_settings
    order = db.session.get(Order, order_id) or abort(404)
    pdf_bytes = build_receipt_pdf(order, load_all_settings())
    response = send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         download_name=f"receipt-{order.order_number}.pdf")
    response.headers["Content-Disposition"] = f'inline; filename="receipt-{order.order_number}.pdf"'
    log_admin_action(current_user, "receipt_generated", "order", order.id)
    db.session.commit()
    return response


@admin_bp.route("/orders/<int:order_id>/regenerate-tracking", methods=["POST"])
@login_required
def regenerate_tracking(order_id):
    """Show a fresh tracking token once (old hash replaced)."""
    from ..utils.order_ids import generate_tracking_credentials
    order = db.session.get(Order, order_id) or abort(404)
    token, pin, token_hash, pin_hash = generate_tracking_credentials()
    order.tracking_token_hash = token_hash
    order.tracking_pin_hash = pin_hash
    log_admin_action(current_user, "tracking_regenerated", "order", order.id)
    db.session.commit()
    flash("New tracking token generated (shown once): " + token, "success")
    return redirect(url_for("admin.order_detail", order_id=order.id))


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------

@admin_bp.route("/applications")
@login_required
def applications_list():
    page = request.args.get("page", 1, type=int)
    q = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "").strip()
    query = Application.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Application.application_number.ilike(like),
                                 Application.service_name_snapshot.ilike(like)))
    if status:
        query = query.filter(Application.status == status)
    pagination = query.order_by(Application.updated_at.desc()).paginate(
        page=page, per_page=20, error_out=False)
    return render_template("admin/applications_list.html", pagination=pagination,
                           q=q, status=status, statuses=APPLICATION_STATUSES)


@admin_bp.route("/applications/<int:app_id>")
@login_required
def application_detail(app_id):
    application = db.session.get(Application, app_id) or abort(404)
    field_values = ApplicationFieldValue.query.filter_by(application_id=application.id).all()
    documents = (UploadedDocument.query
                 .filter(UploadedDocument.application_id == application.id)
                 .order_by(UploadedDocument.created_at.desc()).all())
    history = (StatusHistory.query.filter_by(application_id=application.id, entity_type="application")
               .order_by(StatusHistory.created_at.desc()).all())
    requirements = []
    if application.service:
        requirements = application.service.active_document_requirements
    return render_template("admin/application_detail.html", application=application,
                           field_values=field_values, documents=documents,
                           history=history, requirements=requirements,
                           statuses=APPLICATION_STATUSES)


@admin_bp.route("/applications/<int:app_id>/status", methods=["POST"])
@login_required
def application_set_status(app_id):
    application = db.session.get(Application, app_id) or abort(404)
    new_status = request.form.get("status")
    if new_status not in APPLICATION_STATUSES:
        flash("Invalid status.", "danger")
        return redirect(url_for("admin.application_detail", app_id=application.id))
    remark = (request.form.get("customer_remark") or "").strip()
    internal = (request.form.get("internal_note") or "").strip() or None
    previous = application.status
    set_application_status(application, new_status, customer_remark=remark or None,
                           internal_note=internal, admin=current_user)
    db.session.commit()
    event_application_status(application.order, application, new_status, remark)
    log_admin_action(current_user, "application_status_changed", "application",
                     application.id, {"from": previous, "to": new_status})
    db.session.commit()
    flash("Application status updated.", "success")
    return redirect(url_for("admin.application_detail", app_id=application.id))


@admin_bp.route("/applications/<int:app_id>/request-documents", methods=["POST"])
@login_required
def request_documents(app_id):
    application = db.session.get(Application, app_id) or abort(404)
    detail = (request.form.get("detail") or "").strip()
    if not detail:
        flash("Please describe which documents are required.", "danger")
        return redirect(url_for("admin.application_detail", app_id=application.id))
    previous = application.status
    set_application_status(application, "documents_required",
                           customer_remark=detail, admin=current_user)
    db.session.commit()
    event_documents_required(application.order, application, detail)
    log_admin_action(current_user, "documents_requested", "application", application.id)
    db.session.commit()
    flash("Document request sent to the customer's tracking page.", "success")
    return redirect(url_for("admin.application_detail", app_id=application.id))


@admin_bp.route("/applications/<int:app_id>/upload-output", methods=["POST"])
@login_required
def upload_output_document(app_id):
    """Upload the completed certificate / acknowledgement for the customer."""
    application = db.session.get(Application, app_id) or abort(404)
    file = request.files.get("output_file")
    label = (request.form.get("label") or "Completed Document").strip()
    if file is None or not file.filename:
        flash("Please choose a file to upload.", "danger")
        return redirect(url_for("admin.application_detail", app_id=application.id))
    from ..utils.files import validate_upload
    ok, err = validate_upload(file.stream, file.filename,
                              current_app.config["ALLOWED_DOCUMENT_EXTENSIONS"],
                              current_app.config["UPLOAD_DEFAULT_MAX_MB"])
    if not ok:
        flash(f"Invalid file: {err}", "danger")
        return redirect(url_for("admin.application_detail", app_id=application.id))
    file.stream.seek(0)
    from ..utils.dynamic_forms import stage_files
    staged = stage_files([(file, None)], label)[0]
    from ..storage.documents import upload_document_record
    doc = upload_document_record(application.order, staged, application=application,
                                 purpose="output_document", uploaded_by="admin",
                                 admin=current_user)
    db.session.add(doc)
    db.session.commit()
    log_admin_action(current_user, "output_document_uploaded", "application", application.id)
    db.session.commit()
    flash("Output document uploaded. The customer can download it from tracking.",
          "success")
    return redirect(url_for("admin.application_detail", app_id=application.id))
