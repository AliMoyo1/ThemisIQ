"""Focused G6b/G6c service and HTTP checks."""
from datetime import timedelta

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.middleware as middleware
from core.ai_policy import FEATURES
from core.timeutils import utcnow
from modules.ai_governance import literacy, platform_features
from modules.ai_governance.routes import router as ai_router
from modules.ai_governance.service import ServiceError
from tests.test_ai_governance_service import roles  # noqa: F401
from tests.test_platform_ownership import world  # noqa: F401


COURSE = {"title": "Responsible AI", "body": "Check every output.",
          "audience_roles": ["employee"], "renewal_months": 12, "due_days": 30,
          "questions": [{"prompt": "Who reviews an output?", "options": ["A person", "Nobody"], "correct": 0}],
          "pass_mark": 100}


def _published(world):
    manager = world.users["dpo_a"]
    created = literacy.create_course(world.db, manager, {**COURSE, "business_unit_id": world.unit["A"]})
    world.db.commit()
    course = created["course"]
    published = literacy.publish_course(world.db, manager, course["id"], True, course["version"])
    world.db.commit()
    return course["id"], published["course"]


def _error(call, status):
    with pytest.raises(ServiceError) as caught:
        call()
    assert caught.value.status == status


def test_literacy_grades_without_answer_leak_and_retakes_only_when_required(roles):
    world = roles
    course_id, current = _published(world)
    learner = world.users["employee_a"]
    version = current["current_version"]
    lesson = literacy.get_for_learning(world.db, learner, course_id)["course"]
    assert lesson["questions"] == [{"prompt": "Who reviews an output?", "options": ["A person", "Nobody"]}]
    assert "correct" not in str(lesson)
    failed = literacy.complete(world.db, learner, course_id, [1], False, version)["result"]
    world.db.commit()
    assert failed == {"passed": False, "score": 0, "wrong_questions": [1]}
    assert world.db.execute("SELECT count(*) FROM ai_literacy_completions").fetchone()[0] == 0
    passed = literacy.complete(world.db, learner, course_id, [0], False, version)["result"]
    world.db.commit()
    assert passed["passed"] and passed["score"] == 100
    again = literacy.complete(world.db, learner, course_id, [0], False, version)["result"]
    world.db.commit()
    assert again["already"] is True
    assert world.db.execute("SELECT count(*) FROM ai_literacy_completions").fetchone()[0] == 1
    _error(lambda: literacy.complete(world.db, learner, course_id, [0], False, 999), 409)
    world.db.rollback()
    updated = literacy.update_course(world.db, world.users["dpo_a"], course_id,
                                     {"body": "Review all AI output."}, current["version"])
    world.db.commit()
    second = literacy.publish_course(world.db, world.users["dpo_a"], course_id, True,
                                     updated["course"]["version"])
    world.db.commit()
    assert second["course"]["retake_from"] == 2
    assert literacy.my_courses(world.db, learner)["items"][0]["state"] in ("to_do", "overdue")


def test_literacy_scope_and_coverage_denominator(roles):
    world = roles
    course_id, _ = _published(world)
    learner = world.users["employee_a"]
    own = literacy.my_courses(world.db, learner)["items"]
    assert [item["id"] for item in own] == [course_id]
    assert literacy.my_courses(world.db, world.users["owner_b"])["items"] == []
    scoped = literacy.course_coverage(world.db, world.users["dpo_a"], course_id)["course"]
    assert scoped["denominator"] == 1
    assert [person["user_id"] for person in scoped["people"]] == [learner["id"]]
    _error(lambda: literacy.course_coverage(world.db, world.users["dpo_b"], course_id), 404)
    _error(lambda: literacy.get_for_learning(world.db, world.users["owner_b"], course_id), 404)


def test_literacy_acknowledgement_expiry_and_my_work(roles, monkeypatch):
    from core import ai_rollout
    from modules.launcher import my_work_service

    world = roles
    learner = world.users["employee_a"]
    course = literacy.create_course(world.db, world.users["dpo_a"], {
        "title": "AI safety briefing", "body": "Escalate unsafe output.",
        "audience_roles": ["employee"], "business_unit_id": world.unit["A"],
    })["course"]
    world.db.commit()
    published = literacy.publish_course(world.db, world.users["dpo_a"], course["id"], True,
                                         course["version"])["course"]
    world.db.commit()
    _error(lambda: literacy.complete(world.db, learner, course["id"], [], False,
                                      published["current_version"]), 422)
    world.db.rollback()
    monkeypatch.setattr(ai_rollout, "is_enabled", lambda org: True)
    before = my_work_service._ai_governance_work(world.db, learner, None)
    assert [(item["entity_type"], item["entity_id"]) for item in before
            if item["entity_type"] == "ai_literacy_course"] == [("ai_literacy_course", course["id"])]
    completed = literacy.complete(world.db, learner, course["id"], [], True,
                                   published["current_version"])["result"]
    world.db.commit()
    assert completed["passed"]
    after = my_work_service._ai_governance_work(world.db, learner, None)
    assert not any(item["entity_type"] == "ai_literacy_course" for item in after)
    world.db.execute("UPDATE ai_literacy_completions SET expires_at='2000-01-01' WHERE course_id=%s", (course["id"],))
    world.db.commit()
    assert literacy.my_courses(world.db, learner)["items"][0]["state"] == "expired"
    assert literacy.course_coverage(world.db, world.users["dpo_a"], course["id"])["course"]["expired"] == 1


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


def test_g6bc_http_access_cache_and_malformed_payloads(http):
    course_id, _ = _published(http.world)
    key = next(iter(FEATURES))
    assert http("get", "/ai-governance/literacy", name=None).status_code == 303
    assert http("get", "/ai-governance/api/literacy/mine", name="employee_a").headers["cache-control"] == "private, no-store"
    learn = http("get", f"/ai-governance/api/literacy/{course_id}/learn", name="employee_a")
    assert learn.status_code == 200 and "correct" not in learn.text
    hidden = http("get", f"/ai-governance/api/literacy/{course_id}/learn", name="owner_b")
    missing = http("get", "/ai-governance/api/literacy/999999/learn", name="owner_b")
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    assert http("post", "/ai-governance/api/literacy/courses", json=[]).status_code == 400
    assert http("get", "/ai-governance/platform-features", name="dpo_a").status_code == 403
    assert http("get", "/ai-governance/api/platform-features", name="dpo_a").status_code == 403
    assert http("get", "/ai-governance/api/platform-features", name="super").headers["cache-control"] == "private, no-store"
    assert http("put", f"/ai-governance/api/platform-features/{key}", name="super", json=[]).status_code == 400


def test_owner_literacy_quality_signal_clears_after_completion(http):
    from modules.ai_governance import quality
    from tests.test_ai_governance_routes import _accepted

    world = http.world
    app_id = _accepted(http)
    course = literacy.create_course(world.db, world.users["dpo_a"], {
        "title": "AI owner briefing", "body": "Review the use.",
        "audience_owners": True, "business_unit_id": world.unit["A"],
    })["course"]
    world.db.commit()
    published = literacy.publish_course(world.db, world.users["dpo_a"], course["id"], True,
                                         course["version"])["course"]
    world.db.commit()
    before = quality.evaluate(world.db, world.users["dpo_a"], app_id)
    assert [finding["rule"] for finding in before["findings"]].count("owner_literacy") == 1
    done = literacy.complete(world.db, world.users["employee_a"], course["id"], [], True,
                             published["current_version"])
    world.db.commit()
    assert done["result"]["passed"]
    after = quality.evaluate(world.db, world.users["dpo_a"], app_id)
    assert "owner_literacy" not in [finding["rule"] for finding in after["findings"]]
    assert quality.evaluate(world.db, world.users["dpo_b"], app_id) is None


def test_literacy_publish_notifies_the_current_audience_once(http):
    world = http.world
    created = http("post", "/ai-governance/api/literacy/courses", json={
        "title": "AI notification course", "body": "Review model output.",
        "audience_roles": ["employee"], "business_unit_id": world.unit["A"],
    })
    assert created.status_code == 201, created.text
    course = created.json()["course"]
    path = f"/ai-governance/api/literacy/courses/{course['id']}/publish"
    published = http("post", path, json={"version": course["version"], "retake": True})
    assert published.status_code == 200, published.text
    notices = world.db.execute("SELECT user_id FROM notifications WHERE user_id=%s AND link=%s",
                               (world.users["employee_a"]["id"],
                                f"/ai-governance/literacy/{course['id']}")).fetchall()
    assert len(notices) == 1
    assert http("post", path, json={"version": course["version"], "retake": True}).status_code == 409
    notices = world.db.execute("SELECT count(*) FROM notifications WHERE user_id=%s AND link=%s",
                               (world.users["employee_a"]["id"],
                                f"/ai-governance/literacy/{course['id']}")).fetchone()[0]
    assert notices == 1
