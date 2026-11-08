"""Operator can run and inspect the bounded Ask ARIA contract check."""


def test_operator_runs_synthetic_citation_check(login_as, live_app, page):
    login_as("super_admin")
    page.goto(f"{live_app}/ai-governance/platform-features")
    page.get_by_role("searchbox", name="Search platform AI features").fill("aria.ask")
    page.get_by_role("button", name="Citation check history").click()
    dialog = page.locator(".aig-dialog")
    dialog.get_by_text("No checks have been run.").wait_for()
    dialog.get_by_role("button", name="Run synthetic checks").click()
    dialog.get_by_text("passed · 5 cases · 0 failed", exact=False).wait_for()
    assert dialog.get_by_text("Passed: fabricated title").count() == 1
    assert dialog.get_by_text("Independent review: pending").count() == 1
    assert dialog.get_by_role("button", name="Review as accepted").count() == 0

    page.context.clear_cookies()
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/platform-features")
    assert page.get_by_role("button", name="Citation check history").count() == 0
