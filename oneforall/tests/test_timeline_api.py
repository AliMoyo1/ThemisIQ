"""Tests for PLAN-08: Governance Timeline — data-layer verification.

We test the SQL filtering directly rather than the route handler,
since the handler logic is composed of simple SQL + Python transforms
that are best verified at the data layer. The route itself adds only
auth and HTTP marshalling.

Run from the app root (oneforall/):
    python -m pytest tests/test_timeline_api.py -q
"""
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest
from database import sql_date_offset


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type          TEXT NOT NULL,
            source_module       TEXT,
            source_entity_type  TEXT,
            source_entity_id    INTEGER,
            payload             TEXT DEFAULT '{}',
            created_by          INTEGER,
            created_at          TEXT,
            status              TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT, full_name TEXT
        );
        INSERT INTO users (id, username, full_name) VALUES (1, 'admin', 'Admin User');
        INSERT INTO events (id, event_type, source_module, source_entity_type, source_entity_id, created_by, created_at)
            VALUES (1, 'erm.risk.created', 'erm', 'enterprise_risk', 42, 1, datetime('now'));
        INSERT INTO events (id, event_type, source_module, source_entity_type, source_entity_id, created_by, created_at)
            VALUES (2, 'sentinel.breach.confirmed', 'sentinel', 'breach', 7, 1, datetime('now'));
        INSERT INTO events (id, event_type, source_module, source_entity_type, source_entity_id, created_by, created_at)
            VALUES (3, 'old.event', 'bcm', 'plan', 1, 1, datetime('now', '-60 days'));
        """
    )
    yield c
    c.close()


def test_timeline_recent_filter(con):
    """WHERE created_at >= days-ago returns only recent 2 events."""
    days_ago = sql_date_offset("-7 days")
    where = f"created_at >= {days_ago}"
    rows = con.execute(f"SELECT COUNT(*) FROM events WHERE {where}").fetchone()
    assert rows[0] == 2, f"Expected 2 recent, got {rows[0]}"


def test_timeline_module_filter(con):
    """Filter by source_module returns only that module's events."""
    days_ago = sql_date_offset("-365 days")
    where = f"created_at >= {days_ago} AND source_module = 'sentinel'"
    rows = con.execute(f"SELECT id, event_type FROM events WHERE {where}").fetchall()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "sentinel.breach.confirmed"


def test_timeline_pagination_offset(con):
    """OFFSET works correctly for pagination."""
    days_ago = sql_date_offset("-365 days")
    where = f"created_at >= {days_ago}"
    rows = con.execute(
        f"SELECT id FROM events WHERE {where} ORDER BY created_at DESC LIMIT 100 OFFSET 2"
    ).fetchall()
    # There are 3 events total, so offset 2 should return the oldest 1
    assert len(rows) == 1
    assert rows[0]["id"] == 3


def test_event_label_map():
    """The event label map covers the known event types."""
    import modules.launcher.routes_platform as rp
    from modules.launcher.routes_platform import _EVENT_LABELS

    assert _EVENT_LABELS["erm.risk.created"] == "Risk created"
    assert _EVENT_LABELS["sentinel.breach.confirmed"] == "Breach confirmed"
    assert len(_EVENT_LABELS) >= 18


def test_entity_type_alias():
    """Entity type aliases map event types to PLAN-06 deep-link types."""
    from modules.launcher.routes_platform import _ENTITY_TYPE_ALIAS

    assert _ENTITY_TYPE_ALIAS["enterprise_risk"] == "risk"
    assert _ENTITY_TYPE_ALIAS["non_conformance"] == "nc"
    assert _ENTITY_TYPE_ALIAS["processing_activity"] == "ropa"
