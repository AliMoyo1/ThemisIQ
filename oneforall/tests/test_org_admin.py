"""
Tests for PLAN-30: tenant-scoped Org Admin role.

Covers the two things that matter for this role: (1) the pre-existing
_target_user() org-scoping logic actually engages once a non-super-admin
role can reach it, and (2) the new platform.manage_org_users capability is
additive -- it does not also grant platform.manage_users (API keys,
webhooks, connectors, security stay super-admin-only).

Uses the standard conftest test_db fixture (fresh SQLite per test, no
seeded users/orgs -- create them directly, matching the pattern in
test_audit_org_isolation.py).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _create_org(db, slug):
    db.execute(
        "INSERT INTO organizations (name, slug) VALUES (%s, %s)",
        (slug.title(), slug),
    )
    db.commit()
    return db.execute(
        "SELECT id FROM organizations WHERE slug=%s", (slug,)
    ).fetchone()["id"]


def _create_user(db, username, org_id, is_super_admin=0):
    db.execute(
        "INSERT INTO users (username, email, full_name, password_hash, org_id, is_super_admin) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (username, f"{username}@example.com", username.title(), "x", org_id, is_super_admin),
    )
    db.commit()
    return db.execute(
        "SELECT id FROM users WHERE username=%s", (username,)
    ).fetchone()["id"]


def test_target_user_blocks_cross_org_access(test_db):
    """The core proof: _target_user (pre-existing code) actually enforces
    org isolation once reached by a non-super-admin caller."""
    from modules.launcher.routes_admin import _target_user

    org_a = _create_org(test_db, "org-a")
    org_b = _create_org(test_db, "org-b")
    org_admin_uid = _create_user(test_db, "org_a_admin", org_a)
    other_org_user_uid = _create_user(test_db, "org_b_user", org_b)

    org_admin = {"id": org_admin_uid, "org_id": org_a, "is_super_admin": 0}
    result = _target_user(test_db, other_org_user_uid, org_admin)
    assert result is None


def test_target_user_allows_same_org_access(test_db):
    from modules.launcher.routes_admin import _target_user

    org_a = _create_org(test_db, "org-a2")
    org_admin_uid = _create_user(test_db, "org_a2_admin", org_a)
    same_org_user_uid = _create_user(test_db, "org_a2_user", org_a)

    org_admin = {"id": org_admin_uid, "org_id": org_a, "is_super_admin": 0}
    result = _target_user(test_db, same_org_user_uid, org_admin)
    assert result is not None
    assert result["id"] == same_org_user_uid


def test_target_user_super_admin_bypasses_org_filter(test_db):
    """Sanity: existing super-admin behavior is unchanged -- they can
    still target any user regardless of org."""
    from modules.launcher.routes_admin import _target_user

    org_a = _create_org(test_db, "org-a3")
    org_b = _create_org(test_db, "org-b3")
    super_uid = _create_user(test_db, "super3", org_a, is_super_admin=1)
    other_org_user_uid = _create_user(test_db, "org_b3_user", org_b)

    super_admin = {"id": super_uid, "org_id": org_a, "is_super_admin": 1}
    result = _target_user(test_db, other_org_user_uid, super_admin)
    assert result is not None
    assert result["id"] == other_org_user_uid


def test_org_admin_capability_grants():
    from core.rbac import has_capability, ORG_ADMIN, EMPLOYEE, SUPER_ADMIN

    org_admin_user = {"is_super_admin": 0, "roles": [ORG_ADMIN]}
    employee_user = {"is_super_admin": 0, "roles": [EMPLOYEE]}

    assert has_capability(org_admin_user, "platform.manage_org_users") is True
    assert has_capability(employee_user, "platform.manage_org_users") is False

    # Additive only: org_admin must NOT also get platform.manage_users
    # (API keys, webhooks, connectors, security, email settings stay
    # super-admin-only).
    assert has_capability(org_admin_user, "platform.manage_users") is False
    assert has_capability({"is_super_admin": 0, "roles": [SUPER_ADMIN]},
                           "platform.manage_users") is True

    # Org Admin should be able to reach Org Structure / BU assignment --
    # a natural extension of "managing my org's users".
    assert has_capability(org_admin_user, "governance.bu.assign") is True
    assert has_capability(org_admin_user, "governance.entities.manage") is True
