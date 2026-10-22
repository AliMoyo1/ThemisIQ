"""Evidence Vault browser actions for file type and view controls."""


def test_ai_link_suggestion_stays_data_when_clicked(live_app, page, login_as, synthetic_tenant):
    """A response value containing JavaScript punctuation cannot become a click handler."""
    import json
    import database

    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO evidence_items "
            "(title, category, uploaded_by, org_id, file_path, file_name, file_size, mime_type) "
            "VALUES ('Suggestion test', 'general', %s, %s, %s, 'suggestion.txt', 12, 'text/plain')",
            (
                synthetic_tenant["users"]["compliance_manager"]["user_id"],
                synthetic_tenant["org_id"],
                "isolated-suggestion-test-not-downloaded.txt",
            ),
        )
        db.commit()
        item_id = db.execute(
            "SELECT id FROM evidence_items WHERE title='Suggestion test'"
        ).fetchone()["id"]
    finally:
        db.close()

    payload = "x','y',31,this);window.__xssRan=true;//"
    page.route(
        f"**/evidence/api/items/{item_id}/suggest-links",
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"suggestions": [{"module": payload, "entity_type": "control",
                                              "entity_id": 31, "entity_name": "Test control",
                                              "reason": "Test suggestion"}]}),
        ),
    )
    page.route(
        f"**/evidence/api/items/{item_id}/links",
        lambda route: route.fulfill(
            status=400, content_type="application/json", body='{"detail":"Rejected"}',
        ),
    )

    login_as("compliance_manager")
    page.goto(f"{live_app}/evidence")
    page.evaluate("id => openDetail(id)", item_id)
    page.locator("#evDetailPanel.open").wait_for()
    page.evaluate("window.__xssRan = false")
    page.evaluate("id => aiSuggestLinks(id)", item_id)
    button = page.locator("#aiSuggestBox [data-ev-action='ai-link']")
    button.wait_for()
    assert button.get_attribute("onclick") is None
    button.click()
    assert page.evaluate("window.__xssRan") is False


def test_inspector_rule_stays_data_when_clicked(live_app, page, login_as):
    """Inspector rule keys may contain quotes but must never become JavaScript."""
    import json
    from urllib.parse import parse_qs, urlsplit

    login_as("compliance_manager")
    rule = "x');window.__xssRan=true;//"
    response = {
        "total": 1, "scanned": 1, "note": "Inspector test", "findings": [],
        "counts": {rule: 1},
        "rules": {rule: {"label": "Test rule", "severity": "warning"}},
    }
    page.route(
        "**/evidence/api/inspector?*",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(response),
        ),
    )
    page.goto(f"{live_app}/evidence")
    page.locator("#evInsights summary").click()
    page.evaluate("window.__xssRan = false")
    page.evaluate("loadChecks()")
    button = page.locator("#evChecks [data-ev-action='check-filter']")
    button.wait_for()
    assert button.get_attribute("onclick") is None
    with page.expect_request(lambda request: "&rule=" in request.url) as selected:
        button.click()
    assert parse_qs(urlsplit(selected.value.url).query)["rule"] == [rule]
    assert page.evaluate("window.__xssRan") is False


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
