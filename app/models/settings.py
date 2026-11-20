"""Website settings: a flexible key-value store loaded per request.

Groups: general, contact, social, legal, payment, homepage, notification
templates. Admin edits these in Website / Payment / Drive settings pages.
"""
from sqlalchemy import String, Text, DateTime, ForeignKey

from ..extensions import db
from .admin import utcnow

DEFAULT_SETTINGS = {
    # general
    "shop_name": ("Digital Seva Kendra", "डिजिटल सेवा केंद्र"),
    "shop_name_hi": ("डिजिटल सेवा केंद्र", None),
    "shop_tagline": ("Government & Private Services Online", None),
    "shop_tagline_hi": ("सरकारी एवं निजी सेवाएँ ऑनलाइन", None),
    "default_language": "en",
    # contact
    "shop_address": ("Main Market Road, Near Bus Stand", None),
    "shop_mobile": ("9000000000", None),
    "shop_whatsapp": ("9000000000", None),
    "shop_email": ("contact@example.com", None),
    "working_hours": ("Mon - Sat, 9:00 AM - 8:00 PM", None),
    # homepage
    "homepage_banner_title": ("Apply for government & private services from home", None),
    "homepage_banner_title_hi": ("घर बैठे सरकारी एवं निजी सेवाओं के लिए आवेदन करें", None),
    "homepage_banner_subtitle": (
        "Fill the form, upload documents, pay by UPI and track your application - no account needed.",
        None),
    "homepage_banner_subtitle_hi": (
        "फॉर्म भरें, दस्तावेज़ अपलोड करें, UPI से भुगतान करें और अपने आवेदन की स्थिति देखें - खाता बनाने की ज़रूरत नहीं।",
        None),
    # payment
    "upi_id": ("shop@upi", None),
    "upi_merchant_name": ("Digital Seva Kendra", None),
    "payment_instructions": (
        "Scan the QR with any UPI app, pay the exact amount shown, then submit your UPI transaction ID (UTR) and a screenshot of the payment.",
        None),
    "payment_instructions_hi": (
        "किसी भी UPI ऐप से QR स्कैन करें, दिखाई गई सटीक राशि का भुगतान करें, फिर अपनी UPI ट्रांज़ैक्शन आईडी (UTR) और भुगतान का स्क्रीनशॉट जमा करें।",
        None),
    "payment_support_info": ("Payment problem? Call us on the shop number given above.", None),
    "payment_support_info_hi": ("भुगतान में समस्या? ऊपर दिए गए दुकान के नंबर पर कॉल करें।", None),
    # social
    "social_facebook": ("", None),
    "social_instagram": ("", None),
    "social_youtube": ("", None),
    "footer_text": ("Disclaimer: We are a private service centre helping citizens with application submission. "
                    "We do not claim any official government affiliation unless explicitly stated.", None),
    "footer_text_hi": ("अस्वीकरण: हम नागरिकों को आवेदन जमा करने में सहायता करने वाला एक निजी सेवा केंद्र हैं। "
                       "जब तक स्पष्ट रूप से उल्लेख न हो, हम किसी सरकारी संबद्धता का दावा नहीं करते।", None),
    # legal (long text, editable)
    "privacy_policy": (None, None),
    "terms_conditions": (None, None),
    "privacy_policy_hi": (None, None),
    "terms_conditions_hi": (None, None),
}


class WebsiteSetting(db.Model):
    __tablename__ = "website_settings"

    key = db.Column(db.String(80), primary_key=True)
    value_text = db.Column(db.Text, nullable=True)
    group = db.Column(db.String(30), nullable=False, default="general")
    updated_by_admin_id = db.Column(db.Integer, ForeignKey("admin_users.id", ondelete="SET NULL"),
                                    nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    def __repr__(self):  # pragma: no cover
        return f"<WebsiteSetting {self.key}>"


def ensure_default_settings() -> None:
    """Insert any missing defaults (idempotent; called by CLI + admin pages)."""
    from ..extensions import db
    existing = {s.key for s in db.session.query(WebsiteSetting.key).all()}
    for key, default in DEFAULT_SETTINGS.items():
        if key not in existing:
            en, hi = default
            value = en if en is not None else ""
            db.session.add(WebsiteSetting(key=key, value_text=value, group=_group_for(key)))
    db.session.commit()


def _group_for(key: str) -> str:
    base = key[:-3] if key.endswith("_hi") else key
    if base in ("privacy_policy", "terms_conditions"):
        return "legal"
    if base in ("upi_id", "upi_merchant_name", "payment_instructions", "payment_support_info"):
        return "payment"
    if base.startswith(("social_", "footer_text")):
        return "social"
    if base in ("shop_address", "shop_mobile", "shop_whatsapp", "shop_email", "working_hours"):
        return "contact"
    if base.startswith("homepage_"):
        return "homepage"
    return "general"
