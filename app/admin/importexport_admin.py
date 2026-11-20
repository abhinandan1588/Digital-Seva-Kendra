"""Admin bulk catalogue import/export (Part 13).

CSV/JSON import with validation, preview, and explicit admin confirmation
before anything is written. Update-or-create by slug; existing services are
never silently overwritten - each matched row is shown as an update with the
new values, and rows with errors are skipped entirely.

CSV columns (sample template downloadable):
service_name, hindi_name, category, subcategory, description, service_charge,
official_fee, processing_time, official_url, capability_type, active_status
"""
import csv
import io
import json

from flask import (render_template, request, redirect, url_for, flash, session,
                   Response, current_app)
from flask_login import login_required, current_user

from . import admin_bp
from ..extensions import db
from ..models import (Service, ServiceCategory, ServiceSubcategory)
from ..models.service import CAPABILITY_TYPES
from ..utils.audit import log_admin_action

CSV_FIELDS = ["service_name", "hindi_name", "category", "subcategory", "description",
              "service_charge", "official_fee", "processing_time", "official_url",
              "capability_type", "active_status"]

SESSION_KEY = "dsk_import_rows"

DEFAULT_CAPABILITY = "assisted_application"


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    out = []
    for ch in value:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_", ".", "/", "(", ")", "&", ","):
            out.append("-")
    slug = "".join(out)
    return "-".join(s for s in slug.split("-") if s) or "item"


def _valid_url(url: str) -> bool:
    return (not url) or url.startswith(("http://", "https://"))


def _parse_bool(value, default=True):
    if value in (None, ""):
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "active", "y", "on")


def _validate_rows(raw_rows):
    """Validate raw dicts -> list of row dicts with status/errors/resolved refs."""
    categories = {c.name_en.lower(): c for c in ServiceCategory.query.all()}
    categories.update({c.slug: c for c in ServiceCategory.query.all()})
    subcategories = {}
    for sub in ServiceSubcategory.query.all():
        subcategories.setdefault(sub.category_id, {})[sub.name_en.lower()] = sub
        subcategories[sub.id] = {}

    seen_names = set()
    rows = []
    for index, raw in enumerate(raw_rows, start=1):
        row = {"line": index, "errors": [], "warnings": [], "action": "create"}
        get = lambda k: (raw.get(k) or "").strip() if isinstance(raw.get(k), str) else raw.get(k)

        name = get("service_name")
        hindi = get("hindi_name") or None
        category_name = get("category")
        subcategory_name = get("subcategory")
        description = get("description") or None
        charge_raw = get("service_charge")
        fee_raw = get("official_fee")
        processing = get("processing_time") or None
        official_url = get("official_url")
        capability = get("capability_type") or DEFAULT_CAPABILITY
        active = _parse_bool(get("active_status"), default=True)

        if not name:
            row["errors"].append("service_name is required")
        if not category_name:
            row["errors"].append("category is required")
        category = categories.get((category_name or "").strip().lower())
        if category_name and category is None:
            row["errors"].append(f"invalid category: {category_name!r}")
        subcategory = None
        if subcategory_name and category is not None:
            subs_by_cat = subcategories.get(category.id) or {}
            subcategory = subs_by_cat.get(subcategory_name.strip().lower())
            if subcategory is None:
                row["warnings"].append(
                    f"subcategory {subcategory_name!r} not found in {category.name_en} - left blank")

        try:
            charge = round(float(charge_raw or 0), 2)
            fee = round(float(fee_raw or 0), 2)
            if charge < 0 or fee < 0:
                row["errors"].append("prices cannot be negative")
        except (TypeError, ValueError):
            charge = fee = 0
            row["errors"].append("invalid pricing (not a number)")

        if capability not in CAPABILITY_TYPES:
            row["errors"].append(f"invalid capability_type: {capability!r}")
        if not _valid_url(official_url):
            row["errors"].append("official_url must start with http(s)://")

        slug = _slugify(name) if name else None
        existing = Service.query.filter_by(slug=slug).first() if slug else None
        if name and slug:
            dup_key = (name.lower(), category.id if category else None)
            if dup_key in seen_names:
                row["errors"].append("duplicate service_name+category inside the file")
            seen_names.add(dup_key)
        if existing is not None:
            row["action"] = "update"
            row["existing_id"] = existing.id

        row.update({
            "name": name, "hindi": hindi,
            # store ids/names only - the preview travels through the session,
            # which must stay JSON-serializable
            "category_id": category.id if category else None,
            "category_name": category.name_en if category else None,
            "subcategory_id": subcategory.id if subcategory else None,
            "subcategory_name": subcategory.name_en if subcategory else None,
            "description": description,
            "charge": charge, "fee": fee, "processing": processing,
            "official_url": official_url or None, "capability": capability,
            "active": active, "slug": slug,
        })
        rows.append(row)
    return rows


@admin_bp.route("/catalogue/import-export")
@login_required
def import_export():
    counts = {"services": Service.query.count(),
              "categories": ServiceCategory.query.count(),
              "subcategories": ServiceSubcategory.query.count()}
    return render_template("admin/import_export.html", counts=counts,
                           csv_fields=CSV_FIELDS,
                           preview_rows=session.get(SESSION_KEY))


@admin_bp.route("/catalogue/load-builtin", methods=["POST"])
@login_required
def catalogue_load_builtin():
    """One click: load the full built-in catalogue shipped in data/*.json.

    Same update-or-create seed as `flask seed-catalogue`. Safe by default:
    when services already exist nothing changes unless the admin explicitly
    ticks "also update existing services" (which overwrites manual edits
    with the shipped data-file values).
    """
    from ..cli_catalogue import seed_catalogue_data

    existing = Service.query.count()
    update_existing = bool(request.form.get("update_existing"))
    if existing and not update_existing:
        flash(f"Catalogue already loaded ({existing} services) - nothing was "
              "changed. Tick 'Also update existing services' to refresh from "
              "the shipped data files.", "info")
        return redirect(url_for("admin.import_export"))
    try:
        counts = seed_catalogue_data()
    except Exception as exc:  # noqa: BLE001 - report, never crash the admin UI
        db.session.rollback()
        current_app.logger.warning("Built-in catalogue load failed: %s (%s)",
                                   type(exc).__name__, exc)
        flash("Catalogue load failed - check the server logs.", "danger")
        return redirect(url_for("admin.import_export"))
    log_admin_action(current_user, "catalogue_builtin_loaded", "service", None,
                     {"new_services": counts["services"],
                      "update_existing": update_existing})
    db.session.commit()
    total = Service.query.count()
    flash(f"Built-in catalogue ready: {total} services total "
          f"(+{counts['services']} new), {counts['categories']} categories, "
          f"{counts['subcategories']} subcategories, {counts['portals']} portals, "
          f"{counts['doc_templates']} document templates, {counts['aliases']} "
          "search aliases. Verify official fees before publishing.", "success")
    return redirect(url_for("admin.import_export"))


@admin_bp.route("/catalogue/import/sample.csv")
@login_required
def import_sample_csv():
    lines = [",".join(CSV_FIELDS)]
    lines.append("New PAN Card Variant,नया पैन कार्ड,Identity Card Services,PAN Card,Assistance with a new PAN application,150,0,7-15 working days,https://www.protean-tinpan.com/,assisted_application,active")
    lines.append("Photo Resize Bulk,फोटो रिसाइज बल्क,Digital Document & Computer Services,Photo & Signature,Bulk photo resizing for exam forms,20,0,Same day,,internal_service,active")
    lines.append("GST Return Filing Special,जीएसटी रिटर्न विशेष,Business & Taxation Assistance,GST Services,GST return filing,300,0,2-5 working days,https://www.gst.gov.in/,restricted_authorization_required,inactive")
    return Response("\n".join(lines), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=sample_services.csv"})


@admin_bp.route("/catalogue/import/preview", methods=["POST"])
@login_required
def import_preview():
    upload = request.files.get("file")
    raw_text = request.form.get("json_text", "")
    rows = []
    if upload is not None and upload.filename:
        filename = upload.filename.lower()
        content = upload.read().decode("utf-8-sig", errors="replace")
        if filename.endswith(".json"):
            try:
                data = json.loads(content)
            except json.JSONDecodeError as exc:
                flash(f"Invalid JSON: {exc}", "danger")
                return redirect(url_for("admin.import_export"))
            if isinstance(data, dict):
                data = data.get("services") or data.get("rows") or []
            raw_rows = data
        elif filename.endswith(".csv"):
            reader = csv.DictReader(io.StringIO(content))
            raw_rows = list(reader)
            if not raw_rows:
                flash("The CSV file appears empty.", "danger")
                return redirect(url_for("admin.import_export"))
            missing_cols = [c for c in CSV_FIELDS[:3] if c not in (reader.fieldnames or [])]
            if missing_cols:
                flash(f"CSV is missing required columns: {', '.join(missing_cols)}. "
                      "Download the sample template.", "danger")
                return redirect(url_for("admin.import_export"))
        else:
            flash("Upload a .csv or .json file.", "danger")
            return redirect(url_for("admin.import_export"))
        rows = _validate_rows(raw_rows)
    elif raw_text.strip():
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            flash(f"Invalid JSON: {exc}", "danger")
            return redirect(url_for("admin.import_export"))
        rows = _validate_rows(data if isinstance(data, list) else [])
    else:
        flash("Choose a file or paste JSON.", "danger")
        return redirect(url_for("admin.import_export"))

    session[SESSION_KEY] = rows
    valid = sum(1 for r in rows if not r["errors"])
    creates = sum(1 for r in rows if not r["errors"] and r["action"] == "create")
    updates = sum(1 for r in rows if not r["errors"] and r["action"] == "update")
    flash(f"Preview: {len(rows)} rows - {valid} valid ({creates} new, {updates} updates), "
          f"{len(rows) - valid} with errors. Confirm below to apply.", "info")
    return redirect(url_for("admin.import_export"))


@admin_bp.route("/catalogue/import/apply", methods=["POST"])
@login_required
def import_apply():
    rows = session.get(SESSION_KEY) or []
    if not rows:
        flash("Nothing to import - run a preview first.", "warning")
        return redirect(url_for("admin.import_export"))
    if not request.form.get("confirm"):
        flash("Tick the confirmation box to apply the import.", "danger")
        return redirect(url_for("admin.import_export"))

    created = updated = skipped = 0
    for row in rows:
        if row["errors"]:
            skipped += 1
            continue
        service = db.session.get(Service, row.get("existing_id")) if row["action"] == "update" else None
        if service is None:
            service = Service(slug=row["slug"], name_en=row["name"],
                              category_id=row["category_id"])
            db.session.add(service)
            created += 1
        else:
            updated += 1
        service.name_en = row["name"]
        service.name_hi = row["hindi"]
        service.category_id = row["category_id"]
        service.subcategory_id = row["subcategory_id"]
        service.description_en = row["description"]
        service.service_charge = row["charge"]
        service.official_fee = row["fee"]
        if row["processing"]:
            service.processing_time_en = row["processing"]
        if row["official_url"]:
            service.official_info_url = row["official_url"]
        service.capability_type = row["capability"]
        service.is_active = row["active"]
    db.session.commit()
    log_admin_action(current_user, "catalogue_imported", "service", None,
                     {"created": created, "updated": updated, "skipped": skipped})
    db.session.commit()
    session.pop(SESSION_KEY, None)
    flash(f"Import complete: {created} created, {updated} updated, {skipped} skipped (errors).",
          "success")
    return redirect(url_for("admin.import_export"))


@admin_bp.route("/catalogue/import/cancel", methods=["POST"])
@login_required
def import_cancel():
    session.pop(SESSION_KEY, None)
    flash("Import preview discarded.", "info")
    return redirect(url_for("admin.import_export"))


@admin_bp.route("/catalogue/export.csv")
@login_required
def export_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_FIELDS)
    for s in Service.query.order_by(Service.category_id, Service.name_en).all():
        writer.writerow([
            s.name_en, s.name_hi or "", s.category.name_en if s.category else "",
            s.subcategory.name_en if s.subcategory else "",
            (s.description_en or "").replace("\n", " ")[:300],
            str(s.service_charge), str(s.official_fee),
            s.processing_time_en or "", s.official_info_url or "",
            s.capability_type, "active" if s.is_active else "inactive",
        ])
    log_admin_action(current_user, "catalogue_exported", "service", None, {"format": "csv"})
    db.session.commit()
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=service_catalogue.csv"})


@admin_bp.route("/catalogue/export.json")
@login_required
def export_json():
    data = []
    for s in Service.query.order_by(Service.category_id, Service.name_en).all():
        data.append({
            "service_name": s.name_en, "hindi_name": s.name_hi,
            "category": s.category.name_en if s.category else None,
            "subcategory": s.subcategory.name_en if s.subcategory else None,
            "description": s.description_en, "service_charge": str(s.service_charge),
            "official_fee": str(s.official_fee), "other_charge": str(s.other_charge),
            "processing_time": s.processing_time_en, "official_url": s.official_info_url,
            "capability_type": s.capability_type, "active_status": "active" if s.is_active else "inactive",
            "slug": s.slug, "is_popular": s.is_popular, "is_featured": s.is_featured,
            "is_examination": s.is_examination, "search_keywords": s.search_keywords,
            "eligibility": s.eligibility_en,
            "form_fields": [{"key": f.field_key, "label_en": f.label_en, "label_hi": f.label_hi,
                             "type": f.field_type, "required": f.is_required}
                            for f in s.form_fields],
            "document_requirements": [{"label_en": r.label_en, "label_hi": r.label_hi,
                                       "required": r.is_required} for r in s.document_requirements],
        })
    log_admin_action(current_user, "catalogue_exported", "service", None, {"format": "json"})
    db.session.commit()
    return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=service_catalogue.json"})
