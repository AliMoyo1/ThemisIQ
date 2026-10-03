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


def test_compare_route_returns_own_version_and_hides_other_org(live_app, synthetic_tenant):
    import database

    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO organizations (name,slug) VALUES ('Other Compare Org','other-compare-org')"
        )
        other_org = db.execute(
            "SELECT id FROM organizations WHERE slug='other-compare-org'"
        ).fetchone()["id"]
        version_ids = {}
        for label, org_id in (("OWN-COMPARE", synthetic_tenant["org_id"]),
                              ("OTHER-COMPARE", other_org)):
            db.execute(
                "INSERT INTO aria_documents "
                "(doc_id,framework,title,org_id,policy_workflow_managed) "
                "VALUES (%s,'Test','Comparison policy',%s,1)",
                (label, org_id),
            )
            doc_pk = db.execute(
                "SELECT id FROM aria_documents WHERE doc_id=%s", (label,)
            ).fetchone()["id"]
            db.execute(
                "INSERT INTO aria_policy_versions "
                "(org_id,document_id,version_major,version_minor,version,state,origin,body) "
                "VALUES (%s,%s,1,0,'1.0','approved','authored','Policy body')",
                (org_id, doc_pk),
            )
            version_ids[label] = db.execute(
                "SELECT id FROM aria_policy_versions WHERE document_id=%s", (doc_pk,)
            ).fetchone()["id"]
        db.commit()
    finally:
        db.close()

    creds = synthetic_tenant["users"]["compliance_manager"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        own_id = version_ids["OWN-COMPARE"]
        own = client.get(
            f"/aria/api/documents/OWN-COMPARE/compare?left={own_id}&right={own_id}"
        )
        assert own.status_code == 200
        assert own.json()["left"]["normalized_text"] == "Policy body"
        other_id = version_ids["OTHER-COMPARE"]
        other = client.get(
            f"/aria/api/documents/OTHER-COMPARE/compare?left={other_id}&right={other_id}"
        )
        assert other.status_code == 404
    finally:
        client.close()
