"""An external auditor (the `viewer` persona) reads a Vault file but is offered nothing that files or changes one."""
import database


def _seed_item(tenant, title):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO evidence_items (title, category, uploaded_by, org_id, business_unit_id, status) "
            "VALUES (%s, 'general', %s, %s, %s, 'current')",
            (title, tenant["users"]["compliance_manager"]["user_id"], tenant["org_id"], tenant["business_unit_id"]),
        )
        db.commit()
        return db.execute("SELECT id FROM evidence_items WHERE title=%s", (title,)).fetchone()["id"]
    finally:
        db.close()


_CHANGE_CONTROLS = ("#evDetailContent .ev-edit-btn, #evDetailContent [data-ev-dynamic^='doSetVerification'], "
                    "#evDetailContent [data-ev-dynamic^='aiSuggestLinks'], #evDetailContent [data-ev-dynamic^='openLinkToModal'], "
                    "#evDetailContent [data-ev-dynamic^='evAddVersion']")


def test_the_auditor_reads_a_file_with_no_control_that_changes_it(live_app, page, login_as, synthetic_tenant):
    item_id = _seed_item(synthetic_tenant, "Read-only drawer file")
    login_as("viewer")
    page.goto(f"{live_app}/evidence/")
    assert page.get_by_role("button", name="+ Upload").count() == 0
    assert page.get_by_role("link", name="Batch upload").count() == 0
    page.evaluate("id => openDetail(id)", item_id)
    page.locator("#evDetailPanel.open").wait_for()
    assert "Read-only drawer file" in page.locator("#evDetailContent").inner_text()
    assert page.locator(_CHANGE_CONTROLS).count() == 0


_PAGES = ("/aria/", "/aria/documents", "/aria/risks", "/grid/")


def _visible_write_actions(page, live_app):
    shown = {}
    for path in _PAGES:
        page.goto(f"{live_app}{path}")
        page.wait_for_load_state("networkidle")
        shown[path] = page.locator(".write-action:visible").count()
    return shown


def test_the_auditor_is_not_offered_aria_and_grid_create_actions(live_app, page, login_as):
    login_as("viewer")
    assert _visible_write_actions(page, live_app) == {path: 0 for path in _PAGES}
    assert page.evaluate("document.documentElement.hasAttribute('data-read-only')") is True


def test_audit_and_policy_staff_still_see_them(live_app, page, login_as):
    login_as("compliance_manager")
    shown = _visible_write_actions(page, live_app)
    assert page.evaluate("document.documentElement.hasAttribute('data-read-only')") is False
    assert shown["/aria/documents"] >= 1 and shown["/aria/risks"] >= 1 and shown["/grid/"] >= 1, shown


def test_staff_still_see_the_controls(live_app, page, login_as, synthetic_tenant):
    item_id = _seed_item(synthetic_tenant, "Staff drawer file")
    login_as("employee")
    page.goto(f"{live_app}/evidence/")
    assert page.get_by_role("button", name="+ Upload").count() == 1
    page.evaluate("id => openDetail(id)", item_id)
    page.locator("#evDetailPanel.open").wait_for()
    assert page.locator(_CHANGE_CONTROLS).count() >= 5
