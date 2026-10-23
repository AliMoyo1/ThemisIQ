"""
Scenario Studio HTTP layer (plans/2026-10-scenario-studio/plan.md): who may call the new routes, that the literal paths
are not shadowed by the parameterized ones, and that nothing outside the caller's reach is exposed.
"""
import httpx

import database


def _login(base_url, username, password):
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=15)
    csrf = client.get("/login").cookies.get("csrf_token")
    resp = client.post("/login", data={"username": username, "password": password, "csrf_token": csrf})
    assert resp.status_code in (302, 303) and resp.headers.get("location") != "/login"
    return client


def _as(live_app, tenant, persona):
    creds = tenant["users"][persona]
    return _login(live_app, creds["username"], creds["password"])


def _scenario(client, title="Studio route scenario"):
    resp = client.post("/erm/api/scenarios", json={"title": title, "scenario_type": "Cyber attack", "review_date": "2027-06-30"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_literal_paths_are_not_shadowed_by_the_scenario_id_route(live_app, synthetic_tenant):
    client = _as(live_app, synthetic_tenant, "risk_owner")
    try:
        templates = client.get("/erm/api/scenario-templates")
        assert templates.status_code == 200 and len(templates.json()["templates"]) == 8 and "Cyber attack" in templates.json()["types"]
        assert client.get("/erm/api/scenarios/candidates?type=risk").status_code == 200
        assert client.get("/erm/api/scenarios/candidates?type=vendor").status_code == 400
        assert client.get("/erm/api/scenarios/seed?module=aria&type=control&id=1").status_code == 404
        assert client.get("/erm/api/scenarios/seed?module=bcm&type=incident&id=abc").status_code == 400
    finally:
        client.close()


def test_a_new_scenario_keeps_type_and_review_date_and_the_impact_carries_a_headline(live_app, synthetic_tenant):
    client = _as(live_app, synthetic_tenant, "risk_owner")
    try:
        sid = _scenario(client)
        detail = client.get(f"/erm/api/scenarios/{sid}").json()
        assert (detail["scenario_type"], detail["review_date"]) == ("Cyber attack", "2027-06-30")
        impact = client.get(f"/erm/api/scenarios/{sid}/impact").json()
        assert impact["headline"]["risks"] == 0 and "Add at least one risk" in impact["headline"]["sentence"]
        assert client.get(f"/erm/api/scenarios/{sid}/context").json()["orm_events"]["count"] == 0
        assert client.post("/erm/api/scenarios", json={"title": "t", "review_date": "soon"}).status_code == 400
    finally:
        client.close()


def test_an_action_creates_a_task_and_a_view_only_role_cannot(live_app, synthetic_tenant):
    owner = _as(live_app, synthetic_tenant, "risk_owner")
    viewer = _as(live_app, synthetic_tenant, "dpo")
    try:
        sid = _scenario(owner)
        made = owner.post(f"/erm/api/scenarios/{sid}/actions", json={"title": "Add a standby supplier", "priority": "high"})
        assert made.status_code == 201, made.text
        db = database.get_db()
        try:
            row = db.execute("SELECT module, entity_type, entity_id FROM task_board WHERE id=%s", (made.json()["task_id"],)).fetchone()
        finally:
            db.close()
        assert tuple(row) == ("erm", "scenario", sid)
        assert owner.post(f"/erm/api/scenarios/{sid}/actions", json={"title": ""}).status_code == 400
        assert viewer.post(f"/erm/api/scenarios/{sid}/actions", json={"title": "x"}).status_code == 403
        assert viewer.get("/erm/api/scenarios/candidates?type=risk").status_code == 200
    finally:
        owner.close()
        viewer.close()


def test_rehearsing_in_bcm_needs_the_bcm_right(live_app, synthetic_tenant):
    client = _as(live_app, synthetic_tenant, "risk_owner")
    try:
        sid = _scenario(client)
        assert client.post(f"/erm/api/scenarios/{sid}/rehearse").status_code == 403
        assert client.post("/erm/api/scenarios/999999/rehearse").status_code == 404
    finally:
        client.close()


def test_ai_routes_refuse_politely_when_the_assistant_is_off_and_check_the_scenario_first(live_app, synthetic_tenant):
    client = _as(live_app, synthetic_tenant, "risk_owner")
    viewer = _as(live_app, synthetic_tenant, "dpo")
    try:
        sid = _scenario(client)
        off = client.post("/erm/api/scenarios/ai/draft", json={"sentence": "our main payment processor is down for five days"})
        assert off.status_code in (503, 403) and off.json().get("ai_unavailable") is True
        assert client.post("/erm/api/scenarios/ai/draft", json={"sentence": "mail jane@example.com"}).status_code == 400
        assert client.post(f"/erm/api/scenarios/{sid}/ai/nonsense").status_code == 404
        assert client.post("/erm/api/scenarios/999999/ai/explain").status_code == 404
        assert viewer.post(f"/erm/api/scenarios/{sid}/ai/explain").status_code == 403
        assert viewer.post("/erm/api/scenarios/ai/draft", json={"sentence": "our main payment processor is down"}).status_code == 403
    finally:
        client.close()
        viewer.close()


def test_the_studio_page_tells_the_browser_what_the_person_may_do(live_app, synthetic_tenant):
    client = _as(live_app, synthetic_tenant, "risk_owner")
    viewer = _as(live_app, synthetic_tenant, "dpo")
    try:
        mine = client.get("/erm/scenario-studio").text
        assert "var CAN_MANAGE = true" in mine and 'id="ssNewScenarioBtn"' in mine
        theirs = viewer.get("/erm/scenario-studio").text
        assert "var CAN_MANAGE = false" in theirs and 'id="ssNewScenarioBtn"' not in theirs
        assert "/erm/obligations" in theirs and "/erm/indicators" in theirs
    finally:
        client.close()
        viewer.close()
