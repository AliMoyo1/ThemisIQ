"""The profile page lists the signed-in user's own live sessions.

The query used to ask for a last_active column that the sessions table does not have. The error was swallowed, so
the page always said there were no sessions. These tests sign in with real session cookies and open the real page.
"""
import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.testclient import TestClient

from config import settings
from core.auth import create_session
from modules.launcher.routes import router as launcher_router


def _user(db, username):
    db.execute(
        "INSERT INTO users (username, email, full_name, password_hash) VALUES (%s,%s,%s,'x')",
        (username, f"{username}@example.test", username),
    )
    db.commit()
    return db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]


def _stamp(db, ip, created_at=None, expires_at=None):
    """Give the session opened from `ip` fixed times, so the text on the page is predictable."""
    if created_at:
        db.execute("UPDATE sessions SET created_at=%s WHERE ip_address=%s", (created_at, ip))
    if expires_at:
        db.execute("UPDATE sessions SET expires_at=%s WHERE ip_address=%s", (expires_at, ip))
    db.commit()


@pytest.fixture
def open_profile(test_db):
    app = FastAPI()
    app.mount("/static", StaticFiles(directory="static"), name="static")  # templates link to it
    app.include_router(launcher_router)
    client = TestClient(app, base_url="http://testserver", follow_redirects=False)

    def get(token):
        response = client.get("/profile", headers={"Cookie": f"{settings.SESSION_COOKIE_NAME}={token}"})
        assert response.status_code == 200, response.status_code
        return response.text

    return get


def test_the_profile_page_lists_both_of_the_users_sessions_newest_first(test_db, open_profile):
    me = _user(test_db, "two_sessions")
    older = create_session(me, ip="203.0.113.10", user_agent="OldLaptop/1.0")
    newer = create_session(me, ip="198.51.100.20", user_agent="NewPhone/2.0")
    _stamp(test_db, "203.0.113.10", "2026-10-14 08:00:00", "2099-03-14T10:15:00")
    _stamp(test_db, "198.51.100.20", "2026-10-15 09:30:00", "2099-03-15T11:45:00")
    other_token = create_session(_user(test_db, "someone_else"), ip="192.0.2.77", user_agent="OtherPerson/3.0")

    html = open_profile(newer)

    assert "Active Sessions (2)" in html
    for shown in ("203.0.113.10", "OldLaptop/1.0", "14 Oct 2026 08:00", "14 Mar 2099 10:15",
                  "198.51.100.20", "NewPhone/2.0", "15 Oct 2026 09:30", "15 Mar 2099 11:45"):
        assert shown in html, shown
    assert html.index("198.51.100.20") < html.index("203.0.113.10")
    # Somebody else's session is not this user's to see.
    assert "192.0.2.77" not in html and "OtherPerson/3.0" not in html
    # Neither a raw session token nor the stored hash of one is ever printed.
    stored = [row["token"] for row in test_db.execute("SELECT token FROM sessions").fetchall()]
    assert len(stored) == 3
    assert not any(value in html for value in [older, newer, other_token, *stored])


def test_the_profile_page_leaves_out_expired_and_unfinished_sign_ins(test_db, open_profile):
    me = _user(test_db, "mixed_sessions")
    live = create_session(me, ip="203.0.113.10", user_agent="LiveBrowser/1.0")
    create_session(me, ip="192.0.2.99", user_agent="ExpiredBrowser/1.0")
    _stamp(test_db, "192.0.2.99", expires_at="2000-01-01T00:00:00")
    create_session(me, ip="192.0.2.55", user_agent="WaitingForCode/1.0", mfa_pending=True)

    html = open_profile(live)

    assert "Active Sessions (1)" in html
    assert "LiveBrowser/1.0" in html
    assert "ExpiredBrowser/1.0" not in html and "WaitingForCode/1.0" not in html


def test_the_profile_page_escapes_a_hostile_user_agent(test_db, open_profile):
    """The browser's own header is now printed on the page, and any client can send whatever it likes there."""
    me = _user(test_db, "hostile_agent")
    token = create_session(me, ip="203.0.113.10", user_agent='<script>alert(1)</script>"><img src=x onerror=alert(2)>')

    html = open_profile(token)

    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
