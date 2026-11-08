"""Two-step sign-in, end to end in a real browser: enrollment, signing in with a code, replay refusal, single-use
backup codes, turning it off, and enrollment forced by the organization's policy.

Each test signs in a fresh person of its own, so no shared persona ends up with MFA switched on. The encryption key is
a throwaway generated for the test.
"""
import time

import pyotp
import pytest
from cryptography.fernet import Fernet

import database
from core.auth import hash_password

PASSWORD = "Synthetic-Mfa-Pass-1!"


@pytest.fixture
def mfa_key(monkeypatch):
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))


def _person(synthetic_tenant, username):
    db = database.get_db()
    try:
        db.execute("INSERT INTO users (username, email, full_name, password_hash, org_id, must_change_password) "
                   "VALUES (%s, %s, 'Mfa Journey', %s, %s, 0)",
                   (username, f"{username}@example.test", hash_password(PASSWORD), synthetic_tenant["org_id"]))
        uid = db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]
        db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, 'employee')", (uid,))
        db.commit()
        return uid
    finally:
        db.close()


def _sign_in(page, live_app, username):
    page.context.clear_cookies()
    page.goto(f"{live_app}/login")
    page.fill("#username", username)
    page.fill("#password", PASSWORD)
    page.click("#submitBtn")
    page.wait_for_load_state("networkidle")


def _path(page, live_app):
    return page.url[len(live_app):]


def _verify(page, code):
    page.fill('form[action="/mfa/verify"] input[name="code"]', code)
    page.click('form[action="/mfa/verify"] button[type="submit"]')
    page.wait_for_load_state("networkidle")


def _enroll(page, live_app):
    """Read the secret and backup codes from the setup page, prove a wrong code fails, then enroll."""
    page.goto(f"{live_app}/mfa/setup")
    secret = page.locator(".secret").inner_text().strip()
    codes = [c.strip() for c in page.locator(".backup-grid div").all_inner_texts()]
    assert secret and len(codes) >= 8

    page.fill('form[action="/mfa/enable"] input[name="code"]', "000000" if pyotp.TOTP(secret).now() != "000000"
              else "111111")
    page.click('form[action="/mfa/enable"] button[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "bad=1" in page.url
    assert "didn't verify" in page.locator(".notice-bad").first.inner_text()

    enrolled_code = pyotp.TOTP(secret).now()
    page.fill('form[action="/mfa/enable"] input[name="code"]', enrolled_code)
    page.click('form[action="/mfa/enable"] button[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "ok=1" in page.url, page.url
    assert "now active" in page.locator(".notice-ok").first.inner_text()
    return secret, codes, enrolled_code


def test_enroll_sign_in_with_a_code_refuse_replay_spend_a_backup_code_once_and_turn_it_off(
        page, live_app, synthetic_tenant, mfa_key):
    uid = _person(synthetic_tenant, "mfa_journey_voluntary")
    _sign_in(page, live_app, "mfa_journey_voluntary")
    assert _path(page, live_app) == "/", "no MFA yet: straight in"

    secret, backup_codes, enrolled_code = _enroll(page, live_app)
    db = database.get_db()
    try:
        stored = db.execute("SELECT totp_secret, is_enabled FROM user_mfa WHERE user_id=%s", (uid,)).fetchone()
    finally:
        db.close()
    assert stored["is_enabled"] == 1
    assert stored["totp_secret"].startswith("fernet:v1:") and secret not in stored["totp_secret"]

    # A new sign-in now stops at the code page; the app is out of reach until a code is accepted.
    _sign_in(page, live_app, "mfa_journey_voluntary")
    assert _path(page, live_app) == "/mfa/verify"
    page.goto(f"{live_app}/my-work")
    assert _path(page, live_app) == "/mfa/verify"

    _verify(page, enrolled_code)
    assert _path(page, live_app) == "/mfa/verify", "the code already used to enroll cannot be replayed"
    assert "didn't match" in page.locator(".error").inner_text()

    _verify(page, pyotp.TOTP(secret).at(time.time() + 30))
    assert _path(page, live_app) == "/", page.url
    page.goto(f"{live_app}/my-work")
    assert _path(page, live_app) == "/my-work"

    # A backup code works once and only once.
    _sign_in(page, live_app, "mfa_journey_voluntary")
    _verify(page, backup_codes[0])
    assert _path(page, live_app) == "/", page.url
    _sign_in(page, live_app, "mfa_journey_voluntary")
    _verify(page, backup_codes[0])
    assert _path(page, live_app) == "/mfa/verify", "a spent backup code is refused"
    _verify(page, backup_codes[1])
    assert _path(page, live_app) == "/"

    # Turning it off needs the current password and a confirmation.
    page.goto(f"{live_app}/mfa/setup")
    page.once("dialog", lambda dialog: dialog.accept())
    page.fill('form[action="/mfa/disable"] input[name="password"]', "not-the-password")
    page.click('form[action="/mfa/disable"] button[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "badpw=1" in page.url
    page.once("dialog", lambda dialog: dialog.accept())
    page.fill('form[action="/mfa/disable"] input[name="password"]', PASSWORD)
    page.click('form[action="/mfa/disable"] button[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "off=1" in page.url
    _sign_in(page, live_app, "mfa_journey_voluntary")
    assert _path(page, live_app) == "/", "with MFA off, sign-in goes straight in again"


def test_an_organization_that_requires_mfa_sends_a_new_person_to_enroll_before_anything_else(
        page, live_app, synthetic_tenant, mfa_key):
    _person(synthetic_tenant, "mfa_journey_required")
    db = database.get_db()
    try:
        db.execute("INSERT INTO settings (key, value) VALUES ('security.require_mfa', 'all') "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        db.commit()
    finally:
        db.close()
    background = []
    page.on("response", lambda r: background.append((r.url[len(live_app):], r.status))
            if r.url.startswith(f"{live_app}/api/") else None)
    try:
        _sign_in(page, live_app, "mfa_journey_required")
        assert _path(page, live_app) == "/mfa/setup"
        # The shell's background calls (notifications and the like) must not be redirected to an MFA page: that
        # used to issue a new CSRF cookie and make the setup form fail every time.
        page.wait_for_load_state("networkidle")
        assert background and all(status == 401 for _url, status in background), background
        for elsewhere in ("/", "/my-work", "/mfa/verify"):
            page.goto(f"{live_app}{elsewhere}")
            assert _path(page, live_app) == "/mfa/setup", (elsewhere, page.url)

        secret, _codes, _used = _enroll(page, live_app)
        page.goto(f"{live_app}/my-work")
        assert _path(page, live_app) == "/my-work", "enrolling ends the pending state"

        # Policy forbids turning it off: the request is ignored.
        page.goto(f"{live_app}/mfa/setup")
        page.evaluate("""() => {
          const form = document.createElement('form');
          form.method = 'post'; form.action = '/mfa/disable';
          const csrf = document.querySelector('input[name="csrf_token"]');
          for (const [name, value] of [['csrf_token', csrf ? csrf.value : ''], ['password', %r]]) {
            const input = document.createElement('input'); input.type = 'hidden';
            input.name = name; input.value = value; form.append(input);
          }
          document.body.append(form); form.submit();
        }""" % PASSWORD)
        page.wait_for_load_state("networkidle")
        assert "off=1" not in page.url
        _sign_in(page, live_app, "mfa_journey_required")
        assert _path(page, live_app) == "/mfa/verify", "still enrolled, so the next sign-in asks for a code"
        _verify(page, pyotp.TOTP(secret).at(time.time() + 30))
        assert _path(page, live_app) == "/"
    finally:
        db = database.get_db()
        try:
            db.execute("DELETE FROM settings WHERE key='security.require_mfa'")
            db.commit()
        finally:
            db.close()
