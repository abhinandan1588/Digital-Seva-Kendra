"""Reusable document requirement templates.

The admin defines standard documents once (Photograph, Signature, Aadhaar,
Class 10 certificate, …) and attaches them to services in one click; attaching
copies the template into a per-service ServiceDocumentRequirement row (which
can then be customised per service without touching the shared template).
"""
from sqlalchemy import String, Text, Boolean, Integer, DateTime

from ..extensions import db
from ..models import JSONB
from .admin import utcnow


class DocumentTemplate(db.Model):
    __tablename__ = "document_templates"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name_en = db.Column(db.String(200), nullable=False)
    name_hi = db.Column(db.String(200), nullable=True)
    description_en = db.Column(db.String(300), nullable=True)
    description_hi = db.Column(db.String(300), nullable=True)

    allowed_extensions = db.Column(JSONB, nullable=False,
                                   default=lambda: ["pdf", "jpg", "jpeg", "png"])
    max_file_mb = db.Column(db.Integer, nullable=False, default=5)
    is_required = db.Column(db.Boolean, nullable=False, default=True)
    allow_multiple = db.Column(db.Boolean, nullable=False, default=False)

    # Optional pixel-dimension guidance (e.g. exam photos 20-50 KB, 200x230 px)
    min_width = db.Column(db.Integer, nullable=True)
    max_width = db.Column(db.Integer, nullable=True)
    min_height = db.Column(db.Integer, nullable=True)
    max_height = db.Column(db.Integer, nullable=True)
    compression_note_en = db.Column(db.String(300), nullable=True)
    compression_note_hi = db.Column(db.String(300), nullable=True)
    # Document must be issued within the last N days when set (e.g. medical certificates)
    expires_after_days = db.Column(db.Integer, nullable=True)

    # "general" | "exam" | "certificate" | "identity" | "vehicle" | "other"
    template_group = db.Column(db.String(30), nullable=False, default="general", index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    @property
    def name(self) -> str:
        from ..utils.i18n import pick
        return pick(self.name_en, self.name_hi)

    @property
    def description(self) -> str:
        from ..utils.i18n import pick
        return pick(self.description_en, self.description_hi)

    @property
    def compression_note(self) -> str:
        from ..utils.i18n import pick
        return pick(self.compression_note_en, self.compression_note_hi)

    def __repr__(self):  # pragma: no cover
        return f"<DocumentTemplate {self.slug}>"
