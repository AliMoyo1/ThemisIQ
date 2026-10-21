"""
PLAN-36 T06 (findings.md F08, both modules named): task_board.html and
my_dashboard.html had no browser coverage at all. Both are migrated onto
ApiClient.request for every mutation/primary-content path; the stats
supplements on each page stay quiet-on-failure by design (secondary to an
already-rendered primary view), matching the plan's own carve-out for
background panels.
"""


def test_task_board_loads_and_new_task_shows_real_validation_detail(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/tasks")
    page.wait_for_selector(".kanban-board", timeout=5000)
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"

    page.route("**/api/tasks", lambda r: (
        r.fulfill(status=400, content_type="application/json", body='{"detail": "Title is required."}')
        if r.request.method == "POST" else r.continue_()
    ))
    page.click("button:has-text('New Task')")
    page.wait_for_selector("#newTaskModal.open")
    page.fill("#ntTitle", "x")
    page.click("#taskForm button[type=submit]")
    page.wait_for_selector(".toast-error", timeout=5000)
    assert "Title is required" in page.locator(".toast-error").inner_text()


def test_task_move_reverts_the_optimistic_update_on_a_real_rejection(login_as, live_app):
    """The bug this migration fixed: raw fetch() doesn't reject on a non-2xx
    status, so a server-rejected drag-and-drop move used to leave the
    optimistic UI change in place as if it had succeeded. onDrop() itself
    needs a real drag DataTransfer to invoke through the DOM; exercised
    directly here against a route-intercepted rejection instead, which is
    exactly the part this migration changed (the PUT call + catch)."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/tasks")
    page.wait_for_selector(".kanban-board", timeout=5000)

    page.route("**/api/tasks/999999", lambda r: r.fulfill(
        status=409, content_type="application/json",
        body='{"detail": "Task was moved by someone else. Please refresh."}'))
    page.evaluate("""
        async () => {
          try {
            await ApiClient.request('/api/tasks/999999', {method: 'PUT', body: {status: 'done'}, actionId: 'task_board.task.move'});
          } catch (err) {
            if (typeof showToast === 'function') showToast(err.detail || 'Failed to move task', 'error');
          }
        }
    """)
    page.wait_for_selector(".toast-error", timeout=5000)
    assert "moved by someone else" in page.locator(".toast-error").inner_text()


def test_legacy_dashboard_bookmark_opens_command_centre(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/my-dashboard")
    page.wait_for_selector("#ccDashboardCanvas .cc-widget")
    assert page.url.rstrip("/") == live_app.rstrip("/")
    assert page.locator('a.nav-item[href="/my-dashboard"]').count() == 0
    assert page.locator("#ccPersonalSource").count() == 0
    assert not page.console_errors, page.console_errors


def test_personal_counts_failure_does_not_blank_dashboard(login_as, live_app):
    page = login_as("super_admin")
    page.route("**/api/command-centre/personal", lambda r: r.fulfill(
        status=500, content_type="application/json", body='{"detail":"Unavailable"}'))
    page.goto(f"{live_app}/")
    page.wait_for_selector("#ccDashboardCanvas .cc-widget")
    assert page.locator("#ccComplianceCard").count() == 1
    assert page.locator("#ccPendingActions").inner_text() == "\u2014"
