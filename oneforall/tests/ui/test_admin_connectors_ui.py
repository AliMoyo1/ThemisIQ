"""
PLAN-36 T06 (findings.md F08): admin_connectors.html had no browser
coverage at all before this. Migrated onto ApiClient.request; this proves
two concrete fixes, not just that the page still works: Remove used to
discard the response entirely (no success/failure check at all -- the most
severe F08 instance found this session), and Test/Save used to be able to
show only whatever _post() got back with no typed-error path for an
HTTP-level failure (a 429/500/network error would have surfaced as an
unhandled rejection, not a message in the page).
"""


def _goto(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/admin/connectors")
    page.wait_for_selector("#slackStatus")
    return page


def test_test_slack_shows_success_message(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/admin/connectors/test-slack", lambda r: r.fulfill(
        status=200, content_type="application/json", body='{"ok": true}'))
    page.click("button:has-text('Send test message')")
    page.wait_for_selector("#slackTestMsg.ok", timeout=5000)
    assert "sent to Slack" in page.locator("#slackTestMsg").inner_text()


def test_test_slack_shows_the_real_failure_detail(login_as, live_app):
    """Previously: _post() only ever returned whatever the body said; an
    HTTP-level failure (e.g. the per-actor rate limit T05 added) had no
    path to a message at all. Now ApiClient.request's typed error detail
    flows through _post()'s catch into the same showMsg() call."""
    page = _goto(login_as, live_app)
    page.route("**/api/admin/connectors/test-slack", lambda r: r.fulfill(
        status=429, content_type="application/json",
        body='{"detail": "Too many test sends. Please wait a few minutes."}'))
    page.click("button:has-text('Send test message')")
    page.wait_for_selector("#slackTestMsg.fail", timeout=5000)
    assert "Too many test sends" in page.locator("#slackTestMsg").inner_text()


def test_save_shows_the_real_per_connector_validation_detail(login_as, live_app):
    page = _goto(login_as, live_app)
    page.route("**/api/admin/connectors", lambda r: (
        r.fulfill(status=400, content_type="application/json",
                   body='{"ok": false, "detail": "Slack URL: URL must use HTTPS"}')
        if r.request.method == "POST" else r.continue_()
    ))
    page.fill("#slackUrl", "http://not-https.example/hook")
    page.click("button:has-text('Save Changes')")
    page.wait_for_selector("#saveMsg.fail", timeout=5000)
    assert "URL must use HTTPS" in page.locator("#saveMsg").inner_text()


def _route_status(page, slack_configured):
    """The Remove button is display:none until loadStatus() reports the
    connector as configured; route the GET before navigating so the page's
    own initial loadStatus() call (fired on load, not by the test) sees it."""
    page.route("**/api/admin/connectors", lambda r: (
        r.fulfill(status=200, content_type="application/json",
                   body='{"slack_configured": %s, "teams_configured": false, "whatsapp_configured": false}'
                   % ("true" if slack_configured() else "false"))
        if r.request.method == "GET" else r.continue_()
    ))


def test_remove_surfaces_a_failure_instead_of_silently_discarding_it(login_as, live_app):
    """The bug this migration fixes: removeSlack() used to `await fetch(...)`
    and throw the result away unconditionally, so a failed remove looked
    identical to a successful one -- nothing in the page ever showed it."""
    page = login_as("super_admin")
    _route_status(page, lambda: True)
    page.route("**/api/admin/connectors/slack", lambda r: r.fulfill(
        status=500, content_type="application/json", body='{"detail": "Database error."}'))
    page.goto(f"{live_app}/admin/connectors")
    page.wait_for_selector("#slackRemoveBtn", state="visible", timeout=5000)

    page.once("dialog", lambda d: d.accept())  # the confirm() prompt
    page.click("#slackRemoveBtn")
    page.wait_for_selector("#slackTestMsg.fail", timeout=5000)
    assert "Database error." in page.locator("#slackTestMsg").inner_text()


def test_remove_succeeds_and_refreshes_status(login_as, live_app):
    removed = {"done": False}

    def _handle_delete(route):
        removed["done"] = True
        route.fulfill(status=200, content_type="application/json", body='{"ok": true}')

    page = login_as("super_admin")
    _route_status(page, lambda: not removed["done"])
    page.route("**/api/admin/connectors/slack", _handle_delete)
    page.goto(f"{live_app}/admin/connectors")
    page.wait_for_selector("#slackRemoveBtn", state="visible", timeout=5000)

    page.once("dialog", lambda d: d.accept())
    page.click("#slackRemoveBtn")
    page.wait_for_selector("#slackStatus.off", timeout=5000)
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
