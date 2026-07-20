"""
Tests for PLAN-21: AI controls catalogue + AIMS/ORAAT risk engine (ORM).

Covers the 5 cases scoped in plans/PLAN-21-active.md Step 6: the hand-pinned
scoring convention, an unlinked risk's full-exposure fallback, catalogue
delete-refusal-with-deactivate-escape-hatch, the legacy ORAAT ice_score_10
input mapping, and the 96-row built-in catalogue seed.

Uses the standard conftest test_db fixture (fresh, fully-migrated SQLite
per test -- init_db() runs the catalogue seed too, count-gated on
ai_control_catalogue).
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_convention_worked_example(test_db):
    """Plan's hand-pinned convention numbers: L5xI5 (IRR 25) EMV 2,000,000
    with controls at factors 0.3/0.6/0.6/0.2 -> mean_factor 0.425,
    residual_emv 850,000.

    NOTE: the plan's own hand-typed residual_rating (10.63) does not match
    Python's actual round(25 * 0.425, 2) output, which is 10.62 -- 0.425 is
    not exactly representable in binary floating point, so 25*0.425 lands
    a hair off 10.625 before rounding. Empirically verified with a
    throwaway script before writing this assertion. Trusting the real
    computed value here per the plan's own instruction to "(Pin YOUR
    computed values by hand.)" rather than the hand-typed figure.
    """
    from modules.orm.data_service import (
        create_aims_assessment, create_aims_risk, create_aims_risk_control, get_aims_risk,
    )

    aid = create_aims_assessment({"title": "Convention Test"})
    rid = create_aims_risk(aid, {
        "risk_description": "Convention worked example",
        "likelihood": 5, "impact": 5, "emv_inherent": 2000000,
    })
    for factor in (0.3, 0.6, 0.6, 0.2):
        create_aims_risk_control(rid, {"ice_score": round(100 * (1 - factor))})

    computed = get_aims_risk(rid)["computed"]
    assert computed["irr"] == 25
    assert computed["mean_factor"] == 0.425
    assert computed["residual_rating"] == 10.62
    assert computed["residual_emv"] == 850000.0


def test_unlinked_risk_full_residual(test_db):
    """A risk with zero linked controls gets mean_factor 1.0 (full,
    unmitigated exposure) -- residual_rating and residual_emv both equal
    the inherent values exactly, not None and not zeroed out."""
    from modules.orm.data_service import create_aims_assessment, create_aims_risk, get_aims_risk

    aid = create_aims_assessment({"title": "Unlinked Test"})
    rid = create_aims_risk(aid, {
        "risk_description": "No controls linked",
        "likelihood": 3, "impact": 4, "emv_inherent": 100000,
    })

    computed = get_aims_risk(rid)["computed"]
    assert computed["irr"] == 12
    assert computed["mean_factor"] == 1.0
    assert computed["residual_rating"] == 12.0
    assert computed["residual_emv"] == 100000.0


def test_catalogue_delete_refused_when_linked(test_db):
    """A custom catalogue control referenced by any aims_risk_controls row
    cannot be deleted -- delete_ai_control must raise, directing the
    caller to deactivate instead. Deactivate succeeds and preserves the
    row (and its historical link) intact. An unreferenced custom control
    deletes freely. Also confirms per_pillar aggregation buckets a
    catalogue-linked control under its own pillar, not the risk's
    impacted_pillar fallback."""
    from modules.orm.data_service import (
        create_ai_control, create_aims_assessment, create_aims_risk,
        create_aims_risk_control, delete_ai_control, update_ai_control,
        get_ai_control, get_aims_risk,
    )

    cid = create_ai_control({"title": "Custom Control", "pillar": "Process"})
    aid = create_aims_assessment({"title": "Delete Test"})
    rid = create_aims_risk(aid, {
        "risk_description": "Delete refusal test", "impacted_pillar": "Technology",
    })
    create_aims_risk_control(rid, {"catalogue_control_id": cid, "ice_score": 50})

    with pytest.raises(ValueError):
        delete_ai_control(cid)

    computed = get_aims_risk(rid)["computed"]
    assert computed["per_pillar"]["Process"]["count"] == 1
    assert computed["per_pillar"]["Technology"]["count"] == 0

    update_ai_control(cid, {"is_active": 0})
    assert get_ai_control(cid)["is_active"] == 0

    cid2 = create_ai_control({"title": "Unreferenced Control", "pillar": "People"})
    delete_ai_control(cid2)
    assert get_ai_control(cid2) is None


def test_oraat_legacy_ice_score_10_input(test_db):
    """Legacy ORAAT sheet values (1-10, LOWER = stronger) map on input as
    ice_score = 100 - legacy*10: sheet value 1 -> ice_score 90 -> factor
    0.1 -> residual_rating 2.5 for IRR 25."""
    from modules.orm.data_service import (
        create_aims_assessment, create_aims_risk, create_aims_risk_control, get_aims_risk,
    )

    aid = create_aims_assessment({"title": "ORAAT Test", "mode": "oraat"})
    rid = create_aims_risk(aid, {
        "risk_description": "ORAAT legacy input", "likelihood": 5, "impact": 5,
    })
    create_aims_risk_control(rid, {"ice_score_10": 1})

    risk = get_aims_risk(rid)
    assert risk["controls"][0]["ice_score"] == 90
    computed = risk["computed"]
    assert computed["mean_factor"] == 0.1
    assert computed["residual_rating"] == 2.5


def test_risk_ref_auto_generated_per_assessment(test_db):
    """Each risk gets an auto-generated 'R{n}' ref scoped to its own
    assessment (not global) -- found via live verification: the
    aggregation CSV export showed a blank ref column because no ref
    generator was ever wired into create_aims_risk. A second, separate
    assessment's first risk must also start at R1, not continue the
    first assessment's sequence."""
    from modules.orm.data_service import create_aims_assessment, create_aims_risk, get_aims_risk

    aid1 = create_aims_assessment({"title": "Ref Test A"})
    r1 = create_aims_risk(aid1, {"risk_description": "First risk"})
    r2 = create_aims_risk(aid1, {"risk_description": "Second risk"})
    assert get_aims_risk(r1)["ref"] == "R1"
    assert get_aims_risk(r2)["ref"] == "R2"

    aid2 = create_aims_assessment({"title": "Ref Test B"})
    r3 = create_aims_risk(aid2, {"risk_description": "Other assessment's first risk"})
    assert get_aims_risk(r3)["ref"] == "R1"


def test_fresh_db_seeds_96_catalogue_controls(test_db):
    """A freshly initialized DB seeds exactly the 96 controls extracted
    from the taxonomy workbook, all marked source='built_in'."""
    from modules.orm.data_service import list_ai_controls

    controls = list_ai_controls(include_inactive=True)
    assert len(controls) == 96
    assert all(c["source"] == "built_in" for c in controls)
