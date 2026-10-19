"""
AI governance G5: recorded evaluation runs through the service layer, and what a failed one does to a decision.

Written by hand. A reviewer records a run; its reading is computed on the server (a failed, cancelled or errored run is
never a pass, a run with no thresholds claims nothing); a stale run says so; a failed run raises one event and reopens a
signed decision without touching it; a finding is a proposed task and not a failed control; and a system the caller may not
open does not exist for them.
"""
import json

import pytest

from core import rbac
from modules.ai_governance import decisions, evaluations, guidance, service
from modules.ai_governance.service import ServiceError
from tests.test_ai_governance_service import FULL, approve_new, commit, count, fail, submitted, user
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401

RUN = {"name": "Citation check", "test_set_name": "aria-citations", "test_set_version": "v3", "rubric_version": "r2",
       "subject_version": "assistant 2026-09", "evaluator": "deterministic", "status": "completed",
       "started_at": "2026-10-01", "finished_at": "2026-10-01 10:30:00", "scores": {"citation_validity": 97.5, "no_match": 100},
       "thresholds": {"citation_validity": 95}, "cases_total": 120, "cases_failed": 3, "retention": "summary"}


@pytest.fixture
def system(world):
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    return world


def record(world, actor="dpo_a", **changes):
    done = evaluations.record_run(world.db, user(world, actor), world.app, {**RUN, **changes})
    commit(world, done, user(world, actor))
    return done


def audit_actions(world):
    return [r[0] for r in world.db.execute("SELECT action FROM audit_log WHERE action LIKE 'ai_evaluation%' ORDER BY id").fetchall()]


def event_count(world):
    return world.db.execute("SELECT COUNT(*) FROM events WHERE event_type = 'evaluation.failed'").fetchone()[0]


# ── Recording ───────────────────────────────────────────────────────────────

def test_a_run_that_met_its_threshold_is_recorded_as_a_pass_and_raises_nothing(system):
    done = record(system)
    run = done["run"]
    assert run["state"] == "passed" and run["state_label"] == "Passed" and run["stale"] is False
    assert run["scores"] == {"citation_validity": 97.5, "no_match": 100.0} and run["recorded_by"] == "dpo_a"
    assert run["test_set_name"] == "aria-citations" and run["subject_version"] == "assistant 2026-09" and run["version"] == 1
    assert done["events"] == [] and audit_actions(system) == ["ai_evaluation_recorded"]


def test_a_failed_run_raises_one_event_and_a_run_that_did_not_finish_never_reads_as_a_pass(system):
    failed = record(system, scores={"citation_validity": 80}, name="Run two")
    assert failed["run"]["state"] == "failed" and failed["run"]["failed_dimensions"] == ["citation_validity"]
    assert len(failed["events"]) == 1
    cancelled = record(system, status="cancelled", scores={}, thresholds={}, finished_at=None, name="Run three")
    assert cancelled["run"]["state"] == "interrupted" and cancelled["run"]["state_label"] == "Did not finish"
    ungated = record(system, thresholds={}, name="Run four")
    assert ungated["run"]["state"] == "ungated" and ungated["events"] == []
    assert event_count(system) == 2, "the failed and the interrupted run, one event each"


def test_only_a_reviewer_records_and_only_for_a_system_they_may_open(system):
    fail(lambda: evaluations.record_run(system.db, user(system, "employee_a"), system.app, RUN), 403)
    fail(lambda: evaluations.record_run(system.db, user(system, "dpo_b"), system.app, RUN), 404)
    fail(lambda: evaluations.record_run(system.db, user(system, "dpo_a"), 987654, RUN), 404)
    retired = service.retire(system.db, user(system, "dpo_a"), system.app, "Contract ended.")
    commit(system, retired, user(system, "dpo_a"))
    fail(lambda: evaluations.record_run(system.db, user(system, "dpo_a"), system.app, RUN), 409)
    assert count(system, "ai_evaluation_runs") == 0


def test_a_bad_run_is_refused_with_a_sentence_for_each_field(system):
    error = fail(lambda: evaluations.record_run(system.db, user(system, "dpo_a"), system.app,
                                                {**RUN, "scores": {"a": 101}, "status": "done"}), 422)
    assert set(error.extra["errors"]) == {"scores", "status", "thresholds"}
    assert count(system, "ai_evaluation_runs") == 0


def test_the_artifact_must_be_a_vault_item_the_recorder_may_open(system):
    mine = _insert(system.db, "evidence_items", title="Run report", status="current", org_id=1, business_unit_id=system.unit["A"])
    theirs = _insert(system.db, "evidence_items", title="Unit B report", status="current", org_id=1, business_unit_id=system.unit["B"])
    system.db.commit()
    fail(lambda: evaluations.record_run(system.db, user(system, "dpo_a"), system.app, {**RUN, "artifact_id": theirs}), 400)
    fail(lambda: evaluations.record_run(system.db, user(system, "dpo_a"), system.app, {**RUN, "artifact_id": 987654}), 400)
    assert record(system, artifact_id=mine)["run"]["artifact_id"] == mine


# ── Reading, comparing, staleness ───────────────────────────────────────────

def test_the_list_gives_the_latest_the_run_before_it_on_the_same_test_set_and_how_they_differ(system):
    record(system, name="First", scores={"citation_validity": 90, "no_match": 100}, finished_at="2026-09-20 09:00:00",
           started_at="2026-09-20")
    record(system, name="Other set", test_set_name="leakage", scores={"leak": 100}, thresholds={"leak": 100},
           finished_at="2026-09-25 09:00:00", started_at="2026-09-25")
    record(system, name="Second", scores={"citation_validity": 96, "no_match": 100}, finished_at="2026-10-05 09:00:00",
           started_at="2026-10-05")
    got = evaluations.list_runs(system.db, user(system, "employee_a"), system.app)
    assert [r["name"] for r in got["runs"]] == ["Second", "Other set", "First"]
    assert got["latest"]["name"] == "Second" and got["previous"]["name"] == "First"
    moved = {r["dimension"]: r["change"] for r in got["comparison"]["dimensions"]}
    assert moved == {"citation_validity": 6.0, "no_match": 0.0} and got["comparison"]["same_test_set"] is True
    assert got["can"] == {"record": False, "review": False}
    assert evaluations.list_runs(system.db, user(system, "dpo_b"), system.app) is None


def test_two_runs_are_compared_only_within_one_system_and_never_across_a_hidden_one(system):
    a = record(system, name="A")["run"]["id"]
    b = record(system, name="B", scores={"citation_validity": 99, "no_match": 100})["run"]["id"]
    got = evaluations.compare_runs(system.db, user(system, "dpo_a"), a, b)
    assert got["older"]["name"] == "A" and got["newer"]["name"] == "B"
    fail(lambda: evaluations.compare_runs(system.db, user(system, "dpo_b"), a, b), 404)
    other = _insert(system.db, "applications", name="Other", business_unit_id=system.unit["A"], is_active=1)
    system.db.commit()
    service.create_profile(system.db, user(system, "super"), other, {})
    system.db.commit()
    c = evaluations.record_run(system.db, user(system, "dpo_a"), other, RUN)["run"]["id"]
    system.db.commit()
    fail(lambda: evaluations.compare_runs(system.db, user(system, "dpo_a"), a, c), 400)


def test_a_run_is_stale_once_a_covered_fact_changes_after_it(system):
    run = record(system)["run"]
    assert evaluations.list_runs(system.db, user(system, "dpo_a"), system.app)["latest"]["stale"] is False
    system.db.execute("UPDATE ai_use_profiles SET material_changed_at = '2999-01-01 00:00:00' WHERE application_id = %s", (system.app,))
    system.db.commit()
    assert evaluations.list_runs(system.db, user(system, "dpo_a"), system.app)["latest"]["stale"] is True
    assert run["id"]


# ── Review ──────────────────────────────────────────────────────────────────

def test_a_passed_run_is_accepted_and_a_failed_one_opens_a_finding_that_is_a_proposed_task(system):
    passed = record(system, name="Good")["run"]
    accepted = evaluations.review_run(system.db, user(system, "dpo_a"), passed["id"], "accepted", "Looks right.", passed["version"])
    commit(system, accepted, user(system, "dpo_a"))
    assert accepted["run"]["review_outcome"] == "accepted" and accepted["run"]["reviewed_by"] == "dpo_a"
    fail(lambda: evaluations.review_run(system.db, user(system, "dpo_a"), passed["id"], "accepted", None, 2), 409)

    bad = record(system, name="Bad", scores={"citation_validity": 70})["run"]
    fail(lambda: evaluations.review_run(system.db, user(system, "dpo_a"), bad["id"], "accepted", None, bad["version"]), 409)
    fail(lambda: evaluations.review_run(system.db, user(system, "dpo_a"), bad["id"], "finding", " ", bad["version"]), 422)
    fail(lambda: evaluations.review_run(system.db, user(system, "dpo_a"), bad["id"], "finding", "x" * 1001, bad["version"]), 422)
    fail(lambda: evaluations.review_run(system.db, user(system, "dpo_a"), bad["id"], "finding", "Citations are wrong.", "1"), 400)
    found = evaluations.review_run(system.db, user(system, "dpo_a"), bad["id"], "finding", "Citations are wrong.", bad["version"])
    commit(system, found, user(system, "dpo_a"))
    task = system.db.execute("SELECT title, assigned_to, priority, status, module FROM task_board WHERE title LIKE 'Evaluation finding%'").fetchone()
    assert task["assigned_to"] == user(system, "employee_a")["id"] and task["priority"] == "high" and task["status"] == "todo"
    fail(lambda: evaluations.review_run(system.db, user(system, "dpo_b"), bad["id"], "finding", "No.", 3), 404)
    fail(lambda: evaluations.review_run(system.db, user(system, "employee_a"), bad["id"], "finding", "No.", 3), 403)
    assert audit_actions(system)[-3:] == ["ai_evaluation_accepted", "ai_evaluation_recorded", "ai_evaluation_finding"]
    assert system.db.execute("SELECT COUNT(*) FROM ai_use_decisions").fetchone()[0] == 0, "a finding withdraws no approval"


# ── What a failed run does to a decision ────────────────────────────────────

def _approve(world):
    commit(world, guidance.set_step_not_applicable(world.db, user(world, "dpo_a"), world.app, "vendor", "Built by us."), user(world, "dpo_a"))
    asked = decisions.request_decision(world.db, user(world, "employee_a"), world.app, None)
    commit(world, asked, user(world, "employee_a"))
    brief = decisions.get_brief(world.db, user(world, "owner_a"), world.app)
    done = decisions.decide(world.db, user(world, "owner_a"), asked["decision"]["id"], "approve", brief=brief["hash"],
                            expected_version=1)
    commit(world, done, user(world, "owner_a"))
    return asked["decision"]["id"]


def test_a_failed_run_after_an_approval_reopens_it_and_leaves_the_signed_record_alone(system):
    decision_id = _approve(system)
    before = dict(system.db.execute("SELECT * FROM ai_use_decisions WHERE id = %s", (decision_id,)).fetchone())
    assert decisions.get_decisions(system.db, user(system, "owner_a"), system.app)["state"]["state"] == "approved"
    system.db.execute("UPDATE ai_use_decisions SET decided_at = '2026-01-01 00:00:00' WHERE id = %s", (decision_id,))
    system.db.commit()
    record(system, name="Passing run")
    assert decisions.get_decisions(system.db, user(system, "owner_a"), system.app)["state"]["state"] == "approved", "a pass reopens nothing"
    record(system, name="Failing run", scores={"citation_validity": 60})
    state = decisions.get_decisions(system.db, user(system, "owner_a"), system.app)["state"]
    assert state["state"] == "needs_re_review" and any("evaluation failed" in r for r in state["reasons"])
    after = dict(system.db.execute("SELECT * FROM ai_use_decisions WHERE id = %s", (decision_id,)).fetchone())
    after["decided_at"] = before["decided_at"] = None
    after["updated_at"] = before["updated_at"] = None
    assert after == before, "the signed record is as it was"


def test_a_failed_run_from_before_the_decision_does_not_reopen_it(system):
    record(system, name="Old failure", scores={"citation_validity": 60}, finished_at="2020-01-01 00:00:00", started_at="2020-01-01")
    system.db.execute("UPDATE ai_evaluation_runs SET recorded_at = '2020-01-01 00:00:00'")
    system.db.commit()
    _approve(system)
    assert decisions.get_decisions(system.db, user(system, "owner_a"), system.app)["state"]["state"] == "approved"
