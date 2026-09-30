"""
PLAN-36 T08 finding (2026-09-30, found while building download-contract
tests, not one of findings.md's original F01-F13): evidence_items had no
tenant-scoping column at all. Every list/get/download/update/delete/restore
route queried it by plain id with no org filter -- any authenticated user in
any organization could read or destroy any other organization's evidence.

This file tests the two backend pieces of the fix directly (no browser, no
live_app -- these are pure data/migration-layer checks, same style as
test_seed_admin_is_super_admin.py):

1. _backfill_evidence_org_id (database.py): a data migration for rows that
   existed before the org_id column did.
2. _scoped_evidence_item (modules/evidence/routes.py): the shared fail-closed
   lookup every affected route now goes through.

HTTP-level cross-org proof (a real upload by one org, a real denied
list/get/download/update/delete attempt by another) is in
tests/ui/test_org_isolation.py, which already has the two-organization
fixture this needs.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _org(test_db, slug):
    test_db.execute(
        "INSERT INTO organizations (name, slug, plan, status) VALUES (%s, %s, 'enterprise', 'active')",
        (slug, slug),
    )
    test_db.commit()
    return test_db.execute(
        "SELECT id FROM organizations WHERE slug=%s", (slug,)
    ).fetchone()["id"]


def _user(test_db, username, org_id):
    test_db.execute(
        "INSERT INTO users (username, email, full_name, password_hash, org_id) "
        "VALUES (%s, %s, %s, 'x', %s)",
        (username, f"{username}@example.test", username, org_id),
    )
    test_db.commit()
    return test_db.execute(
        "SELECT id FROM users WHERE username=%s", (username,)
    ).fetchone()["id"]


def _evidence(test_db, uploaded_by, org_id=None):
    cur = test_db.execute(
        "INSERT INTO evidence_items (title, uploaded_by, org_id) VALUES (%s, %s, %s)",
        ("Test Evidence", uploaded_by, org_id),
    )
    test_db.commit()
    return cur.lastrowid


def test_backfill_sets_org_id_from_uploader(test_db):
    """Red proof (temporarily commenting out the call to
    _backfill_evidence_org_id in database.init_db): this assertion fails
    with org_id None. Restored, it passes."""
    import database

    org_id = _org(test_db, "evidence-backfill-org")
    uid = _user(test_db, "evidence_backfill_uploader", org_id)
    eid = _evidence(test_db, uid, org_id=None)  # simulates a pre-migration row

    database.init_db()

    row = test_db.execute(
        "SELECT org_id FROM evidence_items WHERE id=%s", (eid,)
    ).fetchone()
    assert row["org_id"] == org_id


def test_backfill_does_not_overwrite_an_already_set_org_id(test_db):
    """A row that already has an org_id (uploaded after the fix) must never
    be reassigned to its uploader's CURRENT org, in case that user moved
    orgs later -- the backfill is for NULL rows only."""
    import database

    org_a = _org(test_db, "evidence-backfill-org-a")
    org_b = _org(test_db, "evidence-backfill-org-b")
    uid = _user(test_db, "evidence_backfill_mover", org_b)
    eid = _evidence(test_db, uid, org_id=org_a)

    database.init_db()

    row = test_db.execute(
        "SELECT org_id FROM evidence_items WHERE id=%s", (eid,)
    ).fetchone()
    assert row["org_id"] == org_a


def test_backfill_leaves_orphaned_uploader_rows_null(test_db):
    """An uploader with no org_id (or a deleted uploader) leaves the row
    NULL, which _scoped_evidence_item treats as super-admin-only -- the
    safe direction to fail closed in, not a crash and not a guess."""
    import database

    eid = _evidence(test_db, uploaded_by=None, org_id=None)

    database.init_db()

    row = test_db.execute(
        "SELECT org_id FROM evidence_items WHERE id=%s", (eid,)
    ).fetchone()
    assert row["org_id"] is None


def test_scoped_evidence_item_denies_another_org(test_db):
    from modules.evidence.routes import _scoped_evidence_item

    org_a = _org(test_db, "evidence-scope-org-a")
    org_b = _org(test_db, "evidence-scope-org-b")
    uid = _user(test_db, "evidence_scope_uploader", org_a)
    eid = _evidence(test_db, uid, org_id=org_a)

    other_org_user = {"is_super_admin": False, "org_id": org_b}
    assert _scoped_evidence_item(test_db, eid, other_org_user) is None


def test_scoped_evidence_item_allows_the_owning_org(test_db):
    from modules.evidence.routes import _scoped_evidence_item

    org_a = _org(test_db, "evidence-scope-org-c")
    uid = _user(test_db, "evidence_scope_uploader2", org_a)
    eid = _evidence(test_db, uid, org_id=org_a)

    same_org_user = {"is_super_admin": False, "org_id": org_a}
    row = _scoped_evidence_item(test_db, eid, same_org_user)
    assert row is not None
    assert row["id"] == eid


def test_scoped_evidence_item_allows_super_admin_across_any_org(test_db):
    from modules.evidence.routes import _scoped_evidence_item

    org_a = _org(test_db, "evidence-scope-org-d")
    uid = _user(test_db, "evidence_scope_uploader3", org_a)
    eid = _evidence(test_db, uid, org_id=org_a)

    super_admin = {"is_super_admin": True, "org_id": None}
    row = _scoped_evidence_item(test_db, eid, super_admin)
    assert row is not None
    assert row["id"] == eid


def test_scoped_evidence_item_denies_null_org_row_for_ordinary_user(test_db):
    """NULL org_id (pre-migration/orphaned-uploader row) must be invisible
    to an ordinary org user, never treated as a shared/global row -- unlike
    erm_risk_library, evidence has no such concept."""
    from modules.evidence.routes import _scoped_evidence_item

    eid = _evidence(test_db, uploaded_by=None, org_id=None)
    ordinary_user = {"is_super_admin": False, "org_id": 1}
    assert _scoped_evidence_item(test_db, eid, ordinary_user) is None
