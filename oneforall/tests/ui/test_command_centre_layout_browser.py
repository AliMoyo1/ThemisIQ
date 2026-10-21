"""Real browser coverage for the unified, user-owned Command Centre layout."""


def test_cards_can_be_removed_restored_reordered_and_saved(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/")
    page.locator('#ccDashboardCanvas .cc-widget[data-key="projects"]').wait_for()
    canvas = page.locator("#ccDashboardCanvas")
    assert canvas.locator('.cc-widget[data-key="compliance"]').count() == 1
    assert page.locator("#ccBreachAlert").evaluate("el => !el.closest('#ccDashboardCanvas')")

    page.wait_for_load_state("networkidle")
    page.locator("#ccCustomizeBtn").click()
    page.locator("#ccResetLayout").click()
    page.wait_for_function("""() => Array.from(document.querySelectorAll('#ccDashboardCanvas .cc-widget')).findIndex(n => n.dataset.key === 'projects') === 2""")
    assert page.locator("#ccCustomizer").is_visible()
    page.locator('.cc-widget[data-key="projects"] .cc-remove').click()
    assert canvas.locator('.cc-widget[data-key="projects"]').is_hidden()
    page.get_by_role("button", name="+ Active projects").click()
    assert canvas.locator('.cc-widget[data-key="projects"]').is_visible()

    before = page.evaluate("Array.from(document.querySelectorAll('#ccDashboardCanvas .cc-widget')).map(n => n.dataset.key)")
    page.locator('.cc-widget[data-key="projects"] .cc-move-back').click()
    page.wait_for_timeout(300)
    after = page.evaluate("Array.from(document.querySelectorAll('#ccDashboardCanvas .cc-widget')).map(n => n.dataset.key)")
    assert after.index("projects") == before.index("projects") - 1
    page.wait_for_timeout(350)
    page.reload()
    page.locator('#ccDashboardCanvas .cc-widget[data-key="projects"]').wait_for()
    page.wait_for_function("""() => Array.from(document.querySelectorAll('#ccDashboardCanvas .cc-widget')).findIndex(n => n.dataset.key === 'projects') === 1""")
    assert not page.console_errors, page.console_errors
    page.locator("#ccCustomizeBtn").click()
    page.locator("#ccResetLayout").click()
    page.wait_for_function("async () => (await (await fetch('/api/command-centre/layout')).json()).layout === null")


def test_drag_handle_reorders_and_reset_restores_default(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/")
    page.locator("#ccCustomizeBtn").click()
    source = page.locator('.cc-widget[data-key="overdue"] .cc-drag-handle')
    target = page.locator('.cc-widget[data-key="projects"]')
    source.drag_to(target)
    page.wait_for_function("""() => Array.from(document.querySelectorAll('#ccDashboardCanvas .cc-widget')).findIndex(n => n.dataset.key === 'overdue') < 3""", timeout=5000)
    page.locator("#ccResetLayout").click()
    page.wait_for_function("""() => Array.from(document.querySelectorAll('#ccDashboardCanvas .cc-widget')).findIndex(n => n.dataset.key === 'overdue') === 3""")
    page.wait_for_function("async () => (await (await fetch('/api/command-centre/layout')).json()).layout === null")
    assert not page.console_errors, page.console_errors


def test_layout_rejects_unlisted_widgets(login_as, live_app):
    page = login_as("super_admin")
    result = page.evaluate("""async () => {
      try { await ApiClient.request('/api/command-centre/layout', {
        method: 'PUT', body: {layout: {order: ['<script>'], hidden: []}}, actionId: 'command_centre.layout.save'
      }); return null; } catch (e) { return e.detail; }
    }""")
    assert "Unknown or duplicate" in result
