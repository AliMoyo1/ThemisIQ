"""Parent case entry point uses the same scoped API as its cards."""

from playwright.sync_api import expect


def test_group_case_page_creates_parent_case_without_inline_script(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/group/cases/")
    expect(page.get_by_role("heading", name="Group cases")).to_be_visible()
    form = page.locator("#gcCreate")
    expect(form).to_be_visible()
    form.get_by_label("Case reference").fill("BROWSER-CASE-1")
    form.get_by_label("Title").fill("Group assurance review")
    form.get_by_label("Parent position").fill("The parent is reviewing evidence for its own claim.")
    form.get_by_role("button", name="Create case").click()
    expect(page.locator("#gcStatus")).to_contain_text("Case created")
    expect(page.locator("#gcList")).to_contain_text("BROWSER-CASE-1")
    page.get_by_role("button", name="Open case").first.click()
    expect(page.locator("#gcDetail")).to_contain_text("The parent is reviewing evidence")
    expect(page.locator("#gcRequests")).to_contain_text("Link a proof request")
    amend = page.locator("#gcAmend")
    amend.get_by_label("Revised position").fill("The parent now relies on the subsidiary's annual review.")
    amend.get_by_label("Why it changed").fill("Scope narrowed after the kickoff")
    amend.get_by_role("button", name="Amend position").click()
    expect(page.locator("#gcStatus")).to_contain_text("Position amended")
    expect(page.locator("#gcDetail")).to_contain_text("annual review")
    expect(page.locator("#gcEvents")).to_contain_text("earlier position: The parent is reviewing evidence")


def test_group_case_api_denies_employee(login_as, live_app):
    page = login_as("employee")
    result = page.evaluate("""async () => {
      const r = await fetch('/evidence/api/group/cases');
      return r.status;
    }""")
    assert result == 403
