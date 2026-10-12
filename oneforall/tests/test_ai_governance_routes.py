"""
AI governance G2 through HTTP: who may call what, the shape of every answer, and the whole journey from a staff
member's draft to an accepted AI use that the author can then open.

Written by hand: a person without the capability gets 403, someone not signed in is sent to log in, a record the
caller may not open is a 404 that looks the same as one that does not exist, and a step that cannot be done says why in
a sentence the page can show.
"""
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.middleware as middleware
from core import rbac
from modules.ai_governance.routes import router as ai_router
from modules.launcher.routes import router as launcher_router
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401

GOOD = {"name": "Ticket summarizer", "purpose": "Summarize support tickets", "deployment": "vendor_service",
        "provider_name": "Acme AI", "data_categories": ["internal"], "intended_users": "Support agents"}
FULL = {**GOOD, "affected_people": ["none"], "autonomy": "assist_only", "affects_decisions": False, "external_access": False}


@pytest.fixture
def http(world, monkeypatch):
    people = dict(world.users)
    people["auditor"] = {**world.users["employee_a"], "roles": [rbac.EXTERNAL_AUDITOR]}
    who = {"name": "employee_a"}

    async def current_user(request):
        return people[who["name"]] if who["name"] else None

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(ai_router)
    app.include_router(launcher_router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False, follow_redirects=False)

    def call(method, path, name="employee_a", **kwargs):
        who["name"] = name
        return getattr(client, method)(path, **kwargs)

    call.world = world
    return call


def _draft(http, name="employee_a", answers=None, key=None):
    body = {"answers": {**GOOD, **(answers or {})}}
    if key:
        body["idempotency_key"] = key
    response = http("post", "/ai-governance/api/requests", name=name, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()["intake"]


def _submit(http, name="employee_a", answers=None):
    row = _draft(http, name, answers)
    response = http("post", f"/ai-governance/api/requests/{row['id']}/submit", name=name, json={"version": row["version"]})
    assert response.status_code == 200, response.text
    return response.json()["intake"]


# ── The whole journey ───────────────────────────────────────────────────────

def test_a_staff_member_describes_a_use_a_reviewer_accepts_it_and_the_author_opens_the_system(http):
    first = http("post", "/ai-governance/api/requests", json={"answers": GOOD, "idempotency_key": "form-1"})
    assert first.status_code == 201 and first.json()["intake"]["status"] == "draft"
    row = first.json()["intake"]
    again = http("post", "/ai-governance/api/requests", json={"answers": GOOD, "idempotency_key": "form-1"})
    assert again.status_code == 200 and again.json()["intake"]["id"] == row["id"] and again.json()["created"] is False

    saved = http("put", f"/ai-governance/api/requests/{row['id']}", json={"answers": {"autonomy": "assist_only", "affected_people": ["none"],
                                                                                      "affects_decisions": False, "external_access": False}, "version": row["version"]})
    assert saved.status_code == 200 and saved.json()["intake"]["version"] == 2
    sent = http("post", f"/ai-governance/api/requests/{row['id']}/submit", json={"version": 2})
    assert sent.status_code == 200 and sent.json()["intake"]["status"] == "submitted"
    assert [r["status"] for r in http("get", "/ai-governance/api/requests").json()["items"]] == ["submitted"]

    queue = http("get", "/ai-governance/api/review/queue", name="dpo_a").json()["items"]
    assert [r["id"] for r in queue] == [row["id"]] and queue[0]["author_name"] == "employee_a"
    detail = http("get", f"/ai-governance/api/requests/{row['id']}", name="dpo_a").json()["intake"]
    assert detail["screening"]["tier"] == "lower" and detail["owner_name"] == "employee_a"

    approved = http("post", f"/ai-governance/api/review/requests/{row['id']}/approve", name="dpo_a",
                    json={"version": 3, "new_application": {"vendor_name": "Acme AI"}})
    assert approved.status_code == 200 and approved.json()["created_application"] is True
    app_id = approved.json()["application_id"]
    again = http("post", f"/ai-governance/api/review/requests/{row['id']}/approve", name="dpo_a", json={"version": 3, "new_application": {}})
    assert again.status_code == 200 and again.json()["application_id"] == app_id and again.json()["created_application"] is False

    listed = http("get", "/ai-governance/api/systems").json()
    assert [i["name"] for i in listed["items"]] == ["Ticket summarizer"] and listed["items"][0]["tier"] == "lower"
    system = http("get", f"/ai-governance/api/systems/{app_id}").json()
    assert system["application"]["owner"] == "employee_a" and system["profile"]["purpose"] == "Summarize support tickets"
    assert http("get", f"/ai-governance/systems/{app_id}").status_code == 200
    mine = http("get", "/ai-governance/api/requests").json()["items"][0]
    assert (mine["status"], mine["application_id"]) == ("approved", app_id)


# ── Who may call what ───────────────────────────────────────────────────────

SUBMIT_ONLY = ("GET", "/ai-governance/api/requests"), ("GET", "/ai-governance/api/people"), ("GET", "/ai-governance/api/business-units"), \
              ("GET", "/ai-governance/register"), ("GET", "/ai-governance/requests")
REVIEW_ONLY = ("GET", "/ai-governance/api/review/queue"), ("GET", "/ai-governance/review"), ("GET", "/ai-governance/api/applications/search?q=ab")
VIEW = ("GET", "/ai-governance/api/systems"), ("GET", "/ai-governance/api/systems/choices"), ("GET", "/ai-governance/"), \
       ("GET", "/ai-governance/api/vocabulary"), ("GET", "/ai-governance/api/link-kinds")


@pytest.mark.parametrize("method, path", SUBMIT_ONLY + REVIEW_ONLY + VIEW)
def test_nobody_signed_out_reaches_any_page_or_api(http, method, path):
    response = http(method.lower(), path, name=None)
    assert response.status_code == 303 and response.headers["location"].endswith("/login")


@pytest.mark.parametrize("method, path", SUBMIT_ONLY + REVIEW_ONLY + VIEW)
def test_an_outside_auditor_with_no_ai_capability_is_refused_everywhere(http, method, path):
    assert http(method.lower(), path, name="auditor").status_code == 403


@pytest.mark.parametrize("method, path", REVIEW_ONLY)
def test_ordinary_staff_cannot_use_the_reviewers_pages_and_calls(http, method, path):
    assert http(method.lower(), path, name="employee_a").status_code == 403


@pytest.mark.parametrize("method, path", SUBMIT_ONLY + VIEW + REVIEW_ONLY)
def test_a_reviewer_reaches_all_of_them(http, method, path):
    assert http(method.lower(), path, name="dpo_a").status_code == 200


def test_every_change_a_reviewer_makes_is_closed_to_staff(http):
    row = _submit(http)
    for action, body in (("return", {"note": "x", "version": 3}), ("reject", {"reason": "x", "version": 3}),
                         ("approve", {"version": 3, "new_application": {}})):
        assert http("post", f"/ai-governance/api/review/requests/{row['id']}/{action}", json=body).status_code == 403
    assert http("get", f"/ai-governance/api/review/requests/{row['id']}/duplicates").status_code == 403
    assert http("get", f"/ai-governance/api/requests/{row['id']}").status_code == 200, "its own author may read it"


def test_staff_cannot_change_a_profile_a_tier_or_the_life_of_a_use(http):
    app = _accepted(http)
    for method, suffix, body in (("post", "profile", {"answers": {}}), ("put", "profile", {"answers": {}, "version": 1}),
                                 ("post", "tier", {"tier": "lower", "reason": "x", "version": 1}), ("post", "reviewed", {}),
                                 ("post", "retire", {"reason": "x"}), ("post", "restore", {})):
        assert http(method, f"/ai-governance/api/systems/{app}/{suffix}", json=body).status_code == 403, suffix


def _accepted(http, name="employee_a"):
    row = _submit(http, name, FULL)
    done = http("post", f"/ai-governance/api/review/requests/{row['id']}/approve", name="dpo_a", json={"version": row["version"], "new_application": {}})
    assert done.status_code == 200, done.text
    return done.json()["application_id"]


# ── What a person may not see does not exist ────────────────────────────────

def test_a_request_and_a_use_in_another_unit_answer_exactly_like_one_that_is_not_there(http):
    row = _submit(http)
    app = _accepted(http)
    missing_request = http("get", "/ai-governance/api/requests/987654", name="dpo_b")
    hidden_request = http("get", f"/ai-governance/api/requests/{row['id']}", name="dpo_b")
    assert (hidden_request.status_code, hidden_request.json()) == (missing_request.status_code, missing_request.json()) == (404, {"ok": False, "error": "Request not found."})
    missing_system = http("get", "/ai-governance/api/systems/987654", name="dpo_b")
    hidden_system = http("get", f"/ai-governance/api/systems/{app}", name="dpo_b")
    assert (hidden_system.status_code, hidden_system.json()) == (missing_system.status_code, missing_system.json()) == (404, {"ok": False, "error": "Not found."})
    assert http("get", f"/ai-governance/systems/{app}", name="dpo_b").status_code == 404
    assert http("get", f"/ai-governance/api/systems/{app}/tabs/assessments", name="dpo_b").status_code == 404
    assert http("get", f"/ai-governance/api/systems/{app}/tabs/assessments", name="dpo_a").status_code == 200
    assert http("get", "/ai-governance/api/systems", name="dpo_b").json()["total"] == 0


def test_a_hidden_use_cannot_be_changed_either(http):
    app = _accepted(http)
    version = http("get", f"/ai-governance/api/systems/{app}").json()["profile"]["version"]
    for method, suffix, body in (("put", "profile", {"answers": {"purpose": "x"}, "version": version}), ("post", "reviewed", {}),
                                 ("post", "retire", {"reason": "because"}), ("post", "tier", {"tier": "lower", "reason": "because", "version": version})):
        assert http(method, f"/ai-governance/api/systems/{app}/{suffix}", name="dpo_b", json=body).status_code == 404, suffix


def test_a_title_is_shown_as_text_never_as_markup(http):
    world = http.world
    app = _insert(world.db, "applications", name="<script>alert(1)</script>", business_unit_id=world.unit["A"], is_active=1)
    world.db.commit()
    page = http("get", f"/ai-governance/systems/{app}")
    assert page.status_code == 200 and "<script>alert(1)</script>" not in page.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


# ── Answers and errors the page can show ────────────────────────────────────

def test_a_bad_answer_comes_back_as_field_errors(http):
    response = http("post", "/ai-governance/api/requests", json={"answers": {"deployment": "magic", "purpose": "x" * 2001}})
    assert response.status_code == 422 and response.json()["ok"] is False
    assert set(response.json()["errors"]) == {"deployment", "purpose"} and response.json()["error"]


def test_a_stale_save_says_which_version_is_current(http):
    row = _draft(http)
    http("put", f"/ai-governance/api/requests/{row['id']}", json={"answers": {"purpose": "One"}, "version": 1})
    stale = http("put", f"/ai-governance/api/requests/{row['id']}", json={"answers": {"purpose": "Two"}, "version": 1})
    assert stale.status_code == 409 and stale.json()["current_version"] == 2


def test_submitting_an_unfinished_draft_lists_what_is_missing(http):
    row = _draft(http, answers={"purpose": None})
    response = http("post", f"/ai-governance/api/requests/{row['id']}/submit", json={"version": 1})
    assert response.status_code == 422 and response.json()["missing"] == ["purpose"]


@pytest.mark.parametrize("path, method", [("/ai-governance/api/requests", "post"), ("/ai-governance/api/requests/1", "put"),
                                          ("/ai-governance/api/requests/1/submit", "post"),
                                          ("/ai-governance/api/review/requests/1/return", "post"),
                                          ("/ai-governance/api/review/requests/1/approve", "post")])
def test_a_body_that_is_not_json_or_not_an_object_is_refused_before_anything_runs(http, path, method):
    name = "dpo_a" if "review" in path else "employee_a"
    assert http(method, path, name=name, content=b"{nope", headers={"content-type": "application/json"}).status_code == 400
    assert http(method, path, name=name, json=["a", "list"]).status_code == 400


def test_a_review_without_the_version_is_refused(http):
    row = _submit(http)
    assert http("post", f"/ai-governance/api/review/requests/{row['id']}/return", name="dpo_a", json={"note": "Please add detail."}).status_code == 400
    assert http("post", f"/ai-governance/api/review/requests/{row['id']}/reject", name="dpo_a", json={"reason": "Out of scope.", "version": "3"}).status_code == 400
    assert http("get", f"/ai-governance/api/requests/{row['id']}", name="dpo_a").json()["intake"]["status"] == "submitted", "nothing changed"


def test_the_inventory_rejects_unknown_filters(http):
    for query in ("state=gone", "tier=high", "page_size=0", "page_size=500", "sort=owner", "use_type=magic"):
        assert http("get", f"/ai-governance/api/systems?{query}").status_code == 400, query
    assert http("get", "/ai-governance/api/systems?page=abc&owner=zz").status_code == 200


# ── Pickers ─────────────────────────────────────────────────────────────────

def test_the_people_picker_gives_names_only_found_by_typing(http):
    response = http("get", "/ai-governance/api/people?q=emp").json()
    assert response["items"] == [{"id": http.world.users["employee_a"]["id"], "name": "employee_a"}]
    assert "email" not in str(response) and "@" not in str(response)
    assert http("get", "/ai-governance/api/people?q=zzzz").json()["items"] == []
    assert http("get", "/ai-governance/api/people?q=%25").json()["items"] == [], "a wildcard is just a character"


def test_the_unit_picker_offers_the_persons_own_units_only(http):
    world = http.world
    mine = {u["name"] for u in http("get", "/ai-governance/api/business-units", name="employee_a").json()["items"]}
    assert {"Unit A", "Unit A1"} <= mine and "Unit B" not in mine
    assert http("get", "/ai-governance/api/business-units", name="employee_a").json()["default"] == world.unit["A"]


def test_the_vocabulary_names_every_choice_and_the_required_questions(http):
    vocab = http("get", "/ai-governance/api/vocabulary").json()
    assert vocab["required"] == ["name", "purpose", "deployment", "owner_user_id", "data_categories", "intended_users"]
    assert set(vocab["deployment"]) == {"internal_build", "vendor_service", "embedded_vendor", "open_model_hosted"}
    assert vocab["tiers"]["needs_review"] == "Needs review" and vocab["labels"]["owner_user_id"] == "owner"


# ── Profile, tier, retirement ───────────────────────────────────────────────

def test_a_reviewer_runs_the_life_of_a_use_through_the_api(http):
    app = _accepted(http)
    profile = http("get", f"/ai-governance/api/systems/{app}", name="dpo_a").json()["profile"]
    edited = http("put", f"/ai-governance/api/systems/{app}/profile", name="dpo_a",
                  json={"answers": {"data_categories": ["personal"]}, "version": profile["version"]})
    assert edited.status_code == 200 and edited.json()["profile"]["tier"] == "moderate"
    stale = http("put", f"/ai-governance/api/systems/{app}/profile", name="dpo_a", json={"answers": {"purpose": "x"}, "version": profile["version"]})
    assert stale.status_code == 409
    version = edited.json()["profile"]["version"]
    assert http("post", f"/ai-governance/api/systems/{app}/tier", name="dpo_a", json={"tier": "elevated", "reason": "", "version": version}).status_code == 422
    adopted = http("post", f"/ai-governance/api/systems/{app}/tier", name="dpo_a", json={"tier": "elevated", "reason": "Customer facing.", "version": version})
    assert adopted.status_code == 200 and adopted.json()["profile"]["tier"] == "elevated"
    assert http("post", f"/ai-governance/api/systems/{app}/reviewed", name="dpo_a", json={}).status_code == 200
    assert http("post", f"/ai-governance/api/systems/{app}/retire", name="dpo_a", json={"reason": ""}).status_code == 422
    assert http("post", f"/ai-governance/api/systems/{app}/retire", name="dpo_a", json={"reason": "Contract ended."}).status_code == 200
    assert http("post", f"/ai-governance/api/systems/{app}/retire", name="dpo_a", json={"reason": "Again"}).status_code == 409
    assert http("get", "/ai-governance/api/systems?state=retired", name="dpo_a").json()["total"] == 1
    assert http("get", f"/ai-governance/api/systems/{app}/tabs/activity", name="dpo_a").json()["sections"][0]["items"], "the activity tab shows it"
    assert http("post", f"/ai-governance/api/systems/{app}/restore", name="dpo_a", json={}).status_code == 200
    assert http("post", f"/ai-governance/api/systems/{app}/restore", name="dpo_a", json={}).status_code == 409


def test_a_profile_is_added_to_an_application_that_has_none_and_only_once(http):
    plain = _insert(http.world.db, "applications", name="Plain", business_unit_id=http.world.unit["A"], is_active=1)
    http.world.db.commit()
    made = http("post", f"/ai-governance/api/systems/{plain}/profile", name="dpo_a", json={"answers": {"purpose": "Search"}})
    assert made.status_code == 201 and made.json()["profile"]["purpose"] == "Search"
    assert http("post", f"/ai-governance/api/systems/{plain}/profile", name="dpo_a", json={"answers": {}}).status_code == 409


# ── Linking from the workspace ──────────────────────────────────────────────

def test_a_reviewer_links_an_assessment_and_the_tab_shows_it_and_removing_it_takes_it_away(http):
    world = http.world
    app = _accepted(http)
    dpia = _insert(world.db, "sentinel_dpias", ref_number="DPIA-9", title="DPIA for the summarizer", business_unit_id=world.unit["A"])
    world.db.commit()
    kinds = http("get", "/ai-governance/api/link-kinds").json()["items"]
    assert any(k["verb"] == "assesses" and k["type"] == "dpia" and k["direction"] == "incoming" for k in kinds)
    found = http("get", f"/ai-governance/api/systems/{app}/link-candidates?verb=assesses&module=sentinel&type=dpia", name="dpo_a").json()["items"]
    assert [f["title"] for f in found] == ["DPIA for the summarizer"]
    link = http("post", "/api/links", name="dpo_a", json={"source_module": "sentinel", "source_type": "dpia", "source_id": dpia,
                                                           "target_module": "governance", "target_type": "application", "target_id": app, "relationship": "assesses"})
    assert link.status_code == 201
    tab = http("get", f"/ai-governance/api/systems/{app}/tabs/assessments", name="dpo_a").json()
    linked = next(s for s in tab["sections"] if s["title"] == "Privacy assessments linked to this use")["items"]
    assert [(i["title"], i["status"]) for i in linked] == [("DPIA for the summarizer", "assessed by")] and linked[0]["link_id"] == link.json()["link_id"]
    assert http("delete", f"/api/links/{link.json()['link_id']}", name="dpo_a").status_code == 200
    again = http("get", f"/ai-governance/api/systems/{app}/tabs/assessments", name="dpo_a").json()
    assert next(s for s in again["sections"] if s["title"] == "Privacy assessments linked to this use")["items"] == []


def test_staff_who_do_not_own_the_use_cannot_link_it(http):
    world = http.world
    app = _accepted(http, name="owner_a")  # owner_a owns this use
    process = _insert(world.db, "business_processes", name="Support desk", business_unit_id=world.unit["A"])
    world.db.commit()
    body = {"source_module": "governance", "source_type": "application", "source_id": app, "target_module": "governance",
            "target_type": "process", "target_id": process, "relationship": "supports"}
    assert http("post", "/api/links", name="employee_a", json=body).status_code == 403
    assert http("post", "/api/links", name="owner_a", json=body).status_code == 201


def test_the_pages_render_with_the_modules_navigation(http):
    for path, expect in (("/ai-governance/", "Register an AI use"), ("/ai-governance/register", "Register an AI use"),
                         ("/ai-governance/requests", "My requests")):
        page = http("get", path)
        assert page.status_code == 200 and expect in page.text and "/static/js/ai_governance_common.js" in page.text, path
    review = http("get", "/ai-governance/review", name="dpo_a")
    assert "Review requests" in review.text and "ai_governance_lists.js" in review.text
    assert 'href="/ai-governance/review"' in review.text
    assert 'href="/ai-governance/review"' not in http("get", "/ai-governance/", name="employee_a").text, "staff are not offered the reviewers' page"
