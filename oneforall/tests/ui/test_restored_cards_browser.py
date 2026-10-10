"""A business-unit-restricted role sees its unit's SLA, workflow and platform risk figures, not zeros.

e3ddfad zeroed these cards, and hid the platform risk register, for every role except the super
administrator, because the three tables had no owner. They now carry one, so the Command Centre and the
risk register page must show a restricted role the rows of its own unit. The numbers are compared with the
same page's own API before and after rows are added, so other tests' leftovers cannot change the answer.
"""
import database

PROBE_RISK = "Browser probe platform risk"


def _stats(page):
    return page.evaluate("async () => (await fetch('/api/command-centre/stats')).json()")


def _seed(synthetic_tenant, owner):
    """One active breached SLA clock, one active workflow instance and one critical platform risk in the
    harness business unit. Returns a function that removes them again."""
    org, unit, user = synthetic_tenant["org_id"], synthetic_tenant["business_unit_id"], owner["user_id"]
    db = database.get_db()
    ids = {}
    try:
        ids["flow_def"] = database.insert_returning_id(
            db, "INSERT INTO workflow_definitions (name, steps_json, created_by) VALUES ('Probe flow', '[]', %s)",
            (user,))
        ids["flow"] = database.insert_returning_id(
            db, "INSERT INTO workflow_instances (definition_id, org_id, status, started_by, business_unit_id) "
                "VALUES (%s, %s, 'active', %s, %s)", (ids["flow_def"], org, user, unit))
        ids["sla_def"] = database.insert_returning_id(
            db, "INSERT INTO sla_definitions (name, module, entity_type) VALUES ('Probe SLA', 'sentinel', 'breach')", ())
        ids["sla"] = database.insert_returning_id(
            db, "INSERT INTO sla_instances (definition_id, org_id, entity_module, entity_type, status, breached, "
                "resolution_due, business_unit_id) VALUES (%s, %s, 'sentinel', 'breach', 'active', 1, "
                "'2000-01-01 00:00:00', %s)", (ids["sla_def"], org, unit))
        ids["risk"] = database.insert_returning_id(
            db, "INSERT INTO risk_register (title, likelihood, impact, risk_level, source_module, business_unit_id) "
                "VALUES (%s, 5, 5, 'critical', 'sentinel', %s)", (PROBE_RISK, unit))
        db.commit()
    finally:
        db.close()

    def remove():
        cleanup = database.get_db()
        try:
            for table, key in (("sla_instances", "sla"), ("workflow_instances", "flow"), ("risk_register", "risk"),
                               ("sla_definitions", "sla_def"), ("workflow_definitions", "flow_def")):
                cleanup.execute(f"DELETE FROM {table} WHERE id = %s", (ids[key],))
            cleanup.commit()
        finally:
            cleanup.close()

    return remove


def test_a_risk_owner_sees_the_units_sla_workflow_and_platform_risk_figures(login_as, live_app, synthetic_tenant):
    page = login_as("risk_owner")
    page.goto(f"{live_app}/")
    page.wait_for_load_state("networkidle")
    before = _stats(page)
    remove = _seed(synthetic_tenant, synthetic_tenant["users"]["risk_owner"])
    try:
        page.reload()
        page.wait_for_load_state("networkidle")
        after = _stats(page)
        assert after["sla"]["breached"] == before["sla"]["breached"] + 1
        assert after["workflow_active"] == before["workflow_active"] + 1
        assert after["risk_counts"]["critical"] == before["risk_counts"]["critical"] + 1
        assert page.locator("#ccWorkflowActive").inner_text().strip() == str(after["workflow_active"])
        assert page.locator("#ccRiskCrit").inner_text().strip().startswith(f"{after['risk_counts']['critical']} ")

        page.goto(f"{live_app}/risk-register")
        page.get_by_text(PROBE_RISK).wait_for()
        assert page.locator('button[onclick="openNewRisk()"]').count() == 0   # registering is the administrator's
        assert not page.console_errors, page.console_errors
    finally:
        remove()


def test_an_employee_sees_the_units_clocks_and_workflows_but_no_platform_risks(login_as, live_app, synthetic_tenant):
    """Platform risks need the capability the ERM module requires; clocks and workflows need only a sign-in."""
    page = login_as("employee")
    page.goto(f"{live_app}/")
    page.wait_for_load_state("networkidle")
    before = _stats(page)
    remove = _seed(synthetic_tenant, synthetic_tenant["users"]["employee"])
    try:
        page.reload()
        page.wait_for_load_state("networkidle")
        after = _stats(page)
        assert after["sla"]["breached"] == before["sla"]["breached"] + 1
        assert after["workflow_active"] == before["workflow_active"] + 1
        assert after["risk_counts"] == before["risk_counts"]

        page.goto(f"{live_app}/risk-register")
        page.wait_for_load_state("networkidle")
        assert page.get_by_text(PROBE_RISK).count() == 0
        assert not page.console_errors, page.console_errors
    finally:
        remove()


def test_the_super_administrator_still_sees_the_new_risk_button_and_every_unit(login_as, live_app, synthetic_tenant):
    page = login_as("super_admin")
    remove = _seed(synthetic_tenant, synthetic_tenant["users"]["risk_owner"])
    try:
        page.goto(f"{live_app}/risk-register")
        page.get_by_text(PROBE_RISK).wait_for()
        assert page.locator('button[onclick="openNewRisk()"]').count() == 1
        assert not page.console_errors, page.console_errors
    finally:
        remove()
