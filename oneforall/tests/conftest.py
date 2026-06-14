"""
Shared test fixtures.

Each test gets a fresh SQLite database in a tmp_path. We monkey-patch
`database._DB_PATH` rather than going through env vars so we don't pollute
the developer's real DB on test failure.
"""
import os
import sys

# Pre-set env vars BEFORE any project module loads `config`. Without this,
# config.py raises in non-DEBUG mode because SECRET_KEY is unset.
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only")

# Make `oneforall/` importable when pytest is run from the repo root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Fresh, fully-migrated SQLite DB per test. Yields a get_db() connection."""
    import database
    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    conn = database.get_db()
    try:
        yield conn
    finally:
        conn.close()
