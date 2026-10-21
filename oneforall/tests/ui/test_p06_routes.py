"""
PLAN-36 P06: GET/POST/PUT/DELETE /api/saved-views and
PUT /evidence/api/items/bulk-archive (the first module onboarded).

Validation/ownership/bulk-engine logic is covered thoroughly, with a
red/green proof, in tests/test_saved_views.py -- this file checks the
route layer: auth, and a real mixed authorized/unauthorized bulk-archive
through actual HTTP, proving the route wires the generic engine and
Evidence Vault's own org-scoping together correctly.
"""
import httpx

import database


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


def test_unauthenticated_saved_views_request_is_redirected(live_app):
    client = httpx.Client(base_url=live_app, follow_redirects=False, timeout=10)
    resp = client.get("/api/saved-views?module=evidence&view_key=items_list")
    assert resp.status_code in (301, 302, 303, 307, 308)
    assert "/login" in resp.headers.get("location", "")


def test_create_list_and_delete_a_saved_view(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["employee"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        create_resp = client.post("/api/saved-views", json={
            "module": "evidence", "view_key": "items_list", "name": "My expiring items",
            "filter_params": {"view": "expiring"},
        })
        assert create_resp.status_code == 201
        view_id = create_resp.json()["view"]["id"]

        list_resp = client.get("/api/saved-views?module=evidence&view_key=items_list")
        assert list_resp.status_code == 200
        assert any(v["id"] == view_id for v in list_resp.json()["views"])

        delete_resp = client.delete(f"/api/saved-views/{view_id}")
        assert delete_resp.status_code == 200

        list_resp2 = client.get("/api/saved-views?module=evidence&view_key=items_list")
        assert not any(v["id"] == view_id for v in list_resp2.json()["views"])
    finally:
        client.close()


def test_malicious_filter_param_is_rejected_over_http(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["employee"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.post("/api/saved-views", json={
            "module": "evidence", "view_key": "items_list", "name": "Bad",
            "filter_params": {"status": "current", "raw_sql": "1=1; DROP TABLE evidence_items;"},
        })
        assert resp.status_code == 422
    finally:
        client.close()


def test_employee_cannot_bulk_archive_without_evidence_delete_capability(live_app, synthetic_tenant):
    creds = synthetic_tenant["users"]["employee"]
    client = _login(live_app, creds["username"], creds["password"])
    try:
        resp = client.put("/evidence/api/items/bulk-archive", json={"ids": [1]})
        assert resp.status_code == 403
    finally:
        client.close()


def test_bulk_archive_excludes_an_item_from_another_org(live_app, synthetic_tenant):
    """The acceptance line this exists to prove: 'a mixed authorized/
    unauthorized selection cannot mutate unauthorized rows' -- here the
    unauthorized row belongs to a different organization entirely."""
    manager_creds = synthetic_tenant["users"]["compliance_manager"]
    own_org_id = manager_creds["org_id"]

    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO organizations (name, slug, plan, status) "
            "VALUES ('P06 Other Org', 'p06-other-org', 'enterprise', 'active')"
        )
        db.commit()
        other_org_id = db.execute("SELECT id FROM organizations WHERE slug='p06-other-org'").fetchone()["id"]

        db.execute(
            "INSERT INTO evidence_items (title, org_id, status) VALUES ('Own org item', %s, 'current')",
            (own_org_id,),
        )
        db.execute(
            "INSERT INTO evidence_items (title, org_id, status) VALUES ('Other org item', %s, 'current')",
            (other_org_id,),
        )
        db.commit()
        own_item_id = db.execute("SELECT id FROM evidence_items WHERE title='Own org item'").fetchone()["id"]
        other_item_id = db.execute("SELECT id FROM evidence_items WHERE title='Other org item'").fetchone()["id"]
    finally:
        db.close()

    client = _login(live_app, manager_creds["username"], manager_creds["password"])
    try:
        resp = client.put("/evidence/api/items/bulk-archive", json={"ids": [own_item_id, other_item_id]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied"] == [own_item_id]
        assert any(s["id"] == other_item_id for s in body["skipped"])
    finally:
        client.close()

    db = database.get_db()
    try:
        own_status = db.execute("SELECT status FROM evidence_items WHERE id=%s", (own_item_id,)).fetchone()["status"]
        other_status = db.execute("SELECT status FROM evidence_items WHERE id=%s", (other_item_id,)).fetchone()["status"]
        assert own_status == "archived"
        assert other_status == "current"  # untouched
    finally:
        db.close()


def test_bulk_archive_idempotency_key_prevents_double_processing(live_app, synthetic_tenant):
    manager_creds = synthetic_tenant["users"]["compliance_manager"]
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO evidence_items (title, org_id, status) VALUES ('Idem item', %s, 'current')",
            (manager_creds["org_id"],),
        )
        db.commit()
        item_id = db.execute("SELECT id FROM evidence_items WHERE title='Idem item'").fetchone()["id"]
    finally:
        db.close()

    client = _login(live_app, manager_creds["username"], manager_creds["password"])
    try:
        first = client.put(
            "/evidence/api/items/bulk-archive", json={"ids": [item_id]},
            headers={"Idempotency-Key": "p06-http-test-key-1"},
        )
        assert first.status_code == 200
        assert first.json()["idempotent_replay"] is False

        second = client.put(
            "/evidence/api/items/bulk-archive", json={"ids": [item_id]},
            headers={"Idempotency-Key": "p06-http-test-key-1"},
        )
        assert second.status_code == 200
        assert second.json()["idempotent_replay"] is True
    finally:
        client.close()
