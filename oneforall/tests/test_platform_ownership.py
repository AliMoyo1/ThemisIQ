"""Who owns a platform risk, an SLA clock or a workflow instance, and who may therefore see it.

The three tables used to have no business unit, so the dashboards and the legacy risk register had to hide
them from everyone except the super administrator. Ownership is now stored on the row:

  * the unit of the record the row is about, when that record is a registered kind the actor can open
    (a risk about a unit B breach belongs to unit B; a record that is organization wide stays organization wide);
  * otherwise the unit of the person who created it;
  * otherwise none, which in this platform means organization wide.

A user can never place a row in a unit they cannot see: naming a record they cannot open gives them their own
unit, not that record's. The expectations are written out by hand, and every "cannot see" assertion has a
positive twin (the same persona does see its own rows), so an empty answer cannot pass for isolation.
"""
import asyncio
import json
import types

import pytest

import core.middleware as middleware
from core import rbac
from modules.governance.entity_scope import owner_unit, record_unit

ORG = 1

# persona -> (role, unit tag)
PERSONAS = {
    "super": (rbac.SUPER_ADMIN, None),
    "dpo_a": (rbac.DPO, "A"),
    "dpo_a1": (rbac.DPO, "A1"),
    "dpo_b": (rbac.DPO, "B"),
    "dpo_no_unit": (rbac.DPO, None),
    "owner_a": (rbac.RISK_OWNER, "A"),
    "owner_b": (rbac.RISK_OWNER, "B"),
    "employee_a": (rbac.EMPLOYEE, "A"),
}


def _insert(db, table, **cols):
    cur = db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(cols.values()),
    )
    db.commit()
    return cur.lastrowid


def _request(user, query=None, payload=None):
    request = types.SimpleNamespace(
        state=types.SimpleNamespace(user=user),
        url=types.SimpleNamespace(path="/api/test"),
        query_params=query or {},
    )
    if payload is not None:
        async def _json():
            return payload

        request.json = _json
    return request


def _call(coro):
    response = asyncio.run(coro)
    return response.status_code, json.loads(response.body)


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)


@pytest.fixture
def world(test_db):
    """One organization, units A, A1 (child of A) and B, a few records in each, and the personas."""
    db = test_db
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,'org','org')", (ORG,))
    db.commit()
    unit = {"org": None}
    unit["A"] = _insert(db, "business_units", name="Unit A", is_active=1)
    unit["A1"] = _insert(db, "business_units", name="Unit A1", is_active=1, parent_id=unit["A"])
    unit["B"] = _insert(db, "business_units", name="Unit B", is_active=1)

    rec = {}
    for tag in ("A", "A1", "B", "org"):
        rec[("breach", tag)] = _insert(db, "sentinel_breaches", ref_number=f"BR-{tag}",
                                       title=f"needle breach {tag}", business_unit_id=unit[tag])
    audit_a = _insert(db, "grid_audits", name="Audit A", business_unit_id=unit["A"])
    rec[("audit", "A")] = audit_a
    rec[("nc", "A")] = _insert(db, "grid_non_conformances", audit_id=audit_a, title="NC in unit A")
    rec[("incident", "B")] = _insert(db, "bcm_incidents", title="Incident B", business_unit_id=unit["B"])
    rec[("event", "A")] = _insert(db, "orm_events", title="Event A", business_unit_id=unit["A"])
    rec[("erm", "A")] = _insert(db, "erm_enterprise_risks", title="ERM risk A", business_unit_id=unit["A"])
    rec[("document", "A")] = _insert(db, "aria_documents", doc_id="DOC-A", title="Policy A", framework="ISO 27001",
                                     org_id=ORG, business_unit_id=unit["A"], policy_workflow_managed=0)

    users = {}
    for i, (name, (role, tag)) in enumerate(PERSONAS.items(), start=1):
        unit_id = unit.get(tag) if tag else None
        users[name] = {"id": i, "username": name, "org_id": ORG, "business_unit_id": unit_id,
                       "is_super_admin": 1 if role == rbac.SUPER_ADMIN else 0, "roles": [role]}
        _insert(db, "users", id=i, username=name, email=f"{name}@example.test", full_name=name,
                password_hash="x", org_id=ORG, business_unit_id=unit_id)
    return types.SimpleNamespace(db=db, unit=unit, rec=rec, users=users)


# ── The columns exist ───────────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["risk_register", "sla_instances", "workflow_instances"])
def test_the_three_tables_carry_a_business_unit(test_db, table):
    columns = {row[1] for row in test_db.execute(f"PRAGMA table_info({table})").fetchall()}
    assert "business_unit_id" in columns


# ── The registry is what lets one rule serve every surface ─────────────────

def test_every_kind_with_a_unit_names_its_table_and_the_column_exists(test_db):
    """record_unit reads the unit from the table the registry names, so a kind added without one, or with a
    misspelt column, would silently stop placing rows."""
    from modules.governance.entity_scope import _KINDS
    for key, kind in _KINDS.items():
        if kind.bu or kind.via_audit:
            assert kind.table, key
            columns = {row[1] for row in test_db.execute(f"PRAGMA table_info({kind.table})").fetchall()}
            assert (kind.bu or "audit_id") in columns, key
        else:
            assert not kind.table, key


def test_the_dashboard_table_map_agrees_with_the_registry():
    from modules.governance.entity_scope import _KINDS
    from modules.launcher.scoped_metrics import TABLE_KINDS
    for table, key in TABLE_KINDS.items():
        assert _KINDS[key].table in ("", table), (table, key)


# ── record_unit: the unit of the record a row is about ──────────────────────

def test_a_record_gives_its_own_unit_and_an_organization_wide_record_gives_none(world):
    db, unit, rec = world.db, world.unit, world.rec
    assert record_unit(db, "sentinel", "breach", rec[("breach", "A")]) == (True, unit["A"])
    assert record_unit(db, "sentinel", "breach", rec[("breach", "B")]) == (True, unit["B"])
    assert record_unit(db, "sentinel", "breach", rec[("breach", "org")]) == (True, None)


def test_a_non_conformance_follows_its_audit_and_the_other_registered_kinds_resolve(world):
    db, unit, rec = world.db, world.unit, world.rec
    assert record_unit(db, "grid", "nc", rec[("nc", "A")]) == (True, unit["A"])
    assert record_unit(db, "bcm", "incident", rec[("incident", "B")]) == (True, unit["B"])
    assert record_unit(db, "orm", "event", rec[("event", "A")]) == (True, unit["A"])
    assert record_unit(db, "erm", "risk", rec[("erm", "A")]) == (True, unit["A"])
    assert record_unit(db, "aria", "document", rec[("document", "A")]) == (True, unit["A"])


def test_the_names_callers_actually_use_resolve_to_the_same_kinds(world):
    """Event handlers say non_conformance and enterprise_risk, the form says policy; case and padding vary."""
    db, unit, rec = world.db, world.unit, world.rec
    assert record_unit(db, "grid", "non_conformance", rec[("nc", "A")]) == (True, unit["A"])
    assert record_unit(db, "erm", "enterprise_risk", rec[("erm", "A")]) == (True, unit["A"])
    assert record_unit(db, "aria", "policy", rec[("document", "A")]) == (True, unit["A"])
    assert record_unit(db, " Sentinel ", " BREACH ", str(rec[("breach", "A")])) == (True, unit["A"])


@pytest.mark.parametrize("module, kind, ident", [
    ("sentinel", "breach", 987654),       # no such record
    ("sentinel", "breach", None),         # no id at all
    ("sentinel", "breach", "not a number"),
    ("sentinel", "breach", 0),
    ("aria", "risk", 1),                  # a name nothing registers
    ("", "", None),                       # the form's "None" option
    ("bcm", "risk", 1),
])
def test_a_reference_that_names_no_registered_record_is_unknown_not_an_error(world, module, kind, ident):
    assert record_unit(world.db, module, kind, ident) == (False, None)


def test_a_user_who_cannot_open_the_record_gets_no_answer_about_it(world):
    """Unit B's breach: invisible to a unit A DPO and to an employee, visible to its own unit and the admin."""
    db, rec = world.db, world.rec
    breach_b = rec[("breach", "B")]
    args = ("sentinel", "breach", breach_b)
    assert record_unit(db, *args, user=world.users["dpo_a"]) == (False, None)
    assert record_unit(db, *args, user=world.users["employee_a"]) == (False, None)
    assert record_unit(db, *args, user=world.users["dpo_no_unit"]) == (False, None)
    assert record_unit(db, *args, user=world.users["dpo_b"]) == (True, world.unit["B"])
    assert record_unit(db, *args, user=world.users["super"]) == (True, world.unit["B"])


def test_a_parent_unit_opens_a_child_record_but_not_the_other_way_round(world):
    db, unit, rec = world.db, world.unit, world.rec
    a1 = ("sentinel", "breach", rec[("breach", "A1")])
    a = ("sentinel", "breach", rec[("breach", "A")])
    assert record_unit(db, *a1, user=world.users["dpo_a"]) == (True, unit["A1"])
    assert record_unit(db, *a, user=world.users["dpo_a1"]) == (False, None)


# ── owner_unit: record, else creator, else none ─────────────────────────────

def test_the_record_decides_even_when_the_actor_belongs_elsewhere(world):
    """The super administrator has no unit, yet a risk about a unit B breach is unit B's."""
    breach_b = world.rec[("breach", "B")]
    assert owner_unit(world.db, "sentinel", "breach", breach_b, user=world.users["super"]) == world.unit["B"]
    assert owner_unit(world.db, "sentinel", "breach", breach_b, user_id=world.users["super"]["id"]) == world.unit["B"]


def test_an_organization_wide_record_stays_organization_wide_for_a_unit_actor(world):
    org_wide = world.rec[("breach", "org")]
    assert owner_unit(world.db, "sentinel", "breach", org_wide, user=world.users["dpo_a"]) is None


def test_an_unknown_reference_falls_back_to_the_creators_unit(world):
    dpo_a = world.users["dpo_a"]
    assert owner_unit(world.db, "aria", "risk", 5, user=dpo_a) == world.unit["A"]
    assert owner_unit(world.db, "", "", None, user=dpo_a) == world.unit["A"]
    assert owner_unit(world.db, "aria", "risk", 5, user_id=dpo_a["id"]) == world.unit["A"]


def test_with_no_record_and_no_creator_unit_the_row_is_organization_wide(world):
    assert owner_unit(world.db, "aria", "risk", 5, user=world.users["super"]) is None
    assert owner_unit(world.db, "aria", "risk", 5, user=world.users["dpo_no_unit"]) is None
    assert owner_unit(world.db, "aria", "risk", 5, user_id=None) is None
    assert owner_unit(world.db, "aria", "risk", 5, user_id=424242) is None  # a user that no longer exists


def test_naming_a_record_you_cannot_open_gives_you_your_own_unit_never_that_records(world):
    """Nobody can plant a row on another unit's dashboard by pointing at its record."""
    breach_b = world.rec[("breach", "B")]
    for name in ("dpo_a", "dpo_a1", "employee_a"):
        user = world.users[name]
        assert owner_unit(world.db, "sentinel", "breach", breach_b, user=user) == user["business_unit_id"], name
    assert owner_unit(world.db, "sentinel", "breach", breach_b, user=world.users["dpo_no_unit"]) is None
    assert owner_unit(world.db, "sentinel", "breach", breach_b, user=world.users["dpo_b"]) == world.unit["B"]


# ── Every writer records the owner ──────────────────────────────────────────

def _unit_of(db, table, row_id):
    return db.execute(f"SELECT business_unit_id FROM {table} WHERE id = %s", (row_id,)).fetchone()[0]


def _risk_about(world, module, kind, ident, user):
    from core.event_handlers import _insert_risk
    rid = _insert_risk(world.db, title="Auto risk", description="d", source_module=module, entity_type=kind,
                       entity_id=ident, category="compliance", likelihood=3, impact=3, risk_level="medium",
                       user_id=user["id"])
    assert rid, "the risk must be created"
    world.db.commit()
    return rid


def test_an_automatic_risk_belongs_to_the_unit_of_the_record_it_came_from(world):
    """Even when a super administrator (no unit) triggered it, and even when the actor is in another unit."""
    rec = world.rec
    rid = _risk_about(world, "sentinel", "breach", rec[("breach", "B")], world.users["super"])
    assert _unit_of(world.db, "risk_register", rid) == world.unit["B"]
    rid = _risk_about(world, "grid", "non_conformance", rec[("nc", "A")], world.users["dpo_b"])
    assert _unit_of(world.db, "risk_register", rid) == world.unit["A"]
    rid = _risk_about(world, "sentinel", "breach", rec[("breach", "org")], world.users["dpo_a"])
    assert _unit_of(world.db, "risk_register", rid) is None


def test_an_automatic_risk_about_something_unplaceable_belongs_to_whoever_triggered_it(world):
    rid = _risk_about(world, "aria", "risk", 5, world.users["dpo_a"])
    assert _unit_of(world.db, "risk_register", rid) == world.unit["A"]
    rid = _risk_about(world, "aria", "risk", 5, world.users["super"])
    assert _unit_of(world.db, "risk_register", rid) is None


def _definition(world, **extra):
    return _insert(world.db, "workflow_definitions", name="Approval", steps_json="[]", is_active=1,
                   created_by=world.users["super"]["id"], **extra)


def _start_workflow(world, user, **entity):
    from modules.launcher import routes_workflows as wf
    payload = {"definition_id": _definition(world), **entity}
    if user["is_super_admin"]:
        payload["org_id"] = ORG
    status, body = _call(wf.api_workflow_instance_start(_request(user, payload=payload)))
    assert status == 201, body
    return body["id"]


def test_a_started_workflow_belongs_to_the_unit_of_the_record_the_starter_can_open(world):
    rec, unit = world.rec, world.unit
    dpo_a = world.users["dpo_a"]
    child = _start_workflow(world, dpo_a, entity_module="sentinel", entity_type="breach",
                            entity_id=rec[("breach", "A1")])
    assert _unit_of(world.db, "workflow_instances", child) == unit["A1"]       # the record's, not the starter's
    org_wide = _start_workflow(world, dpo_a, entity_module="sentinel", entity_type="breach",
                               entity_id=rec[("breach", "org")])
    assert _unit_of(world.db, "workflow_instances", org_wide) is None
    admin = _start_workflow(world, world.users["super"], entity_module="sentinel", entity_type="breach",
                            entity_id=rec[("breach", "B")])
    assert _unit_of(world.db, "workflow_instances", admin) == unit["B"]


def test_a_workflow_started_on_a_record_the_starter_cannot_open_is_the_starters_own(world):
    """The reference is kept as typed, but the row cannot land on unit B's dashboard."""
    started = _start_workflow(world, world.users["dpo_a"], entity_module="sentinel", entity_type="breach",
                              entity_id=world.rec[("breach", "B")])
    assert _unit_of(world.db, "workflow_instances", started) == world.unit["A"]
    kept = world.db.execute("SELECT entity_module, entity_type, entity_id FROM workflow_instances WHERE id = %s",
                            (started,)).fetchone()
    assert tuple(kept) == ("sentinel", "breach", world.rec[("breach", "B")])


def test_a_workflow_with_a_free_text_reference_belongs_to_its_starter(world):
    for entity in ({}, {"entity_module": "grid", "entity_type": "finding", "entity_id": 77},
                   {"entity_module": "aria", "entity_type": "policy", "entity_id": 99999}):
        started = _start_workflow(world, world.users["dpo_a"], **entity)
        assert _unit_of(world.db, "workflow_instances", started) == world.unit["A"], entity
    assert _unit_of(world.db, "workflow_instances", _start_workflow(world, world.users["super"])) is None


def _start_sla(world, user, **entity):
    from modules.launcher import routes_workflows as wf
    definition = _insert(world.db, "sla_definitions", name="Breach SLA", module="sentinel", entity_type="breach",
                         response_hours=4, resolution_hours=24, escalation_hours=12, is_active=1)
    payload = {"definition_id": definition, **entity}
    if user["is_super_admin"]:
        payload["org_id"] = ORG
    status, body = _call(wf.api_sla_instance_start(_request(user, payload=payload)))
    assert status == 201, body
    return body["id"]


def test_an_sla_clock_belongs_to_the_unit_of_its_record_or_else_its_starter(world):
    rec, unit = world.rec, world.unit
    dpo_a = world.users["dpo_a"]
    seen = _start_sla(world, dpo_a, entity_module="sentinel", entity_type="breach", entity_id=rec[("breach", "A1")])
    assert _unit_of(world.db, "sla_instances", seen) == unit["A1"]
    hidden = _start_sla(world, dpo_a, entity_module="sentinel", entity_type="breach", entity_id=rec[("breach", "B")])
    assert _unit_of(world.db, "sla_instances", hidden) == unit["A"]
    free_text = _start_sla(world, dpo_a, entity_module="bcm", entity_type="whatever", entity_id=3)
    assert _unit_of(world.db, "sla_instances", free_text) == unit["A"]
    admin = _start_sla(world, world.users["super"], entity_module="bcm", entity_type="incident",
                       entity_id=rec[("incident", "B")])
    assert _unit_of(world.db, "sla_instances", admin) == unit["B"]


def test_a_workflow_started_by_an_event_belongs_to_the_unit_of_the_event_record(world):
    from core.event_handlers import _auto_trigger_workflows
    _insert(world.db, "workflow_definitions", name="Incident flow", steps_json="[]", is_active=1,
            trigger_module="bcm", trigger_action="incident.declared", created_by=world.users["super"]["id"])
    _auto_trigger_workflows(world.db, "bcm.incident.declared", "bcm", "incident", world.rec[("incident", "B")],
                            world.users["dpo_a"]["id"], None, ORG)
    row = world.db.execute("SELECT business_unit_id, started_by FROM workflow_instances").fetchone()
    assert row[0] == world.unit["B"] and row[1] == world.users["dpo_a"]["id"]


def _create_risk(world, user, **body):
    from fastapi import HTTPException
    from modules.launcher import routes_risks as risks
    try:
        return _call(risks.api_risk_create(_request(user, payload={"title": "Hand made", **body})))
    except HTTPException as refused:  # raised, like the score checks, and turned into a response by FastAPI
        return refused.status_code, {"error": refused.detail}


def test_a_risk_registered_by_hand_takes_an_explicit_unit_else_its_records_else_none(world):
    admin, rec, unit = world.users["super"], world.rec, world.unit
    status, made = _create_risk(world, admin, source_module="sentinel", source_entity_type="breach",
                                source_entity_id=rec[("breach", "B")])
    assert status == 201 and _unit_of(world.db, "risk_register", made["id"]) == unit["B"]
    status, made = _create_risk(world, admin, business_unit_id=unit["A1"], source_module="sentinel",
                                source_entity_type="breach", source_entity_id=rec[("breach", "B")])
    assert status == 201 and _unit_of(world.db, "risk_register", made["id"]) == unit["A1"]
    status, made = _create_risk(world, admin)
    assert status == 201 and _unit_of(world.db, "risk_register", made["id"]) is None


@pytest.mark.parametrize("bad", [999999, "abc", -1, 0, 1.5, True])
def test_a_risk_cannot_be_registered_in_a_unit_that_does_not_exist(world, bad):
    status, body = _create_risk(world, world.users["super"], business_unit_id=bad)
    assert status == 400, body
    assert world.db.execute("SELECT COUNT(*) FROM risk_register").fetchone()[0] == 0


def test_an_inactive_unit_cannot_own_a_new_risk(world):
    world.db.execute("UPDATE business_units SET is_active = 0 WHERE id = %s", (world.unit["B"],))
    world.db.commit()
    assert _create_risk(world, world.users["super"], business_unit_id=world.unit["B"])[0] == 400


def test_registering_a_risk_stays_with_the_super_administrator(world):
    for name in ("dpo_a", "owner_a", "employee_a"):
        assert _create_risk(world, world.users[name])[0] == 403, name


# ── Rows that existed before the column ─────────────────────────────────────

MARKER = "ownership.backfill.v1"


def _legacy_rows(world):
    """One row of each kind from before ownership existed (no unit), and what each should become."""
    db, rec, users = world.db, world.rec, world.users
    db.execute("DELETE FROM settings WHERE key = %s", (MARKER,))
    definition = _insert(db, "workflow_definitions", name="Old flow", steps_json="[]", created_by=users["super"]["id"])
    sla_definition = _insert(db, "sla_definitions", name="Old SLA", module="sentinel", entity_type="breach")
    risk = lambda **kw: _insert(db, "risk_register", title="Old risk", **kw)  # noqa: E731
    flow = lambda **kw: _insert(db, "workflow_instances", definition_id=definition, org_id=ORG, **kw)  # noqa: E731
    clock = lambda **kw: _insert(db, "sla_instances", definition_id=sla_definition, org_id=ORG, **kw)  # noqa: E731
    return types.SimpleNamespace(
        risk_from_record=risk(source_module="sentinel", source_entity_type="breach", source_entity_id=rec[("breach", "B")],
                              created_by=users["super"]["id"]),
        risk_from_creator=risk(source_module="aria", source_entity_type="risk", source_entity_id=5,
                               created_by=users["dpo_a"]["id"]),
        risk_org_record=risk(source_module="sentinel", source_entity_type="breach",
                             source_entity_id=rec[("breach", "org")], created_by=users["dpo_a"]["id"]),
        risk_unplaceable=risk(source_module="aria", source_entity_type="risk", source_entity_id=5,
                              created_by=users["super"]["id"]),
        risk_no_creator=risk(),
        already_placed=risk(source_module="sentinel", source_entity_type="breach",
                            source_entity_id=rec[("breach", "B")], business_unit_id=world.unit["A1"]),
        flow_from_record=flow(entity_module="bcm", entity_type="incident", entity_id=rec[("incident", "B")],
                              started_by=users["super"]["id"]),
        flow_from_starter=flow(entity_module="grid", entity_type="finding", entity_id=9, started_by=users["dpo_b"]["id"]),
        clock_from_record=clock(entity_module="sentinel", entity_type="breach", entity_id=rec[("breach", "A1")]),
        clock_unplaceable=clock(entity_module="bcm", entity_type="whatever", entity_id=3),
    )


def _expected(world):
    u = world.unit
    return {
        "risk_register": {"risk_from_record": u["B"], "risk_from_creator": u["A"], "risk_org_record": None,
                          "risk_unplaceable": None, "risk_no_creator": None, "already_placed": u["A1"]},
        "workflow_instances": {"flow_from_record": u["B"], "flow_from_starter": u["B"]},
        "sla_instances": {"clock_from_record": u["A1"], "clock_unplaceable": None},
    }


def _assert_placed(world, legacy):
    for table, wanted in _expected(world).items():
        for name, unit in wanted.items():
            assert _unit_of(world.db, table, getattr(legacy, name)) == unit, name


def test_existing_rows_are_placed_by_the_same_rule_as_new_ones(world):
    import database
    legacy = _legacy_rows(world)
    database._backfill_owner_units(world.db)
    world.db.commit()
    _assert_placed(world, legacy)


def test_the_backfill_runs_once_so_a_user_who_moves_later_does_not_inherit_old_rows(world):
    import database
    legacy = _legacy_rows(world)
    database._backfill_owner_units(world.db)
    world.db.commit()
    world.db.execute("UPDATE users SET business_unit_id = %s WHERE id = %s",
                     (world.unit["B"], world.users["super"]["id"]))
    world.db.commit()
    database._backfill_owner_units(world.db)
    world.db.commit()
    assert _unit_of(world.db, "risk_register", legacy.risk_unplaceable) is None
    assert world.db.execute("SELECT COUNT(*) FROM settings WHERE key = %s", (MARKER,)).fetchone()[0] == 1


def test_a_failed_backfill_leaves_no_marker_so_the_next_start_tries_again(world, monkeypatch):
    import database
    import modules.governance.entity_scope as scope
    legacy = _legacy_rows(world)

    def boom(*args, **kwargs):
        raise RuntimeError("database went away")

    with monkeypatch.context() as broken:
        broken.setattr(scope, "owner_unit", boom)
        database._backfill_owner_units(world.db)
        world.db.commit()
    assert world.db.execute("SELECT COUNT(*) FROM settings WHERE key = %s", (MARKER,)).fetchone()[0] == 0
    database._backfill_owner_units(world.db)
    world.db.commit()
    _assert_placed(world, legacy)


def test_starting_the_application_places_existing_rows(world):
    """The upgrade path: init_db() on a database whose rows predate the column."""
    import database
    legacy = _legacy_rows(world)
    database.init_db()
    _assert_placed(world, legacy)
