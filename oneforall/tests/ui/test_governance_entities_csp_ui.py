"""Governance's entity browser works under strict script CSP."""

import json


def test_governance_entity_tabs_modals_and_control_edit_under_strict_csp(login_as, live_app):
    page = login_as("super_admin")
    saves = []
    payload = [{
        "id": 42, "ref": "A.1", "title": '<img src=x onerror="window.injected=1">',
        "description": "Example", "owner_name": "Owner", "automation": "manual",
        "last_tested_at": "2026-10-01", "score": 75,
        "scored_at": "2026-10-02", "is_active": 1,
        "test_frequency_days": 90, "p2st2_category": "Process",
        "business_unit_id": None,
    }]

    def controls(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    def save(route):
        saves.append((route.request.method, route.request.post_data_json))
        route.fulfill(status=200, content_type="application/json", body='{}')

    page.route("**/governance/api/controls", controls)
    page.route("**/governance/api/controls/42", save)
    response = page.goto(f"{live_app}/governance/")
    assert response.status == 200
    script_policy = response.headers["content-security-policy"].split("script-src ", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script_policy
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert page.locator('script[src="/static/js/governance_entities.js"]').count() == 1
    assert page.locator("script:not([src]), [onclick], [onchange], [oninput]").count() == 0

    page.locator('[data-gov-action="open-add"]').click()
    page.locator("#govModal #bu_name").wait_for()
    page.locator('#govModal [data-gov-action="close-modal"]').first.click()
    assert page.locator("#govModal .modal-overlay").count() == 0

    page.locator('.gov-tab[data-tab="ctrl"]').click()
    page.locator('#ctrlTBody [data-gov-action="edit-ctrl"]').wait_for()
    assert page.locator("#ctrlTBody img").count() == 0
    assert page.evaluate("window.injected === 1") is False
    page.locator('#ctrlTBody [data-gov-action="edit-ctrl"]').click()
    page.locator("#govModal #ctrl_title").wait_for()
    assert page.locator("#govModal img").count() == 0
    page.locator("#ctrl_title").fill("Revised control")
    page.locator('#govModal [data-gov-action="save-ctrl"]').click()
    page.wait_for_function("() => !document.querySelector('#govModal .modal-overlay')")
    assert saves and saves[0][0] == "PUT"
    assert saves[0][1]["title"] == "Revised control"
    assert not page.console_errors
