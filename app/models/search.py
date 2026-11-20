"""Central directory of official government portals + search helpers.

OfficialPortal: every service references the portal where its work actually
happens. The shop is never presented as a government portal; the portal link
always opens the real official website.

SearchAlias / SearchQueryStat: Hindi, romanised Hindi ("aay praman patra") and
colloquial terms mapped onto the same service record, plus anonymous
popularity counters for the "popular searches" chips.
"""
from sqlalchemy import String, Text, Boolean, Integer, DateTime, ForeignKey, UniqueConstraint

from ..extensions import db
from .admin import utcnow


class OfficialPortal(db.Model):
    __tablename__ = "official_portals"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    name_en = db.Column(db.String(200), nullable=False)
    name_hi = db.Column(db.String(200), nullable=True)
    url = db.Column(db.String(500), nullable=False)
    state = db.Column(db.String(60), nullable=False, default="All India")  # Bihar / Central / …
    department = db.Column(db.String(160), nullable=True)
    description_en = db.Column(db.Text, nullable=True)
    description_hi = db.Column(db.Text, nullable=True)
    # Optional permitted official feed for the (future) monitoring mechanism -
    # RSS/Atom only; never aggressive scraping, never CAPTCHA bypass.
    official_feed_url = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    @property
    def name(self) -> str:
        from ..utils.i18n import pick
        return pick(self.name_en, self.name_hi)

    def __repr__(self):  # pragma: no cover
        return f"<OfficialPortal {self.slug}>"


class SearchAlias(db.Model):
    """One search phrase -> target (service or category). Admin-managed."""
    __tablename__ = "search_aliases"
    __table_args__ = (UniqueConstraint("alias", name="uq_search_alias"),)

    id = db.Column(db.Integer, primary_key=True)
    alias = db.Column(db.String(200), nullable=False, index=True)  # normalised: lower-case
    service_id = db.Column(db.Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=True)
    category_id = db.Column(db.Integer, ForeignKey("service_categories.id", ondelete="CASCADE"),
                            nullable=True)
    note = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    service = db.relationship("Service", foreign_keys=[service_id])
    category = db.relationship("ServiceCategory", foreign_keys=[category_id])

    @property
    def target(self):
        """The service or category this alias resolves to (or None)."""
        return self.service or self.category


class SearchQueryStat(db.Model):
    """Anonymous search-term counter (no IP, no identity) powering the
    'popular searches' chips on the catalogue page."""
    __tablename__ = "search_query_stats"
    __table_args__ = (UniqueConstraint("term", name="uq_search_term"),)

    id = db.Column(db.Integer, primary_key=True)
    term = db.Column(db.String(120), nullable=False, index=True)
    count = db.Column(db.Integer, nullable=False, default=1)
    last_searched_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
