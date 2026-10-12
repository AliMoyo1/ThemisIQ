"""One complete AI review pack journey in the disposable browser tenant."""
import re

from tests.ui.test_ai_governance_pages import _accepted_system, unique  # noqa: F401


def test_a_reviewer_previews_shares_and_withdraws_a_pack_from_a_named_recipient(login_as, live_app, page, run_axe, unique):
    _accepted_system(login_as, live_app, page, unique)
    app_id = re.search(r"/systems/(\d+)", page.url).group(1)
    page.goto(f"{live_app}/ai-governance/packs?application_id={app_id}")
    page.wait_for_selector("#aigPackName")
    assert run_axe() == []
    page.fill("#aigPackName", "Review of " + unique)
    page.fill("#aigPackPurpose", "Audit discussion")
    page.fill("#aigPackRecipient", "uiharness_viewer")
    page.wait_for_selector(".aig-pack-recipient-results button")
    page.click(".aig-pack-recipient-results button")
    page.click("button:has-text('Preview pack')")
    page.wait_for_selector("button:has-text('Issue this pack'):visible")
    assert "not a certification" in page.locator("#aigPacks").inner_text()
    assert run_axe() == []
    page.click("button:has-text('Issue this pack')")
    page.wait_for_url(re.compile(r"/ai-governance/packs/\d+$"))
    pack_url = page.url
    page.wait_for_selector("#aigPackManage")
    assert "Review of " + unique in page.locator("h1").inner_text()
    assert run_axe() == []

    page.context.clear_cookies()
    login_as("viewer")
    page.goto(f"{live_app}/ai-governance/packs")
    page.wait_for_selector(".aig-pack-card-title")
    assert "Review of " + unique in page.locator(".aig-pack-card-title").first.inner_text()
    assert run_axe() == []
    page.goto(pack_url)
    page.wait_for_selector("h1:has-text('Review of')")
    assert page.locator("#aigPackManage").count() == 0
    assert page.locator("a:has-text('Download JSON')").count() == 0
    assert run_axe() == []
    page.set_viewport_size({"width": 375, "height": 812})
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    page.set_viewport_size({"width": 1280, "height": 800})

    page.context.clear_cookies()
    login_as("dpo")
    page.goto(pack_url)
    page.click("button:has-text('Withdraw access')")
    page.fill("#aigPackRevokeReason", "Review completed")
    page.click(".aig-dialog button:has-text('Withdraw access')")
    page.wait_for_selector(".aig-banner-warn:has-text('revoked')")
    page.context.clear_cookies()
    login_as("viewer")
    page.goto(pack_url)
    assert page.locator("h1:has-text('Review of')").count() == 0
    assert "Review pack not found" in page.locator("body").inner_text()
