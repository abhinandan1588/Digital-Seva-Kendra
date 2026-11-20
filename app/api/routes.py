"""JSON API for the React SPA (frontend/) + SPA static serving.

Mirrors the public customer flow (catalogue, cart, dynamic forms, checkout,
UPI payment, secure tracking) using the SAME session cart, validators,
pricing, checkout and tracking helpers as the Jinja templates — so the
security guarantees are identical for both frontends:

- prices always recomputed server-side from the DB (never from the client)
- uploads validated by content sniffing and staged until checkout
- tracking token/PIN stored only as SHA-256 hashes
- rate limits on checkout / tracking / proof submission

Content fields are returned in BOTH languages (en/hi); the React app picks
per user language. Validation problems return stable error codes that the
client translates (frontend/src/i18n.js). The admin area stays server-
rendered and is intentionally not exposed here.
"""
import os

from flask import (Blueprint, current_app, jsonify, request, session,
                   send_from_directory)
from werkzeug.exceptions import NotFound
from sqlalchemy import or_

from ..extensions import db, limiter
from ..models import Service, ServiceCategory, Order, StatusHistory, UploadedDocument
from ..utils.cart import get_cart, add_service, remove_item, clear_cart, find_item, cart_service_count
from ..utils.checkout import (create_order_from_cart, CheckoutError,
                              item_form_data, drop_item_form_data)
from ..utils.customer_common import (get_profile, get_answers, save_profile,
                                     remember_answers, remember_raw_answers,
                                     wallet_json, add_wallet_files,
                                     remove_wallet_entry, suggest_wallet_entry)
from ..utils.dynamic_forms import (validate_dynamic_form, validate_document_uploads,
                                   stage_field_files, stage_requirement_files, stage_files)
from ..utils.files import validate_upload
from ..utils.order_ids import verify_tracking
from ..utils.payments import build_upi_intent
from ..utils.settings import get_setting
from ..utils.status import set_payment_status, set_order_status
from ..config import Config

api_bp = Blueprint("api", __name__, url_prefix="/api")
spa_bp = Blueprint("spa", __name__)

PROOF_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _money(value) -> str:
    return str(value) if value is not None else "0.00"


def _category_json(cat: ServiceCategory) -> dict:
    return {
        "id": cat.id,
        "slug": cat.slug,
        "name_en": cat.name_en,
        "name_hi": cat.name_hi or "",
        "icon": cat.icon or "bi-folder2",
        "service_count": cat.active_service_count,
    }


def _service_json(s: Service) -> dict:
    return {
        "id": s.id,
        "slug": s.slug,
        "name_en": s.name_en,
        "name_hi": s.name_hi or "",
        "description_en": s.description_en or "",
        "description_hi": s.description_hi or "",
        "service_charge": _money(s.service_charge),
        "official_fee": _money(s.official_fee),
        "other_charge": _money(s.other_charge),
        "total_price": _money(s.total_price),
        "processing_time_en": s.processing_time_en or "",
        "processing_time_hi": s.processing_time_hi or "",
        "image_url": f"/static/{s.image_path}" if s.image_path else "",
        "is_featured": bool(s.is_featured),
        # additive fields (catalogue expansion) - existing clients ignore them
        "is_popular": bool(s.is_popular),
        "is_examination": bool(s.is_examination),
        "capability_type": s.capability_type,
        "is_orderable": s.is_orderable,
        "eligibility_en": s.eligibility_en or "",
        "eligibility_hi": s.eligibility_hi or "",
        "icon": s.icon or (s.category.icon if s.category else "") or "",
        "search_keywords": s.search_keywords or "",
        "subcategory": {"id": s.subcategory.id, "slug": s.subcategory.slug,
                        "name_en": s.subcategory.name_en, "name_hi": s.subcategory.name_hi or ""}
        if s.subcategory else None,
        "official_portal": ({"name": s.official_portal.name_en, "url": s.official_portal.url}
                            if s.official_portal and s.official_portal.is_active else None),
        "official_info_url": s.official_info_url or "",
        "category": _category_json(s.category) if s.category else None,
    }


def _form_field_json(f) -> dict:
    return {
        "id": f.id,
        "field_key": f.field_key,
        "label_en": f.label_en,
        "label_hi": f.label_hi or "",
        "field_type": f.field_type,
        "placeholder": f.placeholder or "",
        "help_text_en": f.help_text_en or "",
        "help_text_hi": f.help_text_hi or "",
        "options": f.options or [],
        "is_required": bool(f.is_required),
        "min_length": f.min_length,
        "max_length": f.max_length,
        "min_value": _money(f.min_value) if f.min_value is not None else None,
        "max_value": _money(f.max_value) if f.max_value is not None else None,
        "allowed_extensions": f.allowed_extensions or [],
        "max_file_mb": f.max_file_mb or Config.UPLOAD_DEFAULT_MAX_MB,
    }


def _requirement_json(r) -> dict:
    return {
        "id": r.id,
        "label_en": r.label_en,
        "label_hi": r.label_hi or "",
        "description_en": r.description_en or "",
        "description_hi": r.description_hi or "",
        "allowed_extensions": r.allowed_extensions or [],
        "max_file_mb": r.max_file_mb,
        "is_required": bool(r.is_required),
        "allow_multiple": bool(r.allow_multiple),
    }


def _bad(error_code: str, status: int = 400, **extra):
    payload = {"ok": False, "error": error_code}
    payload.update(extra)
    return jsonify(payload), status


@api_bp.route("/set-lang/<lang_code>", methods=["POST"])
def api_set_lang(lang_code):
    """Keep the server session language in sync with the SPA language, so
    bilingual option values validate consistently (see i18n.pick)."""
    from ..utils.i18n import set_lang
    if lang_code in Config.SUPPORTED_LANGUAGES:
        set_lang(lang_code)
    return jsonify({"ok": True, "lang": lang_code})


# ---------------------------------------------------------------------------
# Site / catalogue
# ---------------------------------------------------------------------------

PUBLIC_SETTING_KEYS = (
    "shop_name", "shop_name_hi", "shop_tagline", "shop_tagline_hi",
    "default_language", "shop_address", "shop_mobile", "shop_whatsapp",
    "shop_email", "working_hours", "homepage_banner_title",
    "homepage_banner_title_hi", "homepage_banner_subtitle",
    "homepage_banner_subtitle_hi", "social_facebook", "social_instagram",
    "social_youtube", "footer_text", "footer_text_hi",
)


@api_bp.route("/site")
def site():
    settings = {k: get_setting(k) for k in PUBLIC_SETTING_KEYS}
    categories = (ServiceCategory.query.filter_by(is_active=True)
                  .order_by(ServiceCategory.sort_order, ServiceCategory.id).all())
    featured = (Service.query.filter_by(is_active=True, is_featured=True)
                .order_by(Service.sort_order, Service.id).limit(8).all())
    return jsonify({
        "settings": settings,
        "categories": [_category_json(c) for c in categories],
        "featured_services": [_service_json(s) for s in featured],
    })


@api_bp.route("/services")
def services_list():
    query = (request.args.get("q") or "").strip()
    category_slug = (request.args.get("category") or "").strip()

    services_query = Service.query.filter_by(is_active=True)
    if category_slug:
        selected = ServiceCategory.query.filter_by(slug=category_slug).first()
        if selected is None:
            return jsonify({"services": [], "categories": []})
        services_query = services_query.filter_by(category_id=selected.id)
    if query:
        like = f"%{query}%"
        services_query = services_query.filter(or_(
            Service.name_en.ilike(like), Service.name_hi.ilike(like),
            Service.description_en.ilike(like), Service.description_hi.ilike(like),
        ))
    services = services_query.order_by(Service.sort_order, Service.id).all()
    categories = (ServiceCategory.query.filter_by(is_active=True)
                  .order_by(ServiceCategory.sort_order, ServiceCategory.id).all())
    return jsonify({
        "services": [_service_json(s) for s in services],
        "categories": [_category_json(c) for c in categories],
    })


@api_bp.route("/services/<slug>")
def service_detail(slug):
    service = Service.query.filter_by(slug=slug, is_active=True).first()
    if service is None:
        return _bad("not_found", 404)
    data = _service_json(service)
    data["instructions_en"] = service.instructions_en or ""
    data["instructions_hi"] = service.instructions_hi or ""
    from ..utils.exams import deadline_info
    return jsonify({
        "service": data,
        "form_fields": [_form_field_json(f) for f in service.active_form_fields],
        "document_requirements": [_requirement_json(r) for r in service.active_document_requirements],
        "exam_cycles": [{
            "id": c.id, "cycle_slug": c.cycle_slug, "display_name": c.display_name,
            "organization": c.organization, "advertisement_number": c.advertisement_number or "",
            "application_last_date": c.application_last_date.isoformat() if c.application_last_date else None,
            "status": c.exam_status, "deadline": deadline_info(c),
        } for c in service.open_cycles],
    })


@api_bp.route("/search/suggest")
def search_suggest():
    from ..utils.search import suggest
    q = (request.args.get("q") or "").strip()
    return jsonify({"suggestions": suggest(q, limit=8)})


@api_bp.route("/categories/<slug>")
def category_detail(slug):
    """Category page payload with subcategories + services."""
    category = ServiceCategory.query.filter_by(slug=slug, is_active=True).first()
    if category is None:
        return _bad("not_found", 404)
    from ..models import ServiceSubcategory
    subs = (ServiceSubcategory.query.filter_by(category_id=category.id, is_active=True)
            .order_by(ServiceSubcategory.sort_order).all())
    services = (Service.query.filter(Service.is_active.is_(True),
                                     Service.is_archived.is_(False),
                                     Service.category_id == category.id)
                .order_by(Service.sort_order, Service.id).all())
    return jsonify({
        "category": {**_category_json(category),
                     "description_en": category.description_en or "",
                     "description_hi": category.description_hi or ""},
        "subcategories": [{"id": s.id, "slug": s.slug, "name_en": s.name_en,
                           "name_hi": s.name_hi or ""} for s in subs],
        "services": [_service_json(s) for s in services],
    })


@api_bp.route("/exams")
def exams_list():
    """Published examination cycles with filters (additive; SPA may use it)."""
    from ..models import ExamCycle
    from ..utils.exams import refresh_all_cycle_statuses, deadline_info, today, filter_options
    from datetime import timedelta
    refresh_all_cycle_statuses()
    organization = (request.args.get("organization") or "").strip()
    education_level = (request.args.get("education_level") or "").strip()
    status = (request.args.get("status") or "").strip()
    state = (request.args.get("state") or "").strip()
    query = ExamCycle.query.filter(ExamCycle.is_published.is_(True),
                                   ExamCycle.is_archived.is_(False))
    if organization:
        query = query.filter(ExamCycle.organization == organization)
    if education_level:
        query = query.filter(ExamCycle.education_level == education_level)
    if status in ("upcoming", "open", "closed"):
        query = query.filter(ExamCycle.exam_status == status)
    if state:
        query = query.filter(ExamCycle.state == state)
    cycles = query.order_by(ExamCycle.application_last_date.asc().nullslast()).all()
    return jsonify({
        "options": filter_options(),
        "cycles": [{
            "id": c.id, "cycle_slug": c.cycle_slug, "display_name": c.display_name,
            "organization": c.organization, "advertisement_number": c.advertisement_number or "",
            "exam_year": c.exam_year,
            "application_last_date": c.application_last_date.isoformat() if c.application_last_date else None,
            "exam_date": c.exam_date.isoformat() if c.exam_date else None,
            "qualification": c.qualification or "", "education_level": c.education_level or "",
            "min_age": c.min_age, "max_age": c.max_age,
            "state": c.state, "status": c.exam_status,
            "fee_note": c.fee_note,
            "deadline": deadline_info(c),
            "service_slug": c.service.slug if c.service else None,
        } for c in cycles],
    })


@api_bp.route("/pages/<name>")
def legal_page(name):
    pairs = {
        "privacy": ("Privacy Policy", "गोपनीयता नीति", "privacy_policy", "privacy_policy_hi"),
        "terms": ("Terms & Conditions", "नियम एवं शर्तें", "terms_conditions", "terms_conditions_hi"),
    }
    pair = pairs.get(name)
    if pair is None:
        return _bad("not_found", 404)
    title_en, title_hi, en_key, hi_key = pair
    body_en = get_setting(en_key)
    body_hi = get_setting(hi_key) or body_en
    return jsonify({"name": name, "title_en": title_en, "title_hi": title_hi,
                    "body_en": body_en, "body_hi": body_hi})


# ---------------------------------------------------------------------------
# Cart (same server session as the Jinja templates)
# ---------------------------------------------------------------------------

def _cart_payload() -> dict:
    from ..orders.routes import _cart_view_items
    lines, totals, unavailable = _cart_view_items()
    items = []
    for line in lines:
        svc = line["service"]
        cycle = line.get("cycle")
        items.append({
            "key": line["item"]["key"],
            "service_id": svc.id,
            "slug": svc.slug,
            "name_en": svc.name_en,
            "name_hi": svc.name_hi or "",
            "service_charge": _money(line["service_charge"]),
            "official_fee": _money(line["official_fee"]),
            "other_charge": _money(line["other_charge"]),
            "line_total": _money(line["line_total"]),
            "form_filled": bool(item_form_data(line["item"]["key"])),
            "needs_cycle": bool(line.get("needs_cycle")),
            "exam_cycle": ({"id": cycle.id, "display_name": cycle.display_name,
                            "cycle_slug": cycle.cycle_slug} if cycle else None),
        })
    return jsonify({
        "items": items,
        "totals": {k: _money(totals[k]) for k in
                   ("service_charges_total", "official_fees_total",
                    "other_charges_total", "total")},
        "unavailable": unavailable,
        "cart_count": cart_service_count(),
    })


@api_bp.route("/cart")
def cart_view():
    return _cart_payload()


@api_bp.route("/cart/add", methods=["POST"])
def cart_add():
    data = request.get_json(silent=True) or {}
    try:
        service_id = int(data.get("service_id"))
    except (TypeError, ValueError):
        return _bad("invalid_request", 400)
    service = Service.query.filter_by(id=service_id, is_active=True).first()
    if service is None:
        return _bad("service_unavailable", 400)
    if service.is_restricted:
        return _bad("service_restricted", 403)
    cycle_id = data.get("exam_cycle_id")
    if cycle_id:
        from ..models.exam import ExamCycle
        from ..utils.exams import cycle_accepting_applications
        cycle = db.session.get(ExamCycle, int(cycle_id))
        if (cycle is None or cycle.service_id != service.id
                or not cycle.is_published or cycle.is_archived
                or not cycle_accepting_applications(cycle)):
            return _bad("exam_cycle_closed", 400)
    item = add_service(service.id, exam_cycle_id=cycle_id)
    return jsonify({"ok": True, "item_key": item["key"], "cart_count": cart_service_count()})


@api_bp.route("/cart/remove", methods=["POST"])
def cart_remove():
    data = request.get_json(silent=True) or {}
    if not remove_item(str(data.get("item_key") or "")):
        return _bad("not_found", 404)
    return jsonify({"ok": True})


@api_bp.route("/cart/clear", methods=["POST"])
def cart_clear():
    clear_cart()
    return jsonify({"ok": True})


@api_bp.route("/cart/<item_key>/form", methods=["POST"])
def cart_save_form(item_key):
    """Validate + stage one cart item's dynamic form (multipart POST).

    Field names follow the Jinja flow exactly: text values are POSTed under
    the field_key, files under file_<field_key> and req_<requirement_id>.
    Returns per-field error CODES (client translates) or ok.
    """
    cart_item = find_item(item_key)
    if cart_item is None:
        return _bad("not_found", 404)
    service = db.session.get(Service, cart_item["service_id"])
    if service is None or not service.is_active:
        remove_item(item_key)
        return _bad("service_unavailable", 400)

    # Optional exam-cycle selection on the item form (SPA flow)
    cycle_raw = (request.form.get("exam_cycle_id") or "").strip()
    if cycle_raw:
        from ..models.exam import ExamCycle
        from ..utils.exams import cycle_accepting_applications
        cycle = db.session.get(ExamCycle, int(cycle_raw))
        if (cycle is None or cycle.service_id != service.id
                or not cycle.is_published or cycle.is_archived
                or not cycle_accepting_applications(cycle)):
            return _bad("exam_cycle_closed", 400)
        from ..utils.cart import set_item_cycle
        set_item_cycle(item_key, cycle.id)

    fields = service.active_form_fields
    requirements = service.active_document_requirements
    values, errors = validate_dynamic_form(fields, request)
    req_uploads, req_wallet, req_errors = validate_document_uploads(requirements, request)
    if errors or req_errors:
        all_errors = {f"field:{k}": v for k, v in errors.items()}
        all_errors.update({f"req:{k}": v for k, v in req_errors.items()})
        return jsonify({"ok": False, "errors": all_errors}), 422

    staged = (stage_field_files(fields, values)
              + stage_requirement_files(req_uploads, req_wallet, requirements))
    compact_values = {}
    for k, v in values.items():
        compact_values[k] = {
            "value_text": v.get("value_text"),
            "value_json": v.get("value_json"),
            "files": [{"filename": f.filename} for f in v.get("files", [])],
        }
    from ..utils.checkout import store_item_form_data
    store_item_form_data(item_key, compact_values, staged)
    # Text answers are remembered so the same field_key is asked only once
    # for every other application in this session (see /api/apply/overview).
    remember_answers(values)
    return jsonify({"ok": True})


@api_bp.route("/cart/<item_key>/form/reset", methods=["POST"])
def cart_reset_form(item_key):
    if find_item(item_key):
        drop_item_form_data(item_key)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Unified application flow: common details + document wallet
#
# Instead of one separate form per service, the SPA collects shared details
# (name/mobile/email/address, dynamic field answers) and common documents
# ONCE. `wallet:<id>` references returned here are accepted by the per-item
# form endpoints in place of re-uploading the same file.
# ---------------------------------------------------------------------------

def _common_payload() -> dict:
    return {"profile": get_profile(), "answers": get_answers(), "wallet": wallet_json()}


@api_bp.route("/apply/common", methods=["GET"])
def apply_common_view():
    return jsonify(_common_payload())


@api_bp.route("/apply/common", methods=["POST"])
def apply_common_save():
    """Save common details (multipart or JSON) + wallet uploads.

    Multipart: name/mobile/email/address + `answer_<field_key>` values +
    `wallet_files` (multiple). JSON: {"profile": {...}, "answers": {...}}.
    """
    if (request.content_type or "").startswith("multipart/form-data"):
        # Profile is validated only when actually sent (wallet-only adds skip it).
        sent_profile = any(request.form.get(k) for k in ("name", "mobile", "email", "address"))
        errors = save_profile({
            "name": request.form.get("name"),
            "mobile": request.form.get("mobile"),
            "email": request.form.get("email"),
            "address": request.form.get("address"),
        }) if sent_profile else {}
        if errors:
            return jsonify({"ok": False, "errors": errors}), 422
        raw_answers = {}
        for key in request.form:
            if key.startswith("answer_"):
                raw_answers[key[7:]] = request.form.get(key)
        remember_raw_answers(raw_answers)
        added, wallet_errors = add_wallet_files(request.files.getlist("wallet_files"))
        if wallet_errors:
            return _bad("wallet_upload_invalid", 422)
        return jsonify({"ok": True, "wallet_added": added, **_common_payload()})

    data = request.get_json(silent=True) or {}
    errors = save_profile(data.get("profile") or {})
    if errors:
        return jsonify({"ok": False, "errors": errors}), 422
    remember_raw_answers(data.get("answers") or {})
    return jsonify({"ok": True, **_common_payload()})


@api_bp.route("/wallet/remove", methods=["POST"])
def wallet_remove():
    data = request.get_json(silent=True) or {}
    if not remove_wallet_entry(str(data.get("id") or "")):
        return _bad("not_found", 404)
    return jsonify({"ok": True, **_common_payload()})


@api_bp.route("/apply/overview")
def apply_overview():
    """Everything the unified form page needs in one call: common payload +
    every cart item's fields/requirements with prefills and wallet picks."""
    from ..orders.routes import _cart_view_items
    lines, totals, unavailable = _cart_view_items()
    answers = get_answers()
    wallet = wallet_json()
    items = []
    for line in lines:
        svc = line["service"]
        fields = []
        for f in svc.active_form_fields:
            fj = _form_field_json(f)
            if f.field_type in ("file", "file_multi", "image"):
                fj["prefill"] = None
                allowed = fj["allowed_extensions"] or ["pdf", "jpg", "jpeg", "png"]
                if f.field_type == "image":
                    allowed = [a for a in allowed if a in ("jpg", "jpeg", "png", "webp")]
                fj["prefill_wallet_id"] = suggest_wallet_entry(wallet, f.label_en, allowed)
            else:
                ans = answers.get(f.field_key)
                if ans is not None and isinstance(ans, dict):
                    fj["prefill"] = (ans.get("value_json")
                                     if isinstance(ans.get("value_json"), list)
                                     else ans.get("value_text"))
                else:
                    fj["prefill"] = None
                fj["prefill_wallet_id"] = None
            fields.append(fj)
        requirements = []
        for r in svc.active_document_requirements:
            rj = _requirement_json(r)
            rj["prefill_wallet_id"] = suggest_wallet_entry(
                wallet, r.label_en, rj["allowed_extensions"])
            requirements.append(rj)
        items.append({
            "key": line["item"]["key"],
            "service": _service_json(svc),
            "line_total": _money(line["line_total"]),
            "form_filled": bool(item_form_data(line["item"]["key"])),
            "form_fields": fields,
            "document_requirements": requirements,
        })
    return jsonify({
        "common": _common_payload(),
        "items": items,
        "unavailable": unavailable,
    })


# ---------------------------------------------------------------------------
# Checkout -> order creation (same helper as the Jinja flow)
# ---------------------------------------------------------------------------

@api_bp.route("/checkout/init", methods=["POST"])
def checkout_init():
    """Fresh idempotency token; must be sent back with /api/checkout."""
    import secrets
    session["checkout_token"] = secrets.token_hex(16)
    return jsonify({"checkout_token": session["checkout_token"]})


@api_bp.route("/checkout", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"])
def checkout_submit():
    data = request.get_json(silent=True) or {}
    from ..orders.routes import _cart_view_items
    lines, totals, unavailable = _cart_view_items()
    if not lines:
        return _bad("cart_empty", 400)
    if unavailable:
        return _bad("unavailable_service", 400)
    missing = [line["item"]["key"] for line in lines if not item_form_data(line["item"]["key"])]
    if missing:
        return _bad("missing_forms", 422, item_keys=missing)

    form_data = {
        "name": (data.get("name") or "").strip(),
        "mobile": (data.get("mobile") or "").replace(" ", ""),
        "email": (data.get("email") or "").strip(),
        "address": (data.get("address") or "").strip(),
        "consent": bool(data.get("consent")),
        "checkout_token": (data.get("checkout_token") or "").strip(),
    }
    if not form_data["name"] or len(form_data["name"]) < 2:
        return _bad("invalid_name", 422)
    if not form_data["mobile"].isdigit() or not (10 <= len(form_data["mobile"]) <= 13):
        return _bad("invalid_mobile", 422)
    if not form_data["consent"]:
        return _bad("consent_required", 422)

    try:
        order, token, pin = create_order_from_cart(form_data, request)
    except CheckoutError as exc:
        code = str(exc) if str(exc) in ("consent_required", "cart_empty",
                                        "unavailable_service", "duplicate",
                                        "exam_cycle_required", "exam_cycle_closed") \
            else "checkout_failed"
        return _bad(code, 400)

    if token == "" and pin == "":
        # Duplicate submit -> the order already exists.
        return jsonify({"ok": True, "duplicate": True, "order_number": order.order_number})

    session.pop("checkout_token", None)
    from ..notifications.service import event_order_submitted
    event_order_submitted(order, order.order_number, token)
    return jsonify({
        "ok": True,
        "duplicate": False,
        "order_number": order.order_number,
        "tracking_token": token,
        "tracking_pin": pin,
        "total": _money(order.total_amount),
        "currency": order.currency,
    })


# ---------------------------------------------------------------------------
# Secure tracking (order number + token OR PIN)
# ---------------------------------------------------------------------------

def _tracked_order_or_error(order_number=None):
    """Shared token/PIN check. `order_number` may come from the path or the
    query string; the tracking token (or PIN) always comes from the query."""
    order_number = (order_number or request.args.get("order_number") or "").strip().upper()
    token = (request.args.get("token") or "").strip()
    order = Order.query.filter_by(order_number=order_number).first()
    if not order or not token or not verify_tracking(order_number, token, order):
        return None, None, _bad("invalid_credentials", 404)
    return order, token, None


@api_bp.route("/track")
@limiter.limit("30 per hour")
def track_api():
    order, token, err = _tracked_order_or_error()
    if err is not None:
        return err

    history = (StatusHistory.query
               .filter(StatusHistory.order_id == order.id,
                       StatusHistory.visible_to_customer.is_(True))
               .order_by(StatusHistory.created_at.desc()).all())
    output_docs = (UploadedDocument.query
                   .filter(UploadedDocument.order_id == order.id,
                           UploadedDocument.doc_purpose == "output_document")
                   .order_by(UploadedDocument.id.desc()).all())

    return jsonify({
        "order_number": order.order_number,
        "token": token,
        "status": order.status,
        "payment_status": order.payment_status,
        "currency": order.currency,
        "amounts": {
            "service_charges_total": _money(order.service_charges_total),
            "official_fees_total": _money(order.official_fees_total),
            "other_charges_total": _money(order.other_charges_total),
            "total": _money(order.total_amount),
        },
        "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
        "items": [{
            "application_number": (item.application.application_number
                                   if item.application else None),
            "service_name": item.service_name_snapshot,
            "service_slug": item.service_slug_snapshot or "",
            "service_charge": _money(item.service_charge_snapshot),
            "official_fee": _money(item.official_fee_snapshot),
            "other_charge": _money(item.other_charge_snapshot),
            "line_total": _money(item.line_total_snapshot),
            "application_status": (item.application.status
                                   if item.application else None),
        } for item in order.items],
        "applications": [{
            "application_number": a.application_number,
            "service_name": a.service_name_snapshot,
            "status": a.status,
        } for a in order.applications],
        "history": [{
            "entity_type": h.entity_type,
            "new_status": h.new_status,
            "customer_remark": h.customer_remark or "",
            "created_at": h.created_at.isoformat() if h.created_at else None,
        } for h in history],
        "output_documents": [{
            "id": d.id,
            "original_name": d.original_name,
            "mime_type": d.mime_type,
            "download_url": f"/order/{order.order_number}/document/{d.id}?token={token}",
        } for d in output_docs],
        "receipt_url": f"/order/{order.order_number}/receipt.pdf?token={token}",
        "pay_url": f"/app/pay/{order.order_number}?token={token}",
    })


# ---------------------------------------------------------------------------
# Payment (UPI QR + proof submission)
# ---------------------------------------------------------------------------

@api_bp.route("/pay/<order_number>")
@limiter.limit("30 per hour")
def pay_api(order_number):
    order, token, err = _tracked_order_or_error(order_number)
    if err is not None:
        return err

    payment = order.latest_payment
    upi_id = get_setting("upi_id")
    merchant = get_setting("upi_merchant_name") or get_setting("shop_name")
    intent = build_upi_intent(order.total_amount, upi_id, merchant, order.order_number,
                              note=order.service_names_snapshot[:40])
    return jsonify({
        "order_number": order.order_number,
        "token": token,
        "total": _money(order.total_amount),
        "currency": order.currency,
        "payment_status": payment.status if payment else "awaiting_payment",
        "upi_id": upi_id,
        "merchant_name": merchant,
        "upi_intent": intent,
        # Existing token-authorised QR image route is reused directly.
        "qr_url": f"/pay/{order.order_number}/qr.png?token={token}",
        "instructions_en": get_setting("payment_instructions"),
        "instructions_hi": get_setting("payment_instructions_hi") or get_setting("payment_instructions"),
        "support_info_en": get_setting("payment_support_info"),
        "support_info_hi": get_setting("payment_support_info_hi") or get_setting("payment_support_info"),
    })


@api_bp.route("/pay/<order_number>/proof", methods=["POST"])
@limiter.limit("10 per hour", methods=["POST"])
def pay_proof(order_number):
    token = (request.form.get("token") or "").strip()
    order = Order.query.filter_by(order_number=order_number).first()
    if not order or not verify_tracking(order_number, token, order):
        return _bad("invalid_credentials", 404)

    payment = order.latest_payment
    if payment is None:
        return _bad("not_found", 404)
    if payment.status == "verified":
        return _bad("already_verified", 409)
    if payment.status == "refunded":
        return _bad("refunded", 409)

    utr = (request.form.get("utr") or "").strip()
    remarks = (request.form.get("remarks") or "").strip()
    screenshot = request.files.get("screenshot")

    if not utr or len(utr) < 8 or len(utr) > 60:
        return _bad("invalid_utr", 422)
    if screenshot is None or not screenshot.filename:
        return _bad("screenshot_required", 422)
    ok, err = validate_upload(screenshot.stream, screenshot.filename,
                              PROOF_EXTENSIONS, Config.UPLOAD_DEFAULT_MAX_MB)
    if not ok:
        return _bad("screenshot_invalid", 422)

    screenshot.stream.seek(0)
    staged = stage_files([(screenshot, None)], "Payment Screenshot")[0]
    from ..storage.documents import upload_document_record
    doc = upload_document_record(order, staged, payment=payment, purpose="payment_proof")

    payment.upi_transaction_id = utr
    payment.amount_submitted = order.total_amount
    payment.customer_remarks = remarks or None
    payment.screenshot_document_id = doc.id
    new_status = "pending_verification" if doc.upload_status == "uploaded" else "submitted"
    set_payment_status(payment, new_status,
                       customer_remark="Payment proof received. Verification usually completes within a few hours.")
    order.payment_status = new_status
    set_order_status(order, "payment_verification")
    db.session.commit()

    from ..notifications.service import event_payment_proof_received
    event_payment_proof_received(order)
    return jsonify({"ok": True, "payment_status": new_status,
                    "upload_pending": doc.upload_status == "pending"})


# ---------------------------------------------------------------------------
# React SPA serving (frontend/dist) under /app/
# ---------------------------------------------------------------------------

@spa_bp.route("/app", defaults={"subpath": ""})
@spa_bp.route("/app/", defaults={"subpath": ""})
@spa_bp.route("/app/<path:subpath>")
def spa(subpath):
    dist = current_app.config.get("SPA_DIST_DIR", "")
    index = os.path.join(dist, "index.html")
    if not dist or not os.path.isfile(index):
        return ("React frontend build not found. Run: cd frontend && npm install && npm run build", 404)
    if subpath:
        try:
            return send_from_directory(dist, subpath)
        except NotFound:
            pass  # client-side route -> fall through to index.html
    response = send_from_directory(dist, "index.html")
    response.headers["Cache-Control"] = "no-cache"
    return response
