"""Tests for PLAN-10: Evidence Confidence Score.

Run from the app root (oneforall/):
    python -m pytest tests/test_evidence_confidence.py -q
"""
import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


def _fake_item(overrides=None):
    """Return a minimal evidence item dict for compute_confidence testing."""
    item = {
        "verification_method": "self_asserted",
        "expiry_date": None,
        "file_hash": None,
    }
    if overrides:
        item.update(overrides)
    return item


def test_compute_confidence_default():
    """Self-asserted, no expiry, no links, no hash → 15."""
    from modules.evidence.routes import compute_confidence
    score = compute_confidence(_fake_item(), link_count=0)
    assert score == 15, f"Expected 15, got {score}"


def test_compute_confidence_digitally_signed():
    """Digitally signed + fresh (>30d) + 3 links + hash → 90."""
    from modules.evidence.routes import compute_confidence
    item = _fake_item({
        "verification_method": "digitally_signed",
        "expiry_date": "2099-12-31",
        "file_hash": "abc123",
    })
    score = compute_confidence(item, link_count=3)
    assert score == 90, f"Expected 90, got {score}"


def test_compute_confidence_expired():
    """Expired item with peer_reviewed + hash → 30 (no freshness)."""
    from modules.evidence.routes import compute_confidence
    item = _fake_item({
        "verification_method": "peer_reviewed",
        "expiry_date": "2020-01-01",
        "file_hash": "xyz",
    })
    score = compute_confidence(item, link_count=0)
    assert score == 30, f"Expected 30, got {score}"


def test_compute_confidence_medium():
    """Auditor_signed + 8-day expiry + 1 link + no hash → 55."""
    from modules.evidence.routes import compute_confidence
    from core.timeutils import utcnow
    from datetime import timedelta
    future = (utcnow() + timedelta(days=8)).strftime("%Y-%m-%d")
    item = _fake_item({
        "verification_method": "auditor_signed",
        "expiry_date": future,
    })
    score = compute_confidence(item, link_count=1)
    assert score == 55, f"Expected 55, got {score}"


def test_recompute_confidence_persists():
    """recompute_confidence stores the correct score in DB (using in-memory DB)."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE evidence_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, status TEXT DEFAULT 'current',
            verification_method TEXT DEFAULT 'self_asserted', verified_by INTEGER, verified_at TEXT,
            confidence_score INTEGER, file_hash TEXT, expiry_date TEXT, category TEXT
        );
        CREATE TABLE evidence_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT, evidence_id INTEGER NOT NULL,
            module TEXT, entity_type TEXT, entity_id INTEGER
        );
        INSERT INTO evidence_items (title, verification_method, file_hash) VALUES ('Test', 'self_asserted', 'hash123');
    """)
    from database import _SqliteConnWrapper

    class FakeConn:
        def __init__(self):
            self._c = con
            self._w = _SqliteConnWrapper(con)
        def execute(self, sql, params=None):
            return self._w.execute(sql, params)
        def commit(self):
            self._c.commit()
        def close(self):
            pass

    from modules.evidence import routes as ev
    db = FakeConn()
    eid = 1
    score = ev.recompute_confidence(db, eid)
    assert score > 0
    stored = con.execute("SELECT confidence_score FROM evidence_items WHERE id=1").fetchone()[0]
    assert stored == score, f"Stored {stored} != computed {score}"
