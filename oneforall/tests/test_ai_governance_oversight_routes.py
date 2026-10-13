"""G7 oversight API responses and access checks."""

from tests.test_ai_governance_oversight import COMPLETE
from tests.test_ai_governance_routes import http  # noqa: F401
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401


def _system(http):
    world = http.world
    for name, (role, _) in PERSONAS.items():
        world.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (world.users[name]["id"], role))
    app = _insert(world.db, "applications", name="Oversight app", business_unit_id=world.unit["A"], is_active=1)
    hidden = _insert(world.db, "applications", name="Hidden app", business_unit_id=world.unit["B"], is_active=1)
    _insert(world.db, "ai_use_profiles", application_id=app, version=1)
    return app, hidden


def test_oversight_api_requires_access_and_hides_other_units(http):
    app, hidden = _system(http)
    base = f"/ai-governance/api/systems/{app}/oversight/design"
    for path in (f"/ai-governance/api/systems/{hidden}/oversight/design",
                 "/ai-governance/api/systems/999999/oversight/design"):
        response = http("get", path, name="dpo_a")
        assert response.status_code == 404 and response.json() == {"ok": False, "error": "AI use not found."}
        assert response.headers["cache-control"] == "private, no-store"
    assert http("get", base, name="auditor").status_code == 403
    assert http("put", base, name="employee_a", json={"revision": 0, "arrangement": COMPLETE}).status_code == 403
    assert http("get", base, name="dpo_a").json()["oversight"]["current"] is None
    assert http("get", base, name="dpo_a").headers["cache-control"] == "private, no-store"


def test_oversight_api_saves_reviews_and_rejects_stale_writes(http):
    app, _hidden = _system(http)
    base = f"/ai-governance/api/systems/{app}/oversight/design"
    picker = http("get", f"/ai-governance/api/systems/{app}/oversight-people?q=employee", name="dpo_a")
    assert picker.status_code == 200
    assert [item["name"] for item in picker.json()["items"]] == ["employee_a"]
    payload = {**COMPLETE, "responsible_user_id": http.world.users["employee_a"]["id"]}
    saved = http("put", base, name="dpo_a", json={"revision": 0, "arrangement": payload})
    assert saved.status_code == 200, saved.text
    assert saved.headers["cache-control"] == "private, no-store"
    assert saved.json()["oversight"]["current"]["version"] == 1
    own_review = http("post", base + "/review", name="dpo_a", json={"revision": 1})
    assert own_review.status_code == 403
    reviewed = http("post", base + "/review", name="owner_a", json={"revision": 1})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["oversight"]["current"]["status"] == "reviewed"
    stale = http("put", base, name="dpo_a", json={"revision": 1, "arrangement": payload})
    assert stale.status_code == 409
    assert http("get", base, name="dpo_a").json()["oversight"]["revision"] == 2
