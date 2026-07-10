"""Regression: audit_log activity queries must scope to the current org.

Run from repo root: .venv/Scripts/python -m pytest tests/test_audit_org_isolation.py -q
"""
import database
from database import set_current_org, get_current_org


def test_get_current_org_roundtrip():
    set_current_org(42)
    assert get_current_org() == 42
    set_current_org(None)
    assert get_current_org() is None


def test_grid_log_activity_stamps_org(test_db):
    from modules.grid import data_service as gds
    # Create a real org + user so the audit_log FKs (org_id, user_id) are satisfied.
    test_db.execute(
        "INSERT INTO organizations (name, slug) VALUES (%s, %s)",
        ("PL01 Test Org", "pl01-test-org"),
    )
    test_db.commit()
    org_id = test_db.execute(
        "SELECT id FROM organizations WHERE slug='pl01-test-org'"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO users (username, email, full_name, password_hash, org_id) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("pl01_test_user", "pl01@test.local", "PL01 Test", "x", org_id),
    )
    test_db.commit()
    uid = test_db.execute(
        "SELECT id FROM users WHERE username='pl01_test_user'"
    ).fetchone()[0]
    set_current_org(org_id)
    gds.log_activity(uid, "test_org_stamp", "test", 0, None)
    set_current_org(None)
    row = test_db.execute(
        "SELECT org_id FROM audit_log WHERE action='test_org_stamp' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row[0] == org_id
    test_db.execute("DELETE FROM audit_log WHERE action='test_org_stamp'")
    test_db.execute("DELETE FROM users WHERE username='pl01_test_user'")
    test_db.execute("DELETE FROM organizations WHERE slug='pl01-test-org'")
    test_db.commit()
