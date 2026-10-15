"""
Naming the reviewer of a request and the decider of a decision request, in a real browser
(plans/2026-10-governance-rework/11 step 4). Nobody named is the default; naming one person says so on the page.
"""
from tests.ui.test_ai_governance_decisions_ui import _ask, _open_decisions
from tests.ui.test_ai_governance_pages import _accepted_system, _register_and_submit, unique  # noqa: F401


def test_a_reviewer_names_who_reviews_a_request_and_the_name_is_still_there_after_a_reload(login_as, live_app, page, unique):
    _register_and_submit(login_as, live_app, page, unique)
    page.context.clear_cookies()
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/review")
    page.click(f".aig-queue-item:has-text('{unique}')")
    page.wait_for_selector(f"h2:has-text('{unique}')")
    page.wait_for_selector("h3:has-text('Who reviews it')")
    assert "Nobody is named" in page.locator("section[aria-labelledby='aigAssignH']").inner_text()
    page.wait_for_selector("#aigAssignee option:nth-child(2)", state="attached", timeout=8000)
    name = page.locator("#aigAssignee option").nth(1).inner_text()
    page.select_option("#aigAssignee", index=1)
    page.click("section[aria-labelledby='aigAssignH'] button:has-text('Save')")
    page.wait_for_selector("section[aria-labelledby='aigAssignH'] .aig-say-good", timeout=8000)
    assert f"Assigned to {name}" in page.locator("section[aria-labelledby='aigAssignH']").inner_text()

    page.reload()
    page.click(f".aig-queue-item:has-text('{unique}')")
    page.wait_for_selector("h3:has-text('Who reviews it')")
    assert f"Assigned to {name}" in page.locator("section[aria-labelledby='aigAssignH']").inner_text()
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_a_reviewer_names_who_decides_a_request_from_the_decision_desk(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)  # signed in as the DPO, who is about to be the asker
    _open_decisions(page)
    _ask(page)
    assert "Nobody is named" in page.locator("#aigDecNamed").inner_text()
    page.click("#aigDecNameBtn")
    page.wait_for_selector(".aig-dialog #aigDecAssignee")
    page.wait_for_selector(".aig-dialog #aigDecAssignee option:nth-child(2)", state="attached", timeout=8000)
    name = page.locator(".aig-dialog #aigDecAssignee option").nth(1).inner_text()
    assert name != "", "somebody other than the asker can be named"
    page.select_option(".aig-dialog #aigDecAssignee", index=1)
    page.click(".aig-dialog button:has-text('Save')")
    page.wait_for_selector("#aigDecNamed:has-text('Named to decide')", timeout=8000)
    assert name in page.locator("#aigDecNamed").inner_text()
    assert page.locator("#aigDecNameBtn:has-text('Change who decides')").count() == 1
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
