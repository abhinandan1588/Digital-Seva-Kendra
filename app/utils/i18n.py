"""Hindi/English language support helpers.

Language is stored in the session (switcher in the navbar). Model content
is bilingual: admins fill English and Hindi variants.
"""
from flask import session, request

from ..config import Config


def current_lang() -> str:
    try:
        lang = session.get("lang")
    except RuntimeError:  # outside request context (e.g. PDF generation)
        lang = None
    if lang in Config.SUPPORTED_LANGUAGES:
        return lang
    settings = {}
    try:
        from flask import g
        settings = getattr(g, "settings", {}) or {}
    except RuntimeError:
        pass
    default = settings.get("default_language") or Config.DEFAULT_LANGUAGE
    return default if default in Config.SUPPORTED_LANGUAGES else "en"


def set_lang(lang: str) -> None:
    if lang in Config.SUPPORTED_LANGUAGES:
        session["lang"] = lang


def pick(en_value, hi_value) -> str:
    """Pick the right language variant of model content, falling back sensibly."""
    lang = current_lang()
    if lang == "hi":
        value = hi_value or en_value
    else:
        value = en_value or hi_value
    return value or ""


def t(en_text: str, hi_text: str) -> str:
    """Translate a code-level literal (UI labels) by language."""
    return hi_text if current_lang() == "hi" else en_text
