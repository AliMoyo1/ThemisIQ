"""
Centralised time helpers.

Why this exists: `datetime.utcnow()` is deprecated in Python 3.12 and removed
in 3.13. The replacement, `datetime.now(timezone.utc)`, returns a *timezone-
aware* datetime, but every datetime currently stored in the DB (via
`datetime('now')` and `datetime.fromisoformat(...)`) is naive UTC. Mixing them
would raise TypeError on comparisons across the codebase.

`utcnow()` therefore returns a *naive* UTC datetime — same semantics as the
deprecated call, but using the modern, non-deprecated API. A future migration
can flip this to aware once all stored datetimes carry timezone info.

This helper also exists so tests can monkey-patch a single call site for
deterministic time control.
"""
from datetime import datetime, date as _date, timezone
from typing import Optional


def utcnow() -> datetime:
    """Return the current UTC time as a *naive* datetime.

    Equivalent to the deprecated `datetime.utcnow()` but uses the modern API.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow_aware() -> datetime:
    """Return the current UTC time as a *timezone-aware* datetime.

    Use this in new code or when an aware datetime is explicitly needed.
    """
    return datetime.now(timezone.utc)


def to_dt(value) -> Optional[datetime]:
    """Engine-portable coercion to datetime.

    SQLite returns TEXT timestamps; psycopg2 returns datetime objects for
    TIMESTAMPTZ columns.  This function normalises both to a naive UTC datetime
    (or returns None for empty/NULL values) so call sites don't need to branch.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        # psycopg2 path: strip timezone info so arithmetic stays naive-UTC
        return value.replace(tzinfo=None)
    if isinstance(value, _date):
        # psycopg2 DATE column returns datetime.date — promote to midnight datetime
        return datetime(value.year, value.month, value.day)
    s = str(value).replace("Z", "+00:00").strip()
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=None)
    except ValueError:
        return datetime.strptime(s[:10], "%Y-%m-%d")


def to_iso(value) -> str:
    """Return an ISO-8601 string for display / JSON serialisation.

    Accepts TEXT strings (SQLite) or datetime objects (psycopg2 TIMESTAMPTZ).
    Returns "" for NULL / empty values so templates never see None.
    """
    dt = to_dt(value)
    return dt.isoformat(sep=" ", timespec="seconds") if dt else ""
