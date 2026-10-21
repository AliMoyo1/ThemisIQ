"""
The predictive risk panel on the Command Centre says what its number was made from and lets a reviewer dispute a
signal beside it (plans/2026-10-governance-rework/04 section 9, acceptance scenario 5).
"""
import database


def _clean(ref):
    db = database.get_db()
    try:
        db.execute("DELETE FROM ai_risk_prediction_notes")
        db.execute("DELETE FROM ai_risk_predictions")
        db.execute("DELETE FROM sentinel_breaches WHERE ref_number = %s", (ref,))
        db.commit()
    finally:
        db.close()


def test_why_this_number_lists_the_records_and_records_a_dispute(login_as, live_app):
    ref = "BR-UI-TRACE"
    db = database.get_db()
    try:
        cur = db.execute(
            "INSERT INTO sentinel_breaches (ref_number, title, severity, status, discovery_date) "
            "VALUES (%s, 'Laptop with customer data lost in transit', 'critical', 'open', date('now'))", (ref,))
        db.commit()
        breach_id = cur.lastrowid
    finally:
        db.close()
    try:
        page = login_as("super_admin")
        page.goto(f"{live_app}/")
        page.wait_for_selector("#prPanel", state="visible", timeout=15000)
        # recompute so the prediction is made from the breach seeded above and not from a cached earlier one
        page.evaluate("async () => { await loadPredictiveRisk(true); }")
        if not page.locator("#prBody").is_visible():
            page.click("#prBar")
        page.wait_for_selector("#prTraceBtn", state="visible", timeout=8000)

        page.click("#prTraceBtn")
        page.wait_for_selector("#prTrace section", timeout=8000)
        assert page.locator("#prTrace section").count() == 6
        text = page.locator("#prTrace").inner_text()
        assert "not a decision" in text and "tanh" in text
        assert "Open Sentinel breaches" in text and "Open GRID findings" in text
        assert "A control with documentation but another status is not implemented." in text

        link = page.locator("#prTrace a", has_text="Laptop with customer data lost in transit")
        assert link.count() == 1
        assert link.get_attribute("href") == f"/sentinel/?open=breach:{breach_id}"

        # a dispute is a note beside the number
        first = page.locator("#prTrace section").first
        assert not first.locator("input").is_visible(), "the form is tucked away until it is asked for"
        first.locator("summary").click()
        first.locator("input").fill("This breach was recovered and should not count.")
        first.locator("button", has_text="Record the dispute").click()
        page.wait_for_selector("text=Disputed by", timeout=8000)
        assert "This breach was recovered and should not count." in page.locator("#prTrace").inner_text()

        db = database.get_db()
        try:
            notes = db.execute("SELECT signal, body FROM ai_risk_prediction_notes").fetchall()
            assert [(n["signal"], n["body"]) for n in notes] == [
                ("breaches", "This breach was recovered and should not count.")]
        finally:
            db.close()
        assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
    finally:
        _clean(ref)


def test_the_button_says_so_when_the_trace_cannot_be_read(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/")
    page.wait_for_selector("#prPanel", state="visible", timeout=15000)
    if not page.locator("#prBody").is_visible():
        page.click("#prBar")
    page.wait_for_selector("#prTraceBtn", state="visible", timeout=8000)
    page.route("**/api/predictive-risk/trace**", lambda route: route.fulfill(
        status=500, content_type="application/json", body='{"error": "The trace store is down."}'))
    page.click("#prTraceBtn")
    page.wait_for_selector("#prTrace:has-text('The trace store is down.')", timeout=8000)
    assert page.locator("#prTrace section").count() == 0
    assert page.locator("#prTraceBtn").is_enabled(), "the reviewer can try again"


def test_the_open_trace_has_no_serious_accessibility_violations(login_as, live_app, run_axe):
    page = login_as("super_admin")
    page.goto(f"{live_app}/")
    page.wait_for_selector("#prPanel", state="visible", timeout=15000)
    if not page.locator("#prBody").is_visible():
        page.click("#prBar")
    page.wait_for_selector("#prTraceBtn", state="visible", timeout=8000)
    page.click("#prTraceBtn")
    page.wait_for_selector("#prTrace section", timeout=8000)
    page.locator("#prTrace section").first.locator("summary").click()
    violations = run_axe()
    assert not violations, "; ".join(f"{v['id']}: {v['help']}" for v in violations)
