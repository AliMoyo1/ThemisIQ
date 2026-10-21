"""Evidence Vault browser actions for file type and view controls."""


def test_non_office_file_has_only_original_download(live_app, page, login_as, synthetic_tenant):
    import database

    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO evidence_items "
            "(title, category, uploaded_by, org_id, file_path, file_name, file_size, mime_type) "
            "VALUES ('Text evidence', 'general', %s, %s, %s, 'notes.txt', 12, 'text/plain')",
            (
                synthetic_tenant["users"]["compliance_manager"]["user_id"],
                synthetic_tenant["org_id"],
                "isolated-browser-test-not-downloaded.txt",
            ),
        )
        db.commit()
        item_id = db.execute(
            "SELECT id FROM evidence_items WHERE title='Text evidence'"
        ).fetchone()["id"]
    finally:
        db.close()

    login_as("compliance_manager")
    page.goto(f"{live_app}/evidence")
    page.locator("#btnTable").click()
    page.locator("#evidenceTable").wait_for(state="visible")
    page.locator("#btnCards").click()
    page.locator("#evidenceGrid").wait_for(state="visible")
    page.evaluate("id => openDetail(id)", item_id)
    panel = page.locator("#evDetailPanel.open")
    panel.wait_for()
    assert panel.get_by_role("button", name="Download original").count() == 1
    assert panel.get_by_role("button", name="Download PDF").count() == 0
    panel.get_by_role("button", name="Link to...").click()
    page.locator("#linkToModal.open").wait_for()
