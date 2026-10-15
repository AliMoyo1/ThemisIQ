"""
What the schedulers and routes ask the email outbox for, and what they must not
(plans/2026-10-governance-rework/06 sections 3, 4 and 9, phases E1 and E2).

Expectations are written by hand. Each "is not asked for" has a positive twin: the same situation for a person for whom
nothing is wrong. Nothing here touches a mail server: delivery is a fake provider.
"""
import asyncio
import json
from datetime import timedelta

import pytest
from fastapi import HTTPException

from core import email as mail
from core import email_outbox as outbox
from core.timeutils import utcnow

# Bind the routers' names to the real functions at collection time. A fixture below replaces
# middleware.get_current_user for a while; a router first imported under that patch would keep the stand-in for good.
from modules.launcher import routes_admin as _routes_admin, routes_auth as _routes_auth  # noqa: E402,F401

ORG = 1


def _insert(db, table, **cols):
    cur = db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                     tuple(cols.values()))
    db.commit()
    return cur.lastrowid


def _stamp(moment) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


class Provider:
    def __init__(self):
        self.calls = []
        self.answer = {"status": mail.STATUS_ACCEPTED, "ok": True, "provider": "fake"}

    def __call__(self, *, to, subject, body_html, body_text=None):
        self.calls.append({"to": to, "subject": subject, "html": body_html, "text": body_text})
        return dict(self.answer)


@pytest.fixture
def provider(monkeypatch):
    fake = Provider()
    monkeypatch.setattr(mail, "send_email", fake)
    monkeypatch.setenv("APP_URL", "https://app.themisiq.net")
    return fake


@pytest.fixture
def world(test_db):
    """One organization of two units, one suspended organization, and the people and records the jobs read."""
    db = test_db
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (1, 'org', 'org')")
    db.execute("INSERT INTO organizations (id, name, slug, status) VALUES (2, 'other', 'other', 'suspended')")
    db.commit()
    unit_a = _insert(db, "business_units", name="Unit A", is_active=1)
    unit_b = _insert(db, "business_units", name="Unit B", is_active=1)

    people = {}

    def person(name, role=None, org=ORG, unit=None, active=1, platform=0):
        people[name] = _insert(db, "users", username=name, email=f"{name}@example.test", full_name=name,
                               password_hash="x", org_id=org, business_unit_id=unit, is_active=active,
                               is_super_admin=platform)
        if role:
            _insert(db, "user_roles", user_id=people[name], role_key=role)

    person("first", "employee")                       # the first active user: the old fallback for a DPO address
    person("lead_a", "audit_lead", unit=unit_a)
    person("lead_b", "audit_lead", unit=unit_b)
    person("owner", "audit_lead", unit=unit_a)        # assigned to the controls and findings
    person("boss", "org_admin")
    person("chief", "super_admin")                    # an organization's top role, no platform flag
    person("boss_other", "org_admin", org=2)
    person("operator", "super_admin", org=None, platform=1)
    person("dpo_a", "dpo", unit=unit_a)
    person("dpo_b", "dpo", unit=unit_b)
    person("gone", "dpo", active=0)
    person("analyst", "privacy_analyst", unit=unit_a)
    person("cmdr", "incident_commander")
    person("cmdr2", "bcm_manager")

    today = utcnow().date()
    audit_a = _insert(db, "grid_audits", name="Audit A", business_unit_id=unit_a, lead_id=people["lead_a"])
    audit_b = _insert(db, "grid_audits", name="Audit B", business_unit_id=unit_b, lead_id=people["lead_b"])
    audit_open = _insert(db, "grid_audits", name="Audit for everyone", business_unit_id=None)
    long_ago = (today - timedelta(days=10)).isoformat()
    ctrl_late = _insert(db, "grid_controls", audit_id=audit_a, name="Secret control", status="In Progress",
                        assignee_id=people["owner"], due_date=long_ago, risk_level="High")
    ctrl_late_open = _insert(db, "grid_controls", audit_id=audit_open, name="Open control", status="Not Started",
                             assignee_id=people["owner"], due_date=long_ago, risk_level="Critical")
    ctrl_done = _insert(db, "grid_controls", audit_id=audit_a, name="Done control", status="Complete",
                        assignee_id=people["owner"], due_date=long_ago, risk_level="High")
    return type("World", (), dict(
        db=db, people=people, unit_a=unit_a, unit_b=unit_b, today=today, audit_a=audit_a, audit_b=audit_b,
        audit_open=audit_open, ctrl_late=ctrl_late, ctrl_late_open=ctrl_late_open, ctrl_done=ctrl_done))


def _outbox(w, template=None):
    rows = [dict(r) for r in w.db.execute("SELECT * FROM email_outbox ORDER BY id").fetchall()]
    return [r for r in rows if template is None or r["template_key"] == template]


def _threshold(row) -> str:
    """The threshold is part of the dedupe key: organization|source|recipient|channel|purpose|threshold."""
    return row["dedupe_key"].split("|", 5)[5]


def _who(w, rows):
    names = {v: k for k, v in w.people.items()}
    return sorted(names[r["recipient_user_id"]] for r in rows)


# ── GRID ────────────────────────────────────────────────────────────────────

def test_a_subscribed_reminder_is_asked_once_per_period_and_never_for_a_finished_control(world):
    from modules.grid import scheduler as sched
    w = world
    _insert(w.db, "grid_reminders", control_id=w.ctrl_late, audit_id=w.audit_a, user_id=w.people["owner"],
            frequency="weekly", active=1)
    _insert(w.db, "grid_reminders", control_id=w.ctrl_done, audit_id=w.audit_a, user_id=w.people["owner"],
            frequency="weekly", active=1)
    sched.process_reminders()
    sched.process_reminders()
    rows = _outbox(w)
    assert len(rows) == 1, "the second run asks for the message that exists; a complete control is not reminded"
    row = rows[0]
    assert row["template_key"] == "control.reminder" and row["recipient_user_id"] == w.people["owner"]
    assert (row["source_module"], row["source_type"], row["source_id"]) == ("grid", "control", w.ctrl_late)
    fields = json.loads(row["fields_json"])
    assert fields["reference"] == f"AU-{w.audit_a}" and "Secret control" not in row["fields_json"]


def test_an_overdue_control_goes_to_the_audit_lead_or_else_the_organizations_administrators(world):
    from modules.grid import scheduler as sched
    w = world
    sched.process_escalations()
    rows = _outbox(w, "audit.escalation")
    to = {(r["source_id"], r["recipient_user_id"]) for r in rows}
    names = {v: k for k, v in w.people.items()}
    assert [names[u] for c, u in to if c == w.ctrl_late] == ["lead_a"], "the audit has a lead: only the lead"
    assert sorted(names[u] for c, u in to if c == w.ctrl_late_open) == ["boss", "chief"],         "no lead: the organization's administrators; not a platform operator, not another organization's, not the assignee"
    assert not any(c == w.ctrl_done for c, _ in to), "a complete control is not escalated"


def test_a_response_deadline_is_told_once_and_a_corrected_deadline_is_told_again(world):
    from modules.grid import scheduler as sched
    w = world
    soon = (w.today + timedelta(days=2)).isoformat()
    nc_due = _insert(w.db, "grid_non_conformances", audit_id=w.audit_a, title="Finding that is private", status="open",
                     assigned_to=w.people["owner"], response_deadline=soon, cap_status="Open")
    _insert(w.db, "grid_non_conformances", audit_id=w.audit_a, title="Closed finding", status="closed",
            assigned_to=w.people["owner"], response_deadline=soon, cap_status="Open")
    far = (w.today + timedelta(days=30)).isoformat()
    _insert(w.db, "grid_non_conformances", audit_id=w.audit_a, title="Far away", status="open",
            assigned_to=w.people["owner"], response_deadline=far, cap_status="Open")
    sched.process_nc_deadline_reminders()
    sched.process_nc_deadline_reminders()
    rows = _outbox(w, "audit.deadline")
    assert len(rows) == 1 and rows[0]["source_id"] == nc_due and rows[0]["recipient_user_id"] == w.people["owner"]
    assert "Finding that is private" not in rows[0]["fields_json"]
    later = (w.today + timedelta(days=3)).isoformat()
    w.db.execute("UPDATE grid_non_conformances SET response_deadline = %s WHERE id = %s", (later, nc_due))
    w.db.commit()
    sched.process_nc_deadline_reminders()
    assert len(_outbox(w, "audit.deadline")) == 2, "a corrected due date allows a new reminder"


def test_an_overdue_major_finding_goes_to_the_audit_lead_once_a_week(world):
    from modules.grid import scheduler as sched
    w = world
    nc = _insert(w.db, "grid_non_conformances", audit_id=w.audit_a, title="Late", status="open", severity="major",
                 assigned_to=w.people["owner"], due_date=(w.today - timedelta(days=10)).isoformat(), cap_status="Open")
    _insert(w.db, "grid_non_conformances", audit_id=w.audit_a, title="Minor", status="open", severity="minor",
            assigned_to=w.people["owner"], due_date=(w.today - timedelta(days=10)).isoformat(), cap_status="Open")
    sched.process_nc_escalations()
    sched.process_nc_escalations()
    rows = _outbox(w, "audit.escalation")
    assert [(r["source_id"], r["recipient_user_id"]) for r in rows] == [(nc, w.people["lead_a"])]


def test_the_weekly_summary_counts_only_what_the_subscriber_can_open(world):
    from modules.grid import scheduler as sched
    w = world
    _insert(w.db, "grid_digest_subscriptions", user_id=w.people["lead_a"], email="lead_a@example.test",
            audit_ids="all", active=1)
    _insert(w.db, "grid_digest_subscriptions", user_id=None, email="stranger@example.test", audit_ids="all", active=1)
    _insert(w.db, "grid_digest_subscriptions", user_id=w.people["lead_b"], email="lead_b@example.test",
            audit_ids=str(w.audit_a), active=1)           # chose an audit of a unit lead_b is not in
    _insert(w.db, "grid_digest_subscriptions", user_id=w.people["boss"], email="boss@example.test",
            audit_ids="all", active=0)
    sched.send_weekly_digest()
    sched.send_weekly_digest()
    rows = _outbox(w, "summary.weekly")
    assert _who(w, rows) == ["lead_a"], "no account, nothing the person can open, or a paused subscription: no message"
    fields = json.loads(rows[0]["fields_json"])
    assert fields == {"audits": 2, "overdue": 2}, "audit A and the organization-wide audit; their two late controls"


def test_a_grid_evidence_file_that_is_about_to_expire_is_told_to_the_control_assignee_once(world):
    from modules.grid import scheduler as sched
    w = world
    soon = (w.today + timedelta(days=10)).isoformat()
    kept = _insert(w.db, "grid_evidence_files", control_id=w.ctrl_late, filename="a.pdf", original_name="board.pdf",
                   file_path="x", status="Uploaded", expires_at=soon)
    _insert(w.db, "grid_evidence_files", control_id=w.ctrl_late, filename="b.pdf", original_name="no.pdf",
            file_path="y", status="Rejected", expires_at=soon)
    sched.process_expiry_alerts()
    sched.process_expiry_alerts()
    rows = _outbox(w, "evidence.renew")
    assert len(rows) == 1 and rows[0]["recipient_user_id"] == w.people["owner"]
    assert rows[0]["purpose"] == f"expiry:{kept}" and "board.pdf" not in rows[0]["fields_json"]


def test_the_vault_expiry_is_one_message_whether_the_grid_job_or_the_evidence_job_asks(world):
    from modules.evidence import scheduler as evidence
    from modules.grid import scheduler as sched
    w = world
    item = _insert(w.db, "evidence_items", title="Board minutes, confidential", status="current",
                   expiry_date=(w.today + timedelta(days=5)).isoformat(), uploaded_by=w.people["owner"])
    sched.process_vault_expiry_notifications()
    evidence._expiry_check()
    rows = _outbox(w, "evidence.renew")
    assert len(rows) == 1 and rows[0]["source_id"] == item
    assert _threshold(rows[0]).startswith("d7:") and "Board minutes" not in rows[0]["fields_json"]
    assert rows[0]["route"] == f"/evidence/?open=item:{item}"


def test_evidence_expiry_goes_to_the_owner_and_stops_when_the_file_is_handed_to_someone_else(world, provider):
    from modules.evidence import scheduler as evidence
    w = world
    item = _insert(w.db, "evidence_items", title="Pen test report", status="current", org_id=ORG,
                   expiry_date=(w.today + timedelta(days=20)).isoformat(), uploaded_by=w.people["first"],
                   owner_user_id=w.people["owner"])
    evidence.enqueue_expiry_messages(w.db, ORG)
    w.db.commit()
    rows = _outbox(w, "evidence.renew")
    assert [r["recipient_user_id"] for r in rows] == [w.people["owner"]], "the owner answers for the file, not the uploader"
    w.db.execute("UPDATE evidence_items SET owner_user_id = %s WHERE id = %s", (w.people["lead_a"], item))
    w.db.commit()
    outbox.deliver_due(w.db)
    assert provider.calls == []
    assert _outbox(w)[0]["status"] == "suppressed" and _outbox(w)[0]["suppress_reason"] == "no_longer_open"
    evidence.enqueue_expiry_messages(w.db, ORG)
    w.db.commit()
    assert _who(w, _outbox(w, "evidence.renew")) == ["lead_a", "owner"], "the new owner is told, once"
    outbox.deliver_due(w.db)
    assert [c["to"] for c in provider.calls] == ["lead_a@example.test"]


def test_a_finding_assignment_is_asked_for_through_the_outbox_with_a_reference_not_a_title(world, provider):
    from modules.grid import routes
    w = world
    nc = _insert(w.db, "grid_non_conformances", audit_id=w.audit_a, title="Payroll breach finding", status="open",
                 assigned_to=w.people["owner"], due_date=(w.today + timedelta(days=9)).isoformat())
    routes._ask_nc_assignment_email(nc)
    routes._ask_nc_assignment_email(nc)
    rows = _outbox(w, "audit.finding")
    assert len(rows) == 1 and rows[0]["recipient_user_id"] == w.people["owner"] and rows[0]["route"] == f"/grid/?open=nc:{nc}"
    assert provider.calls == [], "nothing is sent by the request: the outbox sends"
    outbox.deliver_due(w.db)
    (call,) = provider.calls
    assert call["to"] == "owner@example.test" and "Payroll breach finding" not in call["text"] + call["html"]
    assert f"AU-{w.audit_a}" in call["text"]


def test_the_assignment_and_the_share_no_longer_send_from_the_request():
    import inspect
    from modules.grid import routes
    assert "_ask_nc_assignment_email" in inspect.getsource(routes.api_ncs_update)
    assert "_ask_nc_assignment_email" in inspect.getsource(routes.api_ncs_create)
    assert "email_status" in inspect.getsource(routes.api_share_create), "the creator is told what the provider said"


def test_a_task_given_to_someone_else_asks_for_an_email_with_a_reference_and_not_the_title(world, provider):
    from modules.launcher.task_service import create_task_with_assignment_notification
    w = world

    def create(assigned_to, title):
        return create_task_with_assignment_notification(
            title=title, description="d", module="platform", entity_type="", entity_id=None, assigned_to=assigned_to,
            priority="medium", status="todo", due_date=(w.today + timedelta(days=4)).isoformat(), tags="",
            created_by=w.people["boss"])

    own = create(w.people["boss"], "Mine, so no mail")
    given = create(w.people["owner"], "Prepare the restricted payroll review")
    rows = _outbox(w, "action.assigned")
    assert [(r["source_id"], r["recipient_user_id"]) for r in rows] == [(given, w.people["owner"])]
    assert own not in {r["source_id"] for r in rows}
    notices = [dict(r) for r in w.db.execute("SELECT user_id, title FROM notifications WHERE module = 'task'")]
    assert {n["user_id"] for n in notices} == {w.people["boss"], w.people["owner"]}, "the in-app notice is unchanged"
    assert provider.calls == []
    outbox.deliver_due(w.db)
    (call,) = provider.calls
    assert call["to"] == "owner@example.test" and f"Reference: TK-{given}." in call["text"]
    assert "restricted payroll" not in call["text"] + call["html"] and "A task is assigned to you" in call["text"]
    assert "https://app.themisiq.net/tasks" in call["text"]


# ── BCM ─────────────────────────────────────────────────────────────────────

def test_a_named_incident_commander_is_told_and_only_while_the_incident_is_theirs(world, signed_in, provider):
    from modules.bcm import routes as bcm
    w = world
    payload = {"title": "Data centre outage in Harare", "description": "d", "severity": "high",
               "commander_user_id": w.people["cmdr"]}
    status, body = _admin_call(bcm.api_incident_create(_admin_request(w, payload)))
    assert status == 201
    incident = body["id"]
    rows = _outbox(w, "bcm.incident")
    assert [(r["recipient_user_id"], r["priority"], r["source_id"]) for r in rows] == [
        (w.people["cmdr"], "critical", incident)]
    assert json.loads(rows[0]["fields_json"]) == {"minutes": 30, "reference": f"INC-{incident}"},         "no title, no impact: the reference and how long a high severity incident has to be acknowledged"

    # handed to someone else before the first message went: the first is not sent, the second is
    status, _ = _admin_call(bcm.api_incident_update(_admin_request(w, {"commander_user_id": w.people["cmdr2"]}), incident))
    assert status == 200
    outbox.deliver_due(w.db)
    by_person = {r["recipient_user_id"]: r for r in _outbox(w, "bcm.incident")}
    assert by_person[w.people["cmdr"]]["suppress_reason"] == "no_longer_open"
    assert by_person[w.people["cmdr2"]]["status"] == "provider_accepted"
    (call,) = provider.calls
    assert call["to"] == "cmdr2@example.test" and f"incident INC-{incident}" in call["text"]
    assert "Harare" not in call["text"] + call["html"]
    assert f"https://app.themisiq.net/bcm/?open=incident:{incident}" in call["text"]


def test_only_an_active_person_of_this_organization_who_can_open_bcm_may_be_named_commander(world, signed_in):
    from modules.bcm import routes as bcm
    w = world
    for who in ("boss_other", "gone", "lead_b", "operator"):
        payload = {"title": "Incident", "description": "d", "commander_user_id": w.people[who]}
        with pytest.raises(HTTPException) as refused:
            asyncio.run(bcm.api_incident_create(_admin_request(w, payload)))
        assert refused.value.status_code == 422, who
    with pytest.raises(HTTPException) as refused:
        asyncio.run(bcm.api_incident_create(_admin_request(w, {"title": "Incident", "description": "d",
                                                               "commander_user_id": "someone"})))
    assert refused.value.status_code == 422
    status, body = _admin_call(bcm.api_incident_create(_admin_request(w, {"title": "Incident", "description": "d"})))
    assert status == 201, "naming nobody is allowed: the free text label still works"
    assert _outbox(w, "bcm.incident") == []


def test_the_people_list_for_bcm_is_this_organizations_active_bcm_staff(world, signed_in):
    from modules.bcm import routes as bcm
    w = world
    status, got = _admin_call(bcm.api_people(_admin_request(w)))
    names = {p["name"] for p in got}
    assert {"cmdr", "cmdr2"} <= names
    assert not names & {"gone", "boss_other", "operator"}, "inactive, another organization, a platform operator"


def test_the_owner_of_an_upcoming_exercise_is_asked_for_once(world, provider):
    from modules.bcm import scheduler as bcm_sched
    w = world
    due = (w.today + timedelta(days=5)).isoformat()
    exercise = _insert(w.db, "bcm_exercises", title="Failover drill, confidential scenario", status="planned",
                       scheduled_date=due, org_id=ORG, owner_id=w.people["cmdr"])
    bcm_sched._exercise_alert_check()
    bcm_sched._exercise_alert_check()
    rows = _outbox(w, "bcm.exercise")
    assert [(r["recipient_user_id"], r["source_id"]) for r in rows] == [(w.people["cmdr"], exercise)]
    assert json.loads(rows[0]["fields_json"]) == {"reference": f"EX-{exercise}", "due": due}
    outbox.deliver_due(w.db)
    (call,) = provider.calls
    assert call["to"] == "cmdr@example.test" and f"Reference: EX-{exercise}." in call["text"]
    assert "Failover" not in call["text"] + call["html"]


# ── The people a job addresses, and the failure report ──────────────────────

def test_the_people_of_an_organization_are_its_own_active_staff_and_never_a_platform_operator(world):
    w = world
    admins = outbox.organization_people(w.db, ORG, outbox.ADMIN_ROLES)
    names = {v: k for k, v in w.people.items()}
    assert sorted(names[i] for i in admins) == ["boss", "chief"]
    assert [names[i] for i in outbox.organization_people(w.db, ORG, ("dpo",))] == ["dpo_a", "dpo_b"],         "the inactive officer is not addressed"
    assert outbox.organization_people(w.db, ORG, ()) == []
    legacy = _insert(w.db, "users", username="legacy", email="legacy@example.test", full_name="legacy",
                     password_hash="x", is_active=1)
    _insert(w.db, "user_roles", user_id=legacy, role_key="dpo")
    assert legacy in outbox.organization_people(w.db, ORG, ("dpo",)), "a user with no organization recorded is not dropped"


def test_ordinary_failures_are_reported_to_the_administrators_once_a_day_and_not_about_themselves(world, provider):
    w = world
    provider.answer = {"status": mail.STATUS_FAILED, "ok": False, "provider": "fake", "error": "refused", "permanent": True}
    for n in (1, 2):
        nc = _insert(w.db, "grid_non_conformances", audit_id=w.audit_a, title=f"F{n}", status="open",
                     assigned_to=w.people["owner"])
        outbox.enqueue(w.db, "audit.finding", recipient_user_id=w.people["owner"], org_id=ORG,
                       route=f"/grid/?open=nc:{nc}", fields={"reference": "AU-1"}, source=("grid", "nc", nc),
                       purpose="assigned")
    w.db.commit()
    outbox.deliver_due(w.db)
    assert outbox.report_failures(w.db, ORG) == 2
    assert outbox.report_failures(w.db, ORG) == 2, "asking again is the same two messages"
    rows = _outbox(w, "delivery.failure")
    assert _who(w, rows) == ["boss", "chief"] and len(rows) == 2
    assert json.loads(rows[0]["fields_json"]) == {"count": 2}
    provider.answer = {"status": mail.STATUS_ACCEPTED, "ok": True, "provider": "fake"}
    outbox.deliver_due(w.db)
    texts = [c["text"] for c in provider.calls]
    assert any("2 notification(s) could not be accepted" in t and "/admin/email" in t for t in texts)
    assert "Finding" not in " ".join(texts) and "F1" not in " ".join(texts)
    assert outbox.report_failures(w.db, ORG) == 2
    assert len(_outbox(w, "delivery.failure")) == 2, "the report is not counted as a failure it reports"


# ── The summaries a person asked for ────────────────────────────────────────

def _ten_past(w, hour, day_offset=0):
    from datetime import datetime
    base = datetime(w.today.year, w.today.month, w.today.day) + timedelta(days=day_offset)
    return base.replace(hour=hour, minute=10)


def test_a_daily_summary_counts_what_my_work_shows_once_a_day_after_seven_their_time(world, provider):
    from modules.launcher import summary_mail
    w = world
    summary_mail._checked.clear()
    owner = w.people["owner"]
    _insert(w.db, "user_preferences", user_id=owner, pref_key="email.mode", pref_value="daily")
    _insert(w.db, "task_board", title="Overdue", assigned_to=owner, created_by=owner, status="todo",
            due_date=(w.today - timedelta(days=2)).isoformat())
    _insert(w.db, "task_board", title="Open", assigned_to=owner, created_by=owner, status="todo")
    _insert(w.db, "task_board", title="Done", assigned_to=owner, created_by=owner, status="done")
    assert summary_mail.ask_summaries(w.db, ORG, now=_ten_past(w, 5)) == 0, "before 07:00"
    assert summary_mail.ask_summaries(w.db, ORG, now=_ten_past(w, 8)) == 1
    assert summary_mail.ask_summaries(w.db, ORG, now=_ten_past(w, 9)) == 0, "once a day"
    (row,) = _outbox(w, "summary.mywork")
    assert row["recipient_user_id"] == owner and json.loads(row["fields_json"]) == {"count": 2, "overdue": 1}
    assert row["route"] == "/my-work" and "Overdue" not in row["fields_json"]
    assert summary_mail.ask_summaries(w.db, ORG, now=_ten_past(w, 8, day_offset=1)) == 1, "and again the next day"


def test_a_summary_uses_the_persons_own_clock_and_says_nothing_when_nothing_waits(world):
    from modules.launcher import summary_mail
    w = world
    summary_mail._checked.clear()
    owner = w.people["owner"]
    _insert(w.db, "user_preferences", user_id=owner, pref_key="email.mode", pref_value="daily")
    _insert(w.db, "user_preferences", user_id=owner, pref_key="email.utc_offset", pref_value="120")
    assert summary_mail.ask_summaries(w.db, ORG, now=_ten_past(w, 6)) == 0, "07:10 there, but nothing waits for them"
    _insert(w.db, "task_board", title="Open", assigned_to=owner, created_by=owner, status="todo")
    summary_mail._checked.clear()
    assert summary_mail.ask_summaries(w.db, ORG, now=_ten_past(w, 4)) == 0, "06:10 there is before seven"
    assert summary_mail.ask_summaries(w.db, ORG, now=_ten_past(w, 5)) == 1, "07:10 there"


def test_a_weekly_summary_is_sent_once_in_the_week_it_is_due(world):
    from modules.launcher import summary_mail
    w = world
    summary_mail._checked.clear()
    owner = w.people["owner"]
    _insert(w.db, "user_preferences", user_id=owner, pref_key="email.weekly", pref_value="on")
    _insert(w.db, "task_board", title="Open", assigned_to=owner, created_by=owner, status="todo")
    assert summary_mail.ask_summaries(w.db, ORG, now=_ten_past(w, 9)) == 1
    summary_mail._checked.clear()
    assert summary_mail.ask_summaries(w.db, ORG, now=_ten_past(w, 9)) == 0
    (row,) = _outbox(w, "summary.mywork")
    assert row["purpose"] == "weekly" and _threshold(row).startswith("weekly:")


def test_nobody_gets_a_summary_they_did_not_ask_for(world):
    from modules.launcher import summary_mail
    w = world
    summary_mail._checked.clear()
    _insert(w.db, "task_board", title="Open", assigned_to=w.people["owner"], created_by=w.people["owner"], status="todo")
    assert summary_mail.ask_summaries(w.db, ORG, now=_ten_past(w, 9)) == 0
    assert _outbox(w, "summary.mywork") == []


# ── Sentinel ────────────────────────────────────────────────────────────────

def _breach(w, hours, status="open", unit=None, ref="BRE-2026-001"):
    deadline = _stamp(utcnow() + timedelta(hours=hours))
    return _insert(w.db, "sentinel_breaches", ref_number=ref, title="Payroll database exposed", status=status,
                   business_unit_id=unit if unit is not None else w.unit_a, notify_deadline=deadline)


def test_a_breach_deadline_goes_to_the_named_privacy_officers_and_never_to_the_first_user(world, provider):
    from modules.sentinel import scheduler as sched
    w = world
    breach = _breach(w, 5.5)
    _breach(w, 5.5, status="closed", ref="BRE-2026-002")
    sched._breach_deadline_check()
    sched._breach_deadline_check()
    rows = _outbox(w, "privacy.deadline")
    assert _who(w, rows) == ["dpo_a", "dpo_b"], "the DPO role, in this organization; not first, not the inactive one"
    assert {(r["source_id"], _threshold(r), r["priority"]) for r in rows} == {(breach, "6h", "critical")}
    text = rows[0]["fields_json"]
    assert "Payroll database exposed" not in text and json.loads(text)["reference"] == "BRE-2026-001"
    outbox.deliver_due(w.db)
    assert [c["to"] for c in provider.calls] == ["dpo_a@example.test"], "the officer of another unit may not open it"
    suppressed = [r for r in _outbox(w) if r["status"] == "suppressed"]
    assert [r["suppress_reason"] for r in suppressed] == ["not_allowed_to_open_the_record"]
    assert "https://app.themisiq.net/sentinel/?open=breach:" in provider.calls[0]["text"]


def test_the_in_app_notice_is_made_once_and_says_when_nobody_is_named(world):
    from modules.sentinel import scheduler as sched
    w = world
    w.db.execute("DELETE FROM user_roles WHERE role_key = 'dpo'")
    w.db.commit()
    _breach(w, 5.5)
    sched._breach_deadline_check()
    sched._breach_deadline_check()
    assert _outbox(w) == [], "no one is named, so nothing is asked for: the first user is not a DPO"
    notices = [dict(r) for r in w.db.execute(
        "SELECT user_id, title, message FROM notifications WHERE module = 'sentinel'").fetchall()]
    ids = [n["user_id"] for n in notices]
    assert w.people["chief"] in ids and len(ids) == len(set(ids)), "one notice each, although the job ran twice"
    assert all("No privacy officer is named" in n["message"] and "URGENT" in n["title"] for n in notices)
    flag = w.db.execute("SELECT breach_notified_6h FROM sentinel_breaches").fetchone()[0]
    assert flag == 1


def test_a_request_deadline_names_a_reference_and_a_date_and_not_the_data_subject(world):
    from modules.sentinel import scheduler as sched
    w = world
    three = (w.today + timedelta(days=3)).isoformat()
    dsr = _insert(w.db, "sentinel_dsr", ref_number="DSR-2026-007", requester_name="Jane Citizen",
                  requester_email="jane@example.test", request_type="Access", deadline_date=three, status="open",
                  business_unit_id=w.unit_a)
    _insert(w.db, "sentinel_dsr", ref_number="DSR-2026-008", requester_name="Far Away", request_type="Erasure",
            deadline_date=(w.today + timedelta(days=4)).isoformat(), status="open", business_unit_id=w.unit_a)
    sched._dsr_deadline_check()
    rows = _outbox(w, "privacy.dsr")
    assert [(r["source_id"], _threshold(r)) for r in rows] == [(dsr, "d3"), (dsr, "d3")]
    assert _who(w, rows) == ["dpo_a", "dpo_b"]
    for r in rows:
        assert "Jane Citizen" not in r["fields_json"] and "Access" not in r["fields_json"]
        assert json.loads(r["fields_json"]) == {"reference": "DSR-2026-007", "due": three}
        assert r["priority"] == "critical", "a statutory deadline is not turned off by a preference"


# ── Reminders ───────────────────────────────────────────────────────────────

def _reminder(w, **kw):
    cols = dict(module="grid", title="Renew the policy", message="Please renew it.", recipient_email="owner@example.test",
                remind_at=_stamp(utcnow() - timedelta(minutes=5)))
    cols.update(kw)
    return _insert(w.db, "email_reminders", **cols)


def _reminder_row(w, rid):
    return dict(w.db.execute("SELECT * FROM email_reminders WHERE id = %s", (rid,)).fetchone())


def test_a_reminder_is_marked_sent_only_when_the_provider_accepted_it(world, monkeypatch):
    from core import reminder_scheduler as rs
    w = world
    fake = Provider()
    monkeypatch.setattr(rs, "send_email", fake)
    kept = _reminder(w)
    recurring = _reminder(w, title="Weekly check", repeat_interval="weekly")
    rs._process_due_reminders()
    for rid in (kept, recurring):
        row = _reminder_row(w, rid)
        assert row["is_sent"] == 1 and row["delivery_status"] == "provider_accepted" and row["sent_at"]
    nxt = w.db.execute("SELECT remind_at FROM email_reminders WHERE title = 'Weekly check' AND is_sent = 0").fetchall()
    assert len(nxt) == 1, "the next occurrence of a recurring reminder is created once its predecessor was accepted"
    rs._process_due_reminders()
    assert len(fake.calls) == 2, "an accepted reminder is not sent again"


def test_a_logged_only_reminder_stays_due_and_says_so(world, monkeypatch):
    from core import reminder_scheduler as rs
    w = world
    fake = Provider()
    fake.answer = {"status": mail.STATUS_LOGGED, "ok": False, "provider": "console"}
    monkeypatch.setattr(rs, "send_email", fake)
    rid = _reminder(w)
    rs._process_due_reminders()
    row = _reminder_row(w, rid)
    assert row["is_sent"] == 0 and row["sent_at"] is None and row["delivery_status"] == "logged_only"
    assert "nothing was sent" in row["delivery_error"]


def test_a_reminder_with_no_usable_address_is_suppressed_not_sent(world, monkeypatch):
    from core import reminder_scheduler as rs
    w = world
    fake = Provider()
    monkeypatch.setattr(rs, "send_email", fake)
    rid = _reminder(w, recipient_email="not-an-address")
    rs._process_due_reminders()
    row = _reminder_row(w, rid)
    assert row["is_sent"] == 0 and row["delivery_status"] == "suppressed" and fake.calls == []


def test_a_failing_reminder_stops_after_five_attempts_and_a_permanent_failure_at_once(world, monkeypatch):
    from core import reminder_scheduler as rs
    w = world
    fake = Provider()
    fake.answer = {"status": mail.STATUS_FAILED, "ok": False, "provider": "fake", "error": "TimeoutError"}
    monkeypatch.setattr(rs, "send_email", fake)
    rid = _reminder(w)
    for _ in range(rs.MAX_ATTEMPTS + 2):
        rs._process_due_reminders()
    row = _reminder_row(w, rid)
    assert row["delivery_status"] == "permanent_failure" and row["attempts"] == rs.MAX_ATTEMPTS and row["is_sent"] == 0
    assert len(fake.calls) == rs.MAX_ATTEMPTS
    fake.answer = {"status": mail.STATUS_FAILED, "ok": False, "provider": "fake", "error": "refused", "permanent": True}
    rid = _reminder(w, title="Another")
    rs._process_due_reminders()
    assert _reminder_row(w, rid)["delivery_status"] == "permanent_failure"
    assert _reminder_row(w, rid)["attempts"] == 1


def test_a_reminder_title_is_escaped_in_the_message(world, monkeypatch):
    from core import reminder_scheduler as rs
    w = world
    fake = Provider()
    monkeypatch.setattr(rs, "send_email", fake)
    _reminder(w, title="<img src=x onerror=alert(1)>", message="a < b & c")
    rs._process_due_reminders()
    html = fake.calls[0]["html"]
    assert "<img" not in html and "&lt;img" in html and "a &lt; b &amp; c" in html


# ── Administration ──────────────────────────────────────────────────────────

def _admin_call(coro):
    response = asyncio.run(coro)
    return response.status_code, json.loads(response.body)


def _admin_request(w, payload=None):
    import types
    from modules.launcher import _route_helpers  # noqa: F401  (imports the helpers the routes use)
    user = {"id": w.people["chief"], "username": "chief", "org_id": ORG, "email": "chief@example.test",
            "business_unit_id": None, "is_super_admin": 0, "roles": ["super_admin"]}
    request = types.SimpleNamespace(state=types.SimpleNamespace(user=user), url=types.SimpleNamespace(path="/api/x"),
                                    query_params={}, client=None, headers={})
    if payload is not None:
        async def _json():
            return payload
        request.json = _json
    return request


@pytest.fixture
def signed_in(monkeypatch):
    from core import middleware

    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)


def _setting(w, key):
    row = w.db.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else None


def test_a_new_password_is_not_stored_in_the_database_unless_the_operator_allowed_it(world, signed_in, monkeypatch):
    from modules.launcher import routes_admin as admin
    w = world
    monkeypatch.delenv("EMAIL_ALLOW_DB_SECRETS", raising=False)
    payload = {"provider": "google", "smtp_host": "smtp.gmail.com", "smtp_port": "587",
               "smtp_user": "themisiq.alerts@gmail.com", "smtp_pass": "app-password-1234", "smtp_from": ""}
    status, body = _admin_call(admin.api_email_config_save(_admin_request(w, payload)))
    assert status == 200 and body["secrets_not_saved"] == ["smtp_pass"] and "environment" in body["notice"]
    assert _setting(w, "smtp_user") == "themisiq.alerts@gmail.com" and _setting(w, "smtp_pass_enc") is None
    monkeypatch.setenv("EMAIL_ALLOW_DB_SECRETS", "true")
    status, body = _admin_call(admin.api_email_config_save(_admin_request(w, payload)))
    assert status == 200 and "secrets_not_saved" not in body
    stored = _setting(w, "smtp_pass_enc")
    assert stored and "app-password-1234" not in stored, "obscured, never the plain value"
    status, cfg = _admin_call(admin.api_email_config_get(_admin_request(w)))
    assert cfg["smtp_pass"] == "__unchanged__" and "app-password-1234" not in json.dumps(cfg)
    assert cfg["health"]["credential_source"] == "stored_obscured"
    assert any("obscured but not encrypted" in warning for warning in cfg["health"]["warnings"])


def test_clearing_the_stored_secrets_needs_a_confirmation_and_removes_only_the_secrets(world, signed_in):
    from modules.launcher import routes_admin as admin
    w = world
    for key, value in (("smtp_pass_enc", "abc"), ("ms_client_secret_enc", "def"), ("smtp_host", "smtp.gmail.com")):
        w.db.execute("INSERT INTO settings(key, value) VALUES (%s, %s)", (key, value))
    w.db.commit()
    with pytest.raises(HTTPException) as refused:
        asyncio.run(admin.api_email_clear_secrets(_admin_request(w, {})))
    assert refused.value.status_code == 400 and _setting(w, "smtp_pass_enc") == "abc"
    status, body = _admin_call(admin.api_email_clear_secrets(_admin_request(w, {"confirm": True})))
    assert status == 200 and sorted(body["cleared"]) == ["ms_client_secret_enc", "smtp_pass_enc"]
    assert _setting(w, "smtp_pass_enc") is None and _setting(w, "smtp_host") == "smtp.gmail.com"


def test_the_test_message_never_calls_console_mode_a_delivery(world, signed_in, monkeypatch):
    from modules.launcher import routes_admin as admin
    w = world
    monkeypatch.setattr(mail, "_resolve_provider", lambda: "console")
    status, body = _admin_call(admin.api_email_test(_admin_request(w)))
    assert body["ok"] is False and body["status"] == mail.STATUS_LOGGED and "nothing was sent" in body["detail"]
    assert _setting(w, "email_last_test_result").startswith("FAIL ")

    calls = []

    def accepted(**kwargs):
        calls.append(kwargs)
        return {"status": mail.STATUS_ACCEPTED, "ok": True, "provider": "smtp"}

    monkeypatch.setattr(mail, "test_connection", lambda: {"ok": True, "status": "configured", "provider": "smtp",
                                                          "detail": "login succeeded"})
    monkeypatch.setattr(mail, "send_email", accepted)
    status, body = _admin_call(admin.api_email_test(_admin_request(w)))
    assert body["ok"] is True and body["confirm_receipt"] is True and "Accepted is not received" in body["detail"]
    assert calls[0]["to"] == "chief@example.test" and calls[0]["body_text"] and "<script" not in calls[0]["body_html"]
    status, body = _admin_call(admin.api_email_test_receipt(_admin_request(w, {"received": False})))
    assert body["last_receipt"].startswith("Not received") and _setting(w, "email_last_receipt").startswith("Not received")


def test_the_delivery_queue_is_visible_and_a_sent_message_cannot_be_queued_again(world, signed_in, provider):
    from modules.launcher import routes_admin as admin
    w = world
    nc = _insert(w.db, "grid_non_conformances", audit_id=w.audit_a, title="Finding", status="open",
                 assigned_to=w.people["owner"], due_date=(w.today + timedelta(days=9)).isoformat())
    provider.answer = {"status": mail.STATUS_LOGGED, "ok": False, "provider": "console"}
    stuck = outbox.enqueue(w.db, "audit.finding", recipient_user_id=w.people["owner"], org_id=ORG,
                           route=f"/grid/?open=nc:{nc}", fields={"reference": "AU-1"}, source=("grid", "nc", nc),
                           purpose="assigned")
    w.db.commit()
    outbox.deliver_due(w.db)
    status, body = _admin_call(admin.api_email_outbox(_admin_request(w)))
    assert body["counts"] == {"logged_only": 1}
    assert [(a["id"], a["status"]) for a in body["attention"]] == [(stuck, "logged_only")]
    assert "owner@example.test" not in json.dumps(body) and "AU-1" not in json.dumps(body), "no recipient, no text"

    provider.answer = {"status": mail.STATUS_ACCEPTED, "ok": True, "provider": "fake"}
    status, _ = _admin_call(admin.api_email_outbox_requeue(_admin_request(w), stuck))
    assert status == 200
    outbox.deliver_due(w.db)
    with pytest.raises(HTTPException) as again:
        asyncio.run(admin.api_email_outbox_requeue(_admin_request(w), stuck))
    assert again.value.status_code == 409, "a message that was sent is not queued again"
    with pytest.raises(HTTPException) as gone:
        asyncio.run(admin.api_email_outbox_requeue(_admin_request(w), 99999))
    assert gone.value.status_code == 409


def test_a_person_can_set_their_mail_choices_and_only_with_valid_values(world, signed_in):
    from modules.launcher import routes_auth as auth
    w = world

    def put(payload):
        return _admin_call(auth.api_my_email_preferences_put(_admin_request(w, payload)))

    status, got = _admin_call(auth.api_my_email_preferences(_admin_request(w)))
    assert got == {"action": True, "mode": "immediate", "weekly": False, "quiet": None, "utc_offset": 0}
    assert put({"action": False})[1]["action"] is False and _setting_pref(w, "email.action") == "off"
    assert put({"action": True, "mode": "daily", "weekly": True})[1]["mode"] == "daily"
    got = put({"quiet": {"start": "22:00", "end": "7:30"}, "utc_offset": 120})[1]
    assert got["quiet"] == {"start": "22:00", "end": "07:30"} and got["utc_offset"] == 120
    assert _setting_pref(w, "email.quiet") == "22:00-07:30"
    assert put({"quiet": None})[1]["quiet"] is None
    for bad in ({"action": "no"}, {"mode": "hourly"}, {"weekly": 1}, {"utc_offset": 7}, {"utc_offset": 900},
                {"quiet": {"start": "25:00", "end": "07:00"}}, {"quiet": {"start": "08:00", "end": "08:00"}},
                {"quiet": "always"}, {"something": True}, {}):
        status, body = put(bad)
        assert status == 400 and "error" in body, bad
    assert _setting_pref(w, "email.mode") == "daily", "a refused change leaves the choices as they were"


def _setting_pref(w, key):
    row = w.db.execute("SELECT pref_value FROM user_preferences WHERE user_id = %s AND pref_key = %s",
                       (w.people["chief"], key)).fetchone()
    return row["pref_value"] if row else None


def test_sending_can_be_paused_and_resumed_by_an_administrator(world, signed_in):
    from modules.launcher import routes_admin as admin
    w = world
    assert _admin_call(admin.api_email_outbox_pause(_admin_request(w, {"paused": True})))[1] == {"paused": True}
    assert outbox.is_paused(w.db) is True
    with pytest.raises(HTTPException) as bad:
        asyncio.run(admin.api_email_outbox_pause(_admin_request(w, {"paused": "yes"})))
    assert bad.value.status_code == 400, "only true or false"
    assert _admin_call(admin.api_email_outbox_pause(_admin_request(w, {"paused": False})))[1] == {"paused": False}
    assert outbox.is_paused(w.db) is False


def test_the_demo_request_mail_is_escaped_and_has_a_text_part(world, monkeypatch):
    import types
    import main
    w = world
    calls = []

    def capture(**kwargs):
        calls.append(kwargs)
        return {"status": mail.STATUS_ACCEPTED, "ok": True, "provider": "fake"}

    monkeypatch.setattr(mail, "send_email", capture)
    monkeypatch.setattr(main.settings, "ADMIN_EMAIL", "founder@example.test")

    async def _json():
        return {"name": "Ann & Bob", "email": "ann@example.test", "company": "A < B Ltd", "plan": "Team"}

    request = types.SimpleNamespace(json=_json, client=types.SimpleNamespace(host="203.0.113.9"))
    response = asyncio.run(main.demo_request(request))
    assert response.status_code == 200
    (call,) = calls
    assert call["to"] == "founder@example.test" and call["body_text"].startswith("Demo request")
    assert "Ann &amp; Bob" in call["body_html"] and "A &lt; B Ltd" in call["body_html"]
