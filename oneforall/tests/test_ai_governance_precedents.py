"""
Precedents for an AI use or a request (plans/2026-10-governance-rework/01 section 5).

Written by hand. A match is a prompt to look and never evidence of sameness; only a specialist says two uses are the same;
a prior approval is reported as that use's and never carried over; and a use the viewer may not open is not a candidate.
"""
import pytest

from modules.ai_governance import precedents as pr
from modules.ai_governance import service
from tests.test_ai_governance_decisions import ask, decide, resolve_provider_review
from tests.test_ai_governance_service import FULL, approve_new, commit, count, draft, fail, roles, submitted, user  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401


def subject(**changes):
    base = {"name": "Ticket summarizer", "provider": "Acme AI", "deployment": "vendor_service", "autonomy": "assist_only",
            "data_categories": ["internal", "personal"], "affected_people": ["employees"], "jurisdictions": ["ZW"],
            "purpose": "Summarize support tickets for agents"}
    base.update(changes)
    return base


# ── The rules ───────────────────────────────────────────────────────────────

def test_the_same_name_is_a_possible_match_and_a_similar_name_is_one_with_less_weight():
    same = pr.compare(subject(), subject(provider="Other Co", data_categories=[], purpose="x"))
    assert same["band"] == "possible_match" and same["reasons"] == ["Same name"]
    similar = pr.compare(subject(), subject(name="Ticket summarizer v2", provider="Other Co", data_categories=[], purpose="x"))
    assert similar["band"] == "possible_match" and similar["reasons"] == ["Similar name"] and similar["score"] < same["score"]


def test_the_same_provider_alone_is_only_a_related_precedent_and_with_a_similar_purpose_a_possible_match():
    related = pr.compare(subject(), subject(name="Contract reviewer", data_categories=[], purpose="Review contracts for legal"))
    assert related["band"] == "related_precedent" and related["reasons"] == ["Same provider"]
    both = pr.compare(subject(), subject(name="Support assistant", data_categories=[], purpose="Summarize tickets for support agents"))
    assert both["band"] == "possible_match" and both["reasons"][:2] == ["Same provider", "Similar purpose"]


def test_the_same_kind_of_data_provided_the_same_way_is_weak_but_enough_to_be_a_prompt_when_a_provider_also_matches():
    weak = pr.compare(subject(), subject(name="Other", provider="Someone", purpose="Something unrelated entirely"))
    assert weak is None, "shared data and a way of being provided alone is not enough"


def test_nothing_in_common_is_not_a_candidate():
    assert pr.compare(subject(), {"name": "HR portal", "provider": "Zed", "deployment": "internal_build", "data_categories": [],
                                  "purpose": "Leave requests"}) is None
    assert pr.compare(subject(name=None, provider=None), {"name": None}) is None


def test_short_or_empty_names_never_match_each_other():
    assert pr.compare(subject(name="AI"), subject(name="AI", provider=None, purpose=None)) is not None  # same name still counts
    assert pr.compare(subject(name="X", provider=None), subject(name="Xylophone", provider=None, purpose=None)) is None, \
        "a name under four characters is not a fragment of another name"


def test_differences_are_named_in_words():
    got = pr.differences(subject(), subject(deployment="internal_build", data_categories=["internal"], provider="Other Co"))
    labels = {d["label"]: d for d in got}
    assert labels["How it is provided"]["other"] == "Built in-house"
    assert labels["Kinds of data"]["this"] == "Internal business information, Personal data"
    assert labels["Provider"]["this"] == "Acme AI" and labels["Provider"]["other"] == "Other Co"
    assert pr.differences(subject(), subject()) == []


# ── The service ─────────────────────────────────────────────────────────────

@pytest.fixture
def system(world, roles):
    done = approve_new(world, submitted(world, answers={**FULL, "provider_name": "Acme AI"}))
    world.app = done["application_id"]
    return world


def another(world, name, author="employee_a", reviewer="dpo_a", **answers):
    done = approve_new(world, submitted(world, name=author, answers={**FULL, "name": name, **answers}), reviewer=reviewer)
    return done["application_id"]


def test_a_use_with_a_similar_name_in_scope_is_listed_with_why_and_what_differs(system):
    other = another(system, "Ticket summarizer 2", provider_name="Acme AI", deployment="internal_build")
    got = pr.for_use(system.db, user(system, "dpo_a"), system.app)
    assert [c["id"] for c in got["bands"]["possible_match"]] == [other] and got["none"] is False
    candidate = got["bands"]["possible_match"][0]
    assert candidate["reasons"][0] == "Similar name" and candidate["url"] == f"/ai-governance/systems/{other}"
    assert {d["label"] for d in candidate["differences"]} == {"How it is provided"}
    assert candidate["decision"] is None and candidate["evaluation"] is None and candidate["owner"] == "employee_a"
    assert got["rule_version"] == "p1" and "does not carry over" in got["note"]


def test_a_prior_approval_is_reported_as_that_uses_and_never_applied(system):
    other = another(system, "Ticket summarizer copy")
    system.app, original = other, system.app
    resolve_provider_review(system)
    row = ask(system, "dpo_a")
    decide(system, row, "approve", rationale="Fine.")
    system.app = original
    got = pr.for_use(system.db, user(system, "dpo_a"), original)
    candidate = got["bands"]["possible_match"][0]
    assert candidate["decision"]["status"] == "approved" and candidate["decision"]["revoked"] is False
    assert service.get_profile(system.db, user(system, "dpo_a"), original) is not None
    assert system.db.execute("SELECT COUNT(*) FROM ai_use_decisions WHERE application_id = %s", (original,)).fetchone()[0] == 0


def test_a_use_in_another_unit_is_never_a_candidate(system):
    hidden = approve_new(system, submitted(system, name="owner_b", answers={**FULL, "name": "Ticket summarizer"}),
                         reviewer="dpo_b")["application_id"]
    mine = pr.for_use(system.db, user(system, "dpo_a"), system.app)
    assert mine["none"] is True and hidden not in [c["id"] for b in mine["bands"].values() for c in b]
    wide = pr.for_use(system.db, user(system, "super"), system.app)
    assert [c["id"] for c in wide["bands"]["possible_match"]] == [hidden]


def test_only_a_specialist_says_two_uses_are_the_same_and_it_changes_the_band_and_nothing_else(system):
    other = another(system, "Ticket summarizer 2")
    done = pr.set_verdict(system.db, user(system, "dpo_a"), "application", system.app, other, "same_use", "Same team, renamed.")
    commit(system, done, user(system, "dpo_a"))
    assert done["audit"][0][0] == "ai_precedent_verdict"
    got = pr.for_use(system.db, user(system, "dpo_a"), system.app)
    assert [c["id"] for c in got["bands"]["verified_same_use"]] == [other] and got["bands"]["possible_match"] == []
    assert got["bands"]["verified_same_use"][0]["verdict"]["note"] == "Same team, renamed."
    assert count(system, "cross_module_links") == 0, "a verdict links nothing"
    pr.set_verdict(system.db, user(system, "dpo_a"), "application", system.app, other, "not_related", "Different team.")
    system.db.commit()
    again = pr.for_use(system.db, user(system, "dpo_a"), system.app)
    assert again["bands"]["verified_same_use"] == [] and [c["id"] for c in again["set_aside"]] == [other]
    cleared = pr.set_verdict(system.db, user(system, "dpo_a"), "application", system.app, other, None)
    system.db.commit()
    assert cleared["audit"][0][0] == "ai_precedent_cleared"
    assert [c["id"] for c in pr.for_use(system.db, user(system, "dpo_a"), system.app)["bands"]["possible_match"]] == [other]


def test_a_verdict_needs_the_right_and_both_records_to_be_open_to_the_caller(system):
    other = another(system, "Ticket summarizer 2")
    hidden = approve_new(system, submitted(system, name="owner_b", answers={**FULL, "name": "Ticket summarizer 3"}),
                         reviewer="dpo_b")["application_id"]
    fail(lambda: pr.set_verdict(system.db, user(system, "employee_a"), "application", system.app, other, "same_use"), 403)
    fail(lambda: pr.set_verdict(system.db, user(system, "dpo_a"), "application", system.app, hidden, "same_use"), 404)
    fail(lambda: pr.set_verdict(system.db, user(system, "dpo_b"), "application", system.app, other, "same_use"), 404)
    fail(lambda: pr.set_verdict(system.db, user(system, "dpo_a"), "application", system.app, system.app, "same_use"), 404)
    fail(lambda: pr.set_verdict(system.db, user(system, "dpo_a"), "application", system.app, other, "identical"), 422)
    fail(lambda: pr.set_verdict(system.db, user(system, "dpo_a"), "building", system.app, other, "same_use"), 400)
    fail(lambda: pr.set_verdict(system.db, user(system, "dpo_a"), "application", True, other, "same_use"), 400)
    fail(lambda: pr.set_verdict(system.db, user(system, "dpo_a"), "application", system.app, other, "same_use", "x" * 501), 422)
    assert count(system, "ai_precedent_verdicts") == 0


def test_a_request_is_compared_the_same_way_and_a_verdict_on_it_is_its_own(system):
    other = another(system, "Contract reviewer", provider_name="Acme AI", purpose="Review vendor contracts for legal")
    pending = submitted(system, name="employee_a", answers={**FULL, "name": "Contract reviewer pro", "provider_name": "Acme AI",
                                                            "purpose": "Review vendor contracts for legal"})
    got = pr.for_request(system.db, user(system, "dpo_a"), pending["id"])
    assert [c["id"] for c in got["bands"]["possible_match"]] == [other]
    assert [c["id"] for c in got["bands"]["related_precedent"]] == [system.app], "the same provider, a different purpose"
    assert got["subject"]["name"] == "Contract reviewer pro"
    done = pr.set_verdict(system.db, user(system, "dpo_a"), "request", pending["id"], other, "related", "Same vendor.")
    commit(system, done, user(system, "dpo_a"))
    after = pr.for_request(system.db, user(system, "dpo_a"), pending["id"])
    assert {c["id"] for c in after["bands"]["related_precedent"]} == {other, system.app} and after["bands"]["possible_match"] == []
    assert pr.for_use(system.db, user(system, "dpo_a"), system.app)["bands"]["verified_same_use"] == [],         "a request verdict is not a use verdict"


def test_a_request_the_caller_may_not_review_does_not_exist_for_them(system):
    pending = submitted(system, name="employee_a", answers={**FULL, "name": "Another"})
    fail(lambda: pr.for_request(system.db, user(system, "dpo_b"), pending["id"]), 404)
    fail(lambda: pr.for_request(system.db, user(system, "employee_a"), pending["id"]), 403)
    assert pr.for_use(system.db, user(system, "dpo_b"), system.app) is None


def test_only_the_first_ten_of_a_band_are_shown_and_the_rest_are_counted(system):
    for n in range(12):
        another(system, f"Ticket summarizer {n + 10}")
    got = pr.for_use(system.db, user(system, "dpo_a"), system.app)
    assert len(got["bands"]["possible_match"]) == pr.LIMIT_SHOWN and got["more"]["possible_match"] == 2
