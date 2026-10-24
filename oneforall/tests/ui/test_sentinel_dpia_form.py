"""The Privacy DPIA drawer in a real browser: what a person types is saved and shown again, the list reads the stored due
date (the overdue banner and the Due column), and the drawer carries the Related Items panel a report points from.
"""
import datetime
import uuid

import database

TODAY = datetime.date.today()
NO_DATE = "—"  # what the list prints in the Due column when there is none


def _iso(days_from_today):
    return (TODAY + datetime.timedelta(days=days_from_today)).isoformat()


def _seed_dpia(title, due_date, status="draft"):
    db = database.get_db()
    try:
        row = db.execute(
            "INSERT INTO sentinel_dpias (ref_number, title, status, due_date) VALUES (%s, %s, %s, %s)",
            ("DPIA-UI-" + uuid.uuid4().hex[:10], title, status, due_date))
        db.commit()
        return row.lastrowid
    finally:
        db.close()


def _open_dpia_page(page, live_app):
    page.goto(f"{live_app}/sentinel/dpia")
    page.wait_for_selector("#snDpiaBody tr")


def _row(page, title):
    return page.locator("#snDpiaBody tr", has=page.locator(f"strong:has-text('{title}')"))


def _shown_date(page, iso):
    """The date as the list prints it, from the browser's own formatter."""
    return page.evaluate(
        "iso => new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric'})",
        iso)


def test_a_privacy_officer_types_a_dpia_saves_it_and_sees_every_field_again(login_as, live_app, page):
    login_as("dpo")
    title = 'Credit "scoring" ' + uuid.uuid4().hex[:8]  # quotes, ampersands and line breaks must come back as typed
    typed = {"owner": "O'Brien & \"Sons\", T. Moyo", "due": _iso(30), "description": 'Scoring of "A & B"\nsecond line',
             "mitigations": "Scores are pseudonymised & access is reviewed every quarter"}

    _open_dpia_page(page, live_app)
    page.click("button:has-text('New DPIA')")
    page.wait_for_selector("#dd_title")
    assert page.locator("#snDpiaDocs").count() == 0  # nothing to link a document to until the DPIA exists
    page.fill("#dd_title", title)
    page.fill("#dd_owner", typed["owner"])
    page.fill("#dd_due_date", typed["due"])
    page.fill("#dd_description", typed["description"])
    page.click(".ropa-drawer-tab[data-tab='review']")
    page.fill("#dd_mitigations", typed["mitigations"])
    page.select_option("#dd_overall_risk", "high")
    page.click("#snDpiaDrawerSaveBtn")
    page.wait_for_selector("#snDpiaDrawerWrap", state="detached")

    row = _row(page, title)
    row.wait_for()
    assert _shown_date(page, typed["due"]) in row.inner_text()  # the Due column
    assert "High" in row.locator("td").nth(2).inner_text()  # the Risk column shows the level that was chosen

    row.locator("button[title='Edit']").click()
    page.wait_for_selector("#dd_title")
    assert page.locator("#dd_title").input_value() == title
    assert page.locator("#dd_owner").input_value() == typed["owner"]
    assert page.locator("#dd_due_date").input_value() == typed["due"]
    assert page.locator("#dd_description").input_value() == typed["description"]
    assert page.locator("#dd_mitigations").input_value() == typed["mitigations"]
    assert page.locator("#dd_overall_risk").input_value() == "high"


def test_a_stored_value_cannot_break_out_of_an_input_in_the_drawer(login_as, live_app, page):
    """The API stores what it is given (only angle brackets are stripped), and esc() leaves quotes alone, so a value
    with a quote in it used to end the input's value attribute early and could add attributes of its own."""
    login_as("dpo")
    title = "Probe " + uuid.uuid4().hex[:8]
    payload = 'x" onfocus="window.__pwned=1" data-probe="'
    db = database.get_db()
    try:
        db.execute("INSERT INTO sentinel_dpias (ref_number, title, owner, retention, subject_count, data_subjects) "
                   "VALUES (%s, %s, %s, %s, %s, %s)",
                   ("DPIA-UI-" + uuid.uuid4().hex[:10], title, payload, payload, payload, payload))
        db.commit()
    finally:
        db.close()

    _open_dpia_page(page, live_app)
    _row(page, title).locator("button[title='Edit']").click()
    page.wait_for_selector("#dd_title")
    for field in ("#dd_owner", "#dd_data_subjects", "#dd_subject_count", "#dd_retention"):
        assert page.locator(field).input_value() == payload, field
        page.locator(field).focus()
        assert page.locator(field).get_attribute("data-probe") is None, field
    assert page.evaluate("window.__pwned") is None


def test_clearing_the_due_date_removes_it_from_the_list(login_as, live_app, page):
    login_as("dpo")
    title = "Clear the date " + uuid.uuid4().hex[:8]
    _seed_dpia(title, _iso(-3))

    _open_dpia_page(page, live_app)
    row = _row(page, title)
    row.wait_for()
    assert _shown_date(page, _iso(-3)) in row.inner_text()
    row.locator("button[title='Edit']").click()
    page.wait_for_selector("#dd_due_date")
    page.fill("#dd_due_date", "")
    page.click("#snDpiaDrawerSaveBtn")
    page.wait_for_selector("#snDpiaDrawerWrap", state="detached")

    row = _row(page, title)
    row.wait_for()
    assert NO_DATE in row.locator("td").nth(6).inner_text()


def test_the_overdue_banner_counts_only_open_dpias_due_before_today(login_as, live_app, page, synthetic_tenant):
    login_as("dpo")
    tag = uuid.uuid4().hex[:8]
    seeded = {
        "late draft": (_iso(-1), "draft", True),
        "late in progress": (_iso(-10), "in_progress", True),
        "due today": (_iso(0), "in_progress", False),
        "due tomorrow": (_iso(1), "draft", False),
        "late but completed": (_iso(-5), "completed", False),
        "late but approved": (_iso(-2), "approved", False),
        "no date": (None, "draft", False),
    }
    for name, (due, status, _) in seeded.items():
        _seed_dpia(f"{name} {tag}", due, status)

    # Everything this officer can see, counted from the database by the rule written out: strictly before today, still open.
    db = database.get_db()
    try:
        expected = db.execute(
            "SELECT COUNT(*) FROM sentinel_dpias WHERE due_date IS NOT NULL AND due_date < %s "
            "AND status NOT IN ('completed', 'approved') AND (business_unit_id IS NULL OR business_unit_id = %s)",
            (TODAY.isoformat(), synthetic_tenant["business_unit_id"])).fetchone()[0]
    finally:
        db.close()
    assert expected >= 2

    _open_dpia_page(page, live_app)
    _row(page, f"no date {tag}").wait_for()
    banner = page.locator("#snDpiaOverdueBanner")
    assert banner.is_visible()
    assert " ".join(banner.inner_text().split()).startswith(f"{expected} DPIAs are past their due date.")
    card = page.locator("#snDpiaStats .sn-tab-stat", has=page.locator(".sn-tab-stat-label:text-is('Overdue')"))
    assert card.locator(".sn-tab-stat-val").inner_text() == str(expected)
    for name, (due, status, _) in seeded.items():
        text = _row(page, f"{name} {tag}").inner_text()
        assert (_shown_date(page, due) in text) if due else (NO_DATE in text), name


def _vault_document(title, org_id, dpia_id, **columns):
    """A file in the Evidence Vault, linked to the DPIA the way the Vault links it."""
    db = database.get_db()
    try:
        names = ", ".join(["title", "org_id", *columns])
        marks = ", ".join(["%s"] * (2 + len(columns)))
        evidence_id = db.execute(f"INSERT INTO evidence_items ({names}) VALUES ({marks})",
                                 (title, org_id, *columns.values())).lastrowid
        db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id) "
                   "VALUES (%s, 'sentinel', 'dpia', %s)", (evidence_id, dpia_id))
        db.commit()
        return evidence_id
    finally:
        db.close()


def test_the_drawer_lists_the_evidence_vault_documents_linked_to_a_dpia(login_as, live_app, page, synthetic_tenant):
    login_as("dpo")
    tag = uuid.uuid4().hex[:8]
    title = "Linked DPIA " + tag
    dpia_id = _seed_dpia(title, None)
    org = synthetic_tenant["org_id"]
    procedure = _vault_document("Scoring procedure " + tag, org, dpia_id, version=2, expiry_date="2099-01-01")
    _vault_document("Archived memo " + tag, org, dpia_id, status="archived")

    _open_dpia_page(page, live_app)
    _row(page, title).locator("button[title='Edit']").click()
    page.wait_for_selector("#dd_title")
    page.click(".ropa-drawer-tab[data-tab='review']")
    docs = page.locator("#snDpiaDocs")
    link = docs.locator(f"a:has-text('Scoring procedure {tag}')")
    link.wait_for()
    assert link.get_attribute("href") == f"/evidence/?open=item:{procedure}"
    assert "Waiting for a reviewer" in docs.inner_text() and "expires" in docs.inner_text()
    assert f"Archived memo {tag}" not in docs.inner_text()
    assert docs.locator("a:has-text('Evidence Vault')").get_attribute("href") == "/evidence/"
    assert docs.locator("a:has-text('connected view')").get_attribute("href") == f"/governance/connected/sentinel/dpia/{dpia_id}"


def test_a_dpia_without_linked_documents_says_so(login_as, live_app, page):
    login_as("dpo")
    title = "Unlinked DPIA " + uuid.uuid4().hex[:8]
    _seed_dpia(title, None)

    _open_dpia_page(page, live_app)
    _row(page, title).locator("button[title='Edit']").click()
    page.wait_for_selector("#dd_title")
    page.click(".ropa-drawer-tab[data-tab='review']")
    page.locator("#snDpiaDocs:has-text('No document is linked to this DPIA yet.')").wait_for()
