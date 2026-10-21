"""
The email outbox: one delivery per action, person and threshold, resolved at the moment of sending, with a state that is a
fact about mail and nothing else (plans/2026-10-governance-rework/06 sections 3, 6 and 9, phase E2).

Expectations are written by hand. Each "is not sent" has a positive twin: the same message to a person for whom nothing
is wrong is sent.
"""
from datetime import datetime, timedelta

import pytest

from core import email as mail
from core import email_outbox as outbox
from core.timeutils import utcnow

ORG = 1


def _insert(db, table, **cols):
    cur = db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                     tuple(cols.values()))
    db.commit()
    return cur.lastrowid


class Provider:
    """A fake provider that records what it was asked to send and answers as told."""

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
def desk(test_db):
    db = test_db
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,'org','org')", (ORG,))
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (2,'other','other')")
    db.commit()
    unit_a = _insert(db, "business_units", name="Unit A", is_active=1)
    unit_b = _insert(db, "business_units", name="Unit B", is_active=1)
    people = {}
    for name, role, org, unit, address in (
            ("lead", "audit_lead", ORG, unit_a, "lead@example.test"),
            ("lead_b", "audit_lead", ORG, unit_b, "lead-b@example.test"),
            ("outsider", "audit_lead", 2, None, "outsider@example.test"),
            ("noaddr", "audit_lead", ORG, unit_a, ""),
            ("gone", "audit_lead", ORG, unit_a, "gone@example.test")):
        uid = _insert(db, "users", username=name, email=address, full_name=name, password_hash="x", org_id=org,
                      business_unit_id=unit, is_active=0 if name == "gone" else 1)
        _insert(db, "user_roles", user_id=uid, role_key=role)
        people[name] = uid
    audit_a = _insert(db, "grid_audits", name="Audit A", business_unit_id=unit_a)
    audit_b = _insert(db, "grid_audits", name="Audit B", business_unit_id=unit_b)
    nc_a = _insert(db, "grid_non_conformances", audit_id=audit_a, title="Finding A", assigned_to=people["lead"],
                   status="open", due_date="2026-10-23")
    nc_b = _insert(db, "grid_non_conformances", audit_id=audit_b, title="Finding B", assigned_to=people["lead"],
                   status="open", due_date="2026-10-23")
    return type("Desk", (), dict(db=db, people=people, nc_a=nc_a, nc_b=nc_b, unit_a=unit_a, unit_b=unit_b))


def _ask(desk, to="lead", nc=None, org=ORG, purpose="assigned", threshold="", **kw):
    return outbox.enqueue(
        desk.db, "audit.finding", recipient_user_id=desk.people[to], org_id=org,
        route=f"/grid/?open=nc:{nc or desk.nc_a}", fields={"reference": "AU-27", "due": "2026-10-23"},
        source=("grid", "nc", nc or desk.nc_a), purpose=purpose, threshold=threshold, **kw)


def _row(desk, outbox_id):
    return dict(desk.db.execute("SELECT * FROM email_outbox WHERE id = %s", (outbox_id,)).fetchone())


def test_asking_twice_for_the_same_action_person_and_threshold_is_one_message(desk, provider):
    first = _ask(desk)
    again = _ask(desk)
    assert first and again == first
    assert desk.db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == 1
    assert outbox.deliver_due(desk.db)[outbox.ACCEPTED] == 1
    assert len(provider.calls) == 1 and provider.calls[0]["to"] == "lead@example.test"
    assert outbox.deliver_due(desk.db)["examined"] == 0, "nothing is left to send"
    other = _ask(desk, threshold="due:2026-11-01")
    assert other != first, "a corrected due date is a new threshold and may be told again"


def test_an_accepted_message_is_a_provider_acceptance_and_nothing_more(desk, provider):
    row_id = _ask(desk)
    outbox.deliver_due(desk.db)
    row = _row(desk, row_id)
    assert row["status"] == "provider_accepted" and row["provider"] == "fake" and row["sent_at"]
    assert row["attempts"] == 1 and row["last_error"] is None
    call = provider.calls[0]
    assert call["subject"] == "ThemisIQ: a corrective action is assigned to you"
    assert "https://app.themisiq.net/grid/?open=nc:" in call["text"] and "Finding A" not in call["text"]
    assert "Finding A" not in call["html"] and "Audit A" not in call["html"], "a title is not in the message"


def test_a_message_logged_only_is_not_delivered_and_can_be_queued_again(desk, provider):
    provider.answer = {"status": mail.STATUS_LOGGED, "ok": False, "provider": "console"}
    row_id = _ask(desk)
    assert outbox.deliver_due(desk.db)[outbox.LOGGED] == 1
    assert _row(desk, row_id)["status"] == "logged_only" and _row(desk, row_id)["sent_at"] is None
    assert outbox.deliver_due(desk.db)["examined"] == 0, "it is not retried by itself"
    assert outbox.summary(desk.db)["attention"][0]["status"] == "logged_only", "the administrator sees it"
    provider.answer = {"status": mail.STATUS_ACCEPTED, "ok": True, "provider": "fake"}
    assert outbox.requeue(desk.db, row_id) is True
    assert outbox.deliver_due(desk.db)[outbox.ACCEPTED] == 1
    assert outbox.requeue(desk.db, row_id) is False, "a sent message cannot be queued again"


def test_a_temporary_failure_waits_with_a_backoff_and_a_permanent_one_stops(desk, provider):
    provider.answer = {"status": mail.STATUS_FAILED, "ok": False, "provider": "fake", "error": "TimeoutError"}
    row_id = _ask(desk)
    now = utcnow()
    outbox.deliver_due(desk.db, now=now)
    row = _row(desk, row_id)
    assert row["status"] == "retry_due" and row["attempts"] == 1 and row["last_error"] == "TimeoutError"
    assert row["next_attempt_at"] > now.strftime("%Y-%m-%d %H:%M:%S"), "not before the backoff"
    assert outbox.deliver_due(desk.db, now=now)["examined"] == 0
    later = now + timedelta(minutes=10)
    for step in range(outbox.MAX_ATTEMPTS):
        outbox.deliver_due(desk.db, now=later + timedelta(hours=step * 7))
    assert _row(desk, row_id)["status"] == "permanent_failure", "the attempts ran out"

    provider.answer = {"status": mail.STATUS_FAILED, "ok": False, "provider": "fake", "error": "refused", "permanent": True}
    row_id = _ask(desk, purpose="second")
    outbox.deliver_due(desk.db)
    assert _row(desk, row_id)["status"] == "permanent_failure" and _row(desk, row_id)["attempts"] == 1


def test_a_critical_message_that_cannot_be_sent_is_shown_to_an_administrator_in_the_app(desk, provider):
    admin = _insert(desk.db, "users", username="root", email="root@example.test", full_name="root", password_hash="x",
                    org_id=ORG, is_active=1)
    _insert(desk.db, "user_roles", user_id=admin, role_key="super_admin")
    provider.answer = {"status": mail.STATUS_FAILED, "ok": False, "provider": "fake", "error": "refused", "permanent": True}
    _ask(desk, priority="critical")
    outbox.deliver_due(desk.db)
    notice = desk.db.execute("SELECT title, link FROM notifications WHERE user_id = %s", (admin,)).fetchone()
    assert notice["title"] == "A critical notification could not be sent by email" and notice["link"] == "/admin/email"


def test_a_message_is_not_sent_to_someone_it_should_not_reach(desk, provider):
    cases = {
        "gone": "recipient_inactive",
        "noaddr": "no_valid_address",
        "outsider": "recipient_in_another_organization",
    }
    for person, reason in cases.items():
        row_id = _ask(desk, to=person, purpose=person)
        outbox.deliver_due(desk.db)
        row = _row(desk, row_id)
        assert row["status"] == "suppressed" and row["suppress_reason"] == reason, person
    assert provider.calls == []
    positive = _ask(desk, to="lead", purpose="positive")
    outbox.deliver_due(desk.db)
    assert _row(desk, positive)["status"] == "provider_accepted" and len(provider.calls) == 1


def test_a_record_the_person_may_not_open_is_not_mentioned_to_them(desk, provider):
    """The finding belongs to an audit of unit B. The recipient is an audit lead of unit A."""
    row_id = _ask(desk, nc=desk.nc_b, purpose="b")
    outbox.deliver_due(desk.db)
    row = _row(desk, row_id)
    assert row["status"] == "suppressed" and row["suppress_reason"] == "not_allowed_to_open_the_record", \
        "the finding is assigned to the lead, so it is open; its audit is in another unit"
    assert provider.calls == []


def test_work_that_is_done_or_reassigned_is_not_reminded(desk, provider):
    row_id = _ask(desk, purpose="closed")
    desk.db.execute("UPDATE grid_non_conformances SET status = 'closed' WHERE id = %s", (desk.nc_a,))
    desk.db.commit()
    outbox.deliver_due(desk.db)
    assert _row(desk, row_id)["suppress_reason"] == "no_longer_open"
    desk.db.execute("UPDATE grid_non_conformances SET status = 'open', assigned_to = %s WHERE id = %s",
                    (desk.people["lead_b"], desk.nc_a))
    desk.db.commit()
    row_id = _ask(desk, purpose="moved")
    outbox.deliver_due(desk.db)
    assert _row(desk, row_id)["suppress_reason"] == "no_longer_open", "a transfer stops messages to the prior owner"
    assert provider.calls == []


def test_a_person_can_turn_action_mail_off_but_not_critical_mail(desk, provider):
    _insert(desk.db, "user_preferences", user_id=desk.people["lead"], pref_key="email.action", pref_value="off")
    quiet = _ask(desk, purpose="quiet")
    urgent = _ask(desk, purpose="urgent", priority="critical")
    outbox.deliver_due(desk.db)
    assert _row(desk, quiet)["suppress_reason"] == "preference_off"
    assert _row(desk, urgent)["status"] == "provider_accepted"


def test_the_daily_cap_postpones_ordinary_mail_and_lets_critical_mail_through(desk, provider):
    first = _ask(desk, purpose="one")
    second = _ask(desk, purpose="two")
    urgent = _ask(desk, purpose="three", priority="critical")
    summary = outbox.deliver_due(desk.db, cap=1)
    assert _row(desk, urgent)["status"] == "provider_accepted", "critical goes first and is allowed past the cap"
    postponed = [_row(desk, i)["status"] for i in (first, second)]
    assert sorted(postponed) == ["provider_accepted", "retry_due"] or postponed == ["retry_due", "retry_due"]
    assert summary[outbox.ACCEPTED] >= 1


def test_a_second_worker_cannot_send_what_the_first_has_leased(desk, provider):
    row_id = _ask(desk)
    future = utcnow() + timedelta(minutes=outbox.LEASE_MINUTES)
    desk.db.execute("UPDATE email_outbox SET status = 'sending', leased_until = %s WHERE id = %s",
                    (future.strftime("%Y-%m-%d %H:%M:%S"), row_id))
    desk.db.commit()
    assert outbox.deliver_due(desk.db)["examined"] == 0
    assert provider.calls == []


def test_a_message_whose_worker_died_is_sent_again_once_its_lease_has_run_out(desk, provider):
    row_id = _ask(desk)
    past = utcnow() - timedelta(minutes=1)
    desk.db.execute("UPDATE email_outbox SET status = 'sending', leased_until = %s WHERE id = %s",
                    (past.strftime("%Y-%m-%d %H:%M:%S"), row_id))
    desk.db.commit()
    assert outbox.deliver_due(desk.db)[outbox.ACCEPTED] == 1
    assert len(provider.calls) == 1 and _row(desk, row_id)["status"] == "provider_accepted"


def test_a_pause_holds_everything_except_critical_mail_until_it_is_lifted(desk, provider):
    ordinary = _ask(desk, purpose="ordinary")
    urgent = _ask(desk, purpose="urgent", priority="critical")
    outbox.set_paused(desk.db, True)
    desk.db.commit()
    assert outbox.summary(desk.db)["paused"] is True
    outbox.deliver_due(desk.db)
    assert _row(desk, urgent)["status"] == "provider_accepted", "a forgotten pause never costs a deadline alert"
    assert _row(desk, ordinary)["status"] == "queued"
    outbox.set_paused(desk.db, False)
    desk.db.commit()
    assert outbox.summary(desk.db)["paused"] is False
    outbox.deliver_due(desk.db)
    assert _row(desk, ordinary)["status"] == "provider_accepted"


def test_deliveries_are_compared_by_provider_and_state(desk, provider):
    _ask(desk, purpose="one")
    _ask(desk, purpose="two")
    provider.answer = {"status": mail.STATUS_FAILED, "ok": False, "provider": "newprovider", "error": "refused",
                       "permanent": True}
    outbox.deliver_due(desk.db, limit=1)
    provider.answer = {"status": mail.STATUS_ACCEPTED, "ok": True, "provider": "newprovider"}
    outbox.deliver_due(desk.db)
    got = outbox.summary(desk.db)["by_provider"]
    assert got == {"newprovider": {"permanent_failure": 1, "provider_accepted": 1}}, got


def _pref(desk, who, **prefs):
    for key, value in prefs.items():
        _insert(desk.db, "user_preferences", user_id=desk.people[who], pref_key=f"email.{key}", pref_value=value)


def test_quiet_hours_are_read_in_the_persons_own_time():
    def prefs(quiet, offset):
        return {"quiet": outbox._parse_quiet(quiet), "utc_offset": offset}

    noon = datetime(2026, 10, 15, 12, 0)
    assert outbox.quiet_until(prefs("22:00-07:00", 0), noon) is None
    assert outbox.quiet_until(prefs("22:00-07:00", 0), datetime(2026, 10, 15, 23, 0)) == datetime(2026, 10, 16, 7, 0)
    assert outbox.quiet_until(prefs("22:00-07:00", 0), datetime(2026, 10, 15, 3, 0)) == datetime(2026, 10, 15, 7, 0)
    assert outbox.quiet_until(prefs("12:00-14:00", 0), noon) == datetime(2026, 10, 15, 14, 0)
    assert outbox.quiet_until(prefs("22:00-07:00", 120), datetime(2026, 10, 15, 20, 30)) == datetime(2026, 10, 16, 5, 0), \
        "22:30 in UTC+2 is inside, and 07:00 there is 05:00 UTC"
    assert outbox.quiet_until(prefs("22:00-07:00", 120), datetime(2026, 10, 15, 19, 30)) is None, "21:30 there is outside"
    assert outbox._parse_quiet("07:00-07:00") is None and outbox._parse_quiet("nonsense") is None
    assert outbox._parse_quiet("24:00-07:00") is None


def test_ordinary_mail_waits_out_quiet_hours_and_critical_mail_does_not(desk, provider):
    _pref(desk, "lead", quiet="22:00-07:00", utc_offset="120")
    ordinary = _ask(desk, purpose="ordinary")
    urgent = _ask(desk, purpose="urgent", priority="critical")
    outbox.deliver_due(desk.db, now=datetime(2026, 10, 15, 23, 30))
    assert _row(desk, urgent)["status"] == "provider_accepted", "a deadline alert is sent at any hour"
    waiting = _row(desk, ordinary)
    assert waiting["status"] == "retry_due" and waiting["attempts"] == 0, "waiting is not a failed attempt"
    assert waiting["next_attempt_at"] == "2026-10-16 05:00:00" and waiting["last_error"] == "quiet hours; postponed"
    assert outbox.deliver_due(desk.db, now=datetime(2026, 10, 16, 4, 59))["examined"] == 0
    assert outbox.deliver_due(desk.db, now=datetime(2026, 10, 16, 5, 1))[outbox.ACCEPTED] == 1


def test_a_daily_summary_replaces_each_action_mail_but_not_critical_mail_or_a_summary_asked_for(desk, provider):
    _pref(desk, "lead", mode="daily", action="off")
    one = _ask(desk, purpose="one")
    urgent = _ask(desk, purpose="urgent", priority="critical")
    lead = desk.people["lead"]
    summary = outbox.enqueue(desk.db, "summary.mywork", recipient_user_id=lead, org_id=ORG, route="/my-work",
                             fields={"count": 3, "overdue": 1}, source=("platform", "summary", lead), purpose="daily",
                             threshold="daily:2026-10-15")
    desk.db.commit()
    outbox.deliver_due(desk.db)
    assert _row(desk, one)["status"] == "suppressed" and _row(desk, one)["suppress_reason"] == "preference_off"
    assert _row(desk, urgent)["status"] == "provider_accepted"
    assert _row(desk, summary)["status"] == "provider_accepted", "a summary a person asked for is not switched off"
    assert "3 item(s) that need you, 1 of them overdue" in provider.calls[-1]["text"]
    # with action mail on and the daily mode chosen, each action is covered by the summary instead
    desk.db.execute("UPDATE user_preferences SET pref_value = 'on' WHERE user_id = %s AND pref_key = 'email.action'", (lead,))
    desk.db.commit()
    two = _ask(desk, purpose="two")
    outbox.deliver_due(desk.db)
    assert _row(desk, two)["suppress_reason"] == "in_daily_summary"


def test_a_producer_never_loses_its_own_work_to_a_mail_problem(desk):
    assert outbox.enqueue_safely(desk.db, "evidence.renew", recipient_user_id=1, org_id=ORG, route="/evidence/",
                                 fields={"reference": "a free text title, not a code"}, source=("evidence", "item", 1),
                                 purpose="renew") is None
    assert outbox.enqueue_safely(desk.db, "no.such.template", recipient_user_id=1, org_id=ORG, route="/x",
                                 fields={}, source=("a", "b", 1), purpose="p") is None
    assert desk.db.execute("SELECT COUNT(*) FROM email_outbox").fetchone()[0] == 0


# ── The send budget and the purge (plans/2026-10-governance-rework/14) ──────

def test_ordinary_mail_goes_out_at_the_per_minute_budget_and_critical_mail_is_never_held(desk, provider):
    for i in range(25):
        _ask(desk, threshold=f"day:{i}")
    for i in range(3):
        _ask(desk, threshold=f"urgent:{i}", priority="critical")
    first = outbox.deliver_due(desk.db, per_minute=20, limit=100)
    assert first[outbox.ACCEPTED] == 23, "the three critical messages and twenty ordinary ones"
    queued = desk.db.execute("SELECT COUNT(*) FROM email_outbox WHERE status = 'queued'").fetchone()[0]
    assert queued == 5, "the rest wait for the next minute"
    second = outbox.deliver_due(desk.db, per_minute=20, limit=100)
    assert second[outbox.ACCEPTED] == 5
    assert len(provider.calls) == 28


def test_a_suppressed_message_is_a_local_decision_and_does_not_spend_the_budget(desk, provider):
    for i in range(10):
        _ask(desk, to="noaddr", threshold=f"day:{i}")        # no valid address: suppressed, never given to the provider
    for i in range(20):
        _ask(desk, threshold=f"day:{i}")
    got = outbox.deliver_due(desk.db, per_minute=20, limit=100)
    assert got[outbox.SUPPRESSED] == 10 and got[outbox.ACCEPTED] == 20
    assert len(provider.calls) == 20


def test_the_passes_of_one_minute_share_one_budget(desk, provider):
    budget = {"n": 5}
    for i in range(8):
        _ask(desk, threshold=f"day:{i}")
    assert outbox.deliver_due(desk.db, budget=budget, limit=100)[outbox.ACCEPTED] == 5
    assert budget["n"] == 0
    urgent = _ask(desk, threshold="urgent", priority="critical")
    again = outbox.deliver_due(desk.db, budget=budget, limit=100)
    assert again[outbox.ACCEPTED] == 1 and _row(desk, urgent)["status"] == "provider_accepted", \
        "a spent budget holds ordinary mail and lets critical mail through"
    assert desk.db.execute("SELECT COUNT(*) FROM email_outbox WHERE status = 'queued'").fetchone()[0] == 3


def _age(desk, outbox_id, status, days):
    stamp = (utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    desk.db.execute("UPDATE email_outbox SET status = %s, created_at = %s WHERE id = %s", (status, stamp, outbox_id))
    desk.db.commit()


def test_deliveries_that_ended_long_ago_are_deleted_and_nothing_that_is_still_waiting(desk):
    gone = []
    for i, status in enumerate(("provider_accepted", "suppressed", "permanent_failure", "logged_only")):
        row_id = _ask(desk, threshold=f"old:{i}")
        _age(desk, row_id, status, outbox.RETENTION_DAYS + 5)
        gone.append(row_id)
    kept = []
    recent = _ask(desk, threshold="recent")
    _age(desk, recent, "provider_accepted", 10)
    kept.append(recent)
    for i, status in enumerate(("queued", "retry_due", "sending")):
        row_id = _ask(desk, threshold=f"waiting:{i}")
        _age(desk, row_id, status, 400)
        kept.append(row_id)

    assert outbox.purge_old(desk.db) == 4
    desk.db.commit()
    left = {r["id"] for r in desk.db.execute("SELECT id FROM email_outbox").fetchall()}
    assert left == set(kept) and not (left & set(gone))
    assert outbox.purge_old(desk.db) == 0


def test_the_worker_purges_once_a_day_for_each_organization(desk, provider):
    outbox._PURGED_ON.clear()
    first = _ask(desk, threshold="old:1")
    _age(desk, first, "provider_accepted", outbox.RETENTION_DAYS + 1)
    outbox.deliver_all_tenants()
    assert desk.db.execute("SELECT COUNT(*) FROM email_outbox WHERE id = %s", (first,)).fetchone()[0] == 0

    second = _ask(desk, threshold="old:2")
    _age(desk, second, "provider_accepted", outbox.RETENTION_DAYS + 1)
    outbox.deliver_all_tenants()
    assert desk.db.execute("SELECT COUNT(*) FROM email_outbox WHERE id = %s", (second,)).fetchone()[0] == 1, \
        "already purged today by this process"
    outbox._PURGED_ON.clear()
    outbox.deliver_all_tenants()
    assert desk.db.execute("SELECT COUNT(*) FROM email_outbox WHERE id = %s", (second,)).fetchone()[0] == 0
