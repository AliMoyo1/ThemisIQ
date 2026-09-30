"""
PLAN-36 P02: GET /admin/diagnostics, GET /api/admin/diagnostics
(modules/launcher/routes_diagnostics.py).

The one security-relevant assertion this whole feature rests on: platform
infrastructure state (scheduler/backup/ARIA-preview-worker) must only ever
be computed for a platform super admin, never handed to an organization
admin -- even though both roles pass the route's capability gate.
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
    resp = client.get("/api/admin/diagnostics")
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert "/login" in resp.headers.get("location", "")


def test_employee_is_forbidden(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["employee"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/api/admin/diagnostics")
        assert resp.status_code == 403
    finally:
        client.close()


def test_org_admin_sees_org_scoped_state_but_no_platform_key(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["org_admin"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/api/admin/diagnostics")
        assert resp.status_code == 200
        body = resp.json()
        assert "database" in body
        assert "ai" in body
        assert "email" in body
        assert "licensed_modules" in body
        assert "platform" not in body, (
            "org_admin must never receive platform-wide infrastructure state"
        )
    finally:
        client.close()


def test_super_admin_sees_platform_key_with_all_three_probes(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["super_admin"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/api/admin/diagnostics")
        assert resp.status_code == 200
        body = resp.json()
        assert "platform" in body
        platform = body["platform"]
        for key in ("scheduler", "backup", "aria_preview_worker"):
            assert key in platform, f"missing platform probe: {key}"
        # backup/aria_preview_worker report the shared CapabilityState shape;
        # scheduler reports its own richer {running, jobs} shape (see
        # diagnostics.html's client-side handling of pf.scheduler).
        assert "state" in platform["backup"]
        assert "state" in platform["aria_preview_worker"]
        assert "running" in platform["scheduler"]
        assert "jobs" in platform["scheduler"]
    finally:
        client.close()


def test_diagnostics_page_renders_for_super_admin(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["super_admin"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/admin/diagnostics")
        assert resp.status_code == 200
        assert "Diagnostics" in resp.text
    finally:
        client.close()
