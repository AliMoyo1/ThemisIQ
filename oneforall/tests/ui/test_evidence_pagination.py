"""Evidence Vault pager: every item is reachable past the old 200 row cap (PHASE-1A.md, T6)."""
import database

PROBES = 230


def _status_is(page, text):
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    try:
        page.wait_for_function(
            "text => document.getElementById('evPagerStatus').textContent === text", arg=text, timeout=10000
        )
    except PlaywrightTimeout:
        seen = page.text_content("#evPagerStatus")
        raise AssertionError(f"pager status: expected {text!r}, saw {seen!r}") from None


def test_every_item_is_reachable_through_the_pager(login_as, live_app, synthetic_tenant):
    org = synthetic_tenant["org_id"]
    uploader = synthetic_tenant["users"]["compliance_manager"]["user_id"]
    db = database.get_db()
    try:
        for i in range(1, PROBES + 1):
            db.execute(
                "INSERT INTO evidence_items (title, org_id, uploaded_by, status, updated_at) "
                "VALUES (%s,%s,%s,'current','2026-01-01 00:00:00')",
                (f"Pagination probe {i:03d}", org, uploader),
            )
        db.commit()
    finally:
        db.close()
    try:
        page = login_as("compliance_manager")
        page.goto(f"{live_app}/evidence")
        page.wait_for_load_state("networkidle")
        # The search box debounces by 300 ms and then resets to page 1; wait for that request to land.
        with page.expect_response(lambda r: "/evidence/api/items?" in r.url and "q=Pagination" in r.url):
            page.locator("#searchInput").press_sequentially("Pagination probe")
        _status_is(page, f"Showing 1 to 25 of {PROBES}")
        assert page.get_attribute("#evPrevPage", "aria-disabled") == "true"

        # Keyboard operation: Enter on the focused Next button advances one page.
        page.focus("#evNextPage")
        page.keyboard.press("Enter")
        _status_is(page, f"Showing 26 to 50 of {PROBES}")

        for n in range(3, 11):
            page.click("#evNextPage")
            _status_is(page, f"Showing {(n - 1) * 25 + 1} to {min(n * 25, PROBES)} of {PROBES}")
        assert page.get_attribute("#evNextPage", "aria-disabled") == "true"
        assert page.locator("#evidenceGrid", has_text="Pagination probe 001").count() == 1

        page.click("#evPrevPage")
        _status_is(page, f"Showing 201 to 225 of {PROBES}")

        # A new search starts again from page 1 and hides the buttons when everything fits.
        page.locator("#searchInput").fill("")
        page.locator("#searchInput").press_sequentially("probe 22")
        _status_is(page, "Showing 1 to 10 of 10")
        assert not page.locator("#evPagerButtons").is_visible()
    finally:
        db = database.get_db()
        try:
            db.execute("DELETE FROM evidence_items WHERE title LIKE 'Pagination probe %'")
            db.commit()
        finally:
            db.close()
