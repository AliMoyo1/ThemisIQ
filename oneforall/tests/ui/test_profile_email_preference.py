"""
A person can turn off the mail about actions assigned to them, and the choice survives a reload
(plans/2026-10-governance-rework/06 section 3: preference policy, with what is always sent disclosed).
"""


def test_the_action_mail_preference_is_saved_and_restored(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/profile")
    page.wait_for_selector("#emailAction:not([disabled])", timeout=8000)
    assert page.is_checked("#emailAction"), "mail about assigned actions is on until the person turns it off"
    page.uncheck("#emailAction")

    page.wait_for_selector("#emailActionStatus:has-text('You will not be emailed')", timeout=8000)
    page.reload()
    page.wait_for_selector("#emailAction:not([disabled])", timeout=8000)
    assert not page.is_checked("#emailAction")
    page.check("#emailAction")
    page.wait_for_selector("#emailActionStatus:has-text('You will be emailed')", timeout=8000)
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_the_page_says_what_is_always_sent(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/profile")
    text = page.inner_text("body")
    assert "Deadline alerts that a role is named to receive" in text and "never carries a title" in text


def test_a_daily_summary_a_weekly_summary_and_quiet_hours_are_saved_and_restored(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/profile")
    page.wait_for_selector("#emailAction:not([disabled])", timeout=8000)
    assert page.is_checked("#emailModeImmediate") and not page.is_checked("#emailWeekly")
    assert page.is_disabled("#quietStart"), "the times are not offered until quiet hours are switched on"

    page.check("#emailModeDaily")
    page.wait_for_selector("#emailActionStatus:has-text('one summary a day')", timeout=8000)
    page.check("#emailWeekly")
    page.wait_for_selector("#emailActionStatus:has-text('every Monday')", timeout=8000)
    page.check("#quietOn")
    page.fill("#quietStart", "21:30")
    page.fill("#quietEnd", "06:45")
    page.select_option("#utcOffset", "120")
    page.click("#quietSave")
    page.wait_for_selector("#emailActionStatus:has-text('21:30 to 06:45')", timeout=8000)

    page.reload()
    page.wait_for_selector("#emailAction:not([disabled])", timeout=8000)
    assert page.is_checked("#emailModeDaily") and page.is_checked("#emailWeekly") and page.is_checked("#quietOn")
    assert page.input_value("#quietStart") == "21:30" and page.input_value("#quietEnd") == "06:45"
    assert page.input_value("#utcOffset") == "120"

    page.uncheck("#quietOn")
    page.wait_for_selector("#emailActionStatus:has-text('Quiet hours are off')", timeout=8000)
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_changing_the_time_zone_does_not_undo_quiet_hours_that_are_not_saved_yet(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/profile")
    page.wait_for_selector("#emailAction:not([disabled])", timeout=8000)
    page.check("#quietOn")
    page.fill("#quietStart", "20:15")
    page.fill("#quietEnd", "05:30")
    page.select_option("#utcOffset", "180")
    page.wait_for_selector("#emailActionStatus:has-text('Your time zone is saved')", timeout=8000)
    assert page.is_checked("#quietOn"), "the save of the time zone answered with the saved state, which has no quiet hours"
    assert page.input_value("#quietStart") == "20:15" and page.input_value("#quietEnd") == "05:30"
    assert page.is_enabled("#quietSave")

    # leave the saved state as it was for the tests that follow
    page.uncheck("#quietOn")
    page.wait_for_selector("#emailActionStatus:has-text('Quiet hours are off')", timeout=8000)
    page.select_option("#utcOffset", "0")
    page.wait_for_selector("#emailActionStatus:has-text('Your time zone is saved')", timeout=8000)
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
