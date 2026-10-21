"""
PLAN-36 P05: GET/POST /evidence-campaigns/* (modules/evidence_campaigns/routes.py).

State-machine and self-accept-prevention logic is covered thoroughly, with
a red/green proof, in tests/test_evidence_campaigns.py -- this file checks
the route layer: auth, capability gates, and a full create-submit-review
-decide sequence through the real HTTP layer using two distinct real
personas (compliance_manager as creator/reviewer, employee as assignee --
object-level actions like submit/start-review require no role capability
at all, only that the actor really is that specific request's own
assignee/reviewer).
"""
import httpx


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


def test_unauthenticated_request_is_redirected(live_app):
    client = httpx.Client(base_url=live_app, follow_redirects=False, timeout=10)
    resp = client.get("/evidence-campaigns/api/campaigns")
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert "/login" in resp.headers.get("location", "")


def test_employee_cannot_create_a_campaign(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["employee"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.post("/evidence-campaigns/api/campaigns", json={"name": "Test", "due_date": "2099-01-01"})
        assert resp.status_code == 403
    finally:
        client.close()


def test_page_renders_for_any_authenticated_user(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["employee"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/evidence-campaigns")
        assert resp.status_code == 200
        assert "Evidence Campaigns" in resp.text
    finally:
        client.close()


def test_full_request_lifecycle_through_http(live_app, synthetic_tenant):
    manager_creds = synthetic_tenant["users"]["compliance_manager"]
    employee_creds = synthetic_tenant["users"]["employee"]
    employee_id = synthetic_tenant["users"]["employee"]["user_id"]
    manager_id = synthetic_tenant["users"]["compliance_manager"]["user_id"]

    manager = _login(live_app, manager_creds["username"], manager_creds["password"])
    employee = _login(live_app, employee_creds["username"], employee_creds["password"])
    try:
        create_resp = manager.post("/evidence-campaigns/api/requests", json={
            "title": "HTTP lifecycle test", "assignee_id": employee_id, "reviewer_id": manager_id,
            "due_date": "2099-01-01", "module": "grid", "entity_type": "control", "entity_id": "1",
        })
        assert create_resp.status_code == 201
        request_id = create_resp.json()["request"]["id"]
        lock_version = create_resp.json()["request"]["lock_version"]

        # The employee needs a real evidence item to submit. The real
        # upload endpoint (POST /evidence/api/items) has its own dedicated
        # test coverage for its validation layers (magic bytes, MIME/
        # extension allowlists, duplicate detection) -- exercising all of
        # that here would test evidence upload, not this module's own
        # routes, so seed the row directly instead (matching this
        # session's established pattern for HTTP tests that need data a
        # route doesn't itself expose, e.g. test_org_isolation.py).
        import database
        db = database.get_db()
        try:
            db.execute(
                "INSERT INTO evidence_items (title, org_id, uploaded_by, status) VALUES (%s,%s,%s,'current')",
                ("HTTP test evidence", employee_creds["org_id"], employee_id),
            )
            db.commit()
            evidence_id = db.execute(
                "SELECT id FROM evidence_items WHERE title='HTTP test evidence'"
            ).fetchone()["id"]
        finally:
            db.close()

        submit_resp = employee.post(f"/evidence-campaigns/api/requests/{request_id}/submit", json={
            "evidence_id": evidence_id, "expected_lock_version": lock_version,
        })
        assert submit_resp.status_code == 200, submit_resp.text
        lock_version = submit_resp.json()["request"]["lock_version"]

        # The employee (assignee) must not be able to decide their own submission.
        self_decide = employee.post(f"/evidence-campaigns/api/requests/{request_id}/decide", json={
            "decision": "accept", "expected_lock_version": lock_version,
        })
        assert self_decide.status_code == 403

        start_review_resp = manager.post(f"/evidence-campaigns/api/requests/{request_id}/start-review", json={
            "expected_lock_version": lock_version,
        })
        assert start_review_resp.status_code == 200
        lock_version = start_review_resp.json()["request"]["lock_version"]

        decide_resp = manager.post(f"/evidence-campaigns/api/requests/{request_id}/decide", json={
            "decision": "accept", "expected_lock_version": lock_version,
        })
        assert decide_resp.status_code == 200
        assert decide_resp.json()["request"]["status"] == "accepted"
    finally:
        manager.close()
        employee.close()
