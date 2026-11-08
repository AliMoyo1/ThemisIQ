"""Operator-only synthetic checks do not require a provider or tenant data."""

import pytest

from core import rbac
from modules.ai_governance import platform_evaluations
from modules.ai_governance.service import ServiceError
from tests.test_ai_governance_g6bc import http  # noqa: F401
from tests.test_ai_governance_service import platform_world, roles, world  # noqa: F401


PATH = "/ai-governance/api/platform-features/aria.ask/evaluations"


async def _changed_ask(*args, **kwargs):
    return {"covered": False}


def _error(work, status):
    with pytest.raises(ServiceError) as caught:
        work()
    assert caught.value.status == status


def test_fixture_results_and_independent_review(roles, monkeypatch):
    db = roles.db
    operator = roles.users["super"]
    monkeypatch.setattr("core.ai_client.create_message", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("A synthetic fixture must not call a provider")))
    result = platform_evaluations.run(db, operator, "aria.ask")
    db.commit()
    first = result["run"]
    assert first["status"] == "passed" and first["checks_total"] == 5 and first["checks_failed"] == 0
    assert all(case["passed"] for case in first["cases"])
    assert len(first["source_hash"]) == 64
    assert "prompt" not in first and "answer" not in first
    _error(lambda: platform_evaluations.run(db, roles.users["dpo_a"], "aria.ask"), 403)
    _error(lambda: platform_evaluations.run(db, operator, "unknown.feature"), 404)
    _error(lambda: platform_evaluations.review(db, operator, "aria.ask", first["id"], "accepted", 1), 403)
    db.rollback()

    db.execute("INSERT INTO users (id, username, email, full_name, password_hash, is_super_admin) "
               "VALUES (778, 'other_operator', 'other@example.test', 'Other operator', 'x', 1)")
    db.commit()
    other = {"id": 778, "roles": [rbac.SUPER_ADMIN], "is_super_admin": 1, "org_id": None}
    reviewed = platform_evaluations.review(db, other, "aria.ask", first["id"], "accepted", 1)
    db.commit()
    assert reviewed["run"]["review_outcome"] == "accepted"
    _error(lambda: platform_evaluations.review(db, other, "aria.ask", first["id"], "accepted", 1), 409)
    listed = platform_evaluations.list_runs(db, operator, "aria.ask")
    assert listed["runs"][0]["reviewed_by"] == 778
    assert "customer" in listed["scope"]

    second = platform_evaluations.run(db, operator, "aria.ask")["run"]
    db.commit()
    with monkeypatch.context() as patcher:
        patcher.setattr(platform_evaluations.ask_service, "ask", _changed_ask)
        assert platform_evaluations.list_runs(db, operator, "aria.ask")["runs"][0]["stale"] is True
        _error(lambda: platform_evaluations.review(db, other, "aria.ask", second["id"], "accepted", 1), 409)
    with monkeypatch.context() as patcher:
        patcher.setattr(platform_evaluations, "RUBRIC_VERSION", "2")
        assert platform_evaluations.list_runs(db, operator, "aria.ask")["runs"][0]["stale"] is True
        _error(lambda: platform_evaluations.review(db, other, "aria.ask", second["id"], "accepted", 1), 409)
    monkeypatch.setattr(platform_evaluations, "TEST_SET_VERSION", "2")
    assert platform_evaluations.list_runs(db, operator, "aria.ask")["runs"][0]["stale"] is True
    _error(lambda: platform_evaluations.review(db, other, "aria.ask", second["id"], "accepted", 1), 409)


def test_failed_check_cannot_be_accepted(roles, monkeypatch):
    db = roles.db
    monkeypatch.setattr(platform_evaluations, "execute_fixture_set", lambda: {
        "source_hash": platform_evaluations._source_hash(), "checks_total": 1,
        "checks_failed": 1, "cases": [{"case": "simulated regression", "passed": False}],
    })
    failed = platform_evaluations.run(db, roles.users["super"], "aria.ask")["run"]
    db.commit()
    assert failed["status"] == "failed" and failed["checks_failed"] > 0
    db.execute("INSERT INTO users (id, username, email, full_name, password_hash, is_super_admin) "
               "VALUES (779, 'review_operator', 'review@example.test', 'Review operator', 'x', 1)")
    db.commit()
    other = {"id": 779, "roles": [rbac.SUPER_ADMIN], "is_super_admin": 1, "org_id": None}
    _error(lambda: platform_evaluations.review(db, other, "aria.ask", failed["id"], "accepted", 1), 409)
    db.rollback()
    assert platform_evaluations.review(db, other, "aria.ask", failed["id"], "finding", 1)["run"]["review_outcome"] == "finding"


def test_http_requires_operator_and_does_not_cache(http):
    assert http("get", PATH, name="dpo_a").status_code == 403
    assert http("post", PATH, name="dpo_a", json={}).status_code == 403
    response = http("post", PATH, name="super", json={})
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    listing = http("get", PATH, name="super")
    assert listing.status_code == 200 and listing.json()["runs"][0]["id"] == response.json()["run"]["id"]
    assert http("post", PATH + "/" + str(response.json()["run"]["id"]) + "/review",
                name="super", json={"outcome": "accepted", "version": 1}).status_code == 403
    assert http("get", "/ai-governance/api/platform-features/unknown/evaluations", name="super").status_code == 404
