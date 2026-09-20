"""Regression coverage for event-handler retry and notification semantics."""

import json

import pytest

from core import event_handlers
from database import insert_returning_id


def _org_and_user(db, user_id: int = 1) -> None:
    db.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (1, 'Test Org', 'test-org')"
    )
    db.execute(
        "INSERT INTO users "
        "(id, username, email, full_name, password_hash, org_id, is_active) "
        "VALUES (%s,%s,%s,%s,'x',1,1)",
        (user_id, f"user{user_id}", f"user{user_id}@example.test", f"User {user_id}"),
    )
    db.commit()


def _event(db, event_type: str = "aria.policy.published") -> int:
    event_id = insert_returning_id(
        db,
        "INSERT INTO events (event_type, source_module, source_entity_type, "
        "source_entity_id, payload, status) VALUES (%s,'aria','document',10,'{}','processing')",
        (event_type,),
    )
    db.commit()
    return event_id


def _workflow_definition(db, steps_json: str) -> int:
    definition_id = insert_returning_id(
        db,
        "INSERT INTO workflow_definitions "
        "(name, trigger_module, trigger_action, steps_json, is_active) "
        "VALUES ('Publication review','aria','policy.created',%s,1)",
        (steps_json,),
    )
    db.commit()
    return definition_id


def test_workflow_bad_steps_never_leaves_a_committed_empty_instance(test_db):
    event_id = _event(test_db)
    definition_id = _workflow_definition(test_db, "{not valid json")

    with pytest.raises(json.JSONDecodeError):
        event_handlers._auto_trigger_workflows(
            test_db, "aria.policy.published", "aria", "document", 10, None, event_id
        )

    count = test_db.execute(
        "SELECT COUNT(*) AS c FROM workflow_instances WHERE definition_id=%s",
        (definition_id,),
    ).fetchone()["c"]
    assert count == 0


def test_workflow_replay_repairs_an_existing_instance_missing_step_zero(test_db):
    event_id = _event(test_db)
    definition_id = _workflow_definition(
        test_db, json.dumps([{"name": "Review", "type": "approve", "role": ""}])
    )
    instance_id = insert_returning_id(
        test_db,
        "INSERT INTO workflow_instances "
        "(definition_id, entity_module, entity_type, entity_id, source_event_id) "
        "VALUES (%s,'aria','document',10,%s)",
        (definition_id, event_id),
    )
    test_db.commit()

    event_handlers._auto_trigger_workflows(
        test_db, "aria.policy.published", "aria", "document", 10, None, event_id
    )

    actions = test_db.execute(
        "SELECT id FROM workflow_actions WHERE instance_id=%s AND step_index=0",
        (instance_id,),
    ).fetchall()
    assert len(actions) == 1


def test_workflow_replay_does_not_duplicate_an_existing_step_zero_action(test_db):
    event_id = _event(test_db)
    definition_id = _workflow_definition(
        test_db, json.dumps([{"name": "Review", "type": "approve", "role": ""}])
    )

    event_handlers._auto_trigger_workflows(
        test_db, "aria.policy.published", "aria", "document", 10, None, event_id
    )
    event_handlers._auto_trigger_workflows(
        test_db, "aria.policy.published", "aria", "document", 10, None, event_id
    )

    counts = test_db.execute(
        "SELECT COUNT(DISTINCT wi.id) AS instances, COUNT(wa.id) AS actions "
        "FROM workflow_instances wi "
        "LEFT JOIN workflow_actions wa ON wa.instance_id=wi.id "
        "WHERE wi.definition_id=%s AND wi.source_event_id=%s",
        (definition_id, event_id),
    ).fetchone()
    assert counts["instances"] == 1
    assert counts["actions"] == 1


def test_notify_admins_reports_any_failed_insert():
    class _Rows:
        def fetchall(self):
            return [(1,), (2,)]

    class _Db:
        def execute(self, sql, params=None):
            if sql.startswith("SELECT DISTINCT"):
                return _Rows()
            if sql.startswith("INSERT INTO notifications") and params[0] == 2:
                raise RuntimeError("notification store unavailable")
            return _Rows()

    assert event_handlers._notify_admins(
        _Db(), "aria", "Published", "A policy was published."
    ) is False


def test_auto_resolve_grid_request_rolls_back_and_raises_when_notification_fails(
    test_db, monkeypatch
):
    _org_and_user(test_db)
    audit_id = insert_returning_id(
        test_db,
        "INSERT INTO grid_audits (name, status) VALUES ('Audit A','Active')",
        (),
    )
    request_id = insert_returning_id(
        test_db,
        "INSERT INTO grid_policy_requests "
        "(audit_id, framework_name, control_ref, title, requested_by, status) "
        "VALUES (%s,'ISO 27001','A.1','Access policy',1,'pending')",
        (audit_id,),
    )
    test_db.commit()

    monkeypatch.setattr(event_handlers, "get_db", lambda: test_db)
    monkeypatch.setattr(test_db, "close", lambda: None)
    monkeypatch.setattr(event_handlers, "_notify", lambda *args, **kwargs: False)

    with pytest.raises(RuntimeError, match="notification"):
        event_handlers.auto_resolve_grid_policy_requests(
            event_type="aria.policy.published",
            source_module="aria",
            entity_type="document",
            entity_id=99,
            payload={"framework": "ISO 27001", "control_ref": "A.1", "title": "Policy"},
            user_id=1,
        )

    request = test_db.execute(
        "SELECT status, aria_document_id, resolved_at FROM grid_policy_requests WHERE id=%s",
        (request_id,),
    ).fetchone()
    assert request["status"] == "pending"
    assert request["aria_document_id"] is None
    assert request["resolved_at"] is None
