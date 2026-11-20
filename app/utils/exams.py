"""Examination-cycle engine: verified-dates-only status logic.

Rules (never invent dates, never silently extend):
- Status transitions are computed from the admin-verified dates only:
  upcoming -> open (when application_start_date arrives),
  open -> closed (after application_last_date passes).
- An extension exists ONLY when the admin edits the last date after official
  confirmation (officially_extended flag documents it).
- Stale/unverified cycles are flagged (needs_review) for admin review.
"""
from datetime import date, datetime, timedelta, timezone

from ..extensions import db
from ..models.exam import ExamCycle

APPROACHING_DAYS = 7  # "Last Date Approaching" window


def today() -> date:
    """Current date in the shop timezone (IST)."""
    now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return now.date()


def cycle_accepting_applications(cycle: ExamCycle, on: date | None = None) -> bool:
    """True when this published cycle accepts applications right now.

    Uses verified dates when available; cycles without any deadline keep the
    admin-set status (upcoming/open), cancelled cycles never accept.
    """
    if cycle.exam_status == "cancelled" or cycle.is_archived or not cycle.is_published:
        return False
    day = on or today()
    if cycle.application_last_date is not None:
        return day <= cycle.application_last_date
    return cycle.exam_status in ("upcoming", "open")


def compute_status(cycle: ExamCycle, on: date | None = None) -> str:
    """Recompute the cycle status from its verified dates."""
    if cycle.exam_status == "cancelled":
        return "cancelled"
    day = on or today()
    start = cycle.application_start_date
    last = cycle.application_last_date
    if last is not None and day > last:
        return "closed"
    if start is not None and day < start:
        return "upcoming"
    if start is not None or last is not None:
        return "open"
    return cycle.exam_status  # no verified dates yet: keep admin-set state


def refresh_cycle_status(cycle: ExamCycle, on: date | None = None) -> bool:
    """Auto-update one cycle's stored status; returns True when changed."""
    new_status = compute_status(cycle, on)
    if new_status != cycle.exam_status:
        cycle.exam_status = new_status
        return True
    return False


def refresh_all_cycle_statuses() -> int:
    """Refresh every cycle (used by the exams page and a CLI command)."""
    changed = 0
    for cycle in ExamCycle.query.all():
        if refresh_cycle_status(cycle):
            changed += 1
    if changed:
        db.session.commit()
    return changed


def deadline_info(cycle: ExamCycle, on: date | None = None) -> dict:
    """Countdown + urgency for templates: days_left, label, css class.

    Uses the freshly computed status (not the possibly stale stored one)."""
    day = on or today()
    status = compute_status(cycle, day)
    info = {"days_left": None, "label": "", "css": "secondary", "kind": status}
    last = cycle.application_last_date
    start = cycle.application_start_date
    if status == "closed":
        info["label_key"] = "closed"
        info["css"] = "secondary"
        return info
    if status == "upcoming" and start:
        days = (start - day).days
        info.update(days_left=days, label_key="opens_in", css="info")
        return info
    if last:
        days = (last - day).days
        info["days_left"] = days
        if days < 0:
            info.update(label_key="closed", css="secondary")
        elif days <= APPROACHING_DAYS:
            info.update(label_key="last_date_approaching", css="danger")
        else:
            info.update(label_key="days_left", css="success")
    return info


def published_open_cycles_query(on: date | None = None):
    """Query of published, non-archived cycles whose application window is
    still open (verified by date, not by a possibly stale stored status)."""
    from sqlalchemy import or_
    day = on or today()
    return (ExamCycle.query
            .filter(ExamCycle.is_published.is_(True),
                    ExamCycle.is_archived.is_(False),
                    ExamCycle.exam_status != "cancelled",
                    or_(ExamCycle.application_last_date.is_(None),
                        ExamCycle.application_last_date >= day)))


def filter_options():
    """Distinct values for the exam listing filters (from all published cycles)."""
    rows = ExamCycle.query.filter(ExamCycle.is_published.is_(True),
                                  ExamCycle.is_archived.is_(False)).all()
    orgs = sorted({c.organization for c in rows if c.organization})
    levels = sorted({c.education_level for c in rows if c.education_level})
    states = sorted({c.state for c in rows if c.state})
    quals = sorted({c.qualification for c in rows if c.qualification})
    return {"organizations": orgs, "education_levels": levels, "states": states,
            "qualifications": quals}
