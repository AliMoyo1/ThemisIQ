"""Tests for PLAN-13: Regulatory Inbox + compliance drift detection.

Run from the app root (oneforall/):
    python -m pytest tests/test_regulatory_drift.py -q
"""
from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import database as db_mod


class _NoCloseWrapper(db_mod._SqliteConnWrapper):
    """SQLite wrapper whose close() is a no-op so test connections stay alive."""
    def close(self):
        pass


@pytest.fixture
def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    wrapped = _NoCloseWrapper(conn)

    orig = db_mod.get_db
    db_mod.get_db = lambda **kw: wrapped
    db_mod.init_db()
    conn.execute("PRAGMA foreign_keys = OFF")
    yield wrapped
    db_mod.get_db = orig
    conn.close()


@pytest.fixture(autouse=True)
def _restore_ds_get_db(test_db):
    import modules.governance.data_service as ds
    orig = ds.get_db
    ds.get_db = lambda **kw: test_db
    yield
    ds.get_db = orig


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fw_id(test_db, name="ISO 27001:2022"):
    row = test_db.execute(
        "SELECT id FROM frameworks WHERE name=%s", (name,)
    ).fetchone()
    if row:
        return row["id"]
    test_db.execute(
        "INSERT INTO frameworks (name, description, color, is_active) "
        "VALUES (%s,'Test','#000000',1)",
        (name,),
    )
    test_db.commit()
    return test_db.execute(
        "SELECT id FROM frameworks WHERE name=%s", (name,)
    ).fetchone()["id"]


def _insert_control(test_db, fw_id, ref="A.5.1"):
    test_db.execute(
        "INSERT OR IGNORE INTO controls (framework_id, ref, name) "
        "VALUES (%s, %s, 'Test Control')",
        (fw_id, ref),
    )
    test_db.commit()


def _insert_update(test_db, fw_name, title, refs="", severity="info", status="open"):
    test_db.execute(
        "INSERT INTO regulatory_updates "
        "(framework_name, title, affected_refs, severity, status) "
        "VALUES (%s, %s, %s, %s, %s)",
        (fw_name, title, refs or None, severity, status),
    )
    test_db.commit()
    return test_db.execute(
        "SELECT id FROM regulatory_updates WHERE title=%s", (title,)
    ).fetchone()["id"]


def _count_tasks(test_db, uid):
    return test_db.execute(
        "SELECT COUNT(*) FROM task_board "
        "WHERE entity_type='regulatory_update' AND entity_id=%s",
        (uid,),
    ).fetchone()[0]


def _cleanup(test_db, uid):
    test_db.execute(
        "DELETE FROM task_board WHERE entity_type='regulatory_update' AND entity_id=%s",
        (uid,),
    )
    test_db.execute("DELETE FROM regulatory_updates WHERE id=%s", (uid,))
    test_db.commit()


# ── Test 1: framework + control match creates one task ────────────────────────

def test_drift_match_creates_task(test_db):
    from modules.governance.data_service import run_drift_check

    fw_id = _fw_id(test_db)
    _insert_control(test_db, fw_id, "A.5.1")
    uid = _insert_update(test_db, "ISO 27001:2022", "Test ISO Amendment", refs="A.5.1")

    res = run_drift_check(test_db, update_id=uid)

    assert res["tasks"] == 1
    assert res["updates"] == 1
    assert _count_tasks(test_db, uid) == 1

    upd = test_db.execute(
        "SELECT * FROM regulatory_updates WHERE id=%s", (uid,)
    ).fetchone()
    assert upd["status"] == "processed"
    assert upd["matched_count"] == 1

    _cleanup(test_db, uid)


# ── Test 2: second run creates no duplicate tasks ─────────────────────────────

def test_drift_idempotent(test_db):
    from modules.governance.data_service import run_drift_check

    fw_id = _fw_id(test_db)
    _insert_control(test_db, fw_id, "A.8.12")
    uid = _insert_update(test_db, "ISO 27001:2022", "Test ISO Amendment Idem", refs="A.8.12")

    run_drift_check(test_db, update_id=uid)

    test_db.execute(
        "UPDATE regulatory_updates SET status='open' WHERE id=%s", (uid,)
    )
    test_db.commit()

    res2 = run_drift_check(test_db, update_id=uid)

    assert res2["tasks"] == 0, "Second run must not duplicate tasks"
    assert _count_tasks(test_db, uid) == 1

    _cleanup(test_db, uid)


# ── Test 3: unmatched framework creates one generic task ──────────────────────

def test_drift_no_framework_match(test_db):
    from modules.governance.data_service import run_drift_check

    uid = _insert_update(test_db, "XYZZY Regulation 9999", "Bogus Framework Update")

    res = run_drift_check(test_db, update_id=uid)

    assert res["updates"] == 1
    assert _count_tasks(test_db, uid) == 1, "One generic task for unmatched framework"

    upd = test_db.execute(
        "SELECT * FROM regulatory_updates WHERE id=%s", (uid,)
    ).fetchone()
    assert upd["status"] == "processed"
    assert upd["matched_count"] == 0

    _cleanup(test_db, uid)


# ── Test 4: dismissed updates are never processed ─────────────────────────────

def test_drift_skips_dismissed(test_db):
    from modules.governance.data_service import run_drift_check

    uid = _insert_update(
        test_db, "ISO 27001:2022", "Dismissed Update", status="dismissed"
    )

    res = run_drift_check(test_db, update_id=uid)

    assert res["updates"] == 0
    assert res["tasks"] == 0
    assert _count_tasks(test_db, uid) == 0

    test_db.execute("DELETE FROM regulatory_updates WHERE id=%s", (uid,))
    test_db.commit()
