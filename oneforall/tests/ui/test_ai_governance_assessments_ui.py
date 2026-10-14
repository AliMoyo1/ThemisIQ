"""
AI governance G3b in a real browser: the AI impact assessment list and form that used to live in the Privacy module.
A privacy officer records one and reopens it, a system starts its assessment from its profile and the checklist follows,
two people editing do not overwrite each other, an unlinked assessment is found and linked, and every page is checked for
serious accessibility violations and for sideways scroll on a phone.
"""
import re
import uuid

import pytest
import database

from tests.ui.test_ai_governance_pages import _accepted_system, unique  # noqa: F401


@pytest.fixture
def title():
    return "Assessment " + uuid.uuid4().hex[:8]


def _create(page, live_app, name, **answers):
    page.goto(f"{live_app}/ai-governance/assessments/new")
    page.wait_for_selector("#as_title")
    page.fill("#as_title", name)
    for field, value in answers.items():
        page.fill(f"#as_{field}", value)
    page.click("button:has-text('Create assessment')")
    page.wait_for_selector(".aig-say-good:has-text('created')")
    return int(re.search(r"/(\d+)$", page.url).group(1))


def test_a_privacy_officer_records_an_assessment_and_reopens_it(login_as, live_app, page, title):
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/assessments")
    page.wait_for_selector(".aig-empty, .aig-table")
    page.click("a:has-text('New assessment')")
    page.wait_for_selector("#as_title")
    page.fill("#as_title", title)
    page.fill("#as_ai_system_name", "ChurnGuard")
    page.select_option("#as_autonomy_level", "human_in_loop")
    page.check("#as_data_categories input[value='Personal']")
    page.select_option("#as_imp0_l", "4")
    page.select_option("#as_imp0_i", "5")
    page.fill("#as_mitigation_measures", "Human review of every high value offer.")
    page.click("button:has-text('Create assessment')")
    page.wait_for_selector(".aig-say-good:has-text('created')")
    assert re.search(r"/ai-governance/assessments/\d+$", page.url)
    assert page.locator("#aigAssessmentHeader .aig-ref").inner_text().startswith("AIIA-")
    assert page.locator("h1").inner_text() == title

    page.reload()
    page.wait_for_selector("#as_title")
    assert page.locator("#as_title").input_value() == title
    assert page.locator("#as_data_categories input[value='Personal']").is_checked()
    assert page.locator("#as_imp0_l").input_value() == "4" and page.locator("#as_imp0_i").input_value() == "5"
    assert page.locator("#as_mitigation_measures").input_value().startswith("Human review")

    page.goto(f"{live_app}/ai-governance/assessments?q={title.replace(' ', '+')}")
    page.wait_for_selector(f"a:has-text('{title}')")
    row = page.locator("tr", has=page.locator(f"a:has-text('{title}')"))
    assert "Draft" in row.inner_text() and "Not linked" in row.inner_text()


def test_hidden_system_and_ropa_links_survive_an_unrelated_browser_edit(login_as, live_app, page):
    login_as("dpo")
    ref = "AIIA-HIDDEN-" + uuid.uuid4().hex[:8]
    db = database.get_db()
    try:
        unit_b = db.execute("INSERT INTO business_units (name, is_active) VALUES (%s, 1)",
                            ("Other unit " + ref,)).lastrowid
        app_id = db.execute("INSERT INTO applications (name, business_unit_id, is_active) VALUES (%s, %s, 1)",
                            ("Hidden system " + ref, unit_b)).lastrowid
        ropa_id = db.execute("INSERT INTO sentinel_ropa (ref_number, processing_name, business_unit_id) "
                             "VALUES (%s, %s, %s)", ("ROPA-" + ref, "Hidden activity " + ref, unit_b)).lastrowid
        assessment_id = db.execute(
            "INSERT INTO sentinel_aiia (ref_number, title, application_id, ropa_id) VALUES (%s, %s, %s, %s)",
            (ref, "Review " + ref, app_id, ropa_id)).lastrowid
        db.commit()
    finally:
        db.close()

    page.goto(f"{live_app}/ai-governance/assessments/{assessment_id}")
    page.wait_for_selector("#as_application_id_label + .aig-chosen:has-text('cannot open')")
    assert "cannot open" in page.locator("#as_ropa_id_label + .aig-chosen").inner_text()
    assert page.locator("#as_application_id_label ~ .aig-actions button:visible").count() == 0
    assert page.locator("#as_ropa_id_label ~ .aig-actions button:visible").count() == 0
    page.fill("#as_department", "Privacy review")
    page.click("button:has-text('Save changes')")
    page.wait_for_selector(".aig-say-good")

    db = database.get_db()
    try:
        saved = db.execute("SELECT department, application_id, ropa_id FROM sentinel_aiia WHERE id = %s",
                           (assessment_id,)).fetchone()
        assert (saved["department"], saved["application_id"], saved["ropa_id"]) == (
            "Privacy review", app_id, ropa_id)
    finally:
        db.close()


def test_a_system_starts_its_assessment_from_its_profile_and_the_checklist_follows(login_as, live_app, page, unique):
    _accepted_system(login_as, live_app, page, unique)
    page.click("#aigtab_assessments")
    page.wait_for_selector("h2:has-text('What this use needs')")
    page.click("tr:has-text('AI impact assessment') >> a:has-text('Start the assessment')")
    page.wait_for_selector("#as_title")
    assert page.locator("#as_title").input_value() == f"{unique}: AI impact assessment"
    assert "Started from the AI profile" in page.locator(".aig-banner").inner_text()
    assert unique in page.locator("[id='as_application_id_label'] + .aig-chosen").inner_text()
    page.click("button:has-text('Create assessment')")
    page.wait_for_selector(".aig-say-good:has-text('created')")

    page.click("nav[aria-label='Return to the AI system'] a")
    page.wait_for_selector(".aig-tab.is-current:has-text('Assessments')")
    page.wait_for_selector("tr:has-text('AI impact assessment') >> text=In progress")
    assert "AIIA-" in page.locator(".aig-tabpanel").inner_text()


def test_a_status_change_shows_in_the_header_and_a_stale_save_is_refused(login_as, live_app, page, title):
    login_as("dpo")
    assessment_id = _create(page, live_app, title)
    page.select_option("#as_status", "completed")
    page.click("button:has-text('Save changes')")
    page.wait_for_selector("#aigAssessmentHeader >> text=Completed")

    page.evaluate("ApiClient.request('/ai-governance/api/assessments/%d', {method: 'PUT', body: {title: 'Changed elsewhere', version: 2}})"
                  % assessment_id)
    page.fill("#as_department", "Data science")
    page.click("button:has-text('Save changes')")
    page.wait_for_selector(".aig-say-bad:has-text('changed by someone else')")
    assert "Reload" in page.locator(".aig-say-bad").inner_text()


def test_a_field_error_is_named_and_nothing_is_lost(login_as, live_app, page):
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/assessments/new")
    page.wait_for_selector("#as_title")
    page.fill("#as_department", "Data science")
    page.click("button:has-text('Create assessment')")
    summary = page.locator(".aig-errorsummary")
    summary.wait_for(state="visible")
    assert "Give the assessment a title" in summary.inner_text()
    assert page.locator("#as_department").input_value() == "Data science"


def test_an_assessment_can_be_deleted_after_confirming(login_as, live_app, page, title):
    login_as("dpo")
    _create(page, live_app, title)
    page.click("button:has-text('Delete this assessment')")
    page.click(".aig-dialog button:has-text('Delete')")
    page.wait_for_url(re.compile(r"/ai-governance/assessments$"))
    page.goto(f"{live_app}/ai-governance/assessments?q={title.replace(' ', '+')}")
    page.wait_for_selector(".aig-empty:has-text('No assessments match')")


def test_an_unlinked_assessment_is_found_with_the_filter_and_linked_from_the_list(login_as, live_app, page, unique, title):
    _accepted_system(login_as, live_app, page, unique)  # signed in as the DPO
    _create(page, live_app, title)
    page.goto(f"{live_app}/ai-governance/assessments?linked=none&q={title.replace(' ', '+')}")
    page.wait_for_selector(f"a:has-text('{title}')")
    page.click("button:has-text('Link to a system')")
    page.fill("#aigSystemSearch", unique)
    page.click(f".aig-result-row:has-text('{unique}') >> button:has-text('Choose')")
    page.wait_for_selector(".aig-say-good:has-text('Linked to')")
    page.goto(f"{live_app}/ai-governance/assessments?linked=any&q={title.replace(' ', '+')}")
    page.wait_for_selector(f"tr:has-text('{title}') >> a:has-text('{unique}')")


def test_a_configurer_renames_an_impact_dimension_and_it_shows_on_the_form(login_as, live_app, page):
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/assessments")
    page.click("#aigDimensionsBtn")
    page.wait_for_selector(".aig-dialog input[id^='aigDimName']")
    first = page.locator(".aig-dialog input[id^='aigDimName']").first
    original = first.input_value()
    first.fill(original + " (renamed)")
    page.click(".aig-dialog button:has-text('Save dimensions')")
    page.wait_for_selector(".aig-dialog", state="detached")

    page.goto(f"{live_app}/ai-governance/assessments/new")
    page.wait_for_selector(".aig-impact legend")
    assert page.locator(".aig-impact legend").first.inner_text() == original + " (renamed)"

    page.goto(f"{live_app}/ai-governance/assessments")
    page.click("#aigDimensionsBtn")
    page.wait_for_selector(".aig-dialog input[id^='aigDimName']")
    page.locator(".aig-dialog input[id^='aigDimName']").first.fill(original)
    page.click(".aig-dialog button:has-text('Save dimensions')")
    page.wait_for_selector(".aig-dialog", state="detached")


def test_staff_do_not_see_the_assessments_or_the_way_in(login_as, live_app, page):
    login_as("employee")
    assert page.goto(f"{live_app}/ai-governance/assessments").status == 403
    assert page.goto(f"{live_app}/ai-governance/assessments/new").status == 403
    page.goto(f"{live_app}/ai-governance/systems")
    page.wait_for_selector("h1:has-text('AI Systems')")
    assert page.locator("a[href='/ai-governance/assessments']").count() == 0


def test_the_privacy_navigation_points_to_the_new_home(login_as, live_app, page):
    login_as("dpo")
    page.goto(f"{live_app}/sentinel/")
    link = page.locator("a[href='/ai-governance/assessments']").first
    link.wait_for()
    assert page.locator("#view-aiia").count() == 0
    page.goto(f"{live_app}/sentinel/aiia")
    page.wait_for_url(re.compile(r"/ai-governance/assessments$"))


@pytest.mark.parametrize("path", ["/ai-governance/assessments", "/ai-governance/assessments/new"])
def test_the_list_and_the_form_have_no_serious_accessibility_violations(login_as, live_app, page, run_axe, path):
    login_as("dpo")
    page.goto(f"{live_app}{path}")
    page.wait_for_selector("h1")
    page.wait_for_timeout(500)
    assert run_axe() == []


def test_an_existing_assessment_has_no_serious_accessibility_violations(login_as, live_app, page, run_axe, title):
    login_as("dpo")
    _create(page, live_app, title)
    page.wait_for_timeout(300)
    assert run_axe() == []


@pytest.mark.parametrize("path", ["/ai-governance/assessments", "/ai-governance/assessments/new"])
def test_the_list_and_the_form_fit_a_phone_without_sideways_scroll(login_as, live_app, page, path):
    login_as("dpo")
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{live_app}{path}")
    page.wait_for_selector("h1")
    page.wait_for_timeout(400)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
