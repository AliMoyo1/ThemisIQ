"""P08 exercise workspace HTTP tenant boundary."""
import httpx

import database
from modules.bcm import exercise_service


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


def test_exercise_workspace_route_is_scoped_to_organization(live_app, synthetic_tenant):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO organizations (name,slug) VALUES ('Other Exercise Org','other-exercise-org')"
        )
        org_id = db.execute(
            "SELECT id FROM organizations WHERE slug='other-exercise-org'"
        ).fetchone()["id"]
        db.execute("INSERT INTO business_units (name) VALUES ('Other Exercise BU')")
        bu_id = db.execute(
            "SELECT id FROM business_units WHERE name='Other Exercise BU'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO users (username,email,full_name,password_hash,org_id,business_unit_id) "
            "VALUES ('other_exercise_manager','other_exercise_manager@example.test',"
            "'Other Exercise Manager','synthetic',%s,%s)",
            (org_id, bu_id),
        )
        user_id = db.execute(
            "SELECT id FROM users WHERE username='other_exercise_manager'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO user_roles (user_id,role_key) VALUES (%s,'bcm_manager')",
            (user_id,),
        )
        db.commit()
    finally:
        db.close()
    outsider = {"id": user_id, "org_id": org_id, "business_unit_id": bu_id,
                "is_super_admin": False}
    exercise_id = exercise_service.create_exercise(
        outsider, {"title": "Other organization exercise"}
    )
    client = _login(live_app, synthetic_tenant["users"]["bcm_manager"])
    try:
        own = client.post(
            "/bcm/api/exercises", json={"title": "Own organization exercise"}
        )
        assert own.status_code in (200, 201)
        own_id = own.json().get("id")
        assert own_id
        assert client.get(f"/bcm/api/exercises/{own_id}/workspace").status_code == 200
        assert client.get(f"/bcm/api/exercises/{exercise_id}/workspace").status_code == 404
        assert client.post(
            f"/bcm/api/exercises/{exercise_id}/transition",
            json={"target": "ready"},
        ).status_code == 404
    finally:
        client.close()
