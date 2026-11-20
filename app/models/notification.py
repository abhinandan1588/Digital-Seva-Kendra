"""Customer-facing notification records.

V1 records every notification event in PostgreSQL and shows it on the
tracking page. Delivery to WhatsApp/SMS/email happens through the provider
adapter in app/notifications; when no provider is configured the record is
marked honestly as "skipped" - never as "sent".
"""
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, Index

from ..extensions import db
from ..models import JSONB
from .admin import utcnow

CHANNELS = ("inapp", "whatsapp", "sms", "email")
DELIVERY_STATUSES = ("pending", "sent", "skipped", "failed")

EVENT_LABELS = {
    "order_submitted": ("Order submitted", "ऑर्डर जमा हुआ"),
    "payment_proof_received": ("Payment proof received", "भुगतान प्रमाण प्राप्त"),
    "payment_verified": ("Payment verified", "भुगतान सत्यापित"),
    "payment_rejected": ("Payment rejected", "भुगतान अस्वीकृत"),
    "documents_required": ("Additional documents required", "अतिरिक्त दस्तावेज़ आवश्यक"),
    "application_processing": ("Application under processing", "आवेदन प्रक्रिया में"),
    "application_completed": ("Application completed", "आवेदन पूर्ण"),
    "application_rejected": ("Application rejected", "आवेदन अस्वीकृत"),
    "documents_uploaded": ("Documents uploaded", "दस्तावेज़ अपलोड हुए"),
}


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, ForeignKey("orders.id", ondelete="CASCADE"),
                         nullable=True, index=True)
    application_id = db.Column(db.Integer, ForeignKey("applications.id", ondelete="CASCADE"),
                               nullable=True)
    customer_id = db.Column(db.Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)

    event_type = db.Column(db.String(50), nullable=False)
    channel = db.Column(db.String(15), nullable=False, default="inapp")
    recipient_mobile = db.Column(db.String(15), nullable=True)
    recipient_email = db.Column(db.String(255), nullable=True)

    title_en = db.Column(db.String(200), nullable=False)
    title_hi = db.Column(db.String(200), nullable=False)
    message_en = db.Column(db.Text, nullable=True)
    message_hi = db.Column(db.Text, nullable=True)
    visible_to_customer = db.Column(db.Boolean, nullable=False, default=True)

    payload = db.Column(JSONB, nullable=True)

    delivery_status = db.Column(db.String(10), nullable=False, default="pending", index=True)
    provider_name = db.Column(db.String(40), nullable=True)
    provider_error = db.Column(db.String(300), nullable=True)
    sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    order = db.relationship("Order", foreign_keys=[order_id])
    application = db.relationship("Application", foreign_keys=[application_id])
    customer = db.relationship("Customer", foreign_keys=[customer_id])

    def __repr__(self):  # pragma: no cover
        return f"<Notification {self.event_type} {self.delivery_status}>"


Index("ix_notifications_order_created", Notification.order_id, Notification.created_at)
