"""Guided tours and the getting-started checklist (Level 1 onboarding, plans/2026-10-onboarding-agent/plan.md).

A tour is offered only when its area is open to the person, by the same rules as the shell's navigation. Every step
must point at a real page, and a signed-out caller gets nothing.
"""
import re

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from config import settings
from core import onboarding
from core.auth import create_session
from core.rbac import AUDIT_LEAD, DPO, EMPLOYEE, ORG_ADMIN, RISK_OWNER, has_capability, user_modules


def _ids(user):
    return [t["id"] for t in onboarding.tours_for(user)]


def test_every_tour_is_well_formed_and_written_without_dashes_or_counts():
    seen = set()
    for tour in onboarding.TOURS:
        assert tour["id"] not in seen
        seen.add(tour["id"])
        assert tour["title"] and tour["summary"] and tour["steps"]
        assert not all(step["optional"] for step in tour["steps"]), tour["id"]
        for step in tour["steps"]:
            assert step["path"].startswith("/") and not step["path"].startswith("//")
            text = step["title"] + step["body"]
            assert "\u2014" not in text, step["title"]


def test_tours_follow_exactly_what_the_role_opens():
    area_tour = {t["area"]: t["id"] for t in onboarding.TOURS if t["area"]}
    for role in (EMPLOYEE, AUDIT_LEAD, DPO, RISK_OWNER, ORG_ADMIN):
        user = {"roles": [role]}
        ids = _ids(user)
        assert ids[0] == "welcome", role
        expected = {area_tour[m] for m in user_modules(user)}
        if has_capability(user, "ai_use.view"):
            expected.add("ai-governance")
        if has_capability(user, "platform.manage_users"):
            expected.add("administration")
        assert set(ids[1:]) == expected, role
    assert "ai-governance" not in _ids({"roles": [EMPLOYEE]})
    assert "audit" in _ids({"roles": [AUDIT_LEAD]})
    assert "privacy" in _ids({"roles": [DPO]})


def test_a_module_the_organisation_has_not_licensed_offers_no_tour():
    licensed = _ids({"roles": [RISK_OWNER], "licensed_modules": ["erm"], "org_id": None})
    assert "enterprise-risk" in licensed
    assert "operations-risk" not in licensed


def test_the_checklist_lists_two_step_sign_in_and_one_item_per_tour():
    user = {"roles": [AUDIT_LEAD]}
    items = onboarding.checklist_for(user, mfa_enabled=False)
    assert items[0] == {"id": "mfa", "label": "Turn on two-step sign-in", "done": False, "href": "/mfa/setup"}
    assert [i["tour"] for i in items[1:]] == _ids(user)
    assert onboarding.checklist_for(user, mfa_enabled=True)[0]["done"] is True


def test_every_step_points_at_a_real_page():
    import main
    from starlette.routing import Match

    def routed(path):
        scope = {"type": "http", "method": "GET", "path": path, "root_path": "", "headers": [], "query_string": b""}
        return any(route.matches(scope)[0] == Match.FULL for route in main.app.routes)

    for tour in onboarding.TOURS:
        for step in tour["steps"]:
            assert routed(step["path"]), (tour["id"], step["path"])
    assert routed("/mfa/setup")
    assert not routed("/no-such-page-for-onboarding")


@pytest.fixture
def api(test_db):
    from modules.launcher.routes import router as launcher_router
    app = FastAPI()
    app.include_router(launcher_router)
    return TestClient(app, base_url="http://testserver", follow_redirects=False)


def test_the_onboarding_api_answers_a_signed_in_person_and_refuses_everyone_else(test_db, api):
    test_db.execute("INSERT INTO users (username, email, full_name, password_hash) VALUES "
                    "('new_starter','new_starter@example.test','New Starter','x')")
    test_db.commit()
    me = test_db.execute("SELECT id FROM users WHERE username='new_starter'").fetchone()["id"]
    token = create_session(me, ip="203.0.113.5", user_agent="Test/1.0")

    response = api.get("/api/onboarding", headers={"Cookie": f"{settings.SESSION_COOKIE_NAME}={token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == me
    assert [t["id"] for t in body["tours"]] == ["welcome"]
    assert body["checklist"][0]["id"] == "mfa" and body["checklist"][0]["done"] is False

    assert api.get("/api/onboarding").status_code in (303, 401, 403)
