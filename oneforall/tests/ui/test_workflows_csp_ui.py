"""Workflow authoring still works with executable inline HTML disabled."""

import json


def test_workflow_tabs_and_authoring_modal_under_strict_csp(login_as, live_app):
    page = login_as("super_admin")
    submitted = []

    def definitions(route):
        if route.request.method == "POST":
            submitted.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="application/json", body='{"id": 91}')
        else:
            route.fulfill(status=200, content_type="application/json", body=json.dumps([]))

    page.route("**/api/workflows/definitions", definitions)
    response = page.goto(f"{live_app}/workflows")
    assert response.status == 200
    script_policy = response.headers["content-security-policy"].split("script-src ", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script_policy
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert page.locator('script[src="/static/js/workflows.js"]').count() == 1
    assert page.locator("script:not([src]), [onclick], [onchange], [oninput], [onsubmit]").count() == 0

    page.locator('[data-wf-action="new-def"]').click()
    page.locator("#wfDefForm").wait_for()
    assert page.locator("#wfModalRoot [onclick], #wfModalRoot [onsubmit]").count() == 0
    assert page.locator("#stepBuilder .step-item").count() == 2
    page.locator('#stepBuilder [data-wf-action="remove-step"]').first.click()
    assert page.locator("#stepBuilder .step-item").count() == 1
    page.locator('#wfDefForm [data-wf-action="add-step"]').click()
    assert page.locator("#stepBuilder .step-item").count() == 2
    page.locator("#wfName").fill("Example approval")
    page.locator('#stepBuilder [data-field="label"]').first.fill("Review")
    page.locator('#wfDefForm button[type="submit"]').click()
    page.wait_for_function("() => !document.querySelector('#wfModalRoot .modal-overlay')")
    assert submitted and submitted[0]["name"] == "Example approval"
    assert submitted[0]["steps"][0]["label"] == "Review"

    page.locator('[data-wf-tab="sla"]').click()
    assert "active" in page.locator("#panel-sla").get_attribute("class")
    page.locator('[data-sla-tab="inst"]').click()
    page.locator('[data-sla-filter="breached"]').click()
    page.locator('[data-wf-tab="comms"]').click()
    page.locator('[data-wf-action="new-comm"]').click()
    page.locator('#wfModalRoot [data-wf-submit="comm"]').wait_for()
    assert "{{item_name}}" in page.locator("#commSubj").get_attribute("placeholder")
    page.locator('#wfModalRoot [data-wf-action="close-modal"]').click()
    assert not page.console_errors
