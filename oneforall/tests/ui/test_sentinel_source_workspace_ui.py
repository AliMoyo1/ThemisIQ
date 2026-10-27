"""Official-source checks stay beside the source and retain legal review boundaries."""

from datetime import datetime, timedelta, timezone


def _source(key, title, *, result=None, capture=None, checked=None, error=None):
    return {
        "key": key, "jurisdiction": "GDPR", "title": title,
        "source_type": "Official guidance", "url": "https://commission.europa.eu/example",
        "last_checked_at": checked, "last_result": result, "last_error": error,
        "latest_capture": capture, "approved_capture": None,
        "recent_captures": ([{"id": capture["id"], "review_state": capture["review_state"]}]
                            if capture else []),
    }


def _monitor(page, get_sources):
    page.route("**/sentinel/api/law-monitor", lambda route: route.fulfill(json={
        "cadence": "weekly", "retention_days": 2555, "cost_note": "No AI tokens used.",
        "sources": get_sources(), "uncovered": [],
    }))


def test_check_result_and_proof_remain_in_selected_inspector(login_as, live_app, page):
    login_as("dpo")
    state = {"checked": False, "approved": False}
    def sources():
        capture = {"id": 41, "review_state": "approved" if state["approved"] else "pending"} if state["checked"] else None
        checked = datetime.now(timezone.utc).isoformat() if state["checked"] else None
        first = _source("eu-framework", "EU legal framework", result="baseline_pending_review" if capture else None,
                        capture=capture, checked=checked)
        if state["approved"]:
            first["approved_capture"] = capture
        return [first, _source("eu-obligations", "GDPR obligations")]
    _monitor(page, sources)
    def check(route):
        state["checked"] = True
        route.fulfill(json={"source_key": "eu-framework", "result": "baseline_pending_review", "capture_id": 41})
    page.route("**/sentinel/api/law-monitor/check", check)
    page.route("**/sentinel/api/law-monitor/captures/41", lambda route: route.fulfill(json={
        "id": 41, "source_key": "eu-framework", "jurisdiction_key": "GDPR", "proof": "Stored official capture",
        "hash_verified": True, "source_url": "https://commission.europa.eu/example",
        "captured_at": "2026-10-25T10:00:00", "raw_sha256": "a" * 64,
        "text_sha256": "b" * 64, "review_state": "approved" if state["approved"] else "pending",
        "review_note": "Reviewed source" if state["approved"] else None,
        "review_overdue": False, "retention_review_due": False, "legal_hold": False,
        "change_excerpt": "First captured baseline", "captured_text": "Official text",
        "is_latest": True,
    }))
    page.route("**/sentinel/api/law-monitor/captures/41/impact", lambda route: route.fulfill(json={
        "action": "Review impact", "records_in_your_scope": {"RoPA": 1}, "rule_cards": 0,
    }))
    def approve(route):
        state["approved"] = True
        route.fulfill(json={"ok": True})
    page.route("**/sentinel/api/law-monitor/captures/41/review", approve)
    page.goto(f"{live_app}/sentinel/jurisdictions")
    page.locator("#snLawSources .sn-watch-source").first.wait_for()
    page.locator("#snLawSources .sn-watch-source").first.get_by_role("button", name="Check now").click()
    inspector = page.locator("#snWatchInspector")
    inspector.locator(".sn-inspector-state").get_by_text("First capture needs review", exact=True).wait_for()
    inspector.get_by_text("Stored-byte integrity: Verified").wait_for()
    assert inspector.get_by_text("Capture #41", exact=False).count() >= 1
    assert page.locator("#snLawSources .sn-watch-source.selected").get_by_text("EU legal framework").count() == 1
    assert inspector.get_by_role("button", name="Approve for retrieval").count() == 1
    inspector.locator(".sn-inspector-review textarea").fill("Reviewed source")
    inspector.get_by_role("button", name="Approve for retrieval").click()
    inspector.locator(".sn-inspector-state").get_by_text("Capture approved for retrieval", exact=True).wait_for()
    assert inspector.get_by_role("button", name="Approve for retrieval").count() == 0
    page.locator("#snSourceSearch").fill("obligations")
    assert page.locator("#snLawSources .sn-watch-source").count() == 1
    page.locator("#snSourceFilter").select_option("review")
    assert page.get_by_text("No sources match these filters.").count() == 1


def test_failed_check_and_server_rate_limit_are_visible_in_place(login_as, live_app, page):
    login_as("dpo")
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    state = {"checks": 0}
    def sources():
        return [_source("pdf", "Authority fact sheet PDF", result="error" if state["checks"] else None,
                        checked=old if state["checks"] else None,
                        error="Authority PDF could not be safely extracted" if state["checks"] else None)]
    _monitor(page, sources)
    def check(route):
        state["checks"] += 1
        if state["checks"] == 1:
            route.fulfill(json={"source_key": "pdf", "result": "error",
                                "error": "Authority PDF could not be safely extracted"})
        else:
            route.fulfill(status=429, json={"detail": "This source was checked within the last hour"})
    page.route("**/sentinel/api/law-monitor/check", check)
    page.goto(f"{live_app}/sentinel/jurisdictions")
    inspector = page.locator("#snWatchInspector")
    page.locator("#snLawSources").get_by_role("button", name="Check now").click()
    inspector.locator(".sn-inspector-state").get_by_text("Source check failed", exact=True).wait_for()
    assert inspector.locator(".sn-inspector-state").get_by_text("Authority PDF could not be safely extracted").count() == 1
    assert inspector.get_by_text("No textual change detected").count() == 0
    page.locator("#snLawSources").get_by_role("button", name="Check now").click()
    inspector.locator(".sn-inspector-state").get_by_text("Check could not start", exact=True).wait_for()
    assert inspector.locator(".sn-inspector-state").get_by_text("This source was checked within the last hour").count() == 1


def test_unchanged_check_keeps_existing_approved_capture(login_as, live_app, page):
    login_as("dpo")
    state = {"checked": False}
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    def sources():
        capture = {"id": 42, "review_state": "approved"}
        source = _source("guidance", "Authority guidance", result="unchanged" if state["checked"] else "baseline_pending_review",
                         capture=capture, checked=datetime.now(timezone.utc).isoformat() if state["checked"] else old)
        source["approved_capture"] = capture
        return [source]
    _monitor(page, sources)
    def check(route):
        state["checked"] = True
        route.fulfill(json={"source_key": "guidance", "result": "unchanged", "capture_id": 42})
    page.route("**/sentinel/api/law-monitor/check", check)
    page.route("**/sentinel/api/law-monitor/captures/42", lambda route: route.fulfill(json={
        "id": 42, "source_key": "guidance", "jurisdiction_key": "GDPR", "proof": "Stored official capture",
        "hash_verified": True, "source_url": "https://commission.europa.eu/example",
        "captured_at": "2026-10-24T10:00:00", "raw_sha256": "a" * 64,
        "text_sha256": "b" * 64, "review_state": "approved", "review_note": "Reviewed",
        "review_overdue": False, "retention_review_due": False, "legal_hold": False,
        "change_excerpt": "First baseline", "captured_text": "Official text", "is_latest": True,
    }))
    page.route("**/sentinel/api/law-monitor/captures/42/impact", lambda route: route.fulfill(json={
        "action": "No automatic changes", "records_in_your_scope": {}, "rule_cards": 0,
    }))
    page.goto(f"{live_app}/sentinel/jurisdictions")
    page.locator("#snLawSources").get_by_role("button", name="Check now").click()
    inspector = page.locator("#snWatchInspector")
    inspector.locator(".sn-inspector-state").get_by_text("No textual change detected", exact=True).wait_for()
    assert inspector.get_by_text("Approved for retrieval: #42").count() == 1
    assert inspector.get_by_text("Latest capture #42", exact=False).count() == 1
    assert inspector.get_by_role("button", name="Approve for retrieval").count() == 0


def test_phone_result_opens_as_closeable_sheet(login_as, live_app, page):
    login_as("dpo")
    _monitor(page, lambda: [_source("eu-framework", "EU legal framework")])
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_app}/sentinel/jurisdictions")
    selected = page.locator("#snLawSources .sn-source-select").first
    selected.click()
    inspector = page.locator("#snWatchInspector")
    assert inspector.get_attribute("aria-modal") == "true"
    assert inspector.is_visible()
    bounds = inspector.bounding_box()
    assert bounds["y"] + bounds["height"] >= 843
    assert inspector.evaluate("node => node.parentElement === document.body")
    assert page.locator("#snInspectorClose").evaluate("node => document.activeElement === node")
    page.keyboard.press("Escape")
    assert not inspector.is_visible()
    assert selected.evaluate("node => document.activeElement === node")


def test_late_capture_response_cannot_replace_another_selected_source(login_as, live_app, page):
    login_as("dpo")
    _monitor(page, lambda: [
        _source("first", "First authority", result="baseline_pending_review",
                capture={"id": 41, "review_state": "pending"}, checked="2026-10-25T10:00:00"),
        _source("second", "Second authority"),
    ])
    page.route("**/sentinel/api/law-monitor/captures/41", lambda route: route.fulfill(json={
        "id": 41, "source_key": "first", "jurisdiction_key": "GDPR", "proof": "Stored official capture",
        "hash_verified": True, "source_url": "https://commission.europa.eu/example",
        "captured_at": "2026-10-25T10:00:00", "raw_sha256": "a" * 64,
        "text_sha256": "b" * 64, "review_state": "pending", "review_note": None,
        "review_overdue": False, "retention_review_due": False, "legal_hold": False,
        "change_excerpt": "Old source text", "captured_text": "Old source text",
        "is_latest": True,
    }))
    page.goto(f"{live_app}/sentinel/jurisdictions")
    page.locator("#snLawSources .sn-source-select").first.wait_for()
    page.locator("#snLawSources .sn-source-select").nth(1).click()
    page.evaluate("""() => {
      const original = window.ApiClient.request;
      window.ApiClient.request = function(url, options) {
        if (url === '/sentinel/api/law-monitor/captures/41') {
          return new Promise(resolve => setTimeout(() => resolve({
            id: 41, jurisdiction_key: 'GDPR', proof: 'STALE PROOF',
            hash_verified: true, source_url: 'https://commission.europa.eu/example',
            captured_at: '2026-10-25T10:00:00', raw_sha256: 'a', text_sha256: 'b',
            review_state: 'pending', is_latest: true, change_excerpt: 'STALE CHANGE',
            captured_text: 'STALE CAPTURE'
          }), 450));
        }
        return original.call(this, url, options);
      };
    }""")
    page.locator("#snLawSources .sn-source-select").first.click()
    page.locator("#snLawSources .sn-source-select").nth(1).click()
    page.wait_for_timeout(550)
    assert page.locator("#snInspectorTitle").inner_text() == "Second authority"
    assert page.locator("#snWatchInspector").get_by_text("STALE CAPTURE").count() == 0
