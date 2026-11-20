"""Admin dashboard + reports & analytics (all numbers from PostgreSQL)."""
from datetime import datetime, timedelta, timezone

from flask import render_template, request, redirect, url_for, Response, flash
from flask_login import login_required, current_user
from sqlalchemy import func, distinct

from . import admin_bp
from ..extensions import db, login_manager
from ..models import (Order, Application, Payment, UploadedDocument, Notification,
                      Service, ServiceCategory, StatusHistory, Customer)
from ..models.audit_log import AdminAuditLog
from ..utils.audit import log_admin_action


def _ist_day_bounds(day):
    """Start of given UTC day shifted to IST window (IST = UTC+5:30)."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    return start, start + timedelta(days=1)


@login_manager.unauthorized_handler
def _unauthorized():
    return redirect(url_for("auth.login"))


@admin_bp.route("/")
@login_required
def dashboard():
    today_utc = datetime.now(timezone.utc)
    ist_start = today_utc.astimezone(timezone(timedelta(hours=5, minutes=30))).replace(
        hour=0, minute=0, second=0, microsecond=0)
    day_start_utc = ist_start.astimezone(timezone.utc)

    stats = {
        "total_orders": Order.query.count(),
        "total_applications": Application.query.count(),
        "pending_payments": Payment.query.filter(
            Payment.status.in_(["submitted", "pending_verification"])).count(),
        "verified_payments": Payment.query.filter_by(status="verified").count(),
        "under_processing": Application.query.filter_by(status="under_processing").count(),
        "completed_applications": Application.query.filter_by(status="completed").count(),
        "rejected_applications": Application.query.filter_by(status="rejected").count(),
        "todays_orders": Order.query.filter(Order.submitted_at >= day_start_utc).count(),
    }

    # Revenue: ONLY verified payments count as collected.
    today_verified = db.session.query(func.coalesce(func.sum(Payment.amount_expected), 0)).filter(
        Payment.status == "verified", Payment.verified_at >= day_start_utc).scalar() or 0
    month_start_ist = ist_start.replace(day=1)
    month_verified = db.session.query(func.coalesce(func.sum(Payment.amount_expected), 0)).filter(
        Payment.status == "verified", Payment.verified_at >= month_start_ist.astimezone(timezone.utc)).scalar() or 0
    stats["todays_verified_collections"] = today_verified
    stats["monthly_verified_collections"] = month_verified

    # Chart data ------------------------------------------------------------
    days = [day_start_utc - timedelta(days=i) for i in range(13, -1, -1)]
    daily_labels, daily_counts = [], []
    for d in days:
        nxt = d + timedelta(days=1)
        count = Order.query.filter(Order.submitted_at >= d, Order.submitted_at < nxt).count()
        daily_labels.append(d.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d %b"))
        daily_counts.append(count)

    # Monthly collections (last 6 months, verified only)
    month_labels, month_values = [], []
    for back in range(5, -1, -1):
        first = (ist_start.replace(day=1) - timedelta(days=1)).replace(day=1)
        for _ in range(back):
            first = (first - timedelta(days=1)).replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        value = db.session.query(func.coalesce(func.sum(Payment.amount_expected), 0)).filter(
            Payment.status == "verified",
            Payment.verified_at >= first.astimezone(timezone.utc),
            Payment.verified_at < nxt.astimezone(timezone.utc)).scalar() or 0
        month_labels.append(first.strftime("%b %Y"))
        month_values.append(float(value))

    # Service-wise applications (top 10)
    svc_rows = (db.session.query(Application.service_name_snapshot, func.count(Application.id))
                .group_by(Application.service_name_snapshot)
                .order_by(func.count(Application.id).desc()).limit(10).all())

    # Application status distribution
    status_rows = (db.session.query(Application.status, func.count(Application.id))
                   .group_by(Application.status).all())

    # Payment verification stats
    pay_rows = (db.session.query(Payment.status, func.count(Payment.id))
                .group_by(Payment.status).all())

    # Pending attention queues
    pending_payment_orders = (Order.query.join(Payment).filter(
        Payment.status.in_(["submitted", "pending_verification"]))
        .order_by(Order.updated_at.desc()).limit(8).all())
    recent_orders = Order.query.order_by(Order.submitted_at.desc()).limit(8).all()
    pending_uploads = UploadedDocument.query.filter_by(upload_status="pending").count()

    return render_template("admin/dashboard.html", stats=stats,
                           daily_labels=daily_labels, daily_counts=daily_counts,
                           month_labels=month_labels, month_values=month_values,
                           svc_rows=svc_rows, status_rows=status_rows, pay_rows=pay_rows,
                           pending_payment_orders=pending_payment_orders,
                           recent_orders=recent_orders,
                           pending_uploads=pending_uploads)


@admin_bp.route("/reports")
@login_required
def reports():
    date_from = (request.args.get("from") or "").strip()
    date_to = (request.args.get("to") or "").strip()
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc) if date_from \
            else datetime.now(timezone.utc) - timedelta(days=30)
        end = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1) \
            if date_to else datetime.now(timezone.utc) + timedelta(days=1)
    except ValueError:
        start = datetime.now(timezone.utc) - timedelta(days=30)
        end = datetime.now(timezone.utc) + timedelta(days=1)
        date_from = date_to = ""

    orders = Order.query.filter(Order.submitted_at >= start, Order.submitted_at < end).order_by(
        Order.submitted_at.desc()).all()
    verified_total = db.session.query(func.coalesce(func.sum(Payment.amount_expected), 0)).filter(
        Payment.status == "verified", Payment.verified_at >= start, Payment.verified_at < end).scalar() or 0
    svc_counts = (db.session.query(Application.service_name_snapshot, func.count(Application.id))
                  .join(Order).filter(Order.submitted_at >= start, Order.submitted_at < end)
                  .group_by(Application.service_name_snapshot)
                  .order_by(func.count(Application.id).desc()).all())

    return render_template("admin/reports.html", orders=orders,
                           verified_total=verified_total, svc_counts=svc_counts,
                           date_from=date_from, date_to=date_to)


@admin_bp.route("/reports/orders.csv")
@login_required
def reports_csv():
    import csv
    import io as _io

    buf = _io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["order_number", "customer_name", "mobile", "services",
                     "total_amount", "payment_status", "order_status", "submitted_at"])
    for o in Order.query.order_by(Order.submitted_at.desc()).limit(5000).all():
        c = o.customer
        writer.writerow([o.order_number, c.name if c else "", c.mobile if c else "",
                         o.service_names_snapshot, str(o.total_amount),
                         o.payment_status, o.status, o.submitted_at.isoformat()])
    output = Response(buf.getvalue(), mimetype="text/csv")
    output.headers["Content-Disposition"] = "attachment; filename=orders-export.csv"
    log_admin_action(current_user, "reports_export_csv")
    db.session.commit()
    return output


@admin_bp.route("/audit-logs")
@login_required
def audit_logs():
    page = request.args.get("page", 1, type=int)
    pagination = (db.paginate(db.select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()),
                              page=page, per_page=50, error_out=False))
    return render_template("admin/audit_logs.html", pagination=pagination)
