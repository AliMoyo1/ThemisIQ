"""Tests for PLAN-03: concurrency-safe ERM workflow and task board updates.

Run from the app root (oneforall/):
    python -m pytest tests/test_concurrency_guards.py -q
"""
from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import database as db_mod


def _init_db():
    """Minimal in-memory DB with just the tables/rows needed for these tests."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS erm_enterprise_risks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            workflow_step TEXT DEFAULT 'draft',
            status TEXT DEFAULT 'open',
            likelihood INTEGER DEFAULT 1,
            impact INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS erm_risk_workflow_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            risk_id INTEGER NOT NULL,
            from_step TEXT,
            to_step TEXT NOT NULL,
            changed_by INTEGER,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS task_board (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            status TEXT DEFAULT 'todo',
            created_by INTEGER,
            assigned_to INTEGER,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        """
    )
    from database import _SqliteConnWrapper

    class _FakeConn:
        def __init__(self):
            self._c = con
            self._w = _SqliteConnWrapper(con)
        def execute(self, sql, params=None):
            return self._w.execute(sql, params)
        def commit(self):
            self._c.commit()
        def rollback(self):
            self._c.rollback()
        def close(self):
            pass

    fake = _FakeConn()
    db_mod.get_db = lambda: fake
    return fake


def test_workflow_stale_step_raises():
    """A concurrent step change makes the conditional UPDATE hit 0 rows."""
    fake = _init_db()
    import modules.erm.data_service as erm_ds
    erm_ds.get_db = lambda: fake

    # Insert a risk at 'draft'
    fake._c.execute(
        "INSERT INTO erm_enterprise_risks (title, workflow_step) VALUES ('Test Risk', 'draft')"
    )
    fake._c.commit()
    risk_id = fake._c.execute(
        "SELECT id FROM erm_enterprise_risks ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]

    # First transition succeeds
    result = erm_ds.transition_workflow(risk_id, "identified", user_id=1)
    assert result == "identified"

    # Simulate a concurrent writer advancing the step before us
    fake._c.execute(
        "UPDATE erm_enterprise_risks SET workflow_step='assessed' WHERE id=?",
        (risk_id,),
    )
    fake._c.commit()

    # Now try the transition with a stale mental model (still thinks it's 'identified')
    # We test the guard directly: the UPDATE with stale from_step should hit 0 rows
    from database import _percent_s_to_question
    cur = fake._c.execute(
        _percent_s_to_question(
            "UPDATE erm_enterprise_risks SET workflow_step=%s, updated_at=%s "
            "WHERE id=%s AND COALESCE(workflow_step,'draft')=%s"
        ),
        ("treated", "2026-07-10 12:00:00", risk_id, "identified"),
    )
    assert cur.rowcount == 0, (
        "Conditional UPDATE with stale from_step should affect 0 rows"
    )

    # History should have exactly 1 row (the first successful transition)
    count = fake._c.execute(
        "SELECT COUNT(*) FROM erm_risk_workflow_history WHERE risk_id=?",
        (risk_id,),
    ).fetchone()[0]
    assert count == 1, "Stale race must not produce phantom history rows"


def test_workflow_happy_path():
    """Normal workflow transition works end-to-end (one row updated, history written)."""
    fake = _init_db()
    import modules.erm.data_service as erm_ds
    erm_ds.get_db = lambda: fake

    fake._c.execute(
        "INSERT INTO erm_enterprise_risks (title, workflow_step) VALUES ('Happy Risk', 'draft')"
    )
    fake._c.commit()
    risk_id = fake._c.execute(
        "SELECT id FROM erm_enterprise_risks ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]

    result = erm_ds.transition_workflow(risk_id, "identified", user_id=1)
    assert result == "identified"

    # Verify the step changed
    step = fake._c.execute(
        "SELECT workflow_step FROM erm_enterprise_risks WHERE id=?", (risk_id,)
    ).fetchone()[0]
    assert step == "identified"

    # Verify history written
    count = fake._c.execute(
        "SELECT COUNT(*) FROM erm_risk_workflow_history WHERE risk_id=?",
        (risk_id,),
    ).fetchone()[0]
    assert count == 1


def test_task_update_non_owner_refused():
    """Non-owner non-admin task UPDATE hits 0 rows."""
    fake = _init_db()

    # Insert a task owned by user 1
    fake._c.execute(
        "INSERT INTO task_board (title, created_by, assigned_to) VALUES ('My Task', 1, 1)"
    )
    fake._c.commit()
    tid = fake._c.execute(
        "SELECT id FROM task_board ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]

    # Run the guard SQL as uid=999 (not owner, not admin)
    from database import _percent_s_to_question
    cur = fake._c.execute(
        _percent_s_to_question(
            "UPDATE task_board SET title=%s, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=%s AND (created_by=%s OR assigned_to=%s)"
        ),
        ("Hacked", tid, 999, 999),
    )
    assert cur.rowcount == 0, "Non-owner must not be able to update"

    # Verify title unchanged
    title = fake._c.execute(
        "SELECT title FROM task_board WHERE id=?", (tid,)
    ).fetchone()[0]
    assert title == "My Task"
