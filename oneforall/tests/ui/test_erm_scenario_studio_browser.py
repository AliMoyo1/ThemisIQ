"""
PLAN-36 P07: real-browser coverage for the ERM Scenario Studio page
(modules/erm/templates/scenario_studio.html). Service and HTTP-level logic
are covered elsewhere (tests/test_erm_scenarios.py,
tests/ui/test_erm_scenarios_routes.py) -- what only a real browser test can
catch is whether the rendered page actually wires its own JS correctly (a
DOM id mismatch, a script error) under the T08 default-fail console-error
gate (tests/ui/conftest.py's `page` fixture).
"""


def test_scenario_studio_loads_and_creates_a_scenario(live_app, page, synthetic_tenant):
    creds = synthetic_tenant["users"]["risk_owner"]
    page.goto(f"{live_app}/login")
    page.fill("#username", creds["username"])
    page.fill("#password", creds["password"])
    page.click("#submitBtn")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url

    page.goto(f"{live_app}/erm/scenario-studio")
    page.wait_for_selector("#ssScenarioList")

    page.click("#ssNewScenarioBtn")
    page.fill("#ssNewTitle", "Browser-created scenario")
    page.click("#ssNewSubmitBtn")

    page.wait_for_selector("#ssScenarioList .ss-list-item:has-text('Browser-created scenario')", timeout=5000)
    # The list refresh and the detail-pane fetch are two separate async
    # calls (loadScenarios() then selectScenario()'s own renderDetail());
    # wait for the detail pane's own render rather than a bare .count(),
    # which does not auto-retry the way wait_for_selector does.
    page.wait_for_selector("#ssDetailPane .ss-name:has-text('Browser-created scenario')", timeout=5000)
    assert page.locator("#ssDetailPane .ss-name:has-text('Browser-created scenario')").count() == 1



def test_scenario_studio_risk_picker_and_guided_override(live_app, page, login_as, synthetic_tenant):
    import database

    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO erm_enterprise_risks (title, status, likelihood, impact, business_unit_id) "
            "VALUES ('Browser picker risk', 'open', 2, 3, %s)",
            (synthetic_tenant["business_unit_id"],),
        )
        db.commit()
    finally:
        db.close()

    login_as("risk_owner")
    page.goto(f"{live_app}/erm/scenario-studio")
    page.locator("#ssNewScenarioBtn").click()
    page.locator("#ssNewTitle").fill("Browser picker scenario")
    page.locator("#ssNewSubmitBtn").click()
    page.locator("[data-step=items]").click()
    page.locator("#ssItemSearch").fill("Browser picker")
    page.locator(".ss-pick:has-text('Browser picker risk') input").check()
    page.locator("[data-step=shocks]").click()
    page.locator("#ssShockList .ss-shock[data-type=risk]").wait_for()
    page.locator("#ssShockList input[data-key=likelihood_override]").fill("5")
    page.locator("#ssShockList input[data-key=impact_override]").fill("4")
    page.locator("[data-step=impact]").click()
    page.locator("#ssStepBody table").first.wait_for()
    # likelihood 2 -> 5 and impact 3 -> 4 is worse than today, so the headline must say so.
    page.wait_for_selector("#ssLiveText:has-text('get worse')", timeout=10000)


def test_a_template_fills_the_new_scenario_form(live_app, page, login_as):
    page = login_as("risk_owner")
    page.goto(f"{live_app}/erm/scenario-studio")
    page.wait_for_selector("#ssDetailPane .ss-tpl")
    page.locator("#ssDetailPane .ss-tpl").first.click()
    page.wait_for_selector("#ssNewModal.open")
    assert page.locator("#ssNewTitle").input_value().strip()
    assert page.locator("#ssNewAssumptions").input_value().strip()


def test_the_steps_open_without_script_errors_and_the_ai_buttons_follow_permissions(live_app, page, login_as):
    page = login_as("risk_owner")
    page.goto(f"{live_app}/erm/scenario-studio")
    page.locator("#ssNewScenarioBtn").click()
    page.locator("#ssNewTitle").fill("Steps scenario")
    page.locator("#ssNewSubmitBtn").click()
    page.wait_for_selector("#ssDetailPane .ss-name:has-text('Steps scenario')")
    for step in ("define", "items", "shocks", "impact", "brief", "compare"):
        page.locator(f"[data-step={step}]").click()
        page.wait_for_selector(f".ss-step[data-step={step}][aria-selected=true]")
        page.wait_for_timeout(150)
    # Related Items and the evidence card are on the first step.
    page.locator("[data-step=define]").click()
    page.wait_for_selector("#ssEvidence")
    page.wait_for_selector("#ssRelated")


def test_scenario_studio_shows_the_same_sidebar_as_the_erm_dashboard(live_app, page, login_as):
    """The studio used to carry its own four item menu, so opening it hid Obligations, Indicators and the rest."""
    page = login_as("risk_owner")
    links = "#moduleSidebar a.nav-item, .module-sidebar a.nav-item"
    page.goto(f"{live_app}/erm/")
    page.wait_for_selector(links)
    dashboard = sorted(a.get_attribute("href") for a in page.locator(links).all())
    page.goto(f"{live_app}/erm/scenario-studio")
    page.wait_for_selector("#ssScenarioList")
    studio = sorted(a.get_attribute("href") for a in page.locator(links).all())
    assert studio == dashboard, (studio, dashboard)
    assert "/erm/obligations" in studio and "/erm/indicators" in studio and "/erm/scenario-studio" in studio
    assert page.locator("#moduleSidebar a.nav-item.active").get_attribute("href") == "/erm/scenario-studio"


def test_the_evidence_vault_opens_its_upload_form_for_a_scenario(live_app, page, login_as):
    page = login_as("risk_owner")
    page.goto(f"{live_app}/erm/scenario-studio")
    page.locator("#ssNewScenarioBtn").click()
    page.locator("#ssNewTitle").fill("Evidence scenario")
    page.locator("#ssNewSubmitBtn").click()
    page.wait_for_selector("#ssDetailPane .ss-name:has-text('Evidence scenario')")
    href = page.locator("#ssEvidence a[href*='attach=erm:scenario:']").get_attribute("href")
    page.goto(f"{live_app}{href}")
    page.wait_for_selector("#uploadModal.open")
    page.wait_for_selector("#uploadLinkSelected:visible")
    assert "Evidence scenario" in page.locator("#uploadLinkSelected").inner_text()


def test_a_real_incident_can_start_a_scenario_that_remembers_it(live_app, page, login_as):
    import database

    db = database.get_db()
    try:
        db.execute("INSERT INTO bcm_incidents (title, description, severity, status) VALUES ('Data centre flood', 'Water in hall B', 'high', 'open')")
        db.commit()
        incident_id = db.execute("SELECT id FROM bcm_incidents WHERE title='Data centre flood'").fetchone()["id"]
    finally:
        db.close()
    page = login_as("super_admin")
    page.goto(f"{live_app}/erm/scenario-studio?model=bcm:incident:{incident_id}")
    page.wait_for_selector("#ssNewModal.open")
    assert page.locator("#ssNewTitle").input_value() == "What if it were worse: Data centre flood"
    assert page.locator("#ssNewDescription").input_value() == "Water in hall B"
    page.locator("#ssNewSubmitBtn").click()
    page.wait_for_selector("#ssDetailPane .ss-name:has-text('What if it were worse')")
    db = database.get_db()
    try:
        row = db.execute(
            "SELECT relationship, target_module, target_type, target_id FROM cross_module_links "
            "WHERE source_module='erm' AND source_type='scenario'").fetchone()
    finally:
        db.close()
    assert row and (row["relationship"], row["target_module"], row["target_type"], row["target_id"]) == ("derived_from", "bcm", "incident", incident_id)
