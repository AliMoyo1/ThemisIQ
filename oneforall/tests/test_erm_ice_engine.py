"""
Tests for PLAN-23: ERM Contributing Factors + ICE Scoring Engine.

Covers the 4-tier residual precedence ladder (ICE > manual override >
T1.3 auto-effectiveness > default = IRR), frozen IRR, contributing-factor
ref management, and score-history snapshotting.

Uses the standard conftest test_db fixture (fresh SQLite per test).
"""
import sys
import os
import re
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _create_control(db, title="Test Control"):
    db.execute(
        "INSERT INTO canonical_controls (title, automation) VALUES (%s, 'manual')",
        (title,),
    )
    db.commit()
    row = db.execute(
        "SELECT id FROM canonical_controls WHERE title=%s ORDER BY id DESC LIMIT 1",
        (title,),
    ).fetchone()
    return row["id"]


def test_create_risk_default_path(test_db):
    """A freshly created risk with no controls gets the default-path
    values: rrr and residual_score equal IRR, and exactly one history row."""
    from modules.erm.data_service import create_enterprise_risk, get_enterprise_risk

    rid = create_enterprise_risk({"title": "Vendor Outage", "likelihood": 4, "impact": 5})
    risk = get_enterprise_risk(rid)

    assert risk["irr_score"] == 20
    assert re.match(r"^RSK-\d{4}$", risk["risk_ref"])
    assert risk["rrr"] == 20.0
    assert risk["residual_score"] == 20

    hist = test_db.execute(
        "SELECT COUNT(*) AS c FROM erm_risk_score_history WHERE risk_id=%s", (rid,)
    ).fetchone()
    assert hist["c"] == 1


def test_ice_two_controls_worked_example(test_db):
    """Worked example from the plan: L4xI5 gives IRR 20. Two controls
    scored ICE 70 and 90 give LoA 80, RRR 4.0, residual_score 4, and
    EMV-r 100000 with EMV-i 500000."""
    from modules.erm.data_service import (
        create_enterprise_risk, link_risk_control, set_control_assessment,
    )

    rid = create_enterprise_risk({
        "title": "Worked Example", "likelihood": 4, "impact": 5, "emv_inherent": 500000,
    })
    c1 = _create_control(test_db, "Control A")
    c2 = _create_control(test_db, "Control B")
    link_risk_control(rid, c1, 1)
    link_risk_control(rid, c2, 1)

    set_control_assessment(rid, c1, 70, None)
    risk = set_control_assessment(rid, c2, 90, None)

    assert risk["loa_pct"] == 80
    assert risk["rrr"] == 4.0
    assert risk["residual_score"] == 4
    assert risk["emv_residual"] == 100000


def test_ice_zero_counts_as_scored(test_db):
    """ICE 0 is a real score and is falsy in Python — a control scored at
    ICE 0 must be treated as scored (loa_pct 0, not 'unscored')."""
    from modules.erm.data_service import (
        create_enterprise_risk, link_risk_control, set_control_assessment, _ice_rollup,
    )

    rid = create_enterprise_risk({"title": "Zero ICE", "likelihood": 3, "impact": 3})
    c1 = _create_control(test_db, "Weak Control")
    link_risk_control(rid, c1, 1)
    risk = set_control_assessment(rid, c1, 0, None)

    assert risk["loa_pct"] == 0
    assert risk["rrr"] == float(risk["irr_score"])

    # Directly assert the rollup treats ICE 0 as scored, not falsy-skipped.
    ice = _ice_rollup(test_db, rid)
    assert ice["scored"] is True
    assert ice["loa_pct"] == 0
    assert ice["lor"] == 1.0


def test_ice_score_validation(test_db):
    """ICE must be None or one of ICE_ALLOWED; anything else raises
    ValueError. Clearing ICE (None) falls through to the default path."""
    from modules.erm.data_service import (
        create_enterprise_risk, link_risk_control, set_control_assessment,
    )

    rid = create_enterprise_risk({"title": "Validation Risk", "likelihood": 3, "impact": 3})
    c1 = _create_control(test_db, "Validated Control")
    link_risk_control(rid, c1, 1)

    with pytest.raises(ValueError):
        set_control_assessment(rid, c1, 45, None)

    risk = set_control_assessment(rid, c1, 90, None)
    assert risk["loa_pct"] == 90

    risk = set_control_assessment(rid, c1, None, None)
    assert risk["loa_pct"] == 0
    assert risk["rrr"] == float(risk["irr_score"])


def test_irr_frozen_on_update(test_db):
    """IRR is set once at creation and never changes, even via a direct
    PUT-style payload or subsequent likelihood/impact edits — while
    inherent_score keeps tracking current L x I."""
    from modules.erm.data_service import (
        create_enterprise_risk, update_enterprise_risk, get_enterprise_risk,
    )

    rid = create_enterprise_risk({"title": "Frozen IRR", "likelihood": 4, "impact": 5})
    assert get_enterprise_risk(rid)["irr_score"] == 20

    update_enterprise_risk(rid, {"likelihood": 1})
    risk = get_enterprise_risk(rid)
    assert risk["irr_score"] == 20
    assert risk["inherent_score"] == 1 * 5

    update_enterprise_risk(rid, {"irr_score": 1})
    assert get_enterprise_risk(rid)["irr_score"] == 20


def test_manual_override_then_ice_flip(test_db):
    """With no ICE anywhere, a manual residual override drives the
    residual. Once any control gets an ICE score, the ICE path takes over
    and the override is ignored."""
    from modules.erm.data_service import (
        create_enterprise_risk, update_enterprise_risk, get_enterprise_risk,
        link_risk_control, set_control_assessment,
    )

    rid = create_enterprise_risk({"title": "Override Risk", "likelihood": 4, "impact": 4})
    update_enterprise_risk(rid, {"residual_likelihood": 2, "residual_impact": 3})
    risk = get_enterprise_risk(rid)
    assert risk["residual_score"] == 6
    assert risk["rrr"] == 6.0
    assert risk["loa_pct"] is None

    c1 = _create_control(test_db, "Flip Control")
    link_risk_control(rid, c1, 1)
    risk = set_control_assessment(rid, c1, 70, None)
    assert risk["loa_pct"] == 70
    assert risk["rrr"] == round((100 - 70) / 100.0 * risk["irr_score"], 1)


def test_contributing_factors_ref_management(test_db):
    """CF refs derive from MAX existing suffix + 1, never COUNT + 1: after
    deleting CF001, the next new CF must be CF003, not a reused CF002.
    Deleting a CF also clears risk_controls.cf_id for controls that
    referenced it."""
    from modules.erm.data_service import (
        create_enterprise_risk, update_enterprise_risk, get_enterprise_risk,
        link_risk_control,
    )

    rid = create_enterprise_risk({
        "title": "CF Risk", "likelihood": 3, "impact": 3,
        "contributing_factors": [{"description": "Root cause A"}, {"description": "Root cause B"}],
    })
    risk = get_enterprise_risk(rid)
    cfs = sorted(risk["contributing_factors"], key=lambda c: c["cf_ref"])
    assert [c["cf_ref"] for c in cfs] == ["CF001", "CF002"]
    cf1_id, cf2_id = cfs[0]["id"], cfs[1]["id"]

    ctrl_id = _create_control(test_db, "CF Control")
    link_risk_control(rid, ctrl_id, 1, cf_id=cf1_id)

    # Omit CF001 from the submitted list: deleted. CF002 survives unchanged.
    update_enterprise_risk(rid, {
        "contributing_factors": [
            {"id": cf2_id, "description": "Root cause B"},
            {"description": "Root cause C"},
        ],
    })
    risk = get_enterprise_risk(rid)
    refs = sorted(c["cf_ref"] for c in risk["contributing_factors"])
    assert refs == ["CF002", "CF003"]

    row = test_db.execute(
        "SELECT cf_id FROM risk_controls WHERE risk_id=%s AND control_id=%s",
        (rid, ctrl_id),
    ).fetchone()
    assert row["cf_id"] is None


def test_set_control_assessment_rejects_foreign_cf(test_db):
    """set_control_assessment must reject a cf_id belonging to a
    different risk."""
    from modules.erm.data_service import (
        create_enterprise_risk, get_enterprise_risk, link_risk_control, set_control_assessment,
    )

    rid1 = create_enterprise_risk({
        "title": "Risk One", "likelihood": 3, "impact": 3,
        "contributing_factors": [{"description": "Cause X"}],
    })
    rid2 = create_enterprise_risk({"title": "Risk Two", "likelihood": 3, "impact": 3})
    foreign_cf_id = get_enterprise_risk(rid1)["contributing_factors"][0]["id"]

    ctrl_id = _create_control(test_db, "Cross-Risk Control")
    link_risk_control(rid2, ctrl_id, 1)

    with pytest.raises(ValueError):
        set_control_assessment(rid2, ctrl_id, 50, foreign_cf_id)


def test_delete_risk_cascades_cfs_and_history(test_db):
    """Deleting a risk removes its contributing factors and score-history
    rows alongside the existing cleanup deletes."""
    from modules.erm.data_service import create_enterprise_risk, delete_enterprise_risk

    rid = create_enterprise_risk({
        "title": "Doomed Risk", "likelihood": 3, "impact": 3,
        "contributing_factors": [{"description": "Cause Y"}],
    })
    delete_enterprise_risk(rid)

    cf_count = test_db.execute(
        "SELECT COUNT(*) AS c FROM erm_contributing_factors WHERE risk_id=%s", (rid,)
    ).fetchone()["c"]
    hist_count = test_db.execute(
        "SELECT COUNT(*) AS c FROM erm_risk_score_history WHERE risk_id=%s", (rid,)
    ).fetchone()["c"]
    assert cf_count == 0
    assert hist_count == 0


def test_history_snapshot_dedup(test_db):
    """Repeated recompute with an unchanged rrr adds no new history row;
    an actual ICE change adds exactly one."""
    from modules.erm.data_service import (
        create_enterprise_risk, link_risk_control, set_control_assessment,
        recompute_residual_for_risk,
    )
    from database import get_db

    rid = create_enterprise_risk({"title": "History Risk", "likelihood": 3, "impact": 4})
    count_after_create = test_db.execute(
        "SELECT COUNT(*) AS c FROM erm_risk_score_history WHERE risk_id=%s", (rid,)
    ).fetchone()["c"]
    assert count_after_create == 1

    db = get_db()
    try:
        recompute_residual_for_risk(db, rid)
        db.commit()
    finally:
        db.close()
    count_unchanged = test_db.execute(
        "SELECT COUNT(*) AS c FROM erm_risk_score_history WHERE risk_id=%s", (rid,)
    ).fetchone()["c"]
    assert count_unchanged == count_after_create

    ctrl_id = _create_control(test_db, "History Control")
    link_risk_control(rid, ctrl_id, 1)
    set_control_assessment(rid, ctrl_id, 60, None)
    count_after_ice = test_db.execute(
        "SELECT COUNT(*) AS c FROM erm_risk_score_history WHERE risk_id=%s", (rid,)
    ).fetchone()["c"]
    assert count_after_ice == count_after_create + 1
