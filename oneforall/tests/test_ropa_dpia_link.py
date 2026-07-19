"""
Tests for RoPA/DPIA bidirectional link: create_dpia_from_ropa via spawn endpoint
logic, link_dpia_to_ropa backfill, and delete_dpia cleanup.

Uses the standard conftest test_db fixture (fresh SQLite per test).
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _create_ropa(db, name="Test Activity", purpose="Test purpose",
                 department="IT", legal_basis="Legitimate Interest",
                 special_categories='["Health data"]',
                 data_categories='["Contact data"]',
                 retention_period="7 years"):
    db.execute(
        "INSERT INTO sentinel_ropa "
        "(ref_number, processing_name, department, purpose, legal_basis, "
        " special_categories, data_categories, retention_period, regulation, "
        " status, risk_level, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,datetime('now'),datetime('now'))",
        (f"ROPA-TEST-{name[:5]}", name, department, purpose, legal_basis,
         special_categories, data_categories, retention_period,
         "GDPR", "active", "low"),
    )
    db.commit()
    row = db.execute(
        "SELECT id FROM sentinel_ropa WHERE processing_name=%s ORDER BY id DESC LIMIT 1",
        (name,),
    ).fetchone()
    return row["id"]


def _create_dpia(db, title="Test DPIA", ropa_id=None):
    from modules.sentinel.data_service import create_dpia
    data = {"title": title, "status": "draft", "regulation": "GDPR"}
    if ropa_id is not None:
        data["ropa_id"] = ropa_id
    return create_dpia(data)


def test_spawn_dpia_prefills_and_links(test_db):
    """create_dpia called with ropa_id populates DPIA correctly and links both records."""
    from modules.sentinel.data_service import create_dpia, get_dpia, get_ropa

    ropa_id = _create_ropa(test_db, name="Customer Analytics")
    ropa = get_ropa(ropa_id)

    dpia_data = {
        "title": f"DPIA: {ropa['processing_name']}",
        "status": "draft",
        "regulation": ropa.get("regulation", "GDPR"),
        "purpose": ropa.get("purpose", ""),
        "legal_basis": ropa.get("legal_basis", ""),
        "data_categories": ropa.get("data_categories", []),
        "special_cats": ropa.get("special_categories", []),
        "department": ropa.get("department", ""),
        "retention": ropa.get("retention_period", ""),
        "ropa_id": ropa_id,
    }
    dpia_id = create_dpia(dpia_data)

    # Update ropa.dpia_id to simulate what spawn-dpia endpoint does
    test_db.execute(
        "UPDATE sentinel_ropa SET dpia_id=%s WHERE id=%s", (dpia_id, ropa_id)
    )
    test_db.commit()

    dpia = get_dpia(dpia_id)
    assert dpia is not None
    assert dpia["ropa_id"] == ropa_id
    assert dpia["title"] == "DPIA: Customer Analytics"
    assert dpia["legal_basis"] == ropa["legal_basis"]
    assert dpia["department"] == "IT"
    assert dpia["retention"] == "7 years"

    ropa_after = get_ropa(ropa_id)
    assert ropa_after["dpia_id"] == dpia_id

    # ropa_ref and ropa_name enriched via JOIN in get_dpia
    assert dpia.get("ropa_ref") is not None
    assert dpia.get("ropa_name") == "Customer Analytics"


def test_second_spawn_refused(test_db):
    """link_dpia_to_ropa returns False when the RoPA already has a different dpia_id."""
    from modules.sentinel.data_service import link_dpia_to_ropa

    ropa_id = _create_ropa(test_db, name="Activity B")
    dpia1_id = _create_dpia(test_db, "DPIA 1", ropa_id)
    test_db.execute(
        "UPDATE sentinel_ropa SET dpia_id=%s WHERE id=%s", (dpia1_id, ropa_id)
    )
    test_db.execute(
        "UPDATE sentinel_dpias SET ropa_id=%s WHERE id=%s", (ropa_id, dpia1_id)
    )
    test_db.commit()

    dpia2_id = _create_dpia(test_db, "DPIA 2")
    result = link_dpia_to_ropa(dpia2_id, ropa_id)
    assert result is False


def test_link_dpia_backfills_empty_fields_only(test_db):
    """link_dpia_to_ropa fills NULL/empty DPIA fields but never overwrites non-empty ones."""
    from modules.sentinel.data_service import link_dpia_to_ropa, get_dpia

    ropa_id = _create_ropa(test_db, name="Activity C", department="Finance")

    dpia_id = _create_dpia(test_db, "Pre-existing DPIA Title")
    test_db.execute(
        "UPDATE sentinel_dpias SET department='' WHERE id=%s", (dpia_id,)
    )
    test_db.commit()

    result = link_dpia_to_ropa(dpia_id, ropa_id)
    assert result is True

    dpia = get_dpia(dpia_id)
    assert dpia["title"] == "Pre-existing DPIA Title"
    assert dpia["department"] == "Finance"
    assert dpia["ropa_id"] == ropa_id


def test_delete_dpia_clears_ropa_link(test_db):
    """Deleting a DPIA sets sentinel_ropa.dpia_id = NULL so a new DPIA can be created."""
    from modules.sentinel.data_service import delete_dpia, get_ropa

    ropa_id = _create_ropa(test_db, name="Activity D")
    dpia_id = _create_dpia(test_db, "Linked DPIA", ropa_id)
    test_db.execute(
        "UPDATE sentinel_ropa SET dpia_id=%s WHERE id=%s", (dpia_id, ropa_id)
    )
    test_db.execute(
        "UPDATE sentinel_dpias SET ropa_id=%s WHERE id=%s", (ropa_id, dpia_id)
    )
    test_db.commit()

    delete_dpia(dpia_id)

    ropa = get_ropa(ropa_id)
    assert ropa["dpia_id"] is None


def test_list_dpias_includes_ropa_join_fields(test_db):
    """list_dpias returns ropa_ref and ropa_name for linked DPIAs."""
    from modules.sentinel.data_service import list_dpias, create_dpia

    ropa_id = _create_ropa(test_db, name="Activity E")
    dpia_id = create_dpia({"title": "Linked DPIA E", "ropa_id": ropa_id})
    test_db.execute(
        "UPDATE sentinel_dpias SET ropa_id=%s WHERE id=%s", (ropa_id, dpia_id)
    )
    test_db.commit()

    results = list_dpias()
    linked = next((d for d in results if d["id"] == dpia_id), None)
    assert linked is not None
    assert linked["ropa_name"] == "Activity E"
    assert linked["ropa_ref"] is not None
