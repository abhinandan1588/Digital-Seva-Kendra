"""Status management: history recording + cascading status rules."""
from flask_login import current_user

from ..extensions import db
from ..models import StatusHistory


def record_status_change(entity_type: str, order, entity=None, previous=None, new=None,
                         customer_remark: str | None = None, internal_note: str | None = None,
                         visible_to_customer: bool = True, admin=None) -> None:
    """Insert a status_history row. Never log customer PII here."""
    admin_id = None
    updated_by = "system"
    if admin is not None:
        admin_id = admin.id
        updated_by = admin.email
    elif hasattr(current_user, "email") and current_user.is_authenticated:
        admin_id = current_user.id
        updated_by = current_user.email
    db.session.add(StatusHistory(
        entity_type=entity_type,
        order_id=order.id,
        application_id=entity.id if entity_type == "application" and entity else None,
        payment_id=entity.id if entity_type == "payment" and entity else None,
        previous_status=previous,
        new_status=new,
        updated_by_admin_id=admin_id,
        updated_by_label=updated_by,
        visible_to_customer=visible_to_customer,
        customer_remark=customer_remark,
        internal_note=internal_note,
    ))


def set_order_status(order, new_status: str, **kwargs) -> None:
    previous = order.status
    order.status = new_status
    record_status_change("order", order, previous=previous, new=new_status, **kwargs)


def set_application_status(application, new_status: str, **kwargs) -> None:
    previous = application.status
    application.status = new_status
    record_status_change("application", application.order, application,
                         previous, new_status, **kwargs)
    _sync_order_completion(application.order)


def set_payment_status(payment, new_status: str, **kwargs) -> None:
    previous = payment.status
    payment.status = new_status
    record_status_change("payment", payment, payment, previous, new_status, **kwargs)


def _sync_order_completion(order) -> None:
    """If all applications of a confirmed order are completed, mark the order."""
    if order.status not in ("confirmed", "partially_completed", "submitted",
                            "awaiting_payment", "payment_verification"):
        return
    apps = order.applications
    if not apps:
        return
    statuses = {a.status for a in apps}
    if statuses == {"completed"}:
        set_order_status(order, "completed",
                         customer_remark="All applications completed.")
    elif "completed" in statuses and order.status == "confirmed":
        set_order_status(order, "partially_completed",
                         customer_remark="Some applications completed.")
