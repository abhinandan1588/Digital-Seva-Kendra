"""Checkout service: creates orders, applications, payments atomically.

Key guarantees:
- All amounts recomputed server-side from DB prices.
- Prices snapshotted into order_items.
- Idempotency key prevents duplicate orders on double submit.
- Tracking credentials (token+PIN) generated once; only hashes stored.
"""
import uuid

from flask import session
from sqlalchemy.exc import IntegrityError

from ..config import Config
from ..extensions import db
from ..models import Order, OrderItem, Application, Payment, Customer, ApplicationFieldValue
from .cart import get_cart, clear_cart
from .pricing import cart_totals
from .order_ids import (generate_order_number, generate_application_number,
                        generate_tracking_credentials)


class CheckoutError(Exception):
    pass


def create_order_from_cart(form_data: dict, request=None) -> tuple[Order, str, str]:
    """Create order + applications + payment from the session cart.

    form_data keys: name, mobile, email, address, consent.
    Returns (order, tracking_token, tracking_pin). Raises CheckoutError on
    invalid cart or duplicate submission.

    The caller must have staged all uploaded files already (see
    applications.routes) and keeps them in the session cart items.
    """
    items = get_cart()
    if not items:
        raise CheckoutError("cart_empty")

    # --- Idempotency: same checkout token => same order (double click) ------
    checkout_token = form_data.get("checkout_token") or ""
    existing = Order.query.filter_by(idempotency_key=checkout_token).first() \
        if checkout_token else None
    if existing:
        return existing, "", ""  # already created; caller redirects

    try:
        totals = cart_totals(items)
    except ValueError as exc:
        raise CheckoutError("unavailable_service") from exc

    if not form_data.get("consent"):
        raise CheckoutError("consent_required")

    # --- Examination cycles: verified selection required for exam services --
    # A service template with published cycles can only be ordered against a
    # cycle that is accepting applications right now. Closed/unpublished
    # cycles are never orderable.
    from ..models.exam import ExamCycle
    from ..utils.exams import cycle_accepting_applications
    cycles_by_item = {}
    for line in totals["lines"]:
        service, cart_item = line["service"], line["item"]
        cycle_id = cart_item.get("exam_cycle_id")
        if cycle_id:
            cycle = db.session.get(ExamCycle, int(cycle_id))
            invalid = (cycle is None or cycle.service_id != service.id
                       or not cycle.is_published or cycle.is_archived
                       or not cycle_accepting_applications(cycle))
            if invalid:
                raise CheckoutError("exam_cycle_closed")
            cycles_by_item[cart_item["key"]] = cycle
        elif service.is_examination and service.has_cycles:
            raise CheckoutError("exam_cycle_required")

    customer = Customer.query.filter_by(mobile=form_data["mobile"]).first()
    if customer is None:
        customer = Customer(name=form_data["name"], mobile=form_data["mobile"])
    customer.name = form_data["name"]
    customer.email = form_data.get("email") or None
    customer.address = form_data.get("address") or None
    customer.consent_given = True
    customer.consent_at = customer.consent_at or db.func.now()
    db.session.add(customer)

    token, pin, token_hash, pin_hash = generate_tracking_credentials()
    order = Order(
        customer=customer,
        order_number=generate_order_number(),
        status="submitted",
        payment_status="awaiting_payment",
        service_charges_total=totals["service_charges_total"],
        official_fees_total=totals["official_fees_total"],
        other_charges_total=totals["other_charges_total"],
        total_amount=totals["total"],
        currency=Config.CURRENCY,
        tracking_token_hash=token_hash,
        tracking_pin_hash=pin_hash,
        idempotency_key=checkout_token or str(uuid.uuid4()),
        customer_ip=request.remote_addr if request else None,
    )
    db.session.add(order)
    db.session.flush()  # assign order.id for relationships

    applications_by_item_key = {}
    for index, line in enumerate(totals["lines"], start=1):
        service = line["service"]
        cart_item = line["item"]
        order_item = OrderItem(
            order=order,
            service=service,
            item_sequence=index,
            service_name_snapshot=service.name_en,
            service_slug_snapshot=service.slug,
            service_charge_snapshot=line["service_charge"],
            official_fee_snapshot=line["official_fee"],
            other_charge_snapshot=line["other_charge"],
            line_total_snapshot=line["line_total"],
        )
        db.session.add(order_item)
        cycle = cycles_by_item.get(cart_item["key"])
        application = Application(
            order=order,
            order_item=order_item,
            service=service,
            application_number=generate_application_number(order.order_number, index),
            service_name_snapshot=service.name_en,
            exam_cycle=cycle,
            exam_cycle_snapshot=(cycle.display_name or "") if cycle else None,
            status="submitted",
        )
        db.session.add(application)
        applications_by_item_key[cart_item["key"]] = application
        # Persist dynamic form values captured earlier for this cart item.
        values = _values_for_item(request, cart_item["key"], None)
        if values:
            fields_by_key = {f.field_key: f for f in service.active_form_fields}
            for fkey, val in values.items():
                field = fields_by_key.get(fkey)
                if field is None:
                    continue
                db.session.add(ApplicationFieldValue(
                    application=application,
                    form_field_id=field.id,
                    field_key=field.field_key,
                    field_label_snapshot=field.label_en,
                    field_type=field.field_type,
                    value_text=val.get("value_text"),
                    value_json=val.get("value_json"),
                ))

    payment = Payment(order=order, amount_expected=totals["total"], status="awaiting_payment")
    db.session.add(payment)

    # --- Upload staged documents into the storage provider -------------------
    # Local staging -> (Google Drive | local fallback). On storage failure the
    # document row is kept as 'pending' and retried later; the order still
    # succeeds and no file is lost. Identical content (shared wallet file) is
    # uploaded only once per order; later applications get metadata rows that
    # point at the same stored file.
    from ..models import UploadedDocument
    from ..storage.base import get_storage, StorageError
    from ..storage.documents import upload_document_record
    seen_docs: dict[str, "UploadedDocument"] = {}
    try:
        tree = get_storage().ensure_folder_tree(
            order.order_number, [a.service_name_snapshot for a in order.applications])
    except StorageError:
        tree = None

    for line2 in totals["lines"]:
        item_key = line2["item"]["key"]
        data = item_form_data(item_key)
        application = applications_by_item_key.get(item_key)
        if data and application is not None:
            folder_id = None
            if tree:
                label = application.service_name_snapshot.replace("/", "_").replace("\\", "_")[:80]
                folder_id = tree["service_folder_ids"].get(label) or tree["order_folder_id"]
            for staged in data.get("files", []):
                sha = staged.get("sha256") or ""
                primary = seen_docs.get(sha)
                if primary is not None and primary.upload_status == "uploaded":
                    # Identical content was already stored for this order
                    # (one wallet file reused by several applications):
                    # metadata row only — the file is NOT uploaded again.
                    db.session.add(UploadedDocument(
                        order_id=order.id,
                        application_id=application.id,
                        requirement_id=staged.get("requirement_id"),
                        form_field_id=staged.get("form_field_id"),
                        doc_purpose="application_document",
                        label_snapshot=staged.get("label", "Document"),
                        original_name=staged["original_name"],
                        stored_name=primary.stored_name,
                        mime_type=primary.mime_type,
                        size_bytes=primary.size_bytes,
                        storage_provider=primary.storage_provider,
                        drive_file_id=primary.drive_file_id,
                        drive_folder_id=primary.drive_folder_id,
                        web_view_link=primary.web_view_link,
                        upload_status="uploaded",
                        uploaded_by="customer",
                        is_private=True,
                    ))
                    continue
                doc = upload_document_record(
                    order, staged,
                    application=application,
                    form_field_id=staged.get("form_field_id"),
                    requirement_id=staged.get("requirement_id"),
                    purpose="application_document",
                    folder_id=folder_id,
                    keep_staged=(staged.get("source") == "wallet"),
                    commit=False,
                )
                if sha and sha not in seen_docs:
                    seen_docs[sha] = doc
        drop_item_form_data(item_key)

    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        # Unique violation on idempotency_key -> another request created it.
        if checkout_token:
            existing = Order.query.filter_by(idempotency_key=checkout_token).first()
            if existing:
                return existing, "", ""
        raise CheckoutError("duplicate") from exc

    clear_cart()
    return order, token, pin


# --- per-cart-item form data (kept in session until checkout) -------------

FORM_DATA_KEY = "dsk_cart_forms"


def store_item_form_data(item_key: str, values: dict, staged_files: list[dict]) -> None:
    """Remember validated form values + staged file metadata for one item."""
    all_items = session.get(FORM_DATA_KEY, {})
    compact_files = []
    for f in staged_files:
        compact_files.append({
            "abs_path": f["abs_path"], "stored_name": f["stored_name"],
            "original_name": f["original_name"], "mime_type": f["mime_type"],
            "size_bytes": f["size_bytes"], "label": f["label"],
            "form_field_id": f.get("form_field_id"),
            "requirement_id": f.get("requirement_id"),
            "sha256": f.get("sha256"), "source": f.get("source"),
        })
    all_items[item_key] = {"values": values, "files": compact_files}
    session[FORM_DATA_KEY] = all_items
    session.modified = True


def item_form_data(item_key: str) -> dict | None:
    return session.get(FORM_DATA_KEY, {}).get(item_key)


def drop_item_form_data(item_key: str) -> None:
    all_items = session.get(FORM_DATA_KEY, {})
    all_items.pop(item_key, None)
    session[FORM_DATA_KEY] = all_items
    session.modified = True


def _values_for_item(request, item_key: str, stored: dict | None) -> dict:
    data = stored or (item_form_data(item_key) if request else None) or {}
    return data.get("values", {}) or {}
