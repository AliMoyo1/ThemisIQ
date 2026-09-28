"""
PLAN-36 T03, real browser: ERM library admin (F03 + F13) and Email Settings
Reset (F04).
"""
import database


def test_add_template_button_hidden_without_erm_library_manage(login_as, live_app):
    """compliance_manager has module.erm.access (so the library itself is
    reachable) but not erm.library.manage (only SUPER_ADMIN/RISK_OWNER per
    core/rbac.py) -- the button must not even be in the DOM (server renders
    it conditionally), not just CSS-hidden."""
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/erm/library")
    page.wait_for_selector("#ermLibGrid .lib-card", timeout=5000)
    assert page.locator("#libAdminBtn").count() == 0
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_add_template_opens_modal_and_creates_an_org_scoped_template(
    login_as, live_app, synthetic_tenant,
):
    """risk_owner holds erm.library.manage -- the button renders, the T02
    modal contract opens correctly, and the created row is scoped to their
    own organization (never global)."""
    page = login_as("risk_owner")
    page.goto(f"{live_app}/erm/library")
    page.wait_for_selector("#ermLibGrid .lib-card", timeout=5000)

    assert page.locator("#libAdminBtn").count() == 1
    page.click("#libAdminBtn")
    page.wait_for_selector("#libItemModal.open", timeout=5000)
    assert page.locator("#libItemModal").get_attribute("role") == "dialog"

    page.fill("#lib-title", "UI Harness Custom Template")
    page.click("#lib-item-save-btn")
    page.wait_for_selector("#libItemModal", state="hidden", timeout=5000)
    page.wait_for_selector("text=UI Harness Custom Template", timeout=5000)

    db = database.get_db()
    try:
        row = dict(db.execute(
            "SELECT org_id FROM erm_risk_library WHERE title='UI Harness Custom Template'"
        ).fetchone())
    finally:
        db.close()
    assert row["org_id"] == synthetic_tenant["org_id"], \
        "a non-super-admin's new template must be scoped to their own organization"

    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_organization_user_cannot_see_manage_controls_on_a_global_template(
    login_as, live_app,
):
    """The seeded baseline catalogue (org_id IS NULL) must show no Edit/Retire
    controls to an ordinary organization risk_owner -- only Quick Add/Customize."""
    page = login_as("risk_owner")
    page.goto(f"{live_app}/erm/library")
    page.wait_for_selector("#ermLibGrid .lib-card", timeout=5000)

    card = page.locator(".lib-card", has_text="Ransomware Attack")  # a seeded global template
    assert card.locator("text=🌐 Global").count() == 1
    assert card.get_by_role("button", name="Edit").count() == 0
    assert card.get_by_role("button", name="Retire").count() == 0
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_email_reset_reloads_without_error(login_as, live_app):
    """FINDING F04 (fixed): Reset used to call the undefined global
    loadConfig(); it now calls the window-attached resetConfig()."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/admin/email")
    page.click('button:has-text("Reset")')
    page.wait_for_timeout(500)  # resetConfig's own fetch + toast round-trip
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
