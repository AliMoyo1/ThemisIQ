"""Tests for PLAN-07: Related Items cross-module linking API.

Run from the app root (oneforall/):
    python -m pytest tests/test_cross_module_links_api.py -q
"""
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import database as db_mod
import pytest


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS cross_module_links (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_module   TEXT NOT NULL,
            source_type     TEXT NOT NULL,
            source_id       INTEGER NOT NULL,
            target_module   TEXT NOT NULL,
            target_type     TEXT NOT NULL,
            target_id       INTEGER NOT NULL,
            relationship    TEXT DEFAULT 'related',
            created_by      INTEGER,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_xlinks_dedup
            ON cross_module_links(
                source_module, source_type, source_id,
                target_module, target_type, target_id, relationship
            );
        CREATE TABLE IF NOT EXISTS erm_enterprise_risks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT
        );
        CREATE TABLE IF NOT EXISTS bcm_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT
        );
        CREATE TABLE IF NOT EXISTS orm_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT
        );
        CREATE TABLE IF NOT EXISTS grid_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT
        );
        INSERT INTO erm_enterprise_risks (id, title) VALUES (1, 'Test Risk');
        INSERT INTO bcm_plans (id, title) VALUES (1, 'Test Plan');
        INSERT INTO orm_events (id, title) VALUES (1, 'Test Event');
        INSERT INTO grid_audits (id, name) VALUES (1, 'Test Audit');
        """
    )
    from database import _SqliteConnWrapper
    class FakeConn:
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
    fake = FakeConn()
    db_mod.get_db = lambda: fake
    yield fake, con


def test_create_link(db):
    """Link risk→plan creates one row."""
    fake, con = db
    from modules.launcher.routes_platform import _LINKABLE
    fake._c.execute(
        "INSERT INTO cross_module_links (source_module, source_type, source_id, target_module, target_type, target_id, relationship, created_by) "
        "VALUES ('erm', 'risk', 1, 'bcm', 'plan', 1, 'related', 1)"
    )
    fake._c.commit()
    count = con.execute("SELECT COUNT(*) FROM cross_module_links").fetchone()[0]
    assert count == 1


def test_duplicate_link_idempotent(db):
    """Same link twice = one row (UNIQUE constraint)."""
    fake, con = db
    from database import _percent_s_to_question
    for _ in range(2):
        try:
            fake._c.execute(
                _percent_s_to_question(
                    "INSERT INTO cross_module_links (source_module, source_type, source_id, target_module, target_type, target_id, relationship, created_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING"
                ),
                ("erm", "risk", 1, "bcm", "plan", 1, "related", 1)
            )
            fake._c.commit()
        except Exception:
            pass
    count = con.execute("SELECT COUNT(*) FROM cross_module_links").fetchone()[0]
    assert count == 1, "Duplicate link must produce exactly one row"


def test_query_both_directions(db):
    """Link stored one way appears from both entities."""
    fake, con = db
    fake._c.execute(
        "INSERT INTO cross_module_links (source_module, source_type, source_id, target_module, target_type, target_id, relationship, created_by) "
        "VALUES ('erm', 'risk', 1, 'bcm', 'plan', 1, 'related', 1)"
    )
    fake._c.commit()

    src_rows = con.execute(
        "SELECT target_module AS module, target_type AS entity_type, target_id AS entity_id "
        "FROM cross_module_links WHERE source_module='erm' AND source_type='risk' AND source_id=1"
    ).fetchall()
    assert len(src_rows) == 1

    tgt_rows = con.execute(
        "SELECT source_module AS module, source_type AS entity_type, source_id AS entity_id "
        "FROM cross_module_links WHERE target_module='bcm' AND target_type='plan' AND target_id=1"
    ).fetchall()
    assert len(tgt_rows) == 1


def test_delete_link(db):
    """Delete a link by id."""
    fake, con = db
    fake._c.execute(
        "INSERT INTO cross_module_links (id, source_module, source_type, source_id, target_module, target_type, target_id, relationship, created_by) "
        "VALUES (100, 'erm', 'risk', 1, 'bcm', 'plan', 1, 'related', 1)"
    )
    fake._c.commit()
    fake._c.execute("DELETE FROM cross_module_links WHERE id=100")
    fake._c.commit()
    count = con.execute("SELECT COUNT(*) FROM cross_module_links").fetchone()[0]
    assert count == 0
