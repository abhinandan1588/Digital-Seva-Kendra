"""Google Drive settings: OAuth credential storage (encrypted) + service builder.

Credentials are stored encrypted (Fernet, key derived from SECRET_KEY) in
website_settings - never in code, never exposed to the frontend. The
Google client secrets JSON file path comes from the environment.
"""
import base64
import hashlib
import json

from flask import current_app

from ..models.settings import WebsiteSetting
from ..extensions import db

CREDS_KEY = "drive_oauth_credentials"


def _fernet():
    from cryptography.fernet import Fernet
    secret = current_app.config["SECRET_KEY"].encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def save_credentials(credentials_dict: dict) -> None:
    """Encrypt and persist OAuth credentials JSON."""
    payload = _fernet().encrypt(json.dumps(credentials_dict).encode())
    row = db.session.get(WebsiteSetting, CREDS_KEY)
    if row is None:
        row = WebsiteSetting(key=CREDS_KEY, group="payment")
        db.session.add(row)
    row.value_text = payload.decode()
    db.session.commit()


def load_credentials() -> dict | None:
    row = db.session.get(WebsiteSetting, CREDS_KEY)
    if not row or not row.value_text:
        return None
    try:
        return json.loads(_fernet().decrypt(row.value_text.encode()))
    except Exception:
        current_app.logger.warning("Drive credentials could not be decrypted; reconnect needed.")
        return None


def clear_credentials() -> None:
    row = db.session.get(WebsiteSetting, CREDS_KEY)
    if row:
        db.session.delete(row)
        db.session.commit()


def is_drive_connected() -> bool:
    creds = load_credentials()
    return bool(creds and creds.get("refresh_token"))


def get_drive_service():
    """Build a googleapiclient Drive service or None when not configured."""
    creds_dict = load_credentials()
    if not creds_dict:
        return None
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_authorized_user_info(creds_dict, scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())  # handled server-side; tokens never leave backend
        save_credentials(json.loads(creds.to_json()))
    return build("drive", "v3", credentials=creds, cache_discovery=False)
