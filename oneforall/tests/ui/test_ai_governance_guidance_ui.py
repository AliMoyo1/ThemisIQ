"""
AI governance G3 in a real browser: the path to a decision and the quality checks on the Overview, the checklist on the
Assessments tab with a reviewer's "not applicable", the way back from a form opened from a step, and the AI controls
panel saying why it is empty.

The accepted use these tests start from has its provider registered (acceptance creates it from the provider name), so
the one required step is in progress. A profile edit that makes the use elevated is what makes the other steps required.
"""
from tests.ui.test_ai_governance_pages import _accepted_system, unique  # noqa: F401

AIIA_CHECK = "Set aside: AI impact assessment is required and not started"


def _make_elevated(page):
    page.click("button:has-text('Edit profile')")
    page.check("#pf_data_categories input[value='sensitive_personal']")
    page.check("#pf_affected_people input[value='customers']")
    page.click(".aig-dialog button:has-text('Save')")
    page.wait_for_selector(".aig-dialog", state="detached")
    page.wait_for_selector("#aigHeader .aig-tier-elevated")


def test_the_overview_shows_the_path_to_a_decision_and_the_open_checks(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    page.wait_for_selector("h2:has-text('Path to a decision')")
    assert page.locator(".aig-path li").count() == 6
    assert "A decision waits for: Provider review." in page.locator(".aig-tabpanel").inner_text()
    page.wait_for_selector("text=The checks found nothing to act on")

    _make_elevated(page)
    page.wait_for_selector("h2:has-text('Quality checks (')")
    text = page.locator(".aig-tabpanel").inner_text()
    assert "AI impact assessment is required and not started" in text
    assert "(rule step_not_started v1)" in text
    page.click(".aig-path a:has-text('AI impact assessment')")
    page.wait_for_selector(".aig-tab.is-current:has-text('Assessments')")


def test_a_reviewer_sets_a_check_aside_with_a_reason_and_reopens_it(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    _make_elevated(page)
    page.wait_for_selector(f"button[aria-label='{AIIA_CHECK}']")
    page.click(f"button[aria-label='{AIIA_CHECK}']")
    page.fill("#aigDismissWhy", "The assessment is booked for next week.")
    page.click(".aig-dialog button:has-text('Set aside')")
    page.wait_for_selector("summary:has-text('Set aside (1)')")
    assert page.locator(f"button[aria-label='{AIIA_CHECK}']").count() == 0
    page.click("summary:has-text('Set aside (1)')")
    assert "The assessment is booked for next week." in page.locator("details").inner_text()
    page.click("button:has-text('Reopen')")
    page.wait_for_selector(f"button[aria-label='{AIIA_CHECK}']")


def test_a_set_aside_needs_a_reason(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    _make_elevated(page)
    page.wait_for_selector(f"button[aria-label='{AIIA_CHECK}']")
    page.click(f"button[aria-label='{AIIA_CHECK}']")
    page.click(".aig-dialog button:has-text('Set aside')")
    page.wait_for_selector(".aig-dialog .aig-say-bad")
    assert "Say why" in page.locator(".aig-dialog").inner_text()
    page.keyboard.press("Escape")
    assert page.locator(f"button[aria-label='{AIIA_CHECK}']").count() == 1, "nothing was set aside"


def test_the_assessments_tab_lists_what_the_use_needs_and_a_reviewer_can_rule_a_step_out(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    page.click("#aigtab_assessments")
    page.wait_for_selector("h2:has-text('What this use needs')")
    rows = page.locator(".aig-table tbody tr")
    assert rows.count() == 6
    vendor = rows.filter(has_text="Provider review")
    assert "Needed" in vendor.inner_text() and "In progress" in vendor.inner_text()

    vendor.locator("button:has-text('Not applicable')").click()
    page.fill("#aigNaWhy", "Built by us under licence.")
    page.click(".aig-dialog button:has-text('Save')")
    page.wait_for_selector("tr:has-text('Provider review') >> text=Marked not applicable")
    assert "Built by us under licence." in page.locator("tr:has-text('Provider review')").inner_text()

    page.click("tr:has-text('Provider review') >> button:has-text('Put back')")
    page.wait_for_selector("tr:has-text('Provider review') >> button:has-text('Not applicable')")
    assert "Marked not applicable" not in page.locator("tr:has-text('Provider review')").inner_text()


def test_each_step_opens_the_record_that_does_the_work_and_names_the_way_back(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    page.click("#aigtab_assessments")
    page.wait_for_selector("h2:has-text('What this use needs')")
    link = page.locator("tr:has-text('Provider review') >> a:has-text('Acme AI')")
    assert "aig_return=" in link.get_attribute("href")
    link.click()
    page.wait_for_selector("nav[aria-label='Return to the AI system']")
    page.click("nav[aria-label='Return to the AI system'] a")
    page.wait_for_selector(".aig-tab.is-current:has-text('Assessments')")


def test_the_controls_panel_tells_no_access_from_none_recorded(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)  # signed in as the DPO, who has no right to Operations risk
    page.click("#aigtab_risks_controls")
    page.wait_for_selector("h2:has-text('AI controls and their proof')")
    page.wait_for_selector("text=do not have access to AI management assessments")

    page.context.clear_cookies()
    login_as("super_admin")
    page.goto(f"{live_app}/ai-governance/?q={unique.replace(' ', '+')}")
    page.click(f"a:has-text('{unique}')")
    page.click("#aigtab_risks_controls")
    page.wait_for_selector("text=No AI controls are recorded for this use")
