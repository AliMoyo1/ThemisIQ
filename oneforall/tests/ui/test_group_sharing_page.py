"""The group work page shows only actions the signed-in specialist may perform."""

from playwright.sync_api import expect


def test_group_sharing_specialist_page_and_scoped_search(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/group/")
    expect(page.get_by_role("heading", name="Group sharing")).to_be_visible()
    expect(page.locator("#gsPropose")).to_be_hidden()
    expect(page.locator("#gsPublish")).to_be_visible()
    search = page.get_by_label("Find a source document by title")
    search.fill("nonexistent-specific-title-4727")
    expect(page.locator("#gsEvidenceResult")).to_contain_text("0 matching source documents shown")
    expect(page.locator("#gsPublish select[name=evidence_id] option")).to_have_count(1)
