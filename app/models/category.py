"""Service categories - fully admin-managed, never hardcoded.

`group` is a coarse section key used by the homepage and admin filtered lists
(documents / identity / education / scholarship / exam / scheme / business /
transport / digital / legal / utility / other).
"""
from sqlalchemy import String, Text, Boolean, Integer, DateTime

from ..extensions import db
from .admin import utcnow

CATEGORY_GROUPS = (
    "documents", "identity", "education", "scholarship", "exam",
    "scheme", "business", "transport", "digital", "legal", "utility", "other",
)


class ServiceCategory(db.Model):
    __tablename__ = "service_categories"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(140), unique=True, nullable=False, index=True)
    name_en = db.Column(db.String(160), nullable=False)
    name_hi = db.Column(db.String(160), nullable=True)
    description_en = db.Column(db.Text, nullable=True)
    description_hi = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(60), nullable=True)   # bootstrap icon class, e.g. bi-bank
    image_path = db.Column(db.String(255), nullable=True)  # public static/uploads path
    group = db.Column(db.String(30), nullable=False, default="other", index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    services = db.relationship(
        "Service", back_populates="category", lazy="dynamic",
        order_by="Service.sort_order, Service.id",
    )
    subcategories = db.relationship(
        "ServiceSubcategory", back_populates="category",
        cascade="all, delete-orphan", order_by="ServiceSubcategory.sort_order, ServiceSubcategory.id",
    )

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
        return self.services.filter_by(is_active=True).count()

    def __repr__(self):  # pragma: no cover
        return f"<ServiceCategory {self.slug}>"
