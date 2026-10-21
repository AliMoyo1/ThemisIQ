"""
AI governance G5: the pure rules of an evaluation record. A run passes only when it completed and every gated dimension met
its threshold; a failed, cancelled or errored run is never a pass; a completed run with no thresholds claims nothing; and
staleness is derived from the use's last material change and the age of the run.
"""
import pytest

from modules.ai_governance import evaluations
from modules.ai_governance.service import ServiceError

GOOD = {"name": "Citation check", "test_set_name": "aria-citations", "test_set_version": "v3", "rubric_version": "r2",
        "subject_version": "assistant 2026-09", "evaluator": "deterministic", "status": "completed",
        "started_at": "2026-10-01", "finished_at": "2026-10-01 10:30:00", "scores": {"citation_validity": 97.5, "no_match": 100},
        "thresholds": {"citation_validity": 95}, "cases_total": 120, "cases_failed": 3, "retention": "summary"}


# ── Outcome ─────────────────────────────────────────────────────────────────

def test_a_completed_run_passes_only_when_every_gated_dimension_met_its_threshold():
    assert evaluations.outcome_of("completed", {"a": 96, "b": 80}, {"a": 95}) == {"state": "passed", "failed": []}
    assert evaluations.outcome_of("completed", {"a": 94.9}, {"a": 95}) == {"state": "failed", "failed": ["a"]}
    assert evaluations.outcome_of("completed", {"a": 95}, {"a": 95})["state"] == "passed", "meeting the threshold is passing"
    assert evaluations.outcome_of("completed", {"a": 99, "b": 40}, {"a": 95, "b": 50}) == {"state": "failed", "failed": ["b"]}


def test_a_completed_run_with_no_thresholds_claims_no_pass():
    assert evaluations.outcome_of("completed", {"a": 100}, {}) == {"state": "ungated", "failed": []}
    assert evaluations.outcome_of("completed", {"a": 100}, None)["state"] == "ungated"


@pytest.mark.parametrize("status", ["cancelled", "error"])
def test_a_run_that_did_not_finish_is_never_a_pass_whatever_its_scores(status):
    assert evaluations.outcome_of(status, {"a": 100}, {"a": 50}) == {"state": "interrupted", "failed": []}


def test_a_run_recorded_as_failed_stays_failed_even_if_its_scores_look_fine():
    assert evaluations.outcome_of("failed", {"a": 99}, {"a": 50})["state"] == "failed"


# ── Staleness ───────────────────────────────────────────────────────────────

def test_a_run_is_stale_when_the_use_changed_after_it_or_when_it_is_old():
    today = "2026-10-11"
    assert evaluations.is_stale("2026-10-01 09:00:00", None, today) is False
    assert evaluations.is_stale("2026-10-01 09:00:00", "2026-10-05 08:00:00", today) is True, "the use changed after the run"
    assert evaluations.is_stale("2026-10-05 09:00:00", "2026-10-05 08:00:00", today) is False, "the same day is not stale"
    assert evaluations.is_stale("2026-04-14", None, today) is False
    assert evaluations.is_stale("2026-04-13", None, today) is True, "181 days"
    assert evaluations.is_stale(None, None, today) is True


# ── Comparison ──────────────────────────────────────────────────────────────

def test_two_runs_are_compared_dimension_by_dimension_and_say_whether_they_are_alike():
    old = {"scores": {"a": 90, "b": 70}, "test_set_name": "t", "test_set_version": "v1", "rubric_version": "r1",
           "subject_version": "m1", "state": "failed"}
    new = {"scores": {"a": 95, "c": 60}, "test_set_name": "t", "test_set_version": "v2", "rubric_version": "r1",
           "subject_version": "m2", "state": "passed"}
    got = evaluations.compare(old, new)
    assert {r["dimension"]: (r["before"], r["after"], r["change"]) for r in got["dimensions"]} == {
        "a": (90, 95, 5), "b": (70, None, None), "c": (None, 60, None)}
    assert got["same_test_set"] is False and got["same_rubric"] is True and got["subject_changed"] is True
    assert got["state"] == {"before": "failed", "after": "passed"}


# ── Cleaning ────────────────────────────────────────────────────────────────

def test_a_good_run_is_cleaned_and_keeps_its_numbers():
    got = evaluations.clean(GOOD)
    assert got["status"] == "completed" and got["scores"] == {"citation_validity": 97.5, "no_match": 100.0}
    assert got["thresholds"] == {"citation_validity": 95.0} and got["finished_at"] == "2026-10-01 10:30:00"
    assert got["started_at"] == "2026-10-01 00:00:00" and got["retention"] == "summary" and got["artifact_id"] is None


def fixes(**changes):
    with pytest.raises(ServiceError) as caught:
        evaluations.clean({**GOOD, **changes})
    assert caught.value.status == 422
    return caught.value.extra["errors"]


def test_every_field_that_is_wrong_is_named_with_a_sentence():
    assert set(fixes(name="", test_set_version=" ", subject_version=None, rubric_version=None, test_set_name=None)) == {
        "name", "test_set_version", "subject_version", "rubric_version", "test_set_name"}
    assert set(fixes(evaluator="oracle", status="done", retention="forever")) == {"evaluator", "status", "retention"}
    assert "scores" in fixes(scores={"a": 101})
    assert "scores" in fixes(scores={"a": -1})
    assert "scores" in fixes(scores={"a": True})
    assert "scores" in fixes(scores={"bad name!": 5})
    assert "scores" in fixes(scores={f"d{n}": 1 for n in range(31)})
    assert "thresholds" in fixes(thresholds={"missing": 50})
    assert "finished_at" in fixes(started_at="2026-10-02", finished_at="2026-10-01")
    assert "started_at" in fixes(started_at="2999-01-01")
    assert "finished_at" in fixes(finished_at="yesterday")
    assert "cases_failed" in fixes(cases_total=5, cases_failed=6)
    assert "cases_total" in fixes(cases_total=-1)
    assert "artifact_id" in fixes(artifact_id="abc")


def test_a_completed_run_needs_scores_and_a_finish_and_one_that_did_not_finish_needs_neither():
    assert "scores" in fixes(scores={})
    assert "finished_at" in fixes(finished_at=None)
    ok = evaluations.clean({**GOOD, "status": "cancelled", "scores": {}, "thresholds": {}, "finished_at": None})
    assert ok["status"] == "cancelled" and ok["scores"] == {}
    assert "scores" in fixes(status="failed", scores={})


def test_a_body_that_is_not_an_object_is_refused():
    with pytest.raises(ServiceError) as caught:
        evaluations.clean(["a", "list"])
    assert caught.value.status == 422
