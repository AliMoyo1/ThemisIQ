"""
PLAN-36 P04: GET /readiness, /readiness/api/findings, /readiness/api/scan,
etc. (modules/readiness/routes.py).

Rule-level and reconciliation-level behavior is covered thoroughly, with
red/green proofs, in tests/test_readiness_rules.py and
test_readiness_data_service.py -- this file checks the route layer: auth,
capability gates, and that a real HTTP request reaches the service.
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
    resp = client.get("/readiness/api/findings")
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert "/login" in resp.headers.get("location", "")


def test_employee_is_forbidden(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["employee"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/readiness/api/findings")
        assert resp.status_code == 403
    finally:
        client.close()


def test_compliance_manager_can_list_findings(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["compliance_manager"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/readiness/api/findings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "findings" in body
    finally:
        client.close()


def test_page_renders_for_compliance_manager(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["compliance_manager"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/readiness")
        assert resp.status_code == 200
        assert "Data Readiness" in resp.text
    finally:
        client.close()


def test_scan_reflects_a_real_finding_then_rate_limits_an_immediate_repeat(live_app, synthetic_tenant):
    """One sequential test rather than two independent ones: the rate
    limiter is keyed per-org with a 5-minute window (core/middleware.py's
    check_readiness_scan_rate_limit), and synthetic_tenant's org is shared
    (session-scoped) across every test in this file -- two separate tests
    that each expect a *first* scan to succeed would race each other
    depending on execution order. Combined into one linear sequence:
    trigger a scan, confirm it found the seeded violation, then confirm an
    immediate second attempt is rejected rather than silently re-scanning."""
    import database
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO erm_enterprise_risks (title, status) VALUES ('HTTP-seeded orphan risk', 'open')"
        )
        db.commit()
    finally:
        db.close()

    creds = synthetic_tenant["users"]["compliance_manager"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        scan_resp = client.post("/readiness/api/scan")
        assert scan_resp.status_code == 200
        assert scan_resp.json()["ok"] is True

        list_resp = client.get("/readiness/api/findings")
        assert list_resp.status_code == 200
        findings = list_resp.json()["findings"]
        assert any(f["rule_code"] == "MISSING_RISK_OWNER" for f in findings)

        second_scan = client.post("/readiness/api/scan")
        assert second_scan.status_code == 429
    finally:
        client.close()


def test_employee_cannot_trigger_a_scan(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["employee"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.post("/readiness/api/scan")
        assert resp.status_code == 403
    finally:
        client.close()


def test_export_returns_csv(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["compliance_manager"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/readiness/api/findings/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert resp.text.startswith("rule_code,severity,module,")
    finally:
        client.close()
