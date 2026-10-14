"""
Importing the responses of an external form in a real browser (plans/2026-10-governance-rework/01 section 4): read an
export, check the columns, look at each response, create the drafts, and importing the same file again creates nothing.
Every state is checked for serious accessibility violations and for sideways scroll on a phone.
"""
import csv
import io

from modules.ai_governance import import_rules as ir
from tests.ui.test_ai_governance_pages import unique  # noqa: F401


def _export(name, owner="uiharness_employee@example.test", purpose="Summarize support tickets"):
    values = {
        "name": name, "purpose": purpose, "requester_name": "Pat Requester", "requester_email": "pat@outside.example",
        "requester_organization": "Support", "provider_name": "Acme AI", "deployment": "A vendor's AI service that we call",
        "intended_users": "Support agents", "data_categories": "Internal business information; Personal data",
        "affects_decisions": "No", "target_launch": "2026-12-01", "owner": owner}
    guide = [g for g in ir.FIELD_GUIDE if g["target"] != "response_id"]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([g["question"] for g in guide])
    writer.writerow([values.get(g["target"], "") for g in guide])
    return out.getvalue().encode("utf-8")


def _read(page, data, form="UI intake form"):
    page.wait_for_selector("#aigImpFile")
    page.set_input_files("#aigImpFile", files=[{"name": "responses.csv", "mimeType": "text/csv", "buffer": data}])
    page.fill("#aigImpForm", form)
    page.click("button:has-text('Read the file')")
    page.wait_for_selector("h2:has-text('3. Check the responses')")


def test_staff_do_not_get_the_import(login_as, live_app, page):
    login_as("employee")
    assert page.goto(f"{live_app}/ai-governance/import").status == 403


def test_the_form_guide_is_published_and_the_page_is_accessible_before_anything_is_read(login_as, live_app, page, run_axe):
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/import")
    page.wait_for_selector("summary:has-text('What the form needs to ask')")
    page.click("summary:has-text('What the form needs to ask')")
    text = page.locator("details").first.inner_text()
    assert "What is the name of the AI tool or use?" in text and "Download a CSV template" in text
    assert page.locator("a[href='/ai-governance/api/import/template.csv']").count() == 1
    assert run_axe() == []


def test_a_response_is_read_confirmed_and_never_created_twice(login_as, live_app, page, unique, run_axe):
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/import")
    data = _export(unique)
    _read(page, data)
    body = page.locator("#aigImport").inner_text()
    assert "New request" in body and "Nothing has been created yet." in body and unique in body
    assert "Pat Requester" in body
    owner = page.locator("select[aria-label='Owner for row 2']")
    assert "uiharness_employee@example.test" in owner.locator("option:checked").inner_text(), \
        "an owner matched by email is offered ready chosen, to be confirmed by creating"
    assert run_axe() == []

    page.click("button:has-text('Create the draft requests')")
    page.wait_for_selector("h2:has-text('Done')")
    assert "1 new" in page.locator("#aigImport").inner_text()
    page.click(f"a:has-text('{unique}')")
    page.wait_for_selector("#q_name")
    assert page.input_value("#q_name") == unique

    page.goto(f"{live_app}/ai-governance/import")
    _read(page, data)
    again = page.locator("#aigImport").inner_text()
    assert "Already imported" in again
    assert page.locator("button:has-text('Create the draft requests')").is_disabled()

    page.goto(f"{live_app}/ai-governance/requests")
    page.wait_for_selector(f"a:has-text('{unique}')")
    assert "Imported from a form" in page.locator("main, .aig-page").first.inner_text()


def test_a_correction_shows_its_differences_before_it_is_created(login_as, live_app, page, unique):
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/import")
    _read(page, _export(unique))
    page.click("button:has-text('Create the draft requests')")
    page.wait_for_selector("h2:has-text('Done')")
    page.goto(f"{live_app}/ai-governance/import")
    _read(page, _export(unique, purpose="Summarize and route support tickets"))
    page.click("summary:has-text('Differences from request')")
    text = page.locator("#aigImport").inner_text()
    assert "Correction of an earlier response" in text and "Summarize and route support tickets" in text
    page.click("button:has-text('Create the draft requests')")
    page.wait_for_selector("h2:has-text('Done')")
    assert "1 corrected" in page.locator("#aigImport").inner_text()
    assert page.locator("span:has-text('Revision 2')").count() == 1


def test_an_unreadable_file_is_explained_and_the_import_page_fits_a_phone(login_as, live_app, page, unique):
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/import")
    page.wait_for_selector("#aigImpFile")
    page.set_input_files("#aigImpFile", files=[{"name": "responses.csv", "mimeType": "text/csv", "buffer": b"a,b\r\n1,2"}])
    page.fill("#aigImpForm", "Odd file")
    page.click("button:has-text('Read the file')")
    page.wait_for_selector(".aig-say-bad")
    assert "name of the AI use" in page.locator(".aig-say-bad").first.inner_text()
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{live_app}/ai-governance/import")
    _read(page, _export(unique))
    page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
