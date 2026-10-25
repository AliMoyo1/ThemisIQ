"""
A saved report run is the document that was generated, and it is opened only by the person it was generated for
(plans/2026-10-governance-rework/04 section 5, acceptance scenarios 1 and 3).

Before this the output of a run was kept only for a super administrator, and anyone else who opened a run was shown
today's figures under the run's name. These tests pin the other behaviour: a frozen envelope with a hash, a refusal that
is written to the audit log, a blank for a source that could not be read (never a zero), run again linked to the run
before it, and BCM report types that read through the viewer's scope. Expectations are written by hand from the seed
data; every "cannot" has a positive twin.
"""
import asyncio
import json

import pytest

import modules.launcher.routes_reports as reports
from core import rbac
from modules.launcher import report_builders as builders
from modules.launcher.scoped_metrics import run_scope_key
from tests.test_platform_ownership import ORG, _call, _insert, _request, signed_in, world  # noqa: F401


def _raw(coro):
    response = asyncio.run(coro)
    return response.status_code, response.body.decode("utf-8"), response.headers


def _quick(user, report_type, **extra):
    return _call(reports.api_report_quick_run(_request(user, payload={"report_type": report_type, **extra})))


def _open(user, run_id, **query):
    return _call(reports.api_report_run_get(_request(user, query), run_id))


def _bcm_manager(world, tag, uid):
    unit = world.unit.get(tag)
    _insert(world.db, "users", id=uid, username=f"bcm_{tag}_{uid}", email=f"bcm{uid}@example.test",
            full_name=f"BCM {tag}", password_hash="x", org_id=ORG, business_unit_id=unit)
    return {"id": uid, "username": f"bcm_{tag}_{uid}", "org_id": ORG, "business_unit_id": unit,
            "is_super_admin": 0, "roles": [rbac.BCM_MANAGER]}


@pytest.fixture
def continuity(world):
    db, unit = world.db, world.unit
    bia_1 = _insert(db, "bcm_bia_records", process_name="Payroll", business_unit_id=unit["A"], criticality="high")
    _insert(db, "bcm_bia_records", process_name="Billing", business_unit_id=unit["A"], criticality="medium")
    _insert(db, "bcm_bia_records", process_name="Secret B process", business_unit_id=unit["B"])
    plan_a = _insert(db, "bcm_plans", title="Plan A", business_unit_id=unit["A"], status="approved", owner="Ann")
    _insert(db, "bcm_plans", title="Plan B", business_unit_id=unit["B"], status="draft")
    _insert(db, "bcm_bia_plan_links", bia_id=bia_1, plan_id=plan_a)
    _insert(db, "bcm_incidents", title="Outage A", business_unit_id=unit["A"], status="open", severity="high",
            declared_at="2026-10-01 08:00:00")
    _insert(db, "bcm_incidents", title="Fire A", business_unit_id=unit["A"], status="resolved", severity="medium",
            declared_at="2026-09-01 08:00:00", resolved_at="2026-09-01 12:00:00")
    _insert(db, "bcm_incidents", title="Secret B incident", business_unit_id=unit["B"], status="open", severity="low")
    _insert(db, "bcm_exercises", title="Tabletop A", business_unit_id=unit["A"], status="closed",
            objectives_met=3, objectives_total=4, effectiveness_score=80, type="tabletop")
    _insert(db, "bcm_exercises", title="Drill A", business_unit_id=unit["A"], status="planned")
    _insert(db, "bcm_exercises", title="Secret B drill", business_unit_id=unit["B"], status="closed")
    world.bcm_a = _bcm_manager(world, "A", 301)
    world.bcm_b = _bcm_manager(world, "B", 302)
    return world


# ── Frozen runs ─────────────────────────────────────────────────────────────

def test_a_saved_run_shows_the_figures_it_was_generated_with(world):
    dpo = world.users["dpo_a"]
    status, run = _quick(dpo, "privacy_overview")
    assert status == 200 and run["frozen"] is True and run["legacy"] is False
    assert run["result"]["breaches_open"] == 3, "unit A, unit A1 and the organization wide breach"

    _insert(world.db, "sentinel_breaches", ref_number="BR-NEW", title="Late breach", business_unit_id=world.unit["A"])
    status, again = _open(dpo, run["run_id"])
    assert status == 200 and again["result"]["breaches_open"] == 3, "the source changed; the saved run did not"
    assert again["hash"] == run["hash"]


def test_tenant_retention_policy_only_changes_new_report_runs(world):
    manager = world.users["super"]
    reader = world.users["dpo_a"]
    assert _call(reports.api_report_retention_policy_get(_request(manager)))[1]["days"] == 2555
    first = _quick(manager, "privacy_overview")[1]["run_id"]
    before = world.db.execute("SELECT delete_after FROM report_run_retention WHERE run_id=%s", (first,)).fetchone()[0]
    assert _call(reports.api_report_retention_policy_save(_request(reader, payload={
        "days": 365, "reason": "Unauthorised change attempt"})))[0] == 403
    assert _call(reports.api_report_retention_policy_save(_request(manager, payload={
        "days": 365, "reason": "Approved tenant retention schedule"})))[0] == 200
    second = _quick(manager, "privacy_overview")[1]["run_id"]
    after = world.db.execute("SELECT delete_after FROM report_run_retention WHERE run_id=%s", (second,)).fetchone()[0]
    assert before == world.db.execute(
        "SELECT delete_after FROM report_run_retention WHERE run_id=%s", (first,)).fetchone()[0]
    from datetime import date
    assert (date.fromisoformat(before) - date.fromisoformat(after)).days == 2555 - 365


def test_running_it_again_is_a_new_run_linked_to_the_first_with_what_changed(world):
    dpo = world.users["dpo_a"]
    _, first = _quick(dpo, "privacy_overview")
    _insert(world.db, "sentinel_breaches", ref_number="BR-NEW", title="Late breach", business_unit_id=world.unit["A"])
    _, second = _quick(dpo, "privacy_overview")
    assert second["run_id"] != first["run_id"] and second["definition_id"] == first["definition_id"], "one standing definition"
    assert second["previous_run_id"] == first["run_id"]
    assert second["result"]["breaches_open"] == 4
    changes = second["snapshot"]["changes"]
    assert changes["previous_run_id"] == first["run_id"]
    assert [(c["path"], c["was"], c["now"], c["delta"]) for c in changes["changes"]] == [("breaches_open", 3, 4, 1)]
    assert changes["unchanged"] == 3 and changes["scope_changed"] is False and changes["definition_changed"] is False
    assert _open(dpo, first["run_id"])[1]["result"]["breaches_open"] == 3, "the earlier run was not edited"

    status, third = _call(reports.api_report_run_again(_request(dpo), first["run_id"]))
    assert status == 200 and third["previous_run_id"] == first["run_id"], "run again links to the run it was started from"


def test_the_envelope_says_who_when_for_which_scope_and_what_was_read(world):
    dpo = world.users["dpo_a"]
    _, run = _quick(dpo, "privacy_overview")
    snap = run["snapshot"]
    assert snap["run"]["generated_by"] == {"id": dpo["id"], "name": "dpo_a", "username": "dpo_a"}
    assert snap["run"]["report_type"] == "privacy_overview" and snap["run"]["definition_version"]
    assert snap["scope"]["business_unit_ids"] == sorted([world.unit["A"], world.unit["A1"]])
    assert snap["scope"]["whole_organization"] is False
    assert snap["scope"]["label"] == "Unit A and 1 unit below it, and organization-wide records"
    assert snap["scope"]["org_name"] == "org"
    assert {s["source"]: s["state"] for s in snap["sources"]} == {
        "sentinel_ropa": "read", "sentinel_dpias": "read", "sentinel_breaches": "read", "sentinel_dsr": "read"}
    assert snap["complete"] is True and snap["decision_status"]["state"] == "not_reviewed"
    assert snap["inputs"]["sentinel_breaches"] == {"count": 3, "truncated": False}, "identifiers are stored, not returned"
    assert snap["period"]["basis"] == "as_of" and snap["exclusions"]

    _, with_ids = _open(dpo, run["run_id"], records="1")
    ids = with_ids["snapshot"]["inputs"]["sentinel_breaches"]["ids"]
    assert sorted(ids) == sorted(world.rec[("breach", t)] for t in ("A", "A1", "org"))

    whole = _quick(world.users["super"], "privacy_overview")[1]["snapshot"]["scope"]
    assert whole["whole_organization"] is True and whole["label"] == "Whole organization"


# ── Who may open a run ──────────────────────────────────────────────────────

def _denials(world, run_id):
    rows = world.db.execute(
        "SELECT user_id, details FROM audit_log WHERE action = 'report_run_denied' AND entity_id = %s ORDER BY id",
        (run_id,)).fetchall()
    return [(r["user_id"], r["details"]) for r in rows]


def test_only_the_person_it_was_generated_for_may_open_a_run(world):
    dpo, colleague, other_unit = world.users["dpo_a"], world.users["owner_a"], world.users["dpo_b"]
    run_id = _quick(dpo, "privacy_overview")[1]["run_id"]
    assert _open(dpo, run_id)[0] == 200, "the recipient"
    assert _open(world.users["super"], run_id)[0] == 200, "a super administrator"
    assert _open(colleague, run_id)[0] == 404 and _open(other_unit, run_id)[0] == 404
    assert _denials(world, run_id) == [(colleague["id"], "open: not_found"), (other_unit["id"], "open: not_found")]
    assert _call(reports.api_report_runs(_request(colleague)))[1] == [], "and it is not listed for them"
    assert [r["id"] for r in _call(reports.api_report_runs(_request(dpo)))[1]] == [run_id]


def test_losing_access_hides_the_saved_output_and_the_refusal_is_audited(world):
    dpo = world.users["dpo_a"]
    run_id = _quick(dpo, "privacy_overview")[1]["run_id"]
    assert _open(dpo, run_id)[0] == 200

    moved = {**dpo, "business_unit_id": world.unit["B"]}
    status, refused = _open(moved, run_id)
    assert status == 403 and refused["reason"] == "access_changed" and "result" not in refused and "snapshot" not in refused
    assert _denials(world, run_id) == [(dpo["id"], "open: access_changed")]
    assert _call(reports.api_report_runs(_request(moved)))[1] == []

    restored = {**dpo}
    assert _open(restored, run_id)[0] == 200, "the saved run answers to the access the person has, not to a flag"
    assert run_scope_key(restored) == run_scope_key(dpo)


def test_a_run_that_was_changed_in_the_database_is_refused(world):
    dpo = world.users["dpo_a"]
    run_id = _quick(dpo, "privacy_overview")[1]["run_id"]
    row = world.db.execute("SELECT result_json FROM report_runs WHERE id = %s", (run_id,)).fetchone()
    tampered = row["result_json"].replace('"breaches_open":3', '"breaches_open":0')
    assert tampered != row["result_json"]
    world.db.execute("UPDATE report_runs SET result_json = %s WHERE id = %s", (tampered, run_id))
    world.db.commit()
    status, body = _open(dpo, run_id)
    assert status == 409 and body["reason"] == "integrity" and "result" not in body
    assert _raw(reports.api_report_run_export(_request(dpo), run_id))[0] == 409
    logged = world.db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'report_run_integrity_failed' AND entity_id = %s", (run_id,)).fetchone()
    assert logged[0] == 2


def test_a_run_saved_before_reports_were_frozen_is_labelled_and_never_recomputed(world):
    dpo, admin = world.users["dpo_a"], world.users["super"]
    definition = _insert(world.db, "report_definitions", name="Old", report_type="privacy_overview", created_by=dpo["id"])
    kept_nothing = _insert(world.db, "report_runs", definition_id=definition, status="completed",
                           triggered_by=run_scope_key(dpo), completed_at="2026-01-01 00:00:00")
    status, body = _open(dpo, kept_nothing)
    assert status == 200 and body["legacy"] is True and body["frozen"] is False and body["result"] is None
    assert "not recomputed" in body["legacy_note"]
    assert _raw(reports.api_report_run_export(_request(dpo), kept_nothing))[0] == 409

    flat = _insert(world.db, "report_runs", definition_id=definition, status="completed",
                   triggered_by=run_scope_key(admin), result_json=json.dumps({"breaches_open": 9}))
    status, body = _open(admin, flat)
    assert status == 200 and body["legacy"] is True and body["result"] == {"breaches_open": 9}


# ── A figure is blank, not zero, when it was not read ───────────────────────

def test_a_module_the_person_may_not_open_is_left_out_and_said_so(world):
    status, run = _quick(world.users["employee_a"], "privacy_overview")
    assert status == 200
    assert run["result"] == {"ropa_count": None, "dpia_count": None, "breaches_open": None, "dsr_open": None}
    assert {s["state"] for s in run["snapshot"]["sources"]} == {"not_in_scope"}
    assert run["snapshot"]["complete"] is True
    assert any("Breaches are not included" in text for text in run["snapshot"]["limitations"])
    visible = _quick(world.users["dpo_a"], "privacy_overview")[1]["result"]
    assert visible["breaches_open"] == 3, "its positive twin: the same report for a person who may open it"


def test_a_source_that_fails_is_blank_in_the_run_and_the_run_says_it_is_incomplete(world, monkeypatch):
    real = builders.scoped_count

    def failing(db, user, table, condition="", params=()):
        if table == "sentinel_breaches":
            raise RuntimeError("could not read breaches")
        return real(db, user, table, condition, params)

    monkeypatch.setattr(builders, "scoped_count", failing)
    _, run = _quick(world.users["dpo_a"], "privacy_overview")
    assert run["result"]["breaches_open"] is None, "not a zero"
    assert run["snapshot"]["complete"] is False
    states = {s["source"]: s["state"] for s in run["snapshot"]["sources"]}
    assert states["sentinel_breaches"] == "unavailable" and states["sentinel_ropa"] == "read"
    assert any("could not be read" in text for text in run["snapshot"]["limitations"])


def test_the_risk_report_of_a_super_administrator_counts_what_the_register_page_counts(world):
    _insert(world.db, "erm_enterprise_risks", title="ERM risk org", likelihood=5, impact=5, business_unit_id=None)
    _insert(world.db, "risk_register", title="Platform risk", likelihood=4, impact=4, risk_level="high",
            source_module="sentinel", business_unit_id=world.unit["A"])
    got = builders.build(world.db, world.users["super"], "risk_report").result
    # the register page's own sets: the platform register (1) and the enterprise risks (the world's own, medium, and the new one)
    assert got["total_open"] == 3 and got["by_module"] == {"sentinel": 1, "erm": 2}
    assert got["by_level"] == {"critical": 1, "high": 1, "medium": 1, "low": 0}


# ── Business continuity report types ────────────────────────────────────────

def test_every_continuity_report_type_the_page_asks_for_is_registered_and_runs(continuity):
    for report_type in ("bcm_coverage", "bcm_plans", "bcm_incidents", "bcm_exercises", "bcm_summary"):
        assert report_type in reports.REPORT_TYPES, report_type
        status, run = _quick(continuity.bcm_a, report_type)
        assert status == 200 and run["frozen"] is True, report_type
        assert run["snapshot"]["complete"] is True, report_type


def test_the_continuity_reports_read_through_the_viewers_units(continuity):
    a = _quick(continuity.bcm_a, "bcm_coverage")[1]["result"]
    assert (a["analyses"], a["with_plan"], a["without_plan"], a["coverage_pct"]) == (2, 1, 1, 50)
    assert [u["name"] for u in a["uncovered"]] == ["Billing"]
    b = _quick(continuity.bcm_b, "bcm_coverage")[1]["result"]
    assert (b["analyses"], b["with_plan"], b["coverage_pct"]) == (1, 0, 0)
    assert [u["name"] for u in b["uncovered"]] == ["Secret B process"]
    assert "Secret B" not in json.dumps(a)

    plans = _quick(continuity.bcm_a, "bcm_plans")[1]["result"]
    assert plans["plans"] == 1 and plans["by_status"] == {"approved": 1}
    assert [p["title"] for p in plans["list"]] == ["Plan A"]

    incidents = _quick(continuity.bcm_a, "bcm_incidents")[1]["result"]
    assert (incidents["incidents"], incidents["active"]) == (2, 1)
    assert incidents["resolved_with_times"] == 1 and incidents["average_hours_to_resolve"] == 4.0
    assert {i["title"] for i in incidents["list"]} == {"Outage A", "Fire A"}

    exercises = _quick(continuity.bcm_a, "bcm_exercises")[1]["result"]
    assert (exercises["exercises"], exercises["completed"], exercises["completion_pct"]) == (2, 1, 50)
    assert exercises["scored"] == 1 and exercises["average_effectiveness"] == 80.0
    assert "Secret B" not in json.dumps([plans, incidents, exercises])

    whole = _quick(continuity.users["super"], "bcm_coverage")[1]["result"]
    assert whole["analyses"] == 3, "its positive twin: the whole organization sees all three"


def test_no_analysis_recorded_is_not_measured_and_a_person_without_continuity_access_gets_blanks(world):
    manager = _bcm_manager(world, "A", 303)
    got = _quick(manager, "bcm_coverage")[1]
    assert got["result"]["analyses"] == 0 and got["result"]["coverage_pct"] is None, "zero analyses, nothing to measure"
    assert any("not measured" in text for text in got["snapshot"]["limitations"])

    blind = _quick(world.users["dpo_a"], "bcm_plans")[1]
    assert blind["result"]["plans"] is None and blind["result"]["list"] is None
    assert blind["snapshot"]["sources"][0]["state"] == "not_in_scope"


# ── Presets ─────────────────────────────────────────────────────────────────

def test_the_board_report_has_no_record_lists_and_states_what_it_cannot_say(continuity):
    _insert(continuity.db, "risk_register", title="Named platform risk", likelihood=5, impact=5, risk_level="critical",
            business_unit_id=continuity.unit["A"], source_module="sentinel")
    board = _quick(continuity.users["dpo_a"], "preset_board")[1]
    sections = board["result"]["sections"]
    assert set(sections) == {"executive_brief", "risk_report", "privacy_overview", "audit_status"}, \
        "the continuity section is left out: this person may not open it"
    assert sections["risk_report"]["top_risks"] is None and sections["risk_report"]["by_level"]["critical"] == 1
    assert "Named platform risk" not in json.dumps(board["result"])
    text = " ".join(board["snapshot"]["limitations"])
    assert "not an independent assurance rating" in text and "bcm readiness section is left out" in text

    specialist = _quick(continuity.users["dpo_a"], "preset_specialist")[1]
    risks = specialist["result"]["sections"]["risk_report"]["top_risks"]
    assert risks[0]["title"] == "Named platform risk", "the specialist report keeps the record lists, highest score first"


def test_a_preset_is_a_template_over_the_same_definitions(continuity):
    """The section figures equal what the standalone report of the same type returns for the same person."""
    person = continuity.bcm_a
    preset = _quick(person, "preset_management")[1]["result"]["sections"]
    assert preset["bcm_readiness"] == _quick(person, "bcm_readiness")[1]["result"]
    assert preset["bcm_readiness"] == {"plans": 1, "active_incidents": 1, "exercises_completed": 1}


def test_a_case_report_freezes_the_connected_view_and_hides_a_record_the_person_may_not_open(world):
    db, unit = world.db, world.unit
    process = _insert(db, "business_processes", name="Onboarding", business_unit_id=unit["A"], is_active=1)
    ropa = _insert(db, "sentinel_ropa", ref_number="RP-A", processing_name="Onboarding records", business_unit_id=unit["A"])
    _insert(db, "cross_module_links", source_module="sentinel", source_type="ropa", source_id=ropa,
            target_module="governance", target_type="process", target_id=process, relationship="records",
            provenance="manual", status="confirmed")
    subject = {"module": "governance", "entity_type": "process", "entity_id": process}
    status, run = _quick(world.users["dpo_a"], "preset_case", subject=subject)
    assert status == 200 and run["frozen"] is True
    assert run["result"]["entity"]["title"] == "Onboarding"
    titles = [c["title"] for section in run["result"]["connections"] for c in section["items"]]
    assert titles == ["Onboarding records"]
    assert run["report_name"].startswith("Case report: Onboarding")
    assert run["snapshot"]["inputs"]["connected_records"] == {"count": 2, "truncated": False}
    kept = _open(world.users["dpo_a"], run["run_id"], records="1")[1]["snapshot"]["inputs"]["connected_records"]["ids"]
    assert kept[0] == f"governance/process/{process}" and kept[1] == f"sentinel/ropa/{ropa}"

    status, hidden = _quick(world.users["dpo_b"], "preset_case", subject=subject)
    assert status == 404 and "Onboarding" not in json.dumps(hidden), "a hidden record answers like a missing one"
    assert _quick(world.users["dpo_a"], "preset_case")[0] == 400, "a case report needs a record"


def test_definitions_check_their_parameters(world):
    dpo = world.users["dpo_a"]
    bad = _call(reports.api_report_definition_create(_request(dpo, payload={"name": "x", "report_type": "preset_case"})))
    assert bad[0] == 400
    unknown = _call(reports.api_report_definition_create(_request(dpo, payload={"name": "x", "report_type": "nope"})))
    assert unknown[0] == 400
    listy = _call(reports.api_report_definition_create(
        _request(dpo, payload={"name": "x", "report_type": "risk_report", "parameters": [1]})))
    assert listy[0] == 400
    good = _call(reports.api_report_definition_create(_request(dpo, payload={"name": "x", "report_type": "risk_report"})))
    assert good[0] == 201


# ── Export ──────────────────────────────────────────────────────────────────

def test_the_export_is_the_frozen_run_and_text_that_looks_like_a_formula_is_written_as_text(world):
    dpo = world.users["dpo_a"]
    _insert(world.db, "risk_register", title="=HYPERLINK(\"http://evil.example\")", likelihood=4, impact=5,
            risk_level="critical", business_unit_id=world.unit["A"], source_module="sentinel")
    run = _quick(dpo, "risk_report")[1]
    _insert(world.db, "risk_register", title="Added after", likelihood=1, impact=1, risk_level="low",
            business_unit_id=world.unit["A"], source_module="sentinel")
    status, body, headers = _raw(reports.api_report_run_export(_request(dpo), run["run_id"]))
    assert status == 200 and headers["content-type"].startswith("text/csv")
    assert "attachment" in headers["content-disposition"] and headers["cache-control"] == "no-store"
    assert "'=HYPERLINK" in body and ",=HYPERLINK" not in body and "\n=HYPERLINK" not in body
    assert "Added after" not in body, "the file is the frozen run, not today's register"
    assert 'Scope,"Unit A and 1 unit below it, and organization-wide records"' in body
    assert "Whole organization" not in body
    assert _raw(reports.api_report_run_export(_request(world.users["dpo_b"]), run["run_id"]))[0] == 404
    exported = world.db.execute("SELECT user_id FROM audit_log WHERE action = 'report_run_export'").fetchall()
    assert [r["user_id"] for r in exported] == [dpo["id"]]


# ── The executive summary ───────────────────────────────────────────────────

def test_the_executive_figures_are_a_frozen_run_even_when_ai_is_off(world, monkeypatch):
    from core import ai_client
    monkeypatch.setattr(ai_client, "is_configured", lambda: False)
    status, body = _call(reports.api_executive_summary(_request(world.users["dpo_a"])))
    assert status == 200 and body["frozen"] is True and body["narrative"] is None
    assert body["narrative_state"] == "unavailable" and "not configured" in body["narrative_note"]
    assert body["stats"]["breaches_open"] == 3 and body["stats"]["compliance_pct"] is None, "no controls: not measured"
    saved = _open(world.users["dpo_a"], body["run_id"])[1]
    assert saved["frozen"] is True and saved["result"] == body["stats"] and saved["snapshot"]["narrative"] is None


def test_a_narrative_is_a_draft_kept_with_its_run_and_given_only_figures(world, monkeypatch):
    from core import ai_client
    seen = {}

    def write(messages, system="", max_tokens=0, model="", **kw):
        seen["prompt"] = messages[0]["content"]
        seen["feature"] = kw.get("feature")
        return {"text": "First paragraph.\n\nSecond paragraph.", "model": "test-model"}

    monkeypatch.setattr(ai_client, "is_configured", lambda: True)
    monkeypatch.setattr(ai_client, "create_message_full", write)
    _insert(world.db, "sentinel_breaches", ref_number="BR-X", title="Needle breach title", business_unit_id=world.unit["A"])
    status, body = _call(reports.api_executive_summary(_request(world.users["dpo_a"])))
    assert status == 200 and body["narrative"].startswith("First paragraph.")
    assert body["narrative_state"] == "draft" and seen["feature"] == "launcher.api_executive_summary"
    assert "Needle breach title" not in seen["prompt"], "the model is given figures, never a record title"
    saved = _open(world.users["dpo_a"], body["run_id"])[1]["snapshot"]["narrative"]
    assert saved["state"] == "draft" and saved["model"] == "test-model" and saved["approval"] == "not_reviewed"


def test_a_refused_or_failed_narrative_leaves_the_figures_complete(world, monkeypatch):
    from core import ai_client
    from core.ai_policy import AIPolicyError

    def refuse(*a, **kw):
        raise AIPolicyError("disabled", "This organization has switched off AI summaries.")

    monkeypatch.setattr(ai_client, "is_configured", lambda: True)
    monkeypatch.setattr(ai_client, "create_message_full", refuse)
    status, body = _call(reports.api_executive_summary(_request(world.users["dpo_a"])))
    assert status == 200 and body["narrative"] is None and "switched off AI summaries" in body["narrative_note"]
    assert body["stats"]["breaches_open"] == 3

    def boom(*a, **kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(ai_client, "create_message_full", boom)
    status, body = _call(reports.api_executive_summary(_request(world.users["dpo_a"])))
    assert status == 200 and body["narrative"] is None and "could not be written" in body["narrative_note"]


# ── The engine is not a second store ────────────────────────────────────────

def test_report_runs_keep_one_envelope_and_a_hash_of_its_exact_text(world):
    import hashlib
    dpo = world.users["dpo_a"]
    run_id = _quick(dpo, "audit_status")[1]["run_id"]
    row = world.db.execute("SELECT result_json, snapshot_hash, previous_run_id FROM report_runs WHERE id = %s",
                           (run_id,)).fetchone()
    assert row["snapshot_hash"] == hashlib.sha256(row["result_json"].encode("utf-8")).hexdigest()
    assert json.loads(row["result_json"])["format"] == 1 and row["previous_run_id"] is None
