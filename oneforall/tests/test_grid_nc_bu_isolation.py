"""
PLAN-36 T08 finding F16 (2026-09-30): grid_non_conformances was unscoped
whenever GET /grid/api/ncs was called without a specific audit_id (an
optional query parameter) -- list/get/update/delete all reachable by
grid.nc.manage with no BU filter.

Unlike bcm_incidents/sentinel_dsr (also F16), this table needed no new
column and no backfill: audit_id is a required, NOT NULL foreign key to
grid_audits, which already has its own business_unit_id (added for T-work
elsewhere in this plan) and its own bu_scope_ids()-scoped listing. The fix
scopes non-conformances through their parent audit's business_unit_id via
the join the query already had (for audit_name display), so every existing
and future row is correctly scoped with zero backfill risk.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.grid import data_service as ds


def _bu(test_db, name):
    test_db.execute("INSERT INTO business_units (name, is_active) VALUES (%s,1)", (name,))
    test_db.commit()
    return test_db.execute(
        "SELECT id FROM business_units WHERE name=%s", (name,)
    ).fetchone()["id"]


def _audit(test_db, name, bu_id):
    test_db.execute(
        "INSERT INTO grid_audits (name, business_unit_id) VALUES (%s,%s)", (name, bu_id)
    )
    test_db.commit()
    return test_db.execute(
        "SELECT id FROM grid_audits WHERE name=%s", (name,)
    ).fetchone()["id"]


def test_get_nc_denies_another_business_unit(test_db):
    """Red proof (temporarily short-circuiting get_nc's bu_scope check to
    always `return nc`): this assertion fails with a real row instead of
    None."""
    finance = _bu(test_db, "Finance NC Isolation")
    legal = _bu(test_db, "Legal NC Isolation")
    audit_id = _audit(test_db, "Finance Audit", finance)
    ncid = ds.create_nc({"audit_id": audit_id, "title": "Finance NC"})

    assert ds.get_nc(ncid, bu_scope=[legal]) is None


def test_get_nc_allows_the_owning_business_unit(test_db):
    finance = _bu(test_db, "Finance NC Isolation 2")
    audit_id = _audit(test_db, "Finance Audit 2", finance)
    ncid = ds.create_nc({"audit_id": audit_id, "title": "Finance NC 2"})

    row = ds.get_nc(ncid, bu_scope=[finance])
    assert row is not None
    assert row["id"] == ncid


def test_list_ncs_excludes_another_business_units_row(test_db):
    finance = _bu(test_db, "Finance NC Isolation 3")
    legal = _bu(test_db, "Legal NC Isolation 3")
    finance_audit = _audit(test_db, "Finance Audit 3", finance)
    legal_audit = _audit(test_db, "Legal Audit 3", legal)
    ds.create_nc({"audit_id": finance_audit, "title": "Finance-Only NC"})
    ds.create_nc({"audit_id": legal_audit, "title": "Legal-Only NC"})

    titles = [r["title"] for r in ds.list_ncs(bu_scope=[finance])]
    assert "Finance-Only NC" in titles
    assert "Legal-Only NC" not in titles


def test_update_nc_refuses_another_business_unit(test_db):
    """Red proof (temporarily removing update_nc's bu_scope guard): this
    assertion fails because the title actually changed."""
    finance = _bu(test_db, "Finance NC Isolation 4")
    legal = _bu(test_db, "Legal NC Isolation 4")
    audit_id = _audit(test_db, "Finance Audit 4", finance)
    ncid = ds.create_nc({"audit_id": audit_id, "title": "Original Title"})

    result = ds.update_nc(ncid, {"title": "Hijacked"}, bu_scope=[legal])
    assert result is False

    row = ds.get_nc(ncid, bu_scope=None)
    assert row["title"] == "Original Title", "the title changed despite the denial"


def test_delete_nc_refuses_another_business_unit(test_db):
    finance = _bu(test_db, "Finance NC Isolation 5")
    legal = _bu(test_db, "Legal NC Isolation 5")
    audit_id = _audit(test_db, "Finance Audit 5", finance)
    ncid = ds.create_nc({"audit_id": audit_id, "title": "Do Not Delete Me"})

    result = ds.delete_nc(ncid, bu_scope=[legal])
    assert result is False

    row = ds.get_nc(ncid, bu_scope=None)
    assert row is not None, "the row was deleted despite the denial"
