"""The platform operator screen works with inline scripts disabled."""

import json


def test_super_admin_filters_module_toggle_and_demo_actions_under_strict_csp(login_as, live_app):
    page = login_as("super_admin")
    orgs = [{
        "id": 7, "name": "Example Group", "slug": "example_group",
        "plan": "enterprise", "status": "active", "created_at": "2026-11-07",
        "user_count": 1, "modules": ["aria", "grid"], "seats": 5,
        "valid_until": None,
    }]
    demos = [{
        "id": 5, "name": "Demo Contact", "email": "demo@example.invalid",
        "company": "Example", "plan": "enterprise",
        "created_at": "2026-11-07", "contacted": False,
    }]
    writes = []

    def respond(data):
        return lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(data),
        )

    def save_modules(route):
        writes.append((route.request.method, route.request.post_data_json))
        route.fulfill(status=200, content_type="application/json", body='{}')

    page.route("**/super-admin/api/orgs", respond(orgs))
    page.route("**/super-admin/api/orgs/7/users", respond([]))
    page.route("**/super-admin/api/orgs/7", save_modules)
    page.route("**/super-admin/api/demo-requests", respond(demos))
    page.route("**/super-admin/api/demo-requests/5/contacted", save_modules)

    response = page.goto(f"{live_app}/super-admin/")
    assert response.status == 200
    script_policy = response.headers["content-security-policy"].split("script-src ", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script_policy
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert page.locator('script[src="/static/js/super_admin.js"]').count() == 1
    page.locator('#orgsBody [data-sa-org-id="7"]').wait_for()
    assert page.locator("script:not([src]), [onclick], [onchange], [oninput], [onkeyup]").count() == 0

    page.locator('[data-sa-filter="trial"]').focus()
    page.keyboard.press("Enter")
    assert "No organisations match" in page.locator("#orgsBody").inner_text()
    page.locator('[data-sa-filter="all"]').click()
    page.locator("#orgSearch").fill("missing-org")
    assert "No organisations match" in page.locator("#orgsBody").inner_text()
    page.locator("#orgSearch").fill("")
    page.locator('#orgsBody [data-sa-org-id="7"]').click()
    page.locator("#orgPanel.open").wait_for()
    page.locator('.side-panel-tabs [data-tab="modules"]').click()
    row = page.locator('#moduleList [data-sa-module="bcm"]')
    row.focus()
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.querySelector('[data-sa-module=bcm]')?.getAttribute('aria-checked') === 'true'")
    assert ("PUT", {"modules": "aria,grid,bcm"}) in writes
    page.locator('#orgPanel [data-sa-action="close-panel"]').click()
    page.locator("#orgPanel:not(.open)").wait_for()

    page.locator('[data-sa-action="open-org"]').click()
    page.locator("#createOrgModal").wait_for(state="visible")
    page.locator("#newOrgModulesPicker input[value=bcm]").uncheck()
    assert "bcm" not in page.locator("#newOrgModules").input_value()
    page.locator('#createOrgModal [data-sa-action="close-org"]').first.click()
    page.locator("#createOrgModal").wait_for(state="hidden")

    page.locator('[data-dr-filter="pending"]').click()
    page.locator('#drBody [data-sa-demo-contact="5"]').click()
    page.wait_for_function("() => document.querySelector('#drBody')?.textContent.includes('Demo Contact')")
    assert any(method == "POST" for method, _ in writes)
    assert not page.console_errors
