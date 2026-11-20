"""Display formatting helpers: Indian rupee amounts, IST datetimes, dates."""
from datetime import datetime, date, timezone, timedelta

from ..config import Config

IST = timezone(timedelta(hours=5, minutes=30))


def inr(value) -> str:
    """Format a number as Indian currency: ₹1,23,456.75 (lakh/crore grouping)."""
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    negative = amount < 0
    amount = abs(round(amount, 2))
    whole = int(amount)
    paise = round(amount - whole, 2)
    s = str(whole)
    if len(s) > 3:
        last3 = s[-3:]
        rest = s[:-3]
        parts = []
        while len(rest) > 2:
            parts.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            parts.insert(0, rest)
        s = ",".join(parts) + "," + last3
    frac = f".{int(paise * 100):02d}"
    prefix = "-" if negative else ""
    return f"{prefix}\u20B9{s}{frac}"


def to_ist(dt: datetime | date | None):
    if dt is None:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt  # plain calendar date: no timezone conversion needed
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def fmt_dt(dt: datetime | None) -> str:
    local = to_ist(dt)
    if local is None:
        return "-"
    return local.strftime("%d %b %Y, %I:%M %p")


def fmt_date(dt: datetime | date | None) -> str:
    local = to_ist(dt)
    if local is None:
        return "-"
    return local.strftime("%d %b %Y")
