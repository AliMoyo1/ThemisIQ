"""
PLAN-36 F18: the active risk framework's configurable default_residual_factor,
applied by recompute_residual_for_risk's tier-4 fallback (no scored linked
controls, no manual residual override) -- confirmed against the
organization's real, currently-maintained risk register that this case is
a flat fraction of inherent risk, not an unreduced copy of it (the
previous behavior). Configurable the same way the matrix/bands/dimensions
already are, not hardcoded, per the user's own "this template can change"
requirement.
"""
import re

import pytest

from modules.erm import data_service as ds


def _active_framework_id(db):
    return db.execute("SELECT id FROM erm_risk_frameworks WHERE is_active=1").fetchone()["id"]


def test_seeded_default_is_point_two(test_db):
    row = test_db.execute(
        "SELECT default_residual_factor FROM erm_risk_frameworks WHERE is_active=1"
    ).fetchone()
    assert row["default_residual_factor"] == 0.2


def test_changing_the_factor_on_a_cloned_framework_changes_new_calculations(test_db):
    """The built-in framework is immutable (ds.update_framework raises on
    it) -- clone it, change the factor on the clone, activate it, and
    confirm a newly-created risk with no controls reflects the new value."""
    built_in_id = _active_framework_id(test_db)
    clone_id = ds.create_framework_from_clone("Custom", "A clone for testing", built_in_id)

    detail = ds.get_framework_detail(clone_id)
    detail["default_residual_factor"] = 0.5
    ds.update_framework(clone_id, detail)
    ds.activate_framework(clone_id)

    rid = ds.create_enterprise_risk({"title": "New factor risk", "likelihood": 4, "impact": 5})
    risk = ds.get_enterprise_risk(rid)
    assert risk["irr_score"] == 20
    assert risk["rrr"] == 10.0  # 20 * 0.5
    assert risk["residual_score"] == 10
    assert risk["loa_pct"] == 50


def test_update_framework_on_the_built_in_one_is_refused(test_db):
    """The built-in framework cannot be edited directly -- confirms the
    factor can only ever change through a clone, matching every other
    field on this framework."""
    built_in_id = _active_framework_id(test_db)
    detail = ds.get_framework_detail(built_in_id)
    detail["default_residual_factor"] = 0.9
    with pytest.raises(PermissionError):
        ds.update_framework(built_in_id, detail)


def test_clone_inherits_the_sources_factor(test_db):
    built_in_id = _active_framework_id(test_db)
    clone_id = ds.create_framework_from_clone("Inherits", "desc", built_in_id)
    detail = ds.get_framework_detail(clone_id)
    assert detail["default_residual_factor"] == 0.2


def test_validate_framework_payload_rejects_out_of_range_factor(test_db):
    built_in_id = _active_framework_id(test_db)
    detail = ds.get_framework_detail(built_in_id)
    detail["default_residual_factor"] = 1.5
    errors = ds.validate_framework_payload(detail)
    assert any("default_residual_factor" in e for e in errors)


def test_validate_framework_payload_rejects_non_numeric_factor(test_db):
    built_in_id = _active_framework_id(test_db)
    detail = ds.get_framework_detail(built_in_id)
    detail["default_residual_factor"] = "not a number"
    errors = ds.validate_framework_payload(detail)
    assert any("default_residual_factor" in e for e in errors)


def test_existing_ice_and_manual_override_tiers_are_unaffected_by_the_factor(test_db):
    """Changing default_residual_factor must only ever affect the tier-4
    fallback -- a risk with a real ICE-scored control, or a manual
    residual override, must keep using its own tier's math regardless."""
    built_in_id = _active_framework_id(test_db)
    clone_id = ds.create_framework_from_clone("Custom2", "desc", built_in_id)
    detail = ds.get_framework_detail(clone_id)
    detail["default_residual_factor"] = 0.9  # deliberately extreme
    ds.update_framework(clone_id, detail)
    ds.activate_framework(clone_id)

    # Manual override (tier 2): unaffected by the factor.
    rid = ds.create_enterprise_risk({"title": "Override unaffected", "likelihood": 4, "impact": 4})
    ds.update_enterprise_risk(rid, {"residual_likelihood": 2, "residual_impact": 3})
    risk = ds.get_enterprise_risk(rid)
    assert risk["residual_score"] == 6  # 2*3, not influenced by 0.9
    assert risk["rrr"] == 6.0

    # ICE path (tier 1): unaffected by the factor.
    test_db.execute("INSERT INTO canonical_controls (title, automation) VALUES ('C', 'manual')")
    test_db.commit()
    cid = test_db.execute("SELECT id FROM canonical_controls WHERE title='C'").fetchone()["id"]
    rid2 = ds.create_enterprise_risk({"title": "ICE unaffected", "likelihood": 4, "impact": 5})
    ds.link_risk_control(rid2, cid, 1)
    risk2 = ds.set_control_assessment(rid2, cid, 90, None)
    assert risk2["loa_pct"] == 90  # not 10 (1-0.9)
    assert risk2["rrr"] == round(risk2["irr_score"] * 0.1, 1)
