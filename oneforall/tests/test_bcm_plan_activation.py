"""Plan activation must not create an audit record for an invalid incident or repeat."""

import pytest
import json

from modules.bcm import data_service as bcm
from modules.bcm.control_dependencies import for_plan
from modules.governance import change_signals
from tests.test_platform_ownership import _insert, world  # noqa: F401


def test_activation_rechecks_plan_and_incident_in_one_transaction(world, monkeypatch):
    db = world.db
    unit_a = world.units["A"] if hasattr(world, "units") else world.unit["A"]
    unit_b = world.units["B"] if hasattr(world, "units") else world.unit["B"]
    approved = _insert(db, "bcm_plans", title="Recovery", status="approved", business_unit_id=unit_a)
    draft = _insert(db, "bcm_plans", title="Unapproved", status="draft", business_unit_id=unit_a)
    valid = _insert(db, "bcm_incidents", title="Outage", status="open", business_unit_id=unit_a)
    foreign = _insert(db, "bcm_incidents", title="Other unit", status="open", business_unit_id=unit_b)
    closed = _insert(db, "bcm_incidents", title="Old outage", status="closed", business_unit_id=unit_a)

    class SharedConnection:
        def __getattr__(self, name):
            if name == "close":
                return lambda: None
            return getattr(db, name)

    monkeypatch.setattr(bcm, "get_db", lambda: SharedConnection())
    user = world.users["super"]
    for plan, incident in ((draft, valid), (approved, foreign), (approved, closed), (approved, 999999)):
        with pytest.raises(ValueError):
            bcm.activate_plan(plan, "Reviewer", user["id"], "Testing", incident, bu_scope=[unit_a],
                              user=user, control_review=[])
    assert db.execute("SELECT COUNT(*) FROM bcm_plan_activations").fetchone()[0] == 0

    bcm.activate_plan(approved, "Reviewer", user["id"], "Testing", valid, bu_scope=[unit_a],
                      user=user, control_review=[])
    with pytest.raises(ValueError):
        bcm.activate_plan(approved, "Reviewer", user["id"], "Repeat", valid, bu_scope=[unit_a],
                          user=user, control_review=[])
    assert db.execute("SELECT COUNT(*) FROM bcm_plan_activations WHERE plan_id=%s", (approved,)).fetchone()[0] == 1


def test_plan_dependencies_come_from_confirmed_visible_process_links(world, monkeypatch):
    db = world.db
    unit = world.unit["A"]
    plan = _insert(db, "bcm_plans", title="Recovery", status="approved", business_unit_id=unit)
    process = _insert(db, "business_processes", name="Payments", business_unit_id=unit)
    bia = _insert(db, "bcm_bia_records", process_name="Payments", business_process_id=process,
                  business_unit_id=unit)
    _insert(db, "bcm_bia_plan_links", bia_id=bia, plan_id=plan)
    framework = _insert(db, "frameworks", name="Continuity framework")
    control = _insert(db, "controls", framework_id=framework, ref="BC-1", name="Recovery test",
                      status="Implemented")
    _insert(db, "cross_module_links", source_module="governance", source_type="process", source_id=process,
            target_module="aria", target_type="control", target_id=control, relationship="supports",
            status="confirmed")
    shown = for_plan(db, world.users["super"], plan)
    assert [row["id"] for row in shown] == [control]
    assert shown[0]["sources"] == ["Linked to a covered business process"]
    class SharedConnection:
        def __getattr__(self, name):
            if name == "close":
                return lambda: None
            return getattr(db, name)

    monkeypatch.setattr(bcm, "get_db", lambda: SharedConnection())
    user = world.users["super"]
    with pytest.raises(ValueError, match="Review"):
        bcm.activate_plan(plan, "Reviewer", user["id"], bu_scope=[unit], user=user)
    with pytest.raises(ValueError, match="changed"):
        bcm.activate_plan(plan, "Reviewer", user["id"], bu_scope=[unit], user=user,
                          control_review=[{"id": control + 999, "result": "still_working"}])
    assert db.execute("SELECT COUNT(*) FROM bcm_plan_activations").fetchone()[0] == 0
    snapshot = bcm.activate_plan(plan, "Reviewer", user["id"], bu_scope=[unit], user=user,
                                 control_review=[{"id": control, "result": "not_working"}])
    assert snapshot[0]["result"] == "not_working"
    saved = db.execute("SELECT control_review_json FROM bcm_plan_activations WHERE plan_id=%s", (plan,)).fetchone()[0]
    assert json.loads(saved) == snapshot
    signal_id = change_signals.publish(
        db, source=("aria", "control", control), kind="control_check_failed",
        before={"activation_check": "unverified"},
        after={"activation_check": f"reported not working for plan {plan}"},
        fields={"activation_check": "Activation check"}, actor_id=user["id"],
        org_id=user["org_id"], extra_targets=(("bcm", "plan", plan),),
    )
    assert signal_id is not None
    assert db.execute("SELECT target_id FROM change_signal_targets WHERE signal_id=%s AND target_type='plan'",
                      (signal_id,)).fetchone()[0] == plan
    db.execute("UPDATE cross_module_links SET status='candidate' WHERE target_id=%s", (control,))
    db.commit()
    assert for_plan(db, world.users["super"], plan) == []


def test_plan_dependencies_follow_only_visible_confirmed_application_edges(world):
    db = world.db
    unit = world.unit["A"]
    plan = _insert(db, "bcm_plans", title="Recovery", status="approved", business_unit_id=unit)
    process = _insert(db, "business_processes", name="Payments", business_unit_id=unit)
    bia = _insert(db, "bcm_bia_records", process_name="Payments", business_process_id=process,
                  business_unit_id=unit)
    _insert(db, "bcm_bia_plan_links", bia_id=bia, plan_id=plan)
    app = _insert(db, "applications", name="Payments app", business_unit_id=unit, is_active=1)
    framework = _insert(db, "frameworks", name="Continuity framework")
    control = _insert(db, "controls", framework_id=framework, ref="BC-2", name="Failover",
                      status="Implemented")
    _insert(db, "cross_module_links", source_module="governance", source_type="application", source_id=app,
            target_module="governance", target_type="process", target_id=process,
            relationship="supports", status="confirmed")
    link = _insert(db, "cross_module_links", source_module="governance", source_type="application", source_id=app,
                   target_module="aria", target_type="control", target_id=control,
                   relationship="related", status="confirmed")
    db.commit()
    shown = for_plan(db, world.users["super"], plan)
    assert [row["id"] for row in shown] == [control]
    assert shown[0]["sources"] == ["Linked to a covered business process via an application"]
    db.execute("UPDATE cross_module_links SET status='candidate' WHERE id=%s", (link,))
    db.commit()
    assert for_plan(db, world.users["super"], plan) == []


def test_large_plan_includes_controls_beyond_relationship_and_bia_page(world):
    db = world.db
    unit = world.unit["A"]
    plan = _insert(db, "bcm_plans", title="Large plan", status="approved", business_unit_id=unit)
    framework = _insert(db, "frameworks", name="Large plan controls")
    controls = []
    for number in range(201):
        control = db.execute(
            "INSERT INTO controls (framework_id,ref,name,status) VALUES (%s,%s,%s,'Implemented')",
            (framework, f"L-{number}", f"Check {number}"),
        ).lastrowid
        controls.append(control)
        db.execute(
            "INSERT INTO cross_module_links (source_module,source_type,source_id,target_module,target_type,"
            "target_id,relationship,status) VALUES ('bcm','plan',%s,'aria','control',%s,'supports','confirmed')",
            (plan, control),
        )
    process = _insert(db, "business_processes", name="Last impact analysis", business_unit_id=unit)
    extra = _insert(db, "controls", framework_id=framework, ref="L-extra", name="Last BIA control", status="Implemented")
    _insert(db, "cross_module_links", source_module="governance", source_type="process", source_id=process,
            target_module="aria", target_type="control", target_id=extra, relationship="supports", status="confirmed")
    for number in range(201):
        bia = db.execute(
            "INSERT INTO bcm_bia_records (process_name,business_process_id,business_unit_id) VALUES (%s,%s,%s)",
            (f"Impact {number}", process if number == 200 else None, unit),
        ).lastrowid
        db.execute("INSERT INTO bcm_bia_plan_links (plan_id,bia_id) VALUES (%s,%s)", (plan, bia))
    db.commit()
    shown = for_plan(db, world.users["super"], plan)
    assert {row["id"] for row in shown} == set(controls) | {extra}
    assert len(shown) == 202


def test_hidden_relationship_page_does_not_hide_later_visible_control(world):
    db = world.db
    plan = _insert(db, "bcm_plans", title="Scoped plan", status="approved", business_unit_id=world.unit["A"])
    framework = _insert(db, "frameworks", name="Scope checks")
    control = _insert(db, "controls", framework_id=framework, ref="SC-1", name="Check", status="Implemented")
    _insert(db, "cross_module_links", source_module="bcm", source_type="plan", source_id=plan,
            target_module="aria", target_type="control", target_id=control,
            relationship="supports", status="confirmed")
    for number in range(200):
        hidden = db.execute("INSERT INTO applications (name,business_unit_id,is_active) VALUES (%s,%s,1)",
                            (f"Hidden {number}", world.unit["B"])).lastrowid
        db.execute("INSERT INTO cross_module_links (source_module,source_type,source_id,target_module,target_type,"
                   "target_id,relationship,status) VALUES ('bcm','plan',%s,'governance','application',%s,'supports','confirmed')",
                   (plan, hidden))
    db.commit()
    shown = for_plan(db, world.users["owner_a"], plan)
    assert [item["id"] for item in shown] == [control]
