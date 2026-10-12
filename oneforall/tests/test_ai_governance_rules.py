"""
AI governance G2: what an AI use declaration may say, and the screening rules read from it.

Written out by hand and not computed by the code under test:

* an answer outside its list, a text over its limit and a list mixing "no one" with people are refused with a sentence
  that names the question; a half-finished draft is never refused for what it has not answered yet;
* the tier is the highest tier any fired rule points to; a use is "lower" only when every screening answer is given;
  an unanswered question keeps it at "needs review", never at "lower";
* every fired rule is reported with the answers it read, so a reviewer can see why.
"""
import pytest

from modules.ai_governance import rules

ANSWERED = {
    "purpose": "Summarize support tickets", "deployment": "vendor_service", "data_categories": ["internal"],
    "affected_people": ["none"], "autonomy": "assist_only", "affects_decisions": False, "external_access": False,
}


def _screen(**changes):
    return rules.screen({**ANSWERED, **changes})


# ── clean ───────────────────────────────────────────────────────────────────

def test_clean_keeps_known_answers_and_drops_nothing_it_was_given():
    answers, errors = rules.clean({
        "name": "  Ticket summarizer ", "purpose": "Summarize", "deployment": "vendor_service",
        "data_categories": ["internal", "internal", "personal"], "affects_decisions": None, "external_access": True,
        "owner_user_id": 7, "autonomy": "", "target_launch": "2026-12-01"})
    assert errors == {}
    assert answers == {"name": "Ticket summarizer", "purpose": "Summarize", "deployment": "vendor_service",
                       "data_categories": ["internal", "personal"], "affects_decisions": None, "external_access": True,
                       "owner_user_id": 7, "autonomy": None, "target_launch": "2026-12-01"}


def test_unknown_fields_are_ignored_not_stored():
    answers, errors = rules.clean({"purpose": "x", "status": "approved", "application_id": 4, "provisional_tier": "lower"})
    assert answers == {"purpose": "x"} and errors == {}


@pytest.mark.parametrize("field, value, mentions", [
    ("deployment", "magic", "how it is provided"),
    ("autonomy", "sometimes", "how much it decides"),
    ("data_categories", ["internal", "gossip"], "kinds of data"),
    ("data_categories", "internal", "kinds of data"),
    ("data_categories", [7], "kinds of data"),
    ("affected_people", ["none", "customers"], "No one outside the team"),
    ("affects_decisions", "maybe", "effect on decisions"),
    ("external_access", 1, "outside access"),
    ("name", 7, "name"),
    ("purpose", "x" * 2001, "too long"),
    ("name", "x" * 121, "too long"),
    ("owner_user_id", "7", "owner"),
    ("owner_user_id", 0, "owner"),
    ("owner_user_id", True, "owner"),
])
def test_a_bad_answer_is_refused_with_a_sentence_naming_the_question(field, value, mentions):
    answers, errors = rules.clean({field: value})
    assert field in errors and mentions in errors[field] and field not in answers


def test_a_body_that_is_not_an_object_is_refused():
    assert rules.clean(["purpose"]) == ({}, {"_": "Send the answers as an object."})


def test_control_characters_are_removed_from_text():
    answers, _ = rules.clean({"purpose": "a\x00b\x07c\nd"})
    assert answers["purpose"] == "abc\nd"


def test_a_draft_is_never_refused_for_what_it_has_not_answered():
    assert rules.clean({}) == ({}, {})
    answers, errors = rules.clean({"name": "", "purpose": None, "data_categories": None, "deployment": ""})
    assert errors == {} and answers == {"name": None, "purpose": None, "data_categories": [], "deployment": None}


def test_the_required_answers_and_their_order():
    assert rules.missing_for_submit({}) == list(rules.REQUIRED_TO_SUBMIT)
    full = {"name": "n", "purpose": "p", "deployment": "internal_build", "owner_user_id": 3,
            "data_categories": ["public"], "intended_users": "staff"}
    assert rules.missing_for_submit(full) == []
    assert rules.missing_for_submit({**full, "data_categories": []}) == ["data_categories"]
    assert rules.missing_for_submit({**full, "name": "  "}) == ["name"]
    assert rules.missing_for_submit(rules.clean({**full, "intended_users": "   "})[0]) == ["intended_users"]
    assert rules.missing_for_submit({**full, "owner_user_id": None}) == ["owner_user_id"]


# ── screen ──────────────────────────────────────────────────────────────────

def test_a_fully_answered_use_with_nothing_risky_is_lower():
    result = _screen()
    assert (result["tier"], result["reasons"], result["missing"], result["complete"]) == ("lower", [], [], True)
    assert result["rule_version"] == "v1"


@pytest.mark.parametrize("changes, tier, rules_fired", [
    ({"affects_decisions": True}, "elevated", {"E1"}),
    ({"autonomy": "decide_automatically", "affected_people": ["customers"]}, "elevated", {"E2"}),
    ({"autonomy": "decide_automatically", "affected_people": ["none"]}, "lower", set()),
    ({"data_categories": ["health"], "affected_people": ["customers"]}, "elevated", {"E3", "M1"}),
    ({"data_categories": ["sensitive_personal"], "affected_people": ["employees"]}, "elevated", {"E3", "M1"}),
    ({"data_categories": ["health"], "affected_people": ["none"]}, "moderate", {"M1"}),
    ({"data_categories": ["personal"]}, "moderate", {"M1"}),
    ({"external_access": True}, "moderate", {"M2"}),
    ({"autonomy": "decide_with_review"}, "moderate", {"M3"}),
    ({"data_categories": ["financial"]}, "moderate", {"M4"}),
    ({"data_categories": ["confidential", "public"]}, "moderate", {"M5"}),
    ({"data_categories": ["public"]}, "lower", set()),
    ({"affects_decisions": True, "external_access": True, "data_categories": ["personal"]}, "elevated", {"E1", "M1", "M2"}),
])
def test_the_tier_is_the_highest_fired_rule(changes, tier, rules_fired):
    result = _screen(**changes)
    assert result["tier"] == tier
    assert {r["rule"] for r in result["reasons"]} == rules_fired


@pytest.mark.parametrize("missing_field", list(rules.SCREENING_FIELDS))
def test_an_unanswered_question_never_makes_a_use_lower(missing_field):
    answers = {k: v for k, v in ANSWERED.items() if k != missing_field}
    result = rules.screen(answers)
    assert result["tier"] == "needs_review" and result["missing"] == [missing_field] and not result["complete"]
    answers[missing_field] = None
    assert rules.screen(answers)["tier"] == "needs_review"


def test_a_fired_rule_stands_even_when_other_answers_are_missing():
    result = rules.screen({"affects_decisions": True})
    assert result["tier"] == "elevated" and not result["complete"]
    assert {"purpose", "deployment", "data_categories"} <= set(result["missing"])


def test_nothing_answered_is_needs_review_with_every_question_listed():
    result = rules.screen({})
    assert (result["tier"], result["reasons"]) == ("needs_review", [])
    assert result["missing"] == list(rules.SCREENING_FIELDS)


def test_every_reason_names_the_answers_it_read():
    result = _screen(affects_decisions=True, data_categories=["personal"], affected_people=["customers"],
                     autonomy="decide_automatically")
    by_rule = {r["rule"]: r for r in result["reasons"]}
    assert by_rule["E2"]["fields"] == ["autonomy", "affected_people"]
    assert all(r["text"].endswith(".") and r["fields"] and r["tier"] in rules.TIERS for r in result["reasons"])


def test_the_tier_a_reviewer_adopts_wins_over_the_provisional_one():
    assert rules.effective_tier("moderate", "elevated") == "elevated"
    assert rules.effective_tier("moderate", None) == "moderate"
    assert rules.effective_tier("moderate", "nonsense") == "moderate"
    assert rules.effective_tier(None, None) == "needs_review"
    assert rules.is_tier("lower") and not rules.is_tier("high")


def test_every_choice_list_has_a_sentence_for_each_value():
    for table in (rules.CAPABILITY_TYPES, rules.AUTONOMY, rules.DEPLOYMENT, rules.DATA_CATEGORIES,
                  rules.AFFECTED_PEOPLE, rules.JURISDICTIONS):
        assert table and all(isinstance(k, str) and isinstance(v, str) and v for k, v in table.items())
    assert set(rules.TIER_LABELS) == set(rules.TIERS)
