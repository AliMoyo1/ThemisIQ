"""
PLAN-36 P05: evidence collection campaigns -- state machine, self-accept
prevention, cross-org isolation, campaign coverage/close, reminder and
recurrence idempotency.
"""
import pytest

from core.timeutils import utcnow
from modules.evidence_campaigns import data_service as svc


def _org(db, org_id=1):
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, f"org{org_id}", f"org{org_id}"))


def _user(db, uid, org_id=1, username=None, email=None):
    username = username or f"user{uid}"
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
        "VALUES (%s,%s,%s,%s,'x',%s)",
        (uid, username, email or f"{username}@x.com", username, org_id),
    )


def _actor(db, uid):
    row = db.execute(
        "SELECT id, username, full_name, org_id, COALESCE(is_super_admin,0) AS is_super_admin "
        "FROM users WHERE id=%s", (uid,),
    ).fetchone()
    return dict(row)


def _evidence_item(db, org_id, uploaded_by, item_id=1, title="Cert.pdf"):
    db.execute(
        "INSERT INTO evidence_items (id, title, org_id, uploaded_by, status) VALUES (%s,%s,%s,%s,'current')",
        (item_id, title, org_id, uploaded_by),
    )
    return item_id


@pytest.fixture
def scenario(test_db):
    """Author (uid 1, assignee), reviewer (uid 2), bystander (uid 3), all
    org 1. A real evidence_items row for uid 1 to submit."""
    _org(test_db)
    _user(test_db, 1, username="assignee")
    _user(test_db, 2, username="reviewer")
    _user(test_db, 3, username="bystander")
    test_db.commit()
    assignee = _actor(test_db, 1)
    reviewer = _actor(test_db, 2)
    bystander = _actor(test_db, 3)
    request = svc.create_request(
        test_db, reviewer, campaign_id=None, module="grid", entity_type="control", entity_id="42",
        title="SOC 2 report", assignee_id=1, reviewer_id=2, due_date="2099-01-01",
    )
    return {"assignee": assignee, "reviewer": reviewer, "bystander": bystander, "request": request}


# ─────────────────────────────────────────────────────────────────────────
# Creation and object-level authorization
# ─────────────────────────────────────────────────────────────────────────

def test_create_request_notifies_assignee_and_feeds_task_board_and_calendar(test_db, scenario):
    request_id = scenario["request"]["id"]
    notif = test_db.execute("SELECT * FROM notifications WHERE user_id=1").fetchone()
    assert notif is not None
    task = test_db.execute(
        "SELECT * FROM task_board WHERE module='evidence_campaigns' AND entity_type='evidence_request' AND entity_id=%s",
        (request_id,),
    ).fetchone()
    assert task is not None
    assert task["assigned_to"] == 1
    event = test_db.execute(
        "SELECT * FROM calendar_events WHERE module='evidence_campaigns' AND entity_type='evidence_request' AND entity_id=%s",
        (request_id,),
    ).fetchone()
    assert event is not None


def test_only_the_assignee_can_submit(test_db, scenario):
    _evidence_item(test_db, 1, uploaded_by=3)
    test_db.commit()
    with pytest.raises(svc.ForbiddenError):
        svc.submit_request(test_db, scenario["bystander"], scenario["request"]["id"],
                            evidence_id=1, expected_lock_version=1)


def test_assignee_can_submit_with_a_real_evidence_item(test_db, scenario):
    _evidence_item(test_db, 1, uploaded_by=1)
    test_db.commit()
    result = svc.submit_request(test_db, scenario["assignee"], scenario["request"]["id"],
                                 evidence_id=1, expected_lock_version=1)
    assert result["status"] == "submitted"
    assert result["evidence_id"] == 1


def test_submit_rejects_an_evidence_item_from_another_org(test_db, scenario):
    """The evidence_id must resolve through the real scoped fetch -- an id
    that exists but belongs to a different org must not satisfy a request."""
    _org(test_db, org_id=2)
    _user(test_db, 99, org_id=2, username="otherorg")
    test_db.commit()
    _evidence_item(test_db, org_id=2, uploaded_by=99, item_id=1)
    test_db.commit()
    with pytest.raises(svc.CampaignError):
        svc.submit_request(test_db, scenario["assignee"], scenario["request"]["id"],
                            evidence_id=1, expected_lock_version=1)


def test_submit_refuses_a_stale_lock_version(test_db, scenario):
    _evidence_item(test_db, 1, uploaded_by=1)
    test_db.commit()
    with pytest.raises(svc.StaleVersionError):
        svc.submit_request(test_db, scenario["assignee"], scenario["request"]["id"],
                            evidence_id=1, expected_lock_version=99)


# ─────────────────────────────────────────────────────────────────────────
# Self-accept prevention (the direct analog to ARIA's I08)
# ─────────────────────────────────────────────────────────────────────────

def _submit_and_start_review(test_db, scenario):
    _evidence_item(test_db, 1, uploaded_by=1)
    test_db.commit()
    svc.submit_request(test_db, scenario["assignee"], scenario["request"]["id"], evidence_id=1, expected_lock_version=1)
    return svc.start_review(test_db, scenario["reviewer"], scenario["request"]["id"], expected_lock_version=2)


def test_reviewer_can_accept(test_db, scenario):
    reviewed = _submit_and_start_review(test_db, scenario)
    result = svc.decide_request(test_db, scenario["reviewer"], scenario["request"]["id"],
                                 decision="accept", expected_lock_version=reviewed["lock_version"])
    assert result["status"] == "accepted"
    assert result["reviewed_by"] == 2


def test_someone_who_is_not_the_reviewer_cannot_decide(test_db, scenario):
    reviewed = _submit_and_start_review(test_db, scenario)
    with pytest.raises(svc.ForbiddenError):
        svc.decide_request(test_db, scenario["bystander"], scenario["request"]["id"],
                            decision="accept", expected_lock_version=reviewed["lock_version"])


def test_assignee_cannot_self_accept_even_if_somehow_also_the_named_reviewer(test_db):
    """Red/green-relevant: construct the one scenario where the exclusion
    matters -- a request whose assignee_id and reviewer_id are the same
    person (a data-entry mistake, or a role held by one person covering
    both) -- decide_request must still refuse."""
    _org(test_db)
    _user(test_db, 1, username="both")
    test_db.commit()
    actor = _actor(test_db, 1)
    request = svc.create_request(
        test_db, actor, campaign_id=None, module="grid", entity_type="control", entity_id="1",
        title="Self-reviewed", assignee_id=1, reviewer_id=1, due_date="2099-01-01",
    )
    _evidence_item(test_db, 1, uploaded_by=1)
    test_db.commit()
    svc.submit_request(test_db, actor, request["id"], evidence_id=1, expected_lock_version=1)
    reviewed = svc.start_review(test_db, actor, request["id"], expected_lock_version=2)
    with pytest.raises(svc.ForbiddenError):
        svc.decide_request(test_db, actor, request["id"], decision="accept",
                            expected_lock_version=reviewed["lock_version"])


def test_return_requires_a_note(test_db, scenario):
    reviewed = _submit_and_start_review(test_db, scenario)
    with pytest.raises(svc.CampaignError):
        svc.decide_request(test_db, scenario["reviewer"], scenario["request"]["id"],
                            decision="return", notes="", expected_lock_version=reviewed["lock_version"])


def test_returned_request_can_be_resubmitted(test_db, scenario):
    reviewed = _submit_and_start_review(test_db, scenario)
    returned = svc.decide_request(test_db, scenario["reviewer"], scenario["request"]["id"],
                                   decision="return", notes="Wrong document", expected_lock_version=reviewed["lock_version"])
    assert returned["status"] == "returned"
    resubmitted = svc.submit_request(test_db, scenario["assignee"], scenario["request"]["id"],
                                      evidence_id=1, expected_lock_version=returned["lock_version"])
    assert resubmitted["status"] == "submitted"


# ─────────────────────────────────────────────────────────────────────────
# Cross-org isolation
# ─────────────────────────────────────────────────────────────────────────

def test_get_request_is_scoped_to_org(test_db, scenario):
    _org(test_db, org_id=2)
    _user(test_db, 99, org_id=2, username="otherorg")
    test_db.commit()
    other_actor = _actor(test_db, 99)
    assert svc.get_request(test_db, other_actor, scenario["request"]["id"]) is None
    assert svc.get_request(test_db, scenario["assignee"], scenario["request"]["id"]) is not None


# ─────────────────────────────────────────────────────────────────────────
# Cancel
# ─────────────────────────────────────────────────────────────────────────

def test_cancel_requires_a_reason(test_db, scenario):
    with pytest.raises(svc.CampaignError):
        svc.cancel_request(test_db, scenario["reviewer"], scenario["request"]["id"], reason="", expected_lock_version=1)


def test_cancel_is_terminal_and_audited(test_db, scenario):
    result = svc.cancel_request(test_db, scenario["reviewer"], scenario["request"]["id"],
                                 reason="No longer needed", expected_lock_version=1)
    assert result["status"] == "cancelled"
    audit_row = test_db.execute(
        "SELECT * FROM audit_log WHERE module='evidence_campaigns' AND action='cancel'"
    ).fetchone()
    assert audit_row is not None
    with pytest.raises(svc.InvalidTransitionError):
        svc.cancel_request(test_db, scenario["reviewer"], scenario["request"]["id"],
                            reason="again", expected_lock_version=result["lock_version"])


# ─────────────────────────────────────────────────────────────────────────
# Campaign coverage and close-with-override
# ─────────────────────────────────────────────────────────────────────────

def test_campaign_close_refuses_with_unresolved_requests(test_db, scenario):
    campaign = svc.create_campaign(test_db, scenario["reviewer"], name="Q1 Sweep", due_date="2099-01-01")
    svc.create_request(
        test_db, scenario["reviewer"], campaign_id=campaign["id"], module="grid", entity_type="control",
        entity_id="1", title="Open item", assignee_id=1, reviewer_id=2, due_date="2099-01-01",
    )
    with pytest.raises(svc.InvalidTransitionError):
        svc.close_campaign(test_db, scenario["reviewer"], campaign["id"])


def test_campaign_close_with_force_requires_a_reason_and_is_audited(test_db, scenario):
    campaign = svc.create_campaign(test_db, scenario["reviewer"], name="Q1 Sweep", due_date="2099-01-01")
    svc.create_request(
        test_db, scenario["reviewer"], campaign_id=campaign["id"], module="grid", entity_type="control",
        entity_id="1", title="Open item", assignee_id=1, reviewer_id=2, due_date="2099-01-01",
    )
    with pytest.raises(svc.CampaignError):
        svc.close_campaign(test_db, scenario["reviewer"], campaign["id"], force=True, reason="")

    result = svc.close_campaign(test_db, scenario["reviewer"], campaign["id"], force=True, reason="Deadline passed org-wide")
    assert result["status"] == "closed"
    audit_row = test_db.execute(
        "SELECT * FROM audit_log WHERE module='evidence_campaigns' AND action='force_close'"
    ).fetchone()
    assert audit_row is not None


def test_campaign_coverage_counts_by_status(test_db, scenario):
    campaign = svc.create_campaign(test_db, scenario["reviewer"], name="Q1 Sweep", due_date="2099-01-01")
    svc.create_request(test_db, scenario["reviewer"], campaign_id=campaign["id"], module="grid",
                        entity_type="control", entity_id="1", title="A", assignee_id=1, reviewer_id=2, due_date="2099-01-01")
    svc.create_request(test_db, scenario["reviewer"], campaign_id=campaign["id"], module="grid",
                        entity_type="control", entity_id="2", title="B", assignee_id=1, reviewer_id=2, due_date="2099-01-01")
    coverage = svc.campaign_coverage(test_db, scenario["reviewer"], campaign["id"])
    assert coverage["requested"] == 2
    assert coverage["total"] == 2
    assert coverage["uncovered"] == 2


# ─────────────────────────────────────────────────────────────────────────
# Scheduler-facing: overdue transition, reminder idempotency, recurrence
# ─────────────────────────────────────────────────────────────────────────

def test_mark_overdue_transitions_and_records_an_event(test_db, scenario):
    """Force the request's own due_date into the past directly (create_request
    itself validates due_date is provided, not that it's in the future --
    a real campaign's request can legitimately become overdue later)."""
    test_db.execute("UPDATE evidence_requests SET due_date='2000-01-01' WHERE id=%s", (scenario["request"]["id"],))
    test_db.commit()
    count = svc.mark_overdue_requests(test_db, 1)
    assert count == 1
    updated = svc.get_request(test_db, scenario["assignee"], scenario["request"]["id"])
    assert updated["status"] == "overdue"
    events = svc.list_request_events(test_db, scenario["assignee"], scenario["request"]["id"])
    assert events[-1]["to_status"] == "overdue"


def test_mark_overdue_does_not_reprocess_an_already_overdue_request(test_db, scenario):
    test_db.execute("UPDATE evidence_requests SET due_date='2000-01-01' WHERE id=%s", (scenario["request"]["id"],))
    test_db.commit()
    svc.mark_overdue_requests(test_db, 1)
    second_pass = svc.mark_overdue_requests(test_db, 1)
    assert second_pass == 0


def test_schedule_reminders_is_idempotent_across_repeated_calls(test_db, scenario):
    """Red/green-relevant: without the existing-row check, a scheduler tick
    running every few minutes would insert a fresh T-3 reminder every
    single tick for as long as the request stays in 'requested' -- this
    directly tests task_plan.md's own 'reminder retries do not duplicate
    notifications' acceptance line."""
    test_db.execute("UPDATE evidence_requests SET due_date=%s WHERE id=%s",
                     (utcnow().date().isoformat(), scenario["request"]["id"]))
    test_db.commit()
    first = svc.schedule_reminders(test_db, 1)
    second = svc.schedule_reminders(test_db, 1)
    assert first == 1
    assert second == 0
    count = test_db.execute(
        "SELECT COUNT(*) AS n FROM email_reminders WHERE entity_id=%s", (scenario["request"]["id"],)
    ).fetchone()["n"]
    assert count == 1


def test_generate_recurring_campaigns_is_idempotent(test_db, scenario):
    campaign = svc.create_campaign(test_db, scenario["reviewer"], name="Monthly Check", due_date="2026-01-01", recurrence="monthly")
    svc.close_campaign(test_db, scenario["reviewer"], campaign["id"])  # no requests, closes cleanly
    first = svc.generate_recurring_campaigns(test_db, 1)
    second = svc.generate_recurring_campaigns(test_db, 1)
    assert first == 1
    assert second == 0
    children = test_db.execute(
        "SELECT COUNT(*) AS n FROM evidence_campaigns WHERE recurrence_source_id=%s", (campaign["id"],)
    ).fetchone()["n"]
    assert children == 1
