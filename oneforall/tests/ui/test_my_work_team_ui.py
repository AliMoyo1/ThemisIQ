"""
My Work offers "My team's" to a person who heads a unit, and only to them
(plans/2026-10-governance-rework/11 step 6).
"""
from datetime import datetime, timedelta, timezone

import database


def _set_head(unit_id, user_id):
    db = database.get_db()
    try:
        db.execute("UPDATE business_units SET head_user_id = %s WHERE id = %s", (user_id, unit_id))
        db.commit()
    finally:
        db.close()


def test_a_unit_head_sees_the_work_assigned_to_their_team_and_can_go_back(login_as, live_app, synthetic_tenant):
    unit = synthetic_tenant["business_unit_id"]
    head = synthetic_tenant["users"]["compliance_manager"]["user_id"]
    employee = synthetic_tenant["users"]["employee"]["user_id"]
    due = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
    db = database.get_db()
    try:
        cur = db.execute(
            "INSERT INTO task_board (title, status, priority, due_date, assigned_to, created_by, business_unit_id) "
            "VALUES ('Renew the supplier contract register', 'todo', 'high', %s, %s, %s, %s)",
            (due, employee, employee, unit))
        db.commit()
        task_id = cur.lastrowid
    finally:
        db.close()
    _set_head(unit, head)
    try:
        page = login_as("compliance_manager")
        page.goto(f"{live_app}/my-work")
        page.wait_for_selector("#myWorkViewTeam", state="visible", timeout=10000)
        assert page.locator("#myWorkViewTeam").get_attribute("aria-pressed") == "false"

        page.click("#myWorkViewTeam")
        page.wait_for_selector("#myTeamList section", timeout=10000)
        assert page.locator("#myWorkViewTeam").get_attribute("aria-pressed") == "true"
        assert not page.locator("#myWorkSections").is_visible()
        assert "Notifications and shared queues" in page.locator("#myTeamNote").inner_text()

        card = page.locator("#myTeamList section", has_text="Employee").first
        assert "1 overdue" in card.inner_text()
        link = card.locator("a", has_text="Renew the supplier contract register")
        assert link.get_attribute("href") == f"/tasks?open={task_id}"
        assert f"Due {due}" in link.inner_text()

        # the head's own work is one click away
        page.click("#myWorkViewMine")
        assert page.locator("#myWorkSections").is_visible()
        assert not page.locator("#myTeam").is_visible()
        assert page.locator("#myWorkViewMine").get_attribute("aria-pressed") == "true"
        assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
    finally:
        _set_head(unit, None)
        db = database.get_db()
        try:
            db.execute("DELETE FROM task_board WHERE id = %s", (task_id,))
            db.commit()
        finally:
            db.close()


def test_a_person_who_heads_no_unit_is_not_offered_the_team_view(login_as, live_app):
    page = login_as("employee")
    page.goto(f"{live_app}/my-work")
    page.wait_for_selector("#myWorkSections .mywork-section", timeout=10000)
    page.wait_for_load_state("networkidle")
    assert not page.locator("#myWorkViews").is_visible()
    assert not page.locator("#myWorkViewTeam").is_visible()
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_the_team_view_has_no_serious_accessibility_violations(login_as, live_app, synthetic_tenant, run_axe):
    unit = synthetic_tenant["business_unit_id"]
    head = synthetic_tenant["users"]["compliance_manager"]["user_id"]
    _set_head(unit, head)
    try:
        page = login_as("compliance_manager")
        page.goto(f"{live_app}/my-work")
        page.wait_for_selector("#myWorkViewTeam", state="visible", timeout=10000)
        page.click("#myWorkViewTeam")
        page.wait_for_selector("#myTeamList section", timeout=10000)
        violations = run_axe()
        assert not violations, "; ".join(f"{v['id']}: {v['help']}" for v in violations)
    finally:
        _set_head(unit, None)
