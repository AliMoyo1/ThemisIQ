"""Operator can run and inspect the bounded synthetic checks of ThemisIQ's own AI features."""


def test_operator_runs_synthetic_citation_and_policy_checks(login_as, live_app, page):
    login_as("super_admin")
    page.goto(f"{live_app}/ai-governance/platform-features")
    page.get_by_role("searchbox", name="Search platform AI features").fill("aria.ask")
    page.get_by_role("button", name="Synthetic checks").click()
    dialog = page.locator(".aig-dialog")
    dialog.get_by_text("No checks have been run.").wait_for()
    dialog.get_by_role("button", name="Run citation identity checks").click()
    dialog.get_by_text("passed · 5 cases · 0 failed", exact=False).wait_for()
    assert dialog.get_by_text("Passed: fabricated title").count() == 1
    assert dialog.get_by_text("Independent review: pending").count() == 1
    assert dialog.get_by_role("button", name="Review as accepted").count() == 0

    dialog.get_by_role("button", name="Run ai policy refusal checks").click()
    dialog.get_by_text("Passed: refused when business data is not allowed").wait_for()
    assert dialog.get_by_text("Passed: refused for a provider the policy does not name").count() == 1
    assert dialog.get_by_text("Model output: not measured", exact=False).count() == 1

    page.context.clear_cookies()
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/platform-features")
    assert page.get_by_role("button", name="Synthetic checks").count() == 0


def test_every_feature_offers_the_policy_refusal_checks(login_as, live_app, page):
    login_as("super_admin")
    page.goto(f"{live_app}/ai-governance/platform-features")
    page.get_by_role("searchbox", name="Search platform AI features").fill("sentinel.ai_chat")
    page.get_by_role("button", name="Synthetic checks").click()
    dialog = page.locator(".aig-dialog")
    dialog.get_by_role("button", name="Run ai policy refusal checks").click()
    dialog.get_by_text("passed · 9 cases · 0 failed", exact=False).wait_for()
    assert dialog.get_by_text("Passed: refused when personal data is not allowed").count() == 1
    assert dialog.get_by_role("button", name="Run citation identity checks").count() == 0
