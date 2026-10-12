"""
AI governance G3: what an AI use needs, where each step stands, the AI controls with their proof, and the quality checks.

Written out by hand: a step's progress is read from the owning module's own records and only the ones the viewer may
open; a step the viewer has no right to says so and names nothing; a reviewer's "not applicable" needs a reason and is
flagged when the facts change; a mapping is never made by itself; and a check that could not be made is not a clean one.
"""
import json

import pytest

from modules.ai_governance import controls, guidance, quality, service
from modules.ai_governance.service import ServiceError
from modules.governance import relationships
from tests.test_ai_governance_service import FULL, approve_new, commit, count, fail, submitted, user
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401


@pytest.fixture
def system(world):
    """An accepted use in unit A (vendor service, internal data, nobody affected, assists only: tier lower)."""
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    return world


def steps(world, name="dpo_a"):
    return {s["key"]: s for s in guidance.get_checklist(world.db, user(world, name), world.app)["steps"]}


# ── The checklist ───────────────────────────────────────────────────────────

def test_a_new_use_shows_what_it_needs_and_that_nothing_has_started(system):
    plan = guidance.get_checklist(system.db, user(system, "dpo_a"), system.app)
    got = {k: (s["applicability"], s["state"]) for k, s in steps(system).items()}
    assert got == {"aiia": ("recommended", "not_started"), "dpia": ("not_applicable", "not_started"),
                   "ropa": ("not_applicable", "not_started"), "vendor": ("required", "not_started"),
                   # the DPO holds no right to Operations risk records: that is said, not shown as "not started"
                   "aims": ("not_applicable", "no_access"), "policy": ("recommended", "not_started")}
    assert plan["unresolved"] == ["vendor"] and plan["rule_version"] == "v1"
    action = steps(system)["aiia"]["action"]
    assert action["url"] == f"/ai-governance/assessments/new?application_id={system.app}&aig_return={system.app}"


def test_progress_comes_from_the_records_of_the_owning_module(system):
    aiia = _insert(system.db, "sentinel_aiia", ref_number="AIIA-7", title="Churn", business_unit_id=system.unit["A"],
                   application_id=system.app, status="draft")
    system.db.commit()
    assert steps(system)["aiia"]["state"] == "in_progress"
    system.db.execute("UPDATE sentinel_aiia SET status = 'completed' WHERE id = %s", (aiia,))
    system.db.commit()
    done = steps(system)["aiia"]
    assert done["state"] == "complete" and done["records"][0]["title"] == "AIIA-7: Churn"


def test_a_dpia_is_found_through_the_assessment_it_came_from_and_through_a_link(system):
    via_aiia = _insert(system.db, "sentinel_dpias", ref_number="DPIA-1", title="From the AIIA", business_unit_id=system.unit["A"], status="completed")
    via_link = _insert(system.db, "sentinel_dpias", ref_number="DPIA-2", title="By link", business_unit_id=system.unit["A"], status="draft")
    _insert(system.db, "sentinel_aiia", ref_number="AIIA-8", title="X", business_unit_id=system.unit["A"], application_id=system.app, dpia_id=via_aiia)
    relationships.create_link(system.db, user(system, "dpo_a"), ("sentinel", "dpia", via_link), APP_REF(system), "assesses")
    system.db.commit()
    dpia = steps(system)["dpia"]
    assert {r["title"] for r in dpia["records"]} == {"DPIA-1: From the AIIA", "DPIA-2: By link"} and dpia["state"] == "complete"


def APP_REF(world):
    return ("governance", "application", world.app)


def test_a_record_in_another_unit_is_never_named_or_counted(system):
    _insert(system.db, "sentinel_aiia", ref_number="AIIA-B", title="Secret impact", business_unit_id=system.unit["B"],
            application_id=system.app, status="completed")
    system.db.commit()
    got = steps(system)["aiia"]
    assert got["state"] == "not_started" and got["records"] == []
    assert "Secret impact" not in json.dumps(guidance.get_checklist(system.db, user(system, "dpo_a"), system.app))


def test_a_viewer_with_no_right_to_privacy_records_is_told_so_and_shown_nothing(system):
    _insert(system.db, "sentinel_aiia", ref_number="AIIA-9", title="Visible to the DPO only", business_unit_id=system.unit["A"],
            application_id=system.app, status="completed")
    system.db.commit()
    plan = steps(system, "employee_a")
    assert plan["aiia"]["state"] == "no_access" and plan["aiia"]["records"] == []
    assert "Visible to the DPO only" not in json.dumps(plan)


def test_a_use_the_viewer_may_not_open_has_no_checklist(system):
    assert guidance.get_checklist(system.db, user(system, "dpo_b"), system.app) is None
    plain = _insert(system.db, "applications", name="Plain", business_unit_id=system.unit["A"], is_active=1)
    assert guidance.get_checklist(system.db, user(system, "dpo_a"), plain)["steps"] == []


def test_a_source_that_cannot_be_read_is_unavailable_and_not_complete(system, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("table is gone")
    monkeypatch.setitem(guidance._ADAPTERS, "aiia", broken)
    got = steps(system)["aiia"]
    assert got["state"] == "unavailable" and got["records"] == []
    assert steps(system)["policy"]["state"] == "not_started", "the others are still read"


def test_a_provider_review_is_complete_only_when_the_agreement_is_signed_and_an_assessment_exists(system):
    vendor = _insert(system.db, "canonical_vendors", name="Acme AI")
    system.db.execute("UPDATE applications SET vendor_id = %s WHERE id = %s", (vendor, system.app))
    system.db.commit()
    assert steps(system, "super")["vendor"]["state"] == "in_progress"
    sentinel_vendor = _insert(system.db, "sentinel_vendors", name="Acme AI", canonical_id=vendor, dpa_status="signed")
    system.db.commit()
    assert steps(system, "super")["vendor"]["state"] == "in_progress", "an agreement alone is not a review"
    grid_vendor = _insert(system.db, "grid_vendors", name="Acme AI", canonical_id=vendor)
    _insert(system.db, "grid_vendor_assessments", vendor_id=grid_vendor, score=82, assessment_date="2026-09-01")
    system.db.commit()
    got = steps(system, "super")["vendor"]
    assert got["state"] == "complete" and len(got["records"]) == 3 and sentinel_vendor


# ── A reviewer rules a step out ─────────────────────────────────────────────

def test_a_required_step_can_be_ruled_out_with_a_reason_and_put_back(system):
    assert guidance.get_checklist(system.db, user(system, "dpo_a"), system.app)["unresolved"] == ["vendor"]
    fail(lambda: guidance.set_step_not_applicable(system.db, user(system, "dpo_a"), system.app, "vendor", " "), 422)
    fail(lambda: guidance.set_step_not_applicable(system.db, user(system, "dpo_a"), system.app, "nonsense", "because"), 404)
    done = guidance.set_step_not_applicable(system.db, user(system, "dpo_a"), system.app, "vendor", "Built by us under licence.")
    commit(system, done, user(system, "dpo_a"))
    plan = guidance.get_checklist(system.db, user(system, "dpo_a"), system.app)
    vendor = next(s for s in plan["steps"] if s["key"] == "vendor")
    assert vendor["applicability"] == "required", "the rule still says required"
    assert vendor["effective"] == "not_applicable" and vendor["override"]["reason"] == "Built by us under licence."
    assert vendor["override"]["out_of_date"] is False and plan["unresolved"] == []
    reset = guidance.clear_step_judgement(system.db, user(system, "dpo_a"), system.app, "vendor")
    commit(system, reset, user(system, "dpo_a"))
    assert guidance.get_checklist(system.db, user(system, "dpo_a"), system.app)["unresolved"] == ["vendor"]
    fail(lambda: guidance.clear_step_judgement(system.db, user(system, "dpo_a"), system.app, "vendor"), 404)
    actions = [r[0] for r in system.db.execute("SELECT action FROM audit_log WHERE action LIKE 'ai_step_%' ORDER BY id").fetchall()]
    assert actions == ["ai_step_not_applicable", "ai_step_reset"]


def test_a_judgement_is_out_of_date_once_the_use_changes(system):
    done = guidance.set_step_not_applicable(system.db, user(system, "dpo_a"), system.app, "vendor", "Built by us under licence.")
    commit(system, done, user(system, "dpo_a"))
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    changed = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"deployment": "embedded_vendor"}, profile["version"])
    commit(system, changed, user(system, "dpo_a"))
    vendor = steps(system)["vendor"]
    assert vendor["override"]["out_of_date"] is True and vendor["effective"] == "required"
    assert "vendor" in guidance.get_checklist(system.db, user(system, "dpo_a"), system.app)["unresolved"]


def test_only_a_reviewer_may_rule_a_step_out_and_only_for_a_use_they_can_open(system):
    fail(lambda: guidance.set_step_not_applicable(system.db, user(system, "employee_a"), system.app, "vendor", "because"), 403)
    fail(lambda: guidance.set_step_not_applicable(system.db, user(system, "dpo_b"), system.app, "vendor", "because"), 404)
    fail(lambda: guidance.clear_step_judgement(system.db, user(system, "dpo_b"), system.app, "vendor"), 404)
    assert count(system, "ai_use_step_overrides") == 0


# ── What a form can start from ──────────────────────────────────────────────

def test_an_assessment_starts_from_the_profile_and_says_where_it_came_from(system):
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    service.update_profile(system.db, user(system, "dpo_a"), system.app,
                           {"data_categories": ["personal", "financial"], "affected_people": ["customers"], "autonomy": "decide_with_review"},
                           profile["version"])
    system.db.commit()
    got = guidance.aiia_prefill(system.db, user(system, "dpo_a"), system.app)
    fields = got["fields"]
    assert fields["application_id"] == system.app and fields["ai_system_name"] == "Ticket summarizer"
    assert (fields["autonomy_level"], fields["third_party"], fields["deployment_env"]) == ("human_in_loop", 1, "cloud")
    assert fields["data_categories"] == ["Personal", "Transactional"] and fields["stakeholders_direct"] == "Customers"
    assert got["source"]["kind"] == "AI profile" and got["source"]["updated_at"]
    assert guidance.aiia_prefill(system.db, user(system, "dpo_b"), system.app) is None


# ── AI controls and their proof ─────────────────────────────────────────────

@pytest.fixture
def controls_world(system):
    db, unit, app = system.db, system.unit, system.app
    system.aims = _insert(db, "aims_assessments", ref="AIMS-9", title="AI management A", business_unit_id=unit["A"], application_id=app, status="draft")
    system.catalogue = {n: _insert(db, "ai_control_catalogue", ref=f"AC-{n}", title=title, business_unit_id=unit["A"])
                        for n, title in (("mapped", "Human oversight of model output"), ("bare", "Model change management"),
                                         ("stale", "Training data provenance"), ("off", "Incident reporting"))}
    for name, scope, implemented in (("mapped", 1, 1), ("bare", 1, 1), ("stale", 1, 1), ("off", 0, 0)):
        _insert(db, "aims_risks", assessment_id=system.aims, risk_description=name, catalogue_control_id=system.catalogue[name],
                in_scope=scope, implemented=implemented)
    system.canonical = {n: _insert(db, "canonical_controls", ref=f"CC-{n}", title=title, is_active=1)
                        for n, title in (("oversight", "Human oversight of automated output"), ("provenance", "Data provenance and lineage"))}
    for ai, cc in (("mapped", "oversight"), ("stale", "provenance")):
        _insert(db, "ai_control_mappings", ai_control_id=system.catalogue[ai], canonical_control_id=system.canonical[cc], created_by=1)
    current = _insert(db, "evidence_items", title="Oversight procedure v3", status="current", org_id=1, business_unit_id=unit["A"], version=3, verified_at="2026-09-01")
    expired = _insert(db, "evidence_items", title="Old lineage report", status="current", org_id=1, business_unit_id=unit["A"], expiry_date="2000-01-01")
    hidden = _insert(db, "evidence_items", title="Unit B proof", status="current", org_id=1, business_unit_id=unit["B"])
    for item, cc in ((current, "oversight"), (hidden, "oversight"), (expired, "provenance")):
        _insert(db, "evidence_links", evidence_id=item, module="grid", entity_type="canonical_control", entity_id=system.canonical[cc])
    db.commit()
    return system


def test_each_ai_control_shows_applicable_implemented_mapped_and_proof_as_separate_facts(controls_world):
    shown = {c["control"]["ref"]: c for c in controls.use_controls(controls_world.db, user(controls_world, "owner_a"), controls_world.app)}
    mapped = shown["AC-mapped"]
    assert (mapped["applicable"], mapped["implemented"], mapped["mapped"]) == (True, True, True)
    assert mapped["proof"]["current"] == 1 and mapped["proof"]["verified"] == 1 and mapped["proof"]["expired"] == 0
    assert [i["title"] for i in mapped["proof"]["items"]] == ["Oversight procedure v3"], "unit B's proof is neither shown nor counted"
    assert shown["AC-bare"]["mapped"] is False and shown["AC-bare"]["proof"]["current"] == 0
    assert shown["AC-stale"]["proof"] == {"current": 0, "expired": 1, "verified": 0, "items": shown["AC-stale"]["proof"]["items"]}
    assert (shown["AC-off"]["applicable"], shown["AC-off"]["implemented"]) == (False, False)


def test_a_viewer_with_no_right_to_operations_risk_sees_none_and_a_hidden_use_gives_none(controls_world):
    assert controls.use_controls(controls_world.db, user(controls_world, "dpo_a"), controls_world.app) == []
    assert controls.use_controls(controls_world.db, user(controls_world, "owner_b"), controls_world.app) is None


def test_a_mapping_is_made_by_a_reviewer_who_may_see_the_control_and_never_by_itself(controls_world):
    w = controls_world
    made = controls.map_control(w.db, user(w, "owner_a"), w.catalogue["bare"], w.canonical["oversight"], "Same intent.")
    commit(w, made, user(w, "owner_a"))
    assert made["created"] is True
    again = controls.map_control(w.db, user(w, "owner_a"), w.catalogue["bare"], w.canonical["oversight"])
    assert again["created"] is False and again["audit"] == []
    fail(lambda: controls.map_control(w.db, user(w, "employee_a"), w.catalogue["bare"], w.canonical["oversight"]), 403)
    fail(lambda: controls.map_control(w.db, user(w, "dpo_a"), w.catalogue["bare"], w.canonical["oversight"]), 403)
    fail(lambda: controls.map_control(w.db, user(w, "owner_a"), 987654, w.canonical["oversight"]), 404)
    fail(lambda: controls.map_control(w.db, user(w, "owner_a"), w.catalogue["bare"], 987654), 404)
    fail(lambda: controls.map_control(w.db, user(w, "owner_a"), "x", w.canonical["oversight"]), 400)
    other_unit = _insert(w.db, "ai_control_catalogue", ref="AC-B", title="Unit B control", business_unit_id=w.unit["B"])
    fail(lambda: controls.map_control(w.db, user(w, "owner_a"), other_unit, w.canonical["oversight"]), 404)
    removed = controls.unmap_control(w.db, user(w, "owner_a"), w.catalogue["bare"], w.canonical["oversight"])
    commit(w, removed, user(w, "owner_a"))
    fail(lambda: controls.unmap_control(w.db, user(w, "owner_a"), w.catalogue["bare"], w.canonical["oversight"]), 404)


def test_suggestions_are_only_suggestions(controls_world):
    w = controls_world
    found = controls.suggest_mappings(w.db, user(w, "owner_a"), w.catalogue["bare"])
    assert found == [], "no canonical control shares a word with 'Model change management'"
    extra = _insert(w.db, "canonical_controls", ref="CC-chg", title="Model change management process", is_active=1)
    w.db.commit()
    found = controls.suggest_mappings(w.db, user(w, "owner_a"), w.catalogue["bare"])
    assert [f["id"] for f in found] == [extra] and "Shares:" in found[0]["reason"]
    assert count(w, "ai_control_mappings", "ai_control_id = %s", (w.catalogue["bare"],)) == 0, "nothing was stored"


# ── Quality checks ──────────────────────────────────────────────────────────

def _findings(world, name="dpo_a"):
    return {f["key"]: f for f in quality.evaluate(world.db, user(world, name), world.app)["findings"]}


def test_each_check_names_its_rule_its_version_and_the_form_that_fixes_it(controls_world):
    w = controls_world
    found = _findings(w, "owner_a")
    keys = set(found)
    assert {"step_not_started:step:vendor", f"control_unmapped:ai_control:{w.catalogue['bare']}",
            f"proof_stale:ai_control:{w.catalogue['stale']}"} <= keys
    assert not any(k.startswith("proof_missing") for k in keys), "every mapped control here has some proof, current or expired"
    assert f"control_unmapped:ai_control:{w.catalogue['off']}" not in keys, "a control that is not in scope is not checked"
    assert f"proof_missing:ai_control:{w.catalogue['mapped']}" not in keys, "it has current proof"
    for f in found.values():
        assert f["rule_version"] == "v1" and f["fix"]["url"] and f["why"] and f["fingerprint"] and f["severity"] in ("error", "warning")
    ordered = quality.evaluate(w.db, user(w, "owner_a"), w.app)["findings"]
    assert [f["severity"] for f in ordered] == sorted((f["severity"] for f in ordered), key=lambda s: {"error": 0, "warning": 1}[s])


def test_a_missing_owner_and_an_overdue_review_are_findings_and_a_fixed_one_closes(system):
    system.db.execute("UPDATE applications SET owner_user_id = NULL WHERE id = %s", (system.app,))
    system.db.execute("UPDATE ai_use_profiles SET next_review_at = '2000-01-01' WHERE application_id = %s", (system.app,))
    system.db.commit()
    assert {"owner_missing:application:%d" % system.app, "review_overdue:application:%d" % system.app} <= set(_findings(system))
    system.db.execute("UPDATE applications SET owner_user_id = %s WHERE id = %s", (user(system, "owner_a")["id"], system.app))
    system.db.commit()
    assert "owner_missing:application:%d" % system.app not in _findings(system)


def test_a_check_that_could_not_be_made_is_reported_and_not_shown_as_clean(controls_world, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("down")
    monkeypatch.setattr(controls, "use_controls", broken)
    result = quality.evaluate(controls_world.db, user(controls_world, "owner_a"), controls_world.app)
    assert "AI controls" in result["unchecked"]
    assert not any(f["rule"].startswith(("control_", "proof_")) for f in result["findings"])


def test_a_dismissal_needs_a_reason_applies_while_the_facts_hold_and_is_audited(controls_world):
    w = controls_world
    key = f"control_unmapped:ai_control:{w.catalogue['bare']}"
    fail(lambda: quality.dismiss(w.db, user(w, "owner_a"), w.app, key, " "), 422)
    fail(lambda: quality.dismiss(w.db, user(w, "owner_a"), w.app, "made_up:x:1", "because"), 404)
    fail(lambda: quality.dismiss(w.db, user(w, "employee_a"), w.app, key, "because"), 403)
    fail(lambda: quality.dismiss(w.db, user(w, "owner_a"), w.app, key, "because", expires_at="2000-01-01"), 422)
    done = quality.dismiss(w.db, user(w, "owner_a"), w.app, key, "Compensating review in place.", expires_at="2999-01-01")
    commit(w, done, user(w, "owner_a"))
    shown = _findings(w, "owner_a")[key]
    assert shown["dismissed"]["reason"] == "Compensating review in place." and shown["dismissed"]["expires_at"] == "2999-01-01"
    assert quality.evaluate(w.db, user(w, "owner_a"), w.app)["open"] == len(_findings(w, "owner_a")) - 1
    reopened = quality.reopen(w.db, user(w, "owner_a"), w.app, key)
    commit(w, reopened, user(w, "owner_a"))
    assert _findings(w, "owner_a")[key]["dismissed"] is None
    actions = [r[0] for r in w.db.execute("SELECT action FROM audit_log WHERE action LIKE 'ai_finding_%' ORDER BY id").fetchall()]
    assert actions == ["ai_finding_dismissed", "ai_finding_reopened"]


def test_a_dismissal_stops_applying_when_what_it_was_about_changes_or_expires(controls_world):
    w = controls_world
    key = f"proof_stale:ai_control:{w.catalogue['stale']}"
    done = quality.dismiss(w.db, user(w, "owner_a"), w.app, key, "Waiting for the new report.")
    commit(w, done, user(w, "owner_a"))
    assert _findings(w, "owner_a")[key]["dismissed"] is not None
    second_expired = _insert(w.db, "evidence_items", title="Second old report", status="current", org_id=1,
                             business_unit_id=w.unit["A"], expiry_date="2001-01-01")
    _insert(w.db, "evidence_links", evidence_id=second_expired, module="grid", entity_type="canonical_control", entity_id=w.canonical["provenance"])
    w.db.commit()
    _ = quality.evaluate(w.db, user(w, "owner_a"), w.app)
    w.db.execute("UPDATE ai_use_finding_dismissals SET expires_at = '2000-01-01' WHERE finding_key = %s", (key,))
    w.db.commit()
    assert _findings(w, "owner_a")[key]["dismissed"] is None, "an expired dismissal no longer applies"


def test_a_hidden_use_has_no_quality_checks(controls_world):
    assert quality.evaluate(controls_world.db, user(controls_world, "owner_b"), controls_world.app) is None
    fail(lambda: quality.dismiss(controls_world.db, user(controls_world, "dpo_b"), controls_world.app, "owner_missing:application:1", "because"), 404)
