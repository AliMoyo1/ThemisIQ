"""GRID under strict script CSP: every journey runs through the delegated action dispatcher, with no inline handler,
no console error, and record text that tries to plant its own action staying inert."""
import secrets

import database
import pytest
from playwright.sync_api import expect

HOSTILE = '<img src=x data-grid-click="lockAudit(1)">'


@pytest.fixture
def grid_world(live_app, synthetic_tenant):
    tag = secrets.token_hex(3)
    unit = synthetic_tenant["business_unit_id"]
    db = database.get_db()
    try:
        lead = db.execute("SELECT id FROM users WHERE username=%s",
                          (synthetic_tenant["users"]["audit_lead"]["username"],)).fetchone()["id"]
        parent = database.insert_returning_id(
            db, "INSERT INTO grid_audits (name, business_unit_id, lead_id, status) VALUES (%s,%s,%s,'Planning')",
            (f"Parent audit {tag}", unit, lead))
        audit = database.insert_returning_id(
            db, "INSERT INTO grid_audits (name, business_unit_id, lead_id, status, parent_audit_id) "
                "VALUES (%s,%s,%s,'Planning',%s)", (f"CSP audit {tag} {HOSTILE}", unit, lead, parent))
        control = database.insert_returning_id(
            db, "INSERT INTO grid_controls (audit_id, control_id, name, status) VALUES (%s,%s,%s,'Not Started')",
            (audit, "C." + tag, f"Firewall review {HOSTILE}"))
        nc = database.insert_returning_id(
            db, "INSERT INTO grid_non_conformances (audit_id, title, severity, status, due_date) "
                "VALUES (%s,%s,'minor','open',%s)", (audit, f"Finding {tag} {HOSTILE}", '2026-12-01" data-x="1'))
        vault = database.insert_returning_id(
            db, "INSERT INTO evidence_items (title, status, version, file_hash, org_id, business_unit_id, uploaded_by) "
                "VALUES (%s,'current',1,%s,%s,%s,%s)",
            (f"Vault proof {tag}", "h-" + tag, synthetic_tenant["org_id"], unit, lead))
        db.commit()
        yield {"db": db, "tag": tag, "audit": audit, "parent": parent, "control": control, "nc": nc, "vault": vault}
    finally:
        db.execute("DELETE FROM grid_evidence_files WHERE control_id=%s", (control,))
        db.execute("DELETE FROM evidence_links WHERE evidence_id=%s", (vault,))
        db.execute("DELETE FROM evidence_items WHERE id=%s", (vault,))
        for table, key, value in (("grid_non_conformances", "audit_id", audit), ("grid_controls", "audit_id", audit)):
            db.execute(f"DELETE FROM {table} WHERE {key}=%s", (value,))
        db.execute("DELETE FROM grid_audits WHERE id IN (%s,%s)", (audit, parent))
        db.commit()
        db.close()


def _watch(page):
    problems = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
    return problems


def _assert_inert(page):
    """The hostile text is shown as text: no element it described exists anywhere on the page."""
    assert page.locator('img[src="x"]').count() == 0
    assert page.locator('[data-grid-click="lockAudit(1)"]').count() == 0


def test_grid_pages_send_a_strict_script_policy(login_as, live_app, grid_world):
    page = login_as("audit_lead")
    for path in ("/grid/", f"/grid/audits/{grid_world['audit']}", "/grid/findings", "/grid/assignments/"):
        response = page.goto(f"{live_app}{path}")
        policy = response.headers["content-security-policy"]
        script = next(p for p in policy.split(";") if p.strip().startswith("script-src "))
        assert "'unsafe-inline'" not in script and "script-src-attr 'none'" in policy, path
        assert "cdn.jsdelivr.net" not in script, path


def test_audits_list_detail_stepper_and_modals_work_through_the_dispatcher(login_as, live_app, grid_world):
    page = login_as("audit_lead")
    problems = _watch(page)
    page.goto(f"{live_app}/grid/")
    chip = page.locator('#gridStatusFilters button.filter-chip[data-status="planning"]')
    chip.click()
    expect(chip).to_have_class("filter-chip active")
    page.goto(f"{live_app}/grid/audits")
    card = page.locator(".audit-card", has_text=f"CSP audit {grid_world['tag']}")
    expect(card).to_contain_text("<img src=x")
    _assert_inert(page)
    page.get_by_role("button", name="New Audit").first.click()
    expect(page.locator("#newAuditForm")).to_be_visible()
    page.locator("#imsAuditToggle").check()
    expect(page.locator("#createAuditBtn")).to_have_text("Create IMS Audit")
    page.locator("#newAuditForm").get_by_role("button", name="Cancel").click()
    expect(page.locator("#newAuditForm")).to_have_count(0)

    card.click()
    expect(page).to_have_url(f"{live_app}/grid/audits/{grid_world['audit']}")
    _assert_inert(page)
    page.locator('.audit-step[data-status="Active"]').click()
    expect(page.locator('.audit-step[data-status="Active"]')).to_have_class("audit-step active")
    status = grid_world["db"].execute("SELECT status FROM grid_audits WHERE id=%s",
                                      (grid_world["audit"],)).fetchone()["status"]
    assert status == "Active"
    page.locator("[data-grid-import-audit]").click()
    expect(page.locator("#checklistImportForm")).to_be_visible()
    page.locator("#checklistImportForm").get_by_role("button", name="Cancel").click()
    expect(page.locator("#checklistImportForm")).to_have_count(0)
    chain = page.get_by_role("link", name=f"Parent audit {grid_world['tag']}")
    expect(chain).to_have_attribute("href", f"/grid/audits/{grid_world['parent']}")
    chain.click()
    expect(page).to_have_url(f"{live_app}/grid/audits/{grid_world['parent']}")
    assert problems == [], problems


def test_sign_off_evidence_upload_replacement_and_report_download_work_under_strict_policy(
        login_as, live_app, grid_world, tmp_path):
    page = login_as("audit_lead")
    problems = _watch(page)
    db = grid_world["db"]
    page.goto(f"{live_app}/grid/audits/{grid_world['audit']}")
    page.locator("#leadSignoffComment").fill("Reviewed under strict policy")
    page.get_by_role("button", name="Sign as Lead").click()
    expect(page.get_by_role("button", name="Revoke").first).to_be_visible()
    row = db.execute("SELECT role, comment FROM grid_audit_signoffs WHERE audit_id=%s", (grid_world["audit"],)).fetchone()
    assert (row["role"], row["comment"]) == ("lead", "Reviewed under strict policy")

    page.locator(".ctrl-row", has_text="C." + grid_world["tag"]).click()
    first = tmp_path / "access-review.txt"
    first.write_text("Quarterly access review, first version")
    page.locator("#cdFileInput").set_input_files(str(first))
    page.wait_for_function(
        "async () => (await (await fetch('/grid/api/controls/%d')).json()).evidence_uploaded >= 1"
        % grid_world["control"])
    page.goto(f"{live_app}/grid/audits/{grid_world['audit']}")
    page.locator(".ctrl-row", has_text="C." + grid_world["tag"]).click()
    second = tmp_path / "access-review-v2.txt"
    second.write_text("Quarterly access review, second version")
    with page.expect_file_chooser() as chooser:
        page.locator(".ctrl-detail-panel").get_by_title("Upload new version").first.click()
    chooser.value.set_files(str(second))
    page.wait_for_function(
        "async () => { const c = await (await fetch('/grid/api/controls/%d')).json();"
        " return (c.evidence_files || []).some(f => f.version >= 2); }" % grid_world["control"])
    page.locator(".ctrl-detail-panel .ctrl-panel-close").click()

    page.goto(f"{live_app}/grid/reports")
    card = page.locator("div", has_text=f"CSP audit {grid_world['tag']}").filter(
        has=page.locator('button[data-grid-click^="downloadReport("]')).last
    with page.expect_download(timeout=90000) as download:
        card.locator('button[data-grid-click^="downloadReport("]').first.click()
    assert download.value.suggested_filename.endswith(".pdf")
    assert problems == [], problems


def test_a_control_and_a_finding_open_change_and_close_under_strict_policy(login_as, live_app, grid_world):
    page = login_as("audit_lead")
    problems = _watch(page)
    db = grid_world["db"]
    page.goto(f"{live_app}/grid/audits/{grid_world['audit']}")
    page.locator(".ctrl-row", has_text="C." + grid_world["tag"]).click()
    expect(page.locator(".ctrl-detail-panel")).to_be_visible()
    _assert_inert(page)
    page.locator("#cdStatus").select_option("In Progress")
    page.wait_for_function(
        "async () => (await (await fetch('/grid/api/controls/%d')).json()).status === 'In Progress'"
        % grid_world["control"])
    page.locator(".ctrl-detail-panel").get_by_role("button", name="Browse Vault").click()
    search = page.get_by_label("Search vault")
    expect(search).to_be_visible()
    choice = page.locator(".grid-pick-row", has_text=f"Vault proof {grid_world['tag']}")
    search.fill("no such file " + grid_world["tag"])
    expect(choice).to_be_hidden()
    search.fill(grid_world["tag"])
    expect(choice).to_be_visible()
    choice.click()
    page.wait_for_function(
        "async () => (await (await fetch('/grid/api/controls/%d')).json()).evidence_uploaded >= 1"
        % grid_world["control"])
    page.goto(f"{live_app}/grid/audits/{grid_world['audit']}")
    page.locator(".ctrl-row", has_text="C." + grid_world["tag"]).click()
    page.locator(".ctrl-detail-panel .ctrl-panel-close").click()
    expect(page.locator(".ctrl-detail-panel")).to_have_count(0)

    page.goto(f"{live_app}/grid/findings")
    row = page.locator("tr", has_text=f"Finding {grid_world['tag']}")
    expect(row).to_contain_text("<img src=x")
    _assert_inert(page)
    row.click()
    expect(page.locator(".nc-panel-header")).to_be_visible()
    assert page.locator('[data-x="1"]').count() == 0, "a quote in a date cannot add an attribute"
    page.locator("#ncFldSeverity").select_option("major")
    page.wait_for_function(
        "async () => { const r = await fetch('/grid/api/ncs/%d'); return r.ok && (await r.json()).severity === 'major'; }"
        % grid_world["nc"])
    page.locator(".nc-panel-close").click()
    expect(page.locator(".nc-panel-header")).to_have_count(0)
    assert db.execute("SELECT status FROM grid_audits WHERE id=%s", (grid_world["audit"],)).fetchone()["status"] \
        == "Planning", "the planted lockAudit action never ran"
    assert problems == [], problems
