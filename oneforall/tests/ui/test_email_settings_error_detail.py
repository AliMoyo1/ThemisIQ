"""
PLAN-36 T06 (findings.md F08): admin_email.html's Save/Test paths used to
discard the server's real error detail behind a constant 'Save failed'
string (saveConfig) or throw an uncaught exception on any non-JSON response
(loadConfig's unconditional response.json()). Both now go through
ApiClient.request and surface its typed detail. Route-intercepted, so the
server's actual validation logic is irrelevant here -- only the client's
handling of a realistic error response is under test.
"""


def test_save_shows_the_servers_real_error_detail_not_a_generic_string(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/admin/email")
    page.wait_for_selector("#saveRow")

    page.route("**/api/admin/email-config", lambda r: (
        r.fulfill(status=400, content_type="application/json",
                   body='{"detail": "SMTP host is not reachable on port 587."}')
        if r.request.method == "POST" else r.continue_()
    ))
    page.evaluate("() => window.saveConfig()")
    page.wait_for_selector("text=SMTP host is not reachable on port 587.", timeout=5000)


def test_test_email_shows_the_servers_real_error_detail(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/admin/email")
    page.wait_for_selector("#testBtn")

    page.route("**/api/admin/email-test", lambda r: r.fulfill(
        status=502, content_type="application/json",
        body='{"detail": "Upstream SMTP relay refused the connection."}'))
    page.evaluate("() => window.runTest()")
    page.wait_for_selector("text=Upstream SMTP relay refused the connection.", timeout=5000)
    # A real 502 is the scenario under test; Chrome logs any non-2xx fetch as
    # a "Failed to load resource" console message on its own, independent of
    # whether the page's JS handled it gracefully (it did, per the assert
    # above) -- filtered out the same way tests/ui/test_webhook_admin_ui.py
    # handles its own deliberate-failure test.
    real_errors = [e for e in page.console_errors if "Failed to load resource" not in e]
    assert not real_errors, f"unexpected console/page errors: {real_errors}"


def test_test_email_button_icon_survives_a_failed_attempt(login_as, live_app):
    """runTest() keeps its own disable/restore (not the generic
    ApiClient.withButtonState, which is text-only) specifically because the
    button's resting state is an icon + label, not plain text -- confirms
    that choice actually holds after a real failure, not just the happy path."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/admin/email")
    page.wait_for_selector("#testBtn")

    page.route("**/api/admin/email-test", lambda r: r.fulfill(status=500, body=""))
    page.evaluate("() => window.runTest()")
    page.wait_for_selector("#testBtn:not([disabled])", timeout=5000)
    assert page.locator("#testBtn svg").count() == 1
