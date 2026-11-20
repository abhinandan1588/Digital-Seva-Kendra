"""Customer common details + document wallet (session-scoped).

Lets the SPA collect shared information ONCE for a whole cart instead of
re-typing / re-uploading it for every application:

- profile: name / mobile / email / address (prefills checkout contact)
- answers: remembered text answers per dynamic field_key, so identical
  fields across services are asked only once
- wallet: documents uploaded once into a private instance directory; every
  entry is keyed by the SHA-256 of its content, so re-uploading the same
  file never duplicates storage. At checkout the same wallet file attached
  to several applications is uploaded to the storage provider ONCE per
  order (see utils/checkout.py).

Files live server-side (never in the cookie); the session only stores
metadata. No PII goes beyond what the cart flow already stores.
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, session

from .files import validate_upload, MIME_BY_EXT, allowed_extension

PROFILE_KEY = "dsk_customer_profile"
ANSWERS_KEY = "dsk_common_answers"
WALLET_KEY = "dsk_doc_wallet"

# Wallet accepts any document type any requirement may ask for.
WALLET_ALLOWED_EXTENSIONS = ("pdf", "jpg", "jpeg", "png", "webp")

ANSWER_MAX_KEYS = 80
ANSWER_VALUE_MAX_CHARS = 500
WALLET_MAX_FILES_PER_POST = 10


# --------------------------------------------------------------------------
# Profile (checkout contact details, filled once)
# --------------------------------------------------------------------------

def get_profile() -> dict:
    return dict(session.get(PROFILE_KEY) or {})


def save_profile(data: dict) -> dict:
    """Validate + store. Returns {} when stored, else error codes by field."""
    name = (data.get("name") or "").strip()
    mobile = (data.get("mobile") or "").replace(" ", "")
    email = (data.get("email") or "").strip()
    address = (data.get("address") or "").strip()

    errors = {}
    if len(name) < 2:
        errors["name"] = "invalid_name"
    digits = mobile.lstrip("+")
    if not (mobile.isdigit() or (mobile.startswith("+") and digits.isdigit())) \
            or not (10 <= len(digits) <= 13):
        errors["mobile"] = "invalid_mobile"
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        errors["email"] = "invalid_email"
    if errors:
        return errors

    session[PROFILE_KEY] = {
        "name": name[:120], "mobile": digits[-13:],
        "email": email[:200], "address": address[:500],
    }
    session.modified = True
    return {}


# --------------------------------------------------------------------------
# Answer memory (same dynamic field asked only once)
# --------------------------------------------------------------------------

def get_answers() -> dict:
    return dict(session.get(ANSWERS_KEY) or {})


def remember_answers(values_by_key: dict) -> None:
    """Merge cleaned dynamic-form values into the answer memory.

    Only text-like answers are remembered (files go through the wallet).
    """
    stored = session.get(ANSWERS_KEY) or {}
    for key, cleaned in (values_by_key or {}).items():
        text = cleaned.get("value_text")
        value_json = cleaned.get("value_json")
        if not text and value_json is None:
            continue
        if isinstance(value_json, list):
            stored[key] = {"value_text": text or "", "value_json": value_json}
        else:
            stored[key] = {"value_text": (text or "")[:ANSWER_VALUE_MAX_CHARS],
                           "value_json": None}
    # hard cap so a crafted session cannot grow unbounded
    session[ANSWERS_KEY] = dict(list(stored.items())[:ANSWER_MAX_KEYS])
    session.modified = True


def remember_raw_answers(raw: dict) -> None:
    """Store plain text answers sent by the SPA (prefill hints only).

    Values are re-validated against each service's field configuration when
    the form is saved, so these are convenience hints, never trusted data.
    """
    if not isinstance(raw, dict):
        return
    stored = session.get(ANSWERS_KEY) or {}
    for key, value in list(raw.items())[:ANSWER_MAX_KEYS]:
        key = str(key)[:60]
        if isinstance(value, list):
            stored[key] = {"value_text": ", ".join(str(v) for v in value[:20])[:ANSWER_VALUE_MAX_CHARS],
                           "value_json": [str(v)[:ANSWER_VALUE_MAX_CHARS] for v in value[:20]]}
        elif value is not None:
            stored[key] = {"value_text": str(value)[:ANSWER_VALUE_MAX_CHARS], "value_json": None}
    session[ANSWERS_KEY] = stored
    session.modified = True


# --------------------------------------------------------------------------
# Document wallet (upload once, reuse for every requirement)
# --------------------------------------------------------------------------

def wallet_dir() -> str:
    path = current_app.config.get("WALLET_DIR") or os.path.join(
        current_app.instance_path, "wallet")
    os.makedirs(path, exist_ok=True)
    return path


def _wallet_entry_json(entry: dict) -> dict:
    return {
        "id": entry["id"], "original_name": entry["original_name"],
        "mime_type": entry["mime_type"], "size_bytes": entry["size_bytes"],
        "ext": entry["ext"], "created_at": entry["created_at"],
    }


def wallet_json() -> list[dict]:
    return [_wallet_entry_json(e) for e in get_wallet()]


def get_wallet() -> list[dict]:
    entries = []
    for entry in session.get(WALLET_KEY, []):
        if os.path.isfile(entry.get("abs_path", "")):
            entries.append(entry)
    return entries


def find_wallet_entry(entry_id: str) -> dict | None:
    entry_id = (entry_id or "").strip()
    for entry in get_wallet():
        if entry["id"] == entry_id:
            return entry
    return None


def add_wallet_files(filestorages: list) -> tuple[list[dict], list[str]]:
    """Validate + store wallet files. Returns (new_entries_json, error_codes).

    Identical content (same SHA-256) is stored once: a re-upload refreshes
    the display name instead of writing a second file.
    """
    added = []
    errors = []
    stored = {e["id"]: e for e in session.get(WALLET_KEY, [])}
    for f in (filestorages or [])[:WALLET_MAX_FILES_PER_POST]:
        if f is None or not f.filename:
            continue
        ok, err = validate_upload(f.stream, f.filename, WALLET_ALLOWED_EXTENSIONS,
                                  current_app.config["UPLOAD_DEFAULT_MAX_MB"])
        if not ok:
            errors.append(err or "bad_content")
            continue
        digest = hashlib.sha256()
        f.stream.seek(0)
        for chunk in iter(lambda: f.stream.read(65536), b""):
            digest.update(chunk)
        sha = digest.hexdigest()
        entry_id = sha[:16]
        ext = f.filename.rsplit(".", 1)[-1].lower()
        if entry_id in stored and os.path.isfile(stored[entry_id]["abs_path"]):
            # Same content already in the wallet: keep one file on disk.
            stored[entry_id]["original_name"] = f.filename[:255]
            added.append(_wallet_entry_json(stored[entry_id]))
            continue
        stored_name = f"{entry_id}.{ext}"
        abs_path = os.path.join(wallet_dir(), stored_name)
        f.stream.seek(0)
        f.save(abs_path)
        entry = {
            "id": entry_id, "sha256": sha, "stored_name": stored_name,
            "abs_path": abs_path, "original_name": f.filename[:255],
            "mime_type": MIME_BY_EXT.get(ext, "application/octet-stream"),
            "size_bytes": os.path.getsize(abs_path), "ext": ext,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        stored[entry_id] = entry
        added.append(_wallet_entry_json(entry))
    session[WALLET_KEY] = list(stored.values())[-WALLET_MAX_FILES_PER_POST * 10:]
    session.modified = True
    return added, errors


def remove_wallet_entry(entry_id: str) -> bool:
    entry_id = (entry_id or "").strip()
    remaining = []
    removed = False
    for entry in session.get(WALLET_KEY, []):
        if entry["id"] == entry_id:
            removed = True
            try:
                os.remove(entry["abs_path"])
            except OSError:
                pass
        else:
            remaining.append(entry)
    if removed:
        session[WALLET_KEY] = remaining
        session.modified = True
    return removed


def cleanup_wallet(max_age_hours: int = 24 * 7) -> tuple[int, int]:
    """Delete wallet files older than `max_age_hours` (sessions expire much
    sooner). Returns (removed_files, kept_files)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    removed = kept = 0
    path = wallet_dir()
    for name in os.listdir(path):
        full = os.path.join(path, name)
        if not os.path.isfile(full):
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(full), timezone.utc)
        if mtime < cutoff:
            try:
                os.remove(full)
                removed += 1
            except OSError:
                kept += 1
        else:
            kept += 1
    return removed, kept


def staged_from_wallet(entry: dict, label: str, *, form_field_id=None,
                       requirement_id=None) -> dict:
    """Build a staged-file dict referencing the wallet's own file.

    `source: wallet` keeps upload_document_record from deleting the wallet
    file, and the shared stored_name/sha256 let checkout store identical
    content only once per order.
    """
    return {
        "abs_path": entry["abs_path"],
        "stored_name": entry["stored_name"],
        "original_name": entry["original_name"],
        "mime_type": entry["mime_type"],
        "size_bytes": entry["size_bytes"],
        "label": label,
        "form_field_id": form_field_id,
        "requirement_id": requirement_id,
        "sha256": entry["sha256"],
        "source": "wallet",
    }


# --------------------------------------------------------------------------
# Wallet <-> requirement/field matching (suggestions for the SPA)
# --------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    out = set()
    for token in (text or "").lower().replace("_", " ").split():
        token = "".join(ch for ch in token if ch.isalnum())
        if len(token) >= 3:
            out.add(token)
    return out


def _tokens_overlap(label_tokens: set[str], name_tokens: set[str]) -> bool:
    """Exact or prefix overlap ("photo" ~ "photograph", min 4 chars)."""
    for a in label_tokens:
        for b in name_tokens:
            if a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a))):
                return True
    return False


def compatible_extensions(ext: str, allowed: list[str]) -> bool:
    return ext in {a.lower().lstrip(".") for a in (allowed or [])}


def suggest_wallet_entry(entry_list: list[dict], label: str,
                         allowed_extensions: list[str]) -> str | None:
    """Best wallet entry id for one requirement/field, or None.

    Prefers a filename that shares a token with the label (e.g. an uploaded
    "aadhaar_front.png" for a requirement named "Aadhaar Document"); falls
    back to the first extension-compatible entry.
    """
    compatible = [e for e in entry_list
                  if compatible_extensions(e["ext"], allowed_extensions)]
    if not compatible:
        return None
    label_tokens = _tokens(label)
    for entry in compatible:
        if _tokens_overlap(label_tokens, _tokens(entry["original_name"].rsplit(".", 1)[0])):
            return entry["id"]
    return compatible[0]["id"]
