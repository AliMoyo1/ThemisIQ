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
    response = page.goto(f"{live_app}/admin/email")
    script_policy = response.headers["content-security-policy"].split("script-src ", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script_policy
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert page.locator("script:not([src]), [onclick]").count() == 0
    page.wait_for_selector("#secretsNote:not([hidden])", timeout=8000)
    assert "deployment secrets" in page.inner_text("#secretsNote").lower()
    page.locator('[data-provider-id="google"]').click()
    assert page.locator('[data-provider-id="google"]').get_attribute("aria-pressed") == "true"
    assert page.is_disabled("#fSmtpPass")
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_pause_control_remains_wired_without_sending_mail(login_as, live_app):
    page = login_as("super_admin")
    state = {"paused": False, "posts": 0}

    def outbox_response(route):
        route.fulfill(status=200, content_type="application/json", body=(
            '{"counts":{"queued":0},"by_provider":{},"attention":[],"paused":' +
            ("true" if state["paused"] else "false") + "}"
        ))

    def pause_response(route):
        state["posts"] += 1
        state["paused"] = True
        route.fulfill(status=200, content_type="application/json", body='{"paused":true}')

    page.route("**/api/admin/email-outbox", outbox_response)
    page.route("**/api/admin/email-outbox/pause", pause_response)
    page.goto(f"{live_app}/admin/email")
    page.wait_for_function("() => document.querySelector('#pauseBtn')?.textContent === 'Pause sending'")
    page.locator("#pauseBtn").click()
    page.wait_for_function("() => document.querySelector('#pauseBtn')?.textContent === 'Resume sending'")
    assert state["posts"] == 1
    assert not page.console_errors
