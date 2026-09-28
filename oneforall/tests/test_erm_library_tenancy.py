"""
PLAN-36 T03 (findings.md F13): erm_risk_library tenant-safe scoping.

Uses the standard conftest test_db fixture (fresh SQLite per test) and
plain actor dicts shaped like request.state.user -- modules/erm/data_service.py's
library functions take actor explicitly rather than a request, so no route
or middleware mocking is needed here (mirrors test_erm_objectives.py's
pattern for the rest of this module).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.erm import data_service as ds


def _ensure_org(test_db, org_id):
    if org_id is None:
        return
    row = test_db.execute("SELECT id FROM organizations WHERE id=%s", (org_id,)).fetchone()
    if row:
        return
    test_db.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
        (org_id, f"org{org_id}", f"org{org_id}"),
    )
    test_db.commit()


def _actor(test_db, user_id, org_id, is_super_admin=False):
    """A request.state.user-shaped dict backed by a real users row (and
    organizations row, if org_id is set) -- erm_risk_library.created_by and
    .org_id are real foreign keys, so an actor with no matching row would
    fail at INSERT with a constraint error unrelated to what's under test."""
    _ensure_org(test_db, org_id)
    row = test_db.execute("SELECT id FROM users WHERE id=%s", (user_id,)).fetchone()
    if not row:
        test_db.execute(
            "INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
            "VALUES (%s,%s,%s,%s,'x',%s)",
            (user_id, f"user{user_id}", f"user{user_id}@example.com", f"User {user_id}", org_id),
        )
        test_db.commit()
    return {"id": user_id, "org_id": org_id, "is_super_admin": is_super_admin}


def _seed_global(test_db, title="Global Template"):
    test_db.execute(
        "INSERT INTO erm_risk_library (title, category, org_id) VALUES (%s,'operational',NULL)",
        (title,),
    )
    test_db.commit()
    return test_db.execute("SELECT id FROM erm_risk_library WHERE title=%s", (title,)).fetchone()["id"]


def _seed_org(test_db, org_id, title):
    _ensure_org(test_db, org_id)
    test_db.execute(
        "INSERT INTO erm_risk_library (title, category, org_id) VALUES (%s,'operational',%s)",
        (title, org_id),
    )
    test_db.commit()
    return test_db.execute("SELECT id FROM erm_risk_library WHERE title=%s", (title,)).fetchone()["id"]


# ─────────────────────────────────────────────────────────────────────────
# Read scope: list_library / get_library_item
# ─────────────────────────────────────────────────────────────────────────

def test_list_library_returns_global_plus_own_org_only(test_db):
    # test_db auto-seeds the ~24-row baseline global catalogue (all
    # org_id NULL) the first time erm_risk_library is empty -- this test
    # only needs to prove "Global A" is included and "Org2 Custom" is not,
    # not an exact-set match against however many global rows exist.
    _seed_global(test_db, "Global A")
    _seed_org(test_db, 1, "Org1 Custom")
    _seed_org(test_db, 2, "Org2 Custom")

    rows = ds.list_library(_actor(test_db, 10, org_id=1))
    titles = {r["title"] for r in rows}
    assert {"Global A", "Org1 Custom"}.issubset(titles), "must see global + own org rows"
    assert "Org2 Custom" not in titles, "must never see another org's row"


def test_get_library_item_hides_another_orgs_row(test_db):
    other_org_id = _seed_org(test_db, 2, "Org2 Custom")
    assert ds.get_library_item(other_org_id, _actor(test_db, 10, org_id=1)) is None, \
        "another organization's row must be invisible, not just unmanageable"


def test_get_library_item_returns_global_row_to_any_org(test_db):
    global_id = _seed_global(test_db)
    assert ds.get_library_item(global_id, _actor(test_db, 10, org_id=1)) is not None
    assert ds.get_library_item(global_id, _actor(test_db, 20, org_id=2)) is not None


def test_get_library_item_returns_own_org_row(test_db):
    own_id = _seed_org(test_db, 1, "Org1 Custom")
    assert ds.get_library_item(own_id, _actor(test_db, 10, org_id=1)) is not None


# ─────────────────────────────────────────────────────────────────────────
# Write scope: update / delete / create
# ─────────────────────────────────────────────────────────────────────────

def test_org_risk_owner_cannot_update_global_row(test_db):
    global_id = _seed_global(test_db)
    ok = ds.update_library_item(global_id, {"title": "Hijacked"}, _actor(test_db, 10, org_id=1))
    assert ok is False
    row = test_db.execute("SELECT title FROM erm_risk_library WHERE id=%s", (global_id,)).fetchone()
    assert row["title"] != "Hijacked"


def test_org_risk_owner_cannot_update_another_orgs_row(test_db):
    other_id = _seed_org(test_db, 2, "Org2 Custom")
    ok = ds.update_library_item(other_id, {"title": "Hijacked"}, _actor(test_db, 10, org_id=1))
    assert ok is False
    row = test_db.execute("SELECT title FROM erm_risk_library WHERE id=%s", (other_id,)).fetchone()
    assert row["title"] == "Org2 Custom"


def test_org_risk_owner_can_crud_own_org_row(test_db):
    own_id = _seed_org(test_db, 1, "Org1 Custom")
    actor = _actor(test_db, 10, org_id=1)
    assert ds.update_library_item(own_id, {"title": "Renamed"}, actor) is True
    row = test_db.execute("SELECT title, is_active FROM erm_risk_library WHERE id=%s", (own_id,)).fetchone()
    assert row["title"] == "Renamed"

    assert ds.delete_library_item(own_id, actor) is True
    row = test_db.execute("SELECT is_active FROM erm_risk_library WHERE id=%s", (own_id,)).fetchone()
    assert row["is_active"] == 0, "delete must be soft retirement, row must still exist"


def test_super_admin_can_manage_global_row(test_db):
    global_id = _seed_global(test_db)
    admin = _actor(test_db, 1, org_id=None, is_super_admin=True)
    assert ds.update_library_item(global_id, {"title": "Curated Update"}, admin) is True
    row = test_db.execute("SELECT title FROM erm_risk_library WHERE id=%s", (global_id,)).fetchone()
    assert row["title"] == "Curated Update"


def test_super_admin_can_manage_any_orgs_row(test_db):
    """Explicit platform-super-admin override, distinct from ordinary
    cross-org access (which must stay denied for everyone else)."""
    other_id = _seed_org(test_db, 2, "Org2 Custom")
    admin = _actor(test_db, 1, org_id=None, is_super_admin=True)
    assert ds.delete_library_item(other_id, admin) is True


def test_create_library_item_by_super_admin_is_global(test_db):
    admin = _actor(test_db, 1, org_id=None, is_super_admin=True)
    new_id = ds.create_library_item({"title": "New Global"}, admin)
    row = test_db.execute("SELECT org_id, created_by FROM erm_risk_library WHERE id=%s", (new_id,)).fetchone()
    assert row["org_id"] is None
    assert row["created_by"] == 1


def test_create_library_item_by_org_user_is_scoped_to_their_org(test_db):
    actor = _actor(test_db, 10, org_id=1)
    new_id = ds.create_library_item({"title": "New Org Template", "org_id": 999}, actor)
    row = test_db.execute("SELECT org_id, created_by FROM erm_risk_library WHERE id=%s", (new_id,)).fetchone()
    assert row["org_id"] == 1, "caller-supplied org_id must never be trusted"
    assert row["created_by"] == 10


# ─────────────────────────────────────────────────────────────────────────
# Title uniqueness is scoped (global vs per-org), not one blanket constraint
# ─────────────────────────────────────────────────────────────────────────

def test_two_organizations_can_use_the_same_template_title(test_db):
    ds.create_library_item({"title": "Shared Name"}, _actor(test_db, 10, org_id=1))
    # Must not raise -- org 2 using the same title as org 1 is not a conflict.
    new_id = ds.create_library_item({"title": "Shared Name"}, _actor(test_db, 20, org_id=2))
    assert new_id > 0


def test_duplicate_title_within_the_same_global_scope_is_rejected(test_db):
    admin = _actor(test_db, 1, org_id=None, is_super_admin=True)
    ds.create_library_item({"title": "Only One Global"}, admin)
    try:
        ds.create_library_item({"title": "Only One Global"}, admin)
        assert False, "expected a uniqueness violation for a second identically-titled global row"
    except Exception as exc:
        assert "unique" in str(exc).lower() or "constraint" in str(exc).lower(), \
            f"expected a uniqueness error, got: {exc!r}"
