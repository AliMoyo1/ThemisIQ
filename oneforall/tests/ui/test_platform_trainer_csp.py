"""The shared guide remains usable on pages with a strict script policy."""


def test_platform_guide_controls_work_under_ai_governance_csp(login_as, live_app):
    page = login_as("dpo")
    response = page.goto(f"{live_app}/ai-governance/assessments")
    script_policy = response.headers["content-security-policy"].split("script-src ", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script_policy

    page.locator("#trainerBubble .trainer-icon").click()
    assert page.locator("#trainerPanel").evaluate("el => el.classList.contains('open')")

    page.locator("#tooltipToggle").click()
    assert page.locator("body").evaluate("el => el.classList.contains('tooltip-mode')")
    page.locator("#trainerBanner [data-trainer-action='tooltip']").click()
    assert not page.locator("body").evaluate("el => el.classList.contains('tooltip-mode')")

    page.locator("#trainerPanel .trainer-close").click()
    assert not page.locator("#trainerPanel").evaluate("el => el.classList.contains('open')")
