"""
Naming the reviewer of a request and the decider of a decision request
(plans/2026-10-governance-rework/06 sections 3 and 4, follow-up 11).

Expectations are written by hand. Nobody named is the earlier behaviour and sends no email; naming one person tells that
person, in the app and by email, and shows the item to everybody else as waiting on them. Each "may not be named" has a
positive twin.
"""
import json

import pytest

from core import email as mail
from core import email_outbox as outbox
from modules.ai_governance import assignment, decisions, handlers, service
from modules.launcher import my_work_service
from tests.test_ai_governance_decisions import ask, resolve_provider_review, system  # noqa: F401
from tests.test_ai_governance_service import FULL, commit, count, fail, roles, submitted, user  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401


class Provider:
    def __init__(self):
        self.calls = []

    def __call__(self, *, to, subject, body_html, body_text=None):
        self.calls.append({"to": to, "subject": subject, "html": body_html, "text": body_text})
        return {"status": mail.STATUS_ACCEPTED, "ok": True, "provider": "fake"}


@pytest.fixture
def provider(monkeypatch):
    fake = Provider()
    monkeypatch.setattr(mail, "send_email", fake)
    monkeypatch.setenv("APP_URL", "https://app.themisiq.net")
    return fake


def _names(people):
    return sorted(p["name"] for p in people)


def _outbox(world, template=None):
    rows = [dict(r) for r in world.db.execute("SELECT * FROM email_outbox ORDER BY id").fetchall()]
    return [r for r in rows if template is None or r["template_key"] == template]


def _notices(world, who, like="%"):
    return [dict(r) for r in world.db.execute(
        "SELECT title, link FROM notifications WHERE user_id = %s AND module = 'ai_governance' AND title LIKE %s ORDER BY id",
        (user(world, who)["id"], like)).fetchall()]


# ── A request waiting for review ────────────────────────────────────────────

def test_only_people_who_may_review_and_open_the_request_can_be_named(roles):
    w = roles
    intake = submitted(w, answers=FULL)                                # employee_a, unit A
    people = assignment.reviewers_for(w.db, user(w, "dpo_a"), intake["id"])
    assert _names(people) == ["dpo_a", "owner_a"], \
        "the unit's reviewers; not the unit below it, another unit, nobody with no unit, nor the author"
    assert user(w, "employee_a")["id"] not in {p["id"] for p in people}


def test_naming_a_reviewer_tells_that_person_by_name_in_the_app_and_by_email(roles, provider):
    w = roles
    intake = submitted(w, answers=FULL)
    got = assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], user(w, "owner_a")["id"])
    commit(w, got, user(w, "dpo_a"))
    assert got["changed"] is True and got["intake"]["assigned_reviewer_id"] == user(w, "owner_a")["id"]
    assert got["intake"]["assigned_reviewer_name"] == "owner_a"
    assert [n["title"] for n in _notices(w, "owner_a", "%assigned to you%")] == [
        "An AI use request was assigned to you for review"]
    (row,) = _outbox(w, "action.assigned")
    assert row["recipient_user_id"] == user(w, "owner_a")["id"] and row["route"] == "/ai-governance/review"
    assert json.loads(row["fields_json"]) == {"kind": "ai_use_review", "reference": f"AIR-{intake['id']}"}
    assert provider.calls == []
    outbox.deliver_due(w.db)
    (call,) = provider.calls
    assert call["to"] == "owner_a@example.test" and f"Reference: AIR-{intake['id']}." in call["text"]
    assert "An AI use review is assigned to you" in call["text"]

    again = assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], user(w, "owner_a")["id"])
    commit(w, again, user(w, "dpo_a"))
    assert again["changed"] is False and again["events"] == [], "the same name again is nothing new"


def test_handing_the_review_to_someone_else_stops_mail_to_the_first_and_clearing_the_name_goes_back_to_everyone(roles, provider):
    w = roles
    intake = submitted(w, answers=FULL)
    first = assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], user(w, "owner_a")["id"])
    commit(w, first, user(w, "dpo_a"))
    second = assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], user(w, "dpo_a")["id"])
    commit(w, second, user(w, "dpo_a"))
    outbox.deliver_due(w.db)
    by_person = {r["recipient_user_id"]: r for r in _outbox(w, "action.assigned")}
    assert by_person[user(w, "owner_a")["id"]]["suppress_reason"] == "no_longer_open", "a transfer stops the old message"
    assert by_person[user(w, "dpo_a")["id"]]["status"] == "provider_accepted"
    assert [c["to"] for c in provider.calls] == ["dpo_a@example.test"]

    cleared = assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], None)
    commit(w, cleared, user(w, "dpo_a"))
    assert cleared["changed"] is True and cleared["intake"]["assigned_reviewer_id"] is None
    assert cleared["events"] == [], "taking a name off tells nobody by email"


def test_a_request_with_a_named_reviewer_is_not_announced_again_to_everyone(roles):
    w = roles
    intake = submitted(w, answers=FULL)
    before = len(_notices(w, "dpo_a", "%waiting for review%"))
    assert before == 1, "unnamed: everyone in scope was told in the app when it was submitted"
    got = assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], user(w, "owner_a")["id"])
    commit(w, got, user(w, "dpo_a"))
    handlers.tell_reviewers(payload={"intake_id": intake["id"]}, event_id=987001, org_id=1)
    assert len(_notices(w, "dpo_a", "%waiting for review%")) == before, "a named request is not announced again"
    assert _outbox(w) and all(r["template_key"] == "action.assigned" for r in _outbox(w)), \
        "and nobody was ever mailed about it by default"


def test_a_reviewer_who_may_not_be_named_is_refused(roles):
    w = roles
    intake = submitted(w, answers=FULL)
    for who in ("employee_a", "dpo_b", "dpo_a1", "dpo_no_unit"):
        fail(lambda who=who: assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], user(w, who)["id"]), 422)
    fail(lambda: assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], 987654), 422)
    fail(lambda: assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], "owner_a"), 422)
    fail(lambda: assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], True), 422)
    fail(lambda: assignment.assign_reviewer(w.db, user(w, "employee_a"), intake["id"], user(w, "owner_a")["id"]), 403)
    fail(lambda: assignment.assign_reviewer(w.db, user(w, "dpo_b"), intake["id"], user(w, "owner_a")["id"]), 404)
    assert w.db.execute("SELECT assigned_reviewer_id FROM ai_use_intake_requests WHERE id = %s",
                        (intake["id"],)).fetchone()[0] is None


def test_the_author_cannot_review_their_own_request(roles):
    w = roles
    mine = submitted(w, name="owner_a", answers=FULL)          # a risk owner may review, but not their own
    fail(lambda: assignment.assign_reviewer(w.db, user(w, "dpo_a"), mine["id"], user(w, "owner_a")["id"]), 422)
    ok = assignment.assign_reviewer(w.db, user(w, "dpo_a"), mine["id"], user(w, "dpo_a")["id"])
    assert ok["changed"] is True


def test_a_request_that_is_no_longer_waiting_cannot_be_assigned(roles):
    w = roles
    intake = submitted(w, answers=FULL)
    done = service.return_to_author(w.db, user(w, "dpo_a"), intake["id"], "Add the owner.", intake["version"])
    commit(w, done, user(w, "dpo_a"))
    fail(lambda: assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], user(w, "owner_a")["id"]), 409)


def test_my_work_shows_a_named_review_as_mine_and_to_the_others_as_waiting_on_someone(roles):
    w = roles
    intake = submitted(w, answers=FULL)
    got = assignment.assign_reviewer(w.db, user(w, "dpo_a"), intake["id"], user(w, "owner_a")["id"])
    commit(w, got, user(w, "dpo_a"))

    def titles(name, section):
        return [i["title"] for i in my_work_service.get_my_work(user(w, name))["sections"][section]
                if i["entity_type"] == "ai_intake_review"]

    assert titles("owner_a", "needs_my_action") and "Review AI use request" in titles("owner_a", "needs_my_action")[0]
    assert titles("dpo_a", "needs_my_action") == []
    assert titles("dpo_a", "waiting_on_others") == [f"Assigned to another reviewer: {FULL['name']}"]


# ── A decision request ──────────────────────────────────────────────────────

def test_only_people_who_may_decide_and_not_the_asker_or_the_owner_can_be_named(system, roles):
    w = system
    row = ask(w, "dpo_a")                                              # asked by a reviewer; the owner is employee_a
    people = assignment.deciders_for(w.db, user(w, "owner_a"), row["id"])
    assert "dpo_a" not in _names(people), "whoever asked may not decide it"
    assert "owner_a" in _names(people)
    assert "employee_a" not in _names(people), "the owner of the use, and not a decider anyway"


def test_naming_a_decider_tells_that_person_a_decision_is_asked_of_them_and_not_that_anything_is_approved(system, roles, provider):
    w = system
    resolve_provider_review(w)
    row = ask(w)
    got = assignment.assign_decider(w.db, user(w, "dpo_a"), row["id"], user(w, "owner_a")["id"])
    commit(w, got, user(w, "dpo_a"))
    assert got["changed"] is True and got["decision"]["assigned_decider"] == "owner_a"
    assert got["decision"]["version"] == row["version"], "naming a decider does not change what is being decided"
    assert [n["title"] for n in _notices(w, "owner_a", "%asked of you%")] == ["A decision on an AI use was asked of you"]
    (mail_row,) = _outbox(w, "decision.ready")
    assert mail_row["recipient_user_id"] == user(w, "owner_a")["id"]
    assert json.loads(mail_row["fields_json"]) == {"reference": f"AID-{row['id']}"}
    outbox.deliver_due(w.db)
    (call,) = provider.calls
    assert call["to"] == "owner_a@example.test" and "not a decision" in call["text"]
    assert f"https://app.themisiq.net/ai-governance/systems/{w.app}" in call["text"]


def test_a_decider_who_may_not_be_named_is_refused_and_the_named_one_is_not_the_only_one_who_may_decide(system, roles):
    w = system
    resolve_provider_review(w)
    row = ask(w, "dpo_a")
    for who in ("dpo_a", "employee_a", "dpo_b", "dpo_no_unit"):
        fail(lambda who=who: assignment.assign_decider(w.db, user(w, "owner_a"), row["id"], user(w, who)["id"]), 422)
    fail(lambda: assignment.assign_decider(w.db, user(w, "employee_a"), row["id"], user(w, "owner_a")["id"]), 403)
    fail(lambda: assignment.assign_decider(w.db, user(w, "dpo_b"), row["id"], user(w, "owner_a")["id"]), 404)
    got = assignment.assign_decider(w.db, user(w, "dpo_a"), row["id"], user(w, "owner_a")["id"])
    commit(w, got, user(w, "dpo_a"))
    decided = decisions.decide(w.db, user(w, "owner_a"), row["id"], "approve",
                               brief=decisions.get_brief(w.db, user(w, "owner_a"), w.app)["hash"],
                               expected_version=row["version"])
    assert decided["decision"]["status"] == "approved", "the named decider decides it as any decider would"
    fail(lambda: assignment.assign_decider(w.db, user(w, "dpo_a"), row["id"], user(w, "owner_a")["id"]), 409)


def test_my_work_shows_a_named_decision_as_mine_and_to_the_other_deciders_as_waiting_on_someone(system, roles):
    w = system
    resolve_provider_review(w)
    row = ask(w)
    got = assignment.assign_decider(w.db, user(w, "dpo_a"), row["id"], user(w, "owner_a")["id"])
    commit(w, got, user(w, "dpo_a"))

    def titles(name, section):
        return [i["title"] for i in my_work_service.get_my_work(user(w, name))["sections"][section]
                if i["entity_type"] == "ai_decision"]

    assert [t.startswith("Decide:") for t in titles("owner_a", "needs_my_action")] == [True]
    assert titles("dpo_a", "needs_my_action") == []
    assert titles("dpo_a", "waiting_on_others") and titles("dpo_a", "waiting_on_others")[0].startswith("Assigned to another decider")


def test_the_team_view_counts_a_named_decision_against_the_person_named_and_an_unnamed_one_against_nobody(system, roles):
    w = system
    resolve_provider_review(w)
    row = ask(w)
    w.db.execute("UPDATE business_units SET head_user_id = %s WHERE id = %s", (user(w, "dpo_a")["id"], w.unit["A"]))
    w.db.commit()

    def needs_action(name):
        team = {m["name"]: m for m in my_work_service.get_team_work(user(w, "dpo_a"))["members"]}
        return team[name]["counts"]["needs_my_action"]

    before = needs_action("owner_a")
    got = assignment.assign_decider(w.db, user(w, "dpo_a"), row["id"], user(w, "owner_a")["id"])
    commit(w, got, user(w, "dpo_a"))
    assert needs_action("owner_a") == before + 1, "named: it is assigned to them"
    assert needs_action("employee_a") == 0, "a queue anyone who may decide sees is not charged to a person"
    cleared = assignment.assign_decider(w.db, user(w, "dpo_a"), row["id"], None)
    commit(w, cleared, user(w, "dpo_a"))
    assert needs_action("owner_a") == before, "the name taken off: back to the shared queue"
