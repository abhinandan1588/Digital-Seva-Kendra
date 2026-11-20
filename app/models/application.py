"""Applications (one per service inside an order) and their dynamic form data."""
from sqlalchemy import String, Text, DateTime, ForeignKey, UniqueConstraint

from ..extensions import db
from ..models import JSONB
from .admin import utcnow
from .order import APPLICATION_STATUSES


class Application(db.Model):
    __tablename__ = "applications"

    id = db.Column(db.Integer, primary_key=True)
    application_number = db.Column(db.String(40), unique=True, nullable=False, index=True)

    order_id = db.Column(db.Integer, ForeignKey("orders.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    order_item_id = db.Column(db.Integer, ForeignKey("order_items.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    service_id = db.Column(db.Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True)

    # The examination cycle (notification) chosen for exam-type applications.
    # SET NULL keeps the record safe; the snapshot text preserves what was shown.
    exam_cycle_id = db.Column(db.Integer, ForeignKey("exam_cycles.id", ondelete="SET NULL"),
                              nullable=True)
    exam_cycle_snapshot = db.Column(db.String(200), nullable=True)

    service_name_snapshot = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="submitted", index=True)
    customer_visible_remark = db.Column(db.Text, nullable=True)

    submitted_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    order = db.relationship("Order", back_populates="applications")
    order_item = db.relationship("OrderItem", foreign_keys=[order_item_id])
    service = db.relationship("Service")
    exam_cycle = db.relationship("ExamCycle")
    field_values = db.relationship("ApplicationFieldValue", back_populates="application",
                                   cascade="all, delete-orphan", order_by="ApplicationFieldValue.id")

    @property
    def output_documents(self):
        return [d for d in self.documents if d.doc_purpose == "output_document"]

    def __repr__(self):  # pragma: no cover
        return f"<Application {self.application_number}>"


class ApplicationFieldValue(db.Model):
    """Customer-entered value for one dynamic form field.

    value_text stores single answers; value_json stores lists (checkboxes,
    multi-file summaries). form_field_id is nullable ON SET NULL so answers
    survive even when the admin later deletes the field definition.
    """
    __tablename__ = "application_field_values"

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, ForeignKey("applications.id", ondelete="CASCADE"),
                               nullable=False, index=True)
    form_field_id = db.Column(db.Integer, ForeignKey("service_form_fields.id", ondelete="SET NULL"),
                              nullable=True)
    field_key = db.Column(db.String(60), nullable=False)
    field_label_snapshot = db.Column(db.String(200), nullable=False)
    field_type = db.Column(db.String(20), nullable=False, default="text")
    value_text = db.Column(db.Text, nullable=True)
    value_json = db.Column(JSONB, nullable=True)

    application = db.relationship("Application", back_populates="field_values")
    form_field = db.relationship("ServiceFormField")

    @property
    def display_value(self) -> str:
        if self.field_type == "checkbox" and isinstance(self.value_json, list):
            return ", ".join(str(v) for v in self.value_json)
        return self.value_text or ""
