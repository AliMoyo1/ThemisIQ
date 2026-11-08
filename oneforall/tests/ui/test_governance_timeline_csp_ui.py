"""Timeline filters and event rendering under the strict script policy."""

import json


def test_timeline_filters_and_load_more_without_executable_event_markup(login_as, live_app):
    page = login_as("super_admin")
    requests = []

    def timeline(route):
        requests.append(route.request.url)
        second = "page=2" in route.request.url
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "page": 2 if second else 1, "pages": 2, "total": 2, "modules": ["aria"],
            "events": [{"created_at": "2026-11-06 09:00:00", "module": "aria",
                        "color": '#123456" onmouseover="window.timelinePwned=1',
                        "label": "Second event" if second else '<img src=x onerror="window.timelinePwned=1">',
                        "username": "Reviewer", "entity_type_label": "Policy",
                        "entity_id": '1" onclick="window.timelinePwned=1',
                        "details": '<script>window.timelinePwned=1</script>'}],
        }))

    page.route("**/api/timeline?**", timeline)
    response = page.goto(f"{live_app}/timeline")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert page.locator('script[src="/static/js/governance_timeline.js"]').count() == 1
    page.locator(".tl-event").first.wait_for()
    assert page.locator(".tl-event img, .tl-event script, .tl-event [onclick], .tl-event [onmouseover]").count() == 0
    assert page.locator(".tl-dot").first.evaluate("el => el.style.backgroundColor") == "rgb(100, 116, 139)"
    assert page.evaluate("window.timelinePwned || 0") == 0
    page.get_by_role("button", name="Load more").click()
    page.get_by_text("Second event").wait_for()
    assert any("page=2" in url for url in requests)
    page.locator('.tl-chip[data-days="30"]').click()
    assert any("days=30" in url for url in requests)
    assert not page.console_errors
