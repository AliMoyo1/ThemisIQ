"""A session that has not finished two-step sign-in reaches nothing but the MFA pages.

A page request is sent to the code page. A background API call gets a plain 401 instead of a redirect: following the
redirect rendered an MFA page, which issued a new CSRF cookie (and on setup a new secret) and made the form the person
was filling in fail. Someone whose organization requires MFA but who has not enrolled is sent to setup, not to a code
page where no code can match.
"""
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from config import settings
from core.auth import create_session


@pytest.fixture
def client(test_db):
    from modules.launcher.routes import router as launcher_router
    app = FastAPI()
    app.include_router(launcher_router)
    return TestClient(app, base_url="http://testserver", follow_redirects=False)


def _pending_cookie(test_db):
    test_db.execute("INSERT INTO users (username, email, full_name, password_hash) VALUES "
                    "('half_signed_in','half_signed_in@example.test','Half Signed In','x')")
    test_db.commit()
    uid = test_db.execute("SELECT id FROM users WHERE username='half_signed_in'").fetchone()["id"]
    token = create_session(uid, ip="203.0.113.9", user_agent="Test/1.0", mfa_pending=True)
    return {"Cookie": f"{settings.SESSION_COOKIE_NAME}={token}"}


def test_a_pending_session_gets_401_from_the_api_and_a_redirect_from_pages(test_db, client):
    cookie = _pending_cookie(test_db)
    api = client.get("/api/onboarding", headers=cookie)
    assert api.status_code == 401
    assert api.json() == {"error": "Finish two-step sign-in first."}
    assert "set-cookie" not in api.headers, "no CSRF cookie is issued behind the person's back"

    page = client.get("/my-work", headers=cookie)
    assert page.status_code == 303 and page.headers["location"] == "/mfa/verify"


def test_a_pending_session_without_an_authenticator_is_sent_to_setup(test_db, client):
    cookie = _pending_cookie(test_db)
    response = client.get("/mfa/verify", headers=cookie)
    assert response.status_code == 303 and response.headers["location"] == "/mfa/setup"
