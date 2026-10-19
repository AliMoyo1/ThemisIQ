"""
AI governance G3b through HTTP: the AI impact assessment pages and API, and the redirects from where it used to live.

Written by hand: a person not signed in is sent to log in, a person without the capability gets 403, an assessment in
another unit answers exactly like one that does not exist, a body that is not a JSON object is refused before anything
runs, and the old Sentinel addresses lead to the new ones.
"""
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.middleware as middleware
from modules.ai_governance import service, workspace
from modules.sentinel.routes import router as sentinel_router
from tests.test_ai_governance_routes import _accepted, http  # noqa: F401
from tests.test_platform_ownership import _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401

API = "/ai-governance/api"


def _make(http, name="dpo_a", **fields):
    response = http("post", f"{API}/assessments", name=name, json={"title": "Churn model", **fields})
    assert response.status_code == 201, response.text
    return response.json()["assessment"]


# ── Who may call what ───────────────────────────────────────────────────────

PAGES = ("/ai-governance/assessments", "/ai-governance/assessments/new", "/ai-governance/assessments/1")
READS = (f"{API}/assessments", f"{API}/assessments/1", f"{API}/assessment-dimensions", f"{API}/assessments/link-options?kind=ropa")
WRITES = (("post", f"{API}/assessments", {"title": "x"}), ("put", f"{API}/assessments/1", {"title": "x", "version": 1}),
          ("delete", f"{API}/assessments/1", None), ("put", f"{API}/assessment-dimensions", {"dimensions": []}))


def _call(http, method, path, name, body=None):
    return http(method, path, name=name, **({"json": body} if body is not None else {}))


def test_nobody_signed_out_reaches_any_page_or_call(http):
    for path in PAGES + READS:
        assert http("get", path, name=None).status_code == 303, path
    for method, path, body in WRITES:
        assert _call(http, method, path, None, body).status_code == 303, path


@pytest.mark.parametrize("name", ["auditor", "employee_a"])
def test_staff_and_outside_auditors_are_refused_everywhere(http, name):
    for path in PAGES + READS:
        assert http("get", path, name=name).status_code == 403, path
    for method, path, body in WRITES:
        assert _call(http, method, path, name, body).status_code == 403, path


def test_a_risk_owner_reads_and_writes_assessments_but_does_not_configure_dimensions(http):
    row = _make(http, "owner_a", title="Owner's")
    assert http("get", f"{API}/assessments/{row['id']}", name="owner_a").status_code == 200
    assert http("get", f"{API}/assessment-dimensions", name="owner_a").status_code == 200
    assert http("put", f"{API}/assessment-dimensions", name="owner_a", json={"dimensions": [{"name": "Safety"}]}).status_code == 403
    assert http("put", f"{API}/assessment-dimensions", name="dpo_a", json={"dimensions": [{"name": "Safety"}]}).status_code == 200


def test_the_pages_open_for_those_who_may_and_an_assessment_in_another_unit_is_a_404(http):
    mine = _make(http, "dpo_a")
    theirs = _make(http, "dpo_b", title="Theirs")
    assert http("get", "/ai-governance/assessments", name="dpo_a").status_code == 200
    assert http("get", "/ai-governance/assessments/new", name="owner_a").status_code == 200
    assert http("get", f"/ai-governance/assessments/{mine['id']}", name="owner_a").status_code == 200
    assert http("get", f"/ai-governance/assessments/{theirs['id']}", name="dpo_a").status_code == 404
    assert http("get", "/ai-governance/assessments/987654", name="dpo_a").status_code == 404


def test_the_new_form_gets_a_system_only_when_it_is_a_plain_number(http):
    page = http("get", "/ai-governance/assessments/new?application_id=12", name="dpo_a").text
    assert "applicationId: 12" in page
    for bad in ("abc", "12x", "1234567890", "-3"):
        assert "applicationId: 0" in http("get", f"/ai-governance/assessments/new?application_id={bad}", name="dpo_a").text, bad


# ── The journey ─────────────────────────────────────────────────────────────

def test_an_assessment_is_created_listed_changed_and_deleted_through_the_api(http):
    row = _make(http, ai_system_name="ChurnGuard", impacts=[{"dimension_name": "Financial", "applicable": 1, "likelihood": 4, "impact": 4}])
    assert row["status"] == "draft" and row["version"] == 1 and row["overall_classification"]
    assert row["can"] == {"manage": True, "configure": True}

    listed = http("get", f"{API}/assessments?q=churn", name="dpo_a").json()
    assert [i["id"] for i in listed["items"]] == [row["id"]] and listed["total"] == 1 and listed["can"]["manage"] is True
    assert listed["items"][0]["url"] == f"/ai-governance/assessments/{row['id']}"

    shown = http("get", f"{API}/assessments/{row['id']}", name="dpo_a").json()["assessment"]
    assert shown["title"] == "Churn model" and shown["ai_system_name"] == "ChurnGuard"

    changed = http("put", f"{API}/assessments/{row['id']}", name="dpo_a", json={"title": "Churn model v2", "status": "in_progress", "version": 1})
    assert changed.status_code == 200 and changed.json()["assessment"]["version"] == 2
    stale = http("put", f"{API}/assessments/{row['id']}", name="dpo_a", json={"title": "Lost", "version": 1})
    assert stale.status_code == 409 and stale.json()["current_version"] == 2
    assert http("put", f"{API}/assessments/{row['id']}", name="dpo_a", json={"title": "No version"}).status_code == 400

    assert http("delete", f"{API}/assessments/{row['id']}", name="dpo_a").status_code == 200
    assert http("get", f"{API}/assessments/{row['id']}", name="dpo_a").status_code == 404
    assert http("get", f"{API}/assessments", name="dpo_a").json()["total"] == 0


def test_an_assessment_in_another_unit_answers_like_one_that_is_not_there(http):
    theirs = _make(http, "dpo_b", title="Theirs")
    for method, body, message in (("get", None, "Not found."), ("put", {"title": "x", "version": 1}, "Assessment not found."),
                                  ("delete", None, "Assessment not found.")):
        hidden = _call(http, method, f"{API}/assessments/{theirs['id']}", "dpo_a", body)
        gone = _call(http, method, f"{API}/assessments/987654", "dpo_a", body)
        assert (hidden.status_code, hidden.json()) == (gone.status_code, gone.json()) == (404, {"ok": False, "error": message}), method
    assert http("get", f"{API}/assessments/{theirs['id']}", name="dpo_b").status_code == 200


def test_a_bad_answer_comes_back_as_field_errors_and_a_bad_filter_is_a_400(http):
    response = http("post", f"{API}/assessments", name="dpo_a", json={"title": "", "autonomy_level": "magic", "impacts": [
        {"dimension_name": "Financial", "likelihood": 9, "impact": 1}]})
    assert response.status_code == 422 and response.json()["ok"] is False
    assert set(response.json()["errors"]) == {"title", "autonomy_level", "impacts"} and response.json()["error"]
    for query in ("status=gone", "linked=maybe", "page_size=0", "page_size=500"):
        assert http("get", f"{API}/assessments?{query}", name="dpo_a").status_code == 400, query
    assert http("get", f"{API}/assessments?page=abc", name="dpo_a").status_code == 200


@pytest.mark.parametrize("method, path", [("post", f"{API}/assessments"), ("put", f"{API}/assessments/1"),
                                          ("put", f"{API}/assessment-dimensions")])
def test_a_body_that_is_not_a_json_object_is_refused_before_anything_runs(http, method, path):
    assert http(method, path, name="dpo_a", content=b"{nope", headers={"content-type": "application/json"}).status_code == 400
    assert http(method, path, name="dpo_a", json=["a", "list"]).status_code == 400


def test_the_dimensions_can_be_renamed_and_a_collision_says_so(http):
    dims = http("get", f"{API}/assessment-dimensions", name="dpo_a").json()["items"]
    financial = next(d for d in dims if d["name"] == "Financial")
    ok = http("put", f"{API}/assessment-dimensions", name="dpo_a", json={"dimensions": [{**financial, "name": "Financial exposure"}]})
    assert ok.status_code == 200 and "Financial exposure" in [d["name"] for d in ok.json()["dimensions"]]
    clash = http("put", f"{API}/assessment-dimensions", name="dpo_a", json={"dimensions": [{"name": "operational"}]})
    assert clash.status_code == 409


def test_switching_ai_governance_off_hides_the_way_in_and_leaves_the_assessments_and_the_security_rules_alone(http):
    from core import ai_rollout
    row = _make(http, "dpo_a", title="Stays reachable")
    ai_rollout.set_enabled(http.world.users["dpo_a"]["org_id"], False)
    assert http("get", "/ai-governance/assessments", name="dpo_a").status_code == 200
    assert http("get", f"{API}/assessments/{row['id']}", name="dpo_a").status_code == 200
    assert http("get", "/ai-governance/", name="employee_a").status_code == 200, "a switch hides, it does not guard"
    assert http("get", "/ai-governance/assessments", name="employee_a").status_code == 403, "the capability still decides"


# ── Linking to a system and the checklist ───────────────────────────────────

def test_an_assessment_linked_to_a_system_shows_on_its_workspace_and_in_its_checklist(http):
    app = _accepted(http)
    prefill = http("get", f"{API}/systems/{app}/aiia-prefill", name="dpo_a").json()
    row = _make(http, "dpo_a", application_id=app, **{k: v for k, v in prefill["fields"].items()
                                                      if k in ("title", "ai_system_name", "system_description", "autonomy_level")})
    assert row["application"]["id"] == app and row["application"]["url"] == f"/ai-governance/systems/{app}"
    assert row["title"] == "Ticket summarizer: AI impact assessment"

    tab = http("get", f"{API}/systems/{app}/tabs/assessments", name="dpo_a").json()
    item = tab["sections"][0]["items"][0]
    assert item["url"] == f"/ai-governance/assessments/{row['id']}" and item["source"] == "AI Governance"

    plan = http("get", f"{API}/systems/{app}/checklist", name="dpo_a").json()
    aiia = next(s for s in plan["steps"] if s["key"] == "aiia")
    assert aiia["state"] == "in_progress" and aiia["records"][0]["url"] == f"/ai-governance/assessments/{row['id']}"
    assert aiia["action"]["url"].startswith("/ai-governance/assessments/new?application_id=")

    done = http("put", f"{API}/assessments/{row['id']}", name="dpo_a", json={"status": "completed", "version": row["version"]})
    assert done.status_code == 200
    plan = http("get", f"{API}/systems/{app}/checklist", name="dpo_a").json()
    assert next(s for s in plan["steps"] if s["key"] == "aiia")["state"] == "complete"

    filtered = http("get", f"{API}/assessments?application_id={app}", name="dpo_a").json()
    assert [i["id"] for i in filtered["items"]] == [row["id"]]
    assert http("get", f"{API}/assessments?linked=none", name="dpo_a").json()["total"] == 0


def test_the_unlinked_assessments_can_be_found_and_linked_by_a_writer_who_may_open_the_system(http):
    app = _accepted(http)
    row = _make(http, "dpo_a", title="Old assessment")
    unlinked = http("get", f"{API}/assessments?linked=none", name="dpo_a").json()["items"]
    assert [i["id"] for i in unlinked] == [row["id"]] and unlinked[0]["application"] is None
    hidden = _insert(http.world.db, "applications", name="Unit B model", business_unit_id=http.world.unit["B"], is_active=1)
    http.world.db.commit()
    assert http("put", f"{API}/assessments/{row['id']}", name="dpo_a", json={"application_id": hidden, "version": 1}).status_code == 400
    linked = http("put", f"{API}/assessments/{row['id']}", name="dpo_a", json={"application_id": app, "version": 1})
    assert linked.status_code == 200 and linked.json()["assessment"]["application_id"] == app
    assert http("get", f"{API}/assessments?linked=none", name="dpo_a").json()["total"] == 0


# ── Where it used to live ───────────────────────────────────────────────────

@pytest.fixture
def sentinel(world, monkeypatch):
    async def current_user(request):
        return world.users["dpo_a"]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(sentinel_router)
    return TestClient(app, base_url="http://testserver", raise_server_exceptions=False, follow_redirects=False)


def test_the_old_sentinel_page_and_deep_links_lead_to_the_new_pages(sentinel):
    page = sentinel.get("/sentinel/aiia")
    assert page.status_code == 302 and page.headers["location"] == "/ai-governance/assessments"
    deep = sentinel.get("/sentinel/?open=aiia:12")
    assert deep.status_code == 302 and deep.headers["location"] == "/ai-governance/assessments/12"
    for odd in ("aiia:abc", "aiia:", "aiia:1234567890", "ropa:12"):
        assert sentinel.get(f"/sentinel/?open={odd}").status_code != 302, odd


def test_the_old_sentinel_api_is_gone(sentinel):
    for method, path in (("get", "/sentinel/api/aiias"), ("post", "/sentinel/api/aiias"), ("get", "/sentinel/api/aiias/1"),
                         ("put", "/sentinel/api/aiias/1"), ("delete", "/sentinel/api/aiias/1"),
                         ("get", "/sentinel/api/aiia-dimensions"), ("put", "/sentinel/api/aiia-dimensions")):
        assert getattr(sentinel, method)(path).status_code in (404, 405), path


def test_the_sentinel_page_no_longer_carries_the_assessment_screen(sentinel):
    text = sentinel.get("/sentinel/").text
    assert "view-aiia" not in text and "snOpenAiiaDrawer" not in text and "/sentinel/api/aiia" not in text
    assert 'href="/ai-governance/assessments"' in text, "the Privacy navigation still points the way"
