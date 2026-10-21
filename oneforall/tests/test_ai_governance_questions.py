"""
Questions for the requester of a request (plans/2026-10-governance-rework/01 section 5), through the service layer and HTTP.

Written by hand. The requester has no account: questions leave as text and the answer is entered by a specialist with
where it came from. A request with an open question is waiting for information, and the Overview counts it from the same
place. Only a reviewer in the request unit can ask or answer; its own author can read.
"""
import pytest

from modules.ai_governance import overview
from modules.ai_governance import questions as q
from modules.ai_governance import service
from tests.test_ai_governance_routes import _submit, http  # noqa: F401
from tests.test_ai_governance_service import FULL, approve_new, commit, count, fail, roles, submitted, user  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401


@pytest.fixture
def request_(world):
    return submitted(world, "employee_a")


def ask(world, intake, who="dpo_a", texts=("Which vendor contract covers this?",)):
    done = q.ask(world.db, user(world, who), intake["id"], list(texts))
    commit(world, done, user(world, who))
    return done


def test_a_reviewer_asks_and_the_questions_are_numbered_in_order(world, request_):
    done = ask(world, request_, texts=("Which vendor contract covers this?", "Who signs off the data sharing?"))
    assert [(x["position"], x["status"]) for x in done["questions"]] == [(1, "open"), (2, "open")]
    assert done["open"] == 2 and done["audit"][0][0] == "ai_questions_asked"
    more = ask(world, request_, texts=("Is any of the data about children?",))
    assert [x["position"] for x in more["questions"]] == [1, 2, 3]


def test_only_a_specialist_in_the_unit_may_ask_or_answer_and_the_author_may_read(world, request_):
    fail(lambda: q.ask(world.db, user(world, "staff_a"), request_["id"], ["Is this fine for you?"]), 403)
    fail(lambda: q.ask(world.db, user(world, "dpo_b"), request_["id"], ["Is this fine for you?"]), 404)
    done = ask(world, request_)
    qid = done["questions"][0]["id"]
    fail(lambda: q.answer(world.db, user(world, "dpo_b"), qid, "Yes", "email", 1), 404)
    fail(lambda: q.answer(world.db, user(world, "staff_a"), qid, "Yes", "email", 1), 403)
    seen = q.list_questions(world.db, user(world, "employee_a"), request_["id"])
    assert [x["text"] for x in seen["questions"]] == ["Which vendor contract covers this?"] and seen["can_ask"] is True
    fail(lambda: q.list_questions(world.db, user(world, "dpo_b"), request_["id"]), 404)
    fail(lambda: q.list_questions(world.db, user(world, "owner_b"), request_["id"]), 404)


def test_questions_are_checked_and_bounded(world, request_):
    for bad in (["x"], [""], [5], [], "a question", ["y" * 501]):
        fail(lambda b=bad: q.ask(world.db, user(world, "dpo_a"), request_["id"], b), 422)
    ask(world, request_, texts=[f"Question number {n} to answer?" for n in range(q.MAX_QUESTIONS)])
    fail(lambda: q.ask(world.db, user(world, "dpo_a"), request_["id"], ["One too many questions?"]), 422)


def test_an_answer_records_who_entered_it_and_where_it_came_from(world, request_):
    qid = ask(world, request_)["questions"][0]["id"]
    done = q.answer(world.db, user(world, "dpo_a"), qid, "Contract ACME-2026 covers it.", "Email from Pat, 12 October", 1)
    commit(world, done, user(world, "dpo_a"))
    got = done["question"]
    assert (got["status"], got["answer"], got["answer_source"], got["answered_by"]) == (
        "answered", "Contract ACME-2026 covers it.", "Email from Pat, 12 October", "dpo_a")
    assert done["audit"][0][0] == "ai_question_answered"
    fail(lambda: q.answer(world.db, user(world, "dpo_a"), qid, "Changed", "email", 1), 409)  # a stale version
    for text, source in (("", "email"), ("Yes", ""), ("Yes", "no"), ("x" * 2001, "email"), ("Yes", "y" * 121)):
        fail(lambda t=text, s=source: q.answer(world.db, user(world, "dpo_a"), qid, t, s, 2), 422)
    fail(lambda: q.answer(world.db, user(world, "dpo_a"), qid, "Yes", "email", True), 400)


def test_a_withdrawn_question_cannot_be_answered_and_an_answered_one_cannot_be_withdrawn(world, request_):
    first, second = ask(world, request_, texts=("First question here?", "Second question here?"))["questions"]
    gone = q.withdraw(world.db, user(world, "dpo_a"), first["id"], 1)
    commit(world, gone, user(world, "dpo_a"))
    assert [x["status"] for x in gone["questions"]] == ["withdrawn", "open"]
    fail(lambda: q.answer(world.db, user(world, "dpo_a"), first["id"], "Yes", "email", 2), 409)
    answered = q.answer(world.db, user(world, "dpo_a"), second["id"], "Yes", "email", 1)
    commit(world, answered, user(world, "dpo_a"))
    fail(lambda: q.withdraw(world.db, user(world, "dpo_a"), second["id"], 2), 409)


def test_the_export_is_plain_text_of_the_open_questions_only_and_is_audited(world, request_):
    qs = ask(world, request_, texts=("First question here?", "Second question here?"))["questions"]
    commit(world, q.answer(world.db, user(world, "dpo_a"), qs[0]["id"], "Done", "phone call", 1), user(world, "dpo_a"))
    done = q.export_text(world.db, user(world, "dpo_a"), request_["id"])
    assert done["count"] == 1 and done["audit"][0][0] == "ai_questions_exported"
    text = done["text"]
    assert "Questions about: Ticket summarizer" in text and "1. Second question here?" in text
    assert "First question here?" not in text and "Done" not in text
    commit(world, q.answer(world.db, user(world, "dpo_a"), qs[1]["id"], "Also done", "phone call", 1), user(world, "dpo_a"))
    fail(lambda: q.export_text(world.db, user(world, "dpo_a"), request_["id"]), 409)


def test_a_decided_request_takes_no_new_questions(world):
    row = submitted(world, "employee_a")
    approved = service.approve(world.db, user(world, "dpo_a"), row["id"], row["version"], new_application={})
    commit(world, approved, user(world, "dpo_a"))
    fail(lambda: q.ask(world.db, user(world, "dpo_a"), row["id"], ["Anything else at all?"]), 409)


def test_an_open_question_makes_the_request_waiting_and_the_overview_counts_it_from_the_same_place(world, request_):
    assert service.review_count(world.db, user(world, "dpo_a"), "waiting") == 0
    done = ask(world, request_)
    assert service.review_count(world.db, user(world, "dpo_a"), "waiting") == 1
    assert [r["id"] for r in service.review_queue(world.db, user(world, "dpo_a"), "waiting")] == [request_["id"]]
    assert q.waiting_ids(world.db, user(world, "dpo_a")) == [request_["id"]]
    card = {c["key"]: c for c in overview.get_overview(world.db, user(world, "dpo_a"))["cards"]}["waiting_for_information"]
    assert card["value"] == 1 and card["drilldown"] == "/ai-governance/review?stage=needs_clarification"
    assert service.review_count(world.db, user(world, "dpo_b"), "waiting") == 0
    commit(world, q.answer(world.db, user(world, "dpo_a"), done["questions"][0]["id"], "Yes", "email", 1), user(world, "dpo_a"))
    assert service.review_count(world.db, user(world, "dpo_a"), "waiting") == 0, "answered means no longer waiting"


def test_the_workspace_names_the_request_a_use_came_from_for_a_reviewer_only(world, request_):
    from modules.ai_governance import workspace
    done = service.approve(world.db, user(world, "dpo_a"), request_["id"], request_["version"], new_application={})
    commit(world, done, user(world, "dpo_a"))
    app = done["application_id"]
    shown = workspace.get_system(world.db, user(world, "dpo_a"), app)
    assert shown["source_request"] == {"id": request_["id"], "revision": 1, "imported": False}
    assert workspace.get_system(world.db, user(world, "viewer_a"), app)["source_request"] is None, "not a reviewer"
    plain = _insert(world.db, "applications", name="Plain", business_unit_id=world.unit["A"], is_active=1)
    assert workspace.get_system(world.db, user(world, "dpo_a"), plain)["source_request"] is None, "never came from a request"


def test_questions_through_http(http):
    row = _submit(http, "employee_a")
    base = f"/ai-governance/api/requests/{row['id']}/questions"
    assert http("post", base, name="staff_a", json={"questions": ["Is this fine?"]}).status_code == 403
    assert http("post", base, name="dpo_b", json={"questions": ["Is this fine?"]}).status_code == 404
    made = http("post", base, name="dpo_a", json={"questions": ["Which vendor contract covers this?"]})
    assert made.status_code == 201 and made.json()["open"] == 1
    assert http("post", base, name="dpo_a", content=b"[1]", headers={"content-type": "application/json"}).status_code == 400
    listed = http("get", base, name="employee_a").json()
    assert listed["ok"] is True and listed["questions"][0]["status"] == "open" and listed["can_ask"] is True
    assert http("get", base, name="auditor").status_code == 403
    exported = http("post", base + "/export", name="dpo_a", json={})
    assert exported.status_code == 200 and "1. Which vendor contract covers this?" in exported.json()["text"]
    assert exported.headers["cache-control"] == "private, no-store"
    qid = made.json()["questions"][0]["id"]
    done = http("post", f"/ai-governance/api/questions/{qid}/answer", name="dpo_a",
                json={"answer": "ACME-2026", "source": "Email from Pat", "version": 1})
    assert done.status_code == 200 and done.json()["question"]["status"] == "answered"
    waiting = http("get", "/ai-governance/api/review/queue?status=waiting", name="dpo_a").json()["items"]
    assert waiting == []
