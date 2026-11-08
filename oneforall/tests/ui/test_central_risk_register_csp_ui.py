"""The central risk list paginates safely with inline handlers disabled."""

import json
import re
from urllib.parse import parse_qs, urlsplit


def test_central_risk_register_paging_under_strict_scripts(login_as, live_app):
    page = login_as("super_admin")
    requested_pages = []

    def risks_response(route):
        number = int(parse_qs(urlsplit(route.request.url).query).get("page", ["1"])[0])
        requested_pages.append(number)
        title = '<img src=x onerror="window.riskInjected=1">' if number == 1 else "Second risk"
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "page": number, "pages": 2, "total": 2,
            "items": [{"title": title, "category": "test", "risk_level": "high",
                       "risk_score": 16, "source_module": "erm", "treatment": "Review",
                       "owner_name": "Test owner", "status": "open"}],
        }))

    page.route(re.compile(r"/api/risks\?"), risks_response)
    page.route("**/api/risks/stats", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"total":2,"by_level":{"high":2},"heat_map":[]}',
    ))
    response = page.goto(f"{live_app}/risk-register")
    script_policy = response.headers["content-security-policy"].split("script-src ", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script_policy
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert page.locator("script:not([src]), [onclick], [onchange], [onsubmit]").count() == 0
    page.wait_for_function("() => document.querySelector('#riskBody')?.textContent.includes('onerror')")
    assert page.locator("#riskBody img").count() == 0
    assert page.evaluate("() => window.riskInjected || 0") == 0
    page.locator("#riskPager button", has_text="Next").click()
    page.wait_for_function("() => document.querySelector('#riskBody')?.textContent.includes('Second risk')")
    assert requested_pages[:2] == [1, 2]
    page.locator("#riskPager button", has_text="Previous").click()
    page.wait_for_function("() => document.querySelector('#riskBody')?.textContent.includes('onerror')")
    page.locator("#openNewRiskBtn").click()
    assert page.locator("#newRiskModal").is_visible()
    page.locator("#closeNewRiskBtn").click()
    assert not page.locator("#newRiskModal").is_visible()
    assert not page.console_errors
