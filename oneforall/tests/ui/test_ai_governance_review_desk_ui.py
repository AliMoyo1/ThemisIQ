"""
The review desk in a real browser (plans/2026-10-governance-rework/01 sections 5 and 6): what is left before a decision,
similar uses and what a specialist concludes about them, the questions a reviewer puts to a requester who has no account,
and the response that goes back to them, drafted, approved by another person, downloaded and recorded as sent. Every state
is checked for serious accessibility violations and for sideways scroll on a phone.
"""
from tests.ui.test_ai_governance_decisions_ui import _ask, _open_decisions
from tests.ui.test_ai_governance_pages import _accepted_system, _register_and_submit, unique  # noqa: F401


def _open_desk(page):
    page.click("#aigtab_review_desk")
    page.wait_for_selector("h2:has-text('What is left before a decision')")
    page.wait_for_selector("h2:has-text('Response to the requester')")


def _decided_system(login_as, live_app, page, name):
    """An accepted use with a standing approval; returns the address of its workspace."""
    _accepted_system(login_as, live_app, page, name)  # signed in as the DPO
    address = page.url.split("#")[0]
    _open_decisions(page)
    _ask(page)
    page.context.clear_cookies()
    login_as("super_admin")
    page.goto(address + "#decisions")
    page.wait_for_selector("button:has-text('Review and decide')")
    page.click("button:has-text('Review and decide')")
    page.wait_for_selector(".aig-dialog input[name='aigOutcome']")
    page.fill("#aigRationale", "Low tier, and the provider is registered.")
    page.fill("#aigOverride", "The provider review is booked for next week.")
    page.click(".aig-dialog button:has-text('Record the decision')")
    page.wait_for_selector("h2:has-text('Latest decision')")
    return address


def test_the_review_desk_is_for_reviewers_and_a_hash_for_it_falls_back_for_everyone_else(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    address = page.url.split("#")[0]
    assert page.locator("#aigtab_review_desk").count() == 1
    page.context.clear_cookies()
    login_as("privacy_analyst")
    page.goto(address + "#review_desk")
    page.wait_for_selector(".aig-tab.is-current:has-text('Overview')")
    assert page.locator("#aigtab_review_desk").count() == 0
    assert "What is left before a decision" not in page.locator("main, .aig-page").first.inner_text()


def test_the_outstanding_items_say_what_is_left_and_what_blocks_a_decision(login_as, live_app, page, unique, run_axe):
    _accepted_system(login_as, live_app, page, unique)
    _open_desk(page)
    page.wait_for_selector("h2:has-text('What is left before a decision') ~ ul li")
    text = page.locator(".aig-tabpanel").inner_text()
    assert "Not ready for a decision" in text
    assert "Blocks a decision" in text, "a required step that is not done says that it holds the decision"
    assert "A named owner" in text and "Done" in text, "the owner named in the request counts as done"
    assert "Nothing here approves, accepts or certifies a use." in text
    page.wait_for_timeout(300)
    assert run_axe() == []


def test_a_similar_use_is_found_and_a_specialist_says_what_it_is(login_as, live_app, page, unique, run_axe):
    _accepted_system(login_as, live_app, page, unique)
    page.context.clear_cookies()
    _accepted_system(login_as, live_app, page, unique + " pilot")  # ends on the second use, signed in as the DPO
    _open_desk(page)
    panel = page.locator("section[aria-label='Has the organization seen something like this?']")
    panel.locator("h3:has-text('Possible match')").wait_for()
    assert panel.locator(f"a:has-text('{unique}')").count() >= 1
    assert "does not apply to this one" in panel.inner_text() or "A match is a prompt to look" in panel.inner_text()
    page.wait_for_timeout(300)
    assert run_axe() == []

    page.click(f"button[aria-label='Say whether {unique} is the same use']")
    page.wait_for_selector(".aig-dialog #aigVerdict")
    assert run_axe() == [], "the verdict dialog"
    page.select_option("#aigVerdict", "same_use")
    page.fill("#aigVerdictNote", "Same product, a second team.")
    page.click(".aig-dialog button:has-text('Save')")
    page.wait_for_selector("h3:has-text('Confirmed as the same use')")
    assert "Same product, a second team." in page.locator("section[aria-label='Has the organization seen something like this?']").inner_text()
    assert page.locator(".aig-dialog").count() == 0


def test_a_reviewer_asks_the_requester_and_records_the_answer_with_where_it_came_from(login_as, live_app, page, unique, run_axe):
    _register_and_submit(login_as, live_app, page, unique)
    page.context.clear_cookies()
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/review")
    page.click(f".aig-queue-item:has-text('{unique}')")
    page.wait_for_selector(f"h2:has-text('{unique}')")  # the queue selects its first request itself: wait for this one
    page.wait_for_selector("#aigQuestions")
    assert "No question has been asked." in page.locator("section[aria-label='Questions for the requester']").inner_text()
    page.fill("#aigQuestions", "Which vendor contract covers this?")
    page.click("button:has-text('Add the questions')")
    page.wait_for_selector("li:has-text('Which vendor contract covers this?')")
    assert "Waiting for an answer" in page.locator("section[aria-label='Questions for the requester']").inner_text()
    page.wait_for_timeout(300)
    assert run_axe() == []

    page.click("button:has-text('Take the open questions out as text')")
    page.wait_for_selector(".aig-dialog textarea[readonly]")
    assert "1. Which vendor contract covers this?" in page.input_value(".aig-dialog textarea")
    assert "Nothing has been sent from here." in page.locator(".aig-dialog").inner_text()
    page.keyboard.press("Escape")

    page.goto(f"{live_app}/ai-governance/review?status=waiting")
    page.wait_for_selector(f".aig-queue-item:has-text('{unique}')")
    page.click(f".aig-queue-item:has-text('{unique}')")
    page.wait_for_selector(f"h2:has-text('{unique}')")
    page.wait_for_selector("button:has-text('Record the answer')")
    page.click("button:has-text('Record the answer')")
    page.fill("#aigAnswer", "Contract ACME-2026 covers it.")
    page.click(".aig-dialog button:has-text('Save the answer')")
    page.wait_for_selector(".aig-dialog .aig-say-bad")
    assert "where the answer came from" in page.locator(".aig-dialog").inner_text()
    page.fill("#aigAnswerSource", "Email from Pat, 12 October")
    page.click(".aig-dialog button:has-text('Save the answer')")
    page.wait_for_selector("li:has-text('Answer: Contract ACME-2026 covers it.')")
    assert "Email from Pat, 12 October" in page.locator("section[aria-label='Questions for the requester']").inner_text()

    page.goto(f"{live_app}/ai-governance/review?status=waiting")
    page.wait_for_selector("text=No request is waiting for information.")


def test_a_response_is_drafted_approved_by_another_person_downloaded_and_recorded_as_sent(login_as, live_app, page, unique, run_axe):
    address = _decided_system(login_as, live_app, page, unique)

    page.context.clear_cookies()
    login_as("dpo")
    page.goto(address + "#review_desk")
    page.wait_for_selector("button:has-text('Draft a response')")
    page.click("button:has-text('Draft a response')")
    page.wait_for_selector("#aigRespSummary")
    panel = page.locator("section[aria-label='Response to the requester']")
    assert "Approved" in panel.inner_text() and "not a certification" in panel.inner_text()
    page.wait_for_timeout(300)
    assert run_axe() == [], "a draft"

    page.fill("#aigRespSummary", "The use is approved for support agents.")
    page.fill("#aigRespDate", "2026-10-20")
    page.click("button:has-text('Save the draft')")
    page.wait_for_timeout(500)
    page.reload()
    page.wait_for_selector("#aigRespSummary")
    assert page.input_value("#aigRespSummary") == "The use is approved for support agents."
    assert page.locator("button:has-text('Download PDF')").count() == 0, "a draft is not yet a document to send"

    page.context.clear_cookies()
    login_as("super_admin")
    page.goto(address + "#review_desk")
    page.wait_for_selector("button:has-text('Approve for sending')")
    page.click("button:has-text('Approve for sending')")
    page.wait_for_selector(".aig-chip:has-text('Approved, not yet downloaded')")
    assert "Frozen:" in page.locator("section[aria-label='Response to the requester']").inner_text()
    assert page.locator("#aigRespSummary").count() == 0, "an approved response is no longer editable"
    page.wait_for_timeout(300)
    assert run_axe() == [], "an approved response"

    with page.expect_download() as taken:
        page.click("button:has-text('Download PDF')")
    download = taken.value
    assert download.suggested_filename == "ai-use-response-r1.pdf"
    with open(download.path(), "rb") as handle:
        assert handle.read(4) == b"%PDF"
    page.wait_for_selector(".aig-chip:has-text('Downloaded, not recorded as sent')")

    page.click("button:has-text('Record that it was sent')")
    page.wait_for_selector("#aigSentDate")
    page.click(".aig-dialog button:has-text('Record it')")
    page.wait_for_selector(".aig-dialog .aig-say-bad")
    page.fill("#aigSentDate", "2026-10-21")
    page.fill("#aigSentChannel", "Email to the requester")
    page.click(".aig-dialog button:has-text('Record it')")
    page.wait_for_selector(".aig-chip:text-is('Sent')")
    text = page.locator("section[aria-label='Response to the requester']").inner_text()
    assert "recorded as sent on 2026-10-21" in text and "Email to the requester" in text
    assert page.locator("button:has-text('Record that it was sent')").count() == 0
    page.wait_for_timeout(300)
    assert run_axe() == [], "a response recorded as sent"


def test_the_review_desk_fits_a_phone(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    page.set_viewport_size({"width": 375, "height": 812})
    _open_desk(page)
    page.wait_for_selector("h2:has-text('What is left before a decision') ~ ul li")
    page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
