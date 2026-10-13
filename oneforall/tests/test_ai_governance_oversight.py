"""G7 oversight: scoped ownership, version history, and independent review."""

import pytest

from core import ai_rollout
from modules.ai_governance import decisions, monitoring, oversight
from modules.ai_governance.service import ServiceError
from modules.governance.data_service import bu_scope_ids
from modules.launcher.my_work_service import _ai_governance_work
from tests.test_platform_ownership import PERSONAS, _insert, world  # noqa: F401


COMPLETE = {
    "monitoring_method": "Team lead checks the output log each morning.",
    "intervention_method": "Reviewer can correct or reject an output.",
    "stop_procedure": "Disable the use and return to the manual queue.",
    "escalation_path": "Escalate harmful output to the incident lead.",
}


@pytest.fixture
def system(world):
    for name, (role, _) in PERSONAS.items():
        world.db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)", (world.users[name]["id"], role))
    world.app = _insert(world.db, "applications", name="AI A", business_unit_id=world.unit["A"], is_active=1)
    world.hidden = _insert(world.db, "applications", name="AI B", business_unit_id=world.unit["B"], is_active=1)
    _insert(world.db, "ai_use_profiles", application_id=world.app, version=1)
    return world


def person(system, name):
    return system.users[name]


def fail(call, status):
    with pytest.raises(ServiceError) as caught:
        call()
    assert caught.value.status == status


def draft(system, track="design", version=0, **changes):
    payload = {**COMPLETE, "responsible_user_id": person(system, "employee_a")["id"], **changes}
    result = oversight.save_arrangement(system.db, person(system, "dpo_a"), system.app, track, payload, version)
    system.db.commit()
    return result["oversight"]


def test_hidden_and_missing_uses_are_identical_and_never_write(system):
    for application_id in (system.hidden, 999999):
        fail(lambda: oversight.get_arrangement(system.db, person(system, "dpo_a"), application_id, "design"), 404)
        fail(lambda: oversight.save_arrangement(system.db, person(system, "dpo_a"), application_id,
                                                 "design", COMPLETE, 0), 404)
    fail(lambda: oversight.get_arrangement(system.db, person(system, "dpo_b"), system.app, "design"), 404)
    fail(lambda: oversight.eligible_people(system.db, person(system, "dpo_b"), system.app, "emp"), 404)
    assert system.db.execute("SELECT COUNT(*) FROM ai_oversight_heads").fetchone()[0] == 0


def test_review_keeps_content_and_an_edit_creates_a_new_draft(system):
    first = draft(system)
    assert first["current"]["status"] == "draft" and first["revision"] == 1
    fail(lambda: oversight.review_arrangement(system.db, person(system, "dpo_a"), system.app, "design", 1), 403)
    reviewed = oversight.review_arrangement(system.db, person(system, "owner_a"), system.app, "design", 1)["oversight"]
    system.db.commit()
    assert reviewed["current"]["status"] == "reviewed" and reviewed["revision"] == 2
    assert reviewed["current"]["reviewed_by"] == person(system, "owner_a")["id"]
    second = draft(system, version=2, monitoring_method="A new monitoring procedure")
    assert second["current"]["version"] == 2 and second["current"]["status"] == "draft"
    assert second["history"][0]["status"] == "reviewed"
    assert second["history"][0]["monitoring_method"] == COMPLETE["monitoring_method"]
    fail(lambda: oversight.save_arrangement(system.db, person(system, "dpo_a"), system.app,
                                             "design", COMPLETE, 2), 409)
    system.db.rollback()
    assert second["current"]["monitoring_method"] != second["history"][0]["monitoring_method"]


def test_profile_change_blocks_review_until_a_new_version_is_saved(system):
    draft(system)
    system.db.execute("UPDATE ai_use_profiles SET version = version + 1 WHERE application_id = %s", (system.app,))
    system.db.commit()
    got = oversight.get_arrangement(system.db, person(system, "dpo_a"), system.app, "design")["oversight"]
    assert got["current"]["profile_changed"] is True
    fail(lambda: oversight.review_arrangement(system.db, person(system, "owner_a"), system.app, "design", 1), 409)
    system.db.rollback()
    fresh = draft(system, version=1)
    assert fresh["current"]["profile_version"] == 2 and fresh["current"]["profile_changed"] is False


def test_two_tracks_are_independent_and_incomplete_content_cannot_be_reviewed(system):
    draft(system, "design")
    operation = draft(system, "operation", stop_procedure="")
    assert operation["revision"] == 1
    assert oversight.get_arrangement(system.db, person(system, "dpo_a"), system.app,
                                     "design")["oversight"]["current"]["version"] == 1
    fail(lambda: oversight.review_arrangement(system.db, person(system, "owner_a"), system.app, "operation", 1), 422)
    system.db.rollback()


def test_person_picker_and_save_exclude_unreachable_or_inactive_people(system):
    items = oversight.eligible_people(system.db, person(system, "dpo_a"), system.app, "employee")["items"]
    assert [item["name"] for item in items] == ["employee_a"]
    fail(lambda: oversight.save_arrangement(system.db, person(system, "dpo_a"), system.app,
                                             "design", {**COMPLETE, "responsible_user_id": person(system, "employee_a")["id"]}, True), 400)
    fail(lambda: oversight.save_arrangement(system.db, person(system, "dpo_a"), system.app,
                                             "design", {**COMPLETE, "responsible_user_id": person(system, "employee_a")["id"],
                                                        "unexpected": "x"}, 0), 422)
    fail(lambda: oversight.save_arrangement(system.db, person(system, "dpo_a"), system.app,
                                             "design", {**COMPLETE, "responsible_user_id": person(system, "employee_a")["id"],
                                                        "monitoring_method": "x" * 2001}, 0), 422)


def test_live_oversight_status_connects_to_monitoring_and_decisions_without_changing_a_signed_brief(system):
    viewer = person(system, "dpo_a")
    summary = oversight.summary_for_use(system.db, viewer, system.app)
    assert [summary["tracks"][name]["status"] for name in oversight.TRACKS] == ["not_recorded", "not_recorded"]
    fail(lambda: oversight.summary_for_use(system.db, person(system, "dpo_b"), system.app), 404)
    before = decisions.get_brief(system.db, viewer, system.app)
    assert before is not None
    draft(system)
    got = monitoring.get_monitoring(system.db, viewer, system.app)
    source = next(s for s in got["sources"] if s["source"] == "oversight")
    assert source["state"] == "attention" and "oversight" in got["attention"]
    assert [i["detail"] for i in source["items"]] == ["Draft awaiting an independent review", "No arrangement recorded"]
    context = decisions.get_decisions(system.db, viewer, system.app)["oversight"]
    assert context["tracks"]["design"]["status"] == "draft"
    assert decisions.get_brief(system.db, viewer, system.app)["hash"] == before["hash"]
    oversight.review_arrangement(system.db, person(system, "owner_a"), system.app, "design", 1)
    system.db.commit()
    draft(system, "operation")
    oversight.review_arrangement(system.db, person(system, "owner_a"), system.app, "operation", 1)
    system.db.commit()
    got = monitoring.get_monitoring(system.db, viewer, system.app)
    assert next(s for s in got["sources"] if s["source"] == "oversight")["state"] == "ok"
    system.db.execute("UPDATE ai_use_profiles SET version = version + 1 WHERE application_id = %s", (system.app,))
    system.db.commit()
    got = monitoring.get_monitoring(system.db, viewer, system.app)
    assert next(s for s in got["sources"] if s["source"] == "oversight")["state"] == "attention"
    assert decisions.get_decisions(system.db, viewer, system.app)["oversight"]["tracks"]["design"]["profile_changed"] is True


def test_my_work_shows_only_actionable_oversight_for_visible_uses(system, monkeypatch):
    monkeypatch.setattr(ai_rollout, "is_enabled", lambda org_id: True)
    draft(system)

    def actions(name):
        actor = person(system, name)
        return [item for item in _ai_governance_work(system.db, actor, bu_scope_ids(actor))
                if item["entity_type"].startswith("ai_oversight_")]

    assert [(item["action"], item["section"]) for item in actions("dpo_a")] == [("view", "waiting_on_others")]
    assert [(item["action"], item["section"]) for item in actions("owner_a")] == [("review_ai_oversight", "needs_my_action")]
    assert actions("dpo_b") == []
    oversight.review_arrangement(system.db, person(system, "owner_a"), system.app, "design", 1)
    system.db.commit()
    assert actions("dpo_a") == [] and actions("owner_a") == []
    system.db.execute("UPDATE ai_use_profiles SET version = version + 1 WHERE application_id = %s", (system.app,))
    system.db.commit()
    assert [item["action"] for item in actions("dpo_a")] == ["update_ai_oversight"]
    assert actions("dpo_b") == []
    fail(lambda: oversight.save_arrangement(system.db, person(system, "dpo_a"), system.app,
                                             "design", {**COMPLETE, "responsible_user_id": person(system, "owner_b")["id"]}, 0), 422)
    system.db.execute("UPDATE users SET is_active = 0 WHERE id = %s", (person(system, "employee_a")["id"],))
    system.db.commit()
    assert oversight.eligible_people(system.db, person(system, "dpo_a"), system.app, "employee")["items"] == []
