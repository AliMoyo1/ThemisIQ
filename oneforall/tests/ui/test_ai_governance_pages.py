"""
AI governance G2 in a real browser: a specialist author describes an AI use and resumes it, a reviewer accepts it, and
the accepted use opens as a workspace whose tabs work from the keyboard. Every page is checked for serious
accessibility violations and for sideways scroll on a phone. AI Governance is for specialist roles only (owner decision,
2026-10-20): the author is a risk owner, and a general employee is refused every page.
"""
import re
import uuid

import pytest


@pytest.fixture
def unique():
    return "AI use " + uuid.uuid4().hex[:8]


AUTHOR = "risk_owner"  # holds ai_use.intake_create; the DPO reviews


def _fill_essentials(page, name):
    page.fill("#q_name", name)
    page.fill("#q_purpose", "Summarize support tickets for the team")
    page.select_option("#q_deployment", "vendor_service")
    page.fill("#q_provider_name", "Acme AI")
    page.fill("#q_intended_users", "Support agents")
    page.check("#q_data_categories input[value='internal']")


def _register_and_submit(login_as, live_app, page, name):
    login_as(AUTHOR)
    page.goto(f"{live_app}/ai-governance/register")
    page.wait_for_selector("#q_name")
    _fill_essentials(page, name)
    page.click("button:has-text('Continue')")
    page.wait_for_selector("#q_affected_people")
    page.check("#q_affected_people input[value='employees']")
    page.select_option("#q_autonomy", "recommend")
    page.click("button:has-text('Continue')")
    page.wait_for_selector("button:has-text('Submit for review')")
    page.click("button:has-text('Submit for review')")
    page.wait_for_selector(".aig-banner:has-text('waiting for review')")


def test_the_first_screen_starts_with_the_author_as_owner_and_asks_only_the_essentials(login_as, live_app, page):
    login_as(AUTHOR)
    page.goto(f"{live_app}/ai-governance/register")
    page.wait_for_selector("#q_name")
    assert "Chosen:" in page.locator("#q_owner_user_id_shown").inner_text()
    assert page.locator("#q_business_unit_id").input_value() != ""
    assert page.locator("#q_affected_people").is_hidden() or page.locator(".aig-panel-step").nth(1).is_hidden()
    assert page.locator("button:has-text('Submit for review')").count() == 0, "submitting is for the last step"


def test_a_required_answer_missing_is_named_and_nothing_is_lost(login_as, live_app, page, unique):
    login_as(AUTHOR)
    page.goto(f"{live_app}/ai-governance/register")
    page.wait_for_selector("#q_name")
    page.fill("#q_name", unique)
    page.click("button:has-text('Continue')")
    page.wait_for_selector("#q_affected_people")
    page.click("button:has-text('Continue')")
    page.wait_for_selector("button:has-text('Submit for review')")
    page.click("button:has-text('Submit for review')")
    summary = page.locator(".aig-errorsummary")
    summary.wait_for(state="visible")
    text = summary.inner_text()
    assert "purpose" in text and "kinds of data" in text and "intended users" in text
    page.click("button:has-text('Back')")
    page.click("button:has-text('Back')")
    assert page.locator("#q_name").input_value() == unique, "what was typed is still there"


def test_a_draft_saved_at_the_first_step_is_there_when_the_person_comes_back(login_as, live_app, page, unique):
    login_as(AUTHOR)
    page.goto(f"{live_app}/ai-governance/register")
    page.wait_for_selector("#q_name")
    _fill_essentials(page, unique)
    page.click("button:has-text('Save draft')")
    page.wait_for_selector(".aig-say-good")
    assert re.search(r"/ai-governance/requests/\d+$", page.url), "the address is now the draft's own"
    page.goto(f"{live_app}/ai-governance/requests")
    page.wait_for_selector(f"a:has-text('{unique}')")
    page.click(f"a:has-text('{unique}')")
    page.wait_for_selector("#q_name")
    assert page.locator("#q_name").input_value() == unique
    assert page.locator("#q_purpose").input_value().startswith("Summarize support tickets")
    assert page.locator("#q_data_categories input[value='internal']").is_checked()


def test_the_journey_from_a_specialist_draft_to_an_accepted_ai_system(login_as, live_app, page, unique):
    _register_and_submit(login_as, live_app, page, unique)
    page.goto(f"{live_app}/ai-governance/requests")
    row = page.locator("tr", has=page.locator(f"a:has-text('{unique}')"))
    assert "Waiting for review" in row.inner_text()

    page.context.clear_cookies()
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/review")
    page.wait_for_selector(f".aig-queue-item:has-text('{unique}')")
    page.click(f".aig-queue-item:has-text('{unique}')")
    page.wait_for_selector("h2:has-text('" + unique + "')")
    assert "Provisional tier" in page.locator(".aig-detail").inner_text()
    page.fill("#aigNewVendor", "Acme AI")
    page.click("button:has-text('Accept')")
    page.wait_for_selector(".aig-say-good:has-text('Accepted')")

    page.goto(f"{live_app}/ai-governance/systems?q={unique.replace(' ', '+')}")
    page.wait_for_selector(f"a:has-text('{unique}')")
    page.click(f"a:has-text('{unique}')")
    page.wait_for_selector(".aig-tab.is-current:has-text('Overview')")
    assert unique in page.locator("h1").inner_text()
    assert "Summarize support tickets" in page.locator(".aig-tabpanel").inner_text()


def test_the_workspace_tabs_work_from_the_keyboard_and_say_what_they_cannot_show(login_as, live_app, page, unique):
    _register_and_submit(login_as, live_app, page, unique)
    page.context.clear_cookies()
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/review")
    page.click(f".aig-queue-item:has-text('{unique}')")
    page.wait_for_selector(f"h2:has-text('{unique}')")
    page.click("button:has-text('Accept')")
    page.wait_for_selector(".aig-say-good:has-text('Accepted')")
    page.goto(f"{live_app}/ai-governance/systems?q={unique.replace(' ', '+')}")
    page.click(f"a:has-text('{unique}')")
    page.wait_for_selector(".aig-tab.is-current:has-text('Overview')")

    page.focus("#aigtab_overview")
    page.keyboard.press("ArrowRight")
    page.wait_for_selector(".aig-tab.is-current:has-text('Review desk')")
    assert page.evaluate("document.activeElement.id") == "aigtab_review_desk"
    page.keyboard.press("ArrowRight")
    page.wait_for_selector(".aig-tab.is-current:has-text('Assessments')")
    assert page.evaluate("document.activeElement.id") == "aigtab_assessments"
    page.wait_for_selector("h2:has-text('AI impact assessments')")
    page.click("#aigtab_decisions")
    page.wait_for_selector("text=No decision has been recorded")
    page.click("#aigtab_monitoring")
    page.wait_for_selector("h2:has-text('What is measured')")
    assert "Not measured" in page.locator(".aig-tabpanel").inner_text()
    page.wait_for_selector("text=No evaluation has been recorded for this use.")
    page.click("#aigtab_evidence")
    page.wait_for_selector("text=No evidence is attached")
    page.click("#aigtab_activity")
    page.wait_for_selector("li:has-text('Accepted into the inventory')")
    page.keyboard.press("End")  # tab buttons also respond to Home and End
    assert page.url.endswith("#activity")


def test_a_reviewer_adopts_a_tier_and_retires_the_use_from_its_workspace(login_as, live_app, page, unique):
    _register_and_submit(login_as, live_app, page, unique)
    page.context.clear_cookies()
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/review")
    page.click(f".aig-queue-item:has-text('{unique}')")
    page.wait_for_selector(f"h2:has-text('{unique}')")
    page.click("button:has-text('Accept')")
    page.wait_for_selector(".aig-say-good:has-text('Accepted')")
    page.goto(f"{live_app}/ai-governance/systems?q={unique.replace(' ', '+')}")
    page.click(f"a:has-text('{unique}')")
    page.wait_for_selector("button:has-text('Adopt a tier')")

    page.click("button:has-text('Adopt a tier')")
    page.select_option("#aigDlgExtra", "moderate")
    page.fill("#aigDlgReason", "The vendor sees ticket text.")
    page.click(".aig-dialog button:has-text('Adopt')")
    page.wait_for_selector("text=Adopted by a reviewer")
    assert "The vendor sees ticket text." in page.locator(".aig-tabpanel").inner_text()

    page.click("button:has-text('Retire')")
    page.fill("#aigDlgReason", "Contract ended.")
    page.click(".aig-dialog button:has-text('Retire')")
    page.wait_for_selector("button:has-text('Restore')")
    assert "Retired" in page.locator("#aigHeader").inner_text()
    page.keyboard.press("Escape")


def test_a_general_employee_is_refused_every_ai_governance_page(login_as, live_app, page):
    login_as("employee")
    for path in ("/ai-governance/", "/ai-governance/review", "/ai-governance/systems", "/ai-governance/register",
                 "/ai-governance/requests"):
        assert page.goto(f"{live_app}{path}").status == 403, path


def test_an_author_finds_the_way_to_register_from_the_inventory(login_as, live_app, page):
    login_as(AUTHOR)
    page.goto(f"{live_app}/ai-governance/systems")
    page.wait_for_selector("h1:has-text('AI Systems')")
    assert page.locator("a[href='/ai-governance/register']").count() >= 1


def test_the_inventory_filters_survive_a_reload_and_an_empty_result_offers_a_way_out(login_as, live_app, page):
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/systems?q=zzz-no-such-use")
    page.wait_for_selector(".aig-empty:has-text('No AI systems match these filters')")
    page.click("button:has-text('Clear filters')")
    page.wait_for_selector(".aig-table, .aig-empty:has-text('No AI systems are registered yet')")
    assert "q=" not in page.url


def test_overview_uses_the_connected_silver_card_layout(login_as, live_app, page):
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/")
    page.wait_for_selector(".aig-overview-section .aig-card")
    assert page.locator(".aig-overview-section > .aig-cards > .aig-card").count() == 4
    assert page.locator(".aig-cards-followup > .aig-card").count() == 3
    assert page.locator(".aig-page .aig-card-link").count() == 7
    assert page.locator("#aigSignalHeading").inner_text() == "Connected overview"
    assert page.evaluate("getComputedStyle(document.body).getPropertyValue('--accent').trim()") == "#53636c"
    assert page.evaluate("getComputedStyle(document.body).getPropertyValue('--accent-ink').trim()") == "#43525a"
    assert page.locator(".aig-card").first.evaluate("el => getComputedStyle(el).backdropFilter") != "none"
    assert page.locator(".aig-card").first.evaluate("el => getComputedStyle(el, '::before').content") != "none"
    page.emulate_media(reduced_motion="reduce")
    assert page.locator(".aig-card").first.evaluate("el => getComputedStyle(el).animationName") == "none"


@pytest.mark.parametrize("path, who, ready", [
    ("/ai-governance/", "dpo", ".aig-card"),
    ("/ai-governance/systems", "dpo", "h1:has-text('AI Systems')"),
    ("/ai-governance/monitoring", "dpo", "h1:has-text('Monitoring')"),
    ("/ai-governance/register", AUTHOR, "#q_name"),
    ("/ai-governance/requests", AUTHOR, "h1:has-text('My requests')"),
    ("/ai-governance/review", "dpo", "h1:has-text('Review requests')"),
])
def test_each_page_has_no_serious_accessibility_violations(login_as, live_app, page, run_axe, path, who, ready):
    login_as(who)
    page.goto(f"{live_app}{path}")
    page.wait_for_selector(ready)
    page.wait_for_timeout(300)
    assert run_axe() == []


@pytest.mark.parametrize("path, who", [("/ai-governance/", "dpo"), ("/ai-governance/systems", "dpo"), ("/ai-governance/monitoring", "dpo"),
                                       ("/ai-governance/register", AUTHOR), ("/ai-governance/review", "dpo")])
def test_each_page_fits_a_phone_without_sideways_scroll(login_as, live_app, page, path, who):
    login_as(who)
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{live_app}{path}")
    page.wait_for_selector("h1")
    page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


def _accepted_system(login_as, live_app, page, name):
    _register_and_submit(login_as, live_app, page, name)
    page.context.clear_cookies()
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/review")
    page.click(f".aig-queue-item:has-text('{name}')")
    page.wait_for_selector(f"h2:has-text('{name}')")  # the queue selects its first request itself: wait for this one
    page.click("button:has-text('Accept')")
    page.wait_for_selector(".aig-say-good:has-text('Accepted')")
    page.goto(f"{live_app}/ai-governance/systems?q={name.replace(' ', '+')}")
    page.click(f"a:has-text('{name}')")
    page.wait_for_selector(".aig-tab.is-current:has-text('Overview')")


def test_every_workspace_tab_has_no_serious_accessibility_violations(login_as, live_app, page, run_axe, unique):
    _accepted_system(login_as, live_app, page, unique)
    for tab in ("overview", "review_desk", "assessments", "risks_controls", "data_vendors", "evidence", "decisions", "monitoring", "activity"):
        page.click(f"#aigtab_{tab}")
        page.wait_for_selector(f"#aigtab_{tab}[aria-selected='true']")
        page.wait_for_timeout(400)
        assert run_axe() == [], tab


def test_the_dialogs_trap_focus_and_close_with_escape(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    page.click("button:has-text('Edit profile')")
    page.locator(".aig-dialog").wait_for()
    inside = "document.querySelector('.aig-dialog').contains(document.activeElement)"
    assert page.evaluate(inside)
    for _ in range(40):  # tabbing never leaves the dialog
        page.keyboard.press("Tab")
        assert page.evaluate(inside)
    page.keyboard.press("Escape")
    assert page.locator(".aig-dialog").count() == 0
    assert page.evaluate("document.activeElement.textContent.trim()") == "Edit profile", "focus returns to what opened it"


def test_a_profile_edit_from_the_workspace_changes_the_tier_on_the_page(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    assert "Needs review" in page.locator("#aigHeader").inner_text(), "two screening answers were left open"
    page.click("button:has-text('Edit profile')")
    page.check("#pf_data_categories input[value='sensitive_personal']")
    page.check("#pf_affected_people input[value='customers']")
    page.click(".aig-dialog button:has-text('Save')")
    page.wait_for_selector(".aig-dialog", state="detached")
    page.wait_for_selector("#aigHeader .aig-tier-elevated")
    assert "special-category" in page.locator(".aig-tabpanel").inner_text()
