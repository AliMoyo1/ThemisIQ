"""
Material change signals and the connected view (plans/2026-10-governance-rework/03 sections 1 and 2).

A change to a record that others depend on is published once, to the records connected to it. Each one's owner confirms that it
needs a second look or dismisses the signal with a reason; nothing in the connected record is changed. Everything is read through
the reader's own scope: a record they cannot open is not named, counted or hinted at, and what changed is shown only to someone
who may open the record that changed.
"""
import json

import pytest

from modules.governance import change_signals as cs
from modules.governance import data_service as ds
from modules.governance import entity360
from tests.test_platform_ownership import PERSONAS, _insert, signed_in, world  # noqa: F401


def _count(world, table, where="1 = 1"):
    return world.db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def _link(world, source, target, relationship="supports", status="confirmed"):
    (sm, st, sid), (tm, tt, tid) = source, target
    return _insert(world.db, "cross_module_links", source_module=sm, source_type=st, source_id=sid, target_module=tm,
                   target_type=tt, target_id=tid, relationship=relationship, provenance="manual", status=status)


@pytest.fixture
def chain(world):
    """An application in unit A supporting a process in unit A, provided by a vendor, with a process in unit B it also
    depends on, and an AI governance reviewer in each unit."""
    unit = world.unit
    app = _insert(world.db, "applications", name="Ticket summarizer", business_unit_id=unit["A"], owner_user_id=6,
                  criticality="medium", hosting="saas", is_active=1)
    process_a = _insert(world.db, "business_processes", name="Customer support", business_unit_id=unit["A"], owner_user_id=6,
                        criticality="high", is_active=1)
    process_b = _insert(world.db, "business_processes", name="Secret restructuring", business_unit_id=unit["B"],
                        owner_user_id=7, criticality="high", is_active=1)
    vendor = _insert(world.db, "sentinel_vendors", name="Acme AI", risk_level="medium", dpa_status="signed")
    _link(world, ("governance", "application", app), ("governance", "process", process_a))
    _link(world, ("governance", "application", app), ("governance", "process", process_b), "depends_on")
    _link(world, ("governance", "application", app), ("sentinel", "vendor", vendor), "provided_by")
    return types_ns(app=app, process_a=process_a, process_b=process_b, vendor=vendor)


def types_ns(**kw):
    import types
    return types.SimpleNamespace(**kw)


def _change_app(world, chain, **changes):
    row = world.db.execute("SELECT * FROM applications WHERE id = %s", (chain.app,)).fetchone()
    data = {"name": row["name"], "description": row["description"], "application_type": row["application_type"],
            "hosting": row["hosting"], "vendor_id": row["vendor_id"], "business_unit_id": row["business_unit_id"],
            "department_id": row["department_id"], "owner_user_id": row["owner_user_id"], "criticality": row["criticality"],
            "is_active": row["is_active"], **changes}
    assert ds.update_application(chain.app, data) is True


# ── Publishing ──────────────────────────────────────────────────────────────

def test_a_material_change_is_published_once_to_each_connected_record(world, chain):
    _change_app(world, chain, criticality="critical", hosting="on_premises")
    [signal] = world.db.execute("SELECT * FROM change_signals").fetchall()
    assert (signal["source_module"], signal["source_type"], signal["source_id"], signal["change_kind"]) == (
        "governance", "application", chain.app, "application_changed")
    changes = json.loads(signal["changes"])
    assert {(c["field"], c["before"], c["after"]) for c in changes} == {
        ("criticality", "medium", "critical"), ("hosting", "saas", "on_premises")}
    targets = world.db.execute("SELECT target_module, target_type, target_id, status FROM change_signal_targets").fetchall()
    assert {(t["target_module"], t["target_type"], t["target_id"]) for t in targets} == {
        ("governance", "process", chain.process_a), ("governance", "process", chain.process_b),
        ("sentinel", "vendor", chain.vendor)}
    assert {t["status"] for t in targets} == {"open"}


def test_a_save_that_changes_nothing_that_matters_publishes_nothing_and_the_same_change_is_one_signal(world, chain):
    _change_app(world, chain, description="A new description")
    assert _count(world, "change_signals") == 0, "a description is not a material change"
    _change_app(world, chain, criticality="high")
    _change_app(world, chain, criticality="high")
    assert _count(world, "change_signals") == 1
    _change_app(world, chain, criticality="medium")
    assert _count(world, "change_signals") == 2, "a different change is a different signal"


def test_a_process_recovery_target_is_published(world, chain):
    row = world.db.execute("SELECT * FROM business_processes WHERE id = %s", (chain.process_a,)).fetchone()
    assert ds.update_business_process(chain.process_a, {
        "name": row["name"], "business_unit_id": row["business_unit_id"], "owner_user_id": row["owner_user_id"],
        "criticality": "high", "rto_hours": 2, "rpo_hours": 1, "is_active": 1}) is True
    [signal] = world.db.execute("SELECT * FROM change_signals").fetchall()
    assert signal["change_kind"] == "process_changed"
    assert {c["field"] for c in json.loads(signal["changes"])} == {"rto_hours", "rpo_hours"}
    assert [(t["target_module"], t["target_type"], t["target_id"]) for t in world.db.execute(
        "SELECT target_module, target_type, target_id FROM change_signal_targets").fetchall()] == [
        ("governance", "application", chain.app)]


def test_an_unconfirmed_connection_is_not_a_target(world, chain):
    other = _insert(world.db, "business_processes", name="Proposed only", business_unit_id=world.unit["A"], is_active=1)
    _link(world, ("governance", "application", chain.app), ("governance", "process", other), "supports", status="candidate")
    _change_app(world, chain, criticality="critical")
    ids = {t["target_id"] for t in world.db.execute("SELECT target_id FROM change_signal_targets WHERE target_type = 'process'").fetchall()}
    assert other not in ids and chain.process_a in ids


def test_a_publishing_failure_never_costs_the_edit(world, chain, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the target lookup failed")
    monkeypatch.setattr(cs, "_affected", broken)
    _change_app(world, chain, criticality="critical")
    assert world.db.execute("SELECT criticality FROM applications WHERE id = %s", (chain.app,)).fetchone()[0] == "critical"
    assert _count(world, "change_signals") == 0 and _count(world, "change_signal_targets") == 0, "the failed step left nothing"


# ── Reading, scope and deciding ─────────────────────────────────────────────

def test_a_reviewer_sees_a_signal_only_when_they_may_open_both_ends(world, chain):
    _change_app(world, chain, criticality="critical")
    seen = cs.list_open(world.db, world.users["dpo_a"])
    titles = {e["target"]["title"] for e in seen}
    assert titles == {"Customer support", "Acme AI"}
    assert "Secret restructuring" not in json.dumps(seen), "a record in another unit is not named"
    entry = next(e for e in seen if e["target"]["title"] == "Customer support")
    assert entry["source"]["title"] == "Ticket summarizer" and entry["changes"][0]["label"] == "Criticality"
    assert entry["can_review"] is True and entry["kind_label"] == "An application changed"

    # unit B may open its own process and the vendor, but not the application in unit A: nothing says that it changed
    assert cs.list_open(world.db, world.users["dpo_b"]) == []

    # the same persona does see a change to a record in its own unit, and unit A does not
    app_b = _insert(world.db, "applications", name="Unit B system", business_unit_id=world.unit["B"], owner_user_id=7,
                    criticality="low", is_active=1)
    _link(world, ("governance", "application", app_b), ("governance", "process", chain.process_b))
    assert ds.update_application(app_b, {
        "name": "Unit B system", "description": None, "application_type": None, "hosting": None, "vendor_id": None,
        "business_unit_id": world.unit["B"], "department_id": None, "owner_user_id": 7, "criticality": "high",
        "is_active": 1}) is True
    mine = cs.list_open(world.db, world.users["dpo_b"])
    assert [(e["target"]["title"], e["source"]["title"]) for e in mine] == [("Secret restructuring", "Unit B system")]
    assert "Unit B system" not in json.dumps(cs.list_open(world.db, world.users["dpo_a"]))


def test_the_owner_of_a_process_may_decide_without_the_review_right_and_staff_may_not(world, chain):
    _change_app(world, chain, criticality="critical")
    employee = world.users["employee_a"]
    assert cs.list_open(world.db, employee) == [], "staff hold no right to review and own none of these records"
    owned = _insert(world.db, "business_processes", name="Staff process", business_unit_id=world.unit["A"], owner_user_id=8,
                    is_active=1)
    _link(world, ("governance", "application", chain.app), ("governance", "process", owned))
    _change_app(world, chain, hosting="private_cloud")
    mine = cs.list_open(world.db, employee)
    assert [e["target"]["title"] for e in mine] == ["Staff process"] and mine[0]["can_review"] is True


def test_confirming_opens_a_task_and_changes_nothing_in_the_record(world, chain):
    _change_app(world, chain, criticality="critical")
    entry = next(e for e in cs.list_open(world.db, world.users["dpo_a"]) if e["target"]["title"] == "Customer support")
    before = dict(world.db.execute("SELECT * FROM business_processes WHERE id = %s", (chain.process_a,)).fetchone())
    done = cs.decide(world.db, world.users["dpo_a"], entry["id"], "confirmed", "RTO may no longer be met.")
    world.db.commit()
    assert done["status"] == "confirmed" and done["task_id"] and done["audit"][0] == "Change signal confirmed"
    task = world.db.execute("SELECT * FROM task_board WHERE id = %s", (done["task_id"],)).fetchone()
    assert task["assigned_to"] == 2 and "Customer support" in task["title"] and task["module"] == "governance"
    assert dict(world.db.execute("SELECT * FROM business_processes WHERE id = %s", (chain.process_a,)).fetchone()) == before
    assert entry["id"] not in {e["id"] for e in cs.list_open(world.db, world.users["dpo_a"])}


def test_dismissing_needs_a_reason_and_a_decision_is_final(world, chain):
    _change_app(world, chain, criticality="critical")
    entry = next(e for e in cs.list_open(world.db, world.users["dpo_a"]) if e["target"]["title"] == "Customer support")
    with pytest.raises(cs.SignalError) as short:
        cs.decide(world.db, world.users["dpo_a"], entry["id"], "dismissed", "no")
    assert short.value.status == 422
    cs.decide(world.db, world.users["dpo_a"], entry["id"], "dismissed", "Recovery targets are unaffected.")
    world.db.commit()
    with pytest.raises(cs.SignalError) as again:
        cs.decide(world.db, world.users["super"], entry["id"], "confirmed")
    assert again.value.status == 409
    with pytest.raises(cs.SignalError) as child_unit:
        cs.decide(world.db, world.users["dpo_a1"], entry["id"], "confirmed")
    assert child_unit.value.status == 404, "a person in a child unit cannot open the parent unit's records"
    row = world.db.execute("SELECT status, decided_by, reason FROM change_signal_targets WHERE id = %s", (entry["id"],)).fetchone()
    assert (row["status"], row["decided_by"], row["reason"]) == ("dismissed", 2, "Recovery targets are unaffected.")


def test_a_hidden_or_unreviewable_target_answers_as_missing(world, chain):
    _change_app(world, chain, criticality="critical")
    target = world.db.execute("SELECT id FROM change_signal_targets WHERE target_id = %s AND target_type = 'process'",
                              (chain.process_b,)).fetchone()["id"]
    # dpo_b may open the process, not the application that changed: the signal does not exist for them either
    for who in ("dpo_a", "owner_a", "employee_a", "dpo_b"):
        with pytest.raises(cs.SignalError) as hidden:
            cs.decide(world.db, world.users[who], target, "confirmed")
        assert hidden.value.status == 404, who
    visible_target = world.db.execute("SELECT id FROM change_signal_targets WHERE target_id = %s AND target_type = 'process'",
                                      (chain.process_a,)).fetchone()["id"]
    with pytest.raises(cs.SignalError) as forbidden:
        cs.decide(world.db, world.users["employee_a"], visible_target, "confirmed")
    assert forbidden.value.status == 403
    with pytest.raises(cs.SignalError) as bad:
        cs.decide(world.db, world.users["dpo_a"], visible_target, "approve")
    assert bad.value.status == 400


# ── Vendors, files and the connected view ───────────────────────────────────

def test_a_vendor_risk_change_in_one_module_tells_the_connected_records_and_the_same_company_elsewhere(world, chain):
    from modules.sentinel import data_service as sentinel
    grid_vendor = _insert(world.db, "grid_vendors", name="Acme AI", risk_level="low")
    canonical = _insert(world.db, "canonical_vendors", name="Acme AI")
    world.db.execute("UPDATE sentinel_vendors SET canonical_id = %s WHERE id = %s", (canonical, chain.vendor))
    world.db.execute("UPDATE grid_vendors SET canonical_id = %s WHERE id = %s", (canonical, grid_vendor))
    world.db.commit()
    sentinel.update_vendor(chain.vendor, {"risk_level": "high"})
    [signal] = world.db.execute("SELECT * FROM change_signals").fetchall()
    assert signal["change_kind"] == "vendor_changed" and (signal["source_module"], signal["source_id"]) == ("sentinel", chain.vendor)
    assert [(c["field"], c["before"], c["after"]) for c in json.loads(signal["changes"])] == [("risk_level", "medium", "high")]
    targets = {(t["target_module"], t["target_type"], t["target_id"]) for t in world.db.execute(
        "SELECT target_module, target_type, target_id FROM change_signal_targets").fetchall()}
    assert targets == {("governance", "application", chain.app), ("grid", "vendor", grid_vendor)}


def test_the_connected_view_groups_by_owning_module_scopes_and_marks_a_proposal(world, chain):
    proposed = _insert(world.db, "sentinel_breaches", ref_number="BR-X", title="Proposed breach link",
                       business_unit_id=world.unit["A"])
    _link(world, ("governance", "application", chain.app), ("sentinel", "breach", proposed), "affects", status="candidate")
    view = entity360.get_connected(world.db, world.users["dpo_a"], "governance", "application", chain.app)
    assert view["entity"]["title"] == "Ticket summarizer" and view["entity"]["owner"] == "owner_a"
    assert view["entity"]["business_unit"] == "Unit A" and view["entity"]["kind_label"] == "Application"
    titles = {i["title"] for s in view["connections"] for i in s["items"]}
    assert titles == {"Customer support", "Acme AI", "Proposed breach link"}, "the process in unit B is not named"
    assert "Secret restructuring" not in json.dumps(view)
    breach = next(i for s in view["connections"] for i in s["items"] if i["title"] == "Proposed breach link")
    assert breach["confirmed"] is False
    assert view["unavailable"] == [] and view["proof"]["state"] == "empty"
    assert entity360.get_connected(world.db, world.users["dpo_b"], "governance", "application", chain.app) is None, \
        "a record in another unit answers like a missing one"
    assert entity360.get_connected(world.db, world.users["dpo_a"], "governance", "application", 987654) is None
    assert entity360.get_connected(world.db, world.users["dpo_a"], "governance", "nonsense", 1) is None


def test_the_connected_view_shows_the_proof_held_and_the_signals_that_name_the_record(world, chain):
    item = _insert(world.db, "evidence_items", title="Vendor SOC 2", status="current", org_id=1, version=2)
    _insert(world.db, "evidence_links", evidence_id=item, module="governance", entity_type="application", entity_id=chain.app,
            review_status="accepted")
    old = _insert(world.db, "evidence_items", title="Old attestation", status="superseded", org_id=1, version=1)
    _insert(world.db, "evidence_links", evidence_id=old, module="governance", entity_type="application", entity_id=chain.app)
    _change_app(world, chain, criticality="critical")
    view = entity360.get_connected(world.db, world.users["dpo_a"], "governance", "application", chain.app)
    states = {i["title"]: i["state"] for i in view["proof"]["items"]}
    assert states == {"Vendor SOC 2": "Accepted", "Old attestation": "Replaced by a newer version"}
    assert view["changes"]["state"] == "ok" and view["changes"]["items"][0]["source"]["title"] == "Ticket summarizer"
    process_view = entity360.get_connected(world.db, world.users["dpo_a"], "governance", "process", chain.process_a)
    assert any(e["target"]["title"] == "Customer support" for e in process_view["changes"]["items"])


def test_my_work_carries_the_changes_and_the_evidence_waiting_for_a_reviewer(world, chain):
    from modules.launcher import my_work_service as mw
    _change_app(world, chain, criticality="critical")
    item = _insert(world.db, "evidence_items", title="Pen test report", status="current", org_id=1, uploaded_by=8)
    claim = _insert(world.db, "erm_enterprise_risks", title="Unpatched systems", business_unit_id=world.unit["A"])
    _insert(world.db, "evidence_links", evidence_id=item, module="erm", entity_type="risk", entity_id=claim, linked_by=8)
    work = mw.get_my_work(world.users["dpo_a"])
    titles = [i["title"] for s in work["sections"].values() for i in s]
    assert any(t.startswith("Look again at Customer support") for t in titles)
    assert "Review evidence: Pen test report for Unpatched systems" in titles
    states = {s["source"]: s["state"] for s in work["source_states"]}
    assert states["change_reviews"] == "available" and states["evidence_reviews"] == "available"
    assert not any("Secret restructuring" in t for t in titles)
    staff = mw.get_my_work(world.users["employee_a"])
    assert not any(i["source_module"] in ("governance", "evidence") for s in staff["sections"].values() for i in s)


# ── Every watched kind ──────────────────────────────────────────────────────

def test_every_watched_record_names_a_table_and_each_field_exists(test_db):
    from modules.governance.entity_scope import is_linkable, kind_table
    for key, (label, fields) in cs.WATCHED.items():
        assert is_linkable(key), key
        columns = {row[1] for row in test_db.execute(f"PRAGMA table_info({kind_table(key)})").fetchall()}
        assert set(fields) <= columns, (key, sorted(set(fields) - columns))
        if key in cs.VENDOR_KEYS:
            assert "canonical_id" in columns, key
    assert {key[0] for key in cs.VENDOR_KEYS} == {"sentinel", "grid", "bcm"}


def _watched(world, name):
    """(key, record id, the real update that changes one watched field, that field) for a record in unit A."""
    from modules.bcm import data_service as bcm
    from modules.erm import data_service as erm
    from modules.grid import data_service as grid
    from modules.orm import data_service as orm
    from modules.sentinel import data_service as sentinel
    db, unit = world.db, world.unit["A"]
    if name == "ropa":
        rid = _insert(db, "sentinel_ropa", ref_number="RP-1", processing_name="Payroll", business_unit_id=unit, risk_level="low")
        return ("sentinel", "ropa"), rid, lambda: sentinel.update_ropa(rid, {"risk_level": "high"}), "risk_level"
    if name == "dpia":
        rid = _insert(db, "sentinel_dpias", ref_number="DP-1", title="Payroll DPIA", business_unit_id=unit, status="draft")
        return ("sentinel", "dpia"), rid, lambda: sentinel.update_dpia(rid, {"status": "approved"}), "status"
    if name == "breach":
        rid = world.rec[("breach", "A")]
        return ("sentinel", "breach"), rid, lambda: sentinel.update_breach(rid, {"severity": "critical"}), "severity"
    if name == "dsr":
        rid = _insert(db, "sentinel_dsr", ref_number="DSR-1", requester_name="Jane Subject", business_unit_id=unit,
                      status="received")
        return ("sentinel", "dsr"), rid, lambda: sentinel.update_dsr(rid, {"status": "in_progress"}), "status"
    if name == "grid_audit":
        rid = world.rec[("audit", "A")]
        return ("grid", "audit"), rid, lambda: grid.update_audit(rid, {"status": "In Progress"}), "status"
    if name == "grid_control":
        rid = _insert(db, "grid_controls", audit_id=world.rec[("audit", "A")], name="Access review", risk_level="low")
        return ("grid", "control"), rid, lambda: grid.update_control(rid, {"risk_level": "high"}), "risk_level"
    if name == "grid_nc":
        rid = world.rec[("nc", "A")]
        return ("grid", "nc"), rid, lambda: grid.update_nc(rid, {"severity": "major"}), "severity"
    if name == "bcm_plan":
        rid = _insert(db, "bcm_plans", title="Site recovery", business_unit_id=unit, status="draft")
        return ("bcm", "plan"), rid, lambda: bcm.update_plan(rid, {"status": "approved"}), "status"
    if name == "bcm_bia":
        rid = _insert(db, "bcm_bia_records", process_name="Order entry", business_unit_id=unit, rto_hours=24)
        return ("bcm", "bia"), rid, lambda: bcm.update_bia(rid, {"rto_hours": 4}), "rto_hours"
    if name == "bcm_incident":
        rid = _insert(db, "bcm_incidents", title="Outage", business_unit_id=unit, severity="low")
        return ("bcm", "incident"), rid, lambda: bcm.update_incident(rid, {"severity": "critical"}), "severity"
    if name == "bcm_exercise":
        rid = _insert(db, "bcm_exercises", title="Tabletop", business_unit_id=unit, status="scheduled")
        return ("bcm", "exercise"), rid, lambda: bcm.update_exercise(rid, {"status": "completed"}), "status"
    if name == "bcm_risk":
        rid = _insert(db, "bcm_risks", title="Single supplier", treatment="accept")
        return ("bcm", "risk"), rid, lambda: bcm.update_risk(rid, {"treatment": "mitigate"}), "treatment"
    if name == "erm_risk":
        rid = world.rec[("erm", "A")]
        return ("erm", "risk"), rid, lambda: erm.update_enterprise_risk(rid, {"treatment": "accept"}), "treatment"
    if name == "orm_event":
        rid = world.rec[("event", "A")]
        return ("orm", "event"), rid, lambda: orm.update_event(rid, {"severity": "high"}), "severity"
    if name == "orm_kri":
        rid = _insert(db, "orm_kris", name="Phishing click rate", status="green")
        return ("orm", "kri"), rid, lambda: orm.update_kri(rid, {"status": "red"}), "status"
    if name == "data_asset":
        rid = _insert(db, "data_assets", name="Customer table", business_unit_id=unit, classification="internal", is_active=1)
        row = db.execute("SELECT * FROM data_assets WHERE id = %s", (rid,)).fetchone()
        data = {k: row[k] for k in ("name", "description", "category", "classification", "business_unit_id", "application_id",
                                    "owner_user_id", "location", "contains_pii", "contains_phi", "contains_financial",
                                    "contains_ip", "is_active")}
        return (("governance", "data_asset"), rid,
                lambda: ds.update_data_asset(rid, {**data, "classification": "restricted"}), "classification")
    raise AssertionError(name)


WATCHED_CASES = {"ropa": ("sentinel", "ropa"), "dpia": ("sentinel", "dpia"), "breach": ("sentinel", "breach"),
                 "dsr": ("sentinel", "dsr"), "grid_audit": ("grid", "audit"), "grid_control": ("grid", "control"),
                 "grid_nc": ("grid", "nc"), "bcm_plan": ("bcm", "plan"), "bcm_bia": ("bcm", "bia"),
                 "bcm_incident": ("bcm", "incident"), "bcm_exercise": ("bcm", "exercise"), "bcm_risk": ("bcm", "risk"),
                 "erm_risk": ("erm", "risk"), "orm_event": ("orm", "event"), "orm_kri": ("orm", "kri"),
                 "data_asset": ("governance", "data_asset")}


def test_every_watched_kind_is_exercised_here_or_has_its_own_test():
    # application, process and the vendors are tested above, the control and the policy version further down
    elsewhere = {("governance", "application"), ("governance", "process"), ("aria", "control"),
                 ("aria", "document"), ("aria", "risk"), ("aria", "framework")} | set(cs.VENDOR_KEYS)
    assert set(cs.WATCHED) == set(WATCHED_CASES.values()) | elsewhere


def test_framework_control_count_change_reaches_connected_application(world, chain):
    framework_id = _insert(world.db, "frameworks", name="Signal test framework", total_controls=0)
    _link(world, ("aria", "framework", framework_id),
          ("governance", "application", chain.app), "supports")
    world.db.execute("UPDATE frameworks SET total_controls = 2 WHERE id = %s", (framework_id,))
    cs.publish_record_change(world.db, ("aria", "framework"), framework_id,
                             {"total_controls": 0}, {"total_controls": 2},
                             kind="framework_controls_imported")
    [signal] = world.db.execute("SELECT * FROM change_signals").fetchall()
    assert (signal["source_module"], signal["source_type"], signal["source_id"]) == (
        "aria", "framework", framework_id)
    assert signal["change_kind"] == "framework_controls_imported"
    assert [change["field"] for change in json.loads(signal["changes"])] == ["total_controls"]
    [target] = world.db.execute(
        "SELECT target_module,target_type,target_id FROM change_signal_targets").fetchall()
    assert (target["target_module"], target["target_type"], target["target_id"]) == (
        "governance", "application", chain.app)


@pytest.mark.parametrize("name", sorted(WATCHED_CASES))
def test_a_change_in_each_watched_module_reaches_the_connected_application(world, chain, name):
    key, record, update, field = _watched(world, name)
    assert key == WATCHED_CASES[name]
    _link(world, ("governance", "application", chain.app), (key[0], key[1], record), "affects")
    update()
    [signal] = world.db.execute("SELECT * FROM change_signals").fetchall()
    assert (signal["source_module"], signal["source_type"], signal["source_id"]) == (key[0], key[1], record)
    assert signal["change_kind"] == "record_changed"
    assert [c["field"] for c in json.loads(signal["changes"])] == [field]
    targets = [(t["target_module"], t["target_type"], t["target_id"]) for t in world.db.execute(
        "SELECT target_module, target_type, target_id FROM change_signal_targets").fetchall()]
    assert targets == [("governance", "application", chain.app)]
    shown = next(e for e in cs.list_open(world.db, world.users["super"]) if e["target"]["entity_id"] == chain.app)
    assert shown["kind_label"] == f"{cs.WATCHED[key][0]} changed" and shown["source"]["entity_id"] == record


def test_an_update_that_changes_nothing_that_matters_publishes_nothing_and_a_repeat_is_one_signal(world, chain):
    from modules.sentinel import data_service as sentinel
    rid = world.rec[("breach", "A")]
    _link(world, ("governance", "application", chain.app), ("sentinel", "breach", rid), "affects")
    sentinel.update_breach(rid, {"title": "Renamed breach"})
    assert _count(world, "change_signals") == 0
    sentinel.update_breach(rid, {"severity": "high"})
    sentinel.update_breach(rid, {"severity": "high"})
    assert _count(world, "change_signals") == 1, "the same value saved again is not a change"


def test_a_persons_name_is_never_stored_with_a_signal(world, chain):
    key, record, update, _ = _watched(world, "dsr")
    _link(world, ("governance", "application", chain.app), (key[0], key[1], record), "affects")
    update()
    assert _count(world, "change_signals") == 1
    stored = json.dumps([dict(r) for r in world.db.execute("SELECT * FROM change_signals").fetchall()], default=str)
    assert "Jane Subject" not in stored
    columns = {row[1] for row in world.db.execute("PRAGMA table_info(change_signals)").fetchall()}
    assert "source_title" not in columns


def test_confirming_names_the_record_that_changed_in_the_task(world, chain):
    _change_app(world, chain, criticality="critical")
    own = next(e for e in cs.list_open(world.db, world.users["dpo_a"]) if e["target"]["title"] == "Customer support")
    done = cs.decide(world.db, world.users["dpo_a"], own["id"], "confirmed")
    world.db.commit()
    assert world.db.execute("SELECT title FROM task_board WHERE id = %s", (done["task_id"],)).fetchone()[0] == \
        "Reassess Customer support after a change to Ticket summarizer"
    assert "Secret restructuring" not in json.dumps(
        [dict(r) for r in world.db.execute("SELECT * FROM task_board").fetchall()], default=str)


def test_a_control_update_through_aria_tells_the_records_connected_to_it(world, chain):
    from modules.aria import routes as aria
    from tests.test_platform_ownership import _call, _request
    framework = _insert(world.db, "frameworks", name="ISO 27001")
    control = _insert(world.db, "controls", framework_id=framework, ref="A.5.1", name="Policies for security",
                      status="Not Started")
    _link(world, ("governance", "application", chain.app), ("aria", "control", control), "governed_by")
    update = dict(priority=None, owner=None, target_date=None, review_date=None, document_title=None, version=None,
                  evidence_ref=None)
    code, body = _call(aria.update_control(_request(world.users["super"]), control, status="Implemented", notes=None, **update))
    assert code == 200 and body == {"ok": True}
    [signal] = world.db.execute("SELECT * FROM change_signals").fetchall()
    assert [(c["field"], c["before"], c["after"]) for c in json.loads(signal["changes"])] == [
        ("status", "Not Started", "Implemented")]
    assert [(t["target_type"], t["target_id"]) for t in world.db.execute(
        "SELECT target_type, target_id FROM change_signal_targets").fetchall()] == [("application", chain.app)]
    _call(aria.update_control(_request(world.users["super"]), control, status="Implemented", notes="A note", **update))
    assert _count(world, "change_signals") == 1, "a note is not a material change"


# ── An AI use is decided, revoked or changed ────────────────────────────────

def test_a_decision_a_revocation_and_a_changed_use_tell_the_connected_records(world, chain):
    from modules.ai_governance import handlers
    decision = _insert(world.db, "ai_use_decisions", application_id=chain.app, status="approved", requested_by=6,
                       business_unit_id=world.unit["A"])
    handlers.tell_connected_records_about_a_decision(payload={"decision_id": decision}, user_id=2, org_id=1)
    [signal] = world.db.execute("SELECT * FROM change_signals").fetchall()
    assert (signal["change_kind"], signal["source_module"], signal["source_type"], signal["source_id"]) == (
        "ai_use_decided", "governance", "application", chain.app)
    assert [(c["before"], c["after"]) for c in json.loads(signal["changes"])] == [("No decision", "Approved")]
    assert {(t["target_module"], t["target_type"]) for t in world.db.execute(
        "SELECT target_module, target_type FROM change_signal_targets").fetchall()} == {
        ("governance", "process"), ("sentinel", "vendor")}

    handlers.tell_connected_records_about_a_decision(payload={"decision_id": decision}, user_id=2, org_id=1)
    assert _count(world, "change_signals") == 1, "the same decision delivered twice is one signal"

    returned = _insert(world.db, "ai_use_decisions", application_id=chain.app, status="returned", requested_by=6)
    handlers.tell_connected_records_about_a_decision(payload={"decision_id": returned}, user_id=2, org_id=1)
    assert _count(world, "change_signals") == 1, "a return for changes is not a standing outcome"

    handlers.tell_connected_records_about_a_changed_use(payload={"application_id": chain.app}, user_id=2, org_id=1)
    world.db.execute("UPDATE ai_use_decisions SET revoked_at = '2026-10-14 10:00:00', revoked_reason = 'Provider changed' "
                     "WHERE id = %s", (decision,))
    world.db.commit()
    handlers.tell_connected_records_about_a_revocation(payload={"decision_id": decision}, user_id=2, org_id=1)
    handlers.tell_connected_records_about_a_changed_use(payload={"application_id": chain.app}, user_id=2, org_id=1)
    assert _count(world, "change_signals") == 3, "with the approval revoked there is no approval left to cover a change"
    kinds = {r["change_kind"] for r in world.db.execute("SELECT change_kind FROM change_signals").fetchall()}
    assert kinds == {"ai_use_decided", "ai_use_revoked", "ai_use_changed"}

    seen = cs.list_open(world.db, world.users["dpo_a"])
    labels = {e["kind_label"] for e in seen}
    assert labels == {"A decision was made on an AI use", "The approval of an AI use was revoked",
                      "An AI use changed in a way its approval covered"}
    assert "Secret restructuring" not in json.dumps(seen)


# ── Isolation and input ─────────────────────────────────────────────────────

def test_a_signal_of_another_organization_is_neither_listed_nor_decidable(world, chain):
    _change_app(world, chain, criticality="critical")
    world.db.execute("UPDATE change_signals SET org_id = 99")
    world.db.commit()
    dpo = world.users["dpo_a"]
    assert cs.list_open(world.db, dpo) == []
    assert cs.for_entity(world.db, dpo, ("governance", "process"), chain.process_a) == []
    some = world.db.execute("SELECT id FROM change_signal_targets").fetchone()["id"]
    with pytest.raises(cs.SignalError) as other_org:
        cs.decide(world.db, dpo, some, "confirmed")
    assert other_org.value.status == 404
    operator = {**world.users["super"], "org_id": None}
    assert cs.list_open(world.db, operator) != [], "a platform operator, who belongs to no organization, is not filtered by one"


def test_what_a_person_sends_is_checked(world, chain):
    _change_app(world, chain, criticality="critical")
    entry = next(e for e in cs.list_open(world.db, world.users["dpo_a"]) if e["target"]["title"] == "Customer support")
    dpo = world.users["dpo_a"]
    for bad_reason in (["a list"], {"a": "dict"}, 12):
        with pytest.raises(cs.SignalError) as wrong:
            cs.decide(world.db, dpo, entry["id"], "dismissed", bad_reason)
        assert wrong.value.status == 422
    with pytest.raises(cs.SignalError) as long:
        cs.decide(world.db, dpo, entry["id"], "dismissed", "x" * (cs.REASON_MAX + 1))
    assert long.value.status == 422
    with pytest.raises(cs.SignalError) as unknown:
        cs.decide(world.db, dpo, entry["id"], None)
    assert unknown.value.status == 400
    with pytest.raises(cs.SignalError) as missing:
        cs.decide(world.db, dpo, 987654, "confirmed")
    assert missing.value.status == 404
    still = world.db.execute("SELECT status FROM change_signal_targets WHERE id = %s", (entry["id"],)).fetchone()[0]
    assert still == "open", "nothing was decided by any of those"


def test_the_decorator_finds_the_record_whether_it_is_passed_by_position_or_by_name(world, chain):
    row = world.db.execute("SELECT * FROM applications WHERE id = %s", (chain.app,)).fetchone()
    asset = _insert(world.db, "data_assets", name="Ticket text", business_unit_id=world.unit["A"], classification="internal",
                    is_active=1)
    _link(world, ("governance", "data_asset", asset), ("governance", "application", chain.app), "used_by")
    data = {"name": "Ticket text", "description": None, "category": None, "classification": "restricted",
            "business_unit_id": world.unit["A"], "application_id": None, "owner_user_id": None, "location": None,
            "contains_pii": 0, "contains_phi": 0, "contains_financial": 0, "contains_ip": 0, "is_active": 1}
    assert ds.update_data_asset(asset_id=asset, data=data) is True
    assert _count(world, "change_signals") == 1
    assert row["id"] == chain.app


def test_a_long_value_is_stored_in_a_short_form_and_still_counts_as_a_change(world, chain):
    from modules.sentinel import data_service as sentinel
    rid = world.rec[("breach", "A")]
    _link(world, ("governance", "application", chain.app), ("sentinel", "breach", rid), "affects")
    sentinel.update_breach(rid, {"status": "a" * 500})
    [signal] = world.db.execute("SELECT * FROM change_signals").fetchall()
    [change] = json.loads(signal["changes"])
    assert len(change["after"]) == cs.BRIEF_MAX and change["after"].endswith("...")
    sentinel.update_breach(rid, {"status": "a" * 499 + "b"})
    assert _count(world, "change_signals") == 2, "a difference after the stored part is still a change"


def test_a_change_nothing_is_connected_to_leaves_no_row(world):
    lonely = _insert(world.db, "applications", name="Lonely system", business_unit_id=world.unit["A"], criticality="low",
                     hosting="saas", is_active=1)
    assert ds.update_application(lonely, {
        "name": "Lonely system", "description": None, "application_type": None, "hosting": "saas", "vendor_id": None,
        "business_unit_id": world.unit["A"], "department_id": None, "owner_user_id": None, "criticality": "high",
        "is_active": 1}) is True
    assert world.db.execute("SELECT criticality FROM applications WHERE id = %s", (lonely,)).fetchone()[0] == "high"
    assert _count(world, "change_signals") == 0 and _count(world, "change_signal_targets") == 0
