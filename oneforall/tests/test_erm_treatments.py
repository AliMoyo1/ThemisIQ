"""
Tests for PLAN-25: ERM Per-CF Treatments.

Covers auto-created TR refs paired with CF refs, the Accept-at-70%-assurance
suggestion rule, validation on update_treatment, the accept-below-70 warning,
EMV-a totals, and idempotent treatment creation.

Uses the standard conftest test_db fixture (fresh SQLite per test).
"""
import sys
import os
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


def test_ensure_treatments_creates_one_per_cf(test_db):
    """A risk with 2 CFs and no ICE scoring anywhere gets TR001 + TR002,
    both status 'open' and defaulting to treatment_option 'mitigate'."""
    from modules.erm.data_service import create_enterprise_risk, list_treatments

    rid = create_enterprise_risk({
        "title": "Two CF Risk", "likelihood": 3, "impact": 3,
        "contributing_factors": [{"description": "Cause A"}, {"description": "Cause B"}],
    })
    treatments = list_treatments(rid)
    assert len(treatments) == 2
    assert sorted(t["tr_ref"] for t in treatments) == ["TR001", "TR002"]
    for t in treatments:
        assert t["status"] == "open"
        assert t["treatment_option"] == "mitigate"


def test_accept_suggestion_at_70_assurance(test_db):
    """A CF whose only control is scored ICE 70 gets an auto-created
    treatment with option 'accept'; a CF scored at 60 stays 'mitigate'."""
    from modules.erm.data_service import (
        create_enterprise_risk, get_enterprise_risk, link_risk_control,
        set_control_assessment, list_treatments,
    )

    rid = create_enterprise_risk({
        "title": "Assurance Risk", "likelihood": 3, "impact": 3,
        "contributing_factors": [{"description": "Cause A"}, {"description": "Cause B"}],
    })
    cfs = sorted(get_enterprise_risk(rid)["contributing_factors"], key=lambda c: c["cf_ref"])
    cf1_id, cf2_id = cfs[0]["id"], cfs[1]["id"]

    c1 = _create_control(test_db, "Strong Control")
    c2 = _create_control(test_db, "Weak Control")
    link_risk_control(rid, c1, 1, cf_id=cf1_id)
    link_risk_control(rid, c2, 1, cf_id=cf2_id)
    set_control_assessment(rid, c1, 70, cf1_id)
    set_control_assessment(rid, c2, 60, cf2_id)

    treatments = {t["cf_ref"]: t for t in list_treatments(rid)}
    assert treatments["CF001"]["treatment_option"] == "accept"
    assert treatments["CF002"]["treatment_option"] == "mitigate"


def test_tr_ref_pairs_with_cf_and_survives_deletion(test_db):
    """Deleting CF001 removes its treatment row (TR001) too; CF002's
    treatment stays TR002; a newly added CF gets CF003/TR003 (never a
    reused number), matching the CF ref convention from PLAN-23."""
    from modules.erm.data_service import (
        create_enterprise_risk, update_enterprise_risk, get_enterprise_risk, list_treatments,
    )

    rid = create_enterprise_risk({
        "title": "TR Pairing Risk", "likelihood": 3, "impact": 3,
        "contributing_factors": [{"description": "Cause A"}, {"description": "Cause B"}],
    })
    treatments = list_treatments(rid)
    assert sorted(t["tr_ref"] for t in treatments) == ["TR001", "TR002"]

    cfs = sorted(get_enterprise_risk(rid)["contributing_factors"], key=lambda c: c["cf_ref"])
    cf2_id = cfs[1]["id"]

    # Omit CF001 (deleted), keep CF002, add a new CF -> CF003.
    update_enterprise_risk(rid, {
        "contributing_factors": [
            {"id": cf2_id, "description": "Cause B"},
            {"description": "Cause C"},
        ],
    })
    risk = get_enterprise_risk(rid)
    assert sorted(c["cf_ref"] for c in risk["contributing_factors"]) == ["CF002", "CF003"]

    treatments = list_treatments(rid)
    tr_by_cf = {t["cf_ref"]: t["tr_ref"] for t in treatments}
    assert tr_by_cf == {"CF002": "TR002", "CF003": "TR003"}


def test_update_treatment_validates_option_and_status(test_db):
    """Invalid treatment_option/status values raise ValueError; a valid
    value like 'exploit' is accepted and persisted."""
    from modules.erm.data_service import create_enterprise_risk, list_treatments, update_treatment

    rid = create_enterprise_risk({
        "title": "Validation Risk", "likelihood": 3, "impact": 3,
        "contributing_factors": [{"description": "Cause A"}],
    })
    tid = list_treatments(rid)[0]["id"]

    with pytest.raises(ValueError):
        update_treatment(tid, {"treatment_option": "ignore"})
    with pytest.raises(ValueError):
        update_treatment(tid, {"status": "done"})

    updated = update_treatment(tid, {"treatment_option": "exploit"})
    assert updated["treatment_option"] == "exploit"


def test_accept_warning_below_70_assurance(test_db):
    """Setting treatment_option to 'accept' while the CF has no scored
    control (or is scored below 70) returns a warning string; scoring the
    CF's control at exactly 70 clears the warning on the next save."""
    from modules.erm.data_service import (
        create_enterprise_risk, get_enterprise_risk, link_risk_control,
        set_control_assessment, list_treatments, update_treatment,
    )

    rid = create_enterprise_risk({
        "title": "Warning Risk", "likelihood": 3, "impact": 3,
        "contributing_factors": [{"description": "Cause A"}],
    })
    cf_id = get_enterprise_risk(rid)["contributing_factors"][0]["id"]
    tid = list_treatments(rid)[0]["id"]

    result = update_treatment(tid, {"treatment_option": "accept"})
    assert result["warning"]

    ctrl_id = _create_control(test_db, "Assurance Control")
    link_risk_control(rid, ctrl_id, 1, cf_id=cf_id)
    set_control_assessment(rid, ctrl_id, 70, cf_id)
    result = update_treatment(tid, {"treatment_option": "accept"})
    assert result["warning"] == ""


def test_emv_a_total_and_negative_rejected(test_db):
    """emv_a values across a risk's treatments sum into
    get_enterprise_risk()'s emv_a_total; a negative emv_a is rejected."""
    from modules.erm.data_service import (
        create_enterprise_risk, get_enterprise_risk, list_treatments, update_treatment,
    )

    rid = create_enterprise_risk({
        "title": "EMV-a Risk", "likelihood": 3, "impact": 3,
        "contributing_factors": [{"description": "Cause A"}, {"description": "Cause B"}],
    })
    treatments = list_treatments(rid)
    t1, t2 = treatments[0], treatments[1]

    with pytest.raises(ValueError):
        update_treatment(t1["id"], {"emv_a": -100})

    update_treatment(t1["id"], {"emv_a": 12000})
    update_treatment(t2["id"], {"emv_a": 8000})

    risk = get_enterprise_risk(rid)
    assert risk["emv_a_total"] == 20000


def test_list_treatments_idempotent(test_db):
    """Calling list_treatments twice creates no duplicate rows; UNIQUE(cf_id)
    on erm_cf_treatments backstops this at the schema level too."""
    from modules.erm.data_service import create_enterprise_risk, list_treatments

    rid = create_enterprise_risk({
        "title": "Idempotent Risk", "likelihood": 3, "impact": 3,
        "contributing_factors": [{"description": "Cause A"}],
    })
    first = list_treatments(rid)
    second = list_treatments(rid)
    assert len(first) == 1
    assert len(second) == 1
    assert first[0]["id"] == second[0]["id"]

    count = test_db.execute(
        "SELECT COUNT(*) AS c FROM erm_cf_treatments WHERE risk_id=%s", (rid,)
    ).fetchone()["c"]
    assert count == 1
