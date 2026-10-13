"""
AI governance G3: the requirement rules that say which assessments an AI use needs and why.

Written out by hand: a rule that cannot decide because an answer is missing says "needs review" and never "not
applicable"; the tier a reviewer adopted drives the steps, not the provisional one; each step carries the reasons it got
its applicability and only a required step holds a decision.
"""
import pytest

from modules.ai_governance import checklist, rules

LOWER = {"purpose": "Search", "deployment": "internal_build", "data_categories": ["public"], "affected_people": ["none"],
         "autonomy": "assist_only", "affects_decisions": False, "external_access": False}


def profile(**changes):
    answers = {**LOWER, **changes}
    screening = rules.screen(answers)
    return {**answers, "provider_note": answers.get("provider_name"), "provisional_tier": screening["tier"],
            "adopted_tier": changes.get("adopted_tier")}


def applicability(p):
    return {s["key"]: s["applicability"] for s in checklist.evaluate(p)}


def test_a_lower_use_built_in_house_with_no_personal_data_needs_almost_nothing():
    assert applicability(profile()) == {"aiia": "recommended", "dpia": "not_applicable", "ropa": "not_applicable",
                                        "vendor": "not_applicable", "aims": "not_applicable", "policy": "recommended"}


def test_a_moderate_vendor_use_with_personal_data_needs_the_privacy_records_and_a_provider_review():
    p = profile(deployment="vendor_service", data_categories=["internal", "personal"], affected_people=["employees"])
    assert applicability(p) == {"aiia": "required", "dpia": "recommended", "ropa": "required", "vendor": "required",
                                "aims": "recommended", "policy": "recommended"}


def test_an_elevated_use_needs_every_assessment():
    p = profile(deployment="embedded_vendor", data_categories=["health"], affected_people=["customers"])
    found = {s["key"]: s for s in checklist.evaluate(p)}
    assert {k: s["applicability"] for k, s in found.items()} == {"aiia": "required", "dpia": "required", "ropa": "required",
                                                                 "vendor": "required", "aims": "required", "policy": "required"}
    assert found["dpia"]["reasons"] == ["It handles special-category or health data and people outside the team are affected."]
    assert all(s["blocks_decision"] for s in found.values())


def test_significant_decisions_about_people_make_the_dpia_required_when_personal_data_is_used():
    p = profile(data_categories=["personal"], affects_decisions=True)
    assert applicability(p)["dpia"] == "required"


def test_an_answer_that_is_missing_is_needs_review_and_never_not_applicable():
    nothing = {"provisional_tier": "needs_review", "adopted_tier": None}
    got = applicability(nothing)
    assert got == {"aiia": "needs_review", "dpia": "needs_review", "ropa": "needs_review", "vendor": "needs_review",
                   "aims": "needs_review", "policy": "needs_review"}
    only_deployment = applicability({**nothing, "deployment": "internal_build"})
    assert only_deployment["vendor"] == "not_applicable" and only_deployment["dpia"] == "needs_review"


def test_the_tier_a_reviewer_adopted_drives_the_steps():
    p = profile()
    p["adopted_tier"] = "elevated"
    got = applicability(p)
    assert got["aiia"] == "required" and got["aims"] == "required" and got["policy"] == "required"
    reasons = next(s for s in checklist.evaluate(p) if s["key"] == "aims")["reasons"]
    assert "adopted by a reviewer" in reasons[0]


def test_only_a_required_step_holds_a_decision_and_every_step_says_why():
    for p in (profile(), profile(data_categories=["personal"], deployment="vendor_service"), {"provisional_tier": "needs_review"}):
        for step in checklist.evaluate(p):
            assert step["blocks_decision"] == (step["applicability"] == "required")
            assert step["applicability"] in checklist.APPLICABILITY
            assert step["reasons"] and all(r.endswith(".") for r in step["reasons"]), step
            assert step["title"] and step["module"] and step["prefill"]


def test_the_same_answers_always_give_the_same_steps_in_the_same_order():
    p = profile(data_categories=["personal"], deployment="vendor_service")
    first, second = checklist.evaluate(p), checklist.evaluate(dict(p))
    assert first == second and [s["key"] for s in first] == list(checklist.ORDER)
    assert checklist.snapshot(first) == checklist.snapshot(second)


# ── Where a step stands ─────────────────────────────────────────────────────

def test_a_step_with_no_record_has_not_started():
    assert checklist.progress([]) == {"state": "not_started", "stale": False, "records": []}


@pytest.mark.parametrize("status, state", [("draft", "in_progress"), ("in_progress", "in_progress"), ("completed", "complete"),
                                           ("Approved", "complete"), ("published", "complete"), ("something odd", "in_progress")])
def test_progress_comes_from_the_status_the_owning_module_reports(status, state):
    got = checklist.progress([{"title": "X", "url": "/x", "status": status, "updated_at": "2026-10-01"}])
    assert got["state"] == state and got["stale"] is False


def test_a_record_not_touched_since_the_use_changed_is_stale_and_one_that_was_is_not():
    old = {"title": "Old", "url": "/o", "status": "completed", "updated_at": "2026-01-10 09:00:00"}
    fresh = {"title": "Fresh", "url": "/f", "status": "completed", "updated_at": "2026-10-05 09:00:00"}
    assert checklist.progress([old], changed_at="2026-09-01 00:00:00")["stale"] is True
    assert checklist.progress([fresh], changed_at="2026-09-01 00:00:00")["stale"] is False
    assert checklist.progress([old, fresh], changed_at="2026-09-01 00:00:00")["stale"] is False, "one current record is enough"
    assert checklist.progress([old], changed_at=None)["stale"] is False
