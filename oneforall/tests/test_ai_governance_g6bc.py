"""Focused platform AI feature service and HTTP checks."""
from datetime import timedelta

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.middleware as middleware
from core.ai_policy import FEATURES
from core.timeutils import utcnow
from modules.ai_governance import platform_features
from modules.ai_governance.routes import router as ai_router
from modules.ai_governance.service import ServiceError
from tests.test_ai_governance_service import roles  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401


def _error(call, status):
    with pytest.raises(ServiceError) as caught:
        call()
    assert caught.value.status == status


def test_platform_usage_counts_validation_and_overdue_state(roles):
    world = roles
    operator = world.users["super"]
    key = next(iter(FEATURES))
    for status in ("ok", "ok", "refused", "error"):
        world.db.execute("INSERT INTO ai_usage_log (org_id, feature, status) VALUES (%s, %s, %s)",
                         (world.users["dpo_a"]["org_id"], key, status))
    world.db.commit()
    item = next(entry for entry in platform_features.list_features(world.db, operator)["items"] if entry["key"] == key)
    assert item["usage"]["successful"] == 2
    assert item["usage"]["refused"] == 1 and item["usage"]["errors"] == 1
    fields = {"owner": "Owner", "provider_note": "Provider", "known_limitations": "Limits",
              "incident_path": "Security", "deployment": "paused", "review_due": "2000-01-01"}
    _error(lambda: platform_features.save_notes(world.db, operator, key,
                                                  {**fields, "review_due": "2026-02-30"}, 0), 422)
    _error(lambda: platform_features.save_notes(world.db, operator, key,
                                                  {**fields, "deployment": "enabled"}, 0), 422)
    platform_features.save_notes(world.db, operator, key, fields, 0)
    world.db.commit()
    item = next(entry for entry in platform_features.list_features(world.db, operator)["items"] if entry["key"] == key)
    assert item["review_state"] == "overdue" and item["deployment"] == "paused"
    _error(lambda: platform_features.mark_reviewed(world.db, operator, key, 1), 422)
    world.db.rollback()


def test_platform_notes_are_registry_bound_versioned_and_reviewed(roles):
    world = roles
    operator = world.users["super"]
    key = next(iter(FEATURES))
    _error(lambda: platform_features.list_features(world.db, world.users["dpo_a"]), 403)
    _error(lambda: platform_features.save_notes(world.db, operator, "unknown.feature", {}, 0), 404)
    listing = platform_features.list_features(world.db, operator)
    assert listing["count"] == len(FEATURES)
    item = next(entry for entry in listing["items"] if entry["key"] == key)
    assert item["review_state"] == "not_reviewed" and item["version"] == 0
    due = (utcnow().date() + timedelta(days=30)).isoformat()
    notes = {"owner": "Platform owner", "provider_note": "Approved provider",
             "known_limitations": "Human review required", "incident_path": "Contact security",
             "deployment": "in_service", "review_due": due}
    first = platform_features.save_notes(world.db, operator, key, notes, 0)
    world.db.commit()
    assert first["version"] == 1
    _error(lambda: platform_features.save_notes(world.db, operator, key, notes, 0), 409)
    world.db.rollback()
    reviewed = platform_features.mark_reviewed(world.db, operator, key, 1)
    world.db.commit()
    assert reviewed["version"] == 2
    _error(lambda: platform_features.mark_reviewed(world.db, operator, key, 1), 409)
    world.db.rollback()
    item = next(entry for entry in platform_features.list_features(world.db, operator)["items"] if entry["key"] == key)
    assert item["review_state"] == "reviewed" and item["owner"] == "Platform owner"
    assert not any(field in item for field in ("prompt", "response", "evidence"))


@pytest.fixture
def http(roles, monkeypatch):
    world = roles
    who = {"name": "dpo_a"}

    async def current_user(request):
        return world.users[who["name"]] if who["name"] else None

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(ai_router)
    client = TestClient(app, base_url="http://testserver", follow_redirects=False)

    def call(method, path, name="dpo_a", **kwargs):
        who["name"] = name
        return getattr(client, method)(path, **kwargs)

    call.world = world
    return call


def test_platform_feature_http_access_cache_and_malformed_payloads(http):
    key = next(iter(FEATURES))
    assert http("get", "/ai-governance/platform-features", name="dpo_a").status_code == 403
    assert http("get", "/ai-governance/api/platform-features", name="dpo_a").status_code == 403
    assert http("get", "/ai-governance/api/platform-features", name="super").headers["cache-control"] == "private, no-store"
    assert http("put", f"/ai-governance/api/platform-features/{key}", name="super", json=[]).status_code == 400


def test_nothing_in_ai_governance_opens_for_a_general_employee():
    """Owner decision, 2026-10-20: AI Governance is for specialists. Every capability a route asks for refuses an employee."""
    import pathlib
    import re
    from core.rbac import EMPLOYEE, has_capability
    folder = pathlib.Path(__file__).resolve().parent.parent / "modules" / "ai_governance"
    caps = set()
    for path in folder.rglob("*.py"):
        for gate in re.finditer(r"require_capability\(([^)]*)\)", path.read_text(encoding="utf-8")):
            caps |= set(re.findall(r'"([^"]+)"', gate.group(1)))
    assert "ai_use.submit" in caps
    employee = {"id": 1, "roles": [EMPLOYEE], "is_super_admin": 0}
    assert [cap for cap in sorted(caps) if has_capability(employee, cap)] == []
