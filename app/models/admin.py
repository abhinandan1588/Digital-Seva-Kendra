"""Admin user model. Customers never have accounts - only admins do."""
from datetime import datetime, timedelta, timezone

from flask_login import UserMixin
from sqlalchemy import String, Boolean, DateTime, Integer
from werkzeug.security import generate_password_hash, check_password_hash

from ..extensions import db, login_manager


def utcnow():
    return datetime.now(timezone.utc)


def _as_utc(dt):
    """DB-loaded datetimes come back naive on SQLite; treat them as UTC so
    comparisons with utcnow() behave identically on SQLite (dev) and
    PostgreSQL (production)."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


class AdminUser(UserMixin, db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, default="Admin")
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="owner")  # owner | staff (future)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True), nullable=True)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    MAX_FAILED_LOGINS = 5
    LOCK_MINUTES = 15

    def set_password(self, password: str) -> None:
        """Werkzeug scrypt hash - plain-text passwords are never stored."""
        self.password_hash = generate_password_hash(password, method="scrypt")

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def register_failed_login(self) -> None:
        self.failed_login_count = (self.failed_login_count or 0) + 1
        if self.failed_login_count >= self.MAX_FAILED_LOGINS:
            self.locked_until = utcnow() + timedelta(minutes=self.LOCK_MINUTES)
            self.failed_login_count = 0

    def register_successful_login(self) -> None:
        self.failed_login_count = 0
        self.locked_until = None
        self.last_login_at = utcnow()

    @property
    def is_locked(self) -> bool:
        locked_until = _as_utc(self.locked_until)
        if not locked_until:
            return False
        return locked_until > utcnow()

    # Flask-Login
    @property
    def is_active_property(self):
        return self.is_active

    def __repr__(self):  # pragma: no cover
        return f"<AdminUser {self.email}>"


@login_manager.user_loader
def load_admin_user(user_id: str):
    return db.session.get(AdminUser, int(user_id))
