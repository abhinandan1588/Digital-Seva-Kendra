"""Website settings access layer with a per-request cache."""
from flask import g, current_app

from ..models.settings import WebsiteSetting, DEFAULT_SETTINGS, _group_for
from ..extensions import db


def load_all_settings() -> dict:
    """Load every setting into a plain dict (cached on flask.g)."""
    cached = getattr(g, "_settings_cache", None)
    if cached is not None:
        return cached
    settings = {key: (en or "") for key, (en, _hi) in DEFAULT_SETTINGS.items()}
    try:
        for row in WebsiteSetting.query.all():
            settings[row.key] = row.value_text or ""
    except Exception:
        # DB not migrated yet (first boot) - fall back to defaults
        current_app.logger.warning("Settings table unavailable; using defaults.")
    g._settings_cache = settings
    return settings


def get_setting(key: str, default: str = "") -> str:
    settings = getattr(g, "settings", None)
    if settings is None:
        settings = load_all_settings()
        g.settings = settings
    return settings.get(key, default)


def set_setting(key: str, value: str, admin_id=None) -> None:
    row = db.session.get(WebsiteSetting, key)
    if row is None:
        row = WebsiteSetting(key=key, group=_group_for(key))
        db.session.add(row)
    row.value_text = value
    if admin_id:
        row.updated_by_admin_id = admin_id
    g.pop("_settings_cache", None)
