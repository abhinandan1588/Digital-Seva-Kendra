"""Admin authentication blueprint: login, logout, change password.

Customers never authenticate; only /admin is protected. Rate limiting and
account locking protect the login endpoint. CSRF is enforced by CSRFProtect.
"""
from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, current_app)
from flask_login import login_user, logout_user, login_required, current_user

from ..extensions import db, limiter
from ..models import AdminUser
from ..utils.audit import log_admin_action

auth_bp = Blueprint("auth", __name__, url_prefix="/admin")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = AdminUser.query.filter_by(email=email).first()

        if user is None or not user.is_active:
            # Same generic message either way: no account enumeration.
            flash("Invalid email or password.", "danger")
            return render_template("admin/login.html"), 401
        if user.is_locked:
            flash("Account temporarily locked. Try again later.", "danger")
            return render_template("admin/login.html"), 423
        if not user.check_password(password):
            user.register_failed_login()
            db.session.commit()
            flash("Invalid email or password.", "danger")
            return render_template("admin/login.html"), 401

        user.register_successful_login()
        db.session.commit()
        login_user(user, remember=False)  # no long-lived cookies for admins
        log_admin_action(user, "login")
        db.session.commit()
        flash("Welcome back!", "success")
        return redirect(request.args.get("next") or url_for("admin.dashboard"))

    return render_template("admin/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log_admin_action(current_user, "logout")
    db.session.commit()
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password") or ""
        new_password = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        if not current_user.check_password(current_password):
            flash("Current password is incorrect.", "danger")
        elif new_password != confirm:
            flash("New passwords do not match.", "danger")
        elif len(new_password) < 8:
            flash("New password must be at least 8 characters.", "danger")
        else:
            current_user.set_password(new_password)
            log_admin_action(current_user, "password_changed")
            db.session.commit()
            flash("Password changed successfully.", "success")
            return redirect(url_for("admin.profile"))
    return render_template("admin/change_password.html")
