"""
Input sanitization, validation, and IDOR protection utilities.
"""
import re
import html

_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s+")


def sanitize_text(value, max_length: int = 5000) -> str:
    """Strip HTML tags, collapse whitespace, enforce length limit."""
    if not value or not isinstance(value, str):
        return ""
    value = html.unescape(value)
    value = _TAG_RE.sub("", value)
    value = _MULTI_SPACE_RE.sub(" ", value).strip()
    return value[:max_length]


def sanitize_short(value, max_length: int = 255) -> str:
    """Sanitize a short text field (title, name, etc.)."""
    return sanitize_text(value, max_length)


def validate_int(value, default=None, min_val=None, max_val=None):
    """Safely coerce a value to int with bounds."""
    if value is None:
        return default
    try:
        v = int(value)
    except (ValueError, TypeError):
        return default
    if min_val is not None and v < min_val:
        return default
    if max_val is not None and v > max_val:
        return default
    return v


def validate_choice(value, allowed: set, default=None):
    """Ensure value is one of the allowed choices."""
    if value in allowed:
        return value
    return default


_SAFE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")


def validate_date(value) -> str:
    """Validate ISO date or datetime format. Returns empty string if invalid."""
    if not value or not isinstance(value, str):
        return ""
    value = value.strip()
    if _SAFE_DATE_RE.match(value):
        return value
    return ""


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(value) -> str:
    """Basic email format validation."""
    if not value or not isinstance(value, str):
        return ""
    value = value.strip().lower()
    if len(value) > 320:
        return ""
    if _EMAIL_RE.match(value):
        return value
    return ""


def check_ownership(db, table: str, record_id, user_id, owner_col: str = "created_by") -> bool:
    """Verify that a record belongs to a user. Returns True if owned or if admin check is bypassed."""
    row = db.execute(
        f"SELECT {owner_col} FROM {table} WHERE id = %s", (record_id,)
    ).fetchone()
    if not row:
        return False
    return row[owner_col] == user_id
