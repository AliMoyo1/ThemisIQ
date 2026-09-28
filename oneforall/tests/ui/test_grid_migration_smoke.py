"""
PLAN-36 T06 (findings.md F08): GRID had no browser coverage at all. This
module's shared `api(url,methodOrOpts,body)` wrapper (~90 call sites) kept
its old "return null on failure" contract deliberately rather than throwing
like every other module's apiFetch migration -- see progress.md for why.
The page-load test below is the one that actually matters for that
decision: if the migrated api() broke, essentially the whole page would
fail to render, not just one action.
"""


def test_grid_dashboard_loads_via_the_migrated_api_wrapper(login_as, live_app):
    page = login_as("super_admin")
    seen = {"hit": False}
    page.on("request", lambda req: seen.__setitem__("hit", seen["hit"] or "/grid/api/" in req.url))
    page.goto(f"{live_app}/grid/")
    page.wait_for_load_state("networkidle", timeout=10000)
    assert seen["hit"], "expected at least one real request under /grid/api/, saw none"
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_delete_audit_shows_the_real_server_error_on_failure(login_as, live_app):
    """deleteAudit() previously extracted d.detail from a manually-checked
    response; now goes through ApiClient.request. Confirms the message
    still reaches the toast after the migration, against a route-
    intercepted failure so this doesn't depend on real audit data existing."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/grid/")
    page.wait_for_load_state("networkidle", timeout=10000)
    page.route("**/grid/api/audits/999", lambda r: r.fulfill(
        status=409, content_type="application/json",
        body='{"detail": "Cannot delete an audit with an active sign-off."}'))
    page.once("dialog", lambda d: d.accept())
    page.evaluate("() => window.deleteAudit(999, 'Test Audit', false)")
    page.wait_for_selector(".toast-error", timeout=5000)
    assert "active sign-off" in page.locator(".toast-error").inner_text()
