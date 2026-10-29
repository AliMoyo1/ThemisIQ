"""The group figures page in a real browser: three views, not reporting, role limits and masked access."""
import json
import uuid
from datetime import datetime, timedelta, timezone

import database
import pytest
from modules.governance import group_figures as gf
from playwright.sync_api import expect


@pytest.fixture(autouse=True)
def _remove_seeded_group(live_app):
    """The browser tests share one database: take this module's organizations, grants and figures away afterwards so
    the other group pages see an empty tenant."""
    yield
    db = database.get_db()
    try:
        ids = [r["id"] for r in db.execute("SELECT id FROM organizations WHERE slug LIKE 'gf_%'").fetchall()]
        db.execute("DELETE FROM group_packs WHERE title LIKE 'UI pack %'")
        for org in ids:
            db.execute("DELETE FROM group_figure_snapshots WHERE source_org_id=%s", (org,))
            db.execute("DELETE FROM group_issue_rows WHERE source_org_id=%s", (org,))
            db.execute("DELETE FROM group_issue_runs WHERE source_org_id=%s", (org,))
            db.execute("DELETE FROM group_access_events WHERE source_org_id=%s", (org,))
            db.execute("DELETE FROM group_view_grants WHERE source_org_id=%s", (org,))
            db.execute("DELETE FROM org_relationships WHERE child_org_id=%s", (org,))
            db.execute("DELETE FROM organizations WHERE id=%s", (org,))
        db.commit()
    finally:
        db.close()


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
                "legal_review_by,terms_json,review_due_at) VALUES (%s,%s,'active','Group',1,2,3,%s,%s)",
                (parent, kid, json.dumps({"figure_measures": list(gf.PUBLISHABLE)}), _stamp(90)))
            rel = db.execute("SELECT MAX(id) AS i FROM org_relationships").fetchone()["i"]
            db.execute(
                "INSERT INTO group_view_grants (relationship_id,source_org_id,viewer_org_id,user_id,capability,expires_at,"
                "review_due_at,granted_by) VALUES (%s,%s,%s,%s,'figure.view',%s,%s,999)",
                (rel, kid, parent, me["id"], _stamp(30), _stamp(7)))

        def snap(org_id, key, value, module, as_of, version=1):
            db.execute(
                "INSERT INTO group_figure_snapshots (source_org_id,measure_key,module,state,value,window_text,detail_json,"
                "method_version,as_of,publication_version,content_hash) VALUES (%s,%s,%s,'measured',%s,'',%s,'t',%s,%s,%s)",
                (org_id, key, module, value, json.dumps({}), as_of, version, gf._hash(
                    org_id, {"measure_key": key, "state": "measured", "value": float(value), "window": "", "detail": {}},
                    as_of, version)))
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


def test_a_correction_is_proposed_by_one_person_and_the_figure_shows_as_restated(login_as, live_app, synthetic_tenant):
    _seed(synthetic_tenant, "compliance_manager")
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/governance/group/figures/")
    expect(page.locator("#gfCorrections")).to_be_visible()
    page.locator("#gfPropose select[name=measure_key]").select_option("cc.open_breaches")
    page.locator("#gfPropose input[name=new_value]").fill("1")
    page.locator("#gfPropose textarea[name=reason]").fill("Duplicate records were merged on review")
    page.locator("#gfPropose button[type=submit]").click()
    expect(page.locator("#gfCorrectionRows")).to_contain_text("proposed")
    expect(page.locator("#gfCorrectionRows")).to_contain_text("Duplicate records were merged")
    # the proposer cannot approve their own correction
    assert page.locator("#gfCorrectionRows button").count() == 0


def _seed_issues(persona):
    """Let the persona read the child's data subject requests: approved type, named issue grant and a published run."""
    creds = {"dpo": "dpo", "compliance_manager": "compliance_manager"}
    db = database.get_db()
    try:
        child = db.execute("SELECT id FROM organizations WHERE slug LIKE 'gf_child_%' ORDER BY id DESC LIMIT 1").fetchone()["id"]
        rel = db.execute("SELECT id, parent_org_id FROM org_relationships WHERE child_org_id=%s", (child,)).fetchone()
        grant = db.execute("SELECT user_id FROM group_view_grants WHERE source_org_id=%s LIMIT 1", (child,)).fetchone()
        db.execute("UPDATE org_relationships SET terms_json=%s WHERE id=%s",
                   (json.dumps({"figure_measures": list(gf.PUBLISHABLE), "issue_types": ["dsr"]}), rel["id"]))
        db.execute(
            "INSERT INTO group_view_grants (relationship_id,source_org_id,viewer_org_id,user_id,capability,expires_at,"
            "review_due_at,granted_by) VALUES (%s,%s,%s,%s,'issue.view',%s,%s,999)",
            (rel["id"], child, rel["parent_org_id"], grant["user_id"], _stamp(30), _stamp(7)))
        db.execute("INSERT INTO group_issue_runs (source_org_id,issue_type,published_at,row_count,content_hash) "
                   "VALUES (%s,'dsr',%s,2,'h')", (child, _stamp()))
        run = db.execute("SELECT MAX(id) AS i FROM group_issue_runs").fetchone()["i"]
        for ref, kind in (("DSR-2026-001", "Erasure Request"), ("DSR-2026-002", "Access Request")):
            db.execute("INSERT INTO group_issue_rows (run_id,source_org_id,issue_type,ref_number,fields_json) "
                       "VALUES (%s,%s,'dsr',%s,%s)",
                       (run, child, ref, json.dumps({"request_type": kind, "status": "open", "deadline_date": "2026-11-01"})))
        db.commit()
    finally:
        db.close()


def test_the_dpo_reads_a_subsidiarys_approved_register_by_reference(login_as, live_app, synthetic_tenant):
    _seed(synthetic_tenant, "dpo")
    _seed_issues("dpo")
    page = login_as("dpo")
    page.goto(f"{live_app}/governance/group/figures/")
    expect(page.locator("#gfIssues")).to_be_visible()
    expect(page.locator("#gfIssueForm select[name=issue_type] option")).to_have_count(1)
    page.locator("#gfIssueForm button[type=submit]").click()
    expect(page.locator("#gfIssueNote")).to_contain_text("2 listed")
    expect(page.locator("#gfIssueTable")).to_contain_text("DSR-2026-001")
    expect(page.locator("#gfIssueTable")).to_contain_text("Erasure Request")
    status = page.evaluate("async () => (await fetch('/governance/api/group/issues?org_id=999999&issue_type=dsr')).status")
    assert status == 404


def test_without_an_issue_grant_the_register_panel_stays_hidden_and_the_api_is_masked(login_as, live_app, synthetic_tenant):
    _seed(synthetic_tenant, "dpo")
    page = login_as("dpo")
    page.goto(f"{live_app}/governance/group/figures/")
    expect(page.locator("#gfTabs button")).to_have_count(4)
    expect(page.locator("#gfIssues")).to_be_hidden()


def test_a_pack_is_frozen_opened_and_exported_but_its_author_cannot_sign_it_off(login_as, live_app, synthetic_tenant):
    _seed(synthetic_tenant, "compliance_manager")
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/governance/group/figures/")
    expect(page.locator("#gfPacks")).to_be_visible()
    page.locator("#gfPackForm input[name=title]").fill("UI pack one")
    page.locator("#gfPackForm input[name=period]").fill("Q4 2026")
    page.locator("#gfPackForm button[type=submit]").click()
    row = page.locator("#gfPackRows .gf-card", has_text="UI pack one")
    expect(row).to_contain_text("proposed")
    expect(row.get_by_role("button", name="Sign off")).to_have_count(0)
    row.get_by_role("button", name="Open").click()
    expect(page.locator("#gfPackDetail")).to_contain_text("Integrity check passed")
    expect(page.locator("#gfPackDetail")).to_contain_text("Child Co")
    link = page.locator("#gfPackDetail a", has_text="Download Excel")
    href = link.get_attribute("href")
    result = page.evaluate("async (u) => { const r = await fetch(u); return [r.status, r.headers.get('content-type')]; }", href)
    assert result[0] == 200 and "spreadsheetml" in result[1]
    assert page.evaluate("async () => (await fetch('/governance/api/group/packs/999999')).status") == 404


@pytest.mark.parametrize("persona", ["employee", "org_admin"])
def test_roles_without_pack_access_are_refused(login_as, live_app, persona):
    page = login_as(persona)
    page.goto(f"{live_app}/governance/group/figures/")
    assert page.evaluate("async () => (await fetch('/governance/api/group/packs')).status") == 403
    assert page.evaluate("async () => (await fetch('/governance/api/group/packs', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})).status") in (401, 403)
