"""A unit-limited integration may read shared risks but may only edit its unit."""

import sqlite3

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from database import _SqliteConnWrapper
from modules.launcher import routes_api_v1


def _invoke(coroutine):
    """The route has no await; drive it without a Windows event-loop socket."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("Risk route unexpectedly suspended")


def test_unit_limited_key_cannot_edit_shared_or_other_unit_risk(tmp_path, monkeypatch):
    path = tmp_path / "integration_scope.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE risk_register (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                likelihood INTEGER DEFAULT 3, impact INTEGER DEFAULT 3,
                business_unit_id INTEGER, updated_at TEXT
            );
            CREATE TABLE audit_log (
                user_id INTEGER, username TEXT, module TEXT, action TEXT,
                entity_type TEXT, entity_id INTEGER, details TEXT,
                ip_address TEXT, org_id INTEGER
            );
            INSERT INTO risk_register (id, title, business_unit_id)
                VALUES (1, 'Shared risk', NULL),
                       (2, 'Other unit risk', 22),
                       (3, 'Own unit risk', 11);
        """)

    def open_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return _SqliteConnWrapper(conn)

    monkeypatch.setattr(routes_api_v1, "get_db", open_db)
    request = Request({"type": "http", "method": "PATCH", "path": "/api/v1/risks",
                       "headers": [], "client": ("127.0.0.1", 1234)})
    key = {"id": 1, "org_id": 1, "business_unit_id": 11}

    for risk_id, original in ((1, "Shared risk"), (2, "Other unit risk")):
        with pytest.raises(HTTPException) as error:
            _invoke(routes_api_v1.update_risk(
                request, risk_id, routes_api_v1.RiskUpdate(title="Changed"), key=key,
            ))
        assert error.value.status_code == 404
        with open_db() as db:
            assert db.execute(
                "SELECT title FROM risk_register WHERE id=%s", (risk_id,)
            ).fetchone()["title"] == original

    result = _invoke(routes_api_v1.update_risk(
        request, 3, routes_api_v1.RiskUpdate(title="Changed"), key=key,
    ))
    assert result["success"] is True
    with open_db() as db:
        assert db.execute(
            "SELECT title FROM risk_register WHERE id=3"
        ).fetchone()["title"] == "Changed"
        assert db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1

    unrestricted = {**key, "business_unit_id": None}
    result = _invoke(routes_api_v1.update_risk(
        request, 1, routes_api_v1.RiskUpdate(title="Shared changed"), key=unrestricted,
    ))
    assert result["success"] is True
    with open_db() as db:
        assert db.execute(
            "SELECT title FROM risk_register WHERE id=1"
        ).fetchone()["title"] == "Shared changed"
        assert db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 2
