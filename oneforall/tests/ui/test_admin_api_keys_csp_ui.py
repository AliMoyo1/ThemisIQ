"""API key management remains usable without inline script execution."""

import json


def test_api_key_actions_under_strict_script_policy(login_as, live_app):
    page = login_as("super_admin")
    revoked = []
    page.route("**/api/admin/api-keys", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps([{
            "id": 77, "name": "Harness integration", "org_name": "Harness",
            "key_prefix": "ofa_test", "scopes": "risks.read", "is_active": True,
        }])))
    page.route("**/api/admin/api-keys/77", lambda route: (
        revoked.append(route.request.method), route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}')))
    response = page.goto(f"{live_app}/admin/api-keys")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in response.headers["content-security-policy"].split("style-src")[0]
    assert page.locator('script[src="/static/js/admin_api_keys.js"]').count() == 1
    assert page.locator("[onclick], [onchange], [onsubmit]").count() == 0
    page.locator("#newKeyButton").click()
    page.locator("#newKeyModal.open").wait_for()
    page.locator('[data-close-modal="newKeyModal"]').click()
    page.locator("#newKeyModal").wait_for(state="hidden")
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator('[data-revoke-id="77"]').click()
    assert revoked == ["DELETE"]
    assert not page.console_errors
