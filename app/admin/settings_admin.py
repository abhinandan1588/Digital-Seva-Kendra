"""Admin settings: website, payment, Google Drive connect, notification
templates, customers directory, notifications list, staff (future-ready),
and profile."""
import os

from flask import (render_template, request, redirect, url_for, flash, abort,
                   current_app, session)
from flask_login import login_required, current_user

from . import admin_bp
from ..extensions import db
from ..models import (WebsiteSetting, Order, Customer, Notification,
                      AdminUser)
from ..models.settings import DEFAULT_SETTINGS
from ..utils.settings import set_setting, load_all_settings
from ..utils.audit import log_admin_action
from ..utils.i18n import t


# --------------------------------------------------------------------------
# Website settings
# --------------------------------------------------------------------------

@admin_bp.route("/settings/website", methods=["GET", "POST"])
@login_required
def settings_website():
    keys = ["shop_name", "shop_name_hi", "shop_tagline", "shop_tagline_hi",
            "shop_address", "shop_mobile", "shop_whatsapp", "shop_email",
            "working_hours", "homepage_banner_title", "homepage_banner_title_hi",
            "homepage_banner_subtitle", "homepage_banner_subtitle_hi",
            "footer_text", "footer_text_hi", "social_facebook", "social_instagram",
            "social_youtube", "privacy_policy", "privacy_policy_hi",
            "terms_conditions", "terms_conditions_hi", "default_language"]
    if request.method == "POST":
        for key in keys:
            set_setting(key, (request.form.get(key) or "").strip(), admin_id=current_user.id)
        # Logo upload
        logo = request.files.get("logo")
        if logo is not None and logo.filename:
            from ..utils.files import allowed_extension, safe_stored_name
            if allowed_extension(logo.filename, current_app.config["ALLOWED_IMAGE_EXTENSIONS"]):
                ext = logo.filename.rsplit(".", 1)[-1].lower()
                os.makedirs(current_app.config["PUBLIC_UPLOAD_DIR"], exist_ok=True)
                stored = safe_stored_name(ext)
                logo.save(os.path.join(current_app.config["PUBLIC_UPLOAD_DIR"], stored))
                set_setting("shop_logo_path", f"uploads/{stored}", admin_id=current_user.id)
        db.session.commit()
        log_admin_action(current_user, "settings_updated", "settings", "website")
        db.session.commit()
        flash("Website settings saved.", "success")
        return redirect(url_for("admin.settings_website"))
    settings = load_all_settings()
    return render_template("admin/settings_website.html", settings=settings, keys=keys)


# --------------------------------------------------------------------------
# Payment settings
# --------------------------------------------------------------------------

@admin_bp.route("/settings/payment", methods=["GET", "POST"])
@login_required
def settings_payment():
    keys = ["upi_id", "upi_merchant_name", "payment_instructions",
            "payment_instructions_hi", "payment_support_info", "payment_support_info_hi"]
    if request.method == "POST":
        for key in keys:
            set_setting(key, (request.form.get(key) or "").strip(), admin_id=current_user.id)
        db.session.commit()
        log_admin_action(current_user, "settings_updated", "settings", "payment")
        db.session.commit()
        flash("Payment settings saved.", "success")
        return redirect(url_for("admin.settings_payment"))
    settings = load_all_settings()
    return render_template("admin/settings_payment.html", settings=settings, keys=keys)


# --------------------------------------------------------------------------
# Google Drive settings
# --------------------------------------------------------------------------

@admin_bp.route("/settings/drive", methods=["GET", "POST"])
@login_required
def settings_drive():
    from ..storage.gdrive import GoogleDriveStorage
    from ..utils.drive_settings import is_drive_connected, clear_credentials

    if request.method == "POST":
        action = request.form.get("action")
        if action == "start_connect":
            if not current_app.config["GOOGLE_CLIENT_SECRETS_FILE"]:
                flash("GOOGLE_CLIENT_SECRETS_FILE is not configured on the server.", "danger")
                return redirect(url_for("admin.settings_drive"))
            try:
                storage = GoogleDriveStorage()
                flow = storage.build_oauth_flow(url_for("admin.drive_callback", _external=True))
                auth_url, state = flow.authorization_url(access_type="offline",
                                                         include_granted_scopes="true",
                                                         prompt="consent")
                session["drive_oauth_state"] = state
                session["drive_oauth_code_verifier"] = flow.code_verifier
                return redirect(auth_url)
            except Exception as exc:
                flash(f"Could not start Google OAuth: {exc}", "danger")
                return redirect(url_for("admin.settings_drive"))
        if action == "disconnect":
            clear_credentials()
            log_admin_action(current_user, "drive_disconnected", "settings", "drive")
            db.session.commit()
            flash("Google Drive disconnected.", "info")
            return redirect(url_for("admin.settings_drive"))
        if action == "test":
            storage = GoogleDriveStorage()
            result = storage.test_connection()
            (flash("Drive OK: " + result["detail"], "success") if result["ok"]
             else flash("Drive problem: " + result["detail"], "danger"))
            return redirect(url_for("admin.settings_drive"))
        if action == "retry_uploads":
            from ..storage.documents import retry_pending_uploads
            ok, pending = retry_pending_uploads()
            flash(f"Retry complete: {ok} uploaded, {pending} still pending.", "info")
            return redirect(url_for("admin.settings_drive"))

    connected = is_drive_connected()
    from ..storage.documents import retry_pending_uploads as _r  # noqa
    pending_count = 0
    from ..models import UploadedDocument
    pending_count = UploadedDocument.query.filter_by(upload_status="pending").count()
    return render_template("admin/settings_drive.html", connected=connected,
                           pending_count=pending_count,
                           provider=current_app.config["STORAGE_PROVIDER"])


@admin_bp.route("/settings/drive/callback")
@login_required
def drive_callback():
    from ..storage.gdrive import GoogleDriveStorage

    state = request.args.get("state")
    if state != session.get("drive_oauth_state"):
        flash("OAuth state mismatch - connection aborted.", "danger")
        return redirect(url_for("admin.settings_drive"))
    try:
        storage = GoogleDriveStorage()
        flow = storage.build_oauth_flow(url_for("admin.drive_callback", _external=True))
        flow.code_verifier = session.pop("drive_oauth_code_verifier", None)
        flow.fetch_token(code=request.args.get("code"))
        creds = flow.credentials
        from ..utils.drive_settings import save_credentials
        save_credentials(creds_to_dict(creds))
        log_admin_action(current_user, "drive_connected", "settings", "drive")
        db.session.commit()
        flash("Google Drive connected successfully. Documents will now be stored in your Drive.",
              "success")
    except Exception as exc:
        current_app.logger.warning("Drive OAuth failed: %s", type(exc).__name__)
        flash(f"Google Drive connection failed: {exc}", "danger")
    session.pop("drive_oauth_state", None)
    session.pop("drive_oauth_code_verifier", None)
    return redirect(url_for("admin.settings_drive"))


def creds_to_dict(creds):
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    return data


# --------------------------------------------------------------------------
# Notification settings (templates + provider status)
# --------------------------------------------------------------------------

@admin_bp.route("/notifications")
@login_required
def notifications_list():
    page = request.args.get("page", 1, type=int)
    pagination = db.paginate(db.select(Notification).order_by(Notification.created_at.desc()),
                             page=page, per_page=30, error_out=False)
    return render_template("admin/notifications_list.html", pagination=pagination)


@admin_bp.route("/settings/notifications", methods=["GET", "POST"])
@login_required
def settings_notifications():
    keys = ["ntf_order_submitted_en", "ntf_order_submitted_hi",
            "ntf_payment_verified_en", "ntf_payment_verified_hi",
            "ntf_payment_rejected_en", "ntf_payment_rejected_hi",
            "ntf_documents_required_en", "ntf_documents_required_hi",
            "ntf_application_completed_en", "ntf_application_completed_hi"]
    if request.method == "POST":
        for key in keys:
            set_setting(key, (request.form.get(key) or "").strip(), admin_id=current_user.id)
        db.session.commit()
        log_admin_action(current_user, "settings_updated", "settings", "notifications")
        db.session.commit()
        flash("Notification templates saved.", "success")
        return redirect(url_for("admin.settings_notifications"))
    settings = load_all_settings()
    providers = {
        "whatsapp": bool(current_app.config.get("WHATSAPP_PROVIDER_URL")),
        "sms": bool(current_app.config.get("SMS_PROVIDER_URL")),
        "email": bool(current_app.config.get("SMTP_HOST")),
    }
    return render_template("admin/settings_notifications.html", settings=settings,
                           keys=keys, providers=providers)


# --------------------------------------------------------------------------
# Customers (no accounts - derived from orders)
# --------------------------------------------------------------------------

@admin_bp.route("/customers")
@login_required
def customers_list():
    q = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    query = Customer.query
    if q:
        like = f"%{q}%"
        query = query.filter(Customer.name.ilike(like) | Customer.mobile.ilike(like))
    pagination = query.order_by(Customer.updated_at.desc()).paginate(
        page=page, per_page=30, error_out=False)
    return render_template("admin/customers_list.html", pagination=pagination, q=q)


# --------------------------------------------------------------------------
# Staff management (future-ready)
# --------------------------------------------------------------------------

@admin_bp.route("/staff")
@login_required
def staff_list():
    admins = AdminUser.query.order_by(AdminUser.created_at).all()
    return render_template("admin/staff.html", admins=admins)


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------

@admin_bp.route("/profile")
@login_required
def profile():
    return render_template("admin/profile.html")
