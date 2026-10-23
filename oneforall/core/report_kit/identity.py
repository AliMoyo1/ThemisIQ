"""
Who, what and when for a report, and the small helpers that keep a generated file safe.

Pure functions, no request and no database, so every renderer and every adapter can use them and a test can call them
directly.
"""
import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from core.report_kit import theme

# The module names as the platform navigation shows them (templates/base_shell.html), keyed by the module code the
# routes use. A report names the module it was generated from with these words, never with a code name.
MODULE_NAV = {
    "platform": "Command Centre",
    "aria": "Governance",
    "grid": "Audit",
    "bcm": "Resilience",
    "sentinel": "Privacy",
    "erm": "Enterprise Risk",
    "orm": "Operations Risk",
    "ai-governance": "AI Governance",
    "ai_governance": "AI Governance",
    "evidence": "Evidence Vault",
    "evidence_campaigns": "Evidence Campaigns",
    "readiness": "Data Readiness",
    "governance": "Governance Settings",
}


def module_name(key, section=None) -> str:
    """The navigation name for a module code; `section` adds a page inside it ("Command Centre, Reports")."""
    name = MODULE_NAV.get(str(key or "").strip().lower(), str(key or "ThemisIQ"))
    return f"{name}, {section}" if section else name


# ── Time ────────────────────────────────────────────────────────────────────

def to_utc(value):
    """A naive UTC datetime from what the application stores (naive datetime, ISO text, a date) or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def format_when(value) -> str:
    """`21 Oct 2026, 16:05 UTC (18:05 CAT)`; the local date joins the local time only when it is another day."""
    utc = to_utc(value)
    if utc is None:
        return "Not recorded"
    local = utc.replace(tzinfo=timezone.utc).astimezone(theme.DISPLAY_ZONE)
    day = f"{utc.day} {utc.strftime('%b %Y')}"
    near = f"{local.strftime('%H:%M')} {theme.DISPLAY_ZONE_NAME}"
    if local.date() != utc.date():
        near = f"{local.day} {local.strftime('%b')} {near}"
    return f"{day}, {utc.strftime('%H:%M')} UTC ({near})"


def format_day(value) -> str:
    """`21 Oct 2026` for a stored date or datetime, or an empty string."""
    utc = to_utc(value)
    return f"{utc.day} {utc.strftime('%b %Y')}" if utc else ""


# ── Numbers ─────────────────────────────────────────────────────────────────

def pct(part, total, digits=0):
    """A percentage rounded half up (12.5 gives 13, as a person and as the page script round it), or None when there is
    nothing to take a share of. Python's round() takes 12.5 to 12, so a report built on it disagrees with the screen."""
    if part is None or not total:
        return None
    value = (Decimal(part) * 100 / Decimal(total)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return int(value) if digits == 0 else float(value)


def fmt_int(value) -> str:
    """A whole number with thousands separators, or `n/a` when there is no figure (never a zero for a missing one)."""
    if value is None or value == "":
        return "n/a"
    try:
        return f"{int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP)):,}"
    except (TypeError, ValueError, ArithmeticError):
        return str(value)


def _half_up(value, digits):
    """`value` as a Decimal rounded half up to `digits` places, or None when it is not a finite number."""
    try:
        number = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    return number.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP) if number.is_finite() else None


def fmt_number(value, digits=1) -> str:
    """A number with thousands separators and `digits` decimals, rounded half up (11.25 is 11.3; format() says 11.2)."""
    if value is None or value == "":
        return "n/a"
    rounded = _half_up(value, digits)
    if rounded is None:
        return "n/a" if str(value).strip().lower() in ("nan", "inf", "-inf") else str(value)
    return f"{rounded:,.{digits}f}"


def plural(count, singular, plural_form=None) -> str:
    """`1 risk`, `3 risks`, `0 risks`: the number and the noun in agreement."""
    noun = singular if count == 1 else (plural_form or singular + "s")
    return f"{fmt_int(count)} {noun}"


def fmt_pct(value, digits=0) -> str:
    if value is None or value == "":
        return "n/a"
    rounded = _half_up(value, digits)
    return str(value) if rounded is None else f"{rounded:.{digits}f}%"


# ── Text ────────────────────────────────────────────────────────────────────

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TAGS = re.compile(r"<[^>]+>")


def clean_text(value, keep_newlines=True) -> str:
    """Text for a document: no markup, no control characters, no leading or trailing blanks."""
    if value is None:
        return ""
    text = _CONTROL.sub("", _TAGS.sub("", str(value)))
    if not keep_newlines:
        text = re.sub(r"\s+", " ", text)
    return text.strip()


_CP1252_EXTRA = {"‑": "-", "−": "-", " ": " ", " ": " ", " ": " ", "​": "",
                 "→": "to", "≤": "<=", "≥": ">=", "✓": "yes", "✗": "no"}


def pdf_text(value) -> str:
    """Text the built in PDF fonts can draw. Characters outside Windows 1252 would print as black squares, so they are
    folded to their nearest plain letter (a with a macron becomes a) and anything with no plain form becomes `?`."""
    text = clean_text(value)
    out = []
    for char in text:
        if char in _CP1252_EXTRA:
            out.append(_CP1252_EXTRA[char])
            continue
        try:
            char.encode("cp1252")
            out.append(char)
            continue
        except UnicodeEncodeError:
            pass
        folded = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode("ascii")
        out.append(folded or "?")
    return "".join(out)


def markup_safe(value) -> str:
    """Escape for reportlab Paragraph markup after folding to drawable characters."""
    return pdf_text(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def ellipsize(value, limit) -> str:
    """Cut at `limit` characters on a word edge when there is one, and say so with an ellipsis."""
    text = clean_text(value, keep_newlines=False)
    if len(text) <= limit:
        return text
    cut = text[: max(limit - 1, 1)]
    if " " in cut[limit // 2:]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:.") + "…"


# ── Links ───────────────────────────────────────────────────────────────────

_LINK_UNSAFE = re.compile(r"[\s\x00-\x1f\x7f\"'<>\\`{}|^]")


def safe_link(url) -> str:
    """The URL when a document may draw it as a link, else an empty string. Only an absolute https address (http for localhost
    only) qualifies: ASCII, with a host, no credentials and no character that could end an attribute or a markup tag. A relative
    path, `javascript:` and `data:` can never become a link, so a record's address read from a table row is safe to print."""
    text = str(url or "").strip()
    if not text or len(text) > 2000 or not text.isascii() or _LINK_UNSAFE.search(text):
        return ""
    try:
        parts = urlsplit(text)
        host = parts.hostname
        parts.port      # a malformed port raises
    except ValueError:
        return ""
    scheme = parts.scheme.lower()
    if not host or parts.username is not None or parts.password is not None:
        return ""
    if scheme != "https" and not (scheme == "http" and host in ("localhost", "127.0.0.1")):
        return ""
    return text


# ── Files ───────────────────────────────────────────────────────────────────

_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(stem, extension, *, when=None, limit=80) -> str:
    """An ASCII only file name: letters, digits, dot, dash, underscore. A name with quotes, line breaks, slashes or
    non Latin characters can neither break the download header nor name a path."""
    folded = unicodedata.normalize("NFKD", str(stem or "report")).encode("ascii", "ignore").decode("ascii")
    base = _FILENAME_UNSAFE.sub("_", folded).strip("._-")[:limit] or "report"
    if when is not None:
        stamp = to_utc(when)
        if stamp:
            base = f"{base}_{stamp.strftime('%Y%m%d_%H%M')}"
    extension = re.sub(r"[^a-z0-9]", "", str(extension).lower())
    return f"{base}.{extension}" if extension else base


def download_headers(filename, *, private=True) -> dict:
    """The headers for downloading one file. The name is cleaned again here, so a caller that built it by hand still
    cannot put a quote, a line break or a path into the `Content-Disposition` header."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", str(filename or "")):
        stem, _, extension = str(filename or "report").rpartition(".")
        filename = safe_filename(stem or extension, extension if stem else "")
    return {"Content-Disposition": f'attachment; filename="{filename}"', "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store" if private else "no-cache"}


# ── Cells ───────────────────────────────────────────────────────────────────

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n")
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?%?")


def csv_cell(value):
    """A CSV cell a spreadsheet will read as text: a string that starts like a formula gets a leading apostrophe. A
    plain number, even one written with a sign, is left as it is. Non strings pass through unchanged."""
    if isinstance(value, str) and value[:1] in _FORMULA_START and not _NUMBER.fullmatch(value.strip()):
        return "'" + value
    return value


def csv_row(values) -> list:
    """One CSV row with every string cell made safe for a spreadsheet (`csv_cell`)."""
    return [csv_cell(v) for v in values]


def set_cell(cell, value):
    """Write a value to an openpyxl cell. A string is stored as a string whatever it starts with, so a title that begins
    with an equals sign is shown as text and is never evaluated as a formula."""
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"
    return cell
