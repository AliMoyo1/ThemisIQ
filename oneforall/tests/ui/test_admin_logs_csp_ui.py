"""Audit log filters and escaping work with the strict script policy."""

import json


def test_audit_log_filters_and_escaping_under_strict_scripts(login_as, live_app):
    page = login_as("super_admin")
    queries = []

    def logs(route):
        queries.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "page": 1, "pages": 1, "total": 1, "modules": ["platform"],
            "logs": [{"created_at": "2026-11-06T10:00:00", "full_name": "Reviewer",
                      "module": "platform", "action": "edit", "details": 'sample" onmouseover="alert(1)',
                      "ip_address": "127.0.0.1"}],
        }))

    page.route("**/admin/api/logs?**", logs)
    response = page.goto(f"{live_app}/admin/logs")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert page.locator('script[src="/static/js/admin_logs.js"]').count() == 1
    assert page.locator("[onclick], [onchange], [onsubmit]").count() == 0
    page.locator("#logBody tr").first.wait_for()
    assert page.locator("#logBody [onmouseover]").count() == 0
    assert page.locator("#logBody td[title]").first.get_attribute("title") == 'sample" onmouseover="alert(1)'
    page.get_by_role("button", name="Login Failures").click()
    page.wait_for_function("() => document.querySelector('#filterAction').value === 'login_failed'")
    assert any("action=login_failed" in url for url in queries)
    assert not page.console_errors
