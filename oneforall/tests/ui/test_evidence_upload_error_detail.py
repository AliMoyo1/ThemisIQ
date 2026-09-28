"""
PLAN-36 T06 (findings.md F08): evidence_index.html's handleUpload() had two
paths that needed structured/typed error handling, migrated onto
ApiClient.request: the 409 duplicate-file case (needs existing_id/
existing_title out of the body, not just a message -- the reason
ApiError gained a .body field) and every other failure status, which
previously did nothing at all (no else branch after `if(r.ok){...}`).
"""
import io


def _open_upload_modal(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/evidence")
    page.wait_for_selector("button:has-text('+ Upload')")
    page.click("button:has-text('+ Upload')")
    page.wait_for_selector("#uploadModal.open")
    page.set_input_files("#uploadFile", files=[
        {"name": "policy.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 test"}
    ])
    return page


def test_duplicate_upload_shows_the_existing_item_with_working_actions(login_as, live_app):
    page = _open_upload_modal(login_as, live_app)
    page.route("**/evidence/api/items", lambda r: (
        r.fulfill(status=409, content_type="application/json",
                   body='{"detail": "Duplicate file", "existing_id": 42, "existing_title": "Security Policy.pdf"}')
        if r.request.method == "POST" else r.continue_()
    ))
    page.click("button:has-text('Upload Evidence')")
    page.wait_for_selector("#uploadDupeWarning", state="visible", timeout=5000)
    warning_text = page.locator("#uploadDupeWarning").inner_text()
    assert "Security Policy.pdf" in warning_text
    assert page.locator("#uploadDupeWarning button:has-text('View Existing')").count() == 1
    assert page.locator("#uploadDupeWarning button:has-text('Link Existing')").count() == 1
    # the modal must still be open -- this is a recoverable state, not a dead end
    assert "open" in (page.locator("#uploadModal").get_attribute("class") or "")


def test_other_upload_failures_now_show_a_toast_instead_of_doing_nothing(login_as, live_app):
    """Before this migration: any non-409, non-ok response fell through
    every branch silently -- the button just... stopped, with no feedback."""
    page = _open_upload_modal(login_as, live_app)
    page.route("**/evidence/api/items", lambda r: (
        r.fulfill(status=413, content_type="application/json", body='{"detail": "File too large."}')
        if r.request.method == "POST" else r.continue_()
    ))
    page.click("button:has-text('Upload Evidence')")
    page.wait_for_selector(".toast-error", timeout=5000)
    assert "File too large." in page.locator(".toast-error").inner_text()


def test_successful_upload_closes_the_modal_and_shows_success_toast(login_as, live_app):
    page = _open_upload_modal(login_as, live_app)
    page.route("**/evidence/api/items", lambda r: (
        r.fulfill(status=200, content_type="application/json", body='{"ok": true, "id": 99}')
        if r.request.method == "POST" else r.continue_()
    ))
    page.route("**/evidence/api/stats", lambda r: r.fulfill(
        status=200, content_type="application/json", body='{}'))
    page.route("**/evidence/api/items?**", lambda r: r.fulfill(
        status=200, content_type="application/json", body='{"items": [], "total": 0}'))
    page.click("button:has-text('Upload Evidence')")
    page.wait_for_selector(".toast-success", timeout=5000)
    assert "uploaded" in page.locator(".toast-success").inner_text().lower()
    page.wait_for_selector("#uploadModal", state="hidden", timeout=5000)
