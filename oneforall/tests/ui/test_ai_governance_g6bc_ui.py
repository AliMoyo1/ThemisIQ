"""Focused browser journeys for literacy and platform AI feature oversight."""
from datetime import date, timedelta

from tests.ui.test_ai_governance_pages import unique  # noqa: F401


def test_literacy_manager_publishes_and_learner_completes(login_as, live_app, page, run_axe, unique):
    title = "Responsible AI " + unique
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/literacy")
    page.get_by_role("tab", name="Manage courses").click()
    page.get_by_role("button", name="New course").click()
    page.get_by_label("Course title").fill(title)
    page.get_by_label("Course content").fill("A person checks important AI output.")
    page.locator(".aig-literacy-roles label", has_text="employee").locator("input").check()
    page.get_by_role("button", name="Save working copy").click()
    page.get_by_role("button", name="Publish and require retake").wait_for()
    page.get_by_role("button", name="Publish and require retake").click()
    page.locator(".aig-dialog").get_by_role("button", name="Continue").click()
    page.wait_for_timeout(1500)
    assert "active" in page.locator(".aig-literacy-card", has_text=title).first.inner_text().lower(), page.locator("#aigLiteracy").inner_text()[:1500]
    assert run_axe() == []

    page.context.clear_cookies()
    login_as("employee")
    page.goto(f"{live_app}/ai-governance/literacy")
    page.get_by_role("link", name=title).wait_for()
    page.get_by_role("link", name=title).click()
    page.get_by_text("A person checks important AI output.").wait_for()
    page.get_by_label("I have read and understood this AI literacy course.").check()
    page.get_by_role("button", name="Complete course").click()
    page.get_by_text("Completed. Your next renewal is", exact=False).wait_for()
    assert run_axe() == []


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
