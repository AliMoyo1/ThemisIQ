"""
The Command Centre opens with what needs action, what changed, what lacks proof and what can be reported, and when
the read fails it says so in words instead of showing sample figures (plan 04 sections 1, 2 and 7).
"""
import json


def test_the_first_screen_answers_the_four_questions(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/")
    page.wait_for_selector("#ccFirstScreenGrid .panel-card", timeout=15000)
    text = page.locator("#ccFirstScreen").inner_text().lower()
    for question in ("what needs action today", "what changed", "what lacks proof", "what can be reported"):
        assert question in text, question
    assert page.locator("#ccFirstScreenGrid .panel-card").count() == 4
    assert not page.locator("#ccFirstScreenFailed").is_visible()
    # a link goes to the list that holds the number
    hrefs = page.locator("#ccFirstScreenGrid a").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert "/my-work" in hrefs and "/reports" in hrefs


def test_a_failed_read_is_said_in_words_and_no_panel_shows_a_number(login_as, live_app):
    page = login_as("compliance_manager")
    page.route("**/api/command-centre/first-screen", lambda route: route.fulfill(
        status=500, content_type="application/json", body=json.dumps({"error": "boom"})))
    page.goto(f"{live_app}/")
    failed = page.locator("#ccFirstScreenFailed")
    failed.wait_for(state="visible", timeout=15000)
    assert "could not be read" in failed.inner_text()
    assert failed.get_attribute("role") == "alert"
    assert page.locator("#ccFirstScreenGrid .panel-card").count() == 0

    page.unroute("**/api/command-centre/first-screen")
    page.click("#ccFirstScreenRetry")
    page.wait_for_selector("#ccFirstScreenGrid .panel-card", timeout=15000)
    assert not failed.is_visible()


def test_needs_attention_card_discloses_a_partial_count(login_as, live_app):
    page = login_as("compliance_manager")
    page.route("**/api/command-centre/attention", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps({"state": "partial", "open": 3})))
    page.goto(f"{live_app}/")
    page.locator("#ccAttentionOpen").filter(has_text="≥3").wait_for(timeout=15000)
    assert "Partial count" in page.locator("#ccAttentionNote").inner_text()
    assert page.locator(".cc-attention-card").get_attribute("href") == "/governance/attention/"


def test_unscoped_platform_admin_is_not_offered_an_unreadable_attention_card(login_as, live_app):
    page = login_as("super_admin")
    assert page.locator(".cc-attention-card").count() == 0
    assert page.locator("#ccAttentionOpen").count() == 0
    assert not any("/api/command-centre/attention" in error for error in page.console_errors)
