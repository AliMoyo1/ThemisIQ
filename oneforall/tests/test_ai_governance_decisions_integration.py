"""
AI governance G4: who is told, and what shows in My Work.

Written by hand. A decider hears that a request is waiting; the people it concerns hear what was decided, never the person
who decided; a covered change tells the owner and the deciders only when there was an approval to reopen; delivering the
same event again tells nobody twice; and My Work shows one entry per thing the person has to act on or is waiting for,
read through the same unit scope as the module's own pages.
"""
import json

import pytest

import modules.ai_governance.handlers  # noqa: F401  (registers the event handlers)
from core import ai_rollout, events
from modules.ai_governance import decisions, guidance, service
from modules.launcher import my_work_service
from tests.test_ai_governance_service import FULL, approve_new, commit, count, roles, submitted, user  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401


@pytest.fixture
def system(world, roles):
    done = approve_new(world, submitted(world, answers=FULL))
    world.app = done["application_id"]
    return world


def resolve(world):
    commit(world, guidance.set_step_not_applicable(world.db, user(world, "dpo_a"), world.app, "vendor", "Built by us."), user(world, "dpo_a"))


def ask(world, name="employee_a"):
    done = decisions.request_decision(world.db, user(world, name), world.app, "Ready.")
    commit(world, done, user(world, name))
    return done["decision"], done


def decide(world, row, outcome="approve", name="owner_a", **kw):
    brief = decisions.get_brief(world.db, user(world, name), world.app)
    if outcome in ("approve", "approve_with_conditions") and brief["needs_override"]:
        kw.setdefault("override_reason", "The remaining reviews are scheduled and documented for this pilot.")
    done = decisions.decide(world.db, user(world, name), row["id"], outcome, brief=brief["hash"], expected_version=row["version"], **kw)
    commit(world, done, user(world, name))
    return done


def told(world, title):
    rows = world.db.execute("SELECT user_id FROM notifications WHERE module = 'ai_governance' AND title = %s ORDER BY user_id", (title,)).fetchall()
    return sorted(r[0] for r in rows)


def ids(world, *names):
    return sorted(user(world, n)["id"] for n in names)


def work(world, name):
    """The entries AI Governance puts in a person's My Work. Notifications are listed by their own source, not here."""
    out = my_work_service.get_my_work(user(world, name), page_size=100)
    return [(sec, i["entity_type"], i["title"]) for sec, items in out["sections"].items() for i in items
            if i["source_module"] == "ai_governance" and i["entity_type"] != "notification"]


# ── Notifications ───────────────────────────────────────────────────────────

def test_the_deciders_in_the_systems_unit_are_told_and_the_asker_and_owner_are_not(system):
    ask(system)
    assert told(system, "AI use waiting for a decision") == ids(system, "dpo_a", "owner_a", "risk_only_a")


def test_a_decision_tells_the_asker_and_the_owner_and_never_the_decider(system):
    resolve(system)
    row, _ = ask(system, "dpo_a")
    decide(system, row, "approve", rationale="Low tier and the provider is reviewed.")
    assert told(system, "A decision was made on your AI use") == ids(system, "dpo_a", "employee_a"), \
        "dpo_a asked and employee_a owns it; owner_a decided"
    [note] = [r["message"] for r in system.db.execute(
        "SELECT message FROM notifications WHERE title = 'A decision was made on your AI use' AND user_id = %s", (user(system, "employee_a")["id"],))]
    assert "approved" in note and "Low tier" in note


def test_delivering_the_same_event_again_tells_nobody_twice(system):
    _row, done = ask(system)
    before = told(system, "AI use waiting for a decision")
    event = done["events"][0]
    conn = system.db
    conn.execute("DELETE FROM event_deliveries WHERE event_id = %s", (event,))
    conn.execute("UPDATE events SET status = 'pending' WHERE id = %s", (event,))
    conn.commit()
    events.deliver(event)
    assert told(system, "AI use waiting for a decision") == before


def test_a_change_to_a_covered_fact_tells_the_owner_and_deciders_only_when_there_was_an_approval(system):
    resolve(system)
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    first = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "A first change"}, profile["version"])
    commit(system, first, user(system, "dpo_a"))
    assert told(system, "An approved AI use needs a new decision") == [], "nothing was approved, so there is nothing to reopen"

    resolve(system)  # the first change made the earlier ruling out of date
    row, _ = ask(system)
    decide(system, row, "approve")
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    second = service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "A second change"}, profile["version"])
    commit(system, second, user(system, "dpo_a"))
    assert told(system, "An approved AI use needs a new decision") == ids(system, "employee_a", "owner_a", "risk_only_a"), "not dpo_a, who made the change"


def test_a_revocation_tells_the_people_it_concerns_and_not_the_one_who_revoked(system):
    resolve(system)
    row, _ = ask(system)
    decide(system, row, "approve")
    done = decisions.revoke(system.db, user(system, "owner_a"), row["id"], "The provider changed its terms.")
    commit(system, done, user(system, "owner_a"))
    assert told(system, "An approval was revoked") == ids(system, "employee_a")


# ── My Work ─────────────────────────────────────────────────────────────────

def test_a_request_is_a_decision_to_make_for_a_decider_and_a_wait_for_the_asker(system):
    ask(system)
    assert ("needs_my_action", "ai_decision", "Decide: Ticket summarizer") in work(system, "owner_a")
    assert ("waiting_on_others", "ai_decision_waiting", "Waiting for a decision: Ticket summarizer") in work(system, "employee_a")
    assert not [w for w in work(system, "employee_a") if w[1] == "ai_decision"], "the owner may not decide their own, so is not asked to"
    assert work(system, "dpo_b") == [] and work(system, "owner_b") == [], "another unit sees nothing of it"


def test_a_decided_request_leaves_my_work_and_a_change_to_an_approval_returns_as_a_new_decision(system):
    resolve(system)
    row, _ = ask(system)
    decide(system, row, "approve")
    assert [w for w in work(system, "owner_a") if w[1] in ("ai_decision", "ai_decision_waiting")] == []
    profile = service.get_profile(system.db, user(system, "dpo_a"), system.app)
    commit(system, service.update_profile(system.db, user(system, "dpo_a"), system.app, {"purpose": "Changed"}, profile["version"]),
           user(system, "dpo_a"))
    for name in ("employee_a", "owner_a"):
        assert ("needs_my_action", "ai_re_review", "Needs a new decision: Ticket summarizer") in work(system, name), name
    assert work(system, "dpo_b") == []


def test_a_condition_with_a_due_date_is_the_owners_work_until_it_is_met(system):
    resolve(system)
    row, _ = ask(system)
    from datetime import timedelta
    from core.timeutils import utcnow
    due = (utcnow() + timedelta(days=10)).strftime("%Y-%m-%d")
    done = decide(system, row, "approve_with_conditions", conditions=[{"text": "Review monthly", "due_date": due}])
    cid = done["decision"]["conditions"][0]["id"]
    assert ("due_soon", "ai_condition", "Condition due: Review monthly (Ticket summarizer)") in work(system, "employee_a")
    met = decisions.set_condition(system.db, user(system, "employee_a"), cid, True)
    commit(system, met, user(system, "employee_a"))
    assert [w for w in work(system, "employee_a") if w[1] == "ai_condition"] == []


def test_intake_requests_show_for_the_reviewer_while_waiting_and_for_the_author_when_returned(world, roles):
    sent = submitted(world)
    assert any(w[1] == "ai_intake_review" for w in work(world, "dpo_a"))
    assert not [w for w in work(world, "employee_a") if w[1] == "ai_intake_review"], "an author is not their own reviewer"
    returned = service.return_to_author(world.db, user(world, "dpo_a"), sent["id"], "Name the data the vendor sees.", sent["version"])
    commit(world, returned, user(world, "dpo_a"))
    assert any(w[1] == "ai_intake_returned" and w[2].startswith("Update your AI use request") for w in work(world, "employee_a"))
    assert not [w for w in work(world, "dpo_a") if w[1] == "ai_intake_review"]


def test_ai_governance_work_is_hidden_when_the_organization_has_it_switched_off(system):
    ask(system)
    assert work(system, "owner_a")
    ai_rollout.set_enabled(user(system, "owner_a")["org_id"], False)
    assert work(system, "owner_a") == []
