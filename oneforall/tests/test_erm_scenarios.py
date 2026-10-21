"""
PLAN-36 P07: ERM scenario analysis, risk/control/KRI/objective/external-context
linkage, and immutable board-pack snapshots (modules/erm/scenarios.py).

Methodology note: compute_scenario_impact() must reuse data_service's own
tiered residual engine (_compute_residual_tiers) rather than any separate
formula -- these tests assert against hand-computed numbers using that exact
same methodology, the same way test_erm_ice_engine.py/test_erm_dashboard_v2.py
assert against the real engine's tiers.
"""
import json

import pytest

from modules.erm import data_service as ds
from modules.erm import scenarios as sv


def _user(db, uid, username=None):
    username = username or f"scenuser{uid}"
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash) VALUES (%s,%s,%s,%s,'x')",
        (uid, username, f"{username}@x.com", username),
    )
    db.commit()


def _actor(uid, business_unit_id=None, is_super_admin=False):
    return {"id": uid, "business_unit_id": business_unit_id, "is_super_admin": is_super_admin}


def _bu(db, name):
    db.execute("INSERT INTO business_units (name) VALUES (%s)", (name,))
    db.commit()
    return db.execute("SELECT id FROM business_units WHERE name=%s", (name,)).fetchone()["id"]


def _control(db, title="Test Control", business_unit_id=None):
    db.execute(
        "INSERT INTO canonical_controls (title, automation, business_unit_id) VALUES (%s,'manual',%s)",
        (title, business_unit_id),
    )
    db.commit()
    return db.execute("SELECT id FROM canonical_controls WHERE title=%s ORDER BY id DESC LIMIT 1", (title,)).fetchone()["id"]


@pytest.fixture
def actor1(test_db):
    _user(test_db, 1)
    return _actor(1)


# ── Scenario CRUD ────────────────────────────────────────────────────────────

def test_create_update_delete_scenario(test_db, actor1):
    sid = sv.create_scenario({"title": "Cyber stress test", "horizon": "12 months"}, actor1)
    assert sid > 0
    scenario = sv.get_scenario(sid)
    assert scenario["title"] == "Cyber stress test"
    assert scenario["status"] == "draft"
    assert scenario["version"] == 1

    sv.update_scenario(sid, {"status": "active", "description": "updated"}, actor1)
    scenario = sv.get_scenario(sid)
    assert scenario["status"] == "active"
    assert scenario["version"] == 2

    assert sv.delete_scenario(sid, actor1) is True
    assert sv.get_scenario(sid) is None


def test_create_scenario_requires_title(test_db, actor1):
    with pytest.raises(sv.ScenarioError):
        sv.create_scenario({"title": "  "}, actor1)


def test_delete_refused_when_board_packs_exist(test_db, actor1):
    sid = sv.create_scenario({"title": "Has a pack"}, actor1)
    sv.generate_board_pack(scenario_id=sid, actor=actor1)
    with pytest.raises(sv.ScenarioError):
        sv.delete_scenario(sid, actor1)
    assert sv.get_scenario(sid) is not None


# ── Business-unit scope ──────────────────────────────────────────────────────

def test_list_scenarios_bu_scope_filters(test_db):
    # Creation across multiple business units requires an unrestricted
    # actor -- _resolve_write_business_unit refuses to let a scoped (or
    # no-BU) actor assign an arbitrary business_unit_id to a new record.
    # That permission boundary is covered separately
    # (test_scoped_actor_cannot_mutate_org_wide_scenario); this test is only
    # about list_scenarios()'s own bu_scope filtering.
    _user(test_db, 9)
    super_actor = _actor(9, is_super_admin=True)
    bu_a = _bu(test_db, "BU A")
    bu_b = _bu(test_db, "BU B")
    sv.create_scenario({"title": "Org-wide"}, super_actor)
    sv.create_scenario({"title": "BU A scenario", "business_unit_id": bu_a}, super_actor)
    sv.create_scenario({"title": "BU B scenario", "business_unit_id": bu_b}, super_actor)

    scoped = sv.list_scenarios(bu_scope=[bu_a])
    titles = {s["title"] for s in scoped}
    assert titles == {"Org-wide", "BU A scenario"}

    unrestricted = sv.list_scenarios(bu_scope=None)
    assert len(unrestricted) == 3


def test_add_link_rejects_cross_bu_target_structurally(test_db):
    # Same unrestricted-actor rationale as test_list_scenarios_bu_scope_filters
    # above: creation needs an actor allowed to assign bu_a; using the same
    # actor for the link attempt isolates the failure to the structural
    # scenario-vs-target BU mismatch this test targets, not an unrelated
    # actor-scope rejection (covered by test_scoped_actor_cannot_mutate_org_wide_scenario).
    _user(test_db, 9)
    super_actor = _actor(9, is_super_admin=True)
    bu_a = _bu(test_db, "BU A")
    bu_b = _bu(test_db, "BU B")
    sid = sv.create_scenario({"title": "BU A scenario", "business_unit_id": bu_a}, super_actor)
    risk_id = ds.create_enterprise_risk({"title": "BU B risk", "likelihood": 3, "impact": 3, "business_unit_id": bu_b})

    with pytest.raises(sv.ForbiddenScopeError):
        sv.add_scenario_link(sid, "risk", risk_id, actor=super_actor)
    assert sv.list_scenario_links(sid) == []


def test_add_link_allows_org_wide_target_on_bu_scoped_scenario(test_db):
    _user(test_db, 3)
    bu_a = _bu(test_db, "BU A")
    bu_a_actor = _actor(3, business_unit_id=bu_a)
    sid = sv.create_scenario({"title": "BU A scenario", "business_unit_id": bu_a}, bu_a_actor)
    risk_id = ds.create_enterprise_risk({"title": "Org-wide risk", "likelihood": 3, "impact": 3})

    link_id = sv.add_scenario_link(sid, "risk", risk_id, actor=bu_a_actor)
    assert link_id > 0


def test_scoped_actor_cannot_mutate_org_wide_scenario(test_db):
    _user(test_db, 2)
    _user(test_db, 3)
    bu_a = _bu(test_db, "BU A")
    scoped_actor = _actor(2, business_unit_id=bu_a)
    super_actor = _actor(3, is_super_admin=True)
    sid = sv.create_scenario({"title": "Org-wide scenario"}, super_actor)
    risk_id = ds.create_enterprise_risk({
        "title": "Org-wide risk", "likelihood": 3, "impact": 3,
    })

    with pytest.raises(sv.ForbiddenScopeError):
        sv.add_scenario_link(sid, "risk", risk_id, actor=scoped_actor)


def test_link_invalid_type_rejected(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    with pytest.raises(sv.ScenarioError):
        sv.add_scenario_link(sid, "not_a_type", 1, actor=actor1)


def test_link_nonexistent_target_rejected(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    with pytest.raises(sv.ScenarioError):
        sv.add_scenario_link(sid, "risk", 999999, actor=actor1)


# ── Delta validation ─────────────────────────────────────────────────────────

def test_delta_must_be_an_object(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    with pytest.raises(sv.ScenarioError):
        sv.add_scenario_link(sid, "risk", risk_id, delta=[1, 2, 3], actor=actor1)


def test_delta_rejects_unsupported_field_for_link_type(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    control_id = _control(test_db, "C")
    with pytest.raises(sv.ScenarioError):
        # likelihood_override is a 'risk' field, not a 'control' one.
        sv.add_scenario_link(sid, "control", control_id, delta={"likelihood_override": 5}, actor=actor1)


def test_delta_rejects_out_of_range_likelihood(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    with pytest.raises(sv.ScenarioError):
        sv.add_scenario_link(sid, "risk", risk_id, delta={"likelihood_override": 6}, actor=actor1)
    with pytest.raises(sv.ScenarioError):
        sv.add_scenario_link(sid, "risk", risk_id, delta={"likelihood_override": 0}, actor=actor1)
    with pytest.raises(sv.ScenarioError):
        sv.add_scenario_link(sid, "risk", risk_id, delta={"likelihood_override": "five"}, actor=actor1)
    assert sv.list_scenario_links(sid) == []


def test_delta_rejects_ice_score_outside_allowed_set(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    control_id = _control(test_db, "C")
    with pytest.raises(sv.ScenarioError):
        sv.add_scenario_link(sid, "control", control_id, delta={"ice_score_override": 55}, actor=actor1)
    assert sv.list_scenario_links(sid) == []


def test_delta_rejects_negative_emv_override(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    with pytest.raises(sv.ScenarioError):
        sv.add_scenario_link(sid, "risk", risk_id, delta={"emv_inherent_override": -100}, actor=actor1)


def test_relink_upserts_delta(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    sv.add_scenario_link(sid, "risk", risk_id, delta={"likelihood_override": 4}, actor=actor1)
    sv.add_scenario_link(sid, "risk", risk_id, delta={"likelihood_override": 5}, actor=actor1)
    links = sv.list_scenario_links(sid)
    assert len(links) == 1
    assert links[0]["delta"]["likelihood_override"] == 5


def test_remove_link(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    sv.add_scenario_link(sid, "risk", risk_id, actor=actor1)
    assert sv.remove_scenario_link(sid, "risk", risk_id, actor=actor1) is True
    assert sv.list_scenario_links(sid) == []


# ── compute_scenario_impact ──────────────────────────────────────────────────

def test_compute_scenario_impact_is_reproducible(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3, "emv_inherent": 1000})
    sv.add_scenario_link(sid, "risk", risk_id, delta={"likelihood_override": 5}, actor=actor1)

    first = sv.compute_scenario_impact(sid)
    second = sv.compute_scenario_impact(sid)
    assert first == second


def test_likelihood_override_changes_scenario_band_and_irr_not_baseline(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    sv.add_scenario_link(sid, "risk", risk_id, delta={"likelihood_override": 5, "impact_override": 5}, actor=actor1)

    impact = sv.compute_scenario_impact(sid)
    row = impact["per_risk"][0]
    assert row["baseline"]["irr"] == 9  # 3x3, untouched
    assert row["scenario"]["irr"] == 25  # 5x5, hypothetical
    assert row["baseline"]["band"] != row["scenario"]["band"]

    # Baseline (real, live) risk row itself must be completely untouched.
    live = ds.get_enterprise_risk(risk_id)
    assert live["likelihood"] == 3 and live["impact"] == 3


def test_control_ice_override_flips_default_tier_into_ice_tier(test_db, actor1):
    """A risk with no scored controls falls to the tier-4 default (F18:
    residual = inherent * default_residual_factor, i.e. an optimistic 80%
    assumed reduction with the seeded 0.2 factor). A scenario override of a
    linked control's ICE score -- even one with no real ICE score yet --
    must flip the SCENARIO side into the tier-1 ICE path, while the
    baseline (real, live) stays on tier-4. Using an override of 50 (below
    the tier-4 default's implied 80%) deliberately demonstrates the
    documented F18 consequence: an actually-measured-but-weak control can
    look worse than an unassessed risk's own optimistic default."""
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 4, "impact": 4})
    control_id = _control(test_db, "Unscored control")
    ds.link_risk_control(risk_id, control_id, actor1["id"])

    sv.add_scenario_link(sid, "risk", risk_id, actor=actor1)
    sv.add_scenario_link(sid, "control", control_id, delta={"ice_score_override": 50}, actor=actor1)

    impact = sv.compute_scenario_impact(sid)
    row = impact["per_risk"][0]
    irr = 16  # 4 x 4
    assert row["baseline"]["loa_pct"] == 80  # tier-4 default: (1 - 0.2) * 100
    assert row["baseline"]["rrr"] == round(irr * 0.2, 1)
    assert row["scenario"]["loa_pct"] == 50  # tier-1 ICE path: loa_pct == the override itself
    assert row["scenario"]["rrr"] == round(irr * 0.5, 1)
    assert row["scenario"]["rrr"] > row["baseline"]["rrr"]  # weaker measured control, worse residual


def test_missing_kri_value_flagged_not_defaulted_to_zero(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    kri_id = ds.create_kri({"name": "Unmeasured KRI", "linked_risk_id": risk_id})
    sv.add_scenario_link(sid, "kri", kri_id, actor=actor1)

    impact = sv.compute_scenario_impact(sid)
    assert len(impact["kris"]) == 1
    assert impact["kris"][0]["missing"] is True
    assert impact["kris"][0]["latest_value"] is None
    assert any(i["issue"] == "missing_kri_value" for i in impact["data_quality_issues"])


def test_appetite_impact_scoped_to_scenarios_own_linked_risks(test_db, actor1):
    ds.upsert_appetite({"category": "Strategic Risk", "max_score": 3, "appetite_level": "low"})
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 5, "impact": 5, "category": "Strategic Risk"})
    sv.add_scenario_link(sid, "risk", risk_id, actor=actor1)

    impact = sv.compute_scenario_impact(sid)
    strategic = next(a for a in impact["appetite_impact"] if a["category"] == "Strategic Risk")
    assert strategic["max_score"] == 3
    # Unassessed (tier-4 default, 0.2 factor): rrr = 25*0.2 = 5.0 -- breaches, on both sides.
    assert strategic["baseline_breached"] is True
    assert strategic["baseline_max_exposure"] == 5.0
    assert strategic["scenario_breached"] is True
    assert strategic["scenario_max_exposure"] == 5.0


def test_deleted_linked_risk_flagged_not_silently_skipped(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "Will be deleted", "likelihood": 3, "impact": 3})
    sv.add_scenario_link(sid, "risk", risk_id, actor=actor1)
    ds.delete_enterprise_risk(risk_id)

    impact = sv.compute_scenario_impact(sid)
    assert impact["per_risk"] == []
    assert {"link_type": "risk", "link_id": risk_id, "issue": "risk_not_found"} in impact["data_quality_issues"]


# ── Board packs ──────────────────────────────────────────────────────────────

def test_generate_board_pack_chains_hashes(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    pack1_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)
    pack2_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)

    pack1 = sv.get_board_pack(pack1_id)
    pack2 = sv.get_board_pack(pack2_id)
    assert pack1["prev_hash"] is None
    assert pack2["prev_hash"] == pack1["content_hash"]
    assert sv.verify_board_pack_chain() == []


def test_board_pack_inherits_scenario_bu_and_is_isolated_from_other_bus(test_db):
    _user(test_db, 4)
    _user(test_db, 5)
    bu_a = _bu(test_db, "BU A")
    bu_b = _bu(test_db, "BU B")
    bu_a_actor = _actor(4, business_unit_id=bu_a)
    bu_b_actor = _actor(5, business_unit_id=bu_b)

    sid = sv.create_scenario({"title": "BU A scenario"}, bu_a_actor)
    pack_id = sv.generate_board_pack(scenario_id=sid, actor=bu_a_actor)

    pack = sv.get_board_pack(pack_id)
    assert pack["business_unit_id"] == bu_a

    with pytest.raises(sv.ForbiddenScopeError):
        sv.get_board_pack(pack_id, bu_scope=sv.bu_scope_ids(bu_b_actor))
    assert sv.list_board_packs(bu_scope=sv.bu_scope_ids(bu_b_actor)) == []

    same_bu = sv.get_board_pack(pack_id, bu_scope=sv.bu_scope_ids(bu_a_actor))
    assert same_bu["id"] == pack_id
    assert any(p["id"] == pack_id for p in sv.list_board_packs(bu_scope=sv.bu_scope_ids(bu_a_actor)))
    assert sv.verify_board_pack_chain(bu_scope=sv.bu_scope_ids(bu_a_actor)) == []


def test_baseline_only_pack_requires_unrestricted_actor(test_db, actor1):
    # actor1 has no assigned business_unit_id (bu_scope_ids -> [-1], not
    # None), so it is not unrestricted either -- only a true super-admin
    # (or actor=None, the scheduler/system path) may create a baseline-only
    # (no scenario) pack, since it has no single business unit to freeze.
    with pytest.raises(sv.ForbiddenScopeError):
        sv.generate_board_pack(scenario_id=None, actor=actor1)

    _user(test_db, 6)
    super_actor = _actor(6, is_super_admin=True)
    pack_id = sv.generate_board_pack(scenario_id=None, actor=super_actor)
    pack = sv.get_board_pack(pack_id)
    assert pack["business_unit_id"] is None
    assert pack["source_hashes"] == {"baseline_snapshot": pack["source_hashes"]["baseline_snapshot"]}


def test_verify_chain_detects_tampering(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    pack_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)
    assert sv.verify_board_pack_chain() == []

    test_db.execute(
        "UPDATE erm_board_packs SET source_snapshot_json=%s WHERE id=%s",
        (json.dumps({"tampered": True}), pack_id),
    )
    test_db.commit()

    problems = sv.verify_board_pack_chain()
    assert any(p["id"] == pack_id and "altered" in p["issue"] for p in problems)


def test_board_pack_snapshot_immutable_when_live_risk_changes(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 2, "impact": 2})
    sv.add_scenario_link(sid, "risk", risk_id, actor=actor1)
    pack_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)

    frozen_before = sv.get_board_pack(pack_id)["source_snapshot"]

    ds.update_enterprise_risk(risk_id, {"likelihood": 5, "impact": 5})

    frozen_after = sv.get_board_pack(pack_id)["source_snapshot"]
    assert frozen_after == frozen_before  # byte-for-byte unchanged


def test_sweep_stale_board_packs_flags_without_rewriting_snapshot(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 2, "impact": 2})
    sv.add_scenario_link(sid, "risk", risk_id, actor=actor1)
    pack_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)
    frozen_before = sv.get_board_pack(pack_id)["source_snapshot"]

    ds.update_enterprise_risk(risk_id, {"likelihood": 5, "impact": 5})

    newly_stale = sv.sweep_stale_board_packs()
    assert pack_id in newly_stale

    pack = sv.get_board_pack(pack_id)
    assert pack["is_stale"] is True
    assert pack["stale_reason"]
    assert pack["source_snapshot"] == frozen_before  # still untouched


def test_publish_requires_narrative(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    pack_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)
    with pytest.raises(sv.ScenarioError):
        sv.publish_board_pack(pack_id, actor1)

    sv.update_board_pack_narrative(pack_id, "Manual narrative.", [], "human", actor1)
    assert sv.publish_board_pack(pack_id, actor1) is True
    assert sv.get_board_pack(pack_id)["status"] == "published"


def test_narrative_locked_after_publish(test_db, actor1):
    sid = sv.create_scenario({"title": "S"}, actor1)
    pack_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)
    sv.update_board_pack_narrative(pack_id, "Draft narrative.", [], "human", actor1)
    sv.publish_board_pack(pack_id, actor1)

    with pytest.raises(sv.ScenarioError):
        sv.update_board_pack_narrative(pack_id, "Edited after publish.", [], "human", actor1)


# ── AI narrative with required citations ────────────────────────────────────

def test_generate_narrative_ai_not_configured(test_db, actor1, monkeypatch):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    sv.add_scenario_link(sid, "risk", risk_id, actor=actor1)
    pack_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)

    monkeypatch.setattr(sv, "is_configured", lambda: False)
    result = sv.generate_board_pack_narrative(pack_id)
    assert result["ok"] is False
    assert sv.get_board_pack(pack_id)["narrative"] is None


def test_generate_narrative_valid_citations_saved(test_db, actor1, monkeypatch):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    sv.add_scenario_link(sid, "risk", risk_id, actor=actor1)
    pack_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)
    allowed_ref = f"risk:{risk_id}"

    monkeypatch.setattr(sv, "is_configured", lambda: True)
    monkeypatch.setattr(sv, "create_message", lambda *a, **k: json.dumps({
        "narrative": "This risk is elevated.",
        "citations": [{"ref": allowed_ref, "claim": "elevated risk"}],
    }))

    result = sv.generate_board_pack_narrative(pack_id)
    assert result["ok"] is True
    pack = sv.get_board_pack(pack_id)
    assert pack["narrative"] == "This risk is elevated."
    assert pack["narrative_source"] == "ai"
    assert pack["narrative_citations"][0]["ref"] == allowed_ref


def test_generate_narrative_invalid_citation_rejected(test_db, actor1, monkeypatch):
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    sv.add_scenario_link(sid, "risk", risk_id, actor=actor1)
    pack_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)

    monkeypatch.setattr(sv, "is_configured", lambda: True)
    monkeypatch.setattr(sv, "create_message", lambda *a, **k: json.dumps({
        "narrative": "Fabricated claim.",
        "citations": [{"ref": "risk:999999", "claim": "made up"}],
    }))

    result = sv.generate_board_pack_narrative(pack_id)
    assert result["ok"] is False
    assert "unknown source" in result["reason"]
    assert sv.get_board_pack(pack_id)["narrative"] is None


def test_narrative_write_fails_closed_if_pack_published_mid_request(test_db, actor1, monkeypatch):
    """Simulates the race the atomic UPDATE ... WHERE status='draft' guards
    against: the pack already has a human narrative (so it's publishable),
    and get published by a second request WHILE the (slow) AI call for a
    regenerate is still in flight. The final conditional UPDATE must then
    affect 0 rows and the call must fail rather than silently overwriting
    the now-published narrative."""
    sid = sv.create_scenario({"title": "S"}, actor1)
    risk_id = ds.create_enterprise_risk({"title": "R", "likelihood": 3, "impact": 3})
    sv.add_scenario_link(sid, "risk", risk_id, actor=actor1)
    pack_id = sv.generate_board_pack(scenario_id=sid, actor=actor1)
    sv.update_board_pack_narrative(pack_id, "Original human narrative.", [], "human", actor1)
    allowed_ref = f"risk:{risk_id}"

    def _concurrent_publish_then_respond(*a, **k):
        # Stands in for another request's publish_board_pack() completing
        # while this (mocked, slow) AI call is still "in flight".
        sv.publish_board_pack(pack_id, actor1)
        return json.dumps({
            "narrative": "AI tried to overwrite the published narrative.",
            "citations": [{"ref": allowed_ref, "claim": "x"}],
        })

    monkeypatch.setattr(sv, "is_configured", lambda: True)
    monkeypatch.setattr(sv, "create_message", _concurrent_publish_then_respond)

    with pytest.raises(sv.ScenarioError):
        sv.generate_board_pack_narrative(pack_id)

    pack = sv.get_board_pack(pack_id)
    assert pack["status"] == "published"
    assert pack["narrative"] == "Original human narrative."  # untouched by the race
