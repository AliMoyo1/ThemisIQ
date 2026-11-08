"""ERM under strict script CSP: the page script is a static file, every control is a data action read by a fixed
dispatcher, and record text that tries to plant an action stays inert. Two controls that never worked (the framework
editor's fields and the risk drawer's Edit button) now do."""
import secrets

import database
import pytest
from playwright.sync_api import expect

HOSTILE = '<img src=x data-erm-click="ermBulkDelete()">'


@pytest.fixture
def erm_world(live_app, synthetic_tenant):
    tag = secrets.token_hex(3)
    db = database.get_db()
    try:
        owner = db.execute("SELECT id FROM users WHERE username=%s",
                           (synthetic_tenant["users"]["risk_owner"]["username"],)).fetchone()["id"]
        risk = database.insert_returning_id(
            db, "INSERT INTO erm_enterprise_risks (title, likelihood, impact, owner_id, status, business_unit_id, "
                "workflow_step) VALUES (%s,4,4,%s,'open',%s,'draft')",
            (f"Supplier outage {tag} {HOSTILE}", owner, synthetic_tenant["business_unit_id"]))
        db.commit()
        yield {"db": db, "tag": tag, "risk": risk}
    finally:
        db.execute("DELETE FROM erm_enterprise_risks WHERE id=%s", (risk,))
        db.commit()
        db.close()


def _watch(page):
    problems = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
    return problems


def test_erm_pages_send_a_strict_script_policy(login_as, live_app):
    page = login_as("risk_owner")
    for path in ("/erm/", "/erm/register", "/erm/framework-admin", "/erm/scenario-studio"):
        response = page.goto(f"{live_app}{path}")
        assert response.status == 200, path
        policy = response.headers["content-security-policy"]
        script = next(p for p in policy.split(";") if p.strip().startswith("script-src "))
        assert "'unsafe-inline'" not in script and "script-src-attr 'none'" in policy, path


def test_the_register_drawer_workflow_and_edit_work_and_hostile_text_stays_inert(login_as, live_app, erm_world):
    page = login_as("risk_owner")
    problems = _watch(page)
    page.goto(f"{live_app}/erm/register")
    row = page.locator("#ermRegBody tr", has_text=f"Supplier outage {erm_world['tag']}")
    expect(row).to_contain_text("<img src=x")
    assert page.locator('img[src="x"]').count() == 0
    assert page.locator('[data-erm-click="ermBulkDelete()"]').count() == 1, "only the page's own Delete selected button"
    page.locator("#regSearch").fill("no such risk " + erm_world["tag"])
    expect(row).to_have_count(0)
    page.locator("#regSearch").fill(erm_world["tag"])
    expect(row).to_be_visible()
    row.click()
    drawer = page.locator(".erm-drawer-panel")
    expect(drawer).to_contain_text(f"Supplier outage {erm_world['tag']}")
    drawer.locator("button.wf-step-btn", has_text="identified").click()
    page.wait_for_function(
        "async () => (await (await fetch('/erm/api/risks/%d')).json()).workflow_step === 'identified'" % erm_world["risk"])
    drawer = page.locator(".erm-drawer-panel")
    drawer.get_by_role("button", name="Edit", exact=True).click()
    modal = page.locator("#ermRiskModal")
    expect(modal).to_be_visible()
    expect(modal.locator("#rsk_title")).to_have_value(f"Supplier outage {erm_world['tag']} {HOSTILE}")
    modal.get_by_role("button", name="Cancel").click()
    expect(modal).to_have_count(0)
    assert problems == [], problems


def test_the_framework_editor_fields_now_change_what_is_saved(login_as, live_app):
    tag = secrets.token_hex(3)
    page = login_as("risk_owner")
    problems = _watch(page)
    page.goto(f"{live_app}/erm/framework-admin")
    page.get_by_role("button", name="+ New Framework").click()
    page.locator("#fwn_name").fill(f"Pilot framework {tag}")
    page.locator("#fwNewModal").get_by_role("button", name="Create").click()
    name = page.locator('input[data-erm-input="fwEditorSet(\'name\',this.value)"]')
    expect(name).to_have_value(f"Pilot framework {tag}")
    name.fill(f"Renamed framework {tag}")
    page.get_by_role("button", name="Save Framework").click()
    page.wait_for_function(
        "async (want) => (await (await fetch('/erm/api/frameworks')).json()).some(f => f.name === want)",
        arg=f"Renamed framework {tag}")
    assert problems == [], problems


def test_scenario_studio_runs_from_its_static_script(login_as, live_app):
    page = login_as("risk_owner")
    problems = _watch(page)
    page.goto(f"{live_app}/erm/scenario-studio")
    page.wait_for_load_state("networkidle")
    flags = page.evaluate("Object.assign({}, document.getElementById('ssPageConfig').dataset)")
    assert set(flags) == {"canManage", "canAi", "canRehearse", "canGenerateBoardpacks", "canPublishBoardpacks"}
    assert problems == [], problems
