"""Customer order flow: cart, checkout, confirmation, payment page redirect,
secure tracking without login, and receipt PDF download.

Tracking access = order number + tracking token (URL) or PIN. Rate limited.
"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   session, flash, Response, abort, current_app, make_response,
                   send_file)

from ..extensions import db, limiter
from ..models import Order, Service, StatusHistory, UploadedDocument
from ..utils.cart import (get_cart, add_service, remove_item, find_item,
                          clear_cart, cart_service_count, set_item_cycle)
from ..utils.pricing import cart_totals
from ..utils.checkout import create_order_from_cart, CheckoutError
from ..utils.i18n import t
from ..utils.order_ids import verify_tracking, hash_token
from ..utils.settings import get_setting
from ..utils.receipts import build_receipt_pdf
from ..notifications.service import event_order_submitted

orders_bp = Blueprint("orders", __name__)


# --------------------------------------------------------------------------
# Cart
# --------------------------------------------------------------------------

def _cart_view_items():
    """Cart lines with server-computed prices (browser never supplies prices).

    Each line also carries the chosen examination cycle (if any) and a
    `needs_cycle` flag when an exam service still requires a cycle choice.
    """
    items = get_cart()
    unavailable = []
    lines = []
    totals = {"service_charges_total": 0, "official_fees_total": 0,
              "other_charges_total": 0, "total": 0}
    if items:
        try:
            computed = cart_totals(items)
        except ValueError:
            computed = None
        if computed:
            from ..models.exam import ExamCycle
            from ..utils.exams import cycle_accepting_applications
            lines = computed["lines"]
            for line in lines:
                cycle = None
                cycle_id = line["item"].get("exam_cycle_id")
                if cycle_id:
                    cycle = db.session.get(ExamCycle, int(cycle_id))
                    if (cycle is None or cycle.service_id != line["service"].id
                            or not cycle_accepting_applications(cycle)):
                        unavailable.append(line["item"]["key"])
                        line["cycle_stale"] = True
                line["cycle"] = cycle
                service = line["service"]
                line["needs_cycle"] = bool(
                    service.is_examination and service.has_cycles and cycle is None)
            totals = {k: computed[k] for k in
                      ("service_charges_total", "official_fees_total", "other_charges_total", "total")}
            return lines, totals, unavailable
        # Some services disappeared/inactivated: show which
        for item in items:
            svc = db.session.get(Service, item["service_id"])
            if svc is None or not svc.is_active:
                unavailable.append(item["key"])
    return lines, totals, unavailable


@orders_bp.route("/cart")
def cart():
    lines, totals, unavailable = _cart_view_items()
    from ..utils.checkout import item_form_data
    missing_forms = [line["item"]["key"] for line in lines if not item_form_data(line["item"]["key"])]
    needs_cycle = [line["item"]["key"] for line in lines if line.get("needs_cycle")]
    checkout_token = session.get("checkout_token")
    return render_template("orders/cart.html", lines=lines, totals=totals,
                           unavailable=unavailable, missing_forms=missing_forms,
                           needs_cycle=needs_cycle, checkout_token=checkout_token)


@orders_bp.route("/cart/add/<int:service_id>", methods=["POST"])
def add_to_cart(service_id):
    service = Service.query.filter_by(id=service_id, is_active=True).first_or_404()
    if service.is_restricted:
        flash(t("This service currently requires authorization and cannot be ordered online. Please contact the shop.",
                "इस सेवा के लिए अभी अधिकृत आवश्यक है; ऑनलाइन ऑर्डर नहीं हो सकता। कृपया दुकान से संपर्क करें।"), "warning")
        return redirect(request.referrer or url_for("services.detail", slug=service.slug))
    # Optional examination-cycle selection validated server-side.
    cycle_id = request.form.get("exam_cycle_id", type=int)
    if cycle_id:
        from ..models.exam import ExamCycle
        from ..utils.exams import cycle_accepting_applications
        cycle = db.session.get(ExamCycle, cycle_id)
        if (cycle is None or cycle.service_id != service.id
                or not cycle.is_published or cycle.is_archived
                or not cycle_accepting_applications(cycle)):
            flash(t("That examination cycle is not accepting applications. Please choose an open cycle.",
                    "यह परीक्षा चक्र आवेदन स्वीकार नहीं कर रहा। कृपया चालू चक्र चुनें।"), "danger")
            return redirect(url_for("services.detail", slug=service.slug))
    add_service(service.id, exam_cycle_id=cycle_id)
    flash(t("Service added to your list.", "सेवा आपकी सूची में जोड़ दी गई।"), "success")
    return redirect(request.referrer or url_for("orders.cart"))


@orders_bp.route("/cart/<item_key>/cycle", methods=["POST"])
def set_cart_cycle(item_key):
    """Choose/change the examination cycle for a cart item (from cart page)."""
    cycle_id = request.form.get("exam_cycle_id", type=int)
    if find_item(item_key) is None:
        return redirect(url_for("orders.cart"))
    if cycle_id:
        from ..models.exam import ExamCycle
        from ..utils.exams import cycle_accepting_applications
        item = find_item(item_key)
        cycle = db.session.get(ExamCycle, cycle_id)
        service = db.session.get(Service, item["service_id"]) if item else None
        if (cycle is None or service is None or cycle.service_id != service.id
                or not cycle.is_published or cycle.is_archived
                or not cycle_accepting_applications(cycle)):
            flash(t("That examination cycle is not accepting applications.",
                    "यह परीक्षा चक्र आवेदन स्वीकार नहीं कर रहा।"), "danger")
            return redirect(url_for("orders.cart"))
    set_item_cycle(item_key, cycle_id)
    flash(t("Examination cycle updated.", "परीक्षा चक्र अपडेट किया गया।"), "success")
    return redirect(url_for("orders.cart"))


@orders_bp.route("/cart/remove/<item_key>", methods=["POST"])
def remove_from_cart(item_key):
    remove_item(item_key)
    flash(t("Removed from your list.", "सूची से हटा दिया गया।"), "info")
    return redirect(url_for("orders.cart"))


@orders_bp.route("/cart/clear", methods=["POST"])
def clear_cart_route():
    clear_cart()
    flash(t("Your list is now empty.", "आपकी सूची अब खाली है।"), "info")
    return redirect(url_for("orders.cart"))


# --------------------------------------------------------------------------
# Checkout -> creates the order
# --------------------------------------------------------------------------

@orders_bp.route("/checkout", methods=["GET", "POST"])
@limiter.limit("20 per hour", methods=["POST"])
def checkout():
    lines, totals, unavailable = _cart_view_items()
    if not lines:
        flash(t("Please select at least one service first.", "कृपया पहले कम से कम एक सेवा चुनें।"), "warning")
        return redirect(url_for("services.catalogue"))
    if unavailable:
        flash(t("Some selected services are no longer available. Please remove them.",
                "कुछ चयनित सेवाएँ अब उपलब्ध नहीं हैं। कृपया उन्हें हटाएँ।"), "danger")
        return redirect(url_for("orders.cart"))

    # Check all items have completed forms
    from ..utils.checkout import item_form_data
    missing_forms = [line["item"]["key"] for line in lines if not item_form_data(line["item"]["key"])]
    needs_cycle = [line["item"]["key"] for line in lines if line.get("needs_cycle")]

    if request.method == "POST":
        checkout_token = session.get("checkout_token") or request.form.get("checkout_token") or ""
        form_data = {
            "name": (request.form.get("name") or "").strip(),
            "mobile": (request.form.get("mobile") or "").replace(" ", ""),
            "email": (request.form.get("email") or "").strip(),
            "address": (request.form.get("address") or "").strip(),
            "consent": request.form.get("consent"),
            "checkout_token": checkout_token,
        }
        if missing_forms:
            flash(t("Please complete the form for every selected application first.",
                    "कृपया पहले हर चयनित आवेदन का फॉर्म पूरा करें।"), "danger")
            return redirect(url_for("orders.cart"))
        if needs_cycle:
            flash(t("Please choose the examination cycle (notification) for the exam application.",
                    "कृपया परीक्षा आवेदन के लिए चक्र (अधिसूचना) चुनें।"), "danger")
            return redirect(url_for("orders.cart"))
        validation_error = None
        if not form_data["name"] or len(form_data["name"]) < 2:
            validation_error = t("Please enter your full name.", "कृपया अपना पूरा नाम दर्ज करें।")
        elif not form_data["mobile"].isdigit() or not (10 <= len(form_data["mobile"]) <= 13):
            validation_error = t("Please enter a valid mobile number.", "कृपया मोबाइल नंबर सही दर्ज करें।")
        elif not form_data["consent"]:
            validation_error = t("Please give consent to process your documents.",
                                 "कृपया अपने दस्तावेज़ों की प्रक्रिया के लिए सहमति दें।")
        if validation_error:
            flash(validation_error, "danger")
            return redirect(url_for("orders.checkout"))
        try:
            order, token, pin = create_order_from_cart(form_data, request)
        except CheckoutError as exc:
            code = str(exc)
            if code == "consent_required":
                flash(t("Please give consent to process your documents.",
                        "कृपया अपने दस्तावेज़ों की प्रक्रिया के लिए सहमति दें।"), "danger")
            elif code == "exam_cycle_required":
                flash(t("Please choose the examination cycle (notification) for the exam application.",
                        "कृपया परीक्षा आवेदन के लिए चक्र (अधिसूचना) चुनें।"), "danger")
                return redirect(url_for("orders.cart"))
            elif code == "exam_cycle_closed":
                flash(t("The selected examination cycle is no longer accepting applications.",
                        "चयनित परीक्षा चक्र अब आवेदन स्वीकार नहीं कर रहा।"), "danger")
                return redirect(url_for("orders.cart"))
            else:
                flash(t("Could not create the order. Please try again.",
                        "ऑर्डर बनाया नहीं जा सका। कृपया पुनः प्रयास करें।"), "danger")
            return redirect(url_for("orders.cart"))

        if token == "" and pin == "":
            # Duplicate submit -> order already exists; go to tracking page.
            flash(t("This order was already created. Track it below.",
                    "यह ऑर्डर पहले ही बन चुका है। नीचे इसे ट्रैक करें।"), "info")
            return redirect(url_for("orders.track"))
        session.pop("checkout_token", None)
        from ..notifications.service import event_order_submitted as _notify
        _notify(order, order.order_number, token)
        # PIN shown once on the confirmation page (only hash is stored in DB)
        session[f"_pin_{order.order_number}"] = pin
        return redirect(url_for("orders.confirmation",
                                order_number=order.order_number, token=token))

    # GET: fresh checkout token to prevent duplicate submits
    import secrets
    session["checkout_token"] = secrets.token_hex(16)
    return render_template("orders/checkout.html", lines=lines, totals=totals,
                           missing_forms=missing_forms, needs_cycle=needs_cycle,
                           checkout_token=session["checkout_token"])


# --------------------------------------------------------------------------
# Confirmation & receipt
# --------------------------------------------------------------------------

@orders_bp.route("/order/<order_number>/confirmation")
def confirmation(order_number):
    token = request.args.get("token", "")
    order = Order.query.filter_by(order_number=order_number).first()
    if not order or not verify_tracking(order_number, token, order):
        abort(404)
    # The PIN is shown once here; afterwards only its hash remains.
    pin = session.pop(f"_pin_{order_number}", None)
    return render_template("orders/confirmation.html", order=order, token=token, pin=pin)


@orders_bp.route("/order/<order_number>/receipt.pdf")
def receipt_pdf(order_number):
    token = request.args.get("token", "")
    order = Order.query.filter_by(order_number=order_number).first()
    if not order or not verify_tracking(order_number, token, order):
        abort(404)
    from ..utils.settings import load_all_settings
    settings = load_all_settings()
    pdf_bytes = build_receipt_pdf(order, settings)
    response = make_response(pdf_bytes)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"inline; filename=receipt-{order.order_number}.pdf"
    return response


# --------------------------------------------------------------------------
# Secure tracking (no account)
# --------------------------------------------------------------------------

@orders_bp.route("/track", methods=["GET", "POST"])
@limiter.limit("30 per hour", methods=["POST"])
def track():
    order = None
    token = ""
    error = ""
    if request.method == "POST":
        order_number = (request.form.get("order_number") or "").strip().upper()
        token = (request.form.get("token") or "").strip()
        order = Order.query.filter_by(order_number=order_number).first()
        if not order or not token or not verify_tracking(order_number, token, order):
            order = None
            error = t("Invalid order number or tracking code.",
                      "ऑर्डर नंबर या ट्रैकिंग कोड गलत है।")
    else:
        order_number = (request.args.get("order_number") or "").strip().upper()
        token = (request.args.get("token") or "").strip()
        if order_number and token:
            order = Order.query.filter_by(order_number=order_number).first()
            if not order or not verify_tracking(order_number, token, order):
                order = None
                error = t("Invalid order number or tracking code.",
                          "ऑर्डर नंबर या ट्रैकिंग कोड गलत है।")

    if order:
        # Only customer-visible history: internal notes never leave admin area.
        history = (StatusHistory.query
                   .filter(StatusHistory.order_id == order.id,
                           StatusHistory.visible_to_customer.is_(True))
                   .order_by(StatusHistory.created_at.desc()).all())
        return render_template("orders/track_result.html", order=order, token=token,
                               history=history)
    return render_template("orders/track.html", error=error, token=token)


@orders_bp.route("/order/<order_number>/status")
def order_status_by_token(order_number):
    """Confirmation-link style tracking (token in URL)."""
    token = request.args.get("token", "")
    order = Order.query.filter_by(order_number=order_number).first()
    if not order or not verify_tracking(order_number, token, order):
        abort(404)
    history = (StatusHistory.query
               .filter(StatusHistory.order_id == order.id,
                       StatusHistory.visible_to_customer.is_(True))
               .order_by(StatusHistory.created_at.desc()).all())
    return render_template("orders/track_result.html", order=order, token=token, history=history)


@orders_bp.route("/order/<order_number>/document/<int:doc_id>")
def track_document_download(order_number, doc_id):
    """Token-authorised download of a COMPLETED output document only.

    Payment proofs and application documents are never exposed here.
    """
    token = request.args.get("token", "")
    order = Order.query.filter_by(order_number=order_number).first()
    if not order or not verify_tracking(order_number, token, order):
        abort(404)
    doc = db.session.get(UploadedDocument, doc_id)
    if not doc or doc.order_id != order.id or doc.doc_purpose != "output_document":
        abort(404)
    from ..storage.base import get_storage, StorageError
    import os as _os
    storage = get_storage()
    try:
        if doc.drive_file_id and storage.name == "gdrive":
            data = storage.download_file(doc.drive_file_id)
            response = make_response(data)
            response.headers["Content-Type"] = doc.mime_type
        elif doc.local_staging_rel_path:
            path = _os.path.join(current_app.instance_path, doc.local_staging_rel_path)
            if not _os.path.exists(path):
                abort(404)
            response = send_file(path, mimetype=doc.mime_type)
        elif storage.name == "local" and doc.drive_file_id:
            response = send_file(doc.drive_file_id, mimetype=doc.mime_type)
        else:
            abort(404)
    except StorageError:
        abort(404)
    response.headers["Content-Disposition"] = f'attachment; filename="{doc.original_name}"'
    return response
