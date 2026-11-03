"""Audit questions in a real browser: the audit lead sends, the person answers with Vault proof, the reviewer decides."""
import secrets
from datetime import date, timedelta

import database
import pytest
from playwright.sync_api import expect

from modules.grid import assignments as ga


def _person(db, synthetic_tenant, persona):
    name = synthetic_tenant["users"][persona]["username"]
    row = db.execute("SELECT id, org_id, business_unit_id FROM users WHERE username=%s", (name,)).fetchone()
    roles = [r["role_key"] for r in db.execute("SELECT role_key FROM user_roles WHERE user_id=%s", (row["id"],))]
    return {"id": row["id"], "org_id": row["org_id"], "business_unit_id": row["business_unit_id"], "roles": roles,
            "is_super_admin": False, "full_name": persona}


@pytest.fixture
def audit_world(live_app, synthetic_tenant):
    """A fresh audit of the harness unit with two controls (one requiring evidence) and a Vault file."""
    tag = secrets.token_hex(3)
    db = database.get_db()
    try:
        unit = synthetic_tenant["business_unit_id"]
        lead = _person(db, synthetic_tenant, "audit_lead")
        audit = database.insert_returning_id(
            db, "INSERT INTO grid_audits (name, business_unit_id, lead_id) VALUES (%s,%s,%s)",
            (f"Browser audit {tag}", unit, lead["id"]))
        controls = [database.insert_returning_id(
            db, "INSERT INTO grid_controls (audit_id, control_id, name, description) VALUES (%s,%s,%s,%s)",
            (audit, ref, name, "What the auditor needs to see")) for ref, name in
            (("B.1", "Access reviews"), ("B.2", "Backups tested"))]
        db.execute("INSERT INTO grid_evidence_items (control_id, name, required) VALUES (%s,'Review record',1)",
                   (controls[0],))
        uploader = _person(db, synthetic_tenant, "compliance_manager")
        evidence = database.insert_returning_id(
            db, "INSERT INTO evidence_items (title, status, version, file_hash, org_id, business_unit_id, uploaded_by) "
                "VALUES (%s,'current',1,%s,%s,%s,%s)",
            (f"Access review log {tag}", "h-" + tag, uploader["org_id"], unit, uploader["id"]))
        db.commit()
        yield {"db": db, "audit": audit, "controls": controls, "evidence": evidence, "tag": tag, "lead": lead,
               "owner": _person(db, synthetic_tenant, "employee")}
    finally:
        db.execute("DELETE FROM grid_assignments WHERE audit_id=%s", (audit,))
        db.commit()
        db.close()


def _version(db, assignment):
    return db.execute("SELECT version FROM grid_assignments WHERE id=%s", (assignment,)).fetchone()[0]


def _sent(world):
    db = world["db"]
    assignment = ga.create(db, world["lead"], world["audit"], world["controls"], world["owner"]["id"], None,
                           (date.today() + timedelta(days=10)).isoformat(), "Browser questions " + world["tag"],
                           "Please answer both and attach the log.")
    ga.launch(db, world["lead"], assignment, _version(db, assignment))
    db.commit()
    return assignment


def test_the_audit_lead_chooses_controls_and_a_person_and_sends_them(login_as, live_app, audit_world, run_axe):
    page = login_as("audit_lead")
    page.goto(f"{live_app}/grid/assignments/")
    expect(page.get_by_role("heading", name="Audit questions", level=1)).to_be_visible()
    form = page.locator("#gaCreate")
    form.get_by_label("Audit").select_option(str(audit_world["audit"]))
    expect(page.locator("#gaControls")).to_contain_text("Backups tested")
    page.locator("#gaControls input[type=checkbox]").first.check()
    page.locator("#gaControls input[type=checkbox]").nth(1).check()
    form.get_by_label("Person who answers").select_option(str(audit_world["owner"]["id"]))
    form.get_by_label("Reviewer").select_option(str(audit_world["lead"]["id"]))
    form.get_by_label("Due date").fill((date.today() + timedelta(days=7)).isoformat())
    form.get_by_role("button", name="Save as draft").click()
    expect(page.locator("#gaStatus")).to_contain_text("Saved as a draft")
    expect(page.locator("#gaMeta")).to_contain_text("Draft")
    page.get_by_role("button", name="Send to the person").click()
    expect(page.locator("#gaStatus")).to_contain_text("Sent")
    expect(page.locator("#gaMeta")).to_contain_text("With the respondent")
    assert run_axe() == []
    state = audit_world["db"].execute("SELECT state FROM grid_assignments WHERE audit_id=%s",
                                      (audit_world["audit"],)).fetchone()[0]
    assert state == "in_progress"


def test_the_person_answers_chooses_vault_proof_and_sends_for_review(login_as, live_app, audit_world):
    assignment = _sent(audit_world)
    page = login_as("employee")
    page.goto(f"{live_app}/grid/assignments/?open={assignment}")
    expect(page.locator("#gaTitle")).to_contain_text("Browser questions")
    expect(page.locator("#gaItems")).to_contain_text("Evidence required: Review record")
    items = page.locator("#gaItems article")
    for n, answer in enumerate(("Reviewed every quarter by the owner.", "Restores are tested monthly.")):
        items.nth(n).get_by_label("Your answer").fill(answer)
        items.nth(n).get_by_role("button", name="Save answer").click()
        expect(page.locator("#gaStatus")).to_contain_text("Answer saved")
    first = page.locator("#gaItems article").first
    first.get_by_label("Attach existing proof").fill("Access review log " + audit_world["tag"])
    first.get_by_role("button", name="Search").click()
    first.get_by_role("button", name="Choose").click()
    expect(page.locator("#gaStatus")).to_contain_text("Proof chosen")
    expect(page.locator("#gaItems article").first).to_contain_text("Access review log")
    page.get_by_role("button", name="Send answers for review").click()
    expect(page.locator("#gaStatus")).to_contain_text("Sent for review")
    expect(page.locator("#gaMeta")).to_contain_text("Waiting for review")
    expect(page.locator("#gaEvents")).to_be_empty()


def test_the_reviewer_accepts_one_answer_and_asks_for_a_change_on_the_other(login_as, live_app, audit_world):
    assignment = _sent(audit_world)
    db, owner = audit_world["db"], audit_world["owner"]
    items = ga.detail(db, owner, assignment)["items"]
    ga.add_proof(db, owner, assignment, items[0]["id"], _version(db, assignment), audit_world["evidence"])
    for item in items:
        ga.save_item(db, owner, assignment, item["id"], _version(db, assignment), "Answer for " + item["ref"])
    ga.submit(db, owner, assignment, _version(db, assignment))
    db.commit()
    page = login_as("audit_lead")
    page.goto(f"{live_app}/grid/assignments/?open={assignment}")
    expect(page.locator("#gaReview")).to_contain_text("Browser questions")
    cards = page.locator("#gaItems article")
    cards.first.get_by_role("button", name="Accept answer and proof").click()
    expect(page.locator("#gaStatus")).to_contain_text("Answer accepted")
    cards = page.locator("#gaItems article")
    cards.nth(1).get_by_label("Note (required when asking for a change)").fill("Say who runs the restore test")
    cards.nth(1).get_by_role("button", name="Request a change").click()
    expect(page.locator("#gaStatus")).to_contain_text("Change requested")
    expect(page.locator("#gaMeta")).to_contain_text("Changes requested")
    expect(page.locator("#gaEvents")).to_contain_text("changes requested")
    link = db.execute("SELECT review_status FROM evidence_links WHERE evidence_id=%s",
                      (audit_world["evidence"],)).fetchone()[0]
    assert link == "accepted"
