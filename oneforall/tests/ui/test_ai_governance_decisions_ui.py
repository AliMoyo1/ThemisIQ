"""
AI governance G4 in a real browser: asking for a decision from a system's Decisions tab, the brief a decider sees, the
decision itself with its override and conditions, a return, and the queue. Every state is checked for serious
accessibility violations.
"""
import pytest

from tests.ui.test_ai_governance_pages import _accepted_system, unique  # noqa: F401


def _open_decisions(page):
    page.click("#aigtab_decisions")
    page.wait_for_selector("#aigDecState")


def _ask(page, note="Ready for the pilot."):
    page.click("button:has-text('Ask for a decision')")
    page.fill("#aigAskNote", note)
    page.click(".aig-dialog button:has-text('Ask for a decision')")
    page.wait_for_selector("h2:has-text('Waiting for a decision')")


def _as_decider(login_as, live_app, page, name):
    page.context.clear_cookies()
    login_as("super_admin")
    page.goto(f"{live_app}/ai-governance/?q={name.replace(' ', '+')}")
    page.click(f"a:has-text('{name}')")
    page.wait_for_selector(".aig-tab.is-current:has-text('Overview')")
    _open_decisions(page)


def test_a_system_with_no_decision_says_so_and_offers_to_ask(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    _open_decisions(page)
    assert "No decision" in page.locator(".aig-tabpanel").inner_text()
    assert page.locator("button:has-text('Ask for a decision')").count() == 1
    assert page.locator("button:has-text('Review and decide')").count() == 0


def test_a_reviewer_asks_and_cannot_decide_their_own_request_and_a_different_decider_approves_with_a_reason(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)  # signed in as the DPO
    _open_decisions(page)
    _ask(page)
    text = page.locator(".aig-tabpanel").inner_text()
    assert "A request is waiting" in text and "Someone other than the person who asked" in text
    assert page.locator("button:has-text('Review and decide')").count() == 0

    _as_decider(login_as, live_app, page, unique)
    page.click("button:has-text('Review and decide')")
    page.wait_for_selector(".aig-dialog input[name='aigOutcome']")
    dialog = page.locator(".aig-dialog").inner_text()
    assert "Required steps are not done" in dialog and "Provider review" in dialog

    page.click(".aig-dialog button:has-text('Record the decision')")
    page.wait_for_selector(".aig-dialog .aig-say-bad")
    assert "Say why" in page.locator(".aig-dialog").inner_text(), "an unresolved step needs a recorded reason"

    page.fill("#aigRationale", "Low tier, and the provider is registered.")
    page.fill("#aigOverride", "The provider review is booked for next week.")
    page.click(".aig-dialog button:has-text('Record the decision')")
    page.wait_for_selector("h2:has-text('Latest decision')")
    panel = page.locator(".aig-tabpanel").inner_text()
    assert "Approved" in panel and "Low tier" in panel and "provider review is booked" in panel
    assert page.locator("button:has-text('Revoke the approval')").count() == 1
    page.click("button:has-text('What it was decided on')")
    page.wait_for_selector(".aig-dialog .aig-brief")
    assert "AI impact assessments" in page.locator(".aig-dialog").inner_text()
    link = page.locator(".aig-dialog a:has-text('Download the record')")
    assert link.get_attribute("href").endswith("/export")
    page.keyboard.press("Escape")


def test_a_decider_can_approve_with_conditions_and_the_owner_side_sees_them(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    _open_decisions(page)
    _ask(page)
    _as_decider(login_as, live_app, page, unique)
    page.click("button:has-text('Review and decide')")
    page.wait_for_selector(".aig-dialog input[name='aigOutcome']")
    page.check(".aig-dialog input[value='approve_with_conditions']")
    page.fill("#aigCond1", "Every output is reviewed by a person.")
    page.fill("#aigOverride", "The provider review is booked for next week.")
    page.click(".aig-dialog button:has-text('Record the decision')")
    page.wait_for_selector("h2:has-text('Latest decision')")
    assert "Approved with conditions" in page.locator(".aig-tabpanel").inner_text()
    page.click("button[aria-label^='Mark as met']")
    page.wait_for_selector("li:has-text('Every output') >> text=Met")


def test_a_return_asks_for_a_reason_and_leaves_the_system_free_to_ask_again(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    _open_decisions(page)
    _ask(page)
    _as_decider(login_as, live_app, page, unique)
    page.click("button:has-text('Review and decide')")
    page.wait_for_selector(".aig-dialog input[name='aigOutcome']")
    page.check(".aig-dialog input[value='return']")
    page.click(".aig-dialog button:has-text('Record the decision')")
    page.wait_for_selector(".aig-dialog .aig-say-bad")
    page.fill("#aigRationale", "Name the data the provider sees.")
    page.click(".aig-dialog button:has-text('Record the decision')")
    page.wait_for_selector(".aig-dialog", state="detached")
    page.wait_for_selector("h2:has-text('Earlier decisions')")
    assert page.locator("button:has-text('Ask for a decision')").count() == 1
    assert "Returned for changes" in page.locator(".aig-tabpanel").inner_text()


def test_the_queue_lists_the_request_and_links_to_the_system(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    _open_decisions(page)
    _ask(page)
    page.context.clear_cookies()
    login_as("super_admin")
    page.goto(f"{live_app}/ai-governance/decisions")
    page.wait_for_selector(f"a:has-text('{unique}')")
    page.click(f"a:has-text('{unique}')")
    page.wait_for_selector("#aigDecState")


def test_the_decision_states_have_no_serious_accessibility_violations(login_as, live_app, page, run_axe, unique):
    _accepted_system(login_as, live_app, page, unique)
    _open_decisions(page)
    page.wait_for_timeout(300)
    assert run_axe() == [], "no decision"
    _ask(page)
    page.wait_for_timeout(300)
    assert run_axe() == [], "a request waiting"
    _as_decider(login_as, live_app, page, unique)
    page.click("button:has-text('Review and decide')")
    page.wait_for_selector(".aig-dialog input[name='aigOutcome']")
    page.wait_for_timeout(300)
    assert run_axe() == [], "the brief and the decision form"
    page.keyboard.press("Escape")


@pytest.mark.parametrize("who", ["dpo", "employee"])
def test_the_queue_page_has_no_serious_accessibility_violations(login_as, live_app, page, run_axe, who):
    login_as(who)
    page.goto(f"{live_app}/ai-governance/decisions")
    page.wait_for_selector("h1:has-text('Decisions')")
    page.wait_for_timeout(400)
    assert run_axe() == []
