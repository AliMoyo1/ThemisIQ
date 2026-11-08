"""Needs attention in a real browser: the issue is listed with its reason, opens the record, and can be reviewed."""
import secrets

import database
import pytest
from playwright.sync_api import expect


@pytest.fixture
def unproved_control(live_app, synthetic_tenant):
    tag = secrets.token_hex(3)
    db = database.get_db()
    try:
        audit = database.insert_returning_id(
            db, "INSERT INTO grid_audits (name, business_unit_id) VALUES (%s,%s)",
            (f"Attention audit {tag}", synthetic_tenant["business_unit_id"]))
        control = database.insert_returning_id(
            db, "INSERT INTO grid_controls (audit_id, control_id, name, status) VALUES (%s,%s,%s,'Complete')",
            (audit, "NA." + tag, f"Firewall rules reviewed {tag}"))
        db.commit()
        yield {"control": control, "title": f"NA.{tag} Firewall rules reviewed {tag}"}
    finally:
        db.execute("DELETE FROM assurance_issue_reviews WHERE source_id=%s", (control,))
        db.execute("DELETE FROM grid_controls WHERE id=%s", (control,))
        db.execute("DELETE FROM grid_audits WHERE id=%s", (audit,))
        db.commit()
        db.close()


def test_a_specialist_sees_why_a_control_needs_attention_and_records_a_review(login_as, live_app, unproved_control,
                                                                               run_axe):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/")
    page.get_by_role("link", name="Needs attention", exact=True).click()
    expect(page.get_by_role("heading", name="Needs attention", level=1)).to_be_visible()
    issue = page.locator("#naList article", has_text=unproved_control["title"])
    expect(issue).to_contain_text("It is marked Complete with no accepted, current proof.")
    expect(issue.get_by_role("link", name=unproved_control["title"])).to_have_attribute("href", "/grid/controls")
    expect(page.locator("#naSummary")).to_contain_text("warnings")
    assert run_axe() == []
    issue.get_by_role("button", name="Review this issue").click()
    issue.get_by_label("Decision").select_option("accepted_exception")
    issue.get_by_label("Reason (at least 10 characters)").fill("Proof is held by the outsourced firewall vendor")
    issue.get_by_role("button", name="Record review").click()
    expect(page.locator("#naStatus")).to_contain_text("Review recorded")
    expect(page.locator("#naList")).not_to_contain_text(unproved_control["title"])
    page.locator("#naFilters").get_by_label("Show").select_option("reviewed")
    reviewed = page.locator("#naList article", has_text=unproved_control["title"])
    expect(reviewed).to_contain_text("Accepted exception")
    expect(reviewed).to_contain_text("Proof is held by the outsourced firewall vendor")


def test_a_person_without_the_role_sees_no_link_and_no_page(login_as, live_app):
    page = login_as("employee")
    page.goto(f"{live_app}/")
    expect(page.get_by_role("link", name="Needs attention", exact=True)).to_have_count(0)
    response = page.goto(f"{live_app}/governance/attention/")
    assert response.status == 404
