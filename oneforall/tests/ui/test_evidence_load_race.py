"""An older Evidence fetch must not repaint a newer selection."""

def test_stale_items_response_does_not_clear_keyboard_selection(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence")
    page.wait_for_load_state("networkidle", timeout=15000)
    assert page.evaluate("evCanBulkArchive")
    queued = page.evaluate("""() => {
      const originalFetch = window.fetch.bind(window);
      window.__pendingEvidence = [];
      window.fetch = (input, options) => {
        if (String(input).startsWith('/evidence/api/items?')) {
          return new Promise(resolve => window.__pendingEvidence.push(resolve));
        }
        return originalFetch(input, options);
      };
      evSelectionMode = true;
      evViewMode = 'table';
      loadEvidence();
      loadEvidence();
      return window.__pendingEvidence.length;
    }""")
    assert queued == 2
    item = {"id": 742, "title": "Newest evidence", "status": "current",
            "category": "general", "link_count": 0}
    page.evaluate("item => window.__pendingEvidence[1]({json: async () => [item]})", item)
    checkbox = page.get_by_role("checkbox", name="Select Newest evidence")
    checkbox.wait_for()
    checkbox.focus()
    page.keyboard.press("Space")
    assert checkbox.is_checked()
    assert page.locator("#evSelectedCount").inner_text() == "1 selected"
    page.evaluate("item => window.__pendingEvidence[0]({json: async () => [item]})", item)
    page.wait_for_timeout(100)
    assert checkbox.is_checked()
    assert page.locator("#evSelectedCount").inner_text() == "1 selected"
