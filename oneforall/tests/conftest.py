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
# Clear DATABASE_URL so tests always run in SQLite mode regardless of the
# host environment (on the VPS DATABASE_URL is set, which would otherwise
# bypass the _DB_PATH monkeypatch and hit the live PostgreSQL database).
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ["DATABASE_URL"] = ""

# Make `oneforall/` importable when pytest is run from the repo root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

# Pre-import modules whose top level does `from database import get_db`
# (a frozen name binding, not a live attribute lookup) BEFORE any test's
# fixture gets a chance to monkeypatch `database.get_db`. Some modules are
# only ever imported lazily, function-local, from inside another module
# (e.g. core/advisor.py imports modules.erm.data_service inside a
# function body). If that lazy import happens to fire for the first time
# while a fixture elsewhere has temporarily replaced database.get_db with
# a stub connection (e.g. test_advisor.py's `db` fixture), the importing
# module's `get_db` name freezes onto that stub for the rest of the
# process -- Python only executes a module's top-level code once, so a
# later restore of `database.get_db` does not fix an already-bound name
# in a different module. Importing here, at collection time, guarantees
# these modules bind to the real get_db before any test can interfere.
import modules.erm.data_service  # noqa: F401
import modules.governance.data_service  # noqa: F401


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
