"""Admin examination management (Parts 3 & 4):

- /admin/exams                 hub + exam service templates
- /admin/exam-cycles           recruitment notification cycles (list & filters)
- /admin/exam-cycles/new|edit  create/edit a cycle: verified dates, fees by
                               category, official links, notification PDF,
                               extra documents, publish/extend/close/archive,
                               verification (source + last verified date)

The admin can only record dates they verified against the official
notification; extensions require explicit confirmation. The system never
invents dates and never silently updates anything.
"""
import os

from flask import (render_template, request, redirect, url_for, flash, abort,
                   current_app)
from flask_login import login_required, current_user
from sqlalchemy import or_

from . import admin_bp
from ..extensions import db
from ..models import Service, ExamCycle
from ..models.exam import EXAM_CYCLE_STATUSES
from ..utils.audit import log_admin_action
from ..utils.exams import refresh_all_cycle_statuses, deadline_info, today
from ..utils.files import safe_stored_name
from .catalog_admin import _slugify


# --------------------------------------------------------------------------
# Exam service templates (a service with is_examination=True)
# --------------------------------------------------------------------------

@admin_bp.route("/exams")
@login_required
def exams_hub():
    refresh_all_cycle_statuses()
    templates = (Service.query.filter(Service.is_examination.is_(True),
                                      Service.is_archived.is_(False))
                 .order_by(Service.name_en).all())
    total_cycles = ExamCycle.query.filter(ExamCycle.is_archived.is_(False)).count()
    published = ExamCycle.query.filter_by(is_published=True, is_archived=False).count()
    needs_review = ExamCycle.query.filter_by(needs_review=True, is_archived=False).count()
    open_count = 0
    for cycle in ExamCycle.query.filter_by(is_published=True, is_archived=False).all():
        if cycle.exam_status == "open":
            open_count += 1
    return render_template("admin/exams_hub.html", templates=templates,
                           total_cycles=total_cycles, published=published,
                           open_count=open_count, needs_review=needs_review)


@admin_bp.route("/exams/templates")
@login_required
def exam_templates():
    q = (request.args.get("q") or "").strip()
    query = Service.query.filter(Service.is_examination.is_(True))
    if q:
        query = query.filter(Service.name_en.ilike(f"%{q}%"))
    templates = query.order_by(Service.name_en).all()
    cycle_counts = {t.id: len(t.exam_cycles) for t in templates}
    return render_template("admin/exam_templates.html", templates=templates,
                           cycle_counts=cycle_counts, q=q)


# --------------------------------------------------------------------------
# Recruitment notification cycles
# --------------------------------------------------------------------------

@admin_bp.route("/exam-cycles")
@login_required
def exam_cycles_list():
    refresh_all_cycle_statuses()
    status = (request.args.get("status") or "").strip()
    review = request.args.get("review", type=int)
    service_id = request.args.get("service_id", type=int)
    q = (request.args.get("q") or "").strip()

    query = ExamCycle.query
    if status == "published":
        query = query.filter(ExamCycle.is_published.is_(True), ExamCycle.is_archived.is_(False))
    elif status == "unpublished":
        query = query.filter(ExamCycle.is_published.is_(False), ExamCycle.is_archived.is_(False))
    elif status == "archived":
        query = query.filter(ExamCycle.is_archived.is_(True))
    elif status in EXAM_CYCLE_STATUSES:
        query = query.filter(ExamCycle.exam_status == status, ExamCycle.is_archived.is_(False))
    else:
        query = query.filter(ExamCycle.is_archived.is_(False))
    if review:
        query = query.filter(ExamCycle.needs_review.is_(True))
    if service_id:
        query = query.filter(ExamCycle.service_id == service_id)
    if q:
        like = f"%{q}%"
        query = query.join(Service, ExamCycle.service_id == Service.id).filter(
            or_(ExamCycle.display_name.ilike(like), ExamCycle.organization.ilike(like),
                Service.name_en.ilike(like)))
    cycles = query.order_by(ExamCycle.application_last_date.asc().nullslast(),
                            ExamCycle.id.desc()).all()
    deadline = {c.id: deadline_info(c) for c in cycles}
    return render_template("admin/exam_cycles_list.html", cycles=cycles, deadline=deadline,
                           status=status, review=review, service_id=service_id, q=q)


def _parse_fee_block():
    fees = {}
    for key in ("general", "obc", "sc_st", "female", "other"):
        raw = (request.form.get(f"fee_{key}") or "").strip()
        if raw:
            try:
                fees[key] = float(raw)
            except ValueError:
                pass
    note = (request.form.get("fee_note") or "").strip()
    if note:
        fees["note"] = note
    return fees or None


def _parse_date(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    from datetime import date
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _handle_notification_pdf(cycle):
    pdf = request.files.get("notification_pdf")
    if pdf is None or not pdf.filename:
        return
    if not pdf.filename.lower().endswith(".pdf"):
        flash("Notification must be a PDF file.", "danger")
        return
    upload_dir = current_app.config["PUBLIC_UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    stored = safe_stored_name("pdf")
    pdf.save(os.path.join(upload_dir, stored))
    cycle.notification_pdf_path = f"uploads/{stored}"


def _extra_documents_list():
    lines = [ln.strip() for ln in (request.form.get("required_documents_extra") or "").splitlines()
             if ln.strip()]
    return lines or None


def _cycle_from_form(cycle, service):
    cycle.service_id = service.id
    cycle.organization = (request.form.get("organization") or "").strip() or \
        (service.meta or {}).get("organization", "") or "Other"
    cycle.display_name = (request.form.get("display_name") or "").strip() or service.name_en
    cycle.advertisement_number = (request.form.get("advertisement_number") or "").strip() or None
    cycle.exam_year = request.form.get("exam_year", type=int)
    for field in ("notification_date", "application_start_date", "application_last_date",
                  "late_fee_last_date", "correction_window_start", "correction_window_end",
                  "exam_date", "admit_card_date", "result_date"):
        setattr(cycle, field, _parse_date(field))
    cycle.qualification = (request.form.get("qualification") or "").strip() or None
    cycle.education_level = (request.form.get("education_level") or "").strip() or None
    cycle.min_age = request.form.get("min_age", type=int)
    cycle.max_age = request.form.get("max_age", type=int)
    cycle.age_relaxation_info = (request.form.get("age_relaxation_info") or "").strip() or None
    cycle.gender_eligibility = (request.form.get("gender_eligibility") or "").strip() or None
    cycle.application_fees = _parse_fee_block()
    cycle.state = (request.form.get("state") or "All India").strip()
    cycle.official_notification_url = (request.form.get("official_notification_url") or "").strip() or None
    cycle.official_application_url = (request.form.get("official_application_url") or "").strip() or None
    cycle.required_documents_extra = _extra_documents_list()
    cycle.verification_source = (request.form.get("verification_source") or "").strip() or None
    cycle.exam_status = request.form.get("exam_status") or cycle.exam_status
    _handle_notification_pdf(cycle)


@admin_bp.route("/exam-cycles/new", methods=["GET", "POST"])
@login_required
def exam_cycle_new():
    service_id = request.args.get("service_id", type=int) or request.form.get("service_id", type=int)
    service = db.session.get(Service, service_id) if service_id else None
    services = Service.query.filter(Service.is_examination.is_(True),
                                    Service.is_archived.is_(False)).order_by(Service.name_en).all()
    if request.method == "POST":
        if not service:
            flash("Choose a valid examination service.", "danger")
            return render_template("admin/exam_cycle_form.html", cycle=None, services=services,
                                   service=None)
        cycle = ExamCycle(service_id=service.id)
        base = _slugify(f"{service.slug}-{request.form.get('exam_year') or 'cycle'}")
        slug = base
        n = 2
        while ExamCycle.query.filter_by(cycle_slug=slug).first():
            slug = f"{base}-{n}"
            n += 1
        cycle.cycle_slug = slug
        _cycle_from_form(cycle, service)
        db.session.add(cycle)
        db.session.commit()
        log_admin_action(current_user, "exam_cycle_created", "exam_cycle", cycle.id)
        db.session.commit()
        flash("Examination cycle created (unpublished). Verify against the official notification, then publish.",
              "success")
        return redirect(url_for("admin.exam_cycle_edit", cycle_id=cycle.id))
    return render_template("admin/exam_cycle_form.html", cycle=None, services=services,
                           service=service)


@admin_bp.route("/exam-cycles/<int:cycle_id>/edit", methods=["GET", "POST"])
@login_required
def exam_cycle_edit(cycle_id):
    cycle = db.session.get(ExamCycle, cycle_id) or abort(404)
    services = Service.query.filter(Service.is_examination.is_(True),
                                    Service.is_archived.is_(False)).order_by(Service.name_en).all()
    if request.method == "POST":
        service = db.session.get(Service, request.form.get("service_id", type=cycle.service_id))
        if not service:
            flash("Choose a valid examination service.", "danger")
        else:
            _cycle_from_form(cycle, service)
            db.session.commit()
            log_admin_action(current_user, "exam_cycle_updated", "exam_cycle", cycle.id)
            db.session.commit()
            flash("Cycle saved.", "success")
            return redirect(url_for("admin.exam_cycle_edit", cycle_id=cycle.id))
    return render_template("admin/exam_cycle_form.html", cycle=cycle, services=services,
                           service=cycle.service)


@admin_bp.route("/exam-cycles/<int:cycle_id>/publish", methods=["POST"])
@login_required
def exam_cycle_publish(cycle_id):
    cycle = db.session.get(ExamCycle, cycle_id) or abort(404)
    action = request.form.get("action")
    if action == "publish":
        if not cycle.last_verified_at:
            flash("Verify the cycle against the official notification first (set last verified).",
                  "warning")
            return redirect(url_for("admin.exam_cycle_edit", cycle_id=cycle.id))
        cycle.is_published = True
        flash("Cycle published to customers.", "success")
        log_admin_action(current_user, "exam_cycle_published", "exam_cycle", cycle.id)
    elif action == "unpublish":
        cycle.is_published = False
        flash("Cycle unpublished.", "info")
        log_admin_action(current_user, "exam_cycle_unpublished", "exam_cycle", cycle.id)
    elif action == "verify":
        cycle.last_verified_at = db.func.now()
        cycle.needs_review = False
        cycle.review_note = None
        if not cycle.verification_source:
            cycle.verification_source = "Manual verification by admin"
        flash("Cycle marked as verified against the official source.", "success")
        log_admin_action(current_user, "exam_cycle_verified", "exam_cycle", cycle.id)
    elif action == "flag-review":
        cycle.needs_review = True
        cycle.review_note = (request.form.get("review_note") or "Flagged for review.")[:290]
        flash("Cycle flagged for admin review - it stays published until you decide.", "warning")
        log_admin_action(current_user, "exam_cycle_flagged", "exam_cycle", cycle.id)
    elif action == "close":
        cycle.exam_status = "closed"
        flash("Cycle marked closed.", "info")
        log_admin_action(current_user, "exam_cycle_closed", "exam_cycle", cycle.id)
    elif action == "cancel":
        cycle.exam_status = "cancelled"
        flash("Cycle marked cancelled.", "info")
        log_admin_action(current_user, "exam_cycle_cancelled", "exam_cycle", cycle.id)
    elif action == "archive":
        cycle.is_archived = True
        cycle.is_published = False
        flash("Cycle archived (previous cycles stay in the archive).", "info")
        log_admin_action(current_user, "exam_cycle_archived", "exam_cycle", cycle.id)
    elif action == "unarchive":
        cycle.is_archived = False
        flash("Cycle unarchived.", "info")
    db.session.commit()
    return redirect(request.referrer or url_for("admin.exam_cycles_list"))


@admin_bp.route("/exam-cycles/<int:cycle_id>/extend", methods=["POST"])
@login_required
def exam_cycle_extend(cycle_id):
    """Extend the deadline ONLY after official confirmation (admin attests)."""
    cycle = db.session.get(ExamCycle, cycle_id) or abort(404)
    new_last = _parse_date("new_application_last_date")
    confirm = request.form.get("official_confirmation")
    if not new_last:
        flash("Enter the new last date.", "danger")
        return redirect(url_for("admin.exam_cycle_edit", cycle_id=cycle.id))
    if not confirm:
        flash("Extensions require official confirmation (notification/portal). Tick the confirmation box.",
              "danger")
        return redirect(url_for("admin.exam_cycle_edit", cycle_id=cycle.id))
    cycle.application_last_date = new_last
    cycle.officially_extended = True
    cycle.extension_note = (request.form.get("extension_note") or
                            f"Deadline extended to {new_last.isoformat()} (officially confirmed).")[:290]
    cycle.last_verified_at = db.func.now()
    cycle.needs_review = False
    db.session.commit()
    log_admin_action(current_user, "exam_cycle_extended", "exam_cycle", cycle.id,
                     {"new_last_date": new_last.isoformat()})
    db.session.commit()
    flash("Deadline extended and recorded as officially verified.", "success")
    return redirect(url_for("admin.exam_cycle_edit", cycle_id=cycle.id))
