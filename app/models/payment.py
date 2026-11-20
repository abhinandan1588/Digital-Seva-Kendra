"""Payment records - manual UPI verification in v1, gateway-ready structure."""
from sqlalchemy import String, Text, Numeric, DateTime, ForeignKey, Index

from ..extensions import db
from .admin import utcnow
from .order import PAYMENT_STATUSES

PAYMENT_METHODS = ("upi_qr", "manual", "gateway")


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, ForeignKey("orders.id", ondelete="CASCADE"),
                         nullable=False, index=True)

    amount_expected = db.Column(db.Numeric(10, 2), nullable=False)
    amount_submitted = db.Column(db.Numeric(10, 2), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="awaiting_payment", index=True)

    upi_transaction_id = db.Column(db.String(60), nullable=True, index=True)
    customer_remarks = db.Column(db.Text, nullable=True)
    payment_method = db.Column(db.String(20), nullable=False, default="upi_qr")

    # Verification trail (use_alter: circular FK with uploaded_documents)
    screenshot_document_id = db.Column(
        db.Integer, ForeignKey("uploaded_documents.id", ondelete="SET NULL", use_alter=True,
                               name="fk_payments_screenshot_doc"), nullable=True)
    verified_by_admin_id = db.Column(db.Integer, ForeignKey("admin_users.id", ondelete="SET NULL"),
                                     nullable=True)
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    admin_notes = db.Column(db.Text, nullable=True)
    gateway_reference = db.Column(db.String(120), nullable=True)  # future gateway integration

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    order = db.relationship("Order", back_populates="payments", foreign_keys=[order_id])
    screenshot = db.relationship("UploadedDocument", foreign_keys=[screenshot_document_id])
    verified_by = db.relationship("AdminUser", foreign_keys=[verified_by_admin_id])

    def __repr__(self):  # pragma: no cover
        return f"<Payment order={self.order_id} {self.status}>"


Index("ix_payments_status_created", Payment.status, Payment.created_at)
