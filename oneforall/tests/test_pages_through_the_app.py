"""What the real pages show a restricted role, rendered through the routers and templates.

Analytics trends and the Predictive Risk panel are organization-wide, so the APIs behind them are for
super administrators only. A page that still offers them to everyone else shows a dead link, or an
error card plus a console error on every dashboard load (the browser suite caught that). These tests
render the pages themselves, so they fail when a template and its API disagree.
"""
import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.testclient import TestClient

import core.middleware as middleware
from modules.launcher.routes import router as launcher_router

# command_centre.html, platform_base.html (vendors) and base_shell.html (risk register, calendar)
PAGES = ["/", "/vendors", "/risk-register", "/calendar"]
RESTRICTED = ["dpo", "employee", "compliance_manager"]


def _persona(role, uid):
    return {"id": uid, "username": role, "full_name": role, "org_id": 1, "business_unit_id": None,
            "is_super_admin": 1 if role == "super_admin" else 0, "roles": [role]}


@pytest.fixture
def pages(test_db, monkeypatch):
    test_db.execute("INSERT INTO organizations (id, name, slug) VALUES (1, 'org', 'org')")
    personas = {role: _persona(role, i) for i, role in enumerate(RESTRICTED + ["super_admin"], start=11)}
    for p in personas.values():
        test_db.execute(
            "INSERT INTO users (id, username, email, full_name, password_hash, org_id) VALUES (%s,%s,%s,%s,'x',1)",
            (p["id"], p["username"], f"{p['username']}@example.test", p["username"]),
        )
    test_db.commit()
    who = {"role": RESTRICTED[0]}

    async def current_user(request):
        return personas[who["role"]]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")  # templates link to it
    app.include_router(launcher_router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False)

    def get(path, role):
        who["role"] = role
        response = client.get(path)
        assert response.status_code == 200, (path, role, response.status_code)
        return response.text

    return get


@pytest.mark.parametrize("role", RESTRICTED)
def test_the_predictive_risk_card_is_not_offered_to_roles_the_api_refuses(pages, role):
    assert 'id="prPanel"' not in pages("/", role)


def test_the_predictive_risk_card_is_on_the_super_admins_command_centre(pages):
    assert 'id="prPanel"' in pages("/", "super_admin")


@pytest.mark.parametrize("path", PAGES)
@pytest.mark.parametrize("role", RESTRICTED)
def test_the_analytics_link_is_not_offered_to_roles_the_api_refuses(pages, path, role):
    assert 'href="/analytics"' not in pages(path, role)


@pytest.mark.parametrize("path", PAGES)
def test_the_analytics_link_is_in_the_super_admins_navigation(pages, path):
    assert 'href="/analytics"' in pages(path, "super_admin")
