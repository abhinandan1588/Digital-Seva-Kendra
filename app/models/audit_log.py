"""Admin audit log - every sensitive admin action is recorded."""
from sqlalchemy import String, Text, DateTime, ForeignKey, Index

from ..extensions import db
from ..models import JSONB
from .admin import utcnow


class AdminAuditLog(db.Model):
    __tablename__ = "admin_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    admin_email_snapshot = db.Column(db.String(255), nullable=True)

    action = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(40), nullable=True)
    entity_id = db.Column(db.String(40), nullable=True)
    details = db.Column(JSONB, nullable=True)

    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    admin = db.relationship("AdminUser", foreign_keys=[admin_id])

    def __repr__(self):  # pragma: no cover
        return f"<AdminAuditLog {self.action}>"
