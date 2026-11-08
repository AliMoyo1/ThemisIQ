"""Vendor cards, profile and add flow work with strict script policy."""

import json


def test_vendor_directory_actions_under_strict_script_policy(login_as, live_app):
    page = login_as("super_admin")
    vendor = {
        "id": 17, "name": "Supplier <svg/onload=alert(1)>",
        "services": "Hosting", "coverage": 1,
        "risk_flag": 'high" onmouseover="alert(1)',
        "sentinel": {"id": 8, "dpa_status": "expired"},
        "grid": None, "bcm": None,
    }
    profile = {
        "canonical": {"id": 17, "name": vendor["name"], "services": "Hosting"},
        "modules": {"sentinel": {
            "id": 8, "dpa_status": "<img src=x onerror=alert(1)>",
            "type": "processor", "risk_level": "high",
        }, "grid": None, "bcm": None},
        "flags": [{"msg": "Review contract"}],
    }
    saved = []
    registered = []

    def directory_response(route):
        if route.request.method == "POST":
            saved.append(json.loads(route.request.post_data))
            route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"items": [vendor]}))

    page.route("**/api/vendors/directory", directory_response)
    page.route("**/api/vendors/17/profile", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(profile)))
    page.route("**/grid/api/vendors", lambda route: (
        registered.append(json.loads(route.request.post_data)),
        route.fulfill(status=200, content_type="application/json", body='{"ok":true}')))
    response = page.goto(f"{live_app}/vendors")
    assert response.status == 200
    policy = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in policy
    assert "'unsafe-inline'" not in policy.split("style-src")[0]
    assert page.locator('script:not([src]), [onclick], [onchange], [oninput], [onsubmit]').count() == 0
    assert page.locator('script[src="/static/js/vendor_directory.js"]').count() == 1

    card = page.locator('.vd-card[data-vendor-id="17"]')
    card.wait_for()
    assert vendor["name"] in card.inner_text()
    assert page.locator("#vdGrid [onmouseover], #vdGrid svg[onload]").count() == 0
    card.focus()
    card.press("Enter")
    drawer = page.locator("#vdDrawerOverlay.open")
    drawer.wait_for()
    assert profile["modules"]["sentinel"]["dpa_status"] in drawer.inner_text()
    assert page.locator("#vdDrawer img[onerror], #vdDrawer [onclick]").count() == 0
    with page.expect_request("**/grid/api/vendors"):
        page.locator('[data-vendor-action="register"][data-module="grid"]').click()
    assert registered and registered[0]["canonical_id"] == 17
    page.locator("#vdDrawer .vd-drawer-close").click()

    page.locator("#vdSearch").fill("not present")
    page.locator(".vd-empty").wait_for()
    page.locator("#vdSearch").fill("")
    page.locator(".vd-card").wait_for()
    page.locator("#vdOpenAdd").click()
    page.locator("#vdAddForm").wait_for()
    page.locator('#vdAddForm input[name="name"]').fill("New Supplier")
    with page.expect_request("**/api/vendors/directory"):
        page.locator('#vdAddForm button[type="submit"]').click()
    page.locator("#vdAddForm").wait_for(state="detached")
    assert saved and saved[0]["name"] == "New Supplier"
    assert not page.console_errors
