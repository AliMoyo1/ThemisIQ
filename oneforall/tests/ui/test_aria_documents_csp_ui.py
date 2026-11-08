"""ARIA Document Register's core controls work under a strict script policy."""


def test_document_register_add_and_review_controls_under_strict_csp(login_as, live_app):
    page = login_as("super_admin")
    response = page.goto(f"{live_app}/aria/documents")
    assert response.status == 200
    csp = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("style-src")[0]
    assert page.locator('script[src="/static/js/aria_documents.js"]').count() == 1
    assert page.locator("[onclick], [onchange], [oninput], [ondrop], [ondragover]").count() == 0

    page.locator('[data-doc-action="open-add"]').first.click()
    page.locator("#addModal.open").wait_for()
    page.locator("#add-effective-date").fill("2026-11-07")
    page.locator("#add-review-cycle").select_option("90")
    assert page.locator("#add-review-date").input_value() == "2027-02-05"
    page.locator('#addModal [data-doc-close="addModal"]').first.click()
    page.locator("#addModal.open").wait_for(state="hidden")
    assert not page.console_errors
