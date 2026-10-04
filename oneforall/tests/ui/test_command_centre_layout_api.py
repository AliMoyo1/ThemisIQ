"""The saved Command Centre layout belongs to one authenticated user."""
import httpx


def _login(base_url, credentials):
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10)
    csrf = client.get("/login").cookies.get("csrf_token")
    response = client.post("/login", data={
        "username": credentials["username"], "password": credentials["password"],
        "csrf_token": csrf,
    })
    assert response.status_code in (302, 303)
    return client


def test_command_centre_layout_is_user_scoped_and_validated(live_app, synthetic_tenant):
    admin = _login(live_app, synthetic_tenant["users"]["super_admin"])
    employee = _login(live_app, synthetic_tenant["users"]["employee"])
    original = admin.get("/api/command-centre/layout").json()["layout"]
    try:
        # Match the app's origin guard for authenticated JSON mutations.
        saved = admin.put("/api/command-centre/layout", json={
            "layout": {"order": ["modules", "compliance"], "hidden": ["modules"]}
        }, headers={"Origin": live_app})
        assert saved.status_code == 200, saved.text
        assert admin.get("/api/command-centre/layout").json()["layout"]["hidden"] == ["modules"]
        assert employee.get("/api/command-centre/layout").json()["layout"] is None
        malformed = admin.put("/api/command-centre/layout", json={
            "layout": {"order": [["nested"]], "hidden": []}
        }, headers={"Origin": live_app})
        assert malformed.status_code == 400
        assert admin.get("/api/command-centre/layout").json()["layout"]["hidden"] == ["modules"]
    finally:
        admin.put("/api/command-centre/layout", json={"layout": original}, headers={"Origin": live_app})
        admin.close()
        employee.close()
