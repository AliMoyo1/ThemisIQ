"""A retention manager sets the workbook policy on Reports and a hold on one source workbook in the Vault drawer."""
import database
from core.timeutils import utcnow


def _source_workbook(synthetic_tenant):
    manager = synthetic_tenant["users"]["compliance_manager"]["user_id"]
    db = database.get_db()
    try:
        db.execute("INSERT INTO evidence_items (title, description, category, uploaded_by, org_id, file_path, "
                   "file_name, file_size, file_hash, mime_type, status) VALUES ('Document register: retention.xlsx', "
                   "'Confirmed source workbook', 'report', %s, %s, 'retention-ui-not-downloaded.xlsx', "
                   "'retention.xlsx', 10, 'abc123', "
                   "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'current')",
                   (manager, synthetic_tenant["org_id"]))
        eid = db.execute("SELECT id FROM evidence_items WHERE file_name='retention.xlsx'").fetchone()["id"]
        db.execute("INSERT INTO aria_document_register_batches (org_id, file_name, file_sha256, source_evidence_id, "
                   "rows, warnings, status, created_by, created_at, confirmed_at) "
                   "VALUES (%s, 'retention.xlsx', 'abc123', %s, '[]', '[]', 'confirmed', %s, %s, %s)",
                   (synthetic_tenant["org_id"], eid, manager, utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    utcnow().strftime("%Y-%m-%d %H:%M:%S")))
        db.commit()
        return eid
    finally:
        db.close()


def test_manager_sets_the_workbook_policy_and_a_legal_hold(live_app, page, login_as, synthetic_tenant):
    eid = _source_workbook(synthetic_tenant)
    login_as("compliance_manager")

    page.goto(f"{live_app}/reports")
    status = page.locator("#sourcePolicyStatus")
    status.filter(has_text="No period chosen").wait_for()
    page.fill("#sourcePolicyDays", "730")
    page.fill("#sourcePolicyReason", "Two years agreed with the DPO")
    page.click("#sourcePolicyForm button[type=submit]")
    status.filter(has_text="kept for 730 days").wait_for()

    page.goto(f"{live_app}/evidence")
    page.evaluate("id => openDetail(id)", eid)
    section = page.locator("#evSourceRetention")
    section.get_by_text("No removal date: the file is kept.").wait_for()
    section.get_by_label("Legal hold reason").fill("Regulator inquiry open until closure")
    section.get_by_label("Why this is changing").fill("Regulator asked us to keep it")
    section.get_by_role("button", name="Save retention").click()
    section.get_by_text("On legal hold: Regulator inquiry open until closure", exact=False).wait_for()
    assert section.get_by_text("Retention saved.").count() == 1
    assert not page.console_errors

    page.context.clear_cookies()
    login_as("employee")
    page.goto(f"{live_app}/reports")
    assert page.locator("#sourcePolicyForm").count() == 0
