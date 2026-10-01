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
    page.wait_for_selector("#ssDetailPane .ss-card-title:has-text('Browser-created scenario')", timeout=5000)
    assert page.locator("#ssDetailPane .ss-card-title:has-text('Browser-created scenario')").count() == 1
