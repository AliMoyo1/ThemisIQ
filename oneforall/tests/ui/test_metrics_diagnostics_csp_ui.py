"""Operational read-only pages render under strict scripts and escape links."""

import json


def test_metrics_definitions_render_under_strict_scripts(login_as, live_app):
    page = login_as("compliance_manager")
    page.route("**/api/metrics/definitions", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"definitions": [{
            "key": "cc.work", "label": "Open work", "definition": "Visible tasks",
            "eligibility": "Open tasks", "denominator": "All tasks", "window": "Current",
            "scope": "Your organization", "ownership": "organization", "refresh": "Live",
            "exclusions": "Closed", "drilldown": "/my-work", "exact": True,
        }]})))
    response = page.goto(f"{live_app}/metrics")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    page.locator(".metrics-card").filter(has_text="Open work").wait_for()
    assert page.locator('.metrics-card a[href="/my-work"]').count() == 1
    assert not page.console_errors


def test_diagnostics_escapes_source_supplied_link_and_state(login_as, live_app):
    page = login_as("super_admin")
    page.route("**/api/admin/diagnostics", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({
            "database": {"state": 'available" onmouseover="alert(1)',
                         "message": "Healthy", "remediation_route": '/help?x=" onmouseover="alert(1)'},
            "ai": {"state": "not_configured"}, "email": {"state": "not_configured"},
            "licensed_modules": [],
        })))
    response = page.goto(f"{live_app}/admin/diagnostics")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    page.locator("#diagOrgGrid .diag-card").first.wait_for()
    assert page.locator("#diagOrgGrid [onmouseover]").count() == 0
    assert page.locator("#diagOrgGrid .diag-badge-not_configured").count() >= 1
    assert page.locator("#diagOrgGrid a").first.get_attribute("href") == '/help?x=" onmouseover="alert(1)'
    assert not page.console_errors
