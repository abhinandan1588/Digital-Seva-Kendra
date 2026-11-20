"""Order/application numbering and secure tracking credentials."""
import hashlib
import secrets
from datetime import datetime, timezone

from sqlalchemy import text as sql_text

from ..extensions import db
from ..models import Counter


def _next_counter(key: str) -> int:
    """Atomic increment of a named counter row (row-locked on PostgreSQL).

    Works on both PostgreSQL (FOR UPDATE) and SQLite (single writer).
    """
    row = db.session.execute(
        sql_text("SELECT value FROM counters WHERE key = :k"),
        {"k": key},
    ).fetchone()
    if row is None:
        try:
            db.session.execute(
                sql_text("INSERT INTO counters (key, value) VALUES (:k, 1)"),
                {"k": key},
            )
            db.session.commit()
            return 1
        except Exception:
            db.session.rollback()
            row = db.session.execute(
                sql_text("SELECT value FROM counters WHERE key = :k"), {"k": key}
            ).fetchone()
            if row is None:
                raise
    # Row exists: lock + increment
    if db.engine.dialect.name == "postgresql":
        locked = db.session.execute(
            sql_text("SELECT value FROM counters WHERE key = :k FOR UPDATE"), {"k": key}
        ).fetchone()
        value = locked[0] + 1
        db.session.execute(sql_text("UPDATE counters SET value = :v WHERE key = :k"),
                           {"v": value, "k": key})
    else:
        value = row[0] + 1
        db.session.execute(sql_text("UPDATE counters SET value = :v WHERE key = :k"),
                           {"v": value, "k": key})
    return value


def generate_order_number() -> str:
    year = datetime.now(timezone.utc).year
    seq = _next_counter(f"order_{year}")
    return f"DSK-{year}-{seq:06d}"


def generate_application_number(order_number: str, sequence: int) -> str:
    return f"{order_number}-A{sequence}"


def generate_tracking_credentials() -> tuple[str, str, str, str]:
    """Return (token, pin, token_hash, pin_hash). Only hashes are stored.

    The token goes into the confirmation/receipt URL; the PIN is printed on
    the receipt so a customer can also track by typing both.
    """
    token = secrets.token_urlsafe(24)
    pin = f"{secrets.randbelow(900000) + 100000:06d}"
    return token, pin, hash_token(token), hash_token(pin)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_tracking(order_number: str, token: str, order) -> bool:
    """Constant-time-ish comparison via hash equality."""
    if order is None or order_number != order.order_number:
        return False
    provided = hash_token((token or "").strip())
    return secrets.compare_digest(provided, order.tracking_token_hash) or \
        secrets.compare_digest(provided, order.tracking_pin_hash)
