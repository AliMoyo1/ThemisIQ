"""The staged browser queue uses an explicit filing scope and reports each result."""

from playwright.sync_api import expect


def test_batch_upload_requires_review_and_files_one_document(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/batch/")
    expect(page.get_by_role("heading", name="Batch upload")).to_be_visible()
    expect(page.locator("#ebSummary")).to_contain_text("Choose files")
    page.locator("#ebFiles").set_input_files({
        "name": "Synthetic_Continuity_Test.txt", "mimeType": "text/plain",
        "buffer": b"Synthetic evidence for a disposable browser test."
    })
    expect(page.locator("#ebQueue .eb-row")).to_have_count(1)
    expect(page.locator("#ebUpload")).to_be_disabled()
    page.locator("#ebQueue select").first.select_option(index=1)
    page.get_by_label("Checked for filing").check()
    expect(page.locator("#ebUpload")).to_be_enabled()
    page.locator("#ebUpload").click()
    expect(page.locator("#ebQueue .eb-state")).to_contain_text("Filed in the Vault")


def test_duplicate_in_batch_does_not_stop_later_files(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/batch/")
    expect(page.locator("#ebSummary")).to_contain_text("Choose files")
    page.locator("#ebFiles").set_input_files([
        {"name": "First.txt", "mimeType": "text/plain", "buffer": b"same synthetic batch bytes"},
        {"name": "Duplicate.txt", "mimeType": "text/plain", "buffer": b"same synthetic batch bytes"},
        {"name": "Third.txt", "mimeType": "text/plain", "buffer": b"third synthetic batch bytes"},
    ])
    expect(page.locator("#ebQueue .eb-row")).to_have_count(3)
    for row in page.locator("#ebQueue .eb-row").all():
        row.locator("select").first.select_option(index=1)
    for row in page.locator("#ebQueue .eb-row").all():
        row.get_by_label("Checked for filing").check()
    page.locator("#ebUpload").click()
    expect(page.locator("#ebQueue .eb-state[data-state=uploaded]")).to_have_count(2)
    expect(page.locator("#ebQueue .eb-state[data-state=duplicate]")).to_have_count(1)
