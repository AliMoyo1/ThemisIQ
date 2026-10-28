"""Company review screen and Vault navigation use the same source-tenant UI."""

from playwright.sync_api import expect


def test_company_label_page_and_vault_facet(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/companies/")
    expect(page.get_by_role("heading", name="Company labels")).to_be_visible()
    expect(page.locator("#coCreatePanel")).to_be_visible()
    page.locator("#coCreate input[name=name]").fill("Synthetic Test Company")
    page.locator("#coCreate button").click()
    expect(page.locator("#coStatus")).to_contain_text("Company added")
    page.goto(f"{live_app}/evidence/")
    expect(page.get_by_role("heading", name="By reviewed company")).to_be_visible()
    expect(page.get_by_role("link", name="Review company labels")).to_be_visible()
    expect(page.locator("#evEntityViews")).to_contain_text("All accessible documents")


def test_employee_cannot_open_company_review_page(login_as, live_app):
    page = login_as("employee")
    page.goto(f"{live_app}/evidence/companies/")
    expect(page.get_by_role("heading", name="Access Denied")).to_be_visible()
