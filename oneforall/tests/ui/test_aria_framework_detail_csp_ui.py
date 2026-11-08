"""The ARIA control detail page works when executable inline code is refused."""

import database


def test_aria_framework_detail_controls_under_strict_csp(login_as, live_app):
    db = database.get_db()
    try:
        framework = database.insert_returning_id(
            db, "INSERT INTO frameworks (name, color, is_active) VALUES (%s, %s, 1)",
            ("Browser control detail", "#234567"),
        )
        database.insert_returning_id(
            db, "INSERT INTO controls (framework_id, ref, name, status) VALUES (%s, %s, %s, %s)",
            (framework, "CSP-1", "Browser control", "Not Started"),
        )
        db.commit()
    finally:
        db.close()

    page = login_as("super_admin")
    updates = []

    def accept_update(route):
        updates.append(route.request.post_data)
        route.fulfill(status=200, content_type="application/json", body='{"ok":true}')

    page.route("**/aria/control/*/update", accept_update)
    response = page.goto(f"{live_app}/aria/framework/{framework}")
    assert response.status == 200
    policy = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in policy
    assert "'unsafe-inline'" not in policy.split("style-src")[0]
    assert page.locator('script:not([src]), [onclick], [onchange], [onblur], [onkeydown]').count() == 0
    assert page.locator('script[src="/static/js/aria_framework_detail.js"]').count() == 1
    assert page.locator('script[src*="chart.js"]').count() == 0

    with page.expect_request("**/aria/control/*/update"):
        page.locator(".js-control-status").select_option("Implemented")
    page.locator(".js-edit-control").click()
    assert page.locator("#editModal").is_visible()
    page.locator("#editNotes").fill("Reviewed locally")
    with page.expect_request("**/aria/control/*/update"):
        page.locator("#saveControlModal").click()
    page.locator("#editModal").wait_for(state="hidden")
    assert len(updates) == 2

    page.locator("#statusFilter").select_option("Implemented")
    page.wait_for_url("**/aria/framework/*?status=Implemented")
    assert not page.console_errors
