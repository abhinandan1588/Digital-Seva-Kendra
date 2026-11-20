"""Customer-facing dynamic application form: render per cart item, validate
server-side, stage uploaded documents securely until checkout."""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, abort, current_app)

from ..extensions import db
from ..models import Service
from ..utils.cart import find_item, remove_item
from ..utils.i18n import t
from ..utils.dynamic_forms import (validate_dynamic_form, validate_document_uploads,
                                   stage_field_files, stage_requirement_files)
from ..utils.checkout import store_item_form_data, item_form_data, drop_item_form_data

applications_bp = Blueprint("applications", __name__, url_prefix="/apply")

ERROR_MESSAGES = {
    "required": ("This field is required.", "यह फ़ील्ड आवश्यक है।"),
    "too_short": ("Value is too short.", "मान बहुत छोटा है।"),
    "too_long": ("Value is too long.", "मान बहुत लंबा है।"),
    "invalid_email": ("Please enter a valid email address.", "कृपया मान्य ईमेल पता दर्ज करें।"),
    "invalid_mobile": ("Please enter a valid mobile number.", "कृपया मान्य मोबाइल नंबर दर्ज करें।"),
    "invalid_number": ("Please enter a valid number.", "कृपया मान्य संख्या दर्ज करें।"),
    "range": ("Value is out of the allowed range.", "मान अनुमत सीमा से बाहर है।"),
    "invalid_option": ("Please choose a valid option.", "कृपया मान्य विकल्प चुनें।"),
    "file_required": ("Please attach the file.", "कृपया फ़ाइल संलग्न करें।"),
    "file_too_large": ("File is too large.", "फ़ाइल बहुत बड़ी है।"),
    "file_bad_type": ("File format not allowed.", "फ़ाइल प्रारूप अनुमत नहीं है।"),
    "file_bad_content": ("File content is invalid or corrupted.", "फ़ाइल की सामग्री अमान्य है।"),
    "file_empty_file": ("The file is empty.", "फ़ाइल खाली है।"),
    "too_many": ("Only one file is allowed here.", "यहाँ केवल एक फ़ाइल की अनुमति है।"),
}


def _error_text(key: str) -> str:
    msg = ERROR_MESSAGES.get(key)
    if not msg:
        return t("Invalid value.", "अमान्य मान।")
    return t(*msg)


@applications_bp.route("/<item_key>", methods=["GET", "POST"])
def fill_form(item_key):
    cart_item = find_item(item_key)
    if cart_item is None:
        flash(t("This application is no longer in your list.", "यह आवेदन अब आपकी सूची में नहीं है।"), "warning")
        return redirect(url_for("orders.cart"))

    service = db.session.get(Service, cart_item["service_id"])
    if service is None or not service.is_active:
        flash(t("This service is no longer available.", "यह सेवा अब उपलब्ध नहीं है।"), "danger")
        remove_item(item_key)
        return redirect(url_for("orders.cart"))

    fields = service.active_form_fields
    requirements = service.active_document_requirements
    existing = item_form_data(item_key) or {"values": {}, "files": []}

    # Examination services: the customer must pick the open cycle (notification)
    # they are applying to. Closed/unpublished cycles are never offered.
    open_cycles = service.open_cycles if service.is_examination else []
    cycle_error_key = None
    if request.method == "POST":
        if service.is_examination and service.has_cycles:
            cycle_id = request.form.get("exam_cycle_id", type=int)
            chosen = next((c for c in open_cycles if c.id == cycle_id), None)
            if chosen is None:
                cycle_error_key = ("Please choose the examination cycle (notification).",
                                   "कृपया परीक्षा चक्र (अधिसूचना) चुनें।")
            else:
                from ..utils.cart import set_item_cycle
                set_item_cycle(item_key, chosen.id)
        values, errors = validate_dynamic_form(fields, request)
        req_uploads, req_wallet, req_errors = validate_document_uploads(requirements, request)

        # merge file-related errors into one display map keyed "field:key"/"req:id"
        display_errors = {f"field:{k}": v for k, v in errors.items()}
        display_errors.update({f"req:{k}": v for k, v in req_errors.items()})
        if cycle_error_key:
            display_errors["cycle"] = "cycle_error"

        if display_errors:
            for key, err in display_errors.items():
                if key == "cycle":
                    flash(t(*cycle_error_key), "danger")
                else:
                    flash(f"{_error_text(err)}", "danger")
            # Redisplay entered values without losing customer data
            redisplay = {}
            for k in request.form.keys():
                vals = request.form.getlist(k)
                redisplay[k] = {
                    "value_text": vals[0] if len(vals) == 1 else ", ".join(vals),
                    "value_json": vals if len(vals) > 1 else None,
                }
            return render_template("applications/fill_form.html", service=service,
                                   item_key=item_key, fields=fields,
                                   requirements=requirements,
                                   open_cycles=open_cycles,
                                   form_values=redisplay,
                                   existing_files=existing.get("files", []),
                                   errors=display_errors, _error_text=_error_text)

        # Stage validated files in the secure staging area.
        staged_field_files = stage_field_files(fields, values)
        staged_req_files = stage_requirement_files(req_uploads, req_wallet, requirements)

        compact_values = {}
        for k, v in values.items():
            # store only JSON-serializable display info (FileStorage objects
            # must never go into the session cookie)
            compact_values[k] = {
                "value_text": v.get("value_text"),
                "value_json": v.get("value_json"),
                "files": [{"filename": f.filename} for f in v.get("files", [])],
            }

        store_item_form_data(item_key, compact_values, staged_field_files + staged_req_files)
        flash(t("Application details saved. Continue with the next service or checkout.",
                "आवेदन विवरण सुरक्षित कर लिए गए। अगली सेवा भरें या चेकआउट करें।"), "success")
        return redirect(url_for("orders.cart"))

    return render_template("applications/fill_form.html", service=service,
                           item_key=item_key, fields=fields, requirements=requirements,
                           open_cycles=open_cycles,
                           form_values=None,
                           existing_files=existing.get("files", []),
                           errors={}, _error_text=_error_text)


@applications_bp.route("/<item_key>/reset", methods=["POST"])
def reset_form(item_key):
    if find_item(item_key):
        drop_item_form_data(item_key)
        flash(t("Form cleared. Please fill it again.", "फॉर्म साफ़ कर दिया गया। कृपया दोबारा भरें।"), "info")
    return redirect(url_for("applications.fill_form", item_key=item_key))
