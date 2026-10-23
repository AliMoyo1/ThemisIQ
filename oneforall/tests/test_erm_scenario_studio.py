"""
Scenario Studio rebuild (plans/2026-10-scenario-studio/plan.md): the pieces around the impact engine.

Service level. The engine's own numbers are covered by tests/test_erm_scenarios.py; the HTTP layer by
tests/ui/test_erm_scenario_studio_routes.py. Here: the new fields, shock provenance, the headline sentence, the
scoped candidate picker, the AI proposals (provider stubbed, every answer checked), and how the scenario is registered
with the rest of the platform.
"""
import json

import pytest

from core import ai_client
from core.ai_client import AIUnavailable
from modules.erm import scenario_ai as sai
from modules.erm import scenario_support as sup
from modules.erm import scenario_templates as tpl
from modules.erm import scenarios as sv


def _user(db, uid, username=None, active=1):
    username = username or f"studio{uid}"
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, is_active) VALUES (%s,%s,%s,%s,'x',%s)",
        (uid, username, f"{username}@x.com", username, active),
    )
    db.commit()


def _actor(uid, business_unit_id=None, is_super_admin=False):
    return {"id": uid, "business_unit_id": business_unit_id, "is_super_admin": is_super_admin}


def _bu(db, name):
    db.execute("INSERT INTO business_units (name) VALUES (%s)", (name,))
    db.commit()
    return db.execute("SELECT id FROM business_units WHERE name=%s", (name,)).fetchone()["id"]


def _risk(db, title, likelihood=3, impact=3, category="operational", bu=None):
    db.execute(
        "INSERT INTO erm_enterprise_risks (title, status, likelihood, impact, category, business_unit_id) "
        "VALUES (%s,'open',%s,%s,%s,%s)", (title, likelihood, impact, category, bu))
    db.commit()
    return db.execute("SELECT id FROM erm_enterprise_risks WHERE title=%s ORDER BY id DESC LIMIT 1", (title,)).fetchone()["id"]


@pytest.fixture
def actor(test_db):
    _user(test_db, 1)
    return _actor(1, is_super_admin=True)


# ── new fields ───────────────────────────────────────────────────────────────

def test_a_scenario_keeps_its_type_owner_and_review_date(test_db, actor):
    _user(test_db, 2, "owner2")
    sid = sv.create_scenario({"title": "S", "scenario_type": "Cyber attack", "owner_id": 2, "review_date": "2027-01-31"}, actor)
    got = sv.get_scenario(sid)
    assert (got["scenario_type"], got["owner_id"], got["review_date"]) == ("Cyber attack", 2, "2027-01-31")
    sv.update_scenario(sid, {"review_date": "2027-02-28", "scenario_type": "Data breach"}, actor)
    got = sv.get_scenario(sid)
    assert (got["scenario_type"], got["review_date"], got["owner_id"]) == ("Data breach", "2027-02-28", 2)


@pytest.mark.parametrize("bad", ["31/01/2027", "tomorrow", "2027-13-40"])
def test_a_review_date_must_be_a_real_day(test_db, actor, bad):
    with pytest.raises(sv.ScenarioError):
        sv.create_scenario({"title": "S", "review_date": bad}, actor)


def test_the_owner_must_be_an_active_user(test_db, actor):
    _user(test_db, 3, "gone", active=0)
    for bad in (3, 999, "abc"):
        with pytest.raises(sv.ScenarioError):
            sv.create_scenario({"title": "S", "owner_id": bad}, actor)


def test_creating_and_updating_announce_themselves(test_db, actor, monkeypatch):
    seen = []
    monkeypatch.setattr(sv, "emit", lambda *a, **k: seen.append(a[0]))
    sid = sv.create_scenario({"title": "S"}, actor)
    sv.update_scenario(sid, {"status": "active"}, actor)
    assert seen == ["erm.scenario.created", "erm.scenario.updated"]


# ── shock provenance ─────────────────────────────────────────────────────────

def test_a_shock_can_say_who_proposed_it_and_why(test_db, actor):
    sid = sv.create_scenario({"title": "S"}, actor)
    rid = _risk(test_db, "R")
    sv.add_scenario_link(sid, "risk", rid, {"likelihood_override": 5, "source": "ai", "reason": "  Recent outages  "}, actor)
    link = sv.list_scenario_links(sid)[0]
    assert link["delta"] == {"likelihood_override": 5, "reason": "Recent outages", "source": "ai"}


def test_provenance_is_validated_and_never_changes_the_numbers(test_db, actor):
    sid = sv.create_scenario({"title": "S"}, actor)
    rid = _risk(test_db, "R", 2, 3)
    with pytest.raises(sv.ScenarioError):
        sv.add_scenario_link(sid, "risk", rid, {"source": "oracle"}, actor)
    with pytest.raises(sv.ScenarioError):
        sv.add_scenario_link(sid, "risk", rid, {"reason": 7}, actor)
    sv.add_scenario_link(sid, "risk", rid, {"likelihood_override": 4}, actor)
    plain = sv.compute_scenario_impact(sid)["per_risk"][0]["scenario"]
    sv.add_scenario_link(sid, "risk", rid, {"likelihood_override": 4, "source": "ai", "reason": "x"}, actor)
    assert sv.compute_scenario_impact(sid)["per_risk"][0]["scenario"] == plain


def test_a_cleared_override_means_keep_the_baseline(test_db, actor):
    sid = sv.create_scenario({"title": "S"}, actor)
    rid = _risk(test_db, "R", 2, 3)
    sv.add_scenario_link(sid, "risk", rid, {"likelihood_override": None, "impact_override": None, "source": "human"}, actor)
    row = sv.compute_scenario_impact(sid)["per_risk"][0]
    assert row["scenario"]["likelihood"] == row["baseline"]["likelihood"] == 2


# ── baseline and headline ────────────────────────────────────────────────────

def test_a_scenario_that_changes_nothing_shows_no_movement_even_without_a_stored_residual(test_db, actor):
    """A risk that was never recalculated has no stored residual score. The scenario must not compare its calculated
    residual with the inherent score and report an improvement."""
    sid = sv.create_scenario({"title": "S"}, actor)
    rid = _risk(test_db, "Never recalculated", 3, 3)
    sv.add_scenario_link(sid, "risk", rid, {}, actor)
    impact = sv.compute_scenario_impact(sid)
    row = impact["per_risk"][0]
    assert row["baseline"]["rrr"] == row["scenario"]["rrr"] is not None
    assert impact["baseline_totals"] == impact["scenario_totals"]
    head = sup.headline(impact)
    assert head["worse"] == head["band_up"] == head["new_breaches"] == 0
    assert head["sentence"].startswith("No linked risk changes yet")


def test_the_headline_counts_what_got_worse(test_db, actor):
    sid = sv.create_scenario({"title": "S"}, actor)
    a, b = _risk(test_db, "A", 2, 2), _risk(test_db, "B", 3, 3)
    sv.add_scenario_link(sid, "risk", a, {"likelihood_override": 5, "impact_override": 5}, actor)
    sv.add_scenario_link(sid, "risk", b, {}, actor)
    head = sup.headline(sv.compute_scenario_impact(sid))
    assert (head["risks"], head["worse"]) == (2, 1)
    assert "1 of 2 risks get worse" in head["sentence"]
    assert head["band_up"] == 1 and "moves to a higher band" in head["sentence"]


def test_the_headline_asks_for_a_risk_when_there_is_none(test_db, actor):
    sid = sv.create_scenario({"title": "S"}, actor)
    assert "Add at least one risk" in sup.headline(sv.compute_scenario_impact(sid))["sentence"]


# ── candidates ───────────────────────────────────────────────────────────────

def test_candidates_only_offer_what_the_caller_may_link(test_db):
    _user(test_db, 5)
    a, b = _bu(test_db, "Unit A"), _bu(test_db, "Unit B")
    mine, theirs, org_wide = _risk(test_db, "Mine", bu=a), _risk(test_db, "Theirs", bu=b), _risk(test_db, "Org wide")
    scoped = _actor(5, business_unit_id=a)
    ids = {r["id"] for r in sup.candidates("risk", scoped)}
    assert mine in ids and org_wide in ids and theirs not in ids
    assert theirs in {r["id"] for r in sup.candidates("risk", _actor(5, is_super_admin=True))}


def test_candidates_rank_template_matches_first_and_filter_by_text(test_db, actor):
    _risk(test_db, "Zebra paperwork")
    _risk(test_db, "Ransomware exposure on servers", category="cyber")
    rows = sup.candidates("risk", actor, template_id="ransomware")
    assert rows[0]["title"] == "Ransomware exposure on servers" and rows[0]["suggested"] is True
    assert [r["title"] for r in sup.candidates("risk", actor, query="zebra")] == ["Zebra paperwork"]
    with pytest.raises(sv.ScenarioError):
        sup.candidates("vendor", actor)


def test_templates_are_complete_and_use_the_known_types():
    assert len(tpl.TEMPLATES) == 8
    assert len({t["id"] for t in tpl.TEMPLATES}) == 8
    for t in tpl.TEMPLATES:
        assert t["type"] in tpl.SCENARIO_TYPES and t["title"] and t["assumptions"] and t["horizon"]
    assert all("match" not in t for t in tpl.public_templates())


def test_context_is_empty_without_loss_events(test_db, actor):
    sid = sv.create_scenario({"title": "S"}, actor)
    assert sup.context(sid, actor)["orm_events"]["count"] == 0


# ── actions in other modules ─────────────────────────────────────────────────

def test_an_action_becomes_a_task_that_remembers_the_scenario(test_db, actor):
    sid = sv.create_scenario({"title": "Outage"}, actor)
    task_id = sup.create_action(sid, {"title": "Add a standby supplier", "priority": "high", "due_date": "2027-03-01"}, actor)
    row = test_db.execute("SELECT * FROM task_board WHERE id=%s", (task_id,)).fetchone()
    assert (row["module"], row["entity_type"], row["entity_id"], row["priority"]) == ("erm", "scenario", sid, "high")


def test_an_action_needs_a_title_and_a_real_priority_and_date(test_db, actor):
    sid = sv.create_scenario({"title": "Outage"}, actor)
    for bad in ({"title": " "}, {"title": "t", "priority": "urgent"}, {"title": "t", "due_date": "soon"}):
        with pytest.raises(sv.ScenarioError):
            sup.create_action(sid, bad, actor)


def test_a_scoped_user_cannot_raise_an_action_on_another_units_scenario(test_db):
    _user(test_db, 6)
    a, b = _bu(test_db, "Unit A"), _bu(test_db, "Unit B")
    owner = _actor(6, is_super_admin=True)
    sid = sv.create_scenario({"title": "Theirs", "business_unit_id": b}, owner)
    with pytest.raises(sv.ScenarioError):
        sup.create_action(sid, {"title": "t"}, _actor(6, business_unit_id=a))


def test_a_scenario_is_a_registered_related_record_with_evidence_support():
    from modules.evidence import routes as evidence
    from modules.governance import entity_scope as scope
    assert scope.is_linkable(("erm", "scenario"))
    assert ("erm", "scenario") in evidence._ENTITY_RESOLVERS
    from modules.governance.entity360 import KIND_LABELS
    assert KIND_LABELS[("erm", "scenario")] == "Risk scenario"


# ── modelling a scenario on a real record ────────────────────────────────────

def test_a_scenario_can_only_be_modelled_on_a_known_kind(test_db, actor):
    with pytest.raises(sv.ScenarioError):
        sup.seed_from_record("aria", "control", 1, actor)
    with pytest.raises(sv.ScenarioError):
        sup.seed_from_record("bcm", "incident", 9999, actor)


# ── AI proposals ─────────────────────────────────────────────────────────────

@pytest.fixture
def ai(monkeypatch):
    monkeypatch.setattr(ai_client, "is_configured", lambda: True)
    state = {"reply": "{}", "prompts": []}

    def fake(messages, **kwargs):
        state["prompts"].append((messages[0]["content"], kwargs))
        return state["reply"] if isinstance(state["reply"], str) else json.dumps(state["reply"])
    monkeypatch.setattr(sai, "create_message", fake)
    return state


def test_a_typed_sentence_must_be_a_sentence_without_personal_details():
    for bad in ("short", "x" * 601, "email me at jane.doe@example.com about it", "account 1234 5678 9012 3456 is down"):
        with pytest.raises(sv.ScenarioError):
            sai.clean_sentence(bad)
    assert sai.clean_sentence("  our payment processor is down for five days ") == "our payment processor is down for five days"


def test_the_draft_only_links_records_the_caller_was_offered(test_db, actor, ai):
    mine = _risk(test_db, "Payment processor outage")
    ai["reply"] = {"title": "Processor down", "description": "d", "assumptions": "a", "horizon": "3 months",
                   "scenario_type": "Not a real type",
                   "links": [{"link_type": "risk", "link_id": mine, "reason": "directly affected"},
                             {"link_type": "risk", "link_id": 424242, "reason": "invented"},
                             {"link_type": "control", "link_id": mine, "reason": "wrong type"},
                             {"link_type": "vendor", "link_id": 1, "reason": "not allowed"}]}
    out = sai.draft("our main payment processor is down for five days", actor)
    assert [(l["link_type"], l["link_id"]) for l in out["links"]] == [("risk", mine)]
    assert out["scenario_type"] == "Other" and out["source"] == "ai"
    assert "<user_input>" in ai["prompts"][0][0]
    assert ai["prompts"][0][1]["feature"] == "erm.scenario_draft"


def test_suggested_shocks_are_checked_by_the_engines_own_rules(test_db, actor, ai):
    sid = sv.create_scenario({"title": "S"}, actor)
    good, other = _risk(test_db, "Good", 2, 2), _risk(test_db, "Other", 2, 2)
    sv.add_scenario_link(sid, "risk", good, {}, actor)
    sv.add_scenario_link(sid, "risk", other, {}, actor)
    ai["reply"] = {"shocks": [
        {"link_type": "risk", "link_id": good, "likelihood": 4, "impact": 5, "reason": "history of incidents"},
        {"link_type": "risk", "link_id": other, "likelihood": 9, "impact": 2, "reason": "out of range"},
        {"link_type": "risk", "link_id": 777, "likelihood": 3, "impact": 3, "reason": "not linked"},
    ]}
    out = sai.shocks(sid, actor)
    assert [s["link_id"] for s in out["shocks"]] == [good]
    assert out["shocks"][0]["delta"] == {"likelihood_override": 4, "impact_override": 5,
                                         "source": "ai", "reason": "history of incidents"}
    # The proposal is not applied: the scenario still has no overrides.
    assert all(l["delta"] == {} for l in sv.list_scenario_links(sid))


def test_gaps_only_name_unlinked_records(test_db, actor, ai):
    sid = sv.create_scenario({"title": "S"}, actor)
    linked, free = _risk(test_db, "Linked"), _risk(test_db, "Free")
    sv.add_scenario_link(sid, "risk", linked, {}, actor)
    ai["reply"] = {"suggestions": [{"link_type": "risk", "link_id": linked, "reason": "already there"},
                                   {"link_type": "risk", "link_id": free, "reason": "same supplier"}]}
    out = sai.gaps(sid, actor)
    assert [s["link_id"] for s in out["suggestions"]] == [free]


def test_an_explanation_must_cite_the_result_it_explains(test_db, actor, ai):
    sid = sv.create_scenario({"title": "S"}, actor)
    rid = _risk(test_db, "R", 2, 2)
    sv.add_scenario_link(sid, "risk", rid, {"likelihood_override": 5}, actor)
    ai["reply"] = {"summary": "Worse.", "points": [{"text": "R rises", "ref": f"risk:{rid}"},
                                                   {"text": "Made up", "ref": "risk:31337"}]}
    out = sai.explain(sid, actor)
    assert [p["ref"] for p in out["points"]] == [f"risk:{rid}"]
    ai["reply"] = {"summary": "Worse.", "points": [{"text": "Made up", "ref": "risk:31337"}]}
    with pytest.raises(AIUnavailable):
        sai.explain(sid, actor)


def test_explain_and_shocks_need_something_to_work_on(test_db, actor, ai):
    sid = sv.create_scenario({"title": "S"}, actor)
    with pytest.raises(sv.ScenarioError):
        sai.explain(sid, actor)
    with pytest.raises(sv.ScenarioError):
        sai.shocks(sid, actor)


def test_challenge_questions_are_capped_and_typed(test_db, actor, ai):
    sid = sv.create_scenario({"title": "S"}, actor)
    ai["reply"] = {"questions": [{"field": "horizon", "text": f"q{i}"} for i in range(9)] + [{"field": "weird", "text": "odd"}, {"text": ""}]}
    out = sai.challenge(sid, actor)
    assert len(out["questions"]) == 6 and out["questions"][0]["field"] == "horizon"


def test_an_unreadable_answer_is_refused_not_invented(test_db, actor, ai):
    ai["reply"] = "I could not do that"
    with pytest.raises(AIUnavailable):
        sai.draft("our main payment processor is down for five days", actor)


def test_when_the_assistant_is_off_nothing_is_generated(test_db, actor, monkeypatch):
    monkeypatch.setattr(ai_client, "is_configured", lambda: False)
    with pytest.raises(AIUnavailable):
        sai.draft("our main payment processor is down for five days", actor)


def test_another_units_scenario_is_not_reachable_through_the_ai(test_db):
    _user(test_db, 8)
    a, b = _bu(test_db, "Unit A"), _bu(test_db, "Unit B")
    sid = sv.create_scenario({"title": "Theirs", "business_unit_id": b}, _actor(8, is_super_admin=True))
    for run in (sai.shocks, sai.gaps, sai.explain, sai.challenge):
        with pytest.raises(sv.ScenarioError):
            run(sid, _actor(8, business_unit_id=a))


def test_the_owner_must_belong_to_the_actors_organization(test_db):
    org_a = test_db.execute("INSERT INTO organizations (name, slug, plan, status) VALUES ('A','owner-a','enterprise','active') RETURNING id").fetchone()["id"]
    org_b = test_db.execute("INSERT INTO organizations (name, slug, plan, status) VALUES ('B','owner-b','enterprise','active') RETURNING id").fetchone()["id"]
    for uid, org in ((20, org_a), (21, org_b)):
        test_db.execute("INSERT INTO users (id, username, email, full_name, password_hash, is_active, org_id) VALUES (%s,%s,%s,%s,'x',1,%s)",
                        (uid, f"own{uid}", f"own{uid}@x.com", f"own{uid}", org))
    test_db.commit()
    actor_a = {"id": 20, "org_id": org_a, "business_unit_id": None, "is_super_admin": True}
    assert sv.get_scenario(sv.create_scenario({"title": "Mine", "owner_id": 20}, actor_a))["owner_id"] == 20
    with pytest.raises(sv.ScenarioError):
        sv.create_scenario({"title": "Theirs", "owner_id": 21}, actor_a)
