"""Substring search that matches the same rows on SQLite and PostgreSQL.

Plain LIKE ignores ASCII case on SQLite but is case sensitive on PostgreSQL, and the
user's own %, _ and escape characters act as wildcards on both. Build the predicate
with ci_like() and bind like_pattern(term) to each of its placeholders.
"""
import re

MAX_SEARCH_CHARS = 200
_ESC = "!"
_COLUMN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?")


def like_pattern(term: str) -> str:
    """Substring LIKE pattern with the user's own %, _ and escape characters made literal."""
    term = term.strip()[:MAX_SEARCH_CHARS]
    term = term.replace(_ESC, _ESC + _ESC).replace("%", _ESC + "%").replace("_", _ESC + "_")
    return f"%{term}%"


def ci_like(column: str) -> str:
    """Case-insensitive LIKE predicate for one trusted column name. Bind like_pattern(term) to its %s."""
    if not _COLUMN.fullmatch(column):
        raise ValueError("column must be a plain SQL identifier")
    return f"LOWER({column}) LIKE LOWER(%s) ESCAPE '{_ESC}'"
