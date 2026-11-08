"""Connector administration works with inline script execution blocked."""


def test_connector_status_and_test_action_under_strict_scripts(login_as, live_app):
    page = login_as("super_admin")
    test_requests = []

    def status_response(route):
        route.fulfill(status=200, content_type="application/json", body=(
            '{"slack_configured":true,"teams_configured":false,"whatsapp_configured":false}'
        ))

    def test_response(route):
        test_requests.append(route.request.method)
        route.fulfill(status=200, content_type="application/json", body='{"ok":true}')

    page.route("**/api/admin/connectors", status_response)
    page.route("**/api/admin/connectors/test-slack", test_response)
    response = page.goto(f"{live_app}/admin/connectors")
    script_policy = response.headers["content-security-policy"].split("script-src ", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script_policy
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert page.locator("script:not([src]), [onclick]").count() == 0
    page.wait_for_function("() => document.querySelector('#slackStatus')?.textContent === 'Configured'")
    assert page.locator("#slackRemoveBtn").is_visible()
    page.locator("#slackTestBtn").click()
    page.wait_for_function("() => document.querySelector('#slackTestMsg')?.textContent.includes('Test message sent')")
    assert test_requests == ["POST"]
    assert not page.console_errors
