"""Public examination listing (Part 3): verified recruitment notifications
with filters, deadline countdowns and honest closed-cycle handling."""
from datetime import timedelta, date

from flask import Blueprint, render_template, request

from ..models import ExamCycle
from ..utils.exams import (refresh_all_cycle_statuses, deadline_info, today,
                           filter_options)

exams_bp = Blueprint("exams", __name__, url_prefix="/exams")


@exams_bp.route("/")
def exam_list():
    refresh_all_cycle_statuses()

    organization = (request.args.get("organization") or "").strip()
    qualification = (request.args.get("qualification") or "").strip()
    education_level = (request.args.get("education_level") or "").strip()
    status = (request.args.get("status") or "").strip()
    state = (request.args.get("state") or "").strip()
    deadline_within = request.args.get("deadline_within", type=int)

    query = ExamCycle.query.filter(ExamCycle.is_published.is_(True),
                                   ExamCycle.is_archived.is_(False))
    if organization:
        query = query.filter(ExamCycle.organization == organization)
    if qualification:
        query = query.filter(ExamCycle.qualification.ilike(f"%{qualification}%"))
    if education_level:
        query = query.filter(ExamCycle.education_level == education_level)
    if state:
        query = query.filter(ExamCycle.state == state)
    if status in ("upcoming", "open", "closed"):
        query = query.filter(ExamCycle.exam_status == status)
    if deadline_within and deadline_within > 0:
        query = query.filter(ExamCycle.application_last_date.isnot(None),
                             ExamCycle.application_last_date <= today() + timedelta(days=deadline_within),
                             ExamCycle.application_last_date >= today())

    cycles = query.order_by(ExamCycle.application_last_date.asc().nullslast(),
                            ExamCycle.id.desc()).all()
    deadline = {c.id: deadline_info(c) for c in cycles}
    return render_template("exams/list.html", cycles=cycles, deadline=deadline,
                           options=filter_options(),
                           organization=organization, qualification=qualification,
                           education_level=education_level, status=status,
                           state=state, deadline_within=deadline_within or "")


@exams_bp.route("/<cycle_slug>")
def exam_detail(cycle_slug):
    refresh_all_cycle_statuses()
    cycle = ExamCycle.query.filter_by(cycle_slug=cycle_slug,
                                      is_published=True, is_archived=False).first_or_404()
    open_now = cycle.exam_status in ("upcoming", "open")
    return render_template("exams/detail.html", cycle=cycle,
                           deadline=deadline_info(cycle), open_now=open_now)
