"""Legacy workflow assignments must not send reminders across organizations."""

import database
from core import workflow_scheduler


def test_overdue_reminder_excludes_cross_organization_assignee(test_db, monkeypatch):
    test_db.execute(
        "INSERT INTO organizations (id,name,slug) VALUES "
        "(4001,'Workflow A','workflow-a'),(4002,'Workflow B','workflow-b')"
    )
    for uid, org in ((4001, 4001), (4002, 4002)):
        test_db.execute(
            "INSERT INTO users "
            "(id,username,email,full_name,password_hash,org_id,is_active) "
            "VALUES (%s,%s,%s,%s,'x',%s,1)",
            (uid, f"workflow_{uid}", f"workflow_{uid}@example.test",
             f"Workflow {uid}", org),
        )
    definition_id = database.insert_returning_id(
        test_db,
        "INSERT INTO workflow_definitions "
        "(name,steps_json,created_by) VALUES ('Tenant A private flow','[]',4001)",
        (),
    )
    instance_id = database.insert_returning_id(
        test_db,
        "INSERT INTO workflow_instances (definition_id,started_by,org_id) "
        "VALUES (%s,4001,4001)",
        (definition_id,),
    )
    for uid in (4001, 4002):
        test_db.execute(
            "INSERT INTO workflow_actions "
            "(instance_id,step_index,assigned_to,due_at) "
            "VALUES (%s,0,%s,'2000-01-01 00:00:00')",
            (instance_id, uid),
        )
    test_db.commit()

    monkeypatch.setattr(workflow_scheduler, "get_db", database.get_db)
    workflow_scheduler._run_workflow_step_reminders()

    reminders = test_db.execute(
        "SELECT user_id FROM notifications "
        "WHERE module='workflow' AND title LIKE 'Overdue%' "
        "ORDER BY user_id"
    ).fetchall()
    assert [row["user_id"] for row in reminders] == [4001]


def test_sla_warnings_and_breach_updates_stay_in_organization(test_db, monkeypatch):
    test_db.execute(
        "INSERT INTO organizations (id,name,slug) VALUES "
        "(4101,'SLA A','sla-a'),(4102,'SLA B','sla-b')"
    )
    for uid, org in ((4101, 4101), (4102, 4102)):
        test_db.execute(
            "INSERT INTO users "
            "(id,username,email,full_name,password_hash,org_id,is_active) "
            "VALUES (%s,%s,%s,%s,'x',%s,1)",
            (uid, f"sla_{uid}", f"sla_{uid}@example.test", f"SLA {uid}", org),
        )
        test_db.execute(
            "INSERT INTO user_roles (user_id,role_key) VALUES (%s,'compliance_mgr')",
            (uid,),
        )
    definition_id = database.insert_returning_id(
        test_db,
        "INSERT INTO sla_definitions (name,module,entity_type) "
        "VALUES ('SLA warning tenant check','bcm','incident')",
        (),
    )
    from datetime import timedelta
    from core.timeutils import utcnow
    due = (utcnow() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    for org in (4101, 4102):
        test_db.execute(
            "INSERT INTO sla_instances "
            "(definition_id,org_id,entity_module,entity_type,entity_id,response_due) "
            "VALUES (%s,%s,'bcm','incident',%s,%s)",
            (definition_id, org, org, due),
        )
    test_db.commit()
    monkeypatch.setattr(workflow_scheduler, "get_db", database.get_db)

    workflow_scheduler._run_sla_checks_tenant(4101)

    warnings = test_db.execute(
        "SELECT user_id FROM notifications WHERE module='sla_warning'"
    ).fetchall()
    assert [row["user_id"] for row in warnings] == [4101]
    assert test_db.execute(
        "SELECT breached FROM sla_instances WHERE org_id=4102"
    ).fetchone()["breached"] == 0
