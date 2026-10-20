"""
AI governance G1c: the administrator's side of the AI policy.

An organization administrator reads and sets their own organization's policy, a platform administrator names the
organization, nobody else gets in, a bad submission changes nothing, and what is saved is what the AI client then
enforces and what the usage view then counts.
"""
import json
import pathlib
import types

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.ai_client as ai_client
import core.ai_policy as ai_policy
import core.middleware as middleware
import database
from core import rbac
from core.shell_context import shell_ctx
from modules.launcher.routes import router as launcher_router

ORG_A, ORG_B = 11, 12
PEOPLE = {
    "admin_a": (1, ORG_A, rbac.ORG_ADMIN, 0),
    "admin_b": (2, ORG_B, rbac.ORG_ADMIN, 0),
    "employee_a": (3, ORG_A, rbac.EMPLOYEE, 0),
    "platform": (4, None, rbac.SUPER_ADMIN, 1),
}


@pytest.fixture
def http(test_db, monkeypatch):
    for org, slug in ((ORG_A, "acme"), (ORG_B, "globex")):
        test_db.execute("INSERT INTO organizations (id, name, slug, status) VALUES (%s, %s, %s, 'active')", (org, slug.title(), slug))
    for name, (uid, org, _, _) in PEOPLE.items():
        test_db.execute("INSERT INTO users (id, username, email, full_name, password_hash, org_id) VALUES (%s,%s,%s,%s,'x',%s)",
                        (uid, name, f"{name}@example.test", name, org))
    test_db.commit()
    users = {name: {"id": uid, "username": name, "org_id": org, "roles": [role], "is_super_admin": sup}
             for name, (uid, org, role, sup) in PEOPLE.items()}
    who = {"name": "admin_a"}

    async def current_user(request):
        return users[who["name"]] if who["name"] else None

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(launcher_router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False, follow_redirects=False)

    def call(method, path, name="admin_a", **kwargs):
        who["name"] = name
        return getattr(client, method)(path, **kwargs)

    call.db = test_db
    call.users = users
    return call


def _stored(http, org):
    row = http.db.execute("SELECT value FROM settings WHERE key = %s", (f"ai.policy.org{org}",)).fetchone()
    return json.loads(row["value"]) if row else None


GOOD = {"enabled": True, "providers": ["anthropic"], "categories": ["public", "business"],
        "blocked_features": ["bcm.chat"], "monthly_token_budget": 5000}


def test_an_administrator_reads_the_default_policy_and_what_can_be_chosen(http):
    view = http("get", "/api/admin/ai-policy").json()
    assert view["org_id"] == ORG_A and view["configured"] is False
    assert view["policy"] == ai_policy.default_policy()
    assert view["providers"] == list(ai_policy.PROVIDERS) and set(view["categories"]) == set(ai_policy.CATEGORIES)
    assert len(view["features"]) == len(ai_policy.FEATURES)
    assert {"id": "aria.ask", "label": "Ask ARIA", "categories": ["business"]} in view["features"]
    assert view["usage"]["calls"] == 0 and view["usage"]["allowance_used"] == 0


def test_saving_stores_the_policy_audits_the_change_and_reads_back(http):
    saved = http("put", "/api/admin/ai-policy", json=GOOD)
    assert saved.status_code == 200 and saved.json()["configured"] is True
    stored = _stored(http, ORG_A)
    assert {k: stored[k] for k in GOOD} == GOOD and stored["updated_by"] == 1
    assert http("get", "/api/admin/ai-policy").json()["policy"]["blocked_features"] == ["bcm.chat"]
    [entry] = [dict(r) for r in http.db.execute("SELECT * FROM audit_log WHERE action = 'ai_policy_updated'").fetchall()]
    assert (entry["user_id"], entry["org_id"], entry["entity_id"]) == (1, ORG_A, ORG_A)
    assert "first policy" in entry["details"] and "providers" in entry["details"]
    http("put", "/api/admin/ai-policy", json={**GOOD, "monthly_token_budget": None})
    changed = http.db.execute("SELECT details FROM audit_log WHERE action = 'ai_policy_updated' ORDER BY id DESC").fetchone()[0]
    assert changed == "changed: monthly_token_budget"


@pytest.mark.parametrize("body", [
    ["not", "an", "object"],
    {"enabled": "yes"},
    {"providers": ["not-a-provider"]},
    {"providers": "anthropic"},
    {"providers": ["anthropic", 7]},
    {"categories": ["everything"]},
    {"blocked_features": ["no.such_feature"]},
    {"monthly_token_budget": 0},
    {"monthly_token_budget": -5},
    {"monthly_token_budget": "lots"},
    {"monthly_token_budget": True},
    {"monthly_token_budget": 1.5},
])
def test_a_bad_submission_is_refused_and_changes_nothing(http, body):
    response = http("put", "/api/admin/ai-policy", json=body)
    assert response.status_code == 400 and response.json()["ok"] is False and response.json()["error"]
    assert _stored(http, ORG_A) is None


def test_a_body_that_is_not_json_is_refused(http):
    assert http("put", "/api/admin/ai-policy", content=b"{nope", headers={"content-type": "application/json"}).status_code == 400
    assert _stored(http, ORG_A) is None


def test_an_empty_provider_list_means_any_provider_and_is_stored_as_such(http):
    http("put", "/api/admin/ai-policy", json={"enabled": True, "providers": []})
    assert _stored(http, ORG_A)["providers"] == []
    assert _stored(http, ORG_A)["categories"] == list(ai_policy.CATEGORIES)


def test_only_an_administrator_may_read_or_change_the_policy(http):
    for call in (lambda n: http("get", "/api/admin/ai-policy", name=n),
                 lambda n: http("put", "/api/admin/ai-policy", name=n, json=GOOD),
                 lambda n: http("get", "/admin/ai-policy", name=n)):
        assert call("employee_a").status_code == 403
        assert call(None).status_code == 303
    assert _stored(http, ORG_A) is None


def test_an_organization_administrator_cannot_reach_another_organization(http):
    http("put", "/api/admin/ai-policy?org_id=12", json=GOOD)  # org_id is ignored: it is their own policy that changes
    assert _stored(http, ORG_A) is not None and _stored(http, ORG_B) is None
    assert http("get", "/api/admin/ai-policy?org_id=12").json()["org_id"] == ORG_A


def test_a_platform_administrator_names_the_organization(http):
    assert http("get", "/api/admin/ai-policy", name="platform").status_code == 400
    assert http("put", "/api/admin/ai-policy", name="platform", json=GOOD).status_code == 400
    assert http("get", "/api/admin/ai-policy?org_id=999", name="platform").status_code == 404
    saved = http("put", "/api/admin/ai-policy?org_id=12", name="platform", json=GOOD)
    assert saved.status_code == 200 and saved.json()["org_id"] == ORG_B
    assert _stored(http, ORG_B) is not None and _stored(http, ORG_A) is None
    assert http("get", "/api/admin/ai-policy?org_id=12", name="platform").json()["configured"] is True
    assert http("get", "/api/admin/ai-policy?org_id=11", name="platform").json()["configured"] is False


def test_each_organization_keeps_its_own_policy(http):
    http("put", "/api/admin/ai-policy", name="admin_a", json={"enabled": False})
    http("put", "/api/admin/ai-policy", name="admin_b", json={"enabled": True, "monthly_token_budget": 10})
    assert http("get", "/api/admin/ai-policy", name="admin_a").json()["policy"]["enabled"] is False
    assert http("get", "/api/admin/ai-policy", name="admin_b").json()["policy"]["monthly_token_budget"] == 10


def test_what_an_administrator_saves_is_what_the_client_then_enforces_and_counts(http, monkeypatch):
    monkeypatch.setattr(ai_policy, "_RECORDING", True)
    monkeypatch.setattr(ai_client, "_provider", lambda: "anthropic")
    monkeypatch.setattr(ai_client, "_dispatch_to_provider",
                        lambda *a: {"text": "ok", "model": "m", "input_tokens": 10, "output_tokens": 5})
    database.set_current_org(ORG_A, user_id=3)
    try:
        assert ai_client.create_message([{"role": "user", "content": "x"}], feature="aria.ask") == "ok"
        http("put", "/api/admin/ai-policy", json={"enabled": False})
        with pytest.raises(ai_policy.AIPolicyError):
            ai_client.create_message([{"role": "user", "content": "x"}], feature="aria.ask")
    finally:
        database.set_current_org(None)
    usage = http("get", "/api/admin/ai-policy").json()["usage"]
    assert (usage["calls"], usage["refused"], usage["tokens"]) == (1, 1, 15)
    assert usage["by_feature"][0]["label"] == "Ask ARIA" and usage["recent_refusals"][0]["reason"] == "disabled"
    assert http("get", "/api/admin/ai-policy", name="admin_b").json()["usage"]["calls"] == 0


def test_the_page_renders_for_an_administrator_and_the_shell_offers_the_link_only_to_them(http):
    page = http("get", "/admin/ai-policy")
    assert page.status_code == 200 and "AI Policy" in page.text and 'href="/admin/ai-policy"' in page.text
    source = (pathlib.Path(__file__).resolve().parent.parent / "modules/launcher/templates/admin_ai_policy.html").read_text(encoding="utf-8")
    assert "innerHTML" not in source and "insertAdjacentHTML" not in source, "the page builds its rows from text nodes only"
    flags = {name: shell_ctx(types.SimpleNamespace(state=types.SimpleNamespace(user=user)))["can_manage_ai_policy"]
             for name, user in http.users.items()}
    assert flags == {"admin_a": True, "admin_b": True, "employee_a": False, "platform": True}


# ── The rollout switch ──────────────────────────────────────────────────────

def _switch(http, org):
    row = http.db.execute("SELECT value FROM settings WHERE key = %s", (f"ai_governance.enabled.org{org}",)).fetchone()
    return row["value"] if row else None


def test_an_organization_administrator_reads_the_switch_and_only_a_platform_administrator_changes_it(http, monkeypatch):
    from config import settings
    from core import ai_rollout
    monkeypatch.setattr(settings, "AI_GOVERNANCE_DEFAULT_ENABLED", False)
    ai_rollout.clear_cache()
    assert http("get", "/api/admin/ai-policy").json()["governance"] == {
        "enabled": False, "chosen": False, "default": False, "can_change": False, "separation_required": True}

    denied = http("put", "/api/admin/ai-governance", json={"enabled": True})
    assert denied.status_code == 403 and _switch(http, ORG_A) is None
    assert http("put", "/api/admin/ai-governance", name="employee_a", json={"enabled": True}).status_code == 403
    assert http("put", "/api/admin/ai-governance", name="platform", json={"enabled": True}).status_code == 400, "no organization named"

    on = http("put", f"/api/admin/ai-governance?org_id={ORG_A}", name="platform", json={"enabled": True})
    assert on.status_code == 200 and on.json()["governance"]["enabled"] is True and _switch(http, ORG_A) == "1"
    assert _switch(http, ORG_B) is None
    assert http("get", "/api/admin/ai-policy").json()["governance"] == {
        "enabled": True, "chosen": True, "default": False, "can_change": False, "separation_required": True}
    assert http("get", f"/api/admin/ai-policy?org_id={ORG_A}", name="platform").json()["governance"]["can_change"] is True

    off = http("put", f"/api/admin/ai-governance?org_id={ORG_A}", name="platform", json={"enabled": False})
    assert off.status_code == 200 and _switch(http, ORG_A) == "0"
    actions = [(r["user_id"], r["entity_id"], r["details"]) for r in http.db.execute(
        "SELECT user_id, entity_id, details FROM audit_log WHERE action = 'ai_governance_switched' ORDER BY id").fetchall()]
    assert actions == [(4, ORG_A, "off -> on"), (4, ORG_A, "on -> off")]


@pytest.mark.parametrize("body", [{"enabled": "yes"}, {"enabled": 1}, {"on": True}, ["enabled"], None])
def test_a_switch_request_that_is_not_a_plain_yes_or_no_changes_nothing(http, body):
    sent = http("put", f"/api/admin/ai-governance?org_id={ORG_A}", name="platform",
                **({"json": body} if body is not None else {"content": b"{nope", "headers": {"content-type": "application/json"}}))
    assert sent.status_code == 400 and _switch(http, ORG_A) is None


def test_the_navigation_flag_follows_the_switch(http):
    from core import ai_rollout
    person = http.users["admin_a"]
    request = types.SimpleNamespace(state=types.SimpleNamespace(user=person), query_params={})
    assert shell_ctx(request)["can_ai_use"] is True, "the suites start with it on"
    ai_rollout.set_enabled(ORG_A, False)
    assert shell_ctx(request)["can_ai_use"] is False
    assert shell_ctx(types.SimpleNamespace(state=types.SimpleNamespace(user=http.users["admin_b"]), query_params={}))["can_ai_use"] is True,         "another organization is not affected"


def test_an_organization_administrator_turns_separation_of_duties_off_and_on_and_it_is_audited(http):
    from core import ai_rollout
    assert http("get", "/api/admin/ai-policy").json()["governance"]["separation_required"] is True
    off = http("put", "/api/admin/ai-decision-separation", json={"required": False})
    assert off.status_code == 200 and off.json() == {"ok": True, "separation_required": False}
    assert ai_rollout.separation_required(ORG_A) is False and ai_rollout.separation_required(ORG_B) is True
    assert http("get", "/api/admin/ai-policy").json()["governance"]["separation_required"] is False
    assert http("put", "/api/admin/ai-decision-separation", json={"required": True}).status_code == 200
    assert http("put", "/api/admin/ai-decision-separation", name="employee_a", json={"required": False}).status_code == 403
    for bad in ({"required": "no"}, {"required": 0}, {"off": True}, ["required"]):
        assert http("put", "/api/admin/ai-decision-separation", json=bad).status_code == 400, bad
    actions = [r["details"] for r in http.db.execute(
        "SELECT details FROM audit_log WHERE action = 'ai_decision_separation_changed' ORDER BY id").fetchall()]
    assert actions == ["on -> off", "off -> on"]
