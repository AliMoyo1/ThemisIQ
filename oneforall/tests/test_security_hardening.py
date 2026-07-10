"""Tests for ThemisIQ security-hardening features (PLAN-01 / PLAN-18).

Run from the app root (oneforall/):
    python -m pytest tests/test_security_hardening.py -q

The multi-tenant audit-log isolation (PLAN-01) is verified directly against
the data-service layer that backs every audit-log read path. The MFA policy
API and the Security Settings UI are covered by the live end-to-end run
(see session notes): invalid input returns 400, valid input persists.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import modules.sentinel.data_service as ds


def _seed():
    """Build an isolated in-memory DB with two orgs + cross-org audit rows.

    The app's data layer uses `%s` placeholders (Postgres style); the real
    database.get_db() wrapper translates them for SQLite. We replicate that
    minimal translation so we exercise the actual list_audit() code path.
    """
    import sqlite3

    class _Conn:
        def __init__(self):
            self._c = sqlite3.connect(":memory:")
            self._c.row_factory = sqlite3.Row

        def execute(self, sql, params=()):
            sql = sql.replace("%s", "?")
            return self._c.execute(sql, params)

        def close(self):
            self._c.close()

    con = _Conn()
    con.execute(
        """
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY, user_id INTEGER, username TEXT,
            module TEXT, action TEXT, org_id INTEGER, created_at TEXT
        )
        """
    )
    con.execute(
        "INSERT INTO audit_log (id, user_id, username, module, action, org_id, created_at) "
        "VALUES (1, 2, 'compliance', 'sentinel', 'did X (org A)', 1, '2026-07-10 10:00:00')"
    )
    con.execute(
        "INSERT INTO audit_log (id, user_id, username, module, action, org_id, created_at) "
        "VALUES (2, 3, 'bob', 'sentinel', 'did Y (org B)', 2, '2026-07-10 11:00:00')"
    )
    return con


def test_audit_isolation_list_audit_scoped_org1():
    """list_audit(org_id=1) must return ONLY org-1 rows (no cross-tenant leak)."""
    con = _seed()
    ds.get_db = lambda: con  # type: ignore[assignment]
    try:
        rows = ds.list_audit(limit=50, org_id=1)
        assert rows, "expected at least one org-1 row"
        assert all(r["org_id"] == 1 for r in rows), "leaked cross-tenant audit rows"
        assert "did X (org A)" in [r["action"] for r in rows]
        assert "did Y (org B)" not in [r["action"] for r in rows]
    finally:
        ds.get_db = getattr(ds, "_orig_get_db", ds.get_db)


def test_audit_isolation_list_audit_scoped_org2():
    con = _seed()
    ds.get_db = lambda: con  # type: ignore[assignment]
    try:
        rows = ds.list_audit(limit=50, org_id=2)
        assert all(r["org_id"] == 2 for r in rows)
        assert "did Y (org B)" in [r["action"] for r in rows]
        assert "did X (org A)" not in [r["action"] for r in rows]
    finally:
        ds.get_db = getattr(ds, "_orig_get_db", ds.get_db)


def test_audit_unscoped_returns_all():
    """Without org_id, the helper returns every row (used only for true super-admins)."""
    con = _seed()
    ds.get_db = lambda: con  # type: ignore[assignment]
    try:
        rows = ds.list_audit(limit=50)
        assert len(rows) == 2
    finally:
        ds.get_db = getattr(ds, "_orig_get_db", ds.get_db)
