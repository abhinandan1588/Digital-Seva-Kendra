"""Services and their per-service configuration: dynamic form fields and
document requirements. Everything here is editable from the admin dashboard
without touching application code.
"""
from sqlalchemy import String, Text, Numeric, Boolean, Integer, DateTime, ForeignKey, UniqueConstraint

from ..extensions import db
from ..models import JSONB
from .admin import utcnow

FIELD_TYPES = (
    "text", "number", "email", "mobile", "date", "textarea",
    "select", "radio", "checkbox", "file", "file_multi", "image",
)
FILE_FIELD_TYPES = ("file", "file_multi", "image")

# Compliance capability of a service (Part 11). Only RESTRICTED_* is never
# orderable; customers are told exactly who performs the work.
CAPABILITY_INTERNAL = "internal_service"          # done inside the shop/website
CAPABILITY_ASSISTED = "assisted_application"      # customer data + admin submits on portal
CAPABILITY_INTEGRATION = "authorized_integration" # real authorized API/partner
CAPABILITY_EXTERNAL = "external_portal"           # customer redirected to official portal
CAPABILITY_RESTRICTED = "restricted_authorization_required"  # disabled until authorized

CAPABILITY_TYPES = (
    CAPABILITY_INTERNAL, CAPABILITY_ASSISTED, CAPABILITY_INTEGRATION,
    CAPABILITY_EXTERNAL, CAPABILITY_RESTRICTED,
)

CAPABILITY_LABELS = {
    CAPABILITY_INTERNAL: ("Shop Service (done here)", "दुकान सेवा (यहीं संपन्न)"),
    CAPABILITY_ASSISTED: ("Assisted Application", "सहायता प्राप्त आवेदन"),
    CAPABILITY_INTEGRATION: ("Authorized Integration", "अधिकृत इंटीग्रेशन"),
    CAPABILITY_EXTERNAL: ("Official Portal (assistance)", "सरकारी पोर्टल (सहायता)"),
    CAPABILITY_RESTRICTED: ("Authorization Required", "अधिकृत आवश्यक"),
}

CAPABILITY_DESCRIPTIONS = {
    CAPABILITY_INTERNAL:
        ("This work is completed within our centre (typing, printing, PDF tools, photo work).",
         "यह कार्य हमारे केंद्र में ही संपन्न होता है (टाइपिंग, प्रिंटिंग, PDF टूल, फोटो कार्य)।"),
    CAPABILITY_ASSISTED:
        ("You submit details and documents here; our operator fills and submits the application on the official portal for you.",
         "आप यहाँ विवरण और दस्तावेज़ देते हैं; हमारा ऑपरेटर सरकारी पोर्टल पर आवेदन भरकर जमा करता है।"),
    CAPABILITY_INTEGRATION:
        ("This service is performed through an authorized partner/API integration.",
         "यह सेवा अधिकृत पार्टनर/API इंटीग्रेशन के माध्यम से की जाती है।"),
    CAPABILITY_EXTERNAL:
        ("You will be directed to the official government portal; we assist you with preparation and submission.",
         "आपको सरकारी पोर्टल पर भेजा जाएगा; हम तैयारी और जमा करने में सहायता करते हैं।"),
    CAPABILITY_RESTRICTED:
        ("Currently unavailable - this service requires a specific authorization or licensed professional and is activated only after verification.",
         "अभी उपलब्ध नहीं - इस सेवा के लिए विशेष अधिकृत या लाइसेंसी पेशेवर आवश्यक है; सत्यापन के बाद ही चालू की जाएगी।"),
}


def capability_label(value: str) -> str:
    from ..utils.i18n import pick
    pair = CAPABILITY_LABELS.get(value)
    return pick(*pair) if pair else (value or "").replace("_", " ").title()


def capability_description(value: str) -> str:
    from ..utils.i18n import pick
    pair = CAPABILITY_DESCRIPTIONS.get(value)
    return pick(*pair) if pair else ""


class Service(db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, ForeignKey("service_categories.id", ondelete="RESTRICT"),
                            nullable=False, index=True)
    subcategory_id = db.Column(db.Integer, ForeignKey("service_subcategories.id", ondelete="SET NULL"),
                               nullable=True, index=True)
    slug = db.Column(db.String(160), unique=True, nullable=False, index=True)
    name_en = db.Column(db.String(200), nullable=False)
    name_hi = db.Column(db.String(200), nullable=True)
    description_en = db.Column(db.Text, nullable=True)
    description_hi = db.Column(db.Text, nullable=True)
    instructions_en = db.Column(db.Text, nullable=True)
    instructions_hi = db.Column(db.Text, nullable=True)
    eligibility_en = db.Column(db.Text, nullable=True)
    eligibility_hi = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(60), nullable=True)
    image_path = db.Column(db.String(255), nullable=True)

    # Compliance: who performs this service and through which channel.
    capability_type = db.Column(db.String(40), nullable=False, default="assisted_application",
                                index=True)
    official_portal_id = db.Column(db.Integer, ForeignKey("official_portals.id", ondelete="SET NULL"),
                                   nullable=True)
    official_info_url = db.Column(db.String(500), nullable=True)  # direct info/notification page
    # Extra Hindi/romanised keywords for search ("aay", "naali", "avas" ...)
    search_keywords = db.Column(db.String(400), nullable=True)
    # Free-form structured extras (scholarship year, scheme code, …)
    meta = db.Column(JSONB, nullable=True)

    # Exam-type service template: cycles (notifications) hang off it.
    is_examination = db.Column(db.Boolean, nullable=False, default=False, index=True)

    # Prices (rupees). service_charge is the shop's own charge; official_fee and
    # other_charge are government/department fees passed through at cost.
    service_charge = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    official_fee = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    other_charge = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    processing_time_en = db.Column(db.String(120), nullable=True)
    processing_time_hi = db.Column(db.String(120), nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    is_featured = db.Column(db.Boolean, nullable=False, default=False)
    is_popular = db.Column(db.Boolean, nullable=False, default=False)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    category = db.relationship("ServiceCategory", back_populates="services")
    subcategory = db.relationship("ServiceSubcategory")
    official_portal = db.relationship("OfficialPortal")
    exam_cycles = db.relationship("ExamCycle", back_populates="service",
                                  cascade="all, delete-orphan",
                                  order_by="ExamCycle.id.desc()")
    form_fields = db.relationship(
        "ServiceFormField", back_populates="service", cascade="all, delete-orphan",
        order_by="ServiceFormField.sort_order, ServiceFormField.id", lazy="dynamic",
    )
    document_requirements = db.relationship(
        "ServiceDocumentRequirement", back_populates="service", cascade="all, delete-orphan",
        order_by="ServiceDocumentRequirement.sort_order, ServiceDocumentRequirement.id", lazy="dynamic",
    )

    # --- behaviour ---------------------------------------------------------
    @property
    def is_restricted(self) -> bool:
        return self.capability_type == CAPABILITY_RESTRICTED

    @property
    def is_orderable(self) -> bool:
        """Restricted services are visible but never orderable."""
        return self.is_active and not self.is_restricted

    @property
    def open_cycles(self):
        """Published, non-archived cycles whose application window is open
        right now (recomputed, never trusting a stale stored status)."""
        from .exam import ExamCycle
        from ..utils.exams import cycle_accepting_applications
        cycles = [c for c in self.exam_cycles
                  if c.is_published and not c.is_archived and c.exam_status != "cancelled"]
        return [c for c in cycles if cycle_accepting_applications(c)]

    @property
    def has_cycles(self) -> bool:
        return any(not c.is_archived for c in self.exam_cycles)

    @property
    def name(self) -> str:
        from ..utils.i18n import pick
        return pick(self.name_en, self.name_hi)

    @property
    def description(self) -> str:
        from ..utils.i18n import pick
        return pick(self.description_en, self.description_hi)

    @property
    def instructions(self) -> str:
        from ..utils.i18n import pick
        return pick(self.instructions_en, self.instructions_hi)

    @property
    def eligibility(self) -> str:
        from ..utils.i18n import pick
        return pick(self.eligibility_en, self.eligibility_hi)

    @property
    def processing_time(self) -> str:
        from ..utils.i18n import pick
        return pick(self.processing_time_en, self.processing_time_hi)

    @property
    def total_price(self):
        return (self.service_charge or 0) + (self.official_fee or 0) + (self.other_charge or 0)

    @property
    def active_form_fields(self):
        return self.form_fields.filter_by(is_active=True).all()

    @property
    def active_document_requirements(self):
        return self.document_requirements.filter_by(is_active=True).all()

    def __repr__(self):  # pragma: no cover
        return f"<Service {self.slug}>"


class ServiceFormField(db.Model):
    """One configurable field of a service's application form."""
    __tablename__ = "service_form_fields"
    __table_args__ = (UniqueConstraint("service_id", "field_key", name="uq_form_field_key"),)

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, ForeignKey("services.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    field_key = db.Column(db.String(60), nullable=False)  # stable key used in stored values
    label_en = db.Column(db.String(200), nullable=False)
    label_hi = db.Column(db.String(200), nullable=True)
    field_type = db.Column(db.String(20), nullable=False, default="text")
    placeholder = db.Column(db.String(200), nullable=True)
    help_text_en = db.Column(db.String(300), nullable=True)
    help_text_hi = db.Column(db.String(300), nullable=True)
    options = db.Column(JSONB, nullable=True)  # [{"en": "...", "hi": "..."}] for select/radio/checkbox
    is_required = db.Column(db.Boolean, nullable=False, default=True)
    min_length = db.Column(db.Integer, nullable=True)
    max_length = db.Column(db.Integer, nullable=True)
    min_value = db.Column(db.Numeric(12, 2), nullable=True)
    max_value = db.Column(db.Numeric(12, 2), nullable=True)
    allowed_extensions = db.Column(JSONB, nullable=True)  # ["pdf", "jpg", ...]
    max_file_mb = db.Column(db.Integer, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    service = db.relationship("Service", back_populates="form_fields")

    @property
    def label(self) -> str:
        from ..utils.i18n import pick
        return pick(self.label_en, self.label_hi)

    @property
    def help_text(self) -> str:
        from ..utils.i18n import pick
        return pick(self.help_text_en, self.help_text_hi)

    @property
    def is_file_field(self) -> bool:
        return self.field_type in FILE_FIELD_TYPES


class ServiceDocumentRequirement(db.Model):
    """One required/optional document of a service (Aadhaar, photo, ...).

    Optionally linked to the reusable DocumentTemplate it was created from -
    the per-service copy can then be customised without touching the template.
    """
    __tablename__ = "service_document_requirements"

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, ForeignKey("services.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    document_template_id = db.Column(db.Integer, ForeignKey("document_templates.id",
                                                            ondelete="SET NULL"), nullable=True)
    label_en = db.Column(db.String(200), nullable=False)
    label_hi = db.Column(db.String(200), nullable=True)
    description_en = db.Column(db.String(300), nullable=True)
    description_hi = db.Column(db.String(300), nullable=True)
    allowed_extensions = db.Column(JSONB, nullable=False, default=lambda: ["pdf", "jpg", "jpeg", "png"])
    max_file_mb = db.Column(db.Integer, nullable=False, default=5)
    is_required = db.Column(db.Boolean, nullable=False, default=True)
    allow_multiple = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    service = db.relationship("Service", back_populates="document_requirements")
    document_template = db.relationship("DocumentTemplate")

    @property
    def label(self) -> str:
        from ..utils.i18n import pick
        return pick(self.label_en, self.label_hi)

    @property
    def description(self) -> str:
        from ..utils.i18n import pick
        return pick(self.description_en, self.description_hi)
