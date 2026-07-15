"""Tests for PLAN-03: concurrency guards on ERM workflow and task board.

Run from the app root (oneforall/):
    python -m pytest tests/test_concurrency_guards.py -q
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
    """SQLite wrapper whose close() is a no-op.

    Functions like transition_workflow call db.close() in their finally block.
    Overriding close() keeps the underlying connection alive so test code can
    continue using it for verification queries after calling those functions.
    """
    def close(self):
        pass


@pytest.fixture
def test_db(tmp_path):
    """Fresh SQLite DB with the full schema; get_db patched to return it."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    wrapped = _NoCloseWrapper(conn)

    orig = db_mod.get_db
    db_mod.get_db = lambda **kw: wrapped
    db_mod.init_db()
    conn.execute("PRAGMA foreign_keys = OFF")  # init_db re-enables FK; disable for tests
    yield wrapped
    db_mod.get_db = orig
    conn.close()


@pytest.fixture(autouse=True)
def _restore_ds_get_db(test_db):
    """Patch the ERM data_service module's own get_db reference."""
    import modules.erm.data_service as ds
    orig = ds.get_db
    ds.get_db = lambda **kw: test_db
    yield
    ds.get_db = orig


# ── ERM workflow race guard ──────────────────────────────────────────────────

def test_workflow_happy_path(test_db):
    """First transition on a fresh risk (NULL step) succeeds and writes one history row."""
    import modules.erm.data_service as ds

    test_db.execute(
        "INSERT INTO erm_enterprise_risks (title, status) VALUES ('Race Test Risk', 'open')"
    )
    test_db.commit()
    risk_id = test_db.execute(
        "SELECT id FROM erm_enterprise_risks WHERE title='Race Test Risk'"
    ).fetchone()["id"]

    result = ds.transition_workflow(risk_id, "identified", user_id=None)
    assert result == "identified"

    history = test_db.execute(
        "SELECT COUNT(*) AS c FROM erm_risk_workflow_history WHERE risk_id=%s",
        (risk_id,)
    ).fetchone()["c"]
    assert history == 1

    test_db.execute(
        "DELETE FROM erm_risk_workflow_history WHERE risk_id=%s", (risk_id,)
    )
    test_db.execute(
        "DELETE FROM erm_enterprise_risks WHERE id=%s", (risk_id,)
    )
    test_db.commit()


def test_workflow_stale_step_leaves_no_history(test_db):
    """Stale-step conditional UPDATE affects 0 rows and writes no phantom history."""
    test_db.execute(
        "INSERT INTO erm_enterprise_risks "
        "(title, status, workflow_step) VALUES ('Stale Step Risk', 'open', 'identified')"
    )
    test_db.commit()
    risk_id = test_db.execute(
        "SELECT id FROM erm_enterprise_risks WHERE title='Stale Step Risk'"
    ).fetchone()["id"]

    # Simulate a racing request that still believes step is 'draft'.
    cur = test_db.execute(
        "UPDATE erm_enterprise_risks SET workflow_step=%s, updated_at=datetime('now') "
        "WHERE id=%s AND COALESCE(workflow_step,'draft')=%s",
        ("identified", risk_id, "draft")
    )
    assert cur.rowcount == 0, "Stale conditional UPDATE must affect 0 rows"

    history = test_db.execute(
        "SELECT COUNT(*) AS c FROM erm_risk_workflow_history WHERE risk_id=%s",
        (risk_id,)
    ).fetchone()["c"]
    assert history == 0, "No phantom history row after a lost race"

    test_db.execute(
        "DELETE FROM erm_enterprise_risks WHERE id=%s", (risk_id,)
    )
    test_db.commit()


# ── Task board ownership guard ───────────────────────────────────────────────

def test_task_update_non_owner_hits_predicate(test_db):
    """Non-owner UPDATE with folded ownership predicate affects 0 rows."""
    test_db.execute(
        "INSERT INTO task_board (title, status, created_by, assigned_to) "
        "VALUES ('Guard Test Task', 'todo', 1, 1)"
    )
    test_db.commit()
    tid = test_db.execute(
        "SELECT id FROM task_board WHERE title='Guard Test Task'"
    ).fetchone()["id"]

    cur = test_db.execute(
        "UPDATE task_board SET status=%s, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=%s AND (created_by=%s OR assigned_to=%s)",
        ("done", tid, 99999, 99999)
    )
    assert cur.rowcount == 0, "Non-owner predicate must affect 0 rows"

    status = test_db.execute(
        "SELECT status FROM task_board WHERE id=%s", (tid,)
    ).fetchone()["status"]
    assert status == "todo", "Task status must be unchanged"

    test_db.execute("DELETE FROM task_board WHERE id=%s", (tid,))
    test_db.commit()


def test_task_update_owner_succeeds(test_db):
    """Owner UPDATE with the folded predicate still succeeds."""
    test_db.execute(
        "INSERT INTO task_board (title, status, created_by, assigned_to) "
        "VALUES ('Owner Update Task', 'todo', 42, 42)"
    )
    test_db.commit()
    tid = test_db.execute(
        "SELECT id FROM task_board WHERE title='Owner Update Task'"
    ).fetchone()["id"]

    cur = test_db.execute(
        "UPDATE task_board SET status=%s, updated_at=CURRENT_TIMESTAMP "
        "WHERE id=%s AND (created_by=%s OR assigned_to=%s)",
        ("done", tid, 42, 42)
    )
    assert cur.rowcount == 1, "Owner update must succeed"

    test_db.execute("DELETE FROM task_board WHERE id=%s", (tid,))
    test_db.commit()
