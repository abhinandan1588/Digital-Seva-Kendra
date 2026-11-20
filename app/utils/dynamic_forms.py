"""Dynamic application form: render + server-side validation.

The admin configures fields per service; this module renders them (Jinja
macro) and validates the POSTed data against the stored configuration.
Client-side validation is treated as convenience only - never trusted.
"""
import os

from werkzeug.datastructures import FileStorage

from ..config import Config
from ..extensions import db
from ..models import ServiceFormField, ServiceDocumentRequirement, UploadedDocument, JSONB
from .files import validate_upload, safe_stored_name, MIME_BY_EXT, allowed_extension
from .customer_common import find_wallet_entry, staged_from_wallet
from .i18n import pick, t


# --------------------------------------------------------------------------
# Field value validation
# --------------------------------------------------------------------------

def _validate_field_value(field: ServiceFormField, raw_value, files_for_field: dict,
                          wallet_refs: list[str] | None = None) -> tuple[bool, str, dict]:
    """Validate one field. Returns (ok, error_key, cleaned) where cleaned has
    value_text / value_json / files (list of validated FileStorage) /
    wallet_entries (list of wallet dicts for `wallet:<id>` references)."""
    ftype = field.field_type

    if ftype == "checkbox":
        values = raw_value if isinstance(raw_value, list) else ([raw_value] if raw_value else [])
        options = _option_values(field)
        cleaned = [v for v in values if v in options]
        if field.is_required and not cleaned:
            return False, "required", {}
        return True, "", {"value_json": cleaned, "value_text": ", ".join(cleaned)}

    value = (raw_value or "").strip() if isinstance(raw_value, str) else (raw_value or "")

    if ftype in ("select", "radio"):
        options = _option_values(field)
        if value and value not in options:
            return False, "invalid_option", {}
        if field.is_required and not value:
            return False, "required", {}
        return True, "", {"value_text": value}

    if ftype in ("file", "file_multi", "image"):
        allowed = field.allowed_extensions or ["pdf", "jpg", "jpeg", "png"]
        max_mb = field.max_file_mb or Config.UPLOAD_DEFAULT_MAX_MB
        uploaded = files_for_field.get(field.field_key, [])
        if field.field_type == "image":
            allowed = [a for a in allowed if a in ("jpg", "jpeg", "png", "webp")]
        # wallet references: value under the field key = "wallet:<entry_id>"
        wallet_entries = []
        for ref in (wallet_refs or []):
            ref = (ref or "").strip()
            if not ref:
                continue
            if not ref.startswith("wallet:"):
                return False, "bad_content", {}
            entry = find_wallet_entry(ref[7:])
            if entry is None:
                return False, "wallet_missing", {}
            if not allowed_extension(entry["original_name"], allowed):
                return False, "file_bad_type", {}
            if entry["size_bytes"] > max(int(max_mb), 1) * 1024 * 1024:
                return False, "file_too_large", {}
            wallet_entries.append(entry)
        if field.is_required and not uploaded and not wallet_entries:
            return False, "required", {}
        if field.field_type != "file_multi" and len(uploaded) + len(wallet_entries) > 1:
            return False, "too_many", {}
        cleaned_files = []
        for f in uploaded:
            ok, err = validate_upload(f.stream, f.filename, allowed, max_mb)
            if not ok:
                return False, f"file_{err}", {}
            cleaned_files.append(f)
        return True, "", {"files": cleaned_files, "wallet_entries": wallet_entries}

    # text-like fields
    if field.is_required and not value:
        return False, "required", {}
    if field.min_length and len(value) < field.min_length:
        return False, "too_short", {}
    if field.max_length and len(value) > field.max_length:
        return False, "too_long", {}
    if ftype == "email":
        if value and ("@" not in value or "." not in value.split("@")[-1]):
            return False, "invalid_email", {}
    if ftype == "mobile":
        digits = value.replace(" ", "").replace("-", "").lstrip("+")
        if digits and (not digits.isdigit() or not (10 <= len(digits) <= 13)):
            return False, "invalid_mobile", {}
    if ftype == "number":
        if value:
            try:
                num = float(value)
            except ValueError:
                return False, "invalid_number", {}
            if field.min_value is not None and num < float(field.min_value):
                return False, "range", {}
            if field.max_value is not None and num > float(field.max_value):
                return False, "range", {}
    return True, "", {"value_text": value}


def _option_values(field: ServiceFormField) -> list[str]:
    out = []
    for opt in (field.options or []):
        if isinstance(opt, dict):
            out.append(pick(opt.get("en", ""), opt.get("hi", "")))
        elif isinstance(opt, str):
            out.append(opt)
    return out


def validate_dynamic_form(fields: list[ServiceFormField], request) -> tuple[dict, dict]:
    """Validate the whole dynamic form of a service.

    Returns (values_by_key, errors_by_key). values_by_key maps field_key ->
    cleaned dict. errors_by_key maps field_key -> i18n error key.
    """
    values: dict[str, dict] = {}
    errors: dict[str, str] = {}

    # collect files per field_key: input name = f"file_{field_key}"
    files_by_key: dict[str, list] = {}
    for key, storage in request.files.items():
        if not key.startswith("file_"):
            continue
        file_key = key[5:]
        if isinstance(storage, FileStorage) and storage.filename:
            files_by_key.setdefault(file_key, []).append(storage)

    for field in fields:
        if not field.is_active:
            continue
        raw = request.form.get(field.field_key)
        wallet_refs: list[str] = []
        if field.field_type in ("file", "file_multi", "image"):
            wallet_refs = [v for v in request.form.getlist(field.field_key) if v]
        elif field.field_type == "checkbox":
            raw = request.form.getlist(field.field_key)
        ok, err, cleaned = _validate_field_value(field, raw, files_by_key, wallet_refs)
        if not ok:
            errors[field.field_key] = err
        else:
            cleaned.setdefault("files", [])
            cleaned.setdefault("wallet_entries", [])
            values[field.field_key] = cleaned
    return values, errors


# --------------------------------------------------------------------------
# Document requirement validation
# --------------------------------------------------------------------------

def validate_document_uploads(requirements: list[ServiceDocumentRequirement], request) -> tuple[dict, dict, dict]:
    """Validate uploads for service_document_requirements.

    Each requirement accepts either real files (input `req_<id>`) or wallet
    references (form value `wallet:<entry_id>` under the same input name).

    Returns (uploaded_by_req_id, wallet_by_req_id, errors_by_req_id): the
    first two map id -> list of (FileStorage, requirement) pairs / wallet
    entries; errors maps id -> i18n error key.
    """
    uploaded: dict[int, list] = {}
    wallet_by_req: dict[int, list] = {}
    errors: dict[int, str] = {}
    for req in requirements:
        if not req.is_active:
            continue
        input_name = f"req_{req.id}"
        files = [f for f in request.files.getlist(input_name) if f and f.filename]
        wallet_entries = []
        for ref in request.form.getlist(input_name):
            ref = (ref or "").strip()
            if not ref:
                continue
            if not ref.startswith("wallet:"):
                errors[req.id] = "bad_content"
                break
            entry = find_wallet_entry(ref[7:])
            if entry is None:
                errors[req.id] = "wallet_missing"
                break
            if not allowed_extension(entry["original_name"],
                                     req.allowed_extensions or Config.ALLOWED_DOCUMENT_EXTENSIONS):
                errors[req.id] = "file_bad_type"
                break
            if entry["size_bytes"] > req.max_file_mb * 1024 * 1024:
                errors[req.id] = "file_too_large"
                break
            wallet_entries.append(entry)
        if errors.get(req.id):
            continue
        if req.is_required and not files and not wallet_entries:
            errors[req.id] = "required"
            continue
        if not req.allow_multiple and len(files) + len(wallet_entries) > 1:
            errors[req.id] = "too_many"
            continue
        files_ok = True
        for f in files:
            ok, err = validate_upload(f.stream, f.filename, req.allowed_extensions or
                                      Config.ALLOWED_DOCUMENT_EXTENSIONS, req.max_file_mb)
            if not ok:
                errors[req.id] = f"file_{err}"
                files_ok = False
                break
        if files_ok:
            if files:
                uploaded[req.id] = files
            if wallet_entries:
                wallet_by_req[req.id] = wallet_entries
    return uploaded, wallet_by_req, errors


# --------------------------------------------------------------------------
# Staging of validated files (secure temp area before Drive upload)
# --------------------------------------------------------------------------

def stage_files(validated_pairs: list, purpose_label: str) -> list[dict]:
    """Persist validated files into the secure staging directory.

    Returns metadata dicts consumed by the storage layer at checkout time.
    staged dicts: {abs_path, stored_name, original_name, mime_type, size_bytes,
                   label, form_field_id, requirement_id, sha256, source}
    The sha256 lets checkout store identical content (e.g. one wallet file
    reused for several applications) only once per order.
    """
    import hashlib
    from flask import current_app
    staging_dir = current_app.config["STAGING_DIR"]
    staged = []
    for fileobj, obj in validated_pairs:
        ext = fileobj.filename.rsplit(".", 1)[-1].lower()
        stored_name = safe_stored_name(ext)
        subdir = os.path.join(staging_dir, "apps")
        os.makedirs(subdir, exist_ok=True)
        abs_path = os.path.join(subdir, stored_name)
        fileobj.save(abs_path)
        size = os.path.getsize(abs_path)
        digest = hashlib.sha256()
        with open(abs_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        staged.append({
            "abs_path": abs_path,
            "stored_name": stored_name,
            "original_name": fileobj.filename[:255],
            "mime_type": MIME_BY_EXT.get(ext, "application/octet-stream"),
            "size_bytes": size,
            "label": purpose_label,
            "form_field_id": obj.id if obj is not None and hasattr(obj, "field_key") else None,
            "requirement_id": obj.id if obj is not None and hasattr(obj, "allow_multiple") else None,
            "sha256": digest.hexdigest(),
            "source": "upload",
        })
    return staged


def create_field_value_records(application, fields: list, values_by_key: dict) -> list:
    """Create ApplicationFieldValue rows for a validated form submission."""
    from ..models import ApplicationFieldValue
    records = []
    fields_by_key = {f.field_key: f for f in fields}
    for field_key, cleaned in values_by_key.items():
        field = fields_by_key.get(field_key)
        if field is None:
            continue
        record = ApplicationFieldValue(
            application=application,
            form_field_id=field.id,
            field_key=field.field_key,
            field_label_snapshot=field.label_en,
            field_type=field.field_type,
            value_text=cleaned.get("value_text"),
            value_json=cleaned.get("value_json"),
        )
        records.append(record)
    return records


def stage_field_files(fields: list, values_by_key: dict) -> list[dict]:
    """Stage files uploaded via file-type form fields (files + wallet refs)."""
    staged = []
    for field in fields:
        cleaned = values_by_key.get(field.field_key)
        if not cleaned:
            continue
        pairs = [(f, field) for f in cleaned.get("files", [])]
        staged.extend(stage_files(pairs, field.label_en))
        for entry in cleaned.get("wallet_entries", []):
            staged.append(staged_from_wallet(entry, field.label_en,
                                             form_field_id=field.id))
    return staged


def stage_requirement_files(uploaded_by_req: dict, wallet_by_req: dict,
                            requirements: list) -> list[dict]:
    """Stage files uploaded for document requirements (files + wallet refs)."""
    req_by_id = {r.id: r for r in requirements}
    staged = []
    for req_id, files in uploaded_by_req.items():
        req = req_by_id.get(req_id)
        if req is None:
            continue
        pairs = [(f, req) for f in files]
        staged.extend(stage_files(pairs, req.label_en))
    for req_id, entries in (wallet_by_req or {}).items():
        req = req_by_id.get(req_id)
        if req is None:
            continue
        for entry in entries:
            staged.append(staged_from_wallet(entry, req.label_en,
                                             requirement_id=req.id))
    return staged
