"""Task Board record links and tenant-safe reads/writes."""
import httpx

import database


def _login(base_url, credentials):
    client = httpx.Client(base_url=base_url, follow_redirects=False, timeout=10)
    csrf = client.get("/login").cookies.get("csrf_token")
    response = client.post("/login", data={
        "username": credentials["username"],
        "password": credentials["password"],
        "csrf_token": csrf,
    })
    assert response.status_code in (302, 303)
    return client


def test_task_detail_and_admin_mutations_reject_other_organization(live_app, synthetic_tenant):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO organizations (name,slug) VALUES ('Other Task Org','other-task-org')"
        )
        org_id = db.execute(
            "SELECT id FROM organizations WHERE slug='other-task-org'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO users (username,email,full_name,password_hash,org_id) "
            "VALUES ('other_task_owner','other_task_owner@example.test','Other Task Owner','synthetic',%s)",
            (org_id,),
        )
        owner_id = db.execute(
            "SELECT id FROM users WHERE username='other_task_owner'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO task_board (title,status,created_by) "
            "VALUES ('Other tenant task','todo',%s)", (owner_id,)
        )
        task_id = db.execute(
            "SELECT id FROM task_board WHERE title='Other tenant task'"
        ).fetchone()["id"]
        db.commit()
    finally:
        db.close()

    client = _login(live_app, synthetic_tenant["users"]["org_admin"])
    try:
        assert client.get(f"/api/tasks/{task_id}").status_code == 404
        visible_tasks = client.get("/api/tasks").json()
        assert all(row["id"] != task_id for row in visible_tasks)
        stats = client.get("/api/tasks/stats")
        assert stats.status_code == 200
        assert sum(stats.json()["by_status"].values()) == len(visible_tasks)
        assert client.put(f"/api/tasks/{task_id}", json={"title": "Hijacked"}).status_code == 403
        assert client.delete(f"/api/tasks/{task_id}").status_code == 404
        # A user must not send task titles or notification text to an
        # assignee in another organization by guessing that user's id.
        response = client.post("/api/tasks", json={
            "title": "Private task title", "assigned_to": owner_id,
        })
        assert response.status_code in (400, 404)
        own = client.post("/api/tasks", json={"title": "Owned task"})
        assert own.status_code == 201
        own_id = own.json()["id"]
        reassignment = client.put(
            f"/api/tasks/{own_id}", json={"assigned_to": owner_id}
        )
        assert reassignment.status_code in (400, 404)
        bulk = client.put(
            "/api/tasks/bulk",
            json={"ids": [own_id], "updates": {"assigned_to": owner_id}},
        )
        assert bulk.status_code in (400, 404)
    finally:
        client.close()
    db = database.get_db()
    try:
        assert db.execute(
            "SELECT title FROM task_board WHERE id=%s", (task_id,)
        ).fetchone()["title"] == "Other tenant task"
    finally:
        db.close()


def test_task_deep_link_opens_scoped_record_drawer(login_as, live_app, synthetic_tenant):
    user = synthetic_tenant["users"]["employee"]
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO task_board (title,status,created_by,assigned_to,business_unit_id) "
            "VALUES ('Deep link target','todo',%s,%s,%s)",
            (user["user_id"], user["user_id"], synthetic_tenant["business_unit_id"]),
        )
        task_id = db.execute(
            "SELECT id FROM task_board WHERE title='Deep link target'"
        ).fetchone()["id"]
        db.commit()
    finally:
        db.close()
    page = login_as("employee")
    page.goto(f"{live_app}/tasks?open={task_id}")
    page.locator("#taskDrawer.open").wait_for(timeout=10000)
    assert page.locator("#tdHdrTitle").inner_text() == f"Task #{task_id}"
    assert page.locator("#ddTitle").input_value() == "Deep link target"
    assert "open=" not in page.url
