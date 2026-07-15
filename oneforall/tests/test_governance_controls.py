"""Tests for PLAN-05: Governance Graph T1.2 (canonical controls + risk↔control bridge).

Run from the app root (oneforall/):
    python -m pytest tests/test_governance_controls.py -q
"""
from __future__ import annotations

import sys
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import database as db_mod


def _init_test_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS canonical_controls (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            ref                 TEXT,
            title               TEXT NOT NULL,
            description         TEXT,
            owner_user_id       INTEGER,
            automation          TEXT DEFAULT 'manual',
            test_frequency_days INTEGER,
            last_tested_at      TEXT,
            business_unit_id    INTEGER,
            is_active           INTEGER DEFAULT 1,
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS risk_controls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            risk_id     INTEGER NOT NULL,
            control_id  INTEGER NOT NULL,
            weight      REAL DEFAULT 1.0,
            direction   TEXT DEFAULT 'mitigates',
            created_by  INTEGER,
            created_at  TEXT DEFAULT (datetime('now')),
            UNIQUE(risk_id, control_id)
        );
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, full_name TEXT);
        CREATE TABLE IF NOT EXISTS business_units (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE IF NOT EXISTS erm_enterprise_risks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, status TEXT DEFAULT 'open',
            likelihood INTEGER DEFAULT 1, impact INTEGER DEFAULT 1, source_module TEXT
        );
        CREATE TABLE IF NOT EXISTS control_effectiveness_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            control_id INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            evidence_uploaded INTEGER DEFAULT 0,
            evidence_valid INTEGER DEFAULT 0,
            audit_passed INTEGER DEFAULT 0,
            tested_recently INTEGER DEFAULT 0,
            owner_reviewed INTEGER DEFAULT 0,
            automated INTEGER DEFAULT 0,
            no_recent_incidents INTEGER DEFAULT 0,
            scored_at TEXT DEFAULT (datetime('now')),
            UNIQUE(control_id)
        );
        INSERT OR IGNORE INTO users (id, username, full_name) VALUES (1, 'test', 'Test User');
        INSERT OR IGNORE INTO business_units (id, name) VALUES (1, 'Default BU');
        """
    )
    from database import _SqliteConnWrapper
    import modules.governance.data_service as gov_ds
    import modules.erm.data_service as erm_ds

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
    # Patch at module level so data_service references are updated
    db_mod.get_db = lambda: fake
    gov_ds.get_db = lambda: fake
    erm_ds.get_db = lambda: fake
    return fake


def test_create_and_list():
    _init_test_db()
    from modules.governance import data_service as ds
    cid = ds.create_canonical_control({"ref": "CC-001", "title": "Alpha Control"})
    assert cid > 0
    controls = ds.list_canonical_controls()
    assert any(c["title"] == "Alpha Control" for c in controls)


def test_update():
    _init_test_db()
    from modules.governance import data_service as ds
    cid = ds.create_canonical_control({"ref": "CC-002", "title": "Old"})
    ok = ds.update_canonical_control(cid, {"title": "Updated Title"})
    assert ok
    controls = ds.list_canonical_controls()
    updated = [c for c in controls if c["id"] == cid]
    assert len(updated) == 1 and updated[0]["title"] == "Updated Title"


def test_delete_unlinked():
    _init_test_db()
    from modules.governance import data_service as ds
    cid = ds.create_canonical_control({"ref": "CC-003", "title": "Deletable"})
    assert ds.delete_canonical_control(cid) is True
    controls = ds.list_canonical_controls()
    assert cid not in [c["id"] for c in controls]


def test_delete_refused_when_linked():
    fake = _init_test_db()
    from modules.governance import data_service as ds

    cid = ds.create_canonical_control({"ref": "CC-004", "title": "Linked"})
    fake._c.execute(
        "INSERT INTO risk_controls (risk_id, control_id) VALUES (?, ?)",
        (1, cid),
    )
    fake._c.commit()

    assert ds.delete_canonical_control(cid) is False, "refused when linked"
    controls = ds.list_canonical_controls()
    assert cid in [c["id"] for c in controls], "control still exists"


def test_summary_includes_count():
    _init_test_db()
    from modules.governance import data_service as ds
    ds.create_canonical_control({"ref": "CC-005", "title": "Summary"})
    summary = ds.get_governance_summary()
    assert "canonical_controls" in summary
    assert summary["canonical_controls"] >= 1


# ── ERM risk↔control link tests ──────────────────────────────────────

def test_link_and_list_risk_control():
    """Link a control to a risk, list shows it."""
    fake = _init_test_db()
    from modules.governance import data_service as gov
    from modules.erm import data_service as erm

    # Create a control
    cid = gov.create_canonical_control({"ref": "CC-010", "title": "Linked Control"})
    # Create a minimal risk (must have required fields for erm_enterprise_risks)
    fake._c.execute("INSERT INTO erm_enterprise_risks (title, status) VALUES (?, ?)",
                    ("Test Risk", "open"))
    fake._c.commit()
    risk_id = fake._c.execute("SELECT id FROM erm_enterprise_risks ORDER BY id DESC LIMIT 1").fetchone()[0]

    # Link
    ok = erm.link_risk_control(risk_id, cid, user_id=1)
    assert ok is True

    # List
    controls = erm.list_risk_controls(risk_id)
    assert len(controls) >= 1
    assert any(c["control_id"] == cid for c in controls)
    assert any("Linked Control" in (c.get("control_title") or "") for c in controls)


def test_link_idempotent():
    """Re-linking the same control is idempotent."""
    fake = _init_test_db()
    from modules.governance import data_service as gov
    from modules.erm import data_service as erm

    cid = gov.create_canonical_control({"ref": "CC-011", "title": "Idempotent"})
    fake._c.execute("INSERT INTO erm_enterprise_risks (title, status) VALUES (?, ?)", ("Risk", "open"))
    fake._c.commit()
    risk_id = fake._c.execute("SELECT id FROM erm_enterprise_risks ORDER BY id DESC LIMIT 1").fetchone()[0]

    ok1 = erm.link_risk_control(risk_id, cid, user_id=1)
    ok2 = erm.link_risk_control(risk_id, cid, user_id=1)  # same link again
    assert ok1 is True and ok2 is True
    controls = erm.list_risk_controls(risk_id)
    assert len(controls) == 1  # still 1 row


def test_unlink_risk_control():
    fake = _init_test_db()
    from modules.governance import data_service as gov
    from modules.erm import data_service as erm

    cid = gov.create_canonical_control({"ref": "CC-012", "title": "Unlink Me"})
    fake._c.execute("INSERT INTO erm_enterprise_risks (title, status) VALUES (?, ?)", ("Risk", "open"))
    fake._c.commit()
    risk_id = fake._c.execute("SELECT id FROM erm_enterprise_risks ORDER BY id DESC LIMIT 1").fetchone()[0]

    erm.link_risk_control(risk_id, cid, user_id=1)
    assert len(erm.list_risk_controls(risk_id)) == 1

    ok = erm.unlink_risk_control(risk_id, cid)
    assert ok is True
    assert len(erm.list_risk_controls(risk_id)) == 0


def test_weight_clamping():
    """Server-side weight clamping to [0.1, 5.0]."""
    fake = _init_test_db()
    from modules.governance import data_service as gov
    from modules.erm import data_service as erm

    cid = gov.create_canonical_control({"ref": "CC-013", "title": "Weighted"})
    fake._c.execute("INSERT INTO erm_enterprise_risks (title, status) VALUES (?, ?)", ("Risk", "open"))
    fake._c.commit()
    risk_id = fake._c.execute("SELECT id FROM erm_enterprise_risks ORDER BY id DESC LIMIT 1").fetchone()[0]

    erm.link_risk_control(risk_id, cid, user_id=1, weight= -2.0)
    controls = erm.list_risk_controls(risk_id)
    assert controls[0]["weight"] >= 0.1  # clamped to minimum

    erm.unlink_risk_control(risk_id, cid)
    erm.link_risk_control(risk_id, cid, user_id=1, weight=999)
    controls = erm.list_risk_controls(risk_id)
    assert controls[0]["weight"] <= 5.0  # clamped to maximum

