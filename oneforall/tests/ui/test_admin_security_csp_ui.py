"""The administrator MFA policy controls remain usable under strict scripts."""

import json


def test_mfa_policy_selection_and_save_under_strict_scripts(login_as, live_app):
    page = login_as("super_admin")
    response = page.goto(f"{live_app}/admin/security")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in response.headers["content-security-policy"].split("style-src")[0]
    assert page.locator('script[src="/static/js/admin_security.js"]').count() == 1

    submitted = []

    def accept_save(route):
        submitted.append(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type="application/json", body='{"ok":true}')

    page.route("**/api/admin/security-settings", accept_save)
    page.locator('.mfa-card[data-policy="all"]').click()
    assert page.locator("#lockoutWarning").is_visible()
    page.locator("#saveBtn").click()
    page.locator("#saveStatus").filter(has_text="Saved").wait_for()
    assert submitted == [{"security": {"require_mfa": "all"}}]
    assert not page.console_errors


def test_mfa_policy_save_failure_reenables_the_button(login_as, live_app):
    page = login_as("super_admin")
    page.route("**/api/admin/security-settings", lambda route: route.abort())
    page.goto(f"{live_app}/admin/security")
    page.locator("#saveBtn").click()
    page.locator("#saveStatus").filter(has_text="Could not save MFA policy").wait_for()
    assert page.locator("#saveBtn").is_enabled()
    assert not [error for error in page.console_errors if "Failed to load resource" not in error]
