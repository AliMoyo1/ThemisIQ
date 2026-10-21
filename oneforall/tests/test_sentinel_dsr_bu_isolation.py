"""
PLAN-36 T08 finding F16 (2026-09-30): sentinel_dsr (GDPR data-subject
requests -- real requester names/emails/request details) had no
business_unit_id column at all. list/get/update/delete, the AI-draft
endpoint, and the audit evidence-pack ZIP export all queried by plain id or
with no filter, reachable by sentinel.dsr.manage (DPO, PRIVACY_ANALYST).

No backfill exists here either: sentinel_dsr has no user-id column to
backfill a business unit from. Same style as
test_bcm_incident_bu_isolation.py and test_evidence_org_isolation.py.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.sentinel import data_service as ds


def _bu(test_db, name):
    test_db.execute("INSERT INTO business_units (name, is_active) VALUES (%s,1)", (name,))
    test_db.commit()
    return test_db.execute(
        "SELECT id FROM business_units WHERE name=%s", (name,)
    ).fetchone()["id"]


def test_get_dsr_denies_another_business_unit(test_db):
    """Red proof (temporarily short-circuiting get_dsr's bu_scope check to
    always `return row`): this assertion fails with a real row instead of
    None."""
    finance = _bu(test_db, "Finance DSR Isolation")
    legal = _bu(test_db, "Legal DSR Isolation")
    did = ds.create_dsr({"requester_name": "Finance Requester", "business_unit_id": finance})

    assert ds.get_dsr(did, bu_scope=[legal]) is None


def test_get_dsr_allows_the_owning_business_unit(test_db):
    finance = _bu(test_db, "Finance DSR Isolation 2")
    did = ds.create_dsr({"requester_name": "Finance Requester 2", "business_unit_id": finance})

    row = ds.get_dsr(did, bu_scope=[finance])
    assert row is not None
    assert row["id"] == did


def test_list_dsrs_excludes_another_business_units_row(test_db):
    finance = _bu(test_db, "Finance DSR Isolation 3")
    legal = _bu(test_db, "Legal DSR Isolation 3")
    ds.create_dsr({"requester_name": "Finance-Only Requester", "business_unit_id": finance})
    ds.create_dsr({"requester_name": "Legal-Only Requester", "business_unit_id": legal})

    names = [r["requester_name"] for r in ds.list_dsrs(bu_scope=[finance])]
    assert "Finance-Only Requester" in names
    assert "Legal-Only Requester" not in names


def test_update_dsr_refuses_another_business_unit(test_db):
    """Red proof (temporarily removing update_dsr's bu_scope guard): this
    assertion fails because the requester_name actually changed."""
    finance = _bu(test_db, "Finance DSR Isolation 4")
    legal = _bu(test_db, "Legal DSR Isolation 4")
    did = ds.create_dsr({"requester_name": "Original Name", "business_unit_id": finance})

    result = ds.update_dsr(did, {"requester_name": "Hijacked"}, bu_scope=[legal])
    assert result is False

    row = ds.get_dsr(did, bu_scope=None)
    assert row["requester_name"] == "Original Name", "the requester_name changed despite the denial"


def test_delete_dsr_refuses_another_business_unit(test_db):
    finance = _bu(test_db, "Finance DSR Isolation 5")
    legal = _bu(test_db, "Legal DSR Isolation 5")
    did = ds.create_dsr({"requester_name": "Do Not Delete Me", "business_unit_id": finance})

    result = ds.delete_dsr(did, bu_scope=[legal])
    assert result is False

    row = ds.get_dsr(did, bu_scope=None)
    assert row is not None, "the row was deleted despite the denial"
