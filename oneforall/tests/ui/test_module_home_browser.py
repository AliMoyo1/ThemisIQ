"""Connected overview loads on specialist dashboards with truthful source states."""

import pytest


@pytest.mark.parametrize("module", ["grid", "bcm", "sentinel", "erm", "orm"])
def test_connected_overview_renders_live_cards(login_as, live_app, module):
    page = login_as("super_admin")
    page.goto(f"{live_app}/{module}/")
    overview = page.locator(".connected-module-home")
    overview.wait_for()
    page.wait_for_function("""() => {
      const cards = document.querySelectorAll('.connected-module-card');
      return cards.length === 4;
    }""")
    assert overview.get_by_text("Connected overview").is_visible()
    assert overview.get_by_text("Coverage / quality").is_visible()
    assert overview.get_by_text("Not measured").count() <= 1
