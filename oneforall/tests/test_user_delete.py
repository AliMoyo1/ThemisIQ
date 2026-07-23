"""
Tests for PLAN-33 Phase 2: safe delete (soft delete) for users.

Covers the two new pure/data-layer pieces: _user_reference_counts() (the
best-effort ownership/activity check used by both the impact preview and
the hard-delete safety gate) and _group_users_by_bu()'s new deleted_count
tracking. The route-level guardrails (self-delete, last-active-admin) reuse
the exact same inline patterns already covered by test_org_admin.py's
_target_user tests, so they are not re-tested here; this file focuses on
the new logic PLAN-33 Phase 2 actually introduces.

Uses the standard conftest test_db fixture (fresh, fully-migrated SQLite
per test).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _create_user(db, username="tester"):
    db.execute(
        "INSERT INTO users (username, email, full_name, password_hash) VALUES (%s,%s,%s,%s)",
        (username, f"{username}@example.com", username.title(), "x"),
    )
    db.commit()
    return db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]


def test_user_reference_counts_empty_for_fresh_user(test_db):
    from modules.launcher.routes_admin import _user_reference_counts

    uid = _create_user(test_db, "fresh_user")
    counts = _user_reference_counts(test_db, uid)
    assert counts == {}


def test_user_reference_counts_detects_audit_log_and_task_board(test_db):
    from modules.launcher.routes_admin import _user_reference_counts

    uid = _create_user(test_db, "busy_user")
    test_db.execute(
        "INSERT INTO audit_log (user_id, username, module, action) VALUES (%s,%s,%s,%s)",
        (uid, "busy_user", "erm", "Created risk"),
    )
    test_db.execute(
        "INSERT INTO task_board (title, assigned_to, created_by) VALUES (%s,%s,%s)",
        ("Follow up", uid, uid),
    )
    test_db.commit()

    counts = _user_reference_counts(test_db, uid)
    assert counts.get("audit log entries") == 1
    # assigned_to + created_by both point at this user on the same row --
    # the OR'd-column check counts distinct rows, so this is 1 task, not 2.
    assert counts.get("task(s)") == 1


def test_user_reference_counts_detects_business_unit_head(test_db):
    from modules.launcher.routes_admin import _user_reference_counts
    from modules.governance.data_service import create_business_unit

    uid = _create_user(test_db, "bu_head")
    bu_id = create_business_unit({"name": "Test SBU Head Unit"})
    test_db.execute("UPDATE business_units SET head_user_id=%s WHERE id=%s", (uid, bu_id))
    test_db.commit()

    counts = _user_reference_counts(test_db, uid)
    assert counts.get("business unit(s) headed") == 1


def test_soft_delete_and_restore_column_semantics(test_db):
    """Exercises the exact UPDATE statements the delete/restore routes run,
    proving the state machine: active -> soft-deleted (deleted_at set,
    is_active=0, sessions cleared) -> restored (deleted_at cleared, but
    is_active stays 0 -- restore does not implicitly reactivate)."""
    uid = _create_user(test_db, "delete_me")
    test_db.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (%s,%s,%s)",
        ("tok123", uid, "2099-01-01 00:00:00"),
    )
    test_db.commit()

    # Soft delete (mirrors admin_delete_user's UPDATE + session clear).
    test_db.execute(
        "UPDATE users SET deleted_at=CURRENT_TIMESTAMP, is_active=0 WHERE id=%s", (uid,)
    )
    test_db.execute("DELETE FROM sessions WHERE user_id=%s", (uid,))
    test_db.commit()

    row = test_db.execute("SELECT deleted_at, is_active FROM users WHERE id=%s", (uid,)).fetchone()
    assert row["deleted_at"] is not None
    assert row["is_active"] == 0
    remaining_sessions = test_db.execute(
        "SELECT COUNT(*) FROM sessions WHERE user_id=%s", (uid,)
    ).fetchone()[0]
    assert remaining_sessions == 0

    # Restore (mirrors admin_restore_user).
    test_db.execute("UPDATE users SET deleted_at=NULL WHERE id=%s", (uid,))
    test_db.commit()
    row = test_db.execute("SELECT deleted_at, is_active FROM users WHERE id=%s", (uid,)).fetchone()
    assert row["deleted_at"] is None
    assert row["is_active"] == 0  # still inactive -- restore alone does not reactivate


def test_deleted_users_excluded_by_default_query_clause(test_db):
    """Mirrors _render_admin_users' deleted_clause: with no show_deleted
    flag, a deleted_at IS NOT NULL user must not appear in the default
    listing query; with the flag, it does."""
    uid_active = _create_user(test_db, "still_here")
    uid_deleted = _create_user(test_db, "gone_user")
    test_db.execute(
        "UPDATE users SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s", (uid_deleted,)
    )
    test_db.commit()

    default_rows = test_db.execute(
        "SELECT id FROM users WHERE 1=1 AND deleted_at IS NULL"
    ).fetchall()
    default_ids = {r["id"] for r in default_rows}
    assert uid_active in default_ids
    assert uid_deleted not in default_ids

    all_rows = test_db.execute("SELECT id FROM users WHERE 1=1").fetchall()
    all_ids = {r["id"] for r in all_rows}
    assert uid_active in all_ids
    assert uid_deleted in all_ids


def test_group_users_by_bu_tracks_deleted_separately_from_inactive(test_db):
    from modules.launcher._route_helpers import _group_users_by_bu

    rows = [
        {"business_unit_id": None, "business_unit_name": None, "is_active": 1,
         "must_change_password": 0, "deleted_at": None},
        {"business_unit_id": None, "business_unit_name": None, "is_active": 0,
         "must_change_password": 0, "deleted_at": None},
        {"business_unit_id": None, "business_unit_name": None, "is_active": 0,
         "must_change_password": 0, "deleted_at": "2026-01-01 00:00:00"},
    ]
    groups = _group_users_by_bu(rows, {})
    assert len(groups) == 1
    g = groups[0]
    assert g["active_count"] == 1
    assert g["inactive_count"] == 1
    assert g["deleted_count"] == 1
