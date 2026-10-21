"""
Real-browser checks for plan 04 slices 4B to 4D: a report button proves a saved run, the saved run shows what it was
generated from, a failure is said in words, and the topbar search keeps its deep link and shows what a result is.
"""
import json
import re


def _generate_privacy_overview(page, live_app):
    page.goto(f"{live_app}/reports")
    page.wait_for_selector('[data-quick="privacy_overview"]')
    page.click('[data-quick="privacy_overview"]')
    page.wait_for_selector("#reportViewer", state="visible", timeout=10000)


def test_a_quick_report_opens_as_generated_and_runs_again_with_a_change_summary(login_as, live_app):
    page = login_as("compliance_manager")
    _generate_privacy_overview(page, live_app)

    viewer = page.locator("#reportViewer")
    text = viewer.inner_text().lower()  # headings are set in capitals by the stylesheet
    assert "saved as generated" in text
    assert "privacy overview" in text and "sources read" in text
    assert "what this report cannot tell you" in text
    assert re.search(r"SHA-256 [0-9a-f]{64}", page.locator("#viewerFoot").inner_text())
    assert page.locator("#viewerExport").is_visible()

    page.click("#viewerRerun")
    page.locator("#viewerChanges").filter(has_text="Since run #").wait_for(timeout=10000)
    changes = page.locator("#viewerChanges").inner_text()
    assert "unchanged" in changes and "Open that run" in changes


def test_a_failed_generation_is_said_in_words_and_nothing_is_shown_as_a_report(login_as, live_app):
    page = login_as("compliance_manager")
    page.route("**/api/reports/quick-run", lambda route: route.fulfill(
        status=500, content_type="application/json",
        body=json.dumps({"error": "The report could not be generated. Nothing was saved as a result."})))
    page.goto(f"{live_app}/reports")
    page.wait_for_selector('[data-quick="risk_report"]')
    page.click('[data-quick="risk_report"]')
    notice = page.locator("#reportNotice")
    notice.wait_for(state="visible", timeout=10000)
    assert "Nothing was saved as a result" in notice.inner_text()
    assert notice.get_attribute("role") == "alert"
    assert not page.locator("#reportViewer").is_visible()


def test_a_run_opens_from_its_id_in_the_address(login_as, live_app):
    page = login_as("compliance_manager")
    run = page.evaluate("""async () => {
        const r = await fetch('/api/reports/quick-run', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                          body: JSON.stringify({report_type: 'audit_status'})});
        return r.json();
    }""")
    assert run["frozen"] is True
    page.goto(f"{live_app}/reports?run={run['run_id']}")
    page.wait_for_selector("#reportViewer", state="visible", timeout=10000)
    assert "Audit Status" in page.locator("#viewerMeta").inner_text() or "Audit Status" in page.locator("#viewerTitle").inner_text()
    assert f"Run #{run['run_id']}" in page.locator("#viewerMeta").inner_text()


def test_the_continuity_report_buttons_end_in_a_saved_run(login_as, live_app):
    page = login_as("bcm_manager")
    page.goto(f"{live_app}/bcm/reports")
    page.wait_for_selector("text=BIA Coverage Report")
    page.click("text=BIA Coverage Report")
    page.wait_for_url(re.compile(r".*/reports\?run=\d+$"), timeout=15000)
    page.wait_for_selector("#reportViewer", state="visible", timeout=10000)
    assert "BCM: Analysis coverage" in page.locator("#viewerMeta").inner_text() + page.locator("#viewerTitle").inner_text()


def test_the_aria_report_button_is_not_a_timer(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/aria/")
    page.wait_for_selector("text=Generate Report")
    page.click("text=Generate Report")
    page.wait_for_url(re.compile(r".*/reports\?run=\d+$"), timeout=15000)
    page.wait_for_selector("#reportViewer", state="visible", timeout=10000)
    assert "Compliance Summary" in page.locator("#viewerMeta").inner_text() + page.locator("#viewerTitle").inner_text()


def test_the_topbar_search_keeps_the_deep_link_and_shows_what_a_result_is(login_as, live_app):
    page = login_as("compliance_manager")
    page.route("**/api/search?q=*", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"total": 1, "results": [{
            "module": "aria", "type": "control", "id": 12, "title": "AC-1 - Access control policy",
            "subtitle": "ISO 27001", "link": "/aria/?open=control:12", "status": "Implemented", "date": "2026-10-01",
            "business_unit": "Unit A", "snippet": "Access is granted on need."}]})))
    page.goto(f"{live_app}/")
    page.fill("#globalSearch", "access")
    page.wait_for_selector("#searchResults a.search-result", timeout=10000)
    link = page.locator("#searchResults a.search-result").first
    assert link.get_attribute("href") == "/aria/?open=control:12"
    shown = link.inner_text()
    assert "Implemented" in shown and "2026-10-01" in shown and "Unit A" in shown and "Access is granted on need." in shown
