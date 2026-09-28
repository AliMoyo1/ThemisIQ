"""
PLAN-36 T01 (findings.md F01): managed ARIA metadata editing, real browser.

Covers the part no HTTP-level test can: that the *client* only ever sends
the permitted metadata fields for a managed document, that the lifecycle
fields render as read-only text (not disabled inputs sitting in the save
form), and that the Save button is labelled correctly. The server-side
contract (permitted fields succeed, any lifecycle field 409s, pending
approval locks metadata, legacy documents are unaffected, out-of-scope is
404) is already covered at the HTTP layer by tests/test_aria_policy_legacy.py
and is not repeated here.
"""
import database


def _seed_document(org_id: int, business_unit_id: int, owner_user_id: int,
                    doc_id: str, managed: int) -> str:
    """One Approved document with a distinct status/version/owner/approver,
    so an accidental lifecycle-field save would be obviously visible in the
    assertions below."""
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO aria_documents "
            "(doc_id, framework, control_ref, title, version, status, body, "
            "org_id, business_unit_id, owner_user_id, policy_workflow_managed, "
            "owner, approver) "
            "VALUES (%s,'ISO 27001','A.1','Original Title','2.1','Approved','body',"
            "%s,%s,%s,%s,'Original Owner','Original Approver')",
            (doc_id, org_id, business_unit_id, owner_user_id, managed),
        )
        db.commit()
    finally:
        db.close()
    return doc_id


def _seed_managed_document(org_id: int, business_unit_id: int, owner_user_id: int) -> str:
    return _seed_document(org_id, business_unit_id, owner_user_id, "DOC-UIHARNESS-01", managed=1)


def _wait_for_save_and_reload(page):
    """submitEdit() shows a success toast immediately, then reloads the
    page 900ms later (documents.html). Waiting on network-idle alone races
    that timer -- it can resolve right after the save POST, before the
    reload has even started. Wait for the toast (proves the save actually
    succeeded), then past the hardcoded delay, then for the reload itself.

    Returns a snapshot of page.console_errors taken right after the toast,
    before the reload's teardown window -- a background poll racing
    location.reload() (base_shell.html; unrelated to this document's save
    logic, and observed only under heavy full-suite load, never in this
    file's own isolated runs) is not something this test is responsible
    for; what it must prove error-free is opening the modal and saving."""
    page.wait_for_selector(".toast-success", timeout=5000)
    errors_before_reload = list(page.console_errors)
    page.wait_for_timeout(1100)
    page.wait_for_load_state("load")
    return errors_before_reload


def test_managed_document_edit_sends_metadata_only_and_preserves_lifecycle(
    login_as, live_app, synthetic_tenant,
):
    actor = synthetic_tenant["users"]["compliance_manager"]
    doc_id = _seed_managed_document(
        synthetic_tenant["org_id"], synthetic_tenant["business_unit_id"], actor["user_id"],
    )

    page = login_as("compliance_manager")
    page.goto(f"{live_app}/aria/documents")
    page.click(f"#row-{doc_id} .edit-btn")
    page.wait_for_selector("#editModal.open", timeout=5000)

    # Lifecycle fields are shown, but as read-only text -- never as part of
    # the editable form -- and the managed label is on the button.
    assert page.locator("#edit-legacy-lifecycle-fields").is_hidden()
    assert page.locator("#edit-lifecycle-status").inner_text() == "Approved"
    assert page.locator("#edit-lifecycle-version").inner_text() == "2.1"
    assert page.locator("#edit-lifecycle-owner").inner_text() == "Original Owner"
    assert page.locator("#edit-lifecycle-approver").inner_text() == "Original Approver"
    assert page.locator("#edit-save-btn").inner_text() == "Save metadata"

    page.fill("#edit-title", "Renamed Via Metadata Save")
    page.click("#edit-save-btn")
    errors = _wait_for_save_and_reload(page)

    db = database.get_db()
    try:
        row = dict(db.execute(
            "SELECT title, status, version, owner, approver FROM aria_documents WHERE doc_id=%s",
            (doc_id,),
        ).fetchone())
    finally:
        db.close()

    assert row["title"] == "Renamed Via Metadata Save", "the permitted metadata field must persist"
    assert row["status"] == "Approved", "lifecycle field must never change via the generic Save"
    assert row["version"] == "2.1", "lifecycle field must never change via the generic Save"
    assert row["owner"] == "Original Owner", "lifecycle field must never change via the generic Save"
    assert row["approver"] == "Original Approver", "lifecycle field must never change via the generic Save"

    assert not errors, f"unexpected console/page errors: {errors}"


def test_legacy_document_edit_still_sends_lifecycle_fields(login_as, live_app, synthetic_tenant):
    """The managed-vs-legacy split lives entirely in the browser (submitEdit
    reads the edit-is-managed hidden flag); this is the one test that
    actually exercises that client branch for the legacy side, rather than
    calling the route directly the way test_aria_policy_legacy.py's
    equivalent HTTP test does."""
    actor = synthetic_tenant["users"]["compliance_manager"]
    doc_id = _seed_document(
        synthetic_tenant["org_id"], synthetic_tenant["business_unit_id"], actor["user_id"],
        "DOC-UIHARNESS-02", managed=0,
    )

    page = login_as("compliance_manager")
    page.goto(f"{live_app}/aria/documents")
    page.click(f"#row-{doc_id} .edit-btn")
    page.wait_for_selector("#editModal.open", timeout=5000)

    assert page.locator("#edit-legacy-lifecycle-fields").is_visible()
    assert page.locator("#edit-save-btn").inner_text() == "Save changes"

    page.select_option("#edit-status", "Retired")
    page.fill("#edit-version", "3.0")
    page.click("#edit-save-btn")
    errors = _wait_for_save_and_reload(page)

    db = database.get_db()
    try:
        row = dict(db.execute(
            "SELECT status, version FROM aria_documents WHERE doc_id=%s", (doc_id,),
        ).fetchone())
    finally:
        db.close()

    assert row["status"] == "Retired", "legacy documents must still accept lifecycle-field edits"
    assert row["version"] == "3.0", "legacy documents must still accept lifecycle-field edits"
    assert not errors, f"unexpected console/page errors: {errors}"
