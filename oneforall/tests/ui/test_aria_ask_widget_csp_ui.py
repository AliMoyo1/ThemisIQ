"""The ARIA question drawer still works after its script leaves the template."""

import json


def test_aria_ask_drawer_uses_external_script(login_as, live_app):
    page = login_as("compliance_manager")
    response = page.goto(f"{live_app}/aria/risks")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in response.headers["content-security-policy"].split("style-src")[0]
    assert page.locator('script[src="/static/js/aria_base.js"]').count() == 1
    assert page.locator('[onclick], [onsubmit], [onchange]').count() == 0

    page.locator("#askFab").click()
    page.locator("#askDrawer.open").wait_for()
    assert page.locator("#askDrawerInput").is_visible()
    page.locator("#askDrawerClose").click()
    page.locator("#askDrawer").wait_for(state="hidden")
    assert page.locator("#askFab").is_visible()
    assert not page.console_errors


def test_aria_risk_and_template_dialogs_work_under_strict_csp(login_as, live_app):
    page = login_as("super_admin")
    page.route("**/aria/risks/add", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"ok":true}'))
    page.route("**/aria/api/templates", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"ok":true}'))
    response = page.goto(f"{live_app}/aria/risks")
    assert response.status == 200
    page.locator('[data-open-risk-modal]').click()
    page.locator('#addRiskModal.open').wait_for()
    page.locator('[data-close-risk-modal]').last.click()
    page.locator('#addRiskModal').wait_for(state="hidden")
    assert page.locator('[onclick], [onsubmit], [onchange]').count() == 0
    page.locator('[data-open-risk-modal]').click()
    page.locator('#addRiskForm textarea[name="description"]').fill("Synthetic risk")
    with page.expect_request("**/aria/risks/add") as risk_request:
        page.locator('#addRiskForm button[type="submit"]').click()
    assert risk_request.value.method == "POST"

    response = page.goto(f"{live_app}/aria/templates")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    page.locator('[data-open-template-modal]').click()
    page.locator('#uploadTplModal.open').wait_for()
    page.locator('[data-close-template-modal]').click()
    page.locator('#uploadTplModal').wait_for(state="hidden")
    assert page.locator('[onclick], [onsubmit], [onchange]').count() == 0
    page.locator('[data-open-template-modal]').click()
    page.locator('#tpl-name').fill("Synthetic branding")
    page.locator('#tpl-file').set_input_files({
        "name": "brand.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "buffer": b"placeholder",
    })
    with page.expect_request("**/aria/api/templates") as template_request:
        page.locator('#tplUploadForm button[type="submit"]').click()
    assert template_request.value.method == "POST"
    assert not page.console_errors


def test_aria_framework_audit_and_import_pages_load_under_strict_csp(login_as, live_app, synthetic_tenant,
                                                                      monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", True)
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [synthetic_tenant["org_id"]])
    page = login_as("compliance_manager")
    for path in ("/aria/frameworks", "/aria/audit-log", "/aria/policy-imports"):
        response = page.goto(f"{live_app}{path}")
        assert response.status == 200
        assert "script-src-attr 'none'" in response.headers["content-security-policy"]
        assert "'unsafe-inline'" not in response.headers["content-security-policy"].split("style-src")[0]
        assert page.locator('[onclick], [onsubmit], [onchange]').count() == 0
    assert page.locator('script[src^="/static/js/aria_policy_intake.js"]').count() == 1
    assert not page.console_errors


def test_ask_aria_escapes_model_list_items_and_uses_static_feedback(login_as, live_app):
    page = login_as("compliance_manager")
    answer = '- <img src=x onerror="window.attackRan=true">'
    page.route("**/aria/api/ask", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({
            "success": True, "covered": True, "answer": answer,
            "citations": [{"content_type": "document", "title": "Synthetic policy",
                           "section": "Access", "url_path": "/aria/documents/DOC-A"}],
            "chunks_retrieved": 1, "latency_ms": 15, "log_id": 42,
        })))
    feedback = []
    page.route("**/aria/api/ask/feedback", lambda route: (
        feedback.append(route.request.method), route.fulfill(
            status=200, content_type="application/json", body='{"ok":true}')))
    response = page.goto(f"{live_app}/aria/ask")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in response.headers["content-security-policy"].split("style-src")[0]
    assert page.locator('[onclick], [onsubmit], [onchange]').count() == 0
    page.locator('#chatInput').fill('What is the access rule?')
    page.locator('#chatSend').click()
    page.locator('.msg-bot .cit-card').wait_for()
    assert page.locator('.msg-bot .msg-bubble img').count() == 0
    assert '<img src=x' in page.locator('.msg-bot:has(.cit-card) .msg-bubble').inner_text()
    assert page.locator('.msg-bot .cit-card').get_attribute('href') == '/aria/documents/DOC-A'
    page.locator('.msg-bot [data-action="feedback"][data-feedback="1"]').click()
    page.wait_for_function("() => document.querySelector('.msg-bot .thumbed-up') !== null")
    assert feedback == ["POST"]
    assert not page.evaluate('window.attackRan === true')
    assert not page.console_errors


def test_aria_dashboard_charts_and_report_action_work_under_strict_csp(login_as, live_app):
    page = login_as("super_admin")
    page.route("**/api/reports/quick-run", lambda route: route.fulfill(
        status=422, content_type="application/json", body='{"error":"Synthetic refusal"}'))
    response = page.goto(f"{live_app}/aria/")
    assert response.status == 200
    assert "script-src-attr 'none'" in response.headers["content-security-policy"]
    assert "'unsafe-inline'" not in response.headers["content-security-policy"].split("style-src")[0]
    assert page.locator('[onclick], [onsubmit], [onchange]').count() == 0
    assert page.locator('script[src="/static/js/aria_dashboard.js"]').count() == 1
    assert page.locator('#ariaArcImpl').count() == 1
    with page.expect_request("**/api/reports/quick-run") as report_request:
        page.locator('#ariaGenerateReport').click()
    assert report_request.value.method == "POST"
    assert not page.console_errors
