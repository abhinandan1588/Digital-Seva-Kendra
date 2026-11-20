"""Configuration classes for the Digital Seva Kendra portal.

All secrets and deployment-specific values are read from environment
variables (loaded from .env in development). Never hardcode credentials.
"""
import os
from datetime import timedelta

from dotenv import load_dotenv

# Load .env from the project root (two levels above this file). override=True
# so the project's own .env always wins over stray DATABASE_URL-style variables
# that a parent-directory .env (e.g. a shared workspace) may have exported.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)


def _sqlite_url(filename: str) -> str:
    """Zero-setup fallback database (development only): file-based SQLite."""
    return "sqlite:///" + os.path.join(INSTANCE_DIR, filename)


def _bool(key: str, default: str = "false") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes", "on")


def _int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


class Config:
    """Base configuration shared by all environments."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-change-me")
    # DATABASE_URL wins when set; otherwise a zero-setup SQLite file is used so
    # `python run.py` works on any machine. Use PostgreSQL in production.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or _sqlite_url("digital_seva.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Sessions / security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE")
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_TIME_LIMIT = None  # token valid for the whole session

    # Admin bootstrap (used only by `flask create-admin`)
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
    ADMIN_INITIAL_PASSWORD = os.environ.get("ADMIN_INITIAL_PASSWORD", "")
    ADMIN_NAME = os.environ.get("ADMIN_NAME", "Shop Owner")

    # First-boot bootstrap: when the database is empty (no schema yet, or the
    # services table exists but is empty), create the schema and load default
    # settings + the full built-in catalogue (and the first admin when
    # ADMIN_EMAIL/ADMIN_INITIAL_PASSWORD are set) automatically on startup.
    AUTO_SEED_CATALOGUE = _bool("AUTO_SEED_CATALOGUE", "true")

    # Rate limiting
    RATELIMIT_ENABLED = _bool("RATELIMIT_ENABLED", "true")
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = "200 per hour"

    # Uploads
    MAX_CONTENT_LENGTH = _int("MAX_CONTENT_LENGTH_MB", 25) * 1024 * 1024
    UPLOAD_DEFAULT_MAX_MB = _int("UPLOAD_DEFAULT_MAX_MB", 5)
    # Local secure staging area for files before they reach Google Drive
    STAGING_DIR = os.environ.get("STAGING_DIR", os.path.join(INSTANCE_DIR, "staging"))
    # Locally generated QR codes (cache)
    QR_CACHE_DIR = os.path.join(INSTANCE_DIR, "qrcodes")
    # Built React SPA (frontend/) served under /app/ by the spa blueprint.
    SPA_DIST_DIR = os.path.join(BASE_DIR, "frontend", "dist")

    # Public assets uploaded by admin (logo, category/service images, banner)
    PUBLIC_UPLOAD_DIR = os.path.join(BASE_DIR, "app", "static", "uploads")
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
    ALLOWED_DOCUMENT_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}

    # Storage backend: "auto" = Google Drive when configured, local fallback otherwise
    STORAGE_PROVIDER = os.environ.get("STORAGE_PROVIDER", "auto")
    DRIVE_ROOT_FOLDER_NAME = os.environ.get("DRIVE_ROOT_FOLDER_NAME", "Digital Seva Kendra")
    GOOGLE_CLIENT_SECRETS_FILE = os.environ.get("GOOGLE_CLIENT_SECRETS_FILE", "")
    GOOGLE_OAUTH_REDIRECT_URI = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "")

    # Business defaults
    DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "en")
    SUPPORTED_LANGUAGES = ("en", "hi")
    CURRENCY = "INR"
    TIMEZONE = "Asia/Kolkata"

    # Notification providers (left empty in v1 -> honest "not configured" state)
    WHATSAPP_PROVIDER_URL = os.environ.get("WHATSAPP_PROVIDER_URL", "")
    WHATSAPP_PROVIDER_KEY = os.environ.get("WHATSAPP_PROVIDER_KEY", "")
    SMS_PROVIDER_URL = os.environ.get("SMS_PROVIDER_URL", "")
    SMS_PROVIDER_KEY = os.environ.get("SMS_PROVIDER_KEY", "")
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = _int("SMTP_PORT", 587)
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "")

    # Staging files older than this are removed by `flask cleanup-staging`
    STAGING_MAX_AGE_HOURS = _int("STAGING_MAX_AGE_HOURS", 24)


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL") or _sqlite_url("digital_seva_test.db")
    SECRET_KEY = "test-secret-key"
    RATELIMIT_ENABLED = False
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False  # tests post forms directly; CSRF is tested separately
    STORAGE_PROVIDER = "local"
    AUTO_SEED_CATALOGUE = False  # tests control their own fixture data
    PRESERVE_CONTEXT_ON_EXCEPTION = False
    # No pooled lingering connections: each request opens/closes its own.
    from sqlalchemy.pool import NullPool
    SQLALCHEMY_ENGINE_OPTIONS = {"poolclass": NullPool}


class ProductionConfig(Config):
    """Production settings. Checks live in validate_production_config() and run
    only when this class is actually selected — checks in the class body would
    execute at import time and crash every command (even dev) when no
    SECRET_KEY is configured."""

    DEBUG = False


CONFIG_BY_NAME = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}


def validate_production_config() -> None:
    """Fail fast when FLASK_CONFIG=production is selected."""
    key = os.environ.get("SECRET_KEY", "")
    if not key or "dev-insecure" in key:
        raise RuntimeError("SECRET_KEY must be set to a strong random value in production.")
    # SQLite cannot handle multiple gunicorn workers safely — require PostgreSQL.
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "FLASK_CONFIG=production requires DATABASE_URL pointing at PostgreSQL "
            "(the SQLite fallback is a development-only convenience)."
        )


def get_config_class():
    name = os.environ.get("FLASK_CONFIG", "default")
    config_class = CONFIG_BY_NAME.get(name, DevelopmentConfig)
    if config_class is ProductionConfig:
        validate_production_config()
    return config_class
