"""
BCM incident acknowledgement and escalation (plans/2026-10-governance-rework/13).

Expectations are written by hand: 15, 30 and 60 minutes for critical, high and medium incidents, nothing for low; the
BCM managers who can open the incident are the first alternate; one escalation per clock. Every "is not told" has a
positive twin. Nothing here touches a mail server: delivery is a fake provider.
"""
import asyncio
import json
import re
import types
from datetime import timedelta

import pytest

import core.middleware as middleware
from core import email as mail
from core import email_outbox as outbox
from core.timeutils import utcnow
from modules.bcm import data_service as ds
from modules.bcm import escalation as esc

# Bind the router's names to the real functions at collection time (the fixture below replaces get_current_user).
from modules.bcm import routes as _bcm_routes  # noqa: E402,F401

ORG = 1


def _insert(db, table, **cols):
    cur = db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                     tuple(cols.values()))
    db.commit()
    return cur.lastrowid


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)


class Provider:
    def __init__(self):
        self.calls = []

    def __call__(self, *, to, subject, body_html, body_text=None):
        self.calls.append({"to": to, "subject": subject, "text": body_text})
        return {"status": mail.STATUS_ACCEPTED, "ok": True, "provider": "fake"}


@pytest.fixture
def provider(monkeypatch):
    fake = Provider()
    monkeypatch.setattr(mail, "send_email", fake)
    monkeypatch.setenv("APP_URL", "https://app.themisiq.net")
    return fake


@pytest.fixture
def world(test_db):
    """Units A and B; BCM managers in A, in B and with no unit; a commander; a responder; an administrator."""
    db = test_db
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (1, 'org', 'org')")
    db.commit()
    unit_a = _insert(db, "business_units", name="Unit A", is_active=1)
    unit_b = _insert(db, "business_units", name="Unit B", is_active=1)
    people = {}

    def person(name, role, unit=None, active=1, platform=0, org=ORG):
        uid = _insert(db, "users", username=name, email=f"{name}@example.test", full_name=name.replace("_", " ").title(),
                      password_hash="x", org_id=org, business_unit_id=unit, is_active=active, is_super_admin=platform)
        _insert(db, "user_roles", user_id=uid, role_key=role)
        people[name] = {"id": uid, "username": name, "full_name": name.replace("_", " ").title(), "org_id": org,
                        "business_unit_id": unit, "is_super_admin": bool(platform), "roles": [role]}

    person("mgr_a", "bcm_manager", unit_a)
    person("mgr_b", "bcm_manager", unit_b)
    person("mgr_none", "bcm_manager")
    person("mgr_gone", "bcm_manager", unit_a, active=0)
    person("cmdr", "incident_commander", unit_a)
    person("responder", "bcm_responder", unit_a)
    person("chief", "super_admin")
    person("org_admin", "org_admin")
    person("employee", "employee", unit_a)
    person("operator", "super_admin", platform=1, org=None)
    return types.SimpleNamespace(db=db, people=people, unit_a=unit_a, unit_b=unit_b)


def _declare(w, severity="critical", commander=None, actor=None, unit="a", status="open", title="Power loss"):
    unit_id = {"a": w.unit_a, "b": w.unit_b, None: None}[unit]
    return ds.create_incident(
        {"title": title, "description": "x", "severity": severity, "status": status, "business_unit_id": unit_id,
         "commander_user_id": w.people[commander]["id"] if commander else None},
        actor_id=w.people[actor]["id"] if actor else None)


def _row(w, incident_id):
    return dict(w.db.execute("SELECT * FROM bcm_incidents WHERE id = %s", (incident_id,)).fetchone())


def _minutes_from_now(stamp) -> float:
    return (esc.parse(stamp) - utcnow()).total_seconds() / 60.0


def _later(minutes):
    return utcnow() + timedelta(minutes=minutes)


# ── The windows and the clock ───────────────────────────────────────────────

def test_each_severity_has_its_window_and_low_has_none():
    assert [esc.window_minutes(s) for s in ("critical", "high", "medium")] == [15, 30, 60]
    assert esc.window_minutes("Critical") == 15, "case does not matter"
    assert esc.window_minutes("low") is None and esc.window_minutes("") is None and esc.window_minutes(None) is None
    now = utcnow()
    assert esc.parse(esc.due_from("high", now)) - now.replace(microsecond=0) == timedelta(minutes=30)
    assert esc.due_from("low", now) is None


def test_a_declared_incident_is_due_by_its_severity_and_a_closed_or_low_one_has_no_clock(world):
    for severity, minutes in (("critical", 15), ("high", 30), ("medium", 60)):
        row = _row(world, _declare(world, severity))
        assert _minutes_from_now(row["ack_due_at"]) == pytest.approx(minutes, abs=0.5), severity
        assert row["acknowledged_at"] is None and row["escalated_at"] is None
    assert _row(world, _declare(world, "low"))["ack_due_at"] is None
    assert _row(world, _declare(world, "critical", status="resolved"))["ack_due_at"] is None
    default = ds.create_incident({"title": "No severity given", "description": "x"})
    assert _minutes_from_now(_row(world, default)["ack_due_at"]) == pytest.approx(60, abs=0.5), "medium is the default"


def test_a_person_who_names_themselves_commander_has_acknowledged_and_naming_someone_else_has_not(world):
    own = _row(world, _declare(world, commander="mgr_a", actor="mgr_a"))
    assert own["acknowledged_by"] == world.people["mgr_a"]["id"] and own["acknowledged_at"]
    assert esc.state(own) == "acknowledged"

    other = _row(world, _declare(world, commander="cmdr", actor="mgr_a"))
    assert other["acknowledged_at"] is None and esc.state(other) == "awaiting"
    none = _row(world, _declare(world, commander=None, actor="mgr_a"))
    assert none["acknowledged_at"] is None and esc.state(none) == "awaiting"


def test_a_new_commander_restarts_the_clock_and_the_same_commander_does_not(world):
    incident = _declare(world, "critical", commander="cmdr", actor="mgr_a")
    assert ds.acknowledge_incident(incident, world.people["cmdr"]["id"]) == "recorded"
    ds.update_incident(incident, {"commander_user_id": world.people["cmdr"]["id"]}, actor_id=world.people["mgr_a"]["id"])
    assert _row(world, incident)["acknowledged_at"], "the same person saved again: nothing restarts"

    ds.update_incident(incident, {"commander_user_id": world.people["responder"]["id"]},
                       actor_id=world.people["mgr_a"]["id"])
    row = _row(world, incident)
    assert row["acknowledged_at"] is None and row["acknowledged_by"] is None, "a new person must acknowledge"
    assert row["escalated_at"] is None
    assert _minutes_from_now(row["ack_due_at"]) == pytest.approx(15, abs=0.5)


def test_raising_the_severity_shortens_the_time_left_and_lowering_it_never_lengthens_it(world):
    incident = _declare(world, "medium", commander="cmdr", actor="mgr_a")
    assert _minutes_from_now(_row(world, incident)["ack_due_at"]) == pytest.approx(60, abs=0.5)
    ds.update_incident(incident, {"severity": "critical"}, actor_id=world.people["mgr_a"]["id"])
    assert _minutes_from_now(_row(world, incident)["ack_due_at"]) == pytest.approx(15, abs=0.5)
    ds.update_incident(incident, {"severity": "low"}, actor_id=world.people["mgr_a"]["id"])
    assert _minutes_from_now(_row(world, incident)["ack_due_at"]) == pytest.approx(15, abs=0.5), "never extended"

    # an acknowledged incident keeps its acknowledgement when the severity is raised
    acked = _declare(world, "medium", commander="cmdr", actor="cmdr")
    before = _row(world, acked)
    ds.update_incident(acked, {"severity": "critical"}, actor_id=world.people["mgr_a"]["id"])
    after = _row(world, acked)
    assert after["acknowledged_at"] == before["acknowledged_at"] and after["ack_due_at"] == before["ack_due_at"]


def test_reopening_an_incident_restarts_the_clock(world):
    incident = _declare(world, "high", commander="cmdr", actor="cmdr")
    assert _row(world, incident)["acknowledged_at"]
    ds.update_incident(incident, {"status": "resolved"}, actor_id=world.people["mgr_a"]["id"])
    assert _row(world, incident)["acknowledged_at"], "resolving does not undo it"
    ds.update_incident(incident, {"status": "active"}, actor_id=world.people["mgr_a"]["id"])
    row = _row(world, incident)
    assert row["acknowledged_at"] is None, "reopened by someone else: the commander must acknowledge again"
    assert _minutes_from_now(row["ack_due_at"]) == pytest.approx(30, abs=0.5)


def test_the_state_of_the_clock_in_words():
    now = utcnow()
    soon, past = esc.stamp(now + timedelta(minutes=5)), esc.stamp(now - timedelta(minutes=5))
    assert esc.state({}) == "none"
    assert esc.state({"ack_due_at": soon}, now) == "awaiting"
    assert esc.state({"ack_due_at": past}, now) == "overdue"
    assert esc.state({"ack_due_at": past, "escalated_at": past}, now) == "escalated"
    assert esc.state({"ack_due_at": past, "acknowledged_at": past}, now) == "acknowledged"
    out = esc.with_state({"severity": "high", "ack_due_at": soon, "acknowledged_by": 7}, now, {7: "Ada"})
    assert (out["ack_state"], out["ack_minutes"], out["acknowledged_by_name"]) == ("awaiting", 30, "Ada")


# ── The job ─────────────────────────────────────────────────────────────────

def test_nothing_is_escalated_before_the_window_ends_and_it_is_escalated_exactly_once_after(world):
    incident = _declare(world, "critical", commander="cmdr", actor="mgr_a")
    assert esc.escalate_due(world.db, ORG, now=_later(14)) == 0
    assert _row(world, incident)["escalated_at"] is None
    assert esc.escalate_due(world.db, ORG, now=_later(16)) == 1
    assert _row(world, incident)["escalated_at"]
    assert esc.escalate_due(world.db, ORG, now=_later(40)) == 0, "once"
    assert esc.state(_row(world, incident), _later(40)) == "escalated"


def test_an_acknowledged_incident_is_not_escalated(world):
    incident = _declare(world, "critical", commander="cmdr", actor="mgr_a")
    assert ds.acknowledge_incident(incident, world.people["cmdr"]["id"], now=_later(5)) == "recorded"
    assert esc.escalate_due(world.db, ORG, now=_later(30)) == 0
    assert _row(world, incident)["escalated_at"] is None


def test_the_bcm_managers_who_can_open_the_incident_are_told_in_the_app_and_by_critical_email(world):
    incident = _declare(world, "critical", commander="cmdr", actor="mgr_a", unit="a", title="Secret outage title")
    assert esc.escalate_due(world.db, ORG, now=_later(16)) == 1

    told = [r["user_id"] for r in world.db.execute(
        "SELECT user_id FROM notifications WHERE module = 'bcm' ORDER BY user_id").fetchall()]
    assert told == [world.people["mgr_a"]["id"]], \
        "the manager of the unit; not the manager of another unit, nor one with no unit, nor an inactive one, nor the commander"
    note = dict(world.db.execute("SELECT title, message, link FROM notifications WHERE module = 'bcm'").fetchone())
    assert note == {"title": f"Incident INC-{incident} was not acknowledged",
                    "message": f"Nobody acknowledged incident INC-{incident} within 15 minutes. Open it to take it over "
                               "or to name a commander.", "link": f"/bcm/?open=incident:{incident}"}

    (queued,) = [dict(r) for r in world.db.execute(
        "SELECT * FROM email_outbox WHERE template_key = 'bcm.escalation'").fetchall()]
    assert queued["recipient_user_id"] == world.people["mgr_a"]["id"] and queued["priority"] == "critical"
    assert json.loads(queued["fields_json"]) == {"minutes": 15, "reference": f"INC-{incident}"}
    assert "Secret outage title" not in json.dumps(queued) and queued["route"] == f"/bcm/?open=incident:{incident}"

    timeline = [r["note"] for r in world.db.execute(
        "SELECT note FROM bcm_incident_updates WHERE incident_id = %s", (incident,)).fetchall()]
    assert timeline == ["Not acknowledged within 15 minutes. The BCM managers were told."]
    audit = world.db.execute("SELECT action, entity_id FROM audit_log WHERE action = 'incident_escalated'").fetchall()
    assert [(a["action"], a["entity_id"]) for a in audit] == [("incident_escalated", incident)]


def test_an_organization_wide_incident_goes_to_every_manager_who_can_open_it(world):
    incident = _declare(world, "critical", commander="cmdr", actor="mgr_a", unit=None)
    esc.escalate_due(world.db, ORG, now=_later(16))
    told = sorted(r["user_id"] for r in world.db.execute(
        "SELECT user_id FROM notifications WHERE module = 'bcm'").fetchall())
    assert told == sorted(world.people[n]["id"] for n in ("mgr_a", "mgr_b", "mgr_none"))
    assert _row(world, incident)["escalated_at"]


def test_an_incident_with_no_named_commander_is_escalated_the_same_way(world):
    _declare(world, "high", commander=None, actor="mgr_a")
    assert esc.escalate_due(world.db, ORG, now=_later(31)) == 1


def test_when_no_manager_can_open_it_a_super_administrator_who_can_is_told(world):
    world.db.execute("UPDATE users SET is_active = 0 WHERE id IN (%s, %s, %s)",
                     (world.people["mgr_a"]["id"], world.people["mgr_b"]["id"], world.people["mgr_none"]["id"]))
    world.db.commit()
    _declare(world, "critical", commander="cmdr", actor="cmdr", unit=None)  # acknowledged by naming self: no clock run
    open_one = _declare(world, "critical", commander="cmdr", actor="responder", unit=None)
    assert esc.escalate_due(world.db, ORG, now=_later(16)) == 1
    told = [r["user_id"] for r in world.db.execute(
        "SELECT user_id FROM notifications WHERE module = 'bcm'").fetchall()]
    assert told == [world.people["chief"]["id"]]
    assert _row(world, open_one)["escalated_at"]


def test_when_nobody_who_can_open_it_exists_the_administrators_are_told_without_the_reference(world):
    for name in ("mgr_a", "mgr_b", "mgr_none"):
        world.db.execute("UPDATE users SET is_active = 0 WHERE id = %s", (world.people[name]["id"],))
    world.db.commit()
    incident = _declare(world, "critical", commander="cmdr", actor="responder", unit="a")  # chief has no unit
    assert esc.escalate_due(world.db, ORG, now=_later(16)) == 1
    rows = [dict(r) for r in world.db.execute(
        "SELECT user_id, title, message, link FROM notifications WHERE module = 'bcm' ORDER BY user_id").fetchall()]
    assert {r["user_id"] for r in rows} == {world.people["chief"]["id"], world.people["org_admin"]["id"]}
    assert all(f"INC-{incident}" not in r["title"] + r["message"] and r["link"] == "/bcm/" for r in rows)
    assert world.db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == 0
    assert _row(world, incident)["escalated_at"], "recorded, so it is not tried every minute"


def test_old_low_resolved_and_closed_incidents_are_never_escalated(world):
    legacy = _insert(world.db, "bcm_incidents", title="Declared before the clock existed", severity="critical",
                     status="open", business_unit_id=world.unit_a)
    low = _declare(world, "low")
    closed = _declare(world, "critical")
    resolved = _declare(world, "critical")
    world.db.execute("UPDATE bcm_incidents SET status = 'closed' WHERE id = %s", (closed,))
    world.db.execute("UPDATE bcm_incidents SET status = 'resolved' WHERE id = %s", (resolved,))
    world.db.commit()
    assert _row(world, legacy)["ack_due_at"] is None
    assert esc.escalate_due(world.db, ORG, now=_later(500)) == 0
    # the positive twin: the same severity and age, still open
    live = _declare(world, "critical")
    assert esc.escalate_due(world.db, ORG, now=_later(500)) == 1
    assert _row(world, live)["escalated_at"] and _row(world, low)["escalated_at"] is None


def test_the_message_is_checked_again_when_it_is_sent(world, provider):
    stale = _declare(world, "critical", commander="cmdr", actor="mgr_a", title="Acknowledged meanwhile")
    kept = _declare(world, "critical", commander="cmdr", actor="mgr_a", title="Still waiting")
    esc.escalate_due(world.db, ORG, now=_later(16))
    assert world.db.execute("SELECT COUNT(*) FROM email_outbox WHERE template_key = 'bcm.escalation'").fetchone()[0] == 2

    # somebody acknowledged one of them before the worker came round
    ds.acknowledge_incident(stale, world.people["cmdr"]["id"], now=_later(17))
    outbox.deliver_due(world.db)
    rows = {r["source_id"]: dict(r) for r in world.db.execute(
        "SELECT source_id, status, suppress_reason FROM email_outbox WHERE template_key = 'bcm.escalation'").fetchall()}
    assert rows[stale]["status"] == "suppressed" and rows[stale]["suppress_reason"] == "no_longer_open"
    assert rows[kept]["status"] == "provider_accepted"
    (call,) = provider.calls
    assert call["to"] == "mgr_a@example.test"
    assert f"INC-{kept}" in call["text"] and "within 15 minutes" in call["text"] and "Still waiting" not in call["text"]


def test_the_commanders_message_says_how_long_they_have(world, provider):
    from modules.bcm import routes as bcm
    critical = _declare(world, "critical", commander="cmdr", actor="mgr_a")
    low = _declare(world, "low", commander="cmdr", actor="mgr_a")
    bcm._ask_commander_mail(critical, world.people["cmdr"]["id"], world.people["mgr_a"]["id"], "critical")
    bcm._ask_commander_mail(low, world.people["cmdr"]["id"], world.people["mgr_a"]["id"], "low")
    outbox.deliver_due(world.db)
    by_ref = {re.search(r"INC-\d+", c["text"]).group(0): c["text"] for c in provider.calls}
    assert "Acknowledge it in ThemisIQ within 15 minutes." in by_ref[f"INC-{critical}"]
    assert "Acknowledge it" not in by_ref[f"INC-{low}"]


# ── The route ───────────────────────────────────────────────────────────────

def _request(user, payload=None):
    request = types.SimpleNamespace(state=types.SimpleNamespace(user=user), url=types.SimpleNamespace(path="/bcm/api/x"),
                                    query_params={}, client=None, headers={})
    if payload is not None:
        async def _json():
            return payload

        request.json = _json
    return request


def _call(coro):
    from fastapi import HTTPException
    try:
        response = asyncio.run(coro)
    except HTTPException as exc:
        return exc.status_code, {"detail": exc.detail}
    return response.status_code, json.loads(response.body)


def test_the_named_commander_and_a_manager_can_acknowledge_and_nobody_else(world):
    from modules.bcm import routes as bcm
    incident = _declare(world, "critical", commander="cmdr", actor="mgr_a")
    p = world.people

    status, body = _call(bcm.api_incident_acknowledge(_request(p["responder"]), incident))
    assert status == 403 and "named incident commander" in body["detail"], "a responder who is not the commander"
    assert _row(world, incident)["acknowledged_at"] is None

    status, body = _call(bcm.api_incident_acknowledge(_request(p["cmdr"]), incident))
    assert status == 200 and body["recorded"] is True and body["ack_state"] == "acknowledged"
    assert body["acknowledged_by_name"] == "Cmdr"
    status, body = _call(bcm.api_incident_acknowledge(_request(p["mgr_a"]), incident))
    assert status == 200 and body["recorded"] is False, "the first acknowledgement stands"
    assert _row(world, incident)["acknowledged_by"] == p["cmdr"]["id"]

    other = _declare(world, "high", commander="cmdr", actor="mgr_a")
    status, body = _call(bcm.api_incident_acknowledge(_request(p["mgr_a"]), other))
    assert status == 200 and body["recorded"] is True, "a BCM manager can take it over"
    notes = [r["note"] for r in world.db.execute(
        "SELECT note FROM bcm_incident_updates WHERE incident_id = %s", (other,)).fetchall()]
    assert notes == ["Acknowledged."]
    audit = world.db.execute("SELECT user_id FROM audit_log WHERE action = 'incident_acknowledged' ORDER BY id").fetchall()
    assert [a["user_id"] for a in audit] == [p["cmdr"]["id"], p["mgr_a"]["id"]]


def test_acknowledging_respects_scope_and_the_state_of_the_incident(world):
    from modules.bcm import routes as bcm
    p = world.people
    in_b = _declare(world, "critical", commander="mgr_b", actor="mgr_a", unit="b")
    status, _ = _call(bcm.api_incident_acknowledge(_request(p["mgr_a"]), in_b))
    assert status == 404, "another unit's incident is not found"
    status, _ = _call(bcm.api_incident_acknowledge(_request(p["mgr_a"]), 99999))
    assert status == 404

    resolved = _declare(world, "critical", commander="cmdr", actor="mgr_a")
    ds.update_incident(resolved, {"status": "resolved"})
    status, body = _call(bcm.api_incident_acknowledge(_request(p["cmdr"]), resolved))
    assert status == 409 and "resolved or closed" in body["detail"]

    status, _ = _call(bcm.api_incident_acknowledge(_request(p["employee"]), resolved))
    assert status == 403, "an employee may open Business Continuity but is neither the commander nor a manager"


def test_the_incident_responses_carry_the_state_and_the_name(world):
    from modules.bcm import routes as bcm
    p = world.people
    waiting = _declare(world, "critical", commander="cmdr", actor="mgr_a")
    done = _declare(world, "high", commander="cmdr", actor="cmdr")
    status, listed = _call(bcm.api_incidents_list(_request(p["mgr_a"])))
    by_id = {r["id"]: r for r in listed}
    assert (by_id[waiting]["ack_state"], by_id[waiting]["ack_minutes"]) == ("awaiting", 15)
    assert (by_id[done]["ack_state"], by_id[done]["acknowledged_by_name"]) == ("acknowledged", "Cmdr")
    status, detail = _call(bcm.api_incident_detail(_request(p["mgr_a"]), waiting))
    assert detail["ack_state"] == "awaiting" and detail["ack_due_at"] == _row(world, waiting)["ack_due_at"]


def test_the_incident_a_confirmed_breach_opens_starts_its_clock_and_is_escalated_when_nobody_takes_it(world):
    from core import event_handlers as handlers
    # the handler writes tier names (major, significant) that the windows read as high and medium
    for severity in ("critical", "high", "medium", "low"):
        handlers.breach_triggers_bcm_incident("sentinel.breach.confirmed", "sentinel", "breach", 7,
                                              {"title": f"Breach {severity}", "severity": severity}, None)
    rows = [dict(r) for r in world.db.execute(
        "SELECT id, title, severity, ack_due_at FROM bcm_incidents ORDER BY id").fetchall()]
    assert [(r["severity"], round(_minutes_from_now(r["ack_due_at"]))) for r in rows] == [
        ("critical", 15), ("major", 30), ("significant", 60), ("major", 30)]
    assert esc.escalate_due(world.db, ORG, now=_later(20)) == 1, "only the critical one is due at 20 minutes"
    assert esc.escalate_due(world.db, ORG, now=_later(70)) == 3
    told = {r["user_id"] for r in world.db.execute("SELECT user_id FROM notifications WHERE module = 'bcm' "
                                                    "AND title LIKE 'Incident INC-%'").fetchall()}
    assert told == {world.people[n]["id"] for n in ("mgr_a", "mgr_b", "mgr_none")}, "no unit: the whole organization"
