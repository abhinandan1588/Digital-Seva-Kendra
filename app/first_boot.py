"""First-boot bootstrap: zero-manual-setup data loading.

On the first start (i.e. the database is empty or has no schema yet) the
application automatically:

1. creates the full table schema when the database has none (and marks the
   alembic head, so `flask db upgrade` stays usable afterwards),
2. inserts the default website settings (idempotent),
3. loads the full built-in catalogue from data/*.json (portals, document
   templates, search aliases, categories, subcategories, services and the
   review-pending exam cycle templates),
4. creates the first admin account when ADMIN_EMAIL and
   ADMIN_INITIAL_PASSWORD are configured.

Every step is individually guarded: a failure is logged and never prevents
startup. The same actions stay available manually via the CLI
(`flask db upgrade`, `flask seed-catalogue`, `flask create-admin`) and in the
admin panel (Catalogue -> Import/Export -> "Load built-in catalogue").
"""
import logging
import os

from .extensions import db

log = logging.getLogger("dsk.first_boot")


def run_first_boot_bootstrap(app) -> None:
    """Run the guarded first-boot steps inside an app context."""
    with app.app_context():
        if not _ensure_schema(app):
            return
        _ensure_settings()
        _seed_catalogue()
        _ensure_admin(app)


def _ensure_schema(app) -> bool:
    """Make sure the ORM tables exist before seeding data.

    Returns True when the schema is usable. Returns False (touching nothing)
    when the database is migration-managed but in an intermediate state -
    only `flask db upgrade` can fix that safely.
    """
    try:
        from sqlalchemy import inspect as sa_inspect
        tables = set(sa_inspect(db.engine).get_table_names())
    except Exception as exc:  # noqa: BLE001 - startup must never crash here
        db.session.rollback()
        log.warning("First-boot schema check skipped (database unavailable): %s",
                    type(exc).__name__)
        return False

    if "services" in tables:
        return True

    if "alembic_version" in tables:
        # Migrations ran before, but the services table is missing - an
        # intermediate migration state. Never fight it with create_all.
        log.warning("Database is migration-managed but the services table is "
                    "missing - run `flask db upgrade` to fix the schema.")
        return False

    # Fresh/empty database (e.g. plain `python run.py` without migrations):
    # create the full schema, then mark the alembic head so a later
    # `flask db upgrade` knows the current state instead of re-creating
    # existing tables.
    try:
        db.create_all()
        _stamp_alembic_head(app)
        log.info("First boot: database schema created automatically.")
        return True
    except Exception as exc:  # noqa: BLE001 - e.g. concurrent worker race
        db.session.rollback()
        log.warning("Automatic schema creation failed: %s (%s) - "
                    "run `flask db upgrade` instead.",
                    type(exc).__name__, exc)
        return False


def _stamp_alembic_head(app) -> None:
    """Mark the freshly created schema as the alembic head (best effort)."""
    try:
        from alembic import command
        from alembic.config import Config as AlembicConfig
        migrations_dir = os.path.join(os.path.dirname(app.root_path), "migrations")
        ini_path = os.path.join(migrations_dir, "alembic.ini")
        cfg = AlembicConfig(ini_path if os.path.exists(ini_path) else None)
        cfg.set_main_option("script_location", migrations_dir)
        cfg.set_main_option("sqlalchemy.url", app.config["SQLALCHEMY_DATABASE_URI"])
        command.stamp(cfg, "head")
    except Exception as exc:  # noqa: BLE001 - stamping is a convenience only
        db.session.rollback()
        log.info("Alembic stamp skipped (%s); run `flask db stamp head` manually "
                 "if you plan to use migrations.", type(exc).__name__)


def _ensure_settings() -> None:
    try:
        from .models.settings import ensure_default_settings
        ensure_default_settings()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log.warning("Default settings bootstrap skipped: %s", type(exc).__name__)


def _seed_catalogue() -> None:
    from .models import Service
    try:
        if Service.query.count() > 0:
            return  # already loaded - never touch a configured catalogue
        from .cli_catalogue import seed_catalogue_data
        counts = seed_catalogue_data()
        log.info("First boot: catalogue auto-seeded %s", counts)
    except Exception as exc:  # noqa: BLE001 - e.g. concurrent worker raced us
        db.session.rollback()
        log.warning("Catalogue auto-seed skipped: %s (%s)", type(exc).__name__, exc)


def _ensure_admin(app) -> None:
    """Create the first admin from env config (same rule as `flask create-admin`)."""
    email = (app.config.get("ADMIN_EMAIL") or "").strip().lower()
    password = app.config.get("ADMIN_INITIAL_PASSWORD") or ""
    if not email or not password:
        return  # nothing configured - admin creation stays a manual step
    try:
        from .models import AdminUser
        if AdminUser.query.count() > 0:
            return
        if len(password) < 8:
            log.warning("ADMIN_INITIAL_PASSWORD is shorter than 8 characters; "
                        "admin account not created. Use `flask create-admin`.")
            return
        user = AdminUser(email=email, name=app.config.get("ADMIN_NAME") or "Admin")
        user.set_password(password)
        user.is_active = True
        db.session.add(user)
        db.session.commit()
        log.info("First boot: admin account created for %s", email)
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log.warning("Admin bootstrap skipped: %s", type(exc).__name__)
