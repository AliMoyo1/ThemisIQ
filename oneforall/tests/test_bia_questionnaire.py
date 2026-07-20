"""
Tests for PLAN-22: BIA questionnaire engine in BCM.

Covers the 5 cases scoped in plans/PLAN-22-active.md Step 5: default row
seeding, the suggest_rto threshold logic, resource CRUD + SPOF flag
persistence, delete_bia cascading its children, and bucket-label
validation.

Uses the standard conftest test_db fixture (fresh SQLite per test).
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_create_bia_seeds_10_default_impact_rows(test_db):
    """A freshly created BIA gets exactly 10 default impact rows: 5
    general (scored 1-3) + 5 financial (money amounts), in that order."""
    from modules.bcm.data_service import create_bia, get_bia

    bid = create_bia({"process_name": "Payroll Processing"})
    bia = get_bia(bid)

    rows = bia["impact_rows"]
    assert len(rows) == 10
    general = [r for r in rows if r["section"] == "general"]
    financial = [r for r in rows if r["section"] == "financial"]
    assert len(general) == 5
    assert len(financial) == 5
    assert general[0]["label"] == "Loss of reputation on the market"
    assert financial[0]["label"] == "Legal penalties"


def test_suggest_rto_threshold_logic(test_db):
    """suggest_rto finds the earliest bucket (in b1..b5 order) where ANY
    general row scores >= 3 (high). No row ever reaching 3 -> None.
    Financial rows are never consulted, even if their money amount is a
    huge number that happens to be >= 3."""
    from modules.bcm.data_service import suggest_rto

    all_low = [{"section": "general", "b1": 1, "b2": 2, "b3": 2, "b4": 2, "b5": 2}]
    assert suggest_rto(all_low) is None

    high_at_b3 = [{"section": "general", "b1": 1, "b2": 2, "b3": 3, "b4": 3, "b5": 3}]
    assert suggest_rto(high_at_b3) == 24

    two_rows_earliest_high_at_b1 = [
        {"section": "general", "b1": 1, "b2": 1, "b3": 1, "b4": 1, "b5": 1},
        {"section": "general", "b1": 3, "b2": 3, "b3": 3, "b4": 3, "b5": 3},
    ]
    assert suggest_rto(two_rows_earliest_high_at_b1) == 2

    # Financial rows must never trigger the threshold even though their
    # money values dwarf 3.
    financial_only = [{"section": "financial", "b1": 500000, "b2": 500000,
                        "b3": 500000, "b4": 500000, "b5": 500000}]
    assert suggest_rto(financial_only) is None


def test_save_bia_impact_rows_updates_suggested_rto(test_db):
    """Saving impact rows recomputes and stores suggested_rto_hours on
    the parent BIA record, without ever touching the user-owned
    rto_hours field."""
    from modules.bcm.data_service import create_bia, update_bia, save_bia_impact_rows, get_bia

    bid = create_bia({"process_name": "Order Fulfilment"})
    update_bia(bid, {"rto_hours": 12})

    save_bia_impact_rows(bid, [
        {"section": "general", "label": "Loss of reputation on the market", "b1": 1, "b3": 3},
        {"section": "financial", "label": "Legal penalties", "b1": 250000},
    ])

    bia = get_bia(bid)
    assert bia["suggested_rto_hours"] == 24
    assert bia["rto_hours"] == 12
    assert len(bia["impact_rows"]) == 2

    financial_row = next(r for r in bia["impact_rows"] if r["section"] == "financial")
    assert financial_row["b1"] == 250000.0


def test_resource_crud_and_spof_persistence(test_db):
    """Resources are row-CRUD (not delete-and-reinsert like impact rows)
    so ids survive mid-edit. The single_point_of_failure flag round-trips
    correctly, including as a real boolean-ish value from a JSON body."""
    from modules.bcm.data_service import (
        create_bia, create_bia_resource, update_bia_resource, delete_bia_resource, get_bia,
    )

    bid = create_bia({"process_name": "Data Centre Ops"})
    rid = create_bia_resource(bid, {
        "category": "IT and communications equipment", "name": "Primary DB server",
        "single_point_of_failure": True, "needed_after": "immediately",
    })

    bia = get_bia(bid)
    resource = next(r for r in bia["resources"] if r["id"] == rid)
    assert resource["single_point_of_failure"] == 1
    assert resource["needed_after"] == "immediately"

    update_bia_resource(rid, {"needed_after": "4h", "single_point_of_failure": False})
    bia = get_bia(bid)
    resource = next(r for r in bia["resources"] if r["id"] == rid)
    assert resource["needed_after"] == "4h"
    assert resource["single_point_of_failure"] == 0

    with pytest.raises(ValueError):
        create_bia_resource(bid, {"name": "Bad resource", "needed_after": "not-a-real-bucket"})

    delete_bia_resource(rid)
    bia = get_bia(bid)
    assert bia["resources"] == []


def test_delete_bia_cascades_children(test_db):
    """Deleting a BIA removes its impact rows and resources (explicit
    child deletes, matching this module's existing convention rather
    than relying solely on ON DELETE CASCADE)."""
    from modules.bcm.data_service import create_bia, create_bia_resource, delete_bia

    bid = create_bia({"process_name": "Doomed Process"})
    create_bia_resource(bid, {"category": "People", "name": "On-call engineer"})
    delete_bia(bid)

    rows = test_db.execute(
        "SELECT COUNT(*) c FROM bcm_bia_impact_rows WHERE bia_id=%s", (bid,)
    ).fetchone()["c"]
    resources = test_db.execute(
        "SELECT COUNT(*) c FROM bcm_bia_resources WHERE bia_id=%s", (bid,)
    ).fetchone()["c"]
    assert rows == 0
    assert resources == 0


def test_seed_standard_rows_if_empty_is_idempotent(test_db):
    """Legacy BIAs (created before this plan) have zero impact rows --
    found via live verification that this path had no automated test.
    seed_standard_rows_if_empty seeds the 10 defaults exactly once and
    reports whether it actually seeded, so a second call on an
    already-populated BIA is a safe no-op rather than a duplicate insert."""
    from modules.bcm.data_service import create_bia, seed_standard_rows_if_empty
    from database import get_db

    bid = create_bia({"process_name": "Legacy Process"})
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_bia_impact_rows WHERE bia_id=%s", (bid,))
        db.commit()
    finally:
        db.close()

    seeded_first = seed_standard_rows_if_empty(bid)
    count_after_first = test_db.execute(
        "SELECT COUNT(*) c FROM bcm_bia_impact_rows WHERE bia_id=%s", (bid,)
    ).fetchone()["c"]
    seeded_second = seed_standard_rows_if_empty(bid)
    count_after_second = test_db.execute(
        "SELECT COUNT(*) c FROM bcm_bia_impact_rows WHERE bia_id=%s", (bid,)
    ).fetchone()["c"]

    assert seeded_first is True
    assert count_after_first == 10
    assert seeded_second is False
    assert count_after_second == 10


def test_bucket_labels_validation_and_persistence(test_db):
    """Bucket labels apply platform-wide (a settings key), not per-BIA.
    Exactly 5 non-empty labels are required; a get before any set
    returns the seeded default."""
    from modules.bcm.data_service import get_bucket_labels, set_bucket_labels

    assert get_bucket_labels() == ["2 hours", "4 hours", "24 hours", "48 hours", "1 week"]

    with pytest.raises(ValueError):
        set_bucket_labels(["2 hours", "4 hours", "24 hours", "48 hours"])  # only 4

    with pytest.raises(ValueError):
        set_bucket_labels(["2 hours", "", "24 hours", "48 hours", "1 week"])  # blank label

    set_bucket_labels(["30 min", "2 hours", "1 day", "2 days", "5 days"])
    assert get_bucket_labels() == ["30 min", "2 hours", "1 day", "2 days", "5 days"]
