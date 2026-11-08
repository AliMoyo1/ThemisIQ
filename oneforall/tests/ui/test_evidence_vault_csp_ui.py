"""Vault controls still work when inline scripts and HTML handlers are blocked."""

import json

import database


def test_vault_drawer_and_filters_under_strict_csp(live_app, page, login_as, synthetic_tenant):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO evidence_items (title, category, uploaded_by, org_id) VALUES (%s, %s, %s, %s)",
            (
                "Vault CSP probe",
                "general",
                synthetic_tenant["users"]["compliance_manager"]["user_id"],
                synthetic_tenant["org_id"],
            ),
        )
        db.commit()
        item_id = db.execute(
            "SELECT id FROM evidence_items WHERE title='Vault CSP probe'"
        ).fetchone()["id"]
    finally:
        db.close()

    saved = []

    def intercept_update(route):
        if route.request.method == "PUT":
            saved.append(json.loads(route.request.post_data))
            route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
        else:
            route.continue_()

    page.route(f"**/evidence/api/items/{item_id}", intercept_update)
    login_as("compliance_manager")
    response = page.goto(f"{live_app}/evidence/")
    csp = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("style-src")[0]
    assert page.locator("[onclick], [onchange], [oninput], [onkeyup], [onsubmit]").count() == 0

    page.get_by_role("button", name="Find evidence").click()
    page.locator("#findModal.open").wait_for()
    page.locator("#findModal .modal-close").click()
    page.locator("#findModal.open").wait_for(state="hidden")
    page.get_by_role("button", name="+ Upload").click()
    page.locator("#uploadModal.open").wait_for()
    page.locator("#uploadModal .modal-close").click()

    page.locator(f"#evidenceTableBody tr[data-ev-dynamic='openDetail({item_id})']").click()
    drawer = page.locator("#evDetailPanel.open")
    drawer.wait_for()
    assert drawer.locator("[onclick], [onchange]").count() == 0
    drawer.get_by_role("tab", name="Versions").click()
    assert drawer.locator("#tab-history").get_attribute("aria-selected") == "true"
    drawer.get_by_role("tab", name="Details").click()
    drawer.get_by_role("button", name="Edit category").click()
    with page.expect_response(lambda response: response.request.method == "PUT" and
                              response.url.endswith(f"/evidence/api/items/{item_id}")):
        drawer.locator("#ev-input-category").select_option("report")
    assert {"category": "report"} in saved

    drawer.locator("#ev-input-category").wait_for(state="detached")
    drawer.get_by_role("button", name="Edit title").click()
    drawer.locator("#ev-input-title").fill("Vault CSP edited")
    with page.expect_response(lambda response: response.request.method == "PUT" and
                              response.url.endswith(f"/evidence/api/items/{item_id}")):
        drawer.locator("#ev-field-title button[data-ev-dynamic^='evSaveField']").click()
    assert {"title": "Vault CSP edited"} in saved
