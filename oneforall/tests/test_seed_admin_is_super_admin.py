"""
Code-review finding (2026-09-28): the default seeded admin held the
SUPER_ADMIN role_key (granted via user_roles) but the raw
users.is_super_admin column was left at its default (0), because
seeds/seed.py's INSERT never set it. Several code paths -- most
concretely modules/erm/data_service.py's ERM library management --
check that raw column directly rather than going through the role-based
capability system, so the fresh-install default admin was not treated
as a true platform super admin by that code, reachable on literally the
first install (see test_erm_library_tenancy.py's companion test for the
concrete consequence this caused).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.rbac import SUPER_ADMIN
from seeds.seed import seed_users


def test_seeded_admin_has_is_super_admin_flag_set(test_db):
    """Red proof (temporarily dropping ", is_super_admin" / ", 1" from
    seed.py's INSERT): this assertion fails with is_super_admin == 0.
    Restored, it passes."""
    seed_users(test_db)
    row = test_db.execute(
        "SELECT is_super_admin FROM users WHERE username='admin'"
    ).fetchone()
    assert row is not None, "seed_users must create the default admin user"
    assert row["is_super_admin"] == 1, (
        "the seeded admin holds the SUPER_ADMIN role_key but must also have "
        "the raw is_super_admin column set, since some code checks that "
        "column directly rather than the role-based capability system"
    )


def _legacy_user(test_db, username, email, full_name):
    cur = test_db.execute(
        "INSERT INTO users (username, email, full_name, password_hash) "
        "VALUES (%s, %s, %s, 'x')",
        (username, email, full_name),
    )
    user_id = cur.lastrowid
    test_db.execute(
        "INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)",
        (user_id, SUPER_ADMIN),
    )
    test_db.commit()
    return user_id


def test_init_db_promotes_the_exact_legacy_seeded_admin(test_db):
    """Existing databases skip seed_users(), so init_db must migrate the old seed."""
    import database

    user_id = _legacy_user(
        test_db,
        "admin",
        "admin@oneforall.local",
        "System Administrator",
    )

    database.init_db()
    database.init_db()  # A second startup must be a no-op.

    row = test_db.execute(
        "SELECT is_super_admin FROM users WHERE id=%s", (user_id,)
    ).fetchone()
    assert row["is_super_admin"] == 1


def test_init_db_does_not_promote_an_org_scoped_super_admin_role(test_db):
    """The data migration must not turn every SUPER_ADMIN role into platform access."""
    import database

    user_id = _legacy_user(
        test_db,
        "org_admin",
        "org-admin@example.com",
        "Organization Administrator",
    )

    database.init_db()

    row = test_db.execute(
        "SELECT is_super_admin FROM users WHERE id=%s", (user_id,)
    ).fetchone()
    assert row["is_super_admin"] == 0
