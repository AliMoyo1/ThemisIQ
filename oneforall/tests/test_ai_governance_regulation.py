"""
AI governance G5: regulatory impact through the service layer.

Written by hand. A change in the Regulatory Inbox proposes only the uses whose intended jurisdictions it concerns, inside the
reviewer's own unit scope; a person confirms or dismisses each; a confirmation is one task for the owner and one event; a
dismissal needs a reason and does not come back unless the source change itself moves; and a confirmed change after a
decision reopens it.
"""
import pytest

from modules.ai_governance import decisions, guidance, regulation, service
from tests.test_ai_governance_service import FULL, approve_new, commit, count, fail, submitted, user
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401


@pytest.fixture
def system(world):
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    profile = service.get_profile(world.db, user(world, "dpo_a"), world.app)
    edited = service.update_profile(world.db, user(world, "dpo_a"), world.app, {"jurisdictions": ["EU", "ZW"]}, profile["version"])
    commit(world, edited, user(world, "dpo_a"))
    return world


def post_update(world, **fields):
    row = {"framework_name": "EU AI Act", "title": "Guidance on prohibited practices", "summary": "Clarifies Article 5.",
           "source_url": "https://example.test/eu/guidance", "effective_date": "2026-12-01", "severity": "high", "status": "open", **fields}
    update_id = _insert(world.db, "regulatory_updates", **row)
    world.db.commit()
    return update_id


def refresh(world, name="dpo_a"):
    done = regulation.refresh(world.db, user(world, name))
    commit(world, done, user(world, name))
    return done


# ── Candidates ──────────────────────────────────────────────────────────────

def test_a_change_proposes_the_uses_whose_jurisdictions_it_concerns_and_asking_again_adds_nothing(system):
    post_update(system)
    post_update(system, framework_name="ISO/IEC 42001", title="Revision")
    first = refresh(system)
    assert first["created"] == 1 and first["reopened"] == 0
    assert refresh(system)["created"] == 0
    queue = regulation.list_queue(system.db, user(system, "dpo_a"))
    assert [(i["title"], i["system"], i["status"]) for i in queue["items"]] == [("Guidance on prohibited practices", "Ticket summarizer", "candidate")]
    assert "EU" in queue["items"][0]["basis"] and queue["can_review"] is True and "Nothing here fetches" in queue["note"]


def test_a_use_whose_jurisdictions_do_not_include_it_is_not_proposed(system):
    post_update(system, framework_name="POPIA", title="South African change")
    assert refresh(system)["created"] == 0


def test_a_reviewer_only_proposes_uses_in_their_own_unit(system):
    post_update(system)
    assert refresh(system, "dpo_b")["created"] == 0, "the use sits in unit A"
    assert regulation.list_queue(system.db, user(system, "dpo_b"))["items"] == []
    assert refresh(system, "dpo_a")["created"] == 1
    assert regulation.list_queue(system.db, user(system, "dpo_b"))["items"] == []
    fail(lambda: regulation.refresh(system.db, user(system, "staff_a")), 403)
    assert [i["system"] for i in regulation.list_queue(system.db, user(system, "employee_a"))["items"]] == ["Ticket summarizer"]


# ── Reviewing ───────────────────────────────────────────────────────────────

def test_confirming_makes_one_task_for_the_owner_and_one_event_and_a_second_review_is_refused(system):
    post_update(system)
    refresh(system)
    item = regulation.list_queue(system.db, user(system, "dpo_a"))["items"][0]
    done = regulation.review(system.db, user(system, "dpo_a"), item["id"], "confirm", "Concerns our EU customers.", item["version"])
    commit(system, done, user(system, "dpo_a"))
    assert done["item"]["status"] == "confirmed" and len(done["events"]) == 1
    task = system.db.execute("SELECT title, assigned_to, priority, due_date FROM task_board WHERE title LIKE 'Regulatory change%'").fetchone()
    assert task["assigned_to"] == user(system, "employee_a")["id"] and task["priority"] == "high" and str(task["due_date"])[:10] == "2026-12-01"
    assert count(system, "task_board", "title LIKE 'Regulatory change%'") == 1
    fail(lambda: regulation.review(system.db, user(system, "dpo_a"), item["id"], "dismiss", "No.", item["version"] + 1), 409)
    assert [i["status"] for i in regulation.list_queue(system.db, user(system, "dpo_a"), "confirmed")["items"]] == ["confirmed"]
    assert [r["title"] for r in regulation.confirmed_for(system.db, user(system, "employee_a"), system.app)] == ["Guidance on prohibited practices"]


def test_dismissing_needs_a_reason_and_the_candidate_does_not_come_back(system):
    update_id = post_update(system)
    refresh(system)
    item = regulation.list_queue(system.db, user(system, "dpo_a"))["items"][0]
    fail(lambda: regulation.review(system.db, user(system, "dpo_a"), item["id"], "dismiss", " ", item["version"]), 422)
    fail(lambda: regulation.review(system.db, user(system, "dpo_a"), item["id"], "maybe", "x", item["version"]), 422)
    fail(lambda: regulation.review(system.db, user(system, "dpo_a"), item["id"], "dismiss", "Not our use.", "1"), 400)
    done = regulation.review(system.db, user(system, "dpo_a"), item["id"], "dismiss", "Not our use.", item["version"])
    commit(system, done, user(system, "dpo_a"))
    assert count(system, "task_board", "title LIKE 'Regulatory change%'") == 0
    again = refresh(system)
    assert again["created"] == 0 and again["reopened"] == 0
    assert regulation.list_queue(system.db, user(system, "dpo_a"))["items"] == []
    # the source change itself moved: a dismissed candidate is proposed again
    system.db.execute("UPDATE regulatory_updates SET effective_date = '2027-03-01' WHERE id = %s", (update_id,))
    system.db.commit()
    assert refresh(system)["reopened"] == 1
    assert [i["status"] for i in regulation.list_queue(system.db, user(system, "dpo_a"))["items"]] == ["candidate"]


def test_a_candidate_in_another_unit_is_a_404_for_the_reviewer(system):
    post_update(system)
    refresh(system)
    item = regulation.list_queue(system.db, user(system, "dpo_a"))["items"][0]
    fail(lambda: regulation.review(system.db, user(system, "dpo_b"), item["id"], "dismiss", "No.", item["version"]), 404)
    fail(lambda: regulation.review(system.db, user(system, "dpo_a"), 987654, "dismiss", "No.", 1), 404)
    fail(lambda: regulation.review(system.db, user(system, "staff_a"), item["id"], "dismiss", "No.", item["version"]), 403)
    fail(lambda: regulation.list_queue(system.db, user(system, "dpo_a"), "pending"), 400)


# ── A confirmed change after a decision ─────────────────────────────────────

def test_a_change_confirmed_after_an_approval_reopens_it(system):
    commit(system, guidance.set_step_not_applicable(system.db, user(system, "dpo_a"), system.app, "vendor", "Built by us."), user(system, "dpo_a"))
    asked = decisions.request_decision(system.db, user(system, "employee_a"), system.app, None)
    commit(system, asked, user(system, "employee_a"))
    brief = decisions.get_brief(system.db, user(system, "owner_a"), system.app)
    commit(system, decisions.decide(system.db, user(system, "owner_a"), asked["decision"]["id"], "approve", brief=brief["hash"],
                                    expected_version=1,
                                    override_reason="The remaining reviews are scheduled and documented for this pilot."
                                    if brief["needs_override"] else None), user(system, "owner_a"))
    system.db.execute("UPDATE ai_use_decisions SET decided_at = '2026-01-01 00:00:00'")
    system.db.commit()
    assert decisions.get_decisions(system.db, user(system, "owner_a"), system.app)["state"]["state"] == "approved"
    post_update(system)
    refresh(system)
    item = regulation.list_queue(system.db, user(system, "dpo_a"))["items"][0]
    commit(system, regulation.review(system.db, user(system, "dpo_a"), item["id"], "confirm", None, item["version"]), user(system, "dpo_a"))
    state = decisions.get_decisions(system.db, user(system, "owner_a"), system.app)["state"]
    assert state["state"] == "needs_re_review" and any("regulatory change" in r.lower() for r in state["reasons"])
