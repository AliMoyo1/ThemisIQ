"""Focused HTTP checks for AI review packs and their recipient boundary."""
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.middleware as middleware
from core import rbac
from modules.ai_governance.routes import router as ai_router
from modules.launcher.routes import router as launcher_router
from tests.test_ai_governance_routes import _accepted
from tests.test_ai_governance_service import roles  # noqa: F401
from tests.test_platform_ownership import _insert, world  # noqa: F401

API = "/ai-governance/api"


@pytest.fixture
def http(world, roles, monkeypatch):
    _insert(world.db, "users", id=50, username="pack-auditor", email="pack-auditor@example.test",
            full_name="Pack Auditor", password_hash="x", org_id=world.users["dpo_a"]["org_id"])
    world.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (50, rbac.EXTERNAL_AUDITOR))
    world.db.commit()
    people = dict(world.users)
    people["auditor"] = {"id": 50, "username": "pack-auditor", "org_id": world.users["dpo_a"]["org_id"],
                         "business_unit_id": None, "is_super_admin": 0, "roles": [rbac.EXTERNAL_AUDITOR]}
    who = {"name": "employee_a"}

    async def current_user(request):
        return people[who["name"]] if who["name"] else None

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(ai_router)
    app.include_router(launcher_router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=True, follow_redirects=False)

    def call(method, path, name="employee_a", **kwargs):
        who["name"] = name
        return getattr(client, method)(path, **kwargs)

    call.world = world
    return call


def _issued(http, *, allow_download=False):
    app = _accepted(http)
    opts = {"name": "Annual AI review", "purpose": "Audit", "recipient_id": 50, "expires_days": 14,
            "allow_download": allow_download}
    preview = http("post", f"{API}/systems/{app}/packs/preview", name="dpo_a", json=opts)
    assert preview.status_code == 200, preview.text
    assert preview.json()["problems"] == {}
    issued = http("post", f"{API}/systems/{app}/packs", name="dpo_a",
                  json={**opts, "expected_hash": preview.json()["hash"]})
    assert issued.status_code == 201, issued.text
    return app, issued.json()["pack"]


def test_pack_pages_and_apis_keep_the_capability_boundary(http):
    app = _accepted(http)
    for path in ("/ai-governance/packs", f"{API}/packs/mine"):
        assert http("get", path, name=None).status_code == 303
        assert http("get", path, name="auditor").status_code == 200
    for path in (f"{API}/systems/{app}/packs", f"{API}/pack-recipients?q=pa"):
        assert http("get", path, name="auditor").status_code == 403
        assert http("get", path, name="employee_a").status_code == 403
    assert http("get", "/ai-governance/packs", name="dpo_a").status_code == 200
    assert http("get", f"{API}/pack-recipients?q=Pack", name="dpo_a").json()["items"][0]["id"] == 50


def test_preview_issue_open_export_and_withdrawal_are_bound_to_one_recipient(http):
    app, pack = _issued(http, allow_download=True)
    pack_id = pack["id"]
    assert http("get", f"{API}/packs/mine", name="auditor").json()["packs"][0]["id"] == pack_id
    page = http("get", f"/ai-governance/packs/{pack_id}", name="auditor")
    assert page.status_code == 200 and b"Annual AI review" in page.content
    export = http("get", f"{API}/packs/{pack_id}/export", name="auditor")
    assert export.status_code == 200 and export.headers["cache-control"] == "no-store"
    assert export.headers["x-content-type-options"] == "nosniff"
    assert export.json()["manifest"]["hash"] == pack["hash"]
    assert http("get", f"{API}/packs/{pack_id}/history", name="auditor").status_code == 403
    history = http("get", f"{API}/packs/{pack_id}/history", name="dpo_a").json()["events"]
    assert [event["action"] for event in history] == ["downloaded", "viewed"]
    withdrawn = http("post", f"{API}/packs/{pack_id}/revoke", name="dpo_a",
                     json={"reason": "Shared in error", "version": pack["version"]})
    assert withdrawn.status_code == 200 and withdrawn.json()["pack"]["state"] == "revoked"
    assert http("get", f"{API}/packs/mine", name="auditor").json()["packs"] == []
    hidden = http("get", f"{API}/packs/{pack_id}", name="auditor")
    missing = http("get", f"{API}/packs/987654", name="auditor")
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    assert http("get", f"/ai-governance/packs/{pack_id}", name="auditor").status_code == 404
    assert http("get", f"/ai-governance/packs/{pack_id}", name="dpo_a").status_code == 200


def test_wrong_unit_cannot_list_or_manage_and_malformed_bodies_are_rejected(http):
    app, pack = _issued(http)
    hidden = http("get", f"{API}/systems/{app}/packs", name="dpo_b")
    missing = http("get", f"{API}/systems/987654/packs", name="dpo_b")
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    for suffix in ("history", "changes"):
        hidden = http("get", f"{API}/packs/{pack['id']}/{suffix}", name="dpo_b")
        missing = http("get", f"{API}/packs/987654/{suffix}", name="dpo_b")
        assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    assert http("post", f"{API}/packs/{pack['id']}/revoke", name="dpo_b",
                json={"reason": "No access", "version": 1}).status_code == 404
    for path in (f"{API}/systems/{app}/packs/preview", f"{API}/systems/{app}/packs",
                 f"{API}/packs/{pack['id']}/revoke"):
        assert http("post", path, name="dpo_a", json=["list"]).status_code == 400
