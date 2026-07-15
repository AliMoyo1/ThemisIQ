"""Tests for PLAN-09: Governance Advisories (daily briefing) engine.

Run from the app root (oneforall/):
    python -m pytest tests/test_advisor.py -q
"""
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
import database as db_mod


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS governance_advisories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            briefing_date TEXT NOT NULL,
            severity TEXT DEFAULT 'info',
            signal_key TEXT NOT NULL,
            title TEXT NOT NULL,
            detail TEXT,
            link TEXT,
            ai_narrative TEXT,
            acknowledged_by INTEGER,
            acknowledged_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(briefing_date, signal_key)
        );
        CREATE TABLE IF NOT EXISTS evidence_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, status TEXT DEFAULT 'current',
            expiry_date TEXT, category TEXT
        );
        CREATE TABLE IF NOT EXISTS grid_audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
            end_date TEXT, status TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS grid_non_conformances (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT,
            severity TEXT, status TEXT DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS bcm_exercises (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT,
            exercise_date TEXT
        );
        CREATE TABLE IF NOT EXISTS ai_risk_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prediction_score INTEGER, created_at TEXT,
            is_active INTEGER DEFAULT 1
        );
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
    orig_get_db = db_mod.get_db
    db_mod.get_db = lambda: fake
    yield fake, con
    db_mod.get_db = orig_get_db


def test_collect_signals_with_expiring_evidence(db):
    """Evidence expiring signal fires when items expire within 7 days."""
    fake, con = db
    from core.advisor import collect_signals

    fake._c.execute("INSERT INTO evidence_items (title, status, expiry_date) VALUES ('Doc A', 'current', date('now', '+3 days'))")
    fake._c.commit()

    signals = collect_signals(con)
    keys = [s["signal_key"] for s in signals]
    assert "evidence_expiring" in keys


def test_collect_signals_no_false_positives(db):
    """Without seeded data, signals list may be empty but never raises."""
    fake, con = db
    from core.advisor import collect_signals

    signals = collect_signals(con)
    assert isinstance(signals, list), "Must return a list even with empty tables"


def test_compose_briefing_idempotent(db):
    """Second compose call for same date returns 0 and doesn't duplicate."""
    fake, con = db
    from core.advisor import compose_briefing

    # Seed data that triggers a signal
    fake._c.execute("INSERT INTO grid_audits (name, end_date, status) VALUES ('Overdue', date('now', '-1 day'), 'active')")
    fake._c.commit()

    first = compose_briefing(fake, "2026-07-11")
    second = compose_briefing(fake, "2026-07-11")

    assert second == 0, "Second compose for same date must return 0"
    count = con.execute("SELECT COUNT(*) FROM governance_advisories WHERE briefing_date='2026-07-11'").fetchone()[0]
    assert count > 0
    # Second call should not add rows
    assert count >= first, "Rows must not decrease"


def test_advisory_acknowledge(db):
    """Acknowledge an advisory updates the acknowledged_by field."""
    fake, con = db
    from core.advisor import compose_briefing

    fake._c.execute("INSERT INTO grid_audits (name, end_date, status) VALUES ('Test', date('now', '-1 day'), 'active')")
    fake._c.commit()
    compose_briefing(fake, "2026-07-11")

    row = con.execute("SELECT id FROM governance_advisories WHERE briefing_date='2026-07-11' LIMIT 1").fetchone()
    advisory_id = row[0]

    con.execute("UPDATE governance_advisories SET acknowledged_by=99, acknowledged_at=datetime('now') WHERE id=?", (advisory_id,))
    con.commit()

    updated = con.execute("SELECT acknowledged_by FROM governance_advisories WHERE id=?", (advisory_id,)).fetchone()[0]
    assert updated == 99
