"""Uploaded documents metadata. File contents live in Google Drive (or the
local fallback store); the database keeps metadata + provider file IDs only.
"""
from sqlalchemy import String, Integer, BigInteger, Boolean, DateTime, ForeignKey, Index

from ..extensions import db
from .admin import utcnow

DOC_PURPOSES = ("application_document", "form_field_file", "payment_proof", "output_document")
UPLOAD_STATUSES = ("pending", "uploaded", "failed")
STORAGE_PROVIDERS = ("gdrive", "local")


class UploadedDocument(db.Model):
    __tablename__ = "uploaded_documents"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, ForeignKey("orders.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    application_id = db.Column(db.Integer, ForeignKey("applications.id", ondelete="CASCADE"),
                               nullable=True, index=True)
    requirement_id = db.Column(db.Integer,
                               ForeignKey("service_document_requirements.id", ondelete="SET NULL"),
                               nullable=True)
    form_field_id = db.Column(db.Integer,
                              ForeignKey("service_form_fields.id", ondelete="SET NULL"),
                              nullable=True)
    payment_id = db.Column(db.Integer, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)

    doc_purpose = db.Column(db.String(30), nullable=False, default="application_document")
    label_snapshot = db.Column(db.String(200), nullable=False)  # e.g. "Aadhaar Document"
    original_name = db.Column(db.String(255), nullable=False)   # display name only, never a path
    stored_name = db.Column(db.String(120), nullable=False)     # generated safe name
    mime_type = db.Column(db.String(120), nullable=False, default="application/octet-stream")
    size_bytes = db.Column(db.BigInteger, nullable=False, default=0)

    storage_provider = db.Column(db.String(10), nullable=False, default="local")
    drive_file_id = db.Column(db.String(500), nullable=True, index=True)
    drive_folder_id = db.Column(db.String(500), nullable=True)
    web_view_link = db.Column(db.String(500), nullable=True)  # private link, admin-only display

    upload_status = db.Column(db.String(10), nullable=False, default="uploaded", index=True)
    retry_count = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.String(500), nullable=True)

    # local fallback storage path (relative to instance dir) for pending/failed retries
    local_staging_rel_path = db.Column(db.String(300), nullable=True)

    uploaded_by = db.Column(db.String(10), nullable=False, default="customer")  # customer|admin
    uploaded_by_admin_id = db.Column(db.Integer, ForeignKey("admin_users.id", ondelete="SET NULL"),
                                     nullable=True)
    is_private = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    order = db.relationship("Order", foreign_keys=[order_id])
    application = db.relationship("Application", foreign_keys=[application_id])
    requirement = db.relationship("ServiceDocumentRequirement", foreign_keys=[requirement_id])

    @property
    def size_display(self) -> str:
        size = self.size_bytes or 0
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} B"

    def __repr__(self):  # pragma: no cover
        return f"<UploadedDocument {self.stored_name}>"


Index("ix_docs_order_purpose", UploadedDocument.order_id, UploadedDocument.doc_purpose)
Index("ix_docs_pending", UploadedDocument.upload_status, UploadedDocument.storage_provider)
