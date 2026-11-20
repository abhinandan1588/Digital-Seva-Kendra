"""Admin audit logging helper."""
from flask import request

from ..extensions import db
from ..models import AdminAuditLog


def log_admin_action(admin, action: str, entity_type: str | None = None,
                     entity_id=None, details: dict | None = None) -> None:
    """Record an admin action. Never includes customer PII in details."""
    entry = AdminAuditLog(
        admin_id=admin.id if admin else None,
        admin_email_snapshot=admin.email if admin else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details or {},
        ip_address=request.remote_addr if request else None,
        user_agent=(request.headers.get("User-Agent", "")[:300] if request else None),
    )
    db.session.add(entry)
