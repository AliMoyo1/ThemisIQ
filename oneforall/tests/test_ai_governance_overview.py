"""
The specialist Overview of AI Governance (plans/2026-10-governance-rework/01 section 3).

Written by hand. Every card says what it counts and where to look; a card is a number only when it was measured; a source
that cannot be read is unavailable and not zero; a use with nothing recorded is "not measured" and never counted as passing;
and a unit never sees another unit's counts.
"""
from datetime import timedelta

import pytest

from core import ai_rollout, metric_state as ms
from core.timeutils import utcnow
from modules.ai_governance import decisions, evaluations, monitoring, oversight, overview, service, workspace
from tests.test_ai_governance_decisions import ask, decide, resolve_provider_review
from tests.test_ai_governance_evaluations import RUN
from tests.test_ai_governance_oversight import COMPLETE
from tests.test_ai_governance_service import FULL, approve_new, commit, count, draft, fail, roles, submitted, user  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401

SPECIALIST_CARDS = ["new_requests", "waiting_for_information", "awaiting_decision", "approved_with_conditions",
                    "reviews_due", "material_change", "evaluation_oversight_gaps"]


@pytest.fixture
def system(world, roles):
    """An accepted use in unit A owned by employee_a."""
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    return world


def view(world, name="dpo_a", **kw):
    return overview.get_overview(world.db, user(world, name), **kw)


def card(world, key, name="dpo_a"):
    return next(c for c in view(world, name)["cards"] if c["key"] == key)


def another_use(world, name="Second use", author="employee_a"):
    done = approve_new(world, submitted(world, name=author, answers={**FULL, "name": name}))
    return done["application_id"]


def approve_with_conditions(world, due="2999-01-01", texts=("Review the output weekly",)):
    resolve_provider_review(world)
    row = ask(world)
    return decide(world, row, "approve_with_conditions", rationale="Fine with conditions.",
                  conditions=[{"text": t, "due_date": due} for t in texts])


# ── The shape of the page ───────────────────────────────────────────────────

def test_a_specialist_gets_the_cards_each_with_a_definition_and_somewhere_to_look(system):
    got = view(system)
    assert [c["key"] for c in got["cards"]] == SPECIALIST_CARDS
    for c in got["cards"]:
        assert c["definition"], c["key"]
        assert c["drilldown"].startswith("/ai-governance/"), c["key"]
        assert c["state"] in ms.STATES
        if c["state"] == "measured":
            assert isinstance(c["value"], int) and c["as_of"], c["key"]
    assert got["viewer"] == {"specialist": True, "reviewer": True, "decider": True}
    assert got["funnel"]["key"] == "decision_funnel" and got["as_of"]


def test_the_scope_is_explained_in_words(system):
    mine = view(system, "dpo_a")["scope"]
    assert mine == {"text": "Unit A and the units below it, plus records that belong to the whole organization.",
                    "whole_organization": False}
    assert view(system, "super")["scope"] == {"text": "The whole organization.", "whole_organization": True}
    assert view(system, "dpo_no_unit")["scope"]["text"] == "Records that belong to the whole organization only, because you have no business unit."


# ── Requests ────────────────────────────────────────────────────────────────

def test_new_requests_are_the_submitted_ones_in_the_viewers_scope(world):
    submitted(world, "employee_a")
    submitted(world, "owner_b")
    assert card(world, "new_requests", "dpo_a")["value"] == 1
    assert card(world, "new_requests", "dpo_b")["value"] == 1
    assert card(world, "new_requests", "super")["value"] == 2
    assert card(world, "new_requests", "dpo_a")["drilldown"] == "/ai-governance/review"


def test_a_returned_request_waits_for_information_and_stops_being_new(world):
    row = submitted(world, "employee_a")
    done = service.return_to_author(world.db, user(world, "dpo_a"), row["id"], "Which vendor is it?", row["version"])
    commit(world, done, user(world, "dpo_a"))
    assert card(world, "new_requests")["value"] == 0
    waiting = card(world, "waiting_for_information")
    assert waiting["value"] == 1 and waiting["drilldown"] == "/ai-governance/review?status=waiting"
    assert card(world, "waiting_for_information", "dpo_b")["value"] == 0


def test_request_aging_buckets_add_up_to_the_new_requests(world):
    old = submitted(world, "employee_a")
    submitted(world, "employee_a", answers={"name": "Fresh one"})
    stamp = (utcnow() - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
    world.db.execute("UPDATE ai_use_intake_requests SET submitted_at = %s WHERE id = %s", (stamp, old["id"]))
    world.db.commit()
    got = view(world)
    buckets = {b["key"]: b["count"] for b in got["aging"]}
    assert buckets == {"0_2": 1, "3_7": 0, "8_14": 0, "15_plus": 1}
    assert sum(buckets.values()) == card(world, "new_requests")["value"] == 2


# ── Decisions ───────────────────────────────────────────────────────────────

def test_a_request_for_a_decision_is_awaiting_and_says_whose_it_is_to_decide(system):
    resolve_provider_review(system)
    ask(system, "dpo_a")
    got = card(system, "awaiting_decision", "owner_a")
    assert got["value"] == 1 and got["drilldown"] == "/ai-governance/decisions"
    assert got["detail"]["yours_to_decide"] == 1
    assert card(system, "awaiting_decision", "dpo_b")["value"] == 0
    asker = card(system, "awaiting_decision", "dpo_a")
    assert asker["value"] == 1 and asker["detail"]["yours_to_decide"] == 0, \
        "dpo_a asked, so separation of duties keeps the decision from them"


def test_conditions_are_counted_per_approval_with_the_overdue_ones_named(system):
    approve_with_conditions(system, due="2999-01-01", texts=("Review weekly", "Report quarterly"))
    got = card(system, "approved_with_conditions")
    assert got["value"] == 1 and got["detail"] == {"open_conditions": 2, "overdue_conditions": 0, "next_due": "2999-01-01"}
    system.db.execute("UPDATE ai_use_decision_conditions SET due_date = '2020-01-01' WHERE text = 'Review weekly'")
    system.db.commit()
    again = card(system, "approved_with_conditions")
    assert again["detail"]["overdue_conditions"] == 1 and again["detail"]["next_due"] == "2020-01-01"


def test_a_met_condition_is_no_longer_counted(system):
    done = approve_with_conditions(system, texts=("Review weekly",))
    condition = done["decision"]["conditions"][0]
    met = decisions.set_condition(system.db, user(system, "employee_a"), condition["id"], True, "Done on Friday.")
    commit(system, met, user(system, "employee_a"))
    assert card(system, "approved_with_conditions")["value"] == 0


def test_an_approval_whose_facts_moved_is_a_material_change(system):
    approve_with_conditions(system)
    assert card(system, "material_change")["value"] == 0
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    edited = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "Something new"}, profile["version"])
    commit(system, edited, user(system, "dpo_a"))
    got = card(system, "material_change")
    assert got["value"] == 1 and got["drilldown"] == "/ai-governance/decisions"
    assert card(system, "material_change", "dpo_b")["value"] == 0


# ── Reviews due ─────────────────────────────────────────────────────────────

def test_reviews_due_counts_dates_reached_and_names_those_inside_the_window(system):
    other = another_use(system)
    today = utcnow().date()
    for app, delta in ((system.app, -3), (other, 10)):
        system.db.execute("UPDATE ai_use_profiles SET next_review_at = %s WHERE application_id = %s",
                          ((today + timedelta(days=delta)).strftime("%Y-%m-%d"), app))
    system.db.commit()
    got = card(system, "reviews_due")
    assert got["value"] == 2 and got["detail"] == {"overdue": 1, "within_days": 30}
    assert got["drilldown"] == "/ai-governance/systems?state=review_soon"
    listed = workspace.list_systems(system.db, user(system, "dpo_a"), state="review_soon")
    assert listed["total"] == got["value"], "the card and its list agree"
    assert workspace.list_systems(system.db, user(system, "dpo_a"), state="review_due")["total"] == 1


# ── Evaluations and oversight ───────────────────────────────────────────────

def test_a_use_with_nothing_recorded_is_not_measured_and_never_counted_as_passing(system):
    got = card(system, "evaluation_oversight_gaps")
    assert got["value"] == 0 and got["state"] == "measured"
    assert got["detail"]["no_evaluation"] == 1 and got["detail"]["no_oversight"] == 1
    assert "not measured" in got["note"].lower()


def test_a_failed_evaluation_is_a_gap_and_a_passing_one_is_not(system):
    evaluations.record_run(system.db, user(system, "dpo_a"), system.app, RUN)
    system.db.commit()
    assert card(system, "evaluation_oversight_gaps")["value"] == 0
    evaluations.record_run(system.db, user(system, "dpo_a"), system.app,
                           {**RUN, "name": "Worse", "scores": {"citation_validity": 50}, "finished_at": "2026-10-05 09:00:00"})
    system.db.commit()
    got = card(system, "evaluation_oversight_gaps")
    assert got["value"] == 1 and got["detail"]["evaluation_failed"] == 1 and got["detail"]["no_evaluation"] == 0
    assert got["drilldown"] == "/ai-governance/monitoring?focus=evaluation_oversight"


def test_oversight_that_awaits_review_or_went_stale_is_a_gap(system):
    arrangement = {**COMPLETE, "responsible_user_id": user(system, "employee_a")["id"]}
    saved = oversight.save_arrangement(system.db, user(system, "dpo_a"), system.app, "design", arrangement, 0)
    system.db.commit()
    got = card(system, "evaluation_oversight_gaps")
    assert got["value"] == 1 and got["detail"]["oversight_attention"] == 1, "a draft nobody reviewed"
    reviewed = oversight.review_arrangement(system.db, user(system, "owner_a"), system.app, "design", saved["oversight"]["revision"])
    system.db.commit()
    assert card(system, "evaluation_oversight_gaps")["value"] == 0
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "Changed"}, profile["version"])
    system.db.commit()
    assert card(system, "evaluation_oversight_gaps")["value"] == 1, "the profile moved after the review"


def test_the_portfolio_lists_each_use_with_its_flags_in_scope_only(system):
    other = approve_new(system, submitted(system, "owner_b", answers={**FULL, "name": "In unit B"}), reviewer="dpo_b")["application_id"]
    evaluations.record_run(system.db, user(system, "dpo_a"), system.app,
                           {**RUN, "scores": {"citation_validity": 10}})
    system.db.commit()
    mine = monitoring.get_portfolio(system.db, user(system, "dpo_a"))
    assert [u["application_id"] for u in mine["uses"]] == [system.app]
    flags = {f["key"] for f in mine["uses"][0]["flags"]}
    assert "evaluation_failed" in flags and mine["with_gaps"] == 1 and mine["counts"]["evaluation_failed"] == 1
    assert mine["state"] == "measured" and mine["uses"][0]["url"] == f"/ai-governance/systems/{system.app}#monitoring"
    theirs = monitoring.get_portfolio(system.db, user(system, "dpo_b"))
    assert [u["application_id"] for u in theirs["uses"]] == [other] and theirs["with_gaps"] == 0
    assert len(monitoring.get_portfolio(system.db, user(system, "super"))["uses"]) == 2


# ── Truthfulness ────────────────────────────────────────────────────────────

def test_a_source_that_cannot_be_read_is_unavailable_and_the_rest_still_answer(system, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the table is gone")
    monkeypatch.setattr(decisions, "list_queue", broken)
    got = view(system)
    by_key = {c["key"]: c for c in got["cards"]}
    for key in ("awaiting_decision", "approved_with_conditions", "material_change"):
        assert by_key[key]["state"] == "unavailable" and by_key[key]["value"] is None, key
    assert by_key["new_requests"]["state"] == "measured"
    assert "not a count of zero" in by_key["awaiting_decision"]["note"]


def test_the_funnel_counts_stages_and_names_the_stages_nothing_measures_yet(world):
    one = submitted(world, "employee_a", answers={**FULL, "name": "Accepted"})
    submitted(world, "employee_a", answers={**FULL, "name": "Still new"})
    approve_new(world, one)
    f = view(world)["funnel"]
    stages = {s["key"]: s for s in f["detail"]["stages"]}
    assert f["state"] == "measured" and f["window"] == "last 90 days"
    assert stages["submitted"]["value"] == 2 and stages["triaged"]["value"] == 1 and stages["accepted"]["value"] == 1
    assert stages["assessed"]["value"] == 0 and stages["decided"]["value"] == 0
    assert stages["responded"]["state"] == "not_measured" and stages["responded"]["value"] is None
    assert stages["closed"]["state"] == "not_measured"
    assert f["denominator"] == {"value": 2, "label": "requests submitted in the window"}


# ── Staff ───────────────────────────────────────────────────────────────────

def test_staff_who_review_nothing_see_only_their_own_work(system):
    submitted(system, "owner_b")                                              # someone else's request: never counted
    draft(system, "employee_a")                                               # one draft
    submitted(system, "employee_a", answers={**FULL, "name": "Waiting use"})  # one submitted
    got = view(system, "employee_a")
    assert got["viewer"] == {"specialist": False, "reviewer": False, "decider": False}
    assert got["funnel"] is None and got["aging"] == []
    assert [c["key"] for c in got["cards"]] == ["my_requests", "my_systems"]
    mine = {c["key"]: c for c in got["cards"]}
    assert mine["my_requests"]["value"] == 2 and mine["my_requests"]["detail"] == {"draft": 1, "submitted": 1, "returned": 0}
    assert mine["my_systems"]["value"] == 1, "the one use they own"
    assert mine["my_requests"]["drilldown"] == "/ai-governance/requests"


def test_staff_cannot_ask_for_the_specialist_numbers_by_name(system):
    got = view(system, "employee_a")
    assert not {c["key"] for c in got["cards"]} & set(SPECIALIST_CARDS)


def test_the_rollout_switch_does_not_change_a_count(system):
    before = [c["value"] for c in view(system)["cards"]]
    ai_rollout.set_enabled(user(system, "dpo_a").get("org_id"), True)
    assert [c["value"] for c in view(system)["cards"]] == before, "the switch is a visibility control only"


# ── The conditions list the decisions page shows ────────────────────────────

def test_the_decisions_queue_names_each_approval_with_open_conditions(system):
    approve_with_conditions(system, due="2999-01-01", texts=("Review weekly",))
    listed = decisions.list_queue(system.db, user(system, "dpo_a"))["conditions"]
    assert len(listed) == 1
    entry = listed[0]
    assert (entry["application_id"], entry["name"], entry["open"], entry["overdue"]) == (system.app, "Ticket summarizer", 1, 0)
    assert entry["next_due"] == "2999-01-01" and entry["url"] == f"/ai-governance/systems/{system.app}#decisions"
    assert decisions.list_queue(system.db, user(system, "dpo_b"))["conditions"] == []
