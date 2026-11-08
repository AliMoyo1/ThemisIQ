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


def test_every_registered_feature_passes_its_policy_refusal_set_without_a_provider(roles, monkeypatch):
    from core.ai_policy import FEATURES
    monkeypatch.setattr("core.ai_client.create_message", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("A synthetic fixture must not call a provider")))
    for key, (_label, categories) in FEATURES.items():
        result = platform_evaluations.execute_policy_set(key)
        assert result["checks_failed"] == 0, (key, [c for c in result["cases"] if not c["passed"]])
        assert result["checks_total"] == 7 + len(categories), key
    db = roles.db
    run = platform_evaluations.run(db, roles.users["super"], "sentinel.ai_chat")["run"]
    db.commit()
    assert run["test_set"] == platform_evaluations.POLICY_TEST_SET and run["status"] == "passed"
    names = [case["case"] for case in run["cases"]]
    assert "refused when personal data is not allowed" in names and "refused when AI is switched off" in names
    listed = platform_evaluations.list_runs(db, roles.users["super"], "sentinel.ai_chat")
    assert [s["key"] for s in listed["test_sets"]] == [platform_evaluations.POLICY_TEST_SET]
    assert "not measured" in listed["scope"]


def test_a_policy_gate_regression_fails_the_set_and_a_changed_declaration_makes_old_runs_stale(roles, monkeypatch):
    db = roles.db
    operator = roles.users["super"]
    passed = platform_evaluations.run(db, operator, "erm.chat", platform_evaluations.POLICY_TEST_SET)["run"]
    db.commit()
    assert passed["status"] == "passed"

    with monkeypatch.context() as patcher:
        # A broken gate that lets everything through must be caught by the cases, not only by code review.
        patcher.setattr("core.ai_policy._refusal", lambda *args, **kwargs: None)
        broken = platform_evaluations.execute_policy_set("erm.chat")
        still_passing = {c["case"] for c in broken["cases"] if c["passed"]}
        assert still_passing == {"declares what it sends and has a written declaration",
                                 "allowed when the policy permits this provider, feature and data",
                                 "refused when the stored policy is unreadable"}  # refused while reading, before the gate
    with monkeypatch.context() as patcher:
        patcher.setitem(platform_evaluations.ai_policy.FEATURES, "erm.chat", ("Risk assistant", ("business", "personal")))
        assert platform_evaluations.list_runs(db, operator, "erm.chat")["runs"][0]["stale"] is True
    assert platform_evaluations.list_runs(db, operator, "erm.chat")["runs"][0]["stale"] is False


def test_aria_ask_offers_both_sets_and_an_unknown_set_is_refused(roles):
    db = roles.db
    operator = roles.users["super"]
    sets = [s["key"] for s in platform_evaluations.list_runs(db, operator, "aria.ask")["test_sets"]]
    assert sets == [platform_evaluations.TEST_SET, platform_evaluations.POLICY_TEST_SET]
    policy = platform_evaluations.run(db, operator, "aria.ask", platform_evaluations.POLICY_TEST_SET)["run"]
    db.commit()
    assert policy["test_set"] == platform_evaluations.POLICY_TEST_SET and policy["stale"] is False
    _error(lambda: platform_evaluations.run(db, operator, "erm.chat", platform_evaluations.TEST_SET), 422)
    _error(lambda: platform_evaluations.run(db, operator, "aria.ask", "made.up"), 422)


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
    other = http("post", "/ai-governance/api/platform-features/erm.chat/evaluations", name="super",
                 json={"test_set": "ai-policy.refusal"})
    assert other.status_code == 201, other.text
    assert other.json()["run"]["test_set"] == "ai-policy.refusal"
    assert http("post", "/ai-governance/api/platform-features/erm.chat/evaluations", name="super",
                json={"test_set": ["not", "text"]}).status_code == 422
