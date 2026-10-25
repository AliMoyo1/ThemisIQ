"""The scoped law monitor and Ask Sentinel work in the real module shell."""


def test_dpo_sees_monitor_and_extractively_abstains_without_approved_sources(login_as, live_app, page):
    login_as("dpo")
    page.goto(f"{live_app}/sentinel/jurisdictions")
    page.locator("#snLawMonitor .sn-watch-settings > summary").click()
    page.locator("#snLawSchedule").get_by_text("Save schedule").wait_for()
    assert page.locator("#snLawMonitor").is_visible()
    assert page.locator("#snAskLawAiDraft").is_visible()
    page.locator("#snAskLawQuestion").fill("When must a personal data breach be notified?")
    page.locator("#snAskLawForm button[type=submit]").click()
    page.get_by_text("I can't verify this from approved official sources", exact=False).wait_for()
    assert page.locator("#snAskLawAnswer a").count() == 0
