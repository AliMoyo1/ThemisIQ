"""
AI governance G4 through HTTP: asking for a decision, the brief, deciding, withdrawing, revoking, conditions and the queue.

Written by hand: a person not signed in is sent to log in, a person without the capability gets 403, a system the caller
may not open answers exactly like one that does not exist, a body that is not a JSON object is refused before anything
runs, and a decision cannot be signed over a brief that has since moved.
"""
import pytest

from tests.test_ai_governance_routes import _accepted, http  # noqa: F401
from tests.test_platform_ownership import _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401

API = "/ai-governance/api"


def _ask(http, app, name="employee_a", note=None):
    response = http("post", f"{API}/systems/{app}/decisions", name=name, json={"note": note})
    assert response.status_code in (200, 201), response.text
    return response.json()["decision"]


def _resolve(http, app):
    """Rule the one required step out, so an approval needs no override."""
    assert http("put", f"{API}/systems/{app}/checklist/vendor", name="dpo_a", json={"reason": "Built by us under licence."}).status_code == 200


def _decide(http, app, decision, outcome="approve", name="owner_a", **body):
    brief = http("get", f"{API}/systems/{app}/decision-brief", name=name).json()
    payload = {"outcome": outcome, "brief_hash": brief["hash"], "version": decision["version"], **body}
    return http("post", f"{API}/decisions/{decision['id']}/decide", name=name, json=payload)


# ── Who may call what ───────────────────────────────────────────────────────

READS = ("/systems/1/decisions", "/systems/1/decision-brief", "/decisions", "/decisions/1")


def test_nobody_signed_out_reaches_any_decision_page_or_call(http):
    for tail in READS:
        assert http("get", f"{API}{tail}", name=None).status_code == 303, tail
    assert http("get", "/ai-governance/decisions", name=None).status_code == 303
    for method, tail in (("post", "/systems/1/decisions"), ("post", "/decisions/1/decide"), ("post", "/decisions/1/withdraw"),
                         ("post", "/decisions/1/revoke"), ("put", "/decision-conditions/1")):
        assert http(method, f"{API}{tail}", name=None, json={}).status_code == 303, tail


def test_an_outside_auditor_is_refused_everywhere(http):
    for tail in READS:
        assert http("get", f"{API}{tail}", name="auditor").status_code == 403, tail
    assert http("get", "/ai-governance/decisions", name="auditor").status_code == 403
    for method, tail in (("post", "/systems/1/decisions"), ("post", "/decisions/1/decide"), ("post", "/decisions/1/revoke")):
        assert http(method, f"{API}{tail}", name="auditor", json={}).status_code == 403, tail


def test_staff_may_ask_and_read_and_may_not_decide_or_revoke(http):
    app = _accepted(http)
    assert http("get", f"{API}/systems/{app}/decisions", name="employee_a").status_code == 200
    assert http("get", f"{API}/systems/{app}/decision-brief", name="employee_a").status_code == 200
    decision = _ask(http, app, "employee_a", "Ready.")
    assert http("get", "/ai-governance/decisions", name="employee_a").status_code == 200
    brief = http("get", f"{API}/systems/{app}/decision-brief", name="employee_a").json()
    assert http("post", f"{API}/decisions/{decision['id']}/decide", name="employee_a",
                json={"outcome": "approve", "brief_hash": brief["hash"], "version": 1}).status_code == 403
    assert http("post", f"{API}/decisions/{decision['id']}/revoke", name="employee_a", json={"reason": "No."}).status_code == 403
    state = http("get", f"{API}/systems/{app}/decisions", name="employee_a").json()
    assert state["can"]["decide"] is False and state["can"]["withdraw"] is True and state["state"]["waiting"] is True


def test_a_system_in_another_unit_answers_like_one_that_is_not_there(http):
    app = _accepted(http)
    decision = _ask(http, app)
    calls = (("get", "/systems/{}/decisions", None), ("get", "/systems/{}/decision-brief", None),
             ("post", "/systems/{}/decisions", {"note": "x"}))
    for method, tail, body in calls:
        hidden = http(method, f"{API}{tail.format(app)}", name="dpo_b", **({"json": body} if body is not None else {}))
        gone = http(method, f"{API}{tail.format(987654)}", name="dpo_b", **({"json": body} if body is not None else {}))
        assert hidden.status_code == gone.status_code == 404 and hidden.json() == gone.json(), tail
    for method, tail, body in (("get", "/decisions/{}", None), ("post", "/decisions/{}/withdraw", {}),
                               ("post", "/decisions/{}/revoke", {"reason": "Because."})):
        name = "owner_b" if tail.endswith("revoke") else "dpo_b"
        hidden = http(method, f"{API}{tail.format(decision['id'])}", name=name, **({"json": body} if body is not None else {}))
        assert hidden.status_code == 404, tail
    assert http("get", f"{API}/decisions", name="dpo_b").json()["requests"] == []


@pytest.mark.parametrize("method, tail", [("post", "/systems/{app}/decisions"), ("post", "/decisions/{id}/decide"),
                                          ("post", "/decisions/{id}/revoke"), ("put", "/decision-conditions/1")])
def test_a_body_that_is_not_a_json_object_is_refused_before_anything_runs(http, method, tail):
    app = _accepted(http)
    decision = _ask(http, app)
    path = f"{API}{tail.format(app=app, id=decision['id'])}"
    assert http(method, path, name="owner_a", content=b"{nope", headers={"content-type": "application/json"}).status_code == 400
    assert http(method, path, name="owner_a", json=["a", "list"]).status_code == 400


# ── The journey ─────────────────────────────────────────────────────────────

def test_a_request_is_made_decided_and_read_back_and_a_change_reopens_it(http):
    app = _accepted(http)
    first = http("post", f"{API}/systems/{app}/decisions", name="employee_a", json={"note": "Ready for the pilot."})
    assert first.status_code == 201 and first.json()["decision"]["status"] == "proposed"
    again = http("post", f"{API}/systems/{app}/decisions", name="employee_a", json={})
    assert again.status_code == 200 and again.json()["decision"]["id"] == first.json()["decision"]["id"]
    row = first.json()["decision"]

    queue = http("get", f"{API}/decisions", name="owner_a").json()
    assert [r["id"] for r in queue["requests"]] == [row["id"]] and queue["can_decide"] is True

    brief = http("get", f"{API}/systems/{app}/decision-brief", name="owner_a").json()
    assert brief["needs_override"] is True and [u["key"] for u in brief["unresolved"]] == ["vendor"]
    assert brief["manifest"]["profile"]["tier"] == "lower" and brief["open_request_id"] == row["id"]

    assert _decide(http, app, row, "approve", rationale="Fine.").status_code == 422, "an unresolved step needs a reason"
    done = _decide(http, app, row, "approve", rationale="Fine.", override_reason="The provider review is booked for next week.")
    assert done.status_code == 200 and done.json()["decision"]["status"] == "approved"
    assert http("post", f"{API}/decisions/{row['id']}/decide", name="owner_a",
                json={"outcome": "reject", "rationale": "No.", "version": 1}).status_code == 409, "already decided"

    state = http("get", f"{API}/systems/{app}/decisions", name="employee_a").json()
    assert state["state"]["state"] == "approved" and state["latest"]["override_reason"].startswith("The provider review")
    signed = http("get", f"{API}/decisions/{row['id']}", name="employee_a").json()["decision"]
    assert signed["manifest"]["application"]["name"] == "Ticket summarizer" and len(signed["manifest_hash"]) == 32

    profile = http("get", f"{API}/systems/{app}", name="dpo_a").json()["profile"]
    changed = http("put", f"{API}/systems/{app}/profile", name="dpo_a",
                   json={"answers": {"data_categories": ["personal"]}, "version": profile["version"]})
    assert changed.status_code == 200
    state = http("get", f"{API}/systems/{app}/decisions", name="employee_a").json()
    assert state["state"]["state"] == "needs_re_review" and state["latest"]["id"] == row["id"] and state["can"]["request"] is True
    assert [r["application_id"] for r in http("get", f"{API}/decisions", name="owner_a").json()["re_reviews"]] == [app]


def test_a_decision_over_a_brief_that_has_moved_is_refused_with_a_reason_to_reload(http):
    app = _accepted(http)
    _resolve(http, app)
    row = _ask(http, app)
    shown = http("get", f"{API}/systems/{app}/decision-brief", name="owner_a").json()["hash"]
    profile = http("get", f"{API}/systems/{app}", name="dpo_a").json()["profile"]
    http("put", f"{API}/systems/{app}/profile", name="dpo_a", json={"answers": {"purpose": "Something different"}, "version": profile["version"]})
    late = http("post", f"{API}/decisions/{row['id']}/decide", name="owner_a",
                json={"outcome": "approve", "brief_hash": shown, "version": row["version"]})
    assert late.status_code == 409 and late.json()["brief_changed"] is True and "Reload" in late.json()["error"]


def test_separation_stops_the_asker_and_the_owner_from_deciding_their_own_request(http):
    app = _accepted(http)
    _resolve(http, app)
    row = _ask(http, app, "dpo_a")
    state = http("get", f"{API}/systems/{app}/decisions", name="dpo_a").json()
    assert state["can"]["decide"] is False and "Someone other" in state["can"]["decide_blocked"]
    refused = _decide(http, app, row, "approve", name="dpo_a")
    assert refused.status_code == 403
    assert _decide(http, app, row, "approve", name="owner_a").status_code == 200


def test_conditions_are_tracked_apart_from_the_signed_decision(http):
    app = _accepted(http)
    _resolve(http, app)
    row = _ask(http, app)
    done = _decide(http, app, row, "approve_with_conditions", rationale="Pilot.", conditions=["Review monthly"])
    assert done.status_code == 200
    cid = done.json()["decision"]["conditions"][0]["id"]
    assert http("put", f"{API}/decision-conditions/{cid}", name="employee_a", json={"met": True, "note": "Held on the 3rd."}).status_code == 200
    latest = http("get", f"{API}/systems/{app}/decisions", name="employee_a").json()["latest"]
    assert latest["conditions"][0]["status"] == "met" and latest["status"] == "approved_with_conditions"
    assert http("put", f"{API}/decision-conditions/{cid}", name="employee_a", json={"met": "yes"}).status_code == 422
    assert http("put", f"{API}/decision-conditions/987654", name="employee_a", json={"met": True}).status_code == 404
    assert http("put", f"{API}/decision-conditions/{cid}", name="dpo_b", json={"met": False}).status_code == 404


def test_a_request_is_withdrawn_and_an_approval_revoked_through_the_api(http):
    app = _accepted(http)
    _resolve(http, app)
    row = _ask(http, app)
    assert http("post", f"{API}/decisions/{row['id']}/withdraw", name="employee_a", json={}).status_code == 200
    assert http("post", f"{API}/decisions/{row['id']}/withdraw", name="employee_a", json={}).status_code == 409
    second = _ask(http, app)
    assert _decide(http, app, second, "approve", rationale="Approved.").status_code == 200
    assert http("post", f"{API}/decisions/{second['id']}/revoke", name="owner_a", json={"reason": " "}).status_code == 422
    assert http("post", f"{API}/decisions/{second['id']}/revoke", name="owner_a", json={"reason": "The provider changed its terms."}).status_code == 200
    assert http("get", f"{API}/systems/{app}/decisions", name="owner_a").json()["state"]["state"] == "revoked"


def test_an_answer_names_what_is_missing_in_a_sentence_the_page_can_show(http):
    app = _accepted(http)
    _resolve(http, app)
    row = _ask(http, app)
    for outcome, extra in (("return", {}), ("reject", {"rationale": " "}), ("approve_with_conditions", {}), ("magic", {})):
        response = _decide(http, app, row, outcome, **extra)
        assert response.status_code == 422 and response.json()["ok"] is False and response.json()["error"], outcome
    assert http("post", f"{API}/decisions/{row['id']}/decide", name="owner_a", json={"outcome": "approve", "brief_hash": "x"}).status_code == 400


def test_the_decisions_page_opens_for_everyone_who_may_see_ai_systems(http):
    for name in ("employee_a", "owner_a", "dpo_a"):
        assert http("get", "/ai-governance/decisions", name=name).status_code == 200, name


def test_a_decision_can_be_downloaded_with_names_looked_up_for_the_person_asking(http):
    app = _accepted(http)
    _resolve(http, app)
    aiia = _insert(http.world.db, "sentinel_aiia", ref_number="AIIA-X1", title="Secret impact assessment",
                   business_unit_id=http.world.unit["A"], application_id=app, status="completed")
    http.world.db.commit()
    row = _ask(http, app)
    assert _decide(http, app, row, "approve", rationale="Approved.").status_code == 200
    mine = http("get", f"{API}/decisions/{row['id']}/export", name="owner_a")
    assert mine.status_code == 200 and mine.headers["content-disposition"] == f'attachment; filename="ai-decision-{row["id"]}.json"'
    assert mine.headers["cache-control"] == "no-store" and "Secret impact assessment" in mine.text
    assert mine.json()["decision"]["manifest"]["assessments"][0]["id"] == aiia
    staff = http("get", f"{API}/decisions/{row['id']}/export", name="employee_a")
    assert staff.status_code == 200 and "Secret impact assessment" not in staff.text
    assert http("get", f"{API}/decisions/{row['id']}/export", name="dpo_b").status_code == 404
    assert http("get", f"{API}/decisions/{row['id']}/export", name=None).status_code == 303
