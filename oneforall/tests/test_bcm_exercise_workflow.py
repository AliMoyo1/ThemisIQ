"""PLAN-36 P08: synthetic BCM exercise lifecycle and tenant isolation."""
import json

import pytest

from modules.bcm import exercise_service as exercises


def _actor(db, suffix):
    db.execute(
        "INSERT INTO organizations (name,slug) VALUES (%s,%s)",
        (f"Exercise {suffix}", f"exercise-{suffix}"),
    )
    org_id = db.execute(
        "SELECT id FROM organizations WHERE slug=%s", (f"exercise-{suffix}",)
    ).fetchone()["id"]
    db.execute("INSERT INTO business_units (name) VALUES (%s)", (f"Exercise BU {suffix}",))
    bu_id = db.execute(
        "SELECT id FROM business_units WHERE name=%s", (f"Exercise BU {suffix}",)
    ).fetchone()["id"]
    db.execute(
        "INSERT INTO users (username,email,full_name,password_hash,org_id,business_unit_id) "
        "VALUES (%s,%s,%s,'synthetic',%s,%s)",
        (f"exercise_{suffix}", f"exercise_{suffix}@example.test", f"Exercise {suffix}", org_id, bu_id),
    )
    user_id = db.execute(
        "SELECT id FROM users WHERE username=%s", (f"exercise_{suffix}",)
    ).fetchone()["id"]
    db.execute(
        "INSERT INTO user_roles (user_id,role_key) VALUES (%s,'bcm_manager')", (user_id,)
    )
    db.commit()
    return {"id": user_id, "org_id": org_id, "business_unit_id": bu_id,
            "is_super_admin": False}


def _ready(actor, ex_id):
    workspace = exercises.get_workspace(actor, ex_id)
    for item in workspace["readiness"]:
        exercises.set_readiness(actor, ex_id, item["id"], True)
    exercises.add_participant(actor, ex_id, actor["id"], "Lead")
    exercises.confirm_participation(actor, ex_id)
    exercises.transition(actor, ex_id, "ready")
    exercises.transition(actor, ex_id, "running")


def test_exercise_lifecycle_retains_signed_report(test_db):
    actor = _actor(test_db, "lifecycle")
    ex_id = exercises.create_exercise(
        actor, {"title": "Tabletop", "scheduled_date": "2026-12-03"}
    )
    with pytest.raises(exercises.ExerciseError) as exc:
        exercises.transition(actor, ex_id, "ready")
    assert exc.value.status == 409
    _ready(actor, ex_id)
    exercises.log_event(actor, ex_id, "inject", "Payment system unavailable")
    exercises.transition(actor, ex_id, "completed_awaiting_review")
    exercises.save_review(actor, ex_id, {
        "objectives_total": 1, "objectives_met": 1,
        "aar_results": "Response completed", "aar_lessons": "Update runbook",
    })
    exercises.sign_review(actor, ex_id)
    exercises.transition(actor, ex_id, "closed")
    report = json.loads(exercises.get_report(actor, ex_id))
    assert report["exercise"]["status"] == "closed"
    assert any(event["event_type"] == "inject" for event in report["events"])
    assert report["exercise"]["effectiveness_score"] == 100


def test_exercise_scope_and_open_action_block_signoff(test_db):
    actor = _actor(test_db, "owner")
    outsider = _actor(test_db, "outsider")
    ex_id = exercises.create_exercise(actor, {"title": "Exercise with action"})
    with pytest.raises(exercises.ExerciseError) as exc:
        exercises.get_workspace(outsider, ex_id)
    assert exc.value.status == 404
    _ready(actor, ex_id)
    action_id = exercises.add_action(actor, ex_id, {
        "title": "Repair call tree", "owner_id": actor["id"], "due_date": "2026-12-05",
    })
    assert action_id
    exercises.transition(actor, ex_id, "completed_awaiting_review")
    exercises.save_review(actor, ex_id, {
        "objectives_total": 1, "objectives_met": 0,
        "aar_results": "Gap identified", "aar_lessons": "Repair the call tree",
    })
    with pytest.raises(exercises.ExerciseError) as exc:
        exercises.sign_review(actor, ex_id)
    assert exc.value.status == 409
    with pytest.raises(exercises.ExerciseError) as exc:
        exercises.transition(actor, ex_id, "closed")
    assert exc.value.status == 409

    task_id = test_db.execute(
        "SELECT task_id FROM bcm_exercise_actions WHERE id=%s", (action_id,)
    ).fetchone()["task_id"]
    test_db.execute("UPDATE task_board SET status='done' WHERE id=%s", (task_id,))
    test_db.execute(
        "INSERT INTO evidence_items (title,org_id,business_unit_id,status) "
        "VALUES ('Other tenant proof',%s,%s,'current')",
        (outsider["org_id"], outsider["business_unit_id"]),
    )
    outside_evidence = test_db.execute(
        "SELECT id FROM evidence_items WHERE title='Other tenant proof'"
    ).fetchone()["id"]
    test_db.execute(
        "INSERT INTO evidence_items (title,org_id,business_unit_id,status) "
        "VALUES ('Own proof',%s,%s,'current')",
        (actor["org_id"], actor["business_unit_id"]),
    )
    own_evidence = test_db.execute(
        "SELECT id FROM evidence_items WHERE title='Own proof'"
    ).fetchone()["id"]
    test_db.commit()
    with pytest.raises(exercises.ExerciseError) as exc:
        exercises.verify_action(actor, ex_id, action_id, outside_evidence)
    assert exc.value.status == 404
    exercises.verify_action(actor, ex_id, action_id, own_evidence)
    exercises.sign_review(actor, ex_id)
    exercises.transition(actor, ex_id, "closed")
    report = json.loads(exercises.get_report(actor, ex_id))
    assert report["actions"][0]["evidence_id"] == own_evidence
    assert report["actions"][0]["verified_at"]


def test_exercise_scheduler_reminder_is_idempotent_and_deep_links(test_db):
    from datetime import timedelta
    from core.timeutils import utcnow
    from modules.bcm.scheduler import _exercise_alert_check_tenant

    actor = _actor(test_db, "reminder")
    scheduled = (utcnow() + timedelta(days=3)).date().isoformat()
    ex_id = exercises.create_exercise(
        actor, {"title": "Upcoming tabletop", "scheduled_date": scheduled}
    )
    _exercise_alert_check_tenant(actor["org_id"])
    _exercise_alert_check_tenant(actor["org_id"])
    key = f"bcm:exercise:{actor['org_id']}:{ex_id}"
    tasks = test_db.execute(
        "SELECT id FROM task_board WHERE reminder_key=%s", (key,)
    ).fetchall()
    assert len(tasks) == 1
    notices = test_db.execute(
        "SELECT link FROM notifications WHERE user_id=%s AND title='BCM exercise upcoming'",
        (actor["id"],),
    ).fetchall()
    assert len(notices) == 1
    assert notices[0]["link"] == f"/bcm/?open=exercise:{ex_id}"
