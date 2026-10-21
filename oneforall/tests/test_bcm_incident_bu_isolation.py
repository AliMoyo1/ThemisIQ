"""
PLAN-36 T08 finding F16 (2026-09-30, found while checking whether P01 could
safely build on existing dashboard queries): bcm_incidents had no
business_unit_id column at all. list/get/update/delete and the CSV export
all queried by plain id with no BU filter, reachable by module.bcm.access,
which EMPLOYEE holds -- any authenticated user with BCM access, in any
business unit, could read or destroy any other business unit's incidents.

No backfill exists for this one (unlike evidence_items' uploaded_by or
webhooks' created_by): commander/assigned_to are free-text names, not user
FKs, so there's no reliable column to derive a business_unit_id from for
pre-existing rows. This file tests the two backend pieces of the fix
directly (no browser, no live_app), same style as
test_evidence_org_isolation.py.

HTTP-level cross-BU proof (a real create by one BU, a real denied
list/get/update/delete attempt by another) would need a live_app fixture
with two distinct business units under the same org, which
tests/ui/conftest.py's synthetic_tenant does not build (its 11 personas
share one BU). Left as a named gap rather than built with a heavier new
fixture, given the two service-level tests below already exercise the same
`get_incident`/`list_incidents` fail-closed logic the routes call directly.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.bcm import data_service as ds


def _bu(test_db, name):
    test_db.execute("INSERT INTO business_units (name, is_active) VALUES (%s,1)", (name,))
    test_db.commit()
    return test_db.execute(
        "SELECT id FROM business_units WHERE name=%s", (name,)
    ).fetchone()["id"]


def test_get_incident_denies_another_business_unit(test_db):
    """Red proof (temporarily short-circuiting get_incident's bu_scope check
    to always `return row`): this assertion fails with a real row instead
    of None."""
    finance = _bu(test_db, "Finance BCM Isolation")
    legal = _bu(test_db, "Legal BCM Isolation")
    iid = ds.create_incident({"title": "Finance Incident", "business_unit_id": finance})

    assert ds.get_incident(iid, bu_scope=[legal]) is None


def test_get_incident_allows_the_owning_business_unit(test_db):
    finance = _bu(test_db, "Finance BCM Isolation 2")
    iid = ds.create_incident({"title": "Finance Incident 2", "business_unit_id": finance})

    row = ds.get_incident(iid, bu_scope=[finance])
    assert row is not None
    assert row["id"] == iid


def test_get_incident_unscoped_super_admin_sees_everything(test_db):
    """bu_scope=None (bu_scope_ids() returns None only for a super admin) --
    same convention as every other bu_scope_ids() consumer in this codebase."""
    finance = _bu(test_db, "Finance BCM Isolation 3")
    iid = ds.create_incident({"title": "Finance Incident 3", "business_unit_id": finance})

    row = ds.get_incident(iid, bu_scope=None)
    assert row is not None


def test_list_incidents_excludes_another_business_units_row(test_db):
    finance = _bu(test_db, "Finance BCM Isolation 4")
    legal = _bu(test_db, "Legal BCM Isolation 4")
    ds.create_incident({"title": "Finance-Only Incident", "business_unit_id": finance})
    ds.create_incident({"title": "Legal-Only Incident", "business_unit_id": legal})

    titles = [r["title"] for r in ds.list_incidents(bu_scope=[finance])]
    assert "Finance-Only Incident" in titles
    assert "Legal-Only Incident" not in titles


def test_update_incident_refuses_another_business_unit(test_db):
    """Red proof (temporarily removing update_incident's bu_scope guard):
    this assertion fails because the title actually changed."""
    finance = _bu(test_db, "Finance BCM Isolation 5")
    legal = _bu(test_db, "Legal BCM Isolation 5")
    iid = ds.create_incident({"title": "Original Title", "business_unit_id": finance})

    result = ds.update_incident(iid, {"title": "Hijacked"}, bu_scope=[legal])
    assert result is False

    row = ds.get_incident(iid, bu_scope=None)
    assert row["title"] == "Original Title", "the title changed despite the denial"


def test_delete_incident_refuses_another_business_unit(test_db):
    finance = _bu(test_db, "Finance BCM Isolation 6")
    legal = _bu(test_db, "Legal BCM Isolation 6")
    iid = ds.create_incident({"title": "Do Not Delete Me", "business_unit_id": finance})

    result = ds.delete_incident(iid, bu_scope=[legal])
    assert result is False

    row = ds.get_incident(iid, bu_scope=None)
    assert row is not None, "the row was deleted despite the denial"
