"""
The connected view and the changes to look at, in a real browser (plans/2026-10-governance-rework/03 sections 1 and 2): what is
connected to a record, grouped by owning module, with its proof and the changes that name it; a reviewer saying whether a
connected record needs a second look. Each state is checked for serious accessibility violations and for sideways scroll on
a phone.
"""
import uuid

import database


def _record(tenant, label):
    """An application, a process it supports and a file linked to the application; returns their ids."""
    org = tenant["org_id"]
    unit = tenant["business_unit_id"]
    owner = tenant["users"]["compliance_manager"]["user_id"]
    db = database.get_db()
    try:
        app = db.execute("INSERT INTO applications (name, business_unit_id, owner_user_id, criticality, hosting, is_active) "
                         "VALUES (%s, %s, %s, 'medium', 'saas', 1)", (f"App {label}", unit, owner)).lastrowid
        process = db.execute("INSERT INTO business_processes (name, business_unit_id, owner_user_id, criticality, is_active) "
                             "VALUES (%s, %s, %s, 'high', 1)", (f"Process {label}", unit, owner)).lastrowid
        db.execute("INSERT INTO cross_module_links (source_module, source_type, source_id, target_module, target_type, "
                   "target_id, relationship, provenance, status) VALUES ('governance', 'application', %s, 'governance', "
                   "'process', %s, 'supports', 'manual', 'confirmed')", (app, process))
        item = db.execute("INSERT INTO evidence_items (title, status, org_id, version) VALUES (%s, 'current', %s, 1)",
                          (f"Proof {label}", org)).lastrowid
        db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, review_status) "
                   "VALUES (%s, 'governance', 'application', %s, 'accepted')", (item, app))
        db.commit()
        return app, process, item
    finally:
        db.close()


def test_the_connected_view_names_the_connections_the_proof_and_a_change(login_as, live_app, page, synthetic_tenant, run_axe):
    label = uuid.uuid4().hex[:8]
    app, process, _ = _record(synthetic_tenant, label)
    login_as("compliance_manager")
    page.goto(f"{live_app}/governance/connected/governance/application/{app}")
    page.wait_for_selector(".gc-h1")
    text = page.inner_text("#gcRoot")
    assert f"App {label}" in text and f"Process {label}" in text and f"Proof {label}" in text
    assert "Accepted" in text and "No connected record has changed" in text
    assert page.locator(f"a:has-text('Process {label}')").count() == 1
    page.wait_for_timeout(200)
    assert run_axe() == []

    # change the application: the connected process now has a change to look at
    from modules.governance import data_service as ds
    row = {"name": f"App {label}", "criticality": "critical", "hosting": "on_premises", "is_active": 1,
           "business_unit_id": synthetic_tenant["business_unit_id"],
           "owner_user_id": synthetic_tenant["users"]["compliance_manager"]["user_id"]}
    ds.update_application(app, row)
    page.goto(f"{live_app}/governance/changes")
    page.wait_for_selector(f"#gcRoot:has-text('Process {label}')")
    changes = page.inner_text("#gcRoot")
    assert "An application changed" in changes and "Hosting: saas to on_premises" in changes
    assert "Criticality: medium to critical" in changes
    assert page.locator("button:has-text('It needs a second look')").count() >= 1
    assert run_axe() == [], "the changes page"

    entry = page.locator("#gcRoot li", has_text=f"Process {label}").first
    entry.locator("input").fill("Recovery targets are unaffected.")
    entry.locator("button:has-text('No action needed')").click()
    page.wait_for_function("(label) => !document.getElementById('gcRoot').innerText.includes('Process ' + label)", arg=label)

    page.goto(f"{live_app}/governance/connected/governance/process/{process}")
    page.wait_for_selector("#gcRoot:has-text('No action needed')")
    assert "Recovery targets are unaffected." in page.inner_text("#gcRoot")


def test_a_record_the_person_may_not_open_is_not_found_and_the_pages_fit_a_phone(login_as, live_app, page, synthetic_tenant):
    app, process, _ = _record(synthetic_tenant, uuid.uuid4().hex[:8])
    login_as("compliance_manager")
    assert page.goto(f"{live_app}/governance/connected/governance/application/99999999").status == 404
    assert page.goto(f"{live_app}/governance/connected/not_a_module/application/1").status == 404
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{live_app}/governance/connected/governance/application/{app}")
    page.wait_for_selector(".gc-h1")
    page.wait_for_timeout(200)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    page.goto(f"{live_app}/governance/changes")
    page.wait_for_selector("#gcRoot")
    page.wait_for_timeout(200)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


def test_the_governance_tables_and_the_ai_system_lead_to_the_connected_view(login_as, live_app, page, synthetic_tenant):
    app, process, _ = _record(synthetic_tenant, uuid.uuid4().hex[:8])
    login_as("compliance_manager")
    page.goto(f"{live_app}/governance/")
    page.click(".gov-tab[data-tab='app']")
    link = f"#appTBody a[href='/governance/connected/governance/application/{app}']"
    page.wait_for_selector(link)
    page.click(link)
    page.wait_for_selector(".gc-h1")
    assert page.url.endswith(f"/governance/connected/governance/application/{app}")

    page.goto(f"{live_app}/governance/")
    page.click(".gov-tab[data-tab='bp']")
    page.wait_for_selector(f"#bpTBody a[href='/governance/connected/governance/process/{process}']")
    page.click("a.gov-tab:has-text('Changes to look at')")
    page.wait_for_selector("h1:has-text('Changes to look at')")
    assert page.url.endswith("/governance/changes")
