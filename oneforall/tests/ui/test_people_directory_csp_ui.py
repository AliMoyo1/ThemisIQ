"""People Directory actions and profile details stay safe under strict scripts."""

import json


def test_people_directory_actions_under_strict_script_policy(login_as, live_app):
    page = login_as("super_admin")
    person = {
        "id": 17, "full_name": "Alex <svg/onload=alert(1)>",
        "email": "alex@example.invalid", "phone": "<img src=x onerror=alert(1)>",
        "job_title": "Analyst", "department": "Risk", "is_active": True,
    }
    profile = {
        **person, "notes": "<svg/onload=alert(1)>",
        "tasks": [{"title": "Review", "status": 'open" onmouseover="alert(1)'}],
        "risks": [],
    }
    page.route("**/api/people", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"items": [person], "departments": ["Risk"], "total": 1})))
    page.route("**/api/people/17/profile", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(profile)))

    response = page.goto(f"{live_app}/people")
    assert response.status == 200
    policy = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in policy
    assert "'unsafe-inline'" not in policy.split("style-src")[0]
    assert page.locator('script:not([src]), [onclick], [onchange], [oninput], [onkeydown]').count() == 0
    assert page.locator('script[src="/static/js/people_directory.js"]').count() == 1
    card = page.locator('.pd-card[data-person-id="17"]')
    card.wait_for()
    assert person["full_name"] in card.inner_text()
    assert page.locator("svg[onload], img[onerror]").count() == 0

    card.focus()
    card.press("Enter")
    page.locator("#pdDrawer.open").wait_for()
    assert person["phone"] in page.locator("#ddBody").inner_text()
    assert page.locator("#ddBody img, #ddBody svg[onload], #ddBody [onmouseover]").count() == 0
    page.locator('[data-person-action="edit"]').click()
    page.locator("#pdAddModal.open").wait_for()
    assert page.locator("#fName").input_value() == person["full_name"]
    page.locator("#pdCancelAdd").click()
    page.locator("#pdCloseDrawer").click()

    page.locator("#pdOpenImport").click()
    page.locator("#pdImportModal.open").wait_for()
    page.locator("#pdCancelImport").click()
    page.locator("#pdOpenAdd").click()
    page.locator("#pdAddModal.open").wait_for()
    assert page.locator("#fName").input_value() == ""
    assert not page.console_errors
