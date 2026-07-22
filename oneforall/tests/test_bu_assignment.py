"""
Tests for PLAN-SBU-01: User -> Business Unit assignment.

Covers assign/clear, rejection of unknown/inactive BUs, the end-to-end link
to bu_scope_ids() (the acceptance-linking test -- proves the whole scoping
mechanism is reachable once a user is actually assigned), and that
list_assignable_users() surfaces the assigned BU's name.

Uses the standard conftest test_db fixture (fresh SQLite per test, no
seeded users -- create them via the local _create_user helper).
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
    row = db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()
    return row["id"]


def test_assign_and_clear(test_db):
    from modules.governance.data_service import (
        create_business_unit, assign_user_business_unit, get_business_unit_tree,
    )

    parent_id = create_business_unit({"name": "Econet"})
    child_id = create_business_unit({"name": "EcoCash", "parent_id": parent_id})
    uid = _create_user(test_db, "alice")

    ok = assign_user_business_unit(uid, child_id)
    assert ok is True
    row = test_db.execute("SELECT business_unit_id FROM users WHERE id=%s", (uid,)).fetchone()
    assert row["business_unit_id"] == child_id

    ok = assign_user_business_unit(uid, None)
    assert ok is True
    row = test_db.execute("SELECT business_unit_id FROM users WHERE id=%s", (uid,)).fetchone()
    assert row["business_unit_id"] is None

    # Sanity: the tree actually nests EcoCash under Econet.
    tree = get_business_unit_tree()
    root = next(b for b in tree if b["id"] == parent_id)
    assert any(c["id"] == child_id for c in root["children"])


def test_assign_rejects_unknown_bu(test_db):
    from modules.governance.data_service import assign_user_business_unit

    uid = _create_user(test_db, "bob")
    ok = assign_user_business_unit(uid, 999999)
    assert ok is False
    row = test_db.execute("SELECT business_unit_id FROM users WHERE id=%s", (uid,)).fetchone()
    assert row["business_unit_id"] is None


def test_assign_rejects_inactive_bu(test_db):
    from modules.governance.data_service import create_business_unit, assign_user_business_unit

    bu_id = create_business_unit({"name": "Infraco"})
    test_db.execute("UPDATE business_units SET is_active=0 WHERE id=%s", (bu_id,))
    test_db.commit()

    uid = _create_user(test_db, "carol")
    ok = assign_user_business_unit(uid, bu_id)
    assert ok is False
    row = test_db.execute("SELECT business_unit_id FROM users WHERE id=%s", (uid,)).fetchone()
    assert row["business_unit_id"] is None


def test_bu_scope_after_assignment(test_db):
    """The acceptance-linking test: assigning a user to the PARENT BU makes
    bu_scope_ids() return a rollup list containing both parent and child --
    proving the whole scoping mechanism is reachable once assignment works,
    not just that a column got written."""
    from modules.governance.data_service import (
        create_business_unit, assign_user_business_unit, bu_scope_ids,
    )

    parent_id = create_business_unit({"name": "Econet"})
    child_id = create_business_unit({"name": "EconetAI", "parent_id": parent_id})
    uid = _create_user(test_db, "dave")

    assign_user_business_unit(uid, parent_id)

    scope = bu_scope_ids({"business_unit_id": parent_id, "is_super_admin": 0})
    assert scope is not None
    assert parent_id in scope
    assert child_id in scope

    # A user with no BU (or super_admin) stays unrestricted.
    assert bu_scope_ids({"business_unit_id": None, "is_super_admin": 0}) is None
    assert bu_scope_ids({"business_unit_id": parent_id, "is_super_admin": 1}) is None


def test_list_assignable_users_includes_bu_name(test_db):
    from modules.governance.data_service import (
        create_business_unit, assign_user_business_unit, list_assignable_users,
    )

    bu_id = create_business_unit({"name": "Infraco"})
    uid = _create_user(test_db, "erin")
    assign_user_business_unit(uid, bu_id)

    users = list_assignable_users()
    row = next(u for u in users if u["id"] == uid)
    assert row["business_unit_id"] == bu_id
    assert row["business_unit_name"] == "Infraco"

    # An inactive user must not appear.
    test_db.execute("UPDATE users SET is_active=0 WHERE id=%s", (uid,))
    test_db.commit()
    users = list_assignable_users()
    assert not any(u["id"] == uid for u in users)
