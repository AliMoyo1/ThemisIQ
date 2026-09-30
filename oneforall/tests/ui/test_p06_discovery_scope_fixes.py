"""
PLAN-36 P06 discovery found four real, pre-existing authorization gaps
while researching bulk-action patterns (none of these are P06 features
themselves -- they were found by reading the code, not designed):

1. ERM PUT/DELETE /api/risks/{id} never checked business_unit_id scope
   (unlike its own GET .../{id} sibling) -- a holder of the broad
   erm.risk.manage capability could mutate/delete a risk entirely outside
   their own BU.
2. ORM PUT/DELETE /api/events/{id} had the identical gap.
3. GRID PUT /api/evidence/bulk-approve trusted the posted id list outright
   with zero ownership/BU check at all.
4. Launcher GET /api/tasks (Task Board) had no business-unit scoping
   despite task_board.business_unit_id existing -- any authenticated user
   saw every BU's tasks within their org.

Each is tested here the same way: seed a row in a BU the acting persona is
NOT part of, confirm the fixed endpoint refuses/excludes it.
"""
import httpx

import database


def _login(base_url: str, username: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10)
    get_resp = client.get("/login")
    csrf = get_resp.cookies.get("csrf_token")
    resp = client.post("/login", data={
        "username": username, "password": password, "csrf_token": csrf,
    })
    assert resp.status_code in (302, 303), f"login POST did not redirect: {resp.status_code}"
    assert resp.headers.get("location") != "/login", "login rejected the credentials"
    return client


def _other_bu(db) -> int:
    db.execute("INSERT INTO business_units (name, is_active) VALUES ('P06 Discovery Other BU', 1)")
    return db.execute("SELECT id FROM business_units WHERE name='P06 Discovery Other BU'").fetchone()["id"]


def test_risk_owner_cannot_update_a_risk_outside_their_bu(live_app, synthetic_tenant):
    db = database.get_db()
    try:
        other_bu = _other_bu(db)
        db.execute(
            "INSERT INTO erm_enterprise_risks (title, status, business_unit_id) "
            "VALUES ('Other BU risk', 'open', %s)", (other_bu,),
        )
        db.commit()
        risk_id = db.execute("SELECT id FROM erm_enterprise_risks WHERE title='Other BU risk'").fetchone()["id"]
    finally:
        db.close()

    creds = synthetic_tenant["users"]["risk_owner"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        update_resp = client.put(f"/erm/api/risks/{risk_id}", json={"title": "Hijacked"})
        assert update_resp.status_code == 404

        delete_resp = client.delete(f"/erm/api/risks/{risk_id}")
        assert delete_resp.status_code == 404
    finally:
        client.close()

    db = database.get_db()
    try:
        row = db.execute("SELECT title FROM erm_enterprise_risks WHERE id=%s", (risk_id,)).fetchone()
        assert row["title"] == "Other BU risk"  # untouched
    finally:
        db.close()


def test_risk_owner_cannot_update_an_event_outside_their_bu(live_app, synthetic_tenant):
    db = database.get_db()
    try:
        other_bu = _other_bu(db)
        db.execute(
            "INSERT INTO orm_events (title, event_type, severity, business_unit_id) "
            "VALUES ('Other BU event', 'operational', 'medium', %s)", (other_bu,),
        )
        db.commit()
        event_id = db.execute("SELECT id FROM orm_events WHERE title='Other BU event'").fetchone()["id"]
    finally:
        db.close()

    creds = synthetic_tenant["users"]["risk_owner"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        update_resp = client.put(f"/orm/api/events/{event_id}", json={"title": "Hijacked"})
        assert update_resp.status_code == 404

        delete_resp = client.delete(f"/orm/api/events/{event_id}")
        assert delete_resp.status_code == 404
    finally:
        client.close()

    db = database.get_db()
    try:
        row = db.execute("SELECT title FROM orm_events WHERE id=%s", (event_id,)).fetchone()
        assert row["title"] == "Other BU event"  # untouched
    finally:
        db.close()


def test_bulk_approve_evidence_excludes_a_file_outside_the_actors_bu(live_app, synthetic_tenant):
    db = database.get_db()
    try:
        other_bu = _other_bu(db)
        db.execute("INSERT INTO grid_audits (name, business_unit_id) VALUES ('Other BU Audit', %s)", (other_bu,))
        audit_id = db.execute("SELECT id FROM grid_audits WHERE name='Other BU Audit'").fetchone()["id"]
        db.execute("INSERT INTO grid_controls (audit_id, name) VALUES (%s, 'Other BU Control')", (audit_id,))
        control_id = db.execute("SELECT id FROM grid_controls WHERE name='Other BU Control'").fetchone()["id"]
        db.execute(
            "INSERT INTO grid_evidence_files (control_id, filename, original_name, file_path, status) "
            "VALUES (%s, 'f.pdf', 'f.pdf', 'x', 'Uploaded')", (control_id,),
        )
        db.commit()
        file_id = db.execute("SELECT id FROM grid_evidence_files WHERE control_id=%s", (control_id,)).fetchone()["id"]
    finally:
        db.close()

    creds = synthetic_tenant["users"]["audit_lead"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.put("/grid/api/evidence/bulk-approve", json={"ids": [file_id], "status": "Approved"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0  # excluded, not applied
    finally:
        client.close()

    db = database.get_db()
    try:
        row = db.execute("SELECT status FROM grid_evidence_files WHERE id=%s", (file_id,)).fetchone()
        assert row["status"] == "Uploaded"  # untouched
    finally:
        db.close()


def test_task_board_list_excludes_tasks_from_another_bu(live_app, synthetic_tenant):
    db = database.get_db()
    try:
        other_bu = _other_bu(db)
        db.execute(
            "INSERT INTO task_board (title, status, business_unit_id) VALUES ('Other BU task', 'todo', %s)",
            (other_bu,),
        )
        db.commit()
    finally:
        db.close()

    creds = synthetic_tenant["users"]["employee"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        titles = [t["title"] for t in resp.json()]
        assert "Other BU task" not in titles
    finally:
        client.close()
