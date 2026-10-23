"""Policy approval through the admin route without a Windows event-loop socket."""

import json

from starlette.requests import Request

import core.ai_policy as ai_policy
import core.middleware as middleware
import database
from core import rbac
from modules.launcher import routes_admin


ORG_ID = 11


def _invoke(coroutine):
    """These handlers have no pending I/O when test receive returns immediately."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("AI policy handler unexpectedly suspended")


def _request(body):
    payload = json.dumps(body).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {"type": "http", "method": "PUT", "path": "/api/admin/ai-policy",
         "headers": [(b"content-type", b"application/json")],
         "query_string": b"", "server": ("testserver", 80)},
        receive=receive,
    )


def test_admin_must_confirm_enabled_policy_and_approval_is_recorded(test_db, monkeypatch):
    test_db.execute("INSERT INTO organizations (id, name, slug, status) "
                    "VALUES (%s, 'Policy test', 'policy_test', 'active')", (ORG_ID,))
    test_db.execute("INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
                    "VALUES (1, 'policy_reviewer', 'reviewer@example.test', 'Policy reviewer', 'x', %s)",
                    (ORG_ID,))
    test_db.commit()
    admin = {"id": 1, "username": "policy_reviewer", "org_id": ORG_ID,
             "roles": [rbac.ORG_ADMIN], "is_super_admin": False}

    async def current_user(request):
        return admin

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    database.set_current_org(ORG_ID, user_id=admin["id"])
    try:
        denied = _invoke(routes_admin.api_ai_policy_put(_request({"enabled": True})))
        assert denied.status_code == 400
        assert ai_policy.get_policy(ORG_ID) is None

        approved = _invoke(routes_admin.api_ai_policy_put(
            _request({"enabled": True, "approval_confirmed": True,
                      "providers": ["openrouter"], "categories": ["business"],
                      "monthly_token_budget": 10000,
                      "monthly_user_token_budget": 5000}),
        ))
        assert approved.status_code == 200
        policy = ai_policy.get_policy(ORG_ID)
        assert policy["enabled"] is True and policy["review_required"] is False
        row = test_db.execute("SELECT value FROM settings WHERE key=%s",
                              (f"ai.policy.org{ORG_ID}",)).fetchone()
        stored = json.loads(row["value"])
        assert stored["approved_by"] == admin["id"] and stored["approved_at"]
        assert stored["providers"] == ["openrouter"]
    finally:
        database.set_current_org(None)
