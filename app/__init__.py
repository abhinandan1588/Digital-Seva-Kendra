"""Flask application factory for the Digital Seva Kendra portal.

Public customer flow needs no login; only /admin is protected with
Flask-Login. Blueprints keep routes modular; business logic lives in
app/utils and app/storage service layers.
"""
import logging
import os

from flask import Flask, render_template, request, g

from .config import get_config_class, validate_production_config, ProductionConfig
from .api.routes import api_bp, spa_bp
from .extensions import db, migrate, csrf, login_manager, limiter

from werkzeug.middleware.proxy_fix import ProxyFix

DEFAULT_BLUEPRINT_PREFIXES = None  # registered explicitly below


def create_app(config_class=None) -> Flask:
    config_class = config_class or get_config_class()
    if config_class is ProductionConfig:
        validate_production_config()
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Ensure instance-like local dirs exist.
    os.makedirs(app.config["STAGING_DIR"], exist_ok=True)
    os.makedirs(app.config["QR_CACHE_DIR"], exist_ok=True)
    os.makedirs(app.config["PUBLIC_UPLOAD_DIR"], exist_ok=True)

    # --- Extensions -------------------------------------------------------
    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)

    from .models.admin import AdminUser

    @login_manager.user_loader
    def load_user(user_id):  # pragma: no cover - trivial loader
        return db.session.get(AdminUser, int(user_id))

    # --- Blueprints -------------------------------------------------------
    from .auth.routes import auth_bp
    from .public.routes import public_bp
    from .services.routes import services_bp
    from .services.category_routes import category_bp
    from .exams.routes import exams_bp
    from .orders.routes import orders_bp
    from .applications.routes import applications_bp
    from .payments.routes import payments_bp
    from .admin.routes import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(services_bp)
    app.register_blueprint(category_bp)
    app.register_blueprint(exams_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # JSON API + React SPA (frontend/) — additive; Jinja templates untouched.
    csrf.exempt(api_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(spa_bp)

    # --- Request-scoped settings cache ------------------------------------
    from .utils.settings import load_all_settings

    @app.before_request
    def _cache_settings():
        g.settings = load_all_settings()

    # --- Template globals & filters ---------------------------------------
    from .utils.i18n import current_lang, t, pick
    from .utils.formatting import inr, fmt_dt, fmt_date
    from .utils.cart import cart_service_count
    from .models.order import status_label

    @app.context_processor
    def inject_globals():
        import datetime
        s = getattr(g, "settings", load_all_settings())
        return {
            "site_settings": s,
            "lang": current_lang,
            "_t": t,
            "_pick": pick,
            "_inr": inr,
            "_dt": fmt_dt,
            "_d": fmt_date,
            "status_label": status_label,
            "cart_count": cart_service_count,
            "current_year": datetime.datetime.now().year,
        }

    def _real_csrf_token():
        from flask_wtf.csrf import generate_csrf

        return generate_csrf()

    app.jinja_env.globals["csrf_token"] = _real_csrf_token
    app.jinja_env.filters["inr"] = inr
    app.jinja_env.filters["dt"] = fmt_dt
    app.jinja_env.filters["dtdate"] = fmt_date

    # --- Error handlers ----------------------------------------------------
    @app.errorhandler(403)
    def forbidden(e):
        if request.path.startswith("/admin"):
            return render_template("errors/403.html"), 403
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(e):
        limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return render_template("errors/413.html", limit_mb=limit_mb), 413

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    # --- Health check -------------------------------------------------------
    @app.route("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    # --- Logging: never log customer PII; keep default concise format ------
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    # --- CLI commands --------------------------------------------------------
    from .cli import register_cli

    register_cli(app)

    # --- First-boot bootstrap ------------------------------------------------
    # Fresh deployment with an empty database: schema, default settings, the
    # full built-in catalogue and (when env-configured) the first admin are
    # created automatically - no manual `flask db upgrade` / `flask
    # seed-catalogue` needed. Every step is guarded; see app/first_boot.py.
    if app.config.get("AUTO_SEED_CATALOGUE", True):
        from .first_boot import run_first_boot_bootstrap

        run_first_boot_bootstrap(app)

    if not app.debug and not app.testing:
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
        )

    return app
