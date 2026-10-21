"""
The Evidence Vault library in a real browser (plans/2026-10-governance-rework/02): search and the list first, work views whose
counts are their lists, one state per row, the three coverage measures with their definitions, a reviewer's verdict on a
link (never by the person who attached it), and what a new version did to the claims of the one it replaced. Each state is
checked for serious accessibility violations and for sideways scroll on a phone.
"""
import uuid

import database


def _title(prefix="Vault probe"):
    return f"{prefix} {uuid.uuid4().hex[:8]}"


def _seed(tenant, title, *, claim=None, uploader="compliance_manager", linked_by=None, **columns):
    """An evidence item, and (when `claim` is given) an enterprise risk it is linked to. Returns (item id, risk id)."""
    org = tenant["org_id"]
    person = tenant["users"][uploader]["user_id"]
    fields = {"title": title, "org_id": org, "uploaded_by": person, "owner_user_id": person, "status": "current", **columns}
    db = database.get_db()
    try:
        cur = db.execute(f"INSERT INTO evidence_items ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))})",
                         tuple(fields.values()))
        item, risk = cur.lastrowid, None
        if claim:
            risk = db.execute("INSERT INTO erm_enterprise_risks (title) VALUES (%s)", (claim,)).lastrowid
            by = tenant["users"][linked_by or uploader]["user_id"]
            db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) "
                       "VALUES (%s, 'erm', 'risk', %s, %s)", (item, risk, by))
        db.commit()
        return item, risk
    finally:
        db.close()


def _open_library(page, live_app):
    page.goto(f"{live_app}/evidence")
    page.wait_for_selector("#evWork")
    page.wait_for_selector("#evidenceTable tbody tr, #emptyState:visible")


def test_the_library_opens_with_search_the_work_views_and_the_list_and_keeps_the_numbers_behind_insights(
        login_as, live_app, page, synthetic_tenant, run_axe):
    title = _title()
    _seed(synthetic_tenant, title)
    login_as("compliance_manager")
    _open_library(page, live_app)
    assert page.locator("#searchInput").is_visible()
    assert page.locator("#evidenceTable").is_visible() and not page.locator("#evidenceGrid").is_visible()
    box = page.locator("#evWork").inner_text()
    for tab in ("All", "Needs filing", "Review due", "Requests", "Recently updated"):
        assert tab in box, tab
    assert not page.locator("#evInsights").evaluate("el => el.open"), "the detailed measures start closed"
    header = page.locator("#evidenceTable thead").inner_text().lower()
    for column in ("Name and source", "Linked claims", "Owner", "Review due", "State", "Updated"):
        assert column.lower() in header, column
    row = page.locator("#evidenceTable tbody tr", has_text=title)
    assert "Needs filing" in row.inner_text(), "a file nobody linked says so in the state column"
    assert run_axe() == []


def test_a_work_view_lists_exactly_what_its_count_says(login_as, live_app, page, synthetic_tenant):
    login_as("compliance_manager")
    _seed(synthetic_tenant, _title("Unfiled"))
    page.goto(f"{live_app}/evidence")
    page.wait_for_selector("#wc-needs_filing:not(:empty)")
    counted = int(page.inner_text("#wc-needs_filing"))
    assert counted >= 1
    page.click("#wt-needs_filing")
    # the pager of the view that was open before the click also says "of N": wait for the number the tab promised
    page.wait_for_function("(n) => document.getElementById('evPagerStatus').textContent.trim().endsWith('of ' + n)", arg=counted)
    assert page.inner_text("#evPagerStatus").endswith(f"of {counted}")
    assert page.locator("#evChips").inner_text().startswith("Needs filing")
    page.click("#evChips button:has-text('Needs filing')")
    page.wait_for_selector("#wt-all.is-current")


def test_a_reviewer_who_did_not_attach_a_file_accepts_the_link_and_it_counts_as_accepted(
        login_as, live_app, page, synthetic_tenant, run_axe):
    title = _title("Signed test report")
    item, _ = _seed(synthetic_tenant, title, claim="Access control is not tested", uploader="compliance_manager")
    # The person who attached it sees that someone else has to review it.
    login_as("compliance_manager")
    page.goto(f"{live_app}/evidence?open=item:{item}")
    page.wait_for_selector(".ev-link-row")
    assert "Waiting for a reviewer" in page.locator(".ev-link-row").inner_text()
    assert page.locator(".ev-link-row button:has-text('Review')").count() == 0
    assert "Needs another reviewer" in page.locator(".ev-link-row").inner_text()

    page.context.clear_cookies()
    login_as("risk_owner")
    page.goto(f"{live_app}/evidence")
    page.wait_for_selector("#wt-for_review:not([hidden])")
    page.click("#wt-for_review")
    page.wait_for_selector(f"#evidenceTable tbody tr:has-text('{title}')")
    assert "Awaiting review" in page.locator(f"#evidenceTable tbody tr:has-text('{title}')").inner_text()
    page.click(f"#evidenceTable tbody tr:has-text('{title}')")
    page.wait_for_selector(".ev-link-row button:has-text('Review')")
    page.click(".ev-link-row button:has-text('Review')")
    page.wait_for_selector("#reviewModal.open")
    page.click("#reviewForm button[type=submit]")
    assert "Choose what you conclude." in page.inner_text("#rvStatus")
    page.check("#reviewForm input[value='returned']")
    page.click("#reviewForm button[type=submit]")
    page.wait_for_function("() => document.getElementById('rvStatus').textContent.indexOf('reasoning') >= 0")
    page.wait_for_timeout(200)
    assert run_axe() == [], "the review dialog"
    page.check("#reviewForm input[value='accepted']")
    page.click("#reviewForm button[type=submit]")
    page.wait_for_selector("#reviewModal:not(.open)", state="attached")
    page.wait_for_selector(".ev-link-row:has-text('Accepted')")
    assert page.locator(".ev-link-row button:has-text('Review')").count() == 1, "a verdict can be revisited by another reviewer"

    page.goto(f"{live_app}/evidence")
    page.click("#evInsights > summary")
    page.wait_for_selector("#coverageBar:has-text('Accepted by a reviewer')")
    assert "What these mean" in page.locator("#coverageBar").inner_text()


def test_a_new_version_proposes_the_links_and_they_wait_for_their_own_review(
        login_as, live_app, page, synthetic_tenant, tmp_path):
    title = _title("Policy attestation")
    login_as("compliance_manager")
    page.goto(f"{live_app}/evidence")
    page.wait_for_selector("#evWork")
    page.click("button:has-text('+ Upload')")
    first = tmp_path / "v1.txt"
    first.write_text("first signed copy " + title)
    page.set_input_files("#uploadFile", str(first))
    page.fill("#uploadTitle", title)
    page.click("#uploadForm button[type=submit]")
    page.wait_for_selector("#uploadModal:not(.open)", state="attached")
    db = database.get_db()
    try:
        item = db.execute("SELECT id FROM evidence_items WHERE title = %s", (title,)).fetchone()["id"]
        risk = db.execute("INSERT INTO erm_enterprise_risks (title) VALUES (%s)", (f"Claim for {title}",)).lastrowid
        reviewer = synthetic_tenant["users"]["risk_owner"]["user_id"]
        db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by, review_status, "
                   "reviewed_by, reviewed_at) VALUES (%s,'erm','risk',%s,%s,'accepted',%s,'2026-10-01 10:00:00')",
                   (item, risk, synthetic_tenant["users"]["compliance_manager"]["user_id"], reviewer))
        db.commit()
    finally:
        db.close()

    page.goto(f"{live_app}/evidence?open=item:{item}")
    page.wait_for_selector("button:has-text('Add a new version')")
    second = tmp_path / "v2.txt"
    second.write_text("second signed copy " + title)
    with page.expect_file_chooser() as chooser:
        page.click("button:has-text('Add a new version')")
    chooser.value.set_files(str(second))
    page.wait_for_selector(f"text=1 link was proposed for review")
    page.wait_for_selector(".ev-link-row:has-text('Carried forward')")
    row = page.locator(".ev-link-row").first.inner_text()
    assert "Waiting for a reviewer" in row, "the earlier acceptance is not inherited"
    page.click("#tab-history")
    page.wait_for_selector("#evImpact:has-text('Version 1 supported 1 claim')")
    impact = page.inner_text("#evImpact")
    assert f"Claim for {title}" in impact and "Accepted then, Waiting for a reviewer now" in impact


def test_guided_upload_files_a_claim_for_independent_review(login_as, live_app, page, synthetic_tenant, tmp_path):
    title = _title("Guided report")
    risk_name = _title("Guided claim")
    db = database.get_db()
    try:
        risk = db.execute("INSERT INTO erm_enterprise_risks (title) VALUES (%s)", (risk_name,)).lastrowid
        db.commit()
    finally:
        db.close()
    login_as("compliance_manager")
    page.goto(f"{live_app}/evidence")
    page.click("button:has-text('+ Upload')")
    file = tmp_path / "guided.txt"
    file.write_text(title)
    page.set_input_files("#uploadFile", str(file))
    page.fill("#uploadTitle", title)
    page.select_option("#uploadLinkModule", "erm")
    page.select_option("#uploadLinkType", "risk")
    page.fill("#uploadLinkSearch", risk_name)
    page.locator("#uploadLinkResults button", has_text=risk_name).click()
    assert risk_name in page.inner_text("#uploadLinkSelected")
    page.click("#uploadSubmit")
    page.wait_for_selector("#uploadModal:not(.open)", state="attached")
    db = database.get_db()
    try:
        linked = db.execute(
            "SELECT el.entity_id, COALESCE(el.review_status,'pending') AS review_status "
            "FROM evidence_items e JOIN evidence_links el ON el.evidence_id=e.id "
            "WHERE e.title=%s AND el.deleted_at IS NULL", (title,),
        ).fetchall()
        assert len(linked) == 1 and linked[0]["entity_id"] == risk
        assert linked[0]["review_status"] == "pending"
    finally:
        db.close()


def test_the_library_detail_and_insights_fit_a_phone_without_sideways_scroll(
        login_as, live_app, page, synthetic_tenant):
    _seed(synthetic_tenant, _title("Phone"), claim="A claim with a long enough name to wrap on a narrow screen")
    login_as("compliance_manager")
    page.set_viewport_size({"width": 375, "height": 812})
    _open_library(page, live_app)
    page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


def test_find_evidence_turns_a_question_into_filters_and_returns_the_files_with_reasons(
        login_as, live_app, page, synthetic_tenant, run_axe):
    word = uuid.uuid4().hex[:8]
    lapsed, _ = _seed(synthetic_tenant, f"Lapsed attestation {word}", expiry_date="2020-01-01")
    _seed(synthetic_tenant, f"Current attestation {word}")
    login_as("compliance_manager")
    page.goto(f"{live_app}/evidence")
    page.wait_for_selector("#evWork")
    page.click("button:has-text('Find evidence')")
    page.wait_for_selector("#findModal.open")
    page.fill("#findQuestion", f"expired attestation {word}")
    page.click("#findForm button[type=submit]")
    page.wait_for_selector("#findResults li")
    results = page.locator("#findResults").inner_text()
    assert f"Lapsed attestation {word}" in results and f"Current attestation {word}" not in results
    assert "State: expired" in results and "read by rules" in page.inner_text("#findStatus") or "Showing 1 of 1" in page.inner_text("#findStatus")
    assert page.input_value("#findState") == "expired" and page.input_value("#findWords") == f"attestation {word}"
    page.wait_for_timeout(200)
    assert run_axe() == [], "the Find evidence dialog"

    page.select_option("#findState", "")
    page.click("#findFilters button[type=submit]")
    page.wait_for_function("() => document.querySelectorAll('#findResults li').length === 2")
    page.click("#findFilters button[type=submit]")
    page.fill("#findQuestion", f"nothing matches {uuid.uuid4().hex}")
    page.click("#findForm button[type=submit]")
    page.wait_for_selector("#findStatus:has-text('No accessible match')")


def test_quality_checks_name_the_defect_in_the_library_and_on_the_file(login_as, live_app, page, synthetic_tenant, run_axe):
    title = _title("Ownerless lapsed")
    item, _ = _seed(synthetic_tenant, title, claim="A claim that relied on it", expiry_date="2020-01-01", owner_user_id=None)
    login_as("compliance_manager")
    page.goto(f"{live_app}/evidence")
    page.click("#evInsights > summary")
    page.wait_for_selector("#evChecks:has-text('Quality checks')")
    text = page.inner_text("#evChecks")
    assert title in text and "Expired but still in use" in text and "No owner" in text
    assert "not a statement that it is sufficient" in text
    assert run_axe() == []

    page.goto(f"{live_app}/evidence?open=item:{item}")
    page.wait_for_selector("#evChecksItem .ev-section")
    checks = page.inner_text("#evChecksItem")
    assert "Expired but still in use" in checks and "A claim that relied on it" in checks
    assert page.locator("#evChecksItem button:has-text('Name an owner')").count() == 1


def test_a_new_owner_is_found_by_typing_a_name_and_saved(login_as, live_app, page, synthetic_tenant):
    title = _title("Owned by someone else")
    item, _ = _seed(synthetic_tenant, title, claim="Backups are restored", uploader="compliance_manager")
    colleague = synthetic_tenant["users"]["audit_lead"]["user_id"]
    db = database.get_db()
    try:
        name = db.execute("SELECT full_name FROM users WHERE id = %s", (colleague,)).fetchone()["full_name"]
    finally:
        db.close()
    login_as("compliance_manager")
    page.goto(f"{live_app}/evidence?open=item:{item}")
    page.click("button[aria-label='Change the owner']")
    page.wait_for_selector("#ev-owner-find")
    page.fill("#ev-owner-find", name[:6])
    page.wait_for_selector(f"#ev-input-owner_user_id option[value='{colleague}']", state="attached")
    page.select_option("#ev-input-owner_user_id", value=str(colleague))
    page.wait_for_selector(f"#ev-field-owner_user_id .ev-field-val:has-text('{name}')")
    db = database.get_db()
    try:
        owner = db.execute("SELECT owner_user_id FROM evidence_items WHERE id = %s", (item,)).fetchone()["owner_user_id"]
    finally:
        db.close()
    assert owner == colleague
