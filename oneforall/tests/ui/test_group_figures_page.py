"""The group figures page in a real browser: three views, not reporting, role limits and masked access."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import database
import pytest
from playwright.sync_api import expect


def _stamp(days=0, hours=0):
    return (datetime.now(timezone.utc) + timedelta(days=days, hours=hours)).replace(tzinfo=None).isoformat()


def _seed(synthetic_tenant, persona):
    creds = synthetic_tenant["users"][persona]
    db = database.get_db()
    try:
        me = db.execute("SELECT id, org_id FROM users WHERE username=%s", (creds["username"],)).fetchone()
        parent = me["org_id"]

        def org(name, slug):
            db.execute("INSERT INTO organizations (name, slug, status, plan) VALUES (%s,%s,'active','enterprise')", (name, slug))
            return db.execute("SELECT id FROM organizations WHERE slug=%s", (slug,)).fetchone()["id"]
        tag = uuid.uuid4().hex[:8]
        child, quiet = org("Child Co", "gf_child_" + tag), org("Quiet Co", "gf_quiet_" + tag)
        for kid in (child, quiet):
            db.execute(
                "INSERT INTO org_relationships (parent_org_id,child_org_id,status,purpose,child_ack_by,privacy_review_by,"
                "legal_review_by,terms_json,review_due_at) VALUES (%s,%s,'active','Group',1,2,3,'{}',%s)",
                (parent, kid, _stamp(90)))
            rel = db.execute("SELECT MAX(id) AS i FROM org_relationships").fetchone()["i"]
            db.execute(
                "INSERT INTO group_view_grants (relationship_id,source_org_id,viewer_org_id,user_id,capability,expires_at,"
                "review_due_at,granted_by) VALUES (%s,%s,%s,%s,'figure.view',%s,%s,999)",
                (rel, kid, parent, me["id"], _stamp(30), _stamp(7)))

        def snap(org_id, key, value, module, as_of, version=1):
            db.execute(
                "INSERT INTO group_figure_snapshots (source_org_id,measure_key,module,state,value,window_text,detail_json,"
                "method_version,as_of,publication_version,content_hash) VALUES (%s,%s,%s,'measured',%s,'',%s,'t',%s,%s,%s)",
                (org_id, key, module, value, json.dumps({}), as_of, version, f"h{org_id}{key}{version}"))
        for org_id, breaches, audits in ((parent, 2, 1), (child, 5, 4)):
            snap(org_id, "cc.open_breaches", breaches, "sentinel", _stamp())
            snap(org_id, "cc.grid_open_audit_controls", audits, "grid", _stamp())
        snap(quiet, "cc.open_breaches", 9, "sentinel", _stamp(hours=-100))
        db.commit()
    finally:
        db.close()


def test_a_group_specialist_reads_the_three_views_and_a_silent_subsidiary_is_not_reporting(login_as, live_app, synthetic_tenant):
    _seed(synthetic_tenant, "compliance_manager")
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/governance/group/figures/")
    tabs = page.locator("#gfTabs button")
    expect(tabs).to_have_count(4)
    expect(tabs.nth(1)).to_have_text("Whole group")
    tabs.nth(1).click()
    expect(page.locator("#gfTotals")).to_contain_text("Open breaches")
    expect(page.locator("#gfTotals tr", has_text="Open breaches")).to_contain_text("7")
    expect(page.locator("#gfTotals tr", has_text="Open breaches")).to_contain_text("2 of 3")
    quiet = page.locator("#gfEntities article", has_text="Quiet Co")
    expect(quiet).to_contain_text("Not reporting")
    expect(quiet.locator(".gf-card")).to_have_count(0)  # its old figure of 9 is not shown or counted
    page.locator("#gfTabs button", has_text="Child Co").click()
    expect(page.locator("#gfEntities article")).to_have_count(1)
    expect(page.locator("#gfEntities")).to_contain_text("Reporting")
    expect(page.locator("#gfEntities .gf-card", has_text="Open breaches")).to_contain_text("5")


def test_the_dpo_sees_privacy_figures_only(login_as, live_app, synthetic_tenant):
    _seed(synthetic_tenant, "dpo")
    page = login_as("dpo")
    page.goto(f"{live_app}/governance/group/figures/")
    page.locator("#gfTabs button", has_text="Child Co").click()
    expect(page.locator("#gfEntities .gf-card", has_text="Open breaches")).to_have_count(1)
    expect(page.locator("#gfEntities")).not_to_contain_text("audit controls")


@pytest.mark.parametrize("persona", ["employee", "org_admin", "risk_owner"])
def test_roles_without_group_figure_access_get_a_masked_page_and_api(login_as, live_app, persona):
    page = login_as(persona)
    assert page.goto(f"{live_app}/governance/group/figures/").status == 404
    status = page.evaluate("async () => (await fetch('/governance/api/group/figures/views')).status")
    assert status == 403


def test_an_ungranted_subsidiary_id_is_masked(login_as, live_app, synthetic_tenant):
    _seed(synthetic_tenant, "compliance_manager")
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/governance/group/figures/")
    status = page.evaluate("async () => (await fetch('/governance/api/group/figures?view=subsidiary&org_id=999999')).status")
    assert status == 404
    status = page.evaluate("async () => (await fetch('/governance/api/group/figures?view=subsidiary&org_id=abc')).status")
    assert status == 422
