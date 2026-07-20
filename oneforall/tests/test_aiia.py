"""
Tests for PLAN-20: AIIA (AI Impact Assessments in Sentinel).

Covers the create/score round-trip (classification computed via ERM's
resolve_band against the active rating framework, not a hardcoded
cutoff), dimension rename-follows-history, cascade delete, and
dimension deactivation excluding a dimension from new forms while
historical scored rows survive on the record that used it.

Uses the standard conftest test_db fixture -- database.init_db() seeds
both the ERM OmniContact rating framework and the 8 AIIA dimensions, so
these tests exercise the real resolve_band() path, not a stub.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_create_aiia_classification_matches_resolve_band(test_db):
    from modules.sentinel.data_service import create_aiia, get_aiia
    from modules.erm.data_service import get_active_framework_matrix, resolve_band

    aiia_id = create_aiia({
        "title": "Customer churn prediction model",
        "ai_system_name": "ChurnGuard",
        "impacts": [
            {"dimension_name": "Financial", "applicable": 1, "likelihood": 5, "impact": 5},
            {"dimension_name": "Operational", "applicable": 1, "likelihood": 2, "impact": 2},
            {"dimension_name": "Privacy", "applicable": 1, "likelihood": 1, "impact": 1},
        ],
    })
    assert aiia_id > 0

    aiia = get_aiia(aiia_id)
    assert aiia["ref_number"].startswith("AIIA-")

    matrix = get_active_framework_matrix(test_db)
    expected = resolve_band(matrix, 5, 5)
    assert aiia["overall_classification"] == expected

    impacts_by_dim = {i["dimension_name"]: i for i in aiia["impacts"]}
    assert impacts_by_dim["Financial"]["likelihood"] == 5
    assert impacts_by_dim["Financial"]["impact"] == 5


def test_unrated_when_no_active_framework(test_db):
    from modules.sentinel.data_service import create_aiia, get_aiia

    test_db.execute("UPDATE erm_risk_frameworks SET is_active=0")
    test_db.commit()

    aiia_id = create_aiia({
        "title": "No framework active",
        "impacts": [{"dimension_name": "Financial", "applicable": 1, "likelihood": 5, "impact": 5}],
    })
    aiia = get_aiia(aiia_id)
    assert aiia["overall_classification"] == "unrated"


def test_inapplicable_rows_excluded_from_classification(test_db):
    from modules.sentinel.data_service import create_aiia, get_aiia
    from modules.erm.data_service import get_active_framework_matrix, resolve_band

    aiia_id = create_aiia({
        "title": "Applicability test",
        "impacts": [
            {"dimension_name": "Financial", "applicable": 0, "likelihood": 5, "impact": 5},
            {"dimension_name": "Operational", "applicable": 1, "likelihood": 2, "impact": 2},
        ],
    })
    aiia = get_aiia(aiia_id)
    matrix = get_active_framework_matrix(test_db)
    expected = resolve_band(matrix, 2, 2)
    assert aiia["overall_classification"] == expected

    impacts_by_dim = {i["dimension_name"]: i for i in aiia["impacts"]}
    assert impacts_by_dim["Financial"]["likelihood"] == 5
    assert impacts_by_dim["Financial"]["applicable"] == 0


def test_rename_dimension_history_follows(test_db):
    from modules.sentinel.data_service import (
        create_aiia, get_aiia, list_aiia_dimensions, save_aiia_dimensions,
    )

    aiia_id = create_aiia({
        "title": "Security scoring test",
        "impacts": [{"dimension_name": "Security", "applicable": 1, "likelihood": 4, "impact": 3}],
    })

    dims = {d["name"]: d for d in list_aiia_dimensions()}
    security_id = dims["Security"]["id"]

    save_aiia_dimensions([{
        "id": security_id, "name": "InfoSec", "order_idx": dims["Security"]["order_idx"],
        "is_active": True,
    }])

    aiia = get_aiia(aiia_id)
    impacts_by_dim = {i["dimension_name"]: i for i in aiia["impacts"]}
    assert "InfoSec" in impacts_by_dim
    assert impacts_by_dim["InfoSec"]["likelihood"] == 4
    assert impacts_by_dim["InfoSec"]["impact"] == 3
    assert "Security" not in impacts_by_dim


def test_rename_collision_rejected(test_db):
    from modules.sentinel.data_service import list_aiia_dimensions, save_aiia_dimensions

    dims = {d["name"]: d for d in list_aiia_dimensions()}
    security_id = dims["Security"]["id"]

    try:
        save_aiia_dimensions([{
            "id": security_id, "name": "Privacy", "order_idx": dims["Security"]["order_idx"],
            "is_active": True,
        }])
        assert False, "expected a ValueError on name collision"
    except ValueError:
        pass

    dims_after = {d["name"]: d for d in list_aiia_dimensions()}
    assert "Security" in dims_after
    assert dims_after["Privacy"]["id"] != security_id


def test_delete_aiia_cascades_impacts(test_db):
    from modules.sentinel.data_service import create_aiia, delete_aiia

    aiia_id = create_aiia({
        "title": "Cascade delete test",
        "impacts": [{"dimension_name": "Financial", "applicable": 1, "likelihood": 3, "impact": 3}],
    })
    remaining = test_db.execute(
        "SELECT COUNT(*) c FROM sentinel_aiia_impacts WHERE aiia_id=%s", (aiia_id,)
    ).fetchone()["c"]
    assert remaining == 1

    delete_aiia(aiia_id)

    remaining = test_db.execute(
        "SELECT COUNT(*) c FROM sentinel_aiia_impacts WHERE aiia_id=%s", (aiia_id,)
    ).fetchone()["c"]
    assert remaining == 0
    assert test_db.execute(
        "SELECT COUNT(*) c FROM sentinel_aiia WHERE id=%s", (aiia_id,)
    ).fetchone()["c"] == 0


def test_deactivate_excludes_from_new_forms_but_history_survives(test_db):
    from modules.sentinel.data_service import (
        create_aiia, get_aiia, list_aiia_dimensions, save_aiia_dimensions,
    )

    aiia_id = create_aiia({
        "title": "Deactivation history test",
        "impacts": [{"dimension_name": "Societal", "applicable": 1, "likelihood": 3, "impact": 4}],
    })

    dims = {d["name"]: d for d in list_aiia_dimensions()}
    societal = dims["Societal"]
    save_aiia_dimensions([{
        "id": societal["id"], "name": "Societal", "order_idx": societal["order_idx"],
        "is_active": False,
    }])

    active_only = [d["name"] for d in list_aiia_dimensions(include_inactive=False)]
    assert "Societal" not in active_only

    aiia = get_aiia(aiia_id)
    impacts_by_dim = {i["dimension_name"]: i for i in aiia["impacts"]}
    assert "Societal" in impacts_by_dim
    assert impacts_by_dim["Societal"]["likelihood"] == 3
    assert impacts_by_dim["Societal"]["impact"] == 4
