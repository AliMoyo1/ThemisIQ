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
