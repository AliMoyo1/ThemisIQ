"""Scoped specialist home summaries preserve empty and unavailable states."""

import pytest

from modules.launcher import module_home


def _id(db, table, **columns):
    result = db.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join(['%s'] * len(columns))})",
        tuple(columns.values()),
    )
    db.commit()
    return result.lastrowid


def _admin(db):
    org = _id(db, "organizations", name="Home tenant", slug="home-tenant")
    uid = _id(db, "users", username="home-admin", email="home@example.test",
              full_name="Home admin", password_hash="x", org_id=org)
    return {"id": uid, "org_id": org, "is_super_admin": True,
            "roles": ["super_admin"]}


def test_module_home_uses_source_records_and_distinguishes_empty_quality(test_db, monkeypatch):
    user = _admin(test_db)
    called = []

    def work(_user, **kwargs):
        called.append(kwargs)
        return {"counts": {"needs_my_action": 2, "due_soon": 1, "overdue": 0},
                "source_states": [{"source": "grid_non_conformances", "state": "available"}]}

    monkeypatch.setattr(module_home, "get_my_work", work)
    empty = module_home.build("grid", user)["cards"]
    assert empty["portfolio"]["value"] == 0
    assert empty["quality"]["state"] == "not_measured"
    assert empty["act_now"]["value"] == 3
    assert called[0]["only_sources"] == frozenset({"grid_non_conformances"})

    _id(test_db, "grid_audits", name="Scoped audit", lead_id=user["id"])
    cards = module_home.build("grid", user)["cards"]
    assert cards["portfolio"]["value"] == 1
    assert cards["trends"]["state"] == "measured"
    assert cards["trends"]["value"] == 1
    assert (cards["quality"]["value"], cards["quality"]["denominator"]) == (1, 1)


def test_module_home_fails_closed_for_unknown_or_unlicensed_module(test_db):
    user = _admin(test_db)
    with pytest.raises(LookupError):
        module_home.build("evidence_items", user)
    user["is_super_admin"] = False
    user["roles"] = ["employee"]
    with pytest.raises(LookupError):
        module_home.build("grid", user)


def test_module_home_http_respects_access(test_db, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    import core.middleware as middleware
    from modules.launcher.routes_dashboard import router

    user = _admin(test_db)
    active = {"user": user}

    async def current_user(request):
        return active["user"]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    monkeypatch.setattr(module_home, "get_my_work", lambda *_a, **_k: {
        "counts": {}, "source_states": []})
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/module-home/grid")
    assert response.status_code == 200
    assert response.json()["cards"]["portfolio"]["value"] == 0
    active["user"] = {**user, "is_super_admin": False, "roles": ["employee"]}
    assert client.get("/api/module-home/grid").status_code == 404
