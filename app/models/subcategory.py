"""Subcategories inside a service category (two-level catalogue).

Categories stay top-level; subcategories let a category such as
"Government Certificates" hold Caste / Income / Residential groups without
creating dozens of near-empty top-level categories. Fully admin-managed.
"""
from sqlalchemy import String, Text, Boolean, Integer, DateTime, ForeignKey, UniqueConstraint

from ..extensions import db
from .admin import utcnow
from .service import Service


class ServiceSubcategory(db.Model):
    __tablename__ = "service_subcategories"
    __table_args__ = (UniqueConstraint("category_id", "slug", name="uq_subcategory_slug_per_category"),)

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, ForeignKey("service_categories.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    slug = db.Column(db.String(140), nullable=False, index=True)
    name_en = db.Column(db.String(160), nullable=False)
    name_hi = db.Column(db.String(160), nullable=True)
    description_en = db.Column(db.Text, nullable=True)
    description_hi = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(60), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    category = db.relationship("ServiceCategory", back_populates="subcategories")

    @property
    def name(self) -> str:
        from ..utils.i18n import pick
        return pick(self.name_en, self.name_hi)

    @property
    def description(self) -> str:
        from ..utils.i18n import pick
        return pick(self.description_en, self.description_hi)

    @property
    def active_service_count(self) -> int:
        return Service.query.filter_by(subcategory_id=self.id, is_active=True,
                                       is_archived=False).count()

    def __repr__(self):  # pragma: no cover
        return f"<ServiceSubcategory {self.slug}>"
