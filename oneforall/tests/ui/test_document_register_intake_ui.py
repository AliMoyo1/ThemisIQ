"""A workbook can be reviewed in Governance without declaring its claims approved."""
from tests.test_document_register_intake import _book


def test_document_register_preview_and_queue(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/aria/policy-imports")
    page.get_by_role("heading", name="Reconcile a document control register").wait_for()
    page.set_input_files("#doc-register-file", files={"name": "IMS-OMNI-R029 v4.1.xlsx",
                                                 "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                                 "buffer": _book()})
    page.locator("#doc-register-form button[type=submit]").click()
    page.wait_for_selector("#doc-register-preview:not([hidden])")
    assert "2 rows" in page.locator("#doc-register-summary").inner_text()
    assert "version conflict" in page.locator("#doc-register-warnings").inner_text()
    page.locator("#doc-register-ack").check()
    page.locator("#doc-register-confirm").click()
    page.locator("#doc-register-preview").wait_for(state="hidden")
    assert "2 claims queued" in page.locator("#doc-register-status").inner_text()
