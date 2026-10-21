"""
The incident list and console show where the acknowledgement clock stands, and the commander or a BCM manager can
acknowledge from the console (plans/2026-10-governance-rework/13).
"""
from datetime import datetime, timedelta, timezone

import database


def _stamp(minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _insert(title, severity, due, escalated=None):
    db = database.get_db()
    try:
        cur = db.execute(
            "INSERT INTO bcm_incidents (title, description, severity, status, ack_due_at, escalated_at) "
            "VALUES (%s, 'x', %s, 'active', %s, %s)", (title, severity, due, escalated))
        db.commit()
        return cur.lastrowid
    finally:
        db.close()


def _row(incident_id):
    db = database.get_db()
    try:
        return dict(db.execute("SELECT * FROM bcm_incidents WHERE id = %s", (incident_id,)).fetchone())
    finally:
        db.close()


def _delete(incident_id):
    db = database.get_db()
    try:
        db.execute("DELETE FROM bcm_incident_updates WHERE incident_id = %s", (incident_id,))
        db.execute("DELETE FROM bcm_incidents WHERE id = %s", (incident_id,))
        db.commit()
    finally:
        db.close()


def test_a_manager_sees_the_clock_and_acknowledges_from_the_console(login_as, live_app):
    incident = _insert("Generator did not start at the data centre", "critical", _stamp(10))
    try:
        page = login_as("super_admin")
        page.goto(f"{live_app}/bcm/incidents")
        row = page.locator("tr", has_text="Generator did not start at the data centre")
        row.wait_for(timeout=10000)
        assert row.locator("[data-ack=awaiting]").inner_text().startswith("Acknowledge by ")

        row.get_by_text("Generator did not start at the data centre").first.click()
        line = page.locator("#bcmAckLine")
        line.wait_for(timeout=8000)
        assert "a 15 minute window" in line.inner_text()
        page.click("#bcmAckBtn")
        page.wait_for_selector("#bcmAckLine:has-text('Acknowledged')", timeout=8000)
        assert not page.locator("#bcmAckBtn").count(), "nothing left to acknowledge"
        assert _row(incident)["acknowledged_at"] and _row(incident)["acknowledged_by"]

        page.locator(".bcm-console-head button", has_text="Close").click()
        page.wait_for_selector("tr:has-text('Generator did not start') [data-ack=acknowledged]", timeout=8000)
        assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
    finally:
        _delete(incident)


def test_an_escalated_incident_says_so_in_the_list_and_the_console(login_as, live_app):
    incident = _insert("Ransomware note on a file server", "critical", _stamp(-20), escalated=_stamp(-5))
    try:
        page = login_as("super_admin")
        page.goto(f"{live_app}/bcm/incidents")
        row = page.locator("tr", has_text="Ransomware note on a file server")
        row.wait_for(timeout=10000)
        assert row.locator("[data-ack=escalated]").inner_text() == "Not acknowledged: escalated"
        row.get_by_text("Ransomware note on a file server").first.click()
        page.wait_for_selector("#bcmAckLine:has-text('The BCM managers were told')", timeout=8000)
        assert page.locator("#bcmAckBtn").is_visible(), "a manager can still take it over"
    finally:
        _delete(incident)


def test_a_low_severity_incident_shows_no_clock(login_as, live_app):
    incident = _insert("Printer queue stuck on floor 2", "low", None)
    try:
        page = login_as("super_admin")
        page.goto(f"{live_app}/bcm/incidents")
        row = page.locator("tr", has_text="Printer queue stuck on floor 2")
        row.wait_for(timeout=10000)
        assert row.locator("[data-ack]").count() == 0
    finally:
        _delete(incident)


def test_the_clock_badges_and_the_console_line_have_no_contrast_or_name_violations(login_as, live_app, run_axe):
    ids = [_insert("Clock state: awaiting", "high", _stamp(20)),
           _insert("Clock state: overdue", "critical", _stamp(-1)),
           _insert("Clock state: escalated", "critical", _stamp(-20), escalated=_stamp(-5))]
    try:
        page = login_as("super_admin")
        page.goto(f"{live_app}/bcm/incidents")
        page.wait_for_selector("[data-ack=escalated]", timeout=10000)
        page.get_by_text("Clock state: escalated").first.click()
        page.wait_for_selector("#bcmAckLine", timeout=8000)
        violations = run_axe()
        ours = [v["id"] for v in violations for n in v["nodes"] if "data-ack" in n["html"] or "bcmAck" in n["html"]]
        assert not ours, f"violations on the acknowledgement markup: {ours}"
    finally:
        for incident in ids:
            _delete(incident)
