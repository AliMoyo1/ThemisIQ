"""SLA and communication-template organization isolation over real HTTP."""

import httpx

import database


def _login(base_url, credentials):
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10)
    csrf = client.get("/login").cookies.get("csrf_token")
    response = client.post("/login", data={
        "username": credentials["username"], "password": credentials["password"],
        "csrf_token": csrf,
    })
    assert response.status_code in (302, 303)
    return client


def test_communication_template_stays_with_creator_organization(
    live_app, synthetic_tenant
):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO organizations (name,slug) "
            "VALUES ('Comm Other Org','comm-other-org')"
        )
        org_id = db.execute(
            "SELECT id FROM organizations WHERE slug='comm-other-org'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO users (username,email,full_name,password_hash,org_id) "
            "VALUES ('comm_other','comm_other@example.test','Comm Other','synthetic',%s)",
            (org_id,),
        )
        creator = db.execute(
            "SELECT id FROM users WHERE username='comm_other'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO comm_templates "
            "(name,body_template,created_by) VALUES ('Private notice','B secret',%s)",
            (creator,),
        )
        template_id = db.execute(
            "SELECT id FROM comm_templates WHERE name='Private notice'"
        ).fetchone()["id"]
        db.commit()
    finally:
        db.close()

    client = _login(live_app, synthetic_tenant["users"]["org_admin"])
    try:
        templates = client.get("/api/comm-templates")
        assert templates.status_code == 200
        assert template_id not in [row["id"] for row in templates.json()]
        assert client.post(
            f"/api/comm-templates/{template_id}/render", json={"variables": {}}
        ).status_code == 404
        assert client.put(
            f"/api/comm-templates/{template_id}", json={"body_template": "Hijacked"}
        ).status_code == 404
    finally:
        client.close()

    db = database.get_db()
    try:
        assert db.execute(
            "SELECT body_template FROM comm_templates WHERE id=%s", (template_id,)
        ).fetchone()["body_template"] == "B secret"
    finally:
        db.close()


def test_sla_instance_routes_and_counts_are_organization_scoped(
    live_app, synthetic_tenant
):
    own_org = synthetic_tenant["org_id"]
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO organizations (name,slug) "
            "VALUES ('SLA Other Org','sla-other-org')"
        )
        other_org = db.execute(
            "SELECT id FROM organizations WHERE slug='sla-other-org'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO sla_definitions "
            "(name,module,entity_type,response_hours,resolution_hours) "
            "VALUES ('Shared SLA','bcm','incident',4,8)"
        )
        definition_id = db.execute(
            "SELECT id FROM sla_definitions WHERE name='Shared SLA'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO sla_instances "
            "(definition_id,org_id,entity_module,entity_type,entity_id,response_due) "
            "VALUES (%s,%s,'bcm','incident',4002,'2000-01-01 00:00:00')",
            (definition_id, other_org),
        )
        other_id = db.execute(
            "SELECT id FROM sla_instances WHERE entity_id=4002"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO sla_instances "
            "(definition_id,org_id,entity_module,entity_type,entity_id,response_due) "
            "VALUES (%s,%s,'bcm','incident',4001,'2999-01-01 00:00:00')",
            (definition_id, own_org),
        )
        own_id = db.execute(
            "SELECT id FROM sla_instances WHERE entity_id=4001"
        ).fetchone()["id"]
        db.commit()
    finally:
        db.close()

    client = _login(live_app, synthetic_tenant["users"]["org_admin"])
    try:
        instances = client.get("/api/sla/instances")
        assert instances.status_code == 200
        assert [row["id"] for row in instances.json()] == [own_id]
        stats = client.get("/api/sla/stats")
        assert stats.status_code == 200
        assert stats.json()["total"] == 1
        assert client.post(f"/api/sla/instances/{other_id}/respond").status_code == 404
        assert client.post(f"/api/sla/instances/{other_id}/resolve").status_code == 404
        assert client.post(f"/api/sla/instances/{other_id}/escalate").status_code == 404
        checked = client.post("/api/sla/check-breaches")
        assert checked.status_code == 200
        assert checked.json()["response_breaches"] == 0
        created = client.post("/api/sla/instances", json={
            "definition_id": definition_id, "entity_module": "bcm",
            "entity_type": "incident", "entity_id": 4100, "org_id": other_org,
        })
        assert created.status_code == 201
        new_id = created.json()["id"]
        assert client.post(f"/api/sla/instances/{own_id}/respond").status_code == 200
    finally:
        client.close()

    super_client = _login(live_app, synthetic_tenant["users"]["super_admin"])
    try:
        payload = {
            "definition_id": definition_id, "entity_module": "bcm",
            "entity_type": "incident", "entity_id": 4200,
        }
        assert super_client.post("/api/sla/instances", json=payload).status_code == 400
        assert super_client.post(
            "/api/sla/instances", json={**payload, "org_id": 999999}
        ).status_code == 404
        super_created = super_client.post(
            "/api/sla/instances", json={**payload, "org_id": own_org}
        )
        assert super_created.status_code == 201
    finally:
        super_client.close()

    db = database.get_db()
    try:
        assert db.execute(
            "SELECT org_id FROM sla_instances WHERE id=%s",
            (super_created.json()["id"],),
        ).fetchone()["org_id"] == own_org
        assert db.execute(
            "SELECT breached,responded_at FROM sla_instances WHERE id=%s", (other_id,)
        ).fetchone()["breached"] == 0
        assert db.execute(
            "SELECT responded_at FROM sla_instances WHERE id=%s", (other_id,)
        ).fetchone()["responded_at"] is None
        assert db.execute(
            "SELECT org_id FROM sla_instances WHERE id=%s", (new_id,)
        ).fetchone()["org_id"] == own_org
    finally:
        db.close()


def test_super_admin_modals_choose_target_organization(
    login_as, live_app, synthetic_tenant
):
    org_id = synthetic_tenant["org_id"]
    creator_id = synthetic_tenant["users"]["org_admin"]["user_id"]
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO workflow_definitions (name,steps_json,created_by) "
            "VALUES ('Modal tenant flow','[]',%s)",
            (creator_id,),
        )
        workflow_id = db.execute(
            "SELECT id FROM workflow_definitions WHERE name='Modal tenant flow'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO sla_definitions (name,module,entity_type) "
            "VALUES ('Modal tenant SLA','bcm','incident')"
        )
        db.commit()
    finally:
        db.close()

    page = login_as("super_admin")
    page.goto(f"{live_app}/workflows")
    page.evaluate(
        "([id, name]) => wfStartInstanceModal(id, name)",
        [workflow_id, "Modal tenant flow"],
    )
    page.locator("#wfTargetOrg").wait_for()
    page.select_option("#wfTargetOrg", str(org_id))
    page.locator("#wfStartDef option", has_text="Modal tenant flow").wait_for(state="attached")
    page.select_option("#wfStartDef", label="Modal tenant flow")
    with page.expect_response(lambda r: "/api/workflows/instances" in r.url and r.request.method == "POST") as start_response:
        page.get_by_role("button", name="Start Flow").click()
    assert start_response.value.status == 201, start_response.value.text()
    page.locator("#wfTargetOrg").wait_for(state="detached")

    page.evaluate("slaOpenStart()")
    page.locator("#slaStartDef").wait_for()
    page.select_option("#wfTargetOrg", str(org_id))
    page.locator("#slaStartDef option", has_text="Modal tenant SLA").wait_for(state="attached")
    page.select_option("#slaStartDef", label="Modal tenant SLA")
    with page.expect_response(lambda r: "/api/sla/instances" in r.url and r.request.method == "POST") as start_response:
        page.get_by_role("button", name="Start Tracking").click()
    assert start_response.value.status == 201, start_response.value.text()
    page.locator("#wfTargetOrg").wait_for(state="detached")

    db = database.get_db()
    try:
        assert db.execute(
            "SELECT org_id FROM workflow_instances WHERE definition_id=%s "
            "ORDER BY id DESC LIMIT 1", (workflow_id,)
        ).fetchone()["org_id"] == org_id
        assert db.execute(
            "SELECT si.org_id FROM sla_instances si "
            "JOIN sla_definitions sd ON sd.id=si.definition_id "
            "WHERE sd.name='Modal tenant SLA' ORDER BY si.id DESC LIMIT 1"
        ).fetchone()["org_id"] == org_id
    finally:
        db.close()
