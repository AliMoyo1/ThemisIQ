"""Input sanitization utilities for request data.

All user-supplied strings entering through JSON bodies or form fields pass
through these functions before being used in business logic or stored.
"""

import re
import unicodedata
from typing import Any

_CTRL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_HTML_TAG = re.compile(r'<[^>]+>')

# Field names whose values may contain intentional HTML or markdown and should
# not have HTML tags stripped.
_RICH_TEXT_KEYS: frozenset[str] = frozenset({
    "content", "body", "policy_content", "plan_content",
    "description_html", "notes_html", "html_content",
})

_DEFAULT_MAX_LEN = 50_000


def clean(s: Any, max_len: int | None = None) -> Any:
    """Strip control characters, normalize unicode, strip surrounding whitespace.

    Non-string values are returned unchanged.
    """
    if not isinstance(s, str):
        return s
    s = _CTRL.sub("", s)
    s = unicodedata.normalize("NFC", s)
    s = s.strip()
    if max_len is not None:
        s = s[:max_len]
    return s


def strip_tags(s: Any) -> Any:
    """Remove HTML tags from a string. Non-strings returned unchanged."""
    if not isinstance(s, str):
        return s
    return _HTML_TAG.sub("", s).strip()


def sanitize_str(s: Any, max_len: int | None = None, allow_html: bool = False) -> Any:
    """Clean a single user-supplied string field.

    Applies: control-char removal, unicode normalization, whitespace trim,
    HTML tag stripping (unless allow_html=True), length cap.
    """
    if not isinstance(s, str):
        return s
    s = clean(s, max_len)
    if not allow_html:
        s = strip_tags(s)
    return s


def sanitize_dict(d: Any, max_len: int = _DEFAULT_MAX_LEN) -> Any:
    """Recursively sanitize all string values in a JSON-decoded request body.

    Keys in _RICH_TEXT_KEYS have HTML stripping skipped so markdown/HTML
    content fields are preserved.
    """
    if isinstance(d, dict):
        return {
            k: sanitize_dict(v, max_len) if isinstance(v, (dict, list))
            else sanitize_str(v, max_len=max_len, allow_html=(k in _RICH_TEXT_KEYS))
            for k, v in d.items()
        }
    if isinstance(d, list):
        return [
            sanitize_dict(item, max_len) if isinstance(item, (dict, list))
            else sanitize_str(item, max_len=max_len)
            for item in d
        ]
    return d
