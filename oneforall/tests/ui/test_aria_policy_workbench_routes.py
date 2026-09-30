"""
PLAN-36 P03: GET /aria/documents/{doc_id}/workbench, GET
/aria/api/documents/{doc_id}/workbench (modules/aria/routes_workbench.py).

Service-level permission logic (can_submit/can_decide/can_withdraw/
can_start_revision, approval visibility) is covered thoroughly, with
red/green proofs, in tests/test_aria_policy_workbench.py -- this file only
checks the route layer: auth, and that a real HTTP request reaches the
service and gets a real 404 (not a 500) for a document that does not exist.
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


def test_unauthenticated_page_request_is_redirected(live_app):
    client = httpx.Client(base_url=live_app, follow_redirects=False, timeout=10)
    resp = client.get("/aria/documents/NO-SUCH-DOC/workbench")
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert "/login" in resp.headers.get("location", "")


def test_unauthenticated_api_request_is_redirected(live_app):
    client = httpx.Client(base_url=live_app, follow_redirects=False, timeout=10)
    resp = client.get("/aria/api/documents/NO-SUCH-DOC/workbench")
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert "/login" in resp.headers.get("location", "")


def test_page_renders_for_a_compliance_manager(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["compliance_manager"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/aria/documents/NO-SUCH-DOC/workbench")
        assert resp.status_code == 200
        assert "Policy Workbench" in resp.text
    finally:
        client.close()


def test_api_returns_404_not_500_for_a_nonexistent_document(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["compliance_manager"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/aria/api/documents/NO-SUCH-DOC/workbench")
        assert resp.status_code == 404
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "NOT_FOUND"
    finally:
        client.close()
