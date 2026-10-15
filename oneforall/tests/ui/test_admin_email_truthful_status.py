"""
The Email Settings page says what the sender really is (plans/2026-10-governance-rework/06 sections 2 and 7, phase E1):
console mode is not a configured provider, a password is a deployment secret and not a field to fill in, and the
delivery queue is visible to the administrator.
"""


def test_console_mode_is_not_shown_as_configured_and_the_queue_is_visible(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/admin/email")
    page.wait_for_selector("#queueCounts:not(:has-text('Loading'))", timeout=8000)
    badge = page.inner_text("#statusBadge").lower()
    assert "configured" not in badge.replace("not configured", "") and ("console only" in badge or "not configured" in badge)
    body = page.inner_text("body").lower()
    assert "sender health" in body and "delivery queue" in body
    assert "queued: 0" in page.inner_text("#queueCounts")


def test_a_password_is_a_deployment_secret_and_its_field_is_not_offered(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/admin/email")
    page.wait_for_selector("#secretsNote:not([hidden])", timeout=8000)
    assert "deployment secrets" in page.inner_text("#secretsNote").lower()
    page.evaluate("() => window.selectProvider('google')")
    assert page.is_disabled("#fSmtpPass")
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
