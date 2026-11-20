"""Examination cycles - one row per official recruitment notification.

A *service* whose ``is_examination`` is True represents an exam TYPE
(e.g. "SSC CGL"); an *exam cycle* represents one particular notification
(e.g. "SSC CGL 2027, Advt. 1/2027"). All dates/fees are admin-verified
against the official notification - the application never invents them.
"""
from sqlalchemy import (String, Text, Numeric, Boolean, Integer, Date, DateTime,
                        ForeignKey, Index)

from ..extensions import db
from ..models import JSONB
from .admin import utcnow

# Status vocabulary. upcoming/open/closed are maintained automatically from
# verified dates (see utils/exams.py); 'cancelled' only by admin action.
EXAM_CYCLE_STATUSES = ("upcoming", "open", "closed", "cancelled")

EXAM_STATUS_LABELS = {
    "upcoming": ("Opening Soon", "शीघ्र शुरु"),
    "open": ("Applications Open", "आवेदन चालू"),
    "closed": ("Applications Closed", "आवेदन बंद"),
    "cancelled": ("Cancelled", "रद्द"),
}


class ExamCycle(db.Model):
    __tablename__ = "exam_cycles"

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, ForeignKey("services.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    cycle_slug = db.Column(db.String(180), unique=True, nullable=False, index=True)

    # Human identifiers, taken verbatim from the official notification
    display_name = db.Column(db.String(200), nullable=False)   # e.g. SSC CGL 2027
    organization = db.Column(db.String(120), nullable=False, index=True)  # SSC / UPSC / BPSC / RRB…
    advertisement_number = db.Column(db.String(80), nullable=True)
    exam_year = db.Column(db.Integer, nullable=True, index=True)

    # Official dates (all nullable - only filled after verification)
    notification_date = db.Column(db.Date, nullable=True)
    application_start_date = db.Column(db.Date, nullable=True)
    application_last_date = db.Column(db.Date, nullable=True, index=True)
    late_fee_last_date = db.Column(db.Date, nullable=True)
    correction_window_start = db.Column(db.Date, nullable=True)
    correction_window_end = db.Column(db.Date, nullable=True)
    exam_date = db.Column(db.Date, nullable=True)
    admit_card_date = db.Column(db.Date, nullable=True)
    result_date = db.Column(db.Date, nullable=True)

    # Eligibility snapshot from the notification
    qualification = db.Column(db.String(200), nullable=True)
    education_level = db.Column(db.String(60), nullable=True, index=True)  # 10th/12th/Graduation…
    min_age = db.Column(db.Integer, nullable=True)
    max_age = db.Column(db.Integer, nullable=True)
    age_relaxation_info = db.Column(db.Text, nullable=True)
    gender_eligibility = db.Column(db.String(60), nullable=True)  # as officially specified

    # {"general": 100, "obc": 100, "sc_st": 25, "female": 25, "note": "..."}
    application_fees = db.Column(JSONB, nullable=True)
    state = db.Column(db.String(60), nullable=False, default="All India", index=True)

    # Official links + uploaded notification PDF (stored like other documents)
    official_notification_url = db.Column(db.String(500), nullable=True)
    official_application_url = db.Column(db.String(500), nullable=True)
    notification_pdf_path = db.Column(db.String(255), nullable=True)  # static/uploads path

    # Extra documents demanded by THIS notification beyond the service default
    required_documents_extra = db.Column(JSONB, nullable=True)  # list[str]

    # Lifecycle / verification
    exam_status = db.Column(db.String(20), nullable=False, default="upcoming",
                            index=True)  # EXAM_CYCLE_STATUSES
    officially_extended = db.Column(db.Boolean, nullable=False, default=False)
    extension_note = db.Column(db.String(300), nullable=True)

    is_published = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)

    # Official-source monitoring: who verified what, when. A cycle whose source
    # cannot be re-verified is FLAGGED for admin review, never silently edited.
    verification_source = db.Column(db.String(300), nullable=True)
    last_verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    needs_review = db.Column(db.Boolean, nullable=False, default=False, index=True)
    review_note = db.Column(db.String(300), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    service = db.relationship("Service", back_populates="exam_cycles")

    @property
    def status_label(self) -> str:
        from ..utils.i18n import pick
        pair = EXAM_STATUS_LABELS.get(self.exam_status)
        return pick(*pair) if pair else self.exam_status.title()

    @property
    def fee_note(self) -> str:
        if not self.application_fees:
            return ""
        parts = []
        for key, label in (("general", "General"), ("obc", "OBC/EBC"), ("sc_st", "SC/ST"),
                           ("female", "Female"), ("other", "Other")):
            value = self.application_fees.get(key)
            if value not in (None, ""):
                parts.append(f"{label}: ₹{value}")
        note = self.application_fees.get("note") or ""
        text = " · ".join(parts)
        return f"{text} {note}".strip()

    def __repr__(self):  # pragma: no cover
        return f"<ExamCycle {self.cycle_slug} {self.exam_status}>"


Index("ix_exam_cycles_status_deadline", ExamCycle.exam_status, ExamCycle.application_last_date)
