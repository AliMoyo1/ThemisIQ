"""
The outstanding items of one AI use (plans/2026-10-governance-rework/01 section 5).

Written by hand. Every line is read from the owning module's own record and says its state in the five words the plan
uses; a source that cannot be read is "could not be read" and never "done"; a required step blocks a decision until it is
done or judged not applicable with a reason; and a model never sets a state (there is none in this module).
"""
import pytest

from modules.ai_governance import evaluations, guidance, oversight, outstanding, service
from modules.governance import relationships
from tests.test_ai_governance_decisions import ask, decide, resolve_provider_review
from tests.test_ai_governance_evaluations import RUN
from tests.test_ai_governance_oversight import COMPLETE
from tests.test_ai_governance_service import FULL, approve_new, commit, fail, roles, submitted, user  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401

KEYS = ["facts", "owner", "aiia", "dpia", "ropa", "vendor", "aims", "policy", "evaluation", "oversight", "proof",
        "continuity", "regulatory", "decision"]


@pytest.fixture
def system(world, roles):
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    return world


def lines(world, name="super"):
    got = outstanding.get_outstanding(world.db, user(world, name), world.app)
    return {l["key"]: l for l in got["lines"]}


def state(world, key, name="super"):
    return lines(world, name)[key]["state"]


def test_a_fresh_use_lists_every_line_in_a_fixed_order_with_the_state_the_records_show(system):
    got = outstanding.get_outstanding(system.db, user(system, "super"), system.app)
    assert [l["key"] for l in got["lines"]] == KEYS
    by = {l["key"]: l for l in got["lines"]}
    assert by["facts"]["state"] == "complete" and by["owner"]["state"] == "complete"
    assert by["dpia"]["state"] == by["ropa"]["state"] == by["aims"]["state"] == "not_applicable"
    assert by["aiia"]["state"] == by["vendor"]["state"] == by["policy"]["state"] == "not_yet_assessed"
    for key in ("evaluation", "oversight", "proof", "continuity", "decision"):
        assert by[key]["state"] == "not_yet_assessed", key
    assert by["regulatory"]["state"] == "not_yet_assessed" and "No intended jurisdiction" in by["regulatory"]["reason"]
    assert all(l["rule_version"] == "o1" and l["state_label"] for l in got["lines"])
    assert got["counts"]["not_applicable"] == 3 and "approves" in got["note"]


def test_only_a_required_step_blocks_a_decision_and_a_reviewers_judgement_clears_it(system):
    first = outstanding.get_outstanding(system.db, user(system, "super"), system.app)
    assert first["blocking"] == ["vendor"] and first["ready_for_decision"] is False
    assert {l["key"] for l in first["lines"] if l["blocks_decision"]} == {"vendor"}
    resolve_provider_review(system)
    cleared = outstanding.get_outstanding(system.db, user(system, "super"), system.app)
    vendor = {l["key"]: l for l in cleared["lines"]}["vendor"]
    assert vendor["state"] == "not_applicable" and "Judged not applicable" in vendor["reason"] and "Built by us" in vendor["reason"]
    assert cleared["blocking"] == [] and cleared["ready_for_decision"] is True


def test_an_owner_who_is_not_named_blocks_and_says_so(system):
    system.db.execute("UPDATE applications SET owner_user_id = NULL WHERE id = %s", (system.app,))
    system.db.commit()
    owner = lines(system)["owner"]
    assert owner["state"] == "not_yet_assessed" and owner["blocks_decision"] is True
    assert outstanding.get_outstanding(system.db, user(system, "super"), system.app)["ready_for_decision"] is False


def test_an_evaluation_is_done_failed_out_of_date_or_unthresholded_and_says_which(system):
    assert state(system, "evaluation") == "not_yet_assessed"
    evaluations.record_run(system.db, user(system, "dpo_a"), system.app, {**RUN, "thresholds": {}})
    system.db.commit()
    assert state(system, "evaluation") == "not_yet_assessed" and "no threshold" in lines(system)["evaluation"]["reason"]
    evaluations.record_run(system.db, user(system, "dpo_a"), system.app, {**RUN, "name": "Passing"})
    system.db.commit()
    assert state(system, "evaluation") == "complete"
    evaluations.record_run(system.db, user(system, "dpo_a"), system.app,
                           {**RUN, "name": "Worse", "scores": {"citation_validity": 10}, "finished_at": "2026-10-05 09:00:00"})
    system.db.commit()
    failed = lines(system)["evaluation"]
    assert failed["state"] == "failed" and "Worse" in failed["reason"]
    system.db.execute("UPDATE ai_evaluation_runs SET finished_at = '2024-01-01 00:00:00', recorded_at = '2024-01-01 00:00:00', "
                      "result_state = 'passed'")
    system.db.commit()
    assert state(system, "evaluation") == "not_yet_assessed" and "out of date" in lines(system)["evaluation"]["reason"]


def test_oversight_is_waiting_while_a_draft_awaits_review_and_done_only_when_both_arrangements_are_reviewed(system):
    arrangement = {**COMPLETE, "responsible_user_id": user(system, "employee_a")["id"]}
    saved = {}
    for track in ("design", "operation"):
        saved[track] = oversight.save_arrangement(system.db, user(system, "dpo_a"), system.app, track, arrangement, 0)["oversight"]
        system.db.commit()
    assert state(system, "oversight") == "waiting"
    oversight.review_arrangement(system.db, user(system, "owner_a"), system.app, "design", saved["design"]["revision"])
    system.db.commit()
    assert state(system, "oversight") == "waiting", "one arrangement is still a draft"
    oversight.review_arrangement(system.db, user(system, "owner_a"), system.app, "operation", saved["operation"]["revision"])
    system.db.commit()
    done = lines(system)["oversight"]
    assert done["state"] == "complete" and "not a legal conformity decision" in done["reason"]
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "Changed"}, profile["version"])
    system.db.commit()
    assert state(system, "oversight") == "not_yet_assessed"


def test_the_decision_line_follows_the_request_the_approval_and_a_change_to_the_use(system):
    resolve_provider_review(system)
    assert state(system, "decision") == "not_yet_assessed"
    row = ask(system, "dpo_a")
    assert state(system, "decision") == "waiting"
    decide(system, row, "approve", rationale="Fine.")
    assert state(system, "decision") == "complete" and "conditions" not in lines(system)
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "Something new"}, profile["version"])
    system.db.commit()
    again = lines(system)["decision"]
    assert again["state"] == "not_yet_assessed" and "Needs re-review" in again["reason"]


def test_conditions_are_waiting_until_one_is_overdue(system):
    resolve_provider_review(system)
    row = ask(system, "dpo_a")
    decide(system, row, "approve_with_conditions", rationale="Fine with a condition.",
           conditions=[{"text": "Review the output weekly", "due_date": "2999-01-01"}])
    waiting = lines(system)["conditions"]
    assert waiting["state"] == "waiting" and waiting["due"] == "2999-01-01"
    system.db.execute("UPDATE ai_use_decision_conditions SET due_date = '2020-01-01'")
    system.db.commit()
    assert lines(system)["conditions"]["state"] == "failed"


def test_a_pending_regulatory_change_is_waiting_and_named_jurisdictions_are_needed_first(system):
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    service.update_profile(system.db, user(system, "dpo_a"), system.app, {"jurisdictions": ["EU"]}, profile["version"])
    system.db.commit()
    assert state(system, "regulatory") == "complete"
    _insert(system.db, "regulatory_updates", framework_name="EU AI Act", title="Guidance", status="open")
    from modules.ai_governance import regulation
    regulation.refresh(system.db, user(system, "dpo_a"))
    system.db.commit()
    assert state(system, "regulatory") == "waiting"


def test_a_linked_continuity_record_makes_that_line_done(system):
    bia = _insert(system.db, "bcm_bia_records", process_name="Ticket handling", business_unit_id=system.unit["A"])
    system.db.commit()
    assert state(system, "continuity") == "not_yet_assessed"
    made = relationships.create_link(system.db, user(system, "super"), ("governance", "application", system.app),
                                     ("bcm", "bia", bia), "related")
    system.db.commit()
    assert made["created"] is True
    got = lines(system)["continuity"]
    assert got["state"] == "complete" and got["records"][0]["title"] == "Ticket handling"


def test_a_source_that_cannot_be_read_is_could_not_be_read_and_never_done(system, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the table is gone")
    monkeypatch.setattr(evaluations, "list_runs", broken)
    got = outstanding.get_outstanding(system.db, user(system, "super"), system.app)
    by = {l["key"]: l for l in got["lines"]}
    assert by["evaluation"]["state"] == "unavailable" and "not the same as done" in by["evaluation"]["reason"]
    assert by["facts"]["state"] == "complete", "the other lines still answer"
    assert got["unavailable"] == ["evaluation"] and got["ready_for_decision"] is False


def test_a_hidden_use_has_no_outstanding_items_for_the_caller(system):
    assert outstanding.get_outstanding(system.db, user(system, "dpo_b"), system.app) is None
    assert outstanding.get_outstanding(system.db, user(system, "super"), 987654) is None
    fail(lambda: outstanding.get_outstanding(system.db, {**user(system, "dpo_a"), "roles": ["external_auditor"]}, system.app), 403)


def test_a_viewer_without_orm_access_is_told_they_may_not_see_the_proof_line(system):
    got = lines(system, "employee_a")["proof"]
    assert got["state"] == "no_access" and "do not have access" in got["reason"]
