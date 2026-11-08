"""AIIA suggestions use reviewed relationships, not matching IDs or titles."""

import pytest

from modules.ai_governance import aiia_controls, assessments
from modules.ai_governance.service import ServiceError
from tests.test_ai_governance_service import commit, platform_world, user, world  # noqa: F401
from tests.test_platform_ownership import _insert


def _assessment(world, app):
    done = assessments.create_assessment(world.db, user(world, "super"),
                                         {"title": "AI impact", "application_id": app})
    commit(world, done, user(world, "super"))
    return done["assessment"]["id"]


def test_confirmed_visible_application_control_requires_aiia_review(world):
    db = world.db
    app = _insert(db, "applications", name="Model", business_unit_id=world.unit["A"], is_active=1)
    framework = _insert(db, "frameworks", name="AI framework")
    control = _insert(db, "controls", framework_id=framework, ref="AI-1", name="Human oversight")
    _insert(db, "cross_module_links", source_module="governance", source_type="application", source_id=app,
            target_module="aria", target_type="control", target_id=control, relationship="related", status="confirmed")
    db.commit()
    assessment = _assessment(world, app)
    shown = aiia_controls.context(db, user(world, "super"), assessment)
    assert [item["control_id"] for item in shown["items"]] == [control]
    assert shown["items"][0]["reasons"] == ["Linked to the AI system"]
    with pytest.raises(ServiceError) as exc:
        aiia_controls.decide(db, user(world, "super"), assessment, control + 10000, "accept")
    assert exc.value.status == 404
    done = aiia_controls.decide(db, user(world, "super"), assessment, control, "accept")
    db.commit()
    assert done["status"] == "confirmed"
    assert db.execute("SELECT status FROM cross_module_links WHERE source_type='aiia' AND source_id=%s",
                      (assessment,)).fetchone()[0] == "confirmed"
    assert aiia_controls.context(db, user(world, "super"), assessment)["items"] == []


def test_unreviewed_and_hidden_source_links_never_become_suggestions(world):
    db = world.db
    app = _insert(db, "applications", name="Model", business_unit_id=world.unit["A"], is_active=1)
    hidden = _insert(db, "applications", name="Foreign model", business_unit_id=world.unit["B"], is_active=1)
    framework = _insert(db, "frameworks", name="AI framework")
    control = _insert(db, "controls", framework_id=framework, ref="AI-1", name="Human oversight")
    _insert(db, "cross_module_links", source_module="governance", source_type="application", source_id=app,
            target_module="aria", target_type="control", target_id=control, relationship="related", status="candidate")
    _insert(db, "cross_module_links", source_module="governance", source_type="application", source_id=hidden,
            target_module="aria", target_type="control", target_id=control, relationship="related", status="confirmed")
    db.commit()
    assessment = _assessment(world, app)
    assert aiia_controls.context(db, user(world, "dpo_a"), assessment)["items"] == []
    assert aiia_controls.context(db, user(world, "dpo_b"), assessment) is None


def test_hidden_first_page_does_not_hide_later_aiia_control(world):
    db = world.db
    app = _insert(db, "applications", name="Scoped model", business_unit_id=world.unit["A"], is_active=1)
    framework = _insert(db, "frameworks", name="AI framework")
    control = _insert(db, "controls", framework_id=framework, ref="AI-201", name="Review check")
    _insert(db, "cross_module_links", source_module="governance", source_type="application", source_id=app,
            target_module="aria", target_type="control", target_id=control, relationship="related", status="confirmed")
    for number in range(200):
        hidden = db.execute(
            "INSERT INTO applications (name,business_unit_id,is_active) VALUES (%s,%s,1)",
            (f"Other unit {number}", world.unit["B"]),
        ).lastrowid
        db.execute("INSERT INTO cross_module_links "
                   "(source_module,source_type,source_id,target_module,target_type,target_id,relationship,status) "
                   "VALUES ('governance','application',%s,'governance','application',%s,'related','confirmed')",
                   (app, hidden))
    db.commit()
    assessment = _assessment(world, app)
    shown = aiia_controls.context(db, user(world, "dpo_a"), assessment)
    assert [item["control_id"] for item in shown["items"]] == [control]
