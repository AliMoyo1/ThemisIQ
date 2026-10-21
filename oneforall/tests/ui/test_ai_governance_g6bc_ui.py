"""Focused browser journey for platform AI feature oversight."""
from datetime import date, timedelta

def test_platform_operator_can_find_record_and_review_feature(login_as, live_app, page, run_axe):
    login_as("super_admin")
    page.goto(f"{live_app}/ai-governance/platform-features")
    page.locator(".aig-platform-card").first.wait_for()
    first = page.locator(".aig-platform-card").first
    key = first.locator(".aig-platform-key").inner_text()
    page.get_by_role("searchbox", name="Search platform AI features").fill(key)
    assert page.locator(".aig-platform-card").count() == 1
    page.get_by_role("button", name="Open oversight notes").click()
    dialog = page.locator(".aig-dialog")
    dialog.get_by_label("Owner").fill("Platform assurance")
    dialog.get_by_label("Provider and model").fill("Reviewed provider")
    dialog.get_by_label("Known limitations").fill("Human confirmation required")
    dialog.get_by_label("Incident path").fill("Contact security")
    dialog.get_by_label("Next review").fill((date.today() + timedelta(days=30)).isoformat())
    dialog.get_by_role("button", name="Save notes").click()
    page.get_by_text("Platform assurance").wait_for()
    page.get_by_role("button", name="Mark reviewed").click()
    page.locator(".aig-dialog").get_by_role("button", name="Mark reviewed").click()
    page.get_by_text("Reviewed", exact=True).first.wait_for()
    assert run_axe() == []
    page.context.clear_cookies()
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/platform-features")
    assert page.get_by_role("heading", name="Platform AI features").count() == 0
