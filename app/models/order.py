"""Orders, order items and the shared status-history log."""
from datetime import datetime

from sqlalchemy import String, Text, Numeric, Boolean, Integer, DateTime, ForeignKey, Index

from ..extensions import db
from .admin import utcnow

# --- Status vocabularies (kept in one place; status values are never re-used
# with different meanings) -------------------------------------------------
ORDER_STATUSES = (
    "draft", "submitted", "awaiting_payment", "payment_verification",
    "confirmed", "partially_completed", "completed", "cancelled",
)
PAYMENT_STATUSES = (
    "awaiting_payment", "submitted", "pending_verification",
    "verified", "rejected", "refunded",
)
APPLICATION_STATUSES = (
    "submitted", "awaiting_payment", "payment_verified", "under_processing",
    "documents_required", "resubmission_required", "completed", "rejected", "cancelled",
)

ORDER_STATUS_LABELS = {
    "draft": ("Draft", "ड्राफ्ट"),
    "submitted": ("Submitted", "जमा किया गया"),
    "awaiting_payment": ("Awaiting Payment", "भुगतान प्रतीक्षित"),
    "payment_verification": ("Payment Verification", "भुगतान सत्यापन"),
    "confirmed": ("Confirmed", "पुष्ट"),
    "partially_completed": ("Partially Completed", "आंशिक रूप से पूर्ण"),
    "completed": ("Completed", "पूर्ण"),
    "cancelled": ("Cancelled", "रद्द"),
}
PAYMENT_STATUS_LABELS = {
    "awaiting_payment": ("Awaiting Payment", "भुगतान प्रतीक्षित"),
    "submitted": ("Payment Submitted", "भुगतान जमा"),
    "pending_verification": ("Pending Verification", "सत्यापन लंबित"),
    "verified": ("Verified", "सत्यापित"),
    "rejected": ("Rejected", "अस्वीकृत"),
    "refunded": ("Refunded", "धनवापसी"),
}
APPLICATION_STATUS_LABELS = {
    "submitted": ("Submitted", "जमा किया गया"),
    "awaiting_payment": ("Awaiting Payment", "भुगतान प्रतीक्षित"),
    "payment_verified": ("Payment Verified", "भुगतान सत्यापित"),
    "under_processing": ("Under Processing", "प्रक्रिया में"),
    "documents_required": ("Documents Required", "दस्तावेज़ आवश्यक"),
    "resubmission_required": ("Resubmission Required", "पुनः जमा आवश्यक"),
    "completed": ("Completed", "पूर्ण"),
    "rejected": ("Rejected", "अस्वीकृत"),
    "cancelled": ("Cancelled", "रद्द"),
}


def status_label(kind: str, value: str) -> str:
    """Customer-facing bilingual label for a status value."""
    labels = {
        "order": ORDER_STATUS_LABELS,
        "payment": PAYMENT_STATUS_LABELS,
        "application": APPLICATION_STATUS_LABELS,
    }.get(kind, {})
    pair = labels.get(value)
    if not pair:
        return value.replace("_", " ").title()
    from ..utils.i18n import pick
    return pick(*pair)


class Counter(db.Model):
    """Atomic per-year counters (order numbers, application numbers)."""
    __tablename__ = "counters"
    key = db.Column(db.String(40), primary_key=True)
    value = db.Column(db.Integer, nullable=False, default=0)


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(30), unique=True, nullable=False, index=True)

    customer_id = db.Column(db.Integer, ForeignKey("customers.id", ondelete="RESTRICT"),
                            nullable=False, index=True)

    status = db.Column(db.String(30), nullable=False, default="submitted",
                       index=True)  # see ORDER_STATUSES
    payment_status = db.Column(db.String(30), nullable=False, default="awaiting_payment",
                               index=True)  # see PAYMENT_STATUSES

    service_charges_total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    official_fees_total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    other_charges_total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="INR")

    # SHA-256 hashes only - the raw token/PIN is shown once at confirmation.
    tracking_token_hash = db.Column(db.String(64), nullable=False, index=True)
    tracking_pin_hash = db.Column(db.String(64), nullable=False)
    # Guards against double-click duplicate submissions.
    idempotency_key = db.Column(db.String(64), unique=True, nullable=True)

    customer_ip = db.Column(db.String(45), nullable=True)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    customer = db.relationship("Customer", back_populates="orders")
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan",
                            order_by="OrderItem.item_sequence")
    applications = db.relationship("Application", back_populates="order", cascade="all, delete-orphan",
                                   order_by="Application.id")
    payments = db.relationship("Payment", back_populates="order", cascade="all, delete-orphan",
                               order_by="Payment.id")

    @property
    def latest_payment(self):
        return self.payments[-1] if self.payments else None

    @property
    def service_names_snapshot(self) -> str:
        return ", ".join(i.service_name_snapshot for i in self.items)

    def __repr__(self):  # pragma: no cover
        return f"<Order {self.order_number}>"


class OrderItem(db.Model):
    """One selected service inside an order; prices are snapshotted at checkout
    so later admin price changes never alter an existing order."""
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, ForeignKey("orders.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    service_id = db.Column(db.Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True)
    item_sequence = db.Column(db.Integer, nullable=False, default=1)

    service_name_snapshot = db.Column(db.String(200), nullable=False)
    service_slug_snapshot = db.Column(db.String(160), nullable=True)
    service_charge_snapshot = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    official_fee_snapshot = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    other_charge_snapshot = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    line_total_snapshot = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    order = db.relationship("Order", back_populates="items")
    service = db.relationship("Service")

    @property
    def application(self):
        for app in self.order.applications:
            if app.order_item_id == self.id:
                return app
        return None


class StatusHistory(db.Model):
    """Every status change of an order / application / payment is recorded.
    Internal notes are never shown on public tracking pages."""
    __tablename__ = "status_history"

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(15), nullable=False, index=True)  # order|application|payment
    order_id = db.Column(db.Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    application_id = db.Column(db.Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=True)
    payment_id = db.Column(db.Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=True)

    previous_status = db.Column(db.String(30), nullable=True)
    new_status = db.Column(db.String(30), nullable=False)
    updated_by_admin_id = db.Column(db.Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    updated_by_label = db.Column(db.String(40), nullable=False, default="system")
    visible_to_customer = db.Column(db.Boolean, nullable=False, default=True)
    customer_remark = db.Column(db.Text, nullable=True)
    internal_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    order = db.relationship("Order", foreign_keys=[order_id])
    admin = db.relationship("AdminUser", foreign_keys=[updated_by_admin_id])

    def __repr__(self):  # pragma: no cover
        return f"<StatusHistory {self.entity_type}:{self.new_status}>"


Index("ix_status_history_order_created", StatusHistory.order_id, StatusHistory.created_at)
