"""Proof request navigation stays available to authorized specialists."""

from playwright.sync_api import expect


def test_proof_request_page_empty_state_and_vault_navigation(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/group/requests/")
    expect(page.get_by_role("heading", name="Proof requests")).to_be_visible()
    expect(page.locator("#grStatus")).not_to_contain_text("unavailable")
    expect(page.locator("#grList")).to_contain_text("No proof requests in your scope")
    expect(page.locator("#grCreate")).to_be_hidden()
    page.get_by_role("link", name="Evidence Vault").first.click()
    expect(page.locator(".page-title")).to_contain_text("Evidence Vault")


def test_policy_adoption_page_requires_named_parent_policy(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/group/adoption/")
    expect(page.get_by_role("heading", name="Policy adoption")).to_be_visible()
    expect(page.locator("#gaList")).to_contain_text("No published parent policies")
    expect(page.locator("#gaMore")).to_be_hidden()
