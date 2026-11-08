"""Calendar navigation and event actions work without inline script attributes."""

import json
from datetime import datetime


def test_calendar_actions_under_strict_script_policy(login_as, live_app):
    page = login_as("compliance_manager")
    date = datetime.now().strftime("%Y-%m-%d")
    event = {
        "id": 17, "title": "<svg/onload=alert(1)>", "event_type": "review",
        "module": "aria", "start_date": date, "end_date": None,
        "status": "scheduled", "description": "Review the control",
        "entity_type": "control", "entity_id": "<img src=x onerror=alert(1)>",
    }
    saved = []
    page.route("**/api/calendar/events?*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps([event])))
    page.route("**/api/calendar/events", lambda route: (
        saved.append(json.loads(route.request.post_data)),
        route.fulfill(status=200, content_type="application/json", body='{"id":18}')))

    response = page.goto(f"{live_app}/calendar")
    assert response.status == 200
    policy = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in policy
    assert "'unsafe-inline'" not in policy.split("style-src")[0]
    assert page.locator('script:not([src]), [onclick], [onchange], [onsubmit], [onkeydown]').count() == 0
    assert page.locator('script[src="/static/js/calendar.js"]').count() == 1

    pill = page.locator('.cal-pill[data-event-id="17"]').first
    pill.wait_for()
    assert pill.inner_text() == event["title"]
    assert page.locator("svg[onload], img[onerror]").count() == 0
    pill.click()
    page.locator("#evDrawer.open").wait_for()
    assert event["entity_id"] in page.locator("#drawerBody").inner_text()
    assert page.locator("#drawerBody img").count() == 0
    page.locator("#calCloseDrawer").click()

    page.locator("#viewList").click()
    row = page.locator('.ev-list-row[data-event-id="17"]')
    row.wait_for()
    row.focus()
    row.press("Enter")
    page.locator("#evDrawer.open").wait_for()
    page.locator("#calCloseDrawer").click()

    page.locator("#calAddEvent").click()
    page.locator("#eventModal.open").wait_for()
    page.locator("#efTitle").fill("Quarterly review")
    page.locator("#efStart").fill(date)
    with page.expect_request("**/api/calendar/events"):
        page.locator("#efSubmitBtn").click()
    page.locator("#eventModal").wait_for(state="hidden")
    assert saved and saved[0]["title"] == "Quarterly review"
    assert not page.console_errors
