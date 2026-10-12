"""
AI governance G5 through HTTP: monitoring, evaluation records, regulatory changes and explanations.

Written by hand: a person not signed in is sent to log in, a person without the capability gets 403, a system the caller
may not open answers exactly like one that does not exist, a body that is not a JSON object is refused before anything
runs, and what a model is asked contains only what the viewer may see.
"""
import pytest

from core import ai_client
from tests.test_ai_governance_evaluations import RUN
from tests.test_ai_governance_routes import _accepted, http  # noqa: F401
from tests.test_platform_ownership import _insert, world  # noqa: F401

API = "/ai-governance/api"


def _record(http, app, actor="dpo_a", **changes):
    response = http("post", f"{API}/systems/{app}/evaluations", name=actor, json={**RUN, **changes})
    assert response.status_code == 201, response.text
    return response.json()["run"]


def _profile_with(http, app, jurisdictions):
    version = http("get", f"{API}/systems/{app}", name="dpo_a").json()["profile"]["version"]
    response = http("put", f"{API}/systems/{app}/profile", name="dpo_a", json={"answers": {"jurisdictions": jurisdictions}, "version": version})
    assert response.status_code == 200, response.text


# ── Who may call what ───────────────────────────────────────────────────────

READS = ("/systems/1/monitoring", "/systems/1/evaluations", "/systems/1/explain", "/regulatory", "/evaluations/compare?older=1&newer=2")
WRITES = (("post", "/systems/1/evaluations"), ("post", "/evaluations/1/review"), ("post", "/regulatory/refresh"),
          ("post", "/regulatory/1/review"))


def test_nobody_signed_out_reaches_any_of_it(http):
    for tail in READS:
        assert http("get", f"{API}{tail}", name=None).status_code == 303, tail
    assert http("get", "/ai-governance/regulatory", name=None).status_code == 303
    for method, tail in WRITES:
        assert http(method, f"{API}{tail}", name=None, json={}).status_code == 303, tail


def test_an_outside_auditor_is_refused_everywhere(http):
    for tail in READS:
        assert http("get", f"{API}{tail}", name="auditor").status_code == 403, tail
    for method, tail in WRITES:
        assert http(method, f"{API}{tail}", name="auditor", json={}).status_code == 403, tail


def test_staff_read_what_they_may_open_and_record_and_review_nothing(http):
    app = _accepted(http)
    for tail in (f"/systems/{app}/monitoring", f"/systems/{app}/evaluations", f"/systems/{app}/explain", "/regulatory"):
        assert http("get", f"{API}{tail}", name="employee_a").status_code == 200, tail
    for method, tail in WRITES:
        assert http(method, f"{API}{tail}", name="employee_a", json={}).status_code == 403, tail
    assert http("get", "/ai-governance/regulatory", name="employee_a").status_code == 200


def test_a_system_in_another_unit_answers_like_one_that_is_not_there(http):
    app = _accepted(http)
    for tail in ("monitoring", "evaluations", "explain"):
        hidden = http("get", f"{API}/systems/{app}/{tail}", name="dpo_b")
        gone = http("get", f"{API}/systems/987654/{tail}", name="dpo_b")
        assert hidden.status_code == gone.status_code == 404 and hidden.json() == gone.json(), tail
    assert http("post", f"{API}/systems/{app}/evaluations", name="dpo_b", json=RUN).status_code == 404


@pytest.mark.parametrize("method, tail", [("post", "/systems/{app}/evaluations"), ("post", "/evaluations/1/review"),
                                          ("post", "/regulatory/1/review")])
def test_a_body_that_is_not_a_json_object_is_refused_before_anything_runs(http, method, tail):
    app = _accepted(http)
    path = f"{API}{tail.format(app=app)}"
    assert http(method, path, name="dpo_a", content=b"{nope", headers={"content-type": "application/json"}).status_code == 400
    assert http(method, path, name="dpo_a", json=["a", "list"]).status_code == 400


# ── Evaluation records ──────────────────────────────────────────────────────

def test_a_run_is_recorded_listed_compared_and_reviewed(http):
    app = _accepted(http)
    first = _record(http, app, name="First", scores={"citation_validity": 90, "no_match": 100},
                    started_at="2026-09-20", finished_at="2026-09-20 09:00:00")
    second = _record(http, app, name="Second", scores={"citation_validity": 97, "no_match": 100})
    assert first["state"] == "failed" and second["state"] == "passed"
    got = http("get", f"{API}/systems/{app}/evaluations", name="employee_a").json()
    assert [r["name"] for r in got["runs"]] == ["Second", "First"] and got["comparison"]["same_test_set"] is True
    both = http("get", f"{API}/evaluations/compare?older={first['id']}&newer={second['id']}", name="dpo_a").json()
    assert both["older"]["name"] == "First" and both["comparison"]["dimensions"][0]["change"] == 7.0
    assert http("get", f"{API}/evaluations/compare?older=x&newer=2", name="dpo_a").status_code == 400
    bad = http("post", f"{API}/evaluations/{first['id']}/review", name="dpo_a", json={"outcome": "accepted", "version": 1})
    assert bad.status_code == 409, "a failed run is not accepted as evidence"
    good = http("post", f"{API}/evaluations/{second['id']}/review", name="dpo_a", json={"outcome": "accepted", "version": 1})
    assert good.status_code == 200 and good.json()["run"]["review_outcome"] == "accepted"
    monitor = http("get", f"{API}/systems/{app}/monitoring", name="dpo_a").json()
    assert "evaluations" not in monitor["attention"], "the latest run passed and nothing has changed since"


def test_a_bad_run_comes_back_as_field_errors(http):
    app = _accepted(http)
    response = http("post", f"{API}/systems/{app}/evaluations", name="dpo_a", json={**RUN, "scores": {"a": 500}, "status": "done"})
    assert response.status_code == 422 and set(response.json()["errors"]) == {"scores", "status", "thresholds"}


def test_a_failed_run_shows_on_the_monitoring_tab_and_in_the_quality_checks(http):
    app = _accepted(http)
    _record(http, app, scores={"citation_validity": 50})
    monitor = http("get", f"{API}/systems/{app}/monitoring", name="dpo_a").json()
    assert "evaluations" in monitor["attention"]
    findings = http("get", f"{API}/systems/{app}/quality", name="dpo_a").json()["findings"]
    assert any(f["rule"] == "evaluation_failed" for f in findings)
    tab = http("get", f"{API}/systems/{app}/tabs/monitoring", name="dpo_a").json()
    assert tab["state"] == "ok" and any(s["title"] == "Evaluations" and s["items"] for s in tab["sections"])


# ── Regulatory changes ──────────────────────────────────────────────────────

def test_a_change_is_proposed_for_a_use_in_its_jurisdiction_and_confirmed_into_a_task(http):
    app = _accepted(http)
    _profile_with(http, app, ["EU"])
    _insert(http.world.db, "regulatory_updates", framework_name="EU AI Act", title="Guidance on prohibited practices",
            summary="Clarifies Article 5.", effective_date="2026-12-01", severity="high", status="open")
    _insert(http.world.db, "regulatory_updates", framework_name="POPIA", title="South African change", status="open")
    http.world.db.commit()
    refreshed = http("post", f"{API}/regulatory/refresh", name="dpo_a", json={})
    assert refreshed.status_code == 200 and refreshed.json()["created"] == 1
    queue = http("get", f"{API}/regulatory", name="dpo_a").json()
    assert [i["title"] for i in queue["items"]] == ["Guidance on prohibited practices"] and queue["can_review"] is True
    item = queue["items"][0]
    assert http("post", f"{API}/regulatory/{item['id']}/review", name="dpo_a", json={"decision": "dismiss", "reason": " ", "version": 1}).status_code == 422
    done = http("post", f"{API}/regulatory/{item['id']}/review", name="dpo_a", json={"decision": "confirm", "reason": "EU customers.", "version": 1})
    assert done.status_code == 200 and done.json()["item"]["status"] == "confirmed"
    assert http("post", f"{API}/regulatory/{item['id']}/review", name="dpo_a", json={"decision": "dismiss", "reason": "No.", "version": 2}).status_code == 409
    assert http("get", f"{API}/regulatory?status=confirmed", name="dpo_b").json()["items"] == []
    assert http("get", f"{API}/regulatory?status=pending", name="dpo_a").status_code == 400
    assert http("post", f"{API}/regulatory/{item['id']}/review", name="dpo_b", json={"decision": "dismiss", "reason": "No.", "version": 1}).status_code == 404


# ── Explain ─────────────────────────────────────────────────────────────────

def test_the_explanation_is_built_from_the_rules_and_a_model_only_rephrases_with_citations(http, monkeypatch):
    app = _accepted(http)
    rules = http("get", f"{API}/systems/{app}/explain", name="employee_a").json()
    assert rules["mode"] == "rules" and rules["sentences"] and rules["facts"][0]["id"] == "F1"

    seen = {}
    monkeypatch.setattr(ai_client, "is_configured", lambda: True)

    def fake(messages, system="", max_tokens=0, model="", *, feature="", sources=None):
        seen["feature"], seen["sources"] = feature, sources
        return "The use is at a lower tier [F1]. It is perfectly legal [F40]."

    monkeypatch.setattr(ai_client, "create_message", fake)
    ai = http("get", f"{API}/systems/{app}/explain?ai=1", name="employee_a").json()
    assert ai["mode"] == "ai" and [s["cites"] for s in ai["sentences"]] == [["F1"]] and ai["dropped"] == 1
    assert seen["feature"] == "governance.explain_ai_use" and seen["sources"] == [f"governance/application/{app}"]


def test_the_pages_open_for_those_who_may_see_ai_systems(http):
    for name in ("employee_a", "dpo_a", "owner_a"):
        assert http("get", "/ai-governance/regulatory", name=name).status_code == 200, name
