"""User management actions survive a strict script policy without inline handlers."""

import json


def test_admin_users_filters_modals_and_import_preview_under_strict_csp(login_as, live_app):
    page = login_as("super_admin")
    response = page.goto(f"{live_app}/admin/users")
    assert response.status == 200
    csp = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("style-src")[0]
    assert page.locator('script[src="/static/js/admin_users.js"]').count() == 1
    assert page.locator("[onclick], [onchange], [oninput], [onsubmit]").count() == 0

    page.locator('[data-users-action="open-create"]').click()
    page.locator("#newUserModal.show").wait_for()
    page.locator('#newUserModal [data-users-action="close-create"]').first.click()
    page.locator("#newUserModal").wait_for(state="hidden")

    page.locator("#chip-inactive").click()
    assert "active" in page.locator("#chip-inactive").get_attribute("class")
    page.locator("#chip-all").click()
    page.locator("#userSearch").fill("no-such-user-734")
    assert page.locator('tr[data-user-id]:not(.u-hidden)').count() == 0
    page.locator("#userSearch").fill("")

    header = page.locator(".org-head, .bu-head").first
    if header.count():
        header.focus()
        page.keyboard.press("Enter")
        assert header.get_attribute("aria-expanded") == "false"
        page.keyboard.press("Enter")
        assert header.get_attribute("aria-expanded") == "true"

    page.route("**/admin/api/users/import-preview", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({
            "sheet_name": "Users", "summary": {
                "total": 1, "valid": 1, "duplicates": 0, "invalid": 0,
            },
            "bu_map": {}, "business_units": [], "warnings": [],
            "rows": [{"full_name": "Example", "email": "example@example.invalid",
                      "roles": ["Employee"], "business_unit_raw": ""}],
        }),
    ))
    page.locator("#userImportFile").set_input_files({
        "name": "users.xlsx",
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "buffer": b"fixture",
    })
    page.locator("#userImportModal.show").wait_for()
    assert page.locator("#userImportModal [onclick], #userImportModal [onchange]").count() == 0
    assert page.get_by_text("example@example.invalid").count() >= 1
    page.route("**/admin/api/users/import-commit", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({
            "created": 1, "skipped": 0, "credentials": [],
            "errors": [],
        }),
    ))
    page.locator('#userImportModal [data-users-action="commit-import"]').click()
    page.locator("#userImportModal").wait_for(state="detached")
    assert "1 created" in page.locator("#userImportResult").inner_text()

    edit = page.locator(".au-edit-btn").first
    assert edit.count()
    page.route("**/api/admin/users/*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({
            "success": True, "full_name": "Example User", "email": "example@example.invalid",
            "avatar_initials": "EU",
        }),
    ))
    edit.click()
    page.locator("#editDrawer.open").wait_for()
    page.locator("#drawerFullName").fill("Example User")
    page.locator("#drawerEmail").fill("example@example.invalid")
    page.locator('[data-users-action="save-edit"]').click()
    page.locator("#editDrawer:not(.open)").wait_for()
    assert not page.console_errors
