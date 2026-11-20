"""Admin document manager: preview/download/open/delete customer documents.

Every access is authenticated; Google Drive links stay private and are only
surfaced to admins here.
"""
import mimetypes
import os

from flask import (render_template, request, redirect, url_for, flash, abort,
                   send_file, Response, current_app)
from flask_login import login_required, current_user

from . import admin_bp
from ..extensions import db
from ..models import UploadedDocument, Order, Application
from ..storage.base import get_storage, StorageError
from ..utils.audit import log_admin_action


@admin_bp.route("/documents")
@login_required
def documents_list():
    page = request.args.get("page", 1, type=int)
    purpose = (request.args.get("purpose") or "").strip()
    upload_status = (request.args.get("upload_status") or "").strip()
    q = (request.args.get("q") or "").strip()

    query = UploadedDocument.query
    if purpose:
        query = query.filter(UploadedDocument.doc_purpose == purpose)
    if upload_status:
        query = query.filter(UploadedDocument.upload_status == upload_status)
    if q:
        like = f"%{q}%"
        query = query.filter(UploadedDocument.original_name.ilike(like) |
                             UploadedDocument.label_snapshot.ilike(like))
    pagination = query.order_by(UploadedDocument.created_at.desc()).paginate(
        page=page, per_page=30, error_out=False)
    return render_template("admin/documents_list.html", pagination=pagination,
                           purpose=purpose, upload_status=upload_status, q=q)


def _admin_document(doc_id):
    doc = db.session.get(UploadedDocument, doc_id)
    if doc is None:
        abort(404)
    return doc


@admin_bp.route("/documents/<int:doc_id>/preview")
@login_required
def document_preview(doc_id):
    """Stream the file inline - only for authenticated admins."""
    doc = _admin_document(doc_id)
    return _send_document(doc, as_attachment=False)


@admin_bp.route("/documents/<int:doc_id>/download")
@login_required
def document_download(doc_id):
    doc = _admin_document(doc_id)
    return _send_document(doc, as_attachment=True)


def _send_document(doc, as_attachment: bool):
    storage = get_storage()
    try:
        if doc.drive_file_id and storage.name == "gdrive":
            data = storage.download_file(doc.drive_file_id)
            log_admin_action(current_user, "document_accessed", "document", doc.id,
                             {"mode": "download" if as_attachment else "preview"})
            db.session.commit()
            response = Response(data, mimetype=doc.mime_type)
        elif doc.local_staging_rel_path:
            path = os.path.join(current_app.instance_path, doc.local_staging_rel_path)
            if not os.path.exists(path):
                flash("Local file not found (still pending on staging?).", "danger")
                return redirect(request.referrer or url_for("admin.documents_list"))
            response = send_file(path, mimetype=doc.mime_type, as_attachment=as_attachment,
                                 download_name=doc.original_name)
        elif storage.name == "local" and doc.drive_file_id:
            # Local adapter stores absolute path in drive_file_id column
            response = send_file(doc.drive_file_id, mimetype=doc.mime_type,
                                 as_attachment=as_attachment, download_name=doc.original_name)
        else:
            flash("File content is not available in the active storage provider.", "danger")
            return redirect(request.referrer or url_for("admin.documents_list"))
    except StorageError as exc:
        flash(f"Storage error: {exc}", "danger")
        return redirect(request.referrer or url_for("admin.documents_list"))

    if as_attachment:
        response.headers["Content-Disposition"] = \
            f"attachment; filename=\"{doc.original_name}\""
    return response


@admin_bp.route("/documents/<int:doc_id>/open-drive")
@login_required
def document_open_drive(doc_id):
    doc = _admin_document(doc_id)
    if doc.web_view_link:
        return redirect(doc.web_view_link)
    flash("No Drive link stored for this document.", "warning")
    return redirect(request.referrer or url_for("admin.documents_list"))


@admin_bp.route("/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def document_delete(doc_id):
    doc = _admin_document(doc_id)
    order_id = doc.order_id
    storage = get_storage()
    file_ref = doc.drive_file_id
    deleted_in_storage = False
    if file_ref:
        deleted_in_storage = storage.delete_file(file_ref)
    db.session.delete(doc)
    db.session.commit()
    log_admin_action(current_user, "document_deleted", "document", doc_id,
                     {"storage_deleted": deleted_in_storage})
    db.session.commit()
    flash("Document deleted from the record" +
          (" and from storage." if deleted_in_storage else
           " (file was not present in the active storage)."), "warning")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@admin_bp.route("/documents/retry-pending", methods=["POST"])
@login_required
def documents_retry_pending():
    from ..storage.documents import retry_pending_uploads
    ok, still_pending = retry_pending_uploads()
    log_admin_action(current_user, "pending_uploads_retried", "document", None,
                     {"ok": ok, "pending": still_pending})
    db.session.commit()
    flash(f"Retry complete: {ok} uploaded, {still_pending} still pending.", "info")
    return redirect(request.referrer or url_for("admin.documents_list"))
