"""Framework administration remains usable when inline scripts are refused."""

import database


def test_framework_admin_actions_under_strict_scripts(login_as, live_app):
    page = login_as("super_admin")
    seed_requests = []

    def seed_response(route):
        seed_requests.append(route.request.method)
        route.fulfill(status=200, content_type="application/json", body='{"seeded":0}')

    page.route("**/admin/api/frameworks/seed-controls", seed_response)
    response = page.goto(f"{live_app}/admin/frameworks")
    script_policy = response.headers["content-security-policy"].split("script-src ", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script_policy
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert page.locator("script:not([src])").count() == 0
    assert page.locator("[onclick], [onchange], [onsubmit], [onmouseenter], [onmouseleave]").count() == 0

    page.get_by_role("button", name="Seed Controls").click()
    page.wait_for_function("() => document.querySelector('.ofa-toast')?.textContent.includes('Seeded 0 controls')")
    assert seed_requests == ["POST"]

    invalid_color = page.request.post(f"{live_app}/admin/api/frameworks", data={
        "name": "Rejected style injection",
        "description": "CSP regression",
        "color": "#112233; background: url(https://example.invalid/track)",
        "relevant_modules": "aria",
    })
    assert invalid_color.status == 400

    page.get_by_role("button", name="+ Custom Framework").click()
    assert page.locator("#newFwModal").is_visible()
    page.get_by_role("button", name="Cancel").click()
    assert not page.locator("#newFwModal").is_visible()
    assert not page.console_errors


def test_legacy_framework_color_is_inert_across_pages(login_as, live_app):
    unsafe = "#112233; background:url(https://example.invalid/track)"
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO frameworks (name, color, is_active) VALUES (%s, %s, 1)",
            ("Stored color in browser", unsafe),
        )
        db.commit()
        fw_id = db.execute(
            "SELECT id FROM frameworks WHERE name=%s", ("Stored color in browser",)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO controls (framework_id, ref, name) VALUES (%s, %s, %s)",
            (fw_id, "SAFE-1", "One control"),
        )
        db.commit()
    finally:
        db.close()

    page = login_as("super_admin")
    for path in ("/admin/frameworks", "/projects", "/aria/", "/aria/frameworks", f"/aria/framework/{fw_id}"):
        response = page.request.get(f"{live_app}{path}")
        assert response.status == 200, path
        markup = response.text()
        assert unsafe not in markup, path
    items = page.request.get(f"{live_app}/aria/api/frameworks").json()["items"]
    assert next(item for item in items if item["id"] == fw_id)["color"] == "#1E3A5F"
