"""Reuse an earlier audit in a real browser: preview, apply one row as a suggestion, then undo it."""
import secrets

import database
import pytest
from playwright.sync_api import expect


@pytest.fixture
def two_audits(live_app, synthetic_tenant):
    tag = secrets.token_hex(3)
    unit = synthetic_tenant["business_unit_id"]
    db = database.get_db()
    try:
        owner = db.execute("SELECT id, org_id FROM users WHERE username=%s",
                           (synthetic_tenant["users"]["compliance_manager"]["username"],)).fetchone()
        earlier = database.insert_returning_id(
            db, "INSERT INTO grid_audits (name, business_unit_id, audit_date) VALUES (%s,%s,'2025-10-01')",
            (f"Earlier {tag}", unit))
        new = database.insert_returning_id(db, "INSERT INTO grid_audits (name, business_unit_id) VALUES (%s,%s)",
                                           (f"Current {tag}", unit))
        source = database.insert_returning_id(
            db, "INSERT INTO grid_controls (audit_id, framework_id, control_id, name, status) "
                "VALUES (%s,9,%s,'Backups tested','Complete')", (earlier, "R." + tag))
        target = database.insert_returning_id(
            db, "INSERT INTO grid_controls (audit_id, framework_id, control_id, name) VALUES (%s,9,%s,'Backups tested')",
            (new, "R." + tag))
        item = database.insert_returning_id(
            db, "INSERT INTO evidence_items (title, status, version, file_hash, org_id, business_unit_id, uploaded_by) "
                "VALUES (%s,'current',1,%s,%s,%s,%s)", (f"Restore test {tag}", "h-" + tag, owner["org_id"], unit,
                                                        owner["id"]))
        db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by, review_status) "
                   "VALUES (%s,'grid','control',%s,%s,'accepted')", (item, source, owner["id"]))
        db.commit()
        yield {"earlier": earlier, "new": new, "target": target, "item": item, "tag": tag, "db": db}
    finally:
        db.close()


def test_the_audit_lead_previews_applies_a_suggestion_and_undoes_it(login_as, live_app, two_audits, run_axe):
    page = login_as("audit_lead")
    page.goto(f"{live_app}/grid/reuse/")
    expect(page.get_by_role("heading", name="Reuse an earlier audit", level=1)).to_be_visible()
    form = page.locator("#grPick")
    form.get_by_label("This audit").select_option(str(two_audits["new"]))
    form.get_by_label("Earlier audit").select_option(str(two_audits["earlier"]))
    form.get_by_role("button", name="Show what could be reused").click()
    row = page.locator("#grRows tr", has_text="R." + two_audits["tag"])
    expect(row).to_contain_text("Full match")
    expect(row).to_contain_text("The same requirement in both audits")
    expect(row).to_contain_text("Restore test " + two_audits["tag"])
    assert run_axe() == []
    row.get_by_role("checkbox").check()
    page.get_by_role("button", name="Apply the chosen rows").click()
    expect(page.locator("#grStatus")).to_contain_text("Applied to 1 control(s): 1 file(s) linked for review")
    expect(page.locator("#grRows tr", has_text="R." + two_audits["tag"])).to_contain_text("Nothing new")
    db = two_audits["db"]
    link = db.execute("SELECT review_status FROM evidence_links WHERE evidence_id=%s AND entity_id=%s AND "
                      "deleted_at IS NULL", (two_audits["item"], two_audits["target"])).fetchone()
    assert link is not None and link["review_status"] is None
    history = page.locator("#grHistory")
    history.get_by_label("Reason for undoing").first.fill("Applied to the wrong audit")
    history.get_by_role("button", name="Undo").first.click()
    expect(page.locator("#grStatus")).to_contain_text("Undone")
    expect(history).to_contain_text("undone")
    assert db.execute("SELECT COUNT(*) FROM evidence_links WHERE evidence_id=%s AND entity_id=%s AND "
                      "deleted_at IS NULL", (two_audits["item"], two_audits["target"])).fetchone()[0] == 0
