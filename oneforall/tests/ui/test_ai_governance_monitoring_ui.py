"""
AI governance G5 in a real browser: the Monitoring tab and recorded evaluation runs, "Explain this status", and the
regulatory change queue. Every state is checked for serious accessibility violations.
"""
import pytest

from tests.ui.test_ai_governance_pages import _accepted_system, unique  # noqa: F401


def _open_monitoring(page):
    page.click("#aigtab_monitoring")
    page.wait_for_selector("h2:has-text('What is measured')")


def _record_run(page, name="Citation check", scores="citation validity: 97.5 needs 95", status="completed"):
    page.click("button:has-text('Record an evaluation run')")
    page.fill("#aigEv_name", name)
    page.fill("#aigEv_test_set_name", "aria-citations")
    page.fill("#aigEv_test_set_version", "v3")
    page.fill("#aigEv_rubric_version", "r2")
    page.fill("#aigEv_subject_version", "assistant 2026-09")
    page.select_option("#aigEv_status", status)
    page.fill("#aigEv_finished", "2026-10-01")
    page.fill("#aigEv_scores", scores)
    page.click(".aig-dialog button:has-text('Record the run')")
    page.wait_for_selector(".aig-dialog", state="detached")


def test_a_new_use_says_nothing_is_measured_for_each_source(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    _open_monitoring(page)
    text = page.locator(".aig-tabpanel").inner_text()
    assert "Not measured" in text and "No evaluation has been recorded for this use." in text
    assert "No AI controls are recorded" in text or "do not have access to AI management" in text


def test_a_run_is_recorded_read_back_as_a_pass_and_accepted(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    _open_monitoring(page)
    _record_run(page)
    page.wait_for_selector("td:has-text('Citation check')")
    row = page.locator("tr", has=page.locator("td:has-text('Citation check')"))
    assert "Passed" in row.inner_text() and "assistant 2026-09" in row.inner_text()
    page.click("button[aria-label^='Accept the run']")
    page.fill("#aigEvNote", "The citations all resolve.")
    page.click(".aig-dialog button:has-text('Accept')")
    page.wait_for_selector("td:has-text('Accepted'), .aig-chip:has-text('Accepted')")


def test_a_failed_run_is_never_a_pass_and_opens_a_finding_that_is_only_a_task(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    _open_monitoring(page)
    _record_run(page, name="Leak check", scores="leakage: 70 needs 100")
    row = page.locator("tr", has=page.locator("td:has-text('Leak check')"))
    row.wait_for()
    assert "Failed" in row.inner_text() and "Passed" not in row.inner_text()
    page.wait_for_selector("h2:has-text('What is measured')")
    assert "Look at this" in page.locator(".aig-tabpanel").inner_text()
    page.click("button[aria-label^='Open a finding about the run']")
    page.fill("#aigEvNote", "Another unit's titles appeared in the answers.")
    page.click(".aig-dialog button:has-text('Open the finding')")
    page.wait_for_selector(".aig-chip:has-text('Finding opened')")


def test_a_bad_run_names_what_is_wrong_and_keeps_the_dialog_open(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    _open_monitoring(page)
    page.click("button:has-text('Record an evaluation run')")
    page.click(".aig-dialog button:has-text('Record the run')")
    page.wait_for_selector(".aig-dialog .aig-say-bad")
    assert "Give the" in page.locator(".aig-dialog").inner_text()


def test_the_explanation_cites_facts_and_says_when_ai_is_not_available(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    page.click("button:has-text('Explain this status')")
    page.wait_for_selector(".aig-dialog li")
    assert "Built from the rules" in page.locator(".aig-dialog").inner_text()
    assert page.locator(".aig-dialog li").count() >= 3
    page.click(".aig-dialog button:has-text('Rephrase with AI')")
    page.wait_for_selector(".aig-dialog .aig-note-warn")
    assert "not configured" in page.locator(".aig-dialog").inner_text()
    page.keyboard.press("Escape")


def test_a_regulatory_change_is_proposed_for_a_use_in_its_jurisdiction_and_confirmed(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)  # the DPO, who reviews AI uses but does not post to the inbox
    page.click("button:has-text('Edit profile')")
    page.check("#pf_jurisdictions input[value='EU']")
    page.click(".aig-dialog button:has-text('Save')")
    page.wait_for_selector(".aig-dialog", state="detached")
    page.context.clear_cookies()
    login_as("super_admin")
    page.goto(f"{live_app}/ai-governance/regulatory")
    page.wait_for_selector("h1:has-text('Regulatory changes')")
    page.evaluate("""ApiClient.request('/governance/api/regulatory-updates', {method: 'POST', body: {
        framework_name: 'EU AI Act', title: 'Guidance %s', summary: 'Clarifies Article 5.',
        effective_date: '2026-12-01', severity: 'high'}})""" % unique[-8:])
    page.click("button:has-text('Look for AI uses affected')")
    page.wait_for_selector(f"td:has-text('Guidance {unique[-8:]}')")
    row = page.locator("tr", has=page.locator(f"td:has-text('Guidance {unique[-8:]}')")).filter(has_text=unique)
    row.wait_for()
    row.locator("button:has-text('Confirm')").click()
    page.fill("#aigRegReason", "Concerns our EU customers.")
    page.click(".aig-dialog button:has-text('Confirm')")
    page.wait_for_selector(".aig-dialog", state="detached")
    page.select_option("#aigRegStatus", "confirmed")
    page.wait_for_selector(f"td:has-text('Guidance {unique[-8:]}')")


def test_the_monitoring_tab_and_the_regulatory_page_have_no_serious_accessibility_violations(login_as, live_app, page, run_axe, unique):
    _accepted_system(login_as, live_app, page, unique)
    _open_monitoring(page)
    _record_run(page, name="A11y run")
    page.wait_for_selector("td:has-text('A11y run')")
    page.wait_for_timeout(300)
    assert run_axe() == [], "monitoring with a run"
    page.click("button:has-text('Record an evaluation run')")
    page.wait_for_selector(".aig-dialog")
    page.wait_for_timeout(300)
    assert run_axe() == [], "the record dialog"
    page.keyboard.press("Escape")
    page.goto(f"{live_app}/ai-governance/regulatory")
    page.wait_for_selector("h1:has-text('Regulatory changes')")
    page.wait_for_timeout(300)
    assert run_axe() == [], "the regulatory queue"


@pytest.mark.parametrize("who", ["dpo", "employee"])
def test_the_regulatory_page_opens_for_reviewers_and_staff(login_as, live_app, page, who):
    login_as(who)
    assert page.goto(f"{live_app}/ai-governance/regulatory").status == 200
    page.wait_for_selector("h1:has-text('Regulatory changes')")
    page.wait_for_selector("#aigRegulatory .aig-empty, #aigRegulatory .aig-table")
    assert page.locator("button:has-text('Look for AI uses affected')").is_visible() == (who == "dpo")
