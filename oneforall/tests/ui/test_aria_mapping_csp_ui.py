"""ARIA mapping actions work without executable inline attributes."""

import json


def test_mapping_review_and_existing_view_under_strict_csp(login_as, live_app):
    page = login_as("super_admin")
    proposal = {
        "id": 17, "mapping_type": "proposed", "created_by": 999,
        "source_ref": "A-1", "source_name": "Source control",
        "target_ref": "B-1", "target_name": "Target control",
        "confidence": 0.8, "notes": '{"suggested_type":"equivalent","method":"text"}',
    }
    reviewed = []

    page.route("**/aria/api/control-mappings", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"items": [proposal]})))
    page.route("**/aria/api/control-mappings/17/review", lambda route: (
        reviewed.append(json.loads(route.request.post_data)),
        route.fulfill(status=200, content_type="application/json", body='{"ok":true}')))
    page.route("**/aria/api/control-mappings/ims-status?*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"stats":{"total":0},"integrated":[],"partial":[],"unique":[]}'))

    response = page.goto(f"{live_app}/aria/mapping")
    assert response.status == 200
    policy = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in policy
    assert "'unsafe-inline'" not in policy.split("style-src")[0]
    assert page.locator('script:not([src]), [onclick], [onchange], [onkeydown]').count() == 0
    assert page.locator('script[src="/static/js/aria_mapping.js"]').count() == 1
    assert page.locator('script[src*="chart.js"]').count() == 0

    reason = page.locator("#mapping-reason-17")
    reason.wait_for()
    reason.fill("Reviewed the matching source controls")
    with page.expect_request("**/aria/api/control-mappings/17/review"):
        page.locator('.js-review-mapping[data-decision="accept"]').click()
    assert reviewed and reviewed[0]["decision"] == "accept"

    selector = page.locator("#fwSelector")
    options = selector.locator("option")
    assert options.count() >= 2
    selector.select_option([options.nth(0).get_attribute("value"), options.nth(1).get_attribute("value")])
    page.locator("#viewExistingMappings").click()
    page.locator("#statsStrip").wait_for(state="visible")
    assert not page.console_errors
