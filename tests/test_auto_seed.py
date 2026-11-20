"""First-boot auto-seed + admin one-click built-in catalogue load.

Covers the zero-manual-setup promise: a fresh, EMPTY database is bootstrapped
automatically on startup - schema created, settings + full catalogue + optional
env-configured admin loaded - and the admin panel offers the same load as a
button. Regression tests cover the "no such table: services" crash that
happened when the app was started without ever running `flask db upgrade`.
"""
from sqlalchemy import text

from app.cli_catalogue import seed_catalogue_data
from app.first_boot import run_first_boot_bootstrap
from app.extensions import db
from app.models import (Service, ServiceCategory, ServiceSubcategory,
                        OfficialPortal, DocumentTemplate, WebsiteSetting,
                        AdminUser)


def test_seed_catalogue_data_populates_everything(app):
    with app.app_context():
        counts = seed_catalogue_data()
        assert counts["services"] >= 300
        assert Service.query.count() == counts["services"]
        assert ServiceCategory.query.count() == counts["categories"]
        assert ServiceSubcategory.query.count() == counts["subcategories"]
        assert OfficialPortal.query.count() == counts["portals"]
        assert DocumentTemplate.query.count() == counts["doc_templates"]
        # update-or-create: a second run creates nothing new
        counts2 = seed_catalogue_data()
        assert counts2["services"] == 0
        assert Service.query.count() == counts["services"]


def _drop_alembic_version() -> None:
    """The alembic_version table is not in ORM metadata (drop_all keeps it),
    so remove it explicitly when a test manipulates it."""
    db.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
    db.session.commit()


def test_first_boot_creates_schema_on_empty_database(app):
    """Fresh install with NO migrations run: booting the app must create the
    schema, then seed - the homepage must not crash with
    'no such table: services'."""
    with app.app_context():
        db.drop_all()  # simulate a brand-new empty database file
        _drop_alembic_version()  # clear any leftover from a previous run
        app.config["AUTO_SEED_CATALOGUE"] = True
        app.config["ADMIN_EMAIL"] = ""
        run_first_boot_bootstrap(app)
        from sqlalchemy import inspect as sa_inspect
        tables = set(sa_inspect(db.engine).get_table_names())
        assert "services" in tables
        assert "alembic_version" in tables  # stamped for future migrations
        assert Service.query.count() >= 300
        assert WebsiteSetting.query.count() > 0
        # ...and the homepage renders instead of raising OperationalError
        resp = app.test_client().get("/")
        assert resp.status_code == 200
        _drop_alembic_version()  # leave the fixture DB in its expected state


def test_first_boot_wont_touch_migration_managed_db(app):
    """alembic_version present but tables missing = intermediate migration
    state: the bootstrap must NOT create_all; it requires `flask db upgrade`."""
    with app.app_context():
        db.drop_all()
        db.session.execute(text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        db.session.commit()
        app.config["AUTO_SEED_CATALOGUE"] = True
        run_first_boot_bootstrap(app)
        from sqlalchemy import inspect as sa_inspect
        tables = set(sa_inspect(db.engine).get_table_names())
        assert "services" not in tables  # untouched - migrations own this DB
        # clean up the manually created table so later fixtures are unaffected
        _drop_alembic_version()
        db.create_all()


def test_first_boot_bootstrap_loads_empty_database(app):
    with app.app_context():
        app.config["AUTO_SEED_CATALOGUE"] = True
        run_first_boot_bootstrap(app)
        assert Service.query.count() >= 300
        assert WebsiteSetting.query.count() > 0


def test_first_boot_bootstrap_never_duplicates(app):
    with app.app_context():
        app.config["AUTO_SEED_CATALOGUE"] = True
        run_first_boot_bootstrap(app)
        total = Service.query.count()
        run_first_boot_bootstrap(app)
        assert Service.query.count() == total


def test_first_boot_bootstrap_creates_admin_from_env(app):
    with app.app_context():
        app.config["AUTO_SEED_CATALOGUE"] = True
        app.config["ADMIN_EMAIL"] = "owner@example.com"
        app.config["ADMIN_INITIAL_PASSWORD"] = "StrongPass#99"
        app.config["ADMIN_NAME"] = "Owner"
        run_first_boot_bootstrap(app)
        user = AdminUser.query.filter_by(email="owner@example.com").one()
        assert user.check_password("StrongPass#99")


def test_admin_load_builtin_button(app, admin_client):
    with app.app_context():
        assert Service.query.count() == 0
        resp = admin_client.post("/admin/catalogue/load-builtin", data={},
                                 follow_redirects=True)
        assert resp.status_code == 200
        assert Service.query.count() >= 300
        # Second click without the update checkbox: safe no-op
        total = Service.query.count()
        resp2 = admin_client.post("/admin/catalogue/load-builtin", data={},
                                  follow_redirects=True)
        assert resp2.status_code == 200
        assert b"nothing was changed" in resp2.data.lower()
        assert Service.query.count() == total


def test_admin_load_builtin_update_existing(app, admin_client):
    with app.app_context():
        admin_client.post("/admin/catalogue/load-builtin", data={})
        service = Service.query.first()
        service.name_en = "Manually Renamed"
        db.session.commit()
        # Re-load WITHOUT the checkbox: manual edits survive
        admin_client.post("/admin/catalogue/load-builtin", data={})
        db.session.expire_all()
        assert Service.query.filter_by(name_en="Manually Renamed").count() == 1
        # Re-load WITH the checkbox: shipped data-file values win
        admin_client.post("/admin/catalogue/load-builtin",
                          data={"update_existing": "on"})
        db.session.expire_all()
        assert Service.query.filter_by(name_en="Manually Renamed").count() == 0
