"""
PLAN-36 P09: GET /api/capability-state/ai (modules/launcher/routes_capability_state.py).
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
    resp = client.get("/api/capability-state/ai")
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert "/login" in resp.headers.get("location", "")


def test_authenticated_request_returns_a_valid_capability_state_shape(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["employee"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/api/capability-state/ai")
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] in (
            "available", "disabled_by_policy", "not_configured",
            "degraded", "forbidden", "unavailable_in_tier",
        )
        assert "reason_code" in body
        assert "message" in body
        assert "retryable" in body
    finally:
        client.close()
