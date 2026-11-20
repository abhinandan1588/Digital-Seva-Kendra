"""Public website: homepage, static pages, language switcher."""
from flask import Blueprint, render_template, request, redirect, url_for, session

from ..models import ServiceCategory, Service
from ..utils.i18n import set_lang, t, current_lang, pick
from ..utils.settings import get_setting

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def home():
    from ..utils.home_sections import build_home_sections
    featured = (Service.query.filter_by(is_active=True, is_featured=True)
                .order_by(Service.sort_order, Service.id).limit(8).all())
    categories = (ServiceCategory.query.filter_by(is_active=True)
                  .order_by(ServiceCategory.sort_order, ServiceCategory.id).all())
    sections = build_home_sections()
    return render_template("public/home.html", featured_services=featured,
                           categories=categories, sections=sections["sections"],
                           has_notifications=sections["has_notifications"])


@public_bp.route("/about")
def about():
    return render_template("public/about.html")


@public_bp.route("/contact")
def contact():
    return render_template("public/contact.html")


@public_bp.route("/faq")
def faq():
    return render_template("public/faq.html")


@public_bp.route("/privacy")
def privacy():
    lang = current_lang()
    body = get_setting("privacy_policy" if lang == "en" else "privacy_policy_hi") \
        or get_setting("privacy_policy")
    return render_template("public/legal.html", title=t("Privacy Policy", "गोपनीयता नीति"), body=body)


@public_bp.route("/terms")
def terms():
    lang = current_lang()
    body = get_setting("terms_conditions" if lang == "en" else "terms_conditions_hi") \
        or get_setting("terms_conditions")
    return render_template("public/legal.html", title=t("Terms & Conditions", "नियम एवं शर्तें"), body=body)


@public_bp.route("/set-lang/<lang_code>")
def set_language(lang_code):
    set_lang(lang_code)
    return redirect(request.referrer or url_for("public.home"))
