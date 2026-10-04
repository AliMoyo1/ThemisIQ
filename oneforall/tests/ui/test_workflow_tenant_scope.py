"""HTTP and browser coverage for tenant-scoped workflow records and links."""
import json

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


def test_workflow_routes_reject_other_organization(live_app, synthetic_tenant):
    own_user = synthetic_tenant["users"]["org_admin"]["user_id"]
    db = database.get_db()
    try:
        db.execute("INSERT INTO organizations (name, slug) VALUES ('Workflow Other Org', 'workflow-other-org')")
        other_org = db.execute("SELECT id FROM organizations WHERE slug='workflow-other-org'").fetchone()["id"]
        db.execute(
            "INSERT INTO users (username,email,full_name,password_hash,org_id) "
            "VALUES ('workflow_other','workflow_other@example.test','Other Workflow User','synthetic',%s)",
            (other_org,),
        )
        other_user = db.execute("SELECT id FROM users WHERE username='workflow_other'").fetchone()["id"]
        db.execute(
            "INSERT INTO user_roles (user_id,role_key) VALUES (%s,'compliance_mgr')",
            (other_user,),
        )
        steps = json.dumps([{"name": "Review", "role": "compliance_mgr", "type": "approval"}])
        db.execute(
            "INSERT INTO workflow_definitions (name,steps_json,created_by) VALUES ('Own flow',%s,%s)",
            (steps, own_user),
        )
        own_def = db.execute("SELECT id FROM workflow_definitions WHERE name='Own flow'").fetchone()["id"]
        db.execute(
            "INSERT INTO workflow_definitions (name,steps_json,created_by) VALUES ('Private other flow',%s,%s)",
            (steps, other_user),
        )
        other_def = db.execute("SELECT id FROM workflow_definitions WHERE name='Private other flow'").fetchone()["id"]
        db.execute(
            "INSERT INTO workflow_instances (definition_id,started_by) VALUES (%s,%s)",
            (other_def, other_user),
        )
        other_inst = db.execute("SELECT id FROM workflow_instances WHERE definition_id=%s", (other_def,)).fetchone()["id"]
        db.execute(
            "INSERT INTO workflow_actions (instance_id,step_index) VALUES (%s,0)",
            (other_inst,),
        )
        other_action = db.execute(
            "SELECT id FROM workflow_actions WHERE instance_id=%s", (other_inst,)
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO workflow_instances (definition_id,started_by) VALUES (%s,%s)",
            (own_def, own_user),
        )
        own_inst = db.execute("SELECT id FROM workflow_instances WHERE definition_id=%s", (own_def,)).fetchone()["id"]
        db.execute(
            "INSERT INTO workflow_actions (instance_id,step_index,assigned_to) VALUES (%s,0,%s)",
            (own_inst, own_user),
        )
        own_action = db.execute(
            "SELECT id FROM workflow_actions WHERE instance_id=%s", (own_inst,)
        ).fetchone()["id"]
        db.commit()
    finally:
        db.close()

    client = _login(live_app, synthetic_tenant["users"]["org_admin"])
    try:
        definitions = client.get("/api/workflows/definitions")
        assert definitions.status_code == 200
        assert other_def not in [row["id"] for row in definitions.json()]
        instances = client.get("/api/workflows/instances")
        assert instances.status_code == 200
        assert other_inst not in [row["id"] for row in instances.json()]
        assert client.get(f"/api/workflows/instances/{other_inst}").status_code == 404
        assert client.put(f"/api/workflows/definitions/{other_def}", json={"name": "Hijacked"}).status_code == 404
        assert client.delete(f"/api/workflows/definitions/{other_def}").status_code in (403, 404)
        assert client.post("/api/workflows/instances", json={"definition_id": other_def}).status_code == 404
        assert client.post(f"/api/workflows/actions/{other_action}/decide", json={"decision": "approve"}).status_code == 404
        assert client.post(f"/api/workflows/actions/{other_action}/delegate", json={"user_id": own_user}).status_code == 404
        assert client.post(f"/api/workflows/actions/{own_action}/delegate", json={"user_id": other_user}).status_code == 404
        assert client.post(f"/api/workflows/actions/{own_action}/delegate", json={"user_id": "bad"}).status_code == 400
        assert client.post(
            f"/api/workflows/actions/{own_action}/decide",
            json={"decision": "return", "return_to_step": "bad"},
        ).status_code == 400
        assert client.get(f"/api/workflows/instances/{own_inst}").status_code == 200
        started = client.post("/api/workflows/instances", json={"definition_id": own_def})
        assert started.status_code == 201
        new_inst = started.json()["id"]
        assert client.get(f"/api/workflows/instances/{new_inst}").status_code == 200
        assert client.post(f"/api/workflows/actions/{own_action}/decide", json={"decision": "approve"}).status_code == 200
    finally:
        client.close()

    super_client = _login(live_app, synthetic_tenant["users"]["super_admin"])
    try:
        assert super_client.post(
            "/api/workflows/instances", json={"definition_id": own_def}
        ).status_code == 400
        assert super_client.post(
            "/api/workflows/instances",
            json={"definition_id": other_def, "org_id": synthetic_tenant["org_id"]},
        ).status_code == 404
        created = super_client.post(
            "/api/workflows/instances",
            json={"definition_id": own_def, "org_id": synthetic_tenant["org_id"]},
        )
        assert created.status_code == 201
        super_inst = created.json()["id"]
    finally:
        super_client.close()

    db = database.get_db()
    try:
        assert db.execute("SELECT org_id FROM workflow_instances WHERE id=%s", (super_inst,)).fetchone()["org_id"] == synthetic_tenant["org_id"]
        assert db.execute("SELECT name FROM workflow_definitions WHERE id=%s", (other_def,)).fetchone()["name"] == "Private other flow"
        assert db.execute("SELECT status FROM workflow_actions WHERE id=%s", (other_action,)).fetchone()["status"] == "pending"
        assert db.execute("SELECT assigned_to FROM workflow_actions WHERE id=%s", (own_action,)).fetchone()["assigned_to"] == own_user
        assert not db.execute(
            "SELECT 1 FROM workflow_actions WHERE instance_id=%s AND assigned_to=%s",
            (new_inst, other_user),
        ).fetchone()
        assert not db.execute(
            "SELECT 1 FROM notifications WHERE user_id=%s AND link=%s",
            (other_user, f"/workflows?instance={new_inst}"),
        ).fetchone()
    finally:
        db.close()


def test_my_work_workflow_link_opens_instance(login_as, live_app, synthetic_tenant):
    user = synthetic_tenant["users"]["compliance_manager"]
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO workflow_definitions (name,steps_json,created_by) "
            "VALUES ('Deep linked workflow',%s,%s)",
            (json.dumps([{"name": "Review", "role": "compliance_mgr"}]), user["user_id"]),
        )
        definition_id = db.execute(
            "SELECT id FROM workflow_definitions WHERE name='Deep linked workflow'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO workflow_instances (definition_id,started_by) VALUES (%s,%s)",
            (definition_id, user["user_id"]),
        )
        instance_id = db.execute(
            "SELECT id FROM workflow_instances WHERE definition_id=%s", (definition_id,)
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO workflow_actions (instance_id,step_index,assigned_to) VALUES (%s,0,%s)",
            (instance_id, user["user_id"]),
        )
        db.commit()
    finally:
        db.close()

    client = _login(live_app, user)
    try:
        result = client.get("/api/my-work")
        assert result.status_code == 200
        items = [item for section in result.json()["sections"].values() for item in section]
        workflow = next(item for item in items if item["entity_type"] == "workflow_action"
                        and item["title"] == "Workflow decision: Deep linked workflow")
        assert workflow["link"] == f"/workflows?instance={instance_id}"
    finally:
        client.close()

    page = login_as("compliance_manager")
    page.goto(f"{live_app}/workflows?instance={instance_id}")
    page.locator("#wfDrawerRoot .drawer").wait_for(timeout=10000)
    page.wait_for_function("() => document.querySelector('#wfDrawerRoot .drawer-header span')?.textContent === 'Deep linked workflow'", timeout=10000)
    assert page.locator("#wfDrawerRoot .drawer-header span").inner_text() == "Deep linked workflow"
    assert "instance=" not in page.url


def test_workflow_definition_and_start_reject_invalid_steps(live_app, synthetic_tenant):
    user = synthetic_tenant["users"]["org_admin"]
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO workflow_definitions (name,steps_json,created_by) "
            "VALUES ('Legacy corrupt steps','not-json',%s)", (user["user_id"],)
        )
        corrupt_id = db.execute(
            "SELECT id FROM workflow_definitions WHERE name='Legacy corrupt steps'"
        ).fetchone()["id"]
        db.commit()
    finally:
        db.close()

    client = _login(live_app, user)
    try:
        assert client.post(
            "/api/workflows/definitions", json={"name": "Invalid", "steps": "wrong"}
        ).status_code == 400
        created = client.post(
            "/api/workflows/definitions", json={
                "name": "Valid workflow", "steps": [{"name": "Review", "role": "org_admin"}]
            }
        )
        assert created.status_code == 201
        definition_id = created.json()["id"]
        assert client.put(
            f"/api/workflows/definitions/{definition_id}", json={"steps": ["wrong"]}
        ).status_code == 400
        assert client.post(
            "/api/workflows/instances", json={"definition_id": corrupt_id}
        ).status_code == 422
    finally:
        client.close()

    db = database.get_db()
    try:
        assert not db.execute(
            "SELECT 1 FROM workflow_instances WHERE definition_id=%s", (corrupt_id,)
        ).fetchone()
        steps = db.execute(
            "SELECT steps_json FROM workflow_definitions WHERE id=%s", (definition_id,)
        ).fetchone()["steps_json"]
        assert isinstance(json.loads(steps), list)
    finally:
        db.close()


def test_next_step_failure_rolls_back_workflow_decision(
    live_app, synthetic_tenant, monkeypatch
):
    from core.rbac import ORG_ADMIN
    from modules.launcher import routes_workflows

    user = synthetic_tenant["users"]["org_admin"]
    client = _login(live_app, user)
    try:
        definition = client.post("/api/workflows/definitions", json={
            "name": "Rollback workflow",
            "steps": [
                {"name": "First", "role": ORG_ADMIN},
                {"name": "Second", "role": "compliance_mgr"},
            ],
        })
        assert definition.status_code == 201
        started = client.post(
            "/api/workflows/instances",
            json={"definition_id": definition.json()["id"]},
        )
        assert started.status_code == 201
        instance_id = started.json()["id"]
        db = database.get_db()
        try:
            action_id = db.execute(
                "SELECT id FROM workflow_actions "
                "WHERE instance_id=%s AND step_index=0 AND assigned_to=%s",
                (instance_id, user["user_id"]),
            ).fetchone()["id"]
        finally:
            db.close()

        def fail_next_step(*args, **kwargs):
            raise RuntimeError("synthetic next-step insert failure")

        with monkeypatch.context() as patch:
            patch.setattr(routes_workflows, "_create_step_action", fail_next_step)
            response = client.post(
                f"/api/workflows/actions/{action_id}/decide",
                json={"decision": "approve"},
            )
        assert response.status_code == 500
    finally:
        client.close()

    db = database.get_db()
    try:
        assert db.execute(
            "SELECT status FROM workflow_actions WHERE id=%s", (action_id,)
        ).fetchone()["status"] == "pending"
        assert db.execute(
            "SELECT current_step FROM workflow_instances WHERE id=%s", (instance_id,)
        ).fetchone()["current_step"] == 0
        assert not db.execute(
            "SELECT 1 FROM workflow_actions WHERE instance_id=%s AND step_index=1",
            (instance_id,),
        ).fetchone()
    finally:
        db.close()
