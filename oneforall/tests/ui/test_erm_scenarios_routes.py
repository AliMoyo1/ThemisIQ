"""
PLAN-36 P07: HTTP-level coverage for ERM scenario analysis and board-pack
routes (modules/erm/routes_scenarios.py). Service-level logic (calculation
reproducibility, tier selection, hash chaining, citation validation) is
already covered by tests/test_erm_scenarios.py; this file exercises the real
HTTP/capability/session layer those unit tests cannot reach: auth gating,
RBAC capability enforcement per persona, and the real route-registration
order (the literal /api/board-packs/verify-chain route must not be shadowed
by the parameterized /api/board-packs/{pack_id} route -- the exact class of
bug P06 found and fixed in modules/evidence/routes.py).
"""
import httpx

import database


def _login(base_url: str, username: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10)
    get_resp = client.get("/login")
    csrf = get_resp.cookies.get("csrf_token")
    resp = client.post("/login", data={"username": username, "password": password, "csrf_token": csrf})
    assert resp.status_code in (302, 303), f"login POST did not redirect: {resp.status_code}"
    assert resp.headers.get("location") != "/login", "login rejected the credentials"
    return client


def test_unauthenticated_requests_are_redirected(live_app):
    client = httpx.Client(base_url=live_app, follow_redirects=False, timeout=10)
    try:
        page_resp = client.get("/erm/scenario-studio")
        assert page_resp.status_code in (302, 303)
        api_resp = client.get("/erm/api/scenarios")
        assert api_resp.status_code in (302, 303, 401)
    finally:
        client.close()


def test_risk_owner_full_scenario_and_board_pack_roundtrip(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["risk_owner"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        create_resp = client.post("/erm/api/scenarios", json={"title": "P07 HTTP roundtrip scenario"})
        assert create_resp.status_code == 201, create_resp.text
        scenario_id = create_resp.json()["id"]

        detail_resp = client.get(f"/erm/api/scenarios/{scenario_id}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["links"] == []

        impact_resp = client.get(f"/erm/api/scenarios/{scenario_id}/impact")
        assert impact_resp.status_code == 200
        assert impact_resp.json()["per_risk"] == []

        pack_resp = client.post("/erm/api/board-packs", json={"scenario_id": scenario_id})
        assert pack_resp.status_code == 201, pack_resp.text
        pack_id = pack_resp.json()["id"]

        narrative_resp = client.put(f"/erm/api/board-packs/{pack_id}/narrative", json={
            "narrative": "HTTP roundtrip narrative.", "citations": [], "source": "human",
        })
        assert narrative_resp.status_code == 200

        publish_resp = client.post(f"/erm/api/board-packs/{pack_id}/publish")
        assert publish_resp.status_code == 200

        final = client.get(f"/erm/api/board-packs/{pack_id}")
        assert final.status_code == 200
        body = final.json()
        assert body["status"] == "published"
        assert body["narrative"] == "HTTP roundtrip narrative."
    finally:
        client.close()


def test_compliance_manager_can_view_but_not_manage(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["compliance_manager"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        list_resp = client.get("/erm/api/scenarios")
        assert list_resp.status_code == 200

        create_resp = client.post("/erm/api/scenarios", json={"title": "Should be forbidden"})
        assert create_resp.status_code == 403
    finally:
        client.close()


def test_cross_bu_link_rejected_over_http(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["risk_owner"]
    own_bu = synthetic_tenant["business_unit_id"]

    db = database.get_db()
    try:
        db.execute("INSERT INTO business_units (name, is_active) VALUES ('P07 Other BU', 1)")
        db.commit()
        other_bu = db.execute("SELECT id FROM business_units WHERE name='P07 Other BU'").fetchone()["id"]
        db.execute(
            "INSERT INTO erm_enterprise_risks (title, status, business_unit_id) "
            "VALUES ('P07 other BU risk', 'open', %s)", (other_bu,),
        )
        db.commit()
        risk_id = db.execute("SELECT id FROM erm_enterprise_risks WHERE title='P07 other BU risk'").fetchone()["id"]
    finally:
        db.close()

    client = _login(live_app, creds["username"], creds["password"])
    try:
        create_resp = client.post("/erm/api/scenarios", json={"title": "BU-scoped scenario", "business_unit_id": own_bu})
        assert create_resp.status_code == 201, create_resp.text
        scenario_id = create_resp.json()["id"]

        link_resp = client.post(f"/erm/api/scenarios/{scenario_id}/links", json={"link_type": "risk", "link_id": risk_id})
        assert link_resp.status_code == 403

        detail_resp = client.get(f"/erm/api/scenarios/{scenario_id}")
        assert detail_resp.json()["links"] == []
    finally:
        client.close()


def test_verify_chain_literal_route_not_shadowed_by_pack_id_route(live_app, synthetic_tenant):
    """Regression proof for the route-ordering class of bug P06 found: if
    GET /api/board-packs/{pack_id} were registered before the literal
    /api/board-packs/verify-chain, Starlette's int() conversion on the
    literal segment "verify-chain" would 422 before this route ever ran."""
    creds = synthetic_tenant["users"]["risk_owner"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.get("/erm/api/board-packs/verify-chain")
        assert resp.status_code == 200
        assert "problems" in resp.json()
    finally:
        client.close()
