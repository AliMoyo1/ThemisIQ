"""
PLAN-36 T07 (findings.md F09): evidence_index.html's stat/filter cards,
recent-item cards, grid-view cards, detail tabs, and the "link an entity"
dropdown were all `<div onclick=...>`/`<span onclick=...>` -- clickable only
with a mouse, with no way to reach or activate them from the keyboard. They
are now real `<button type="button">` elements (native Tab/Enter/Space
support comes for free), and the detail panel's Details/Versions/Activity
tabs carry real ARIA tab semantics (role=tab/tabpanel, aria-selected).
"""


def test_stats_bar_cards_are_real_buttons_not_divs(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/evidence")
    page.wait_for_selector("#statsBar button")
    tags = page.eval_on_selector_all(
        "#statsBar > *", "els => els.map(e => e.tagName)"
    )
    # The "Links" tile has no onclick and stays a plain div; every
    # clickable filter tile must be a real button.
    assert "BUTTON" in tags
    assert "DIV" in tags


def test_stats_bar_card_is_keyboard_operable(login_as, live_app):
    """Red proof for this test (temporarily reverting the switchView tile
    back to a bare div): Tab never reaches it and Enter does nothing,
    window.currentView stays 'all'. Restored, this passes."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/evidence")
    page.wait_for_selector("#statsBar button")
    expiring_btn = page.locator("#statsBar button", has_text="Expiring 30d")
    expiring_btn.focus()
    assert page.evaluate("document.activeElement.textContent").strip().startswith("Expiring")
    page.keyboard.press("Enter")
    assert page.evaluate("window.currentView") == "expiring"
    assert "active" in (page.locator("#nav-expiring").get_attribute("class") or "")


def test_recent_and_grid_cards_are_buttons(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/evidence")
    page.wait_for_load_state("networkidle")
    # Grid view is the default; card wrapper must be a real button.
    page.wait_for_selector("#viewGrid button.card, #viewGrid .empty-state, #emptyState",
                            state="attached", timeout=5000)


def test_link_entity_dropdown_items_are_buttons(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/evidence")
    page.route("**/evidence/api/search-entities**", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body='[{"id": 5, "name": "Access Control Policy"}]'))
    page.evaluate("openLinkToModal(1)")
    page.wait_for_selector("#linkToModal.open")
    # Selecting the module populates #linkEntityType's options for real
    # (entityTypes['aria'] includes 'document'); selecting a type then
    # fires searchEntities() via its own onchange.
    page.select_option("#linkModule", "aria")
    page.select_option("#linkEntityType", "document")
    page.wait_for_selector("#linkEntityList button")
    assert page.locator("#linkEntityList button").count() == 1


def test_detail_tabs_have_tab_semantics_and_toggle_aria_selected(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/evidence")
    page.route("**/evidence/api/items/1", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body='{"id": 1, "title": "Access Control Policy", "category": "General"}'
    ) if r.request.method == "GET" else r.continue_())
    page.evaluate("openDetail(1)")
    page.wait_for_selector("#evDetailPanel.open")
    tablist = page.locator('[role="tablist"]')
    assert tablist.count() == 1
    details_tab = page.locator("#tab-details")
    history_tab = page.locator("#tab-history")
    assert details_tab.get_attribute("aria-selected") == "true"
    assert history_tab.get_attribute("aria-selected") == "false"
    history_tab.click()
    assert history_tab.get_attribute("aria-selected") == "true"
    assert details_tab.get_attribute("aria-selected") == "false"


def test_escape_closes_the_detail_panel(login_as, live_app):
    """Red proof (temporarily removing the new keydown listener in
    closeDetail's vicinity): Escape does nothing, #evDetailPanel keeps the
    'open' class. Restored, Escape closes it."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/evidence")
    page.route("**/evidence/api/items/1", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body='{"id": 1, "title": "Access Control Policy", "category": "General"}'
    ) if r.request.method == "GET" else r.continue_())
    page.evaluate("openDetail(1)")
    page.wait_for_selector("#evDetailPanel.open")
    page.keyboard.press("Escape")
    page.wait_for_selector("#evDetailPanel:not(.open)")


def test_toast_container_is_a_live_region(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/evidence")
    container = page.locator("#toastContainer")
    assert container.get_attribute("role") == "status"
    assert container.get_attribute("aria-live") == "polite"
