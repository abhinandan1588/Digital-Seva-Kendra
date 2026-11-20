"""Admin blueprint: every route requires an authenticated admin."""
from flask import Blueprint, request, redirect, url_for
from flask_login import current_user

admin_bp = Blueprint("admin", __name__)


@admin_bp.before_request
def require_admin():
    """Protect every admin endpoint (defence in depth: views use @login_required too)."""
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.path))
    return None


@admin_bp.app_context_processor
def inject_admin_counters():
    """Badge counters for the sidebar (cheap queries, admin pages only)."""
    if not current_user.is_authenticated:
        return {}
    try:
        from ..models import Payment, UploadedDocument, ExamCycle
        pending_review = ExamCycle.query.filter_by(needs_review=True,
                                                   is_archived=False).count()
        return {
            "pending_payment_count": Payment.query.filter(
                Payment.status.in_(["submitted", "pending_verification"])).count(),
            "pending_upload_count": UploadedDocument.query.filter_by(
                upload_status="pending").count(),
            "pending_review_count": pending_review,
        }
    except Exception:
        return {"pending_payment_count": 0, "pending_upload_count": 0,
                "pending_review_count": 0}


# Import route modules so their @admin_bp.route decorators register.
from . import routes  # noqa: E402,F401  (dashboard)
from . import orders_admin  # noqa: E402,F401
from . import payments_admin  # noqa: E402,F401
from . import catalog_admin  # noqa: E402,F401
from . import subcategory_admin  # noqa: E402,F401
from . import catalog_tools_admin  # noqa: E402,F401  (templates, portals, pricing, availability)
from . import exam_admin  # noqa: E402,F401
from . import importexport_admin  # noqa: E402,F401
from . import docs_admin  # noqa: E402,F401
from . import settings_admin  # noqa: E402,F401
