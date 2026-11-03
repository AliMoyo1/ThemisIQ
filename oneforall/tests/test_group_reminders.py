"""Group oversight reminders (plan 22, C2): the right people, once per stage, nothing released or renewed."""
from datetime import datetime, timedelta, timezone

from modules.evidence import group_documents as group
from modules.evidence import group_reminders as reminders
from modules.evidence import group_requests as requests
from tests.test_group_documents import _activate, _actor, _future, _id, group_world  # noqa: F401 (fixture)


def _at(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(tzinfo=None).isoformat()


def _inbox(db, user):
    return [(r["title"], r["message"]) for r in db.execute(
        "SELECT title, message FROM notifications WHERE user_id=%s AND module='evidence' ORDER BY id",
        (user["id"],)).fetchall()]


def _run_all(db, *orgs):
    return sum(reminders.remind(org) for org in orgs)


def test_grant_reviews_remind_the_other_grant_managers_once_per_stage(group_world):
    db, parent, child, sibling, users, _ = group_world
    relation = _activate(db, parent, child, users)
    grant = group.grant_view(db, users["parent_admin"], relation, users["viewer"]["id"], "figure.view",
                             _future(60), _future(30))
    db.commit()
    assert _run_all(db, parent, child, sibling) == 0, "a review 30 days away is not due yet"
    db.execute("UPDATE group_view_grants SET review_due_at=%s WHERE id=%s", (_at(10), grant))
    db.commit()
    assert _run_all(db, parent, child, sibling) == 1
    assert _run_all(db, parent, child, sibling) == 0, "the same stage is never sent twice"
    assert [t for t, _ in _inbox(db, users["parent_admin"])] == ["Group access review due"]
    assert "Child Co" in _inbox(db, users["parent_admin"])[0][1]
    assert _inbox(db, users["viewer"]) == [], "the person holding the grant is not asked to review it"
    assert _inbox(db, users["ack"]) == [] and _inbox(db, users["sibling"]) == []
    db.execute("UPDATE group_view_grants SET review_due_at=%s WHERE id=%s", (_at(-1), grant))
    db.commit()
    assert _run_all(db, parent, child, sibling) == 1
    assert [t for t, _ in _inbox(db, users["parent_admin"])][-1] == "Group access review overdue"
    row = db.execute("SELECT revoked_at, review_due_at FROM group_view_grants WHERE id=%s", (grant,)).fetchone()
    assert row["revoked_at"] is None and row["review_due_at"] < _at(0), "a reminder never renews access"


def test_an_overdue_proof_request_goes_to_the_source_then_escalates_to_the_requester(group_world):
    db, parent, child, sibling, users, _ = group_world
    relation = _activate(db, parent, child, users)
    request_id = requests.create_request(db, users["viewer"], relation, "Parent control 7.2",
                                         "Need proof of current oversight", _future(14))
    db.commit()
    assert _run_all(db, parent, child, sibling) == 0
    db.execute("UPDATE group_evidence_requests SET needed_by=%s WHERE id=%s", (_at(-2), request_id))
    db.commit()
    assert _run_all(db, parent, child, sibling) == 1
    source_reviewers = [users["legal"], users["privacy"]]
    for person in source_reviewers:
        assert [t for t, _ in _inbox(db, person)] == ["Group proof request overdue"]
        assert "Parent control 7.2" in _inbox(db, person)[0][1] and "Parent Co" in _inbox(db, person)[0][1]
    assert _inbox(db, users["viewer"]) == [], "the requester is not escalated to before the grace period"
    db.execute("UPDATE group_evidence_requests SET needed_by=%s WHERE id=%s", (_at(-8), request_id))
    db.commit()
    assert _run_all(db, parent, child, sibling) == 1
    assert [t for t, _ in _inbox(db, users["viewer"])] == ["Group proof request escalated"]
    assert "Nothing is released automatically" in _inbox(db, users["viewer"])[0][1]
    assert _inbox(db, users["sibling"]) == []
    status = db.execute("SELECT status FROM group_evidence_requests WHERE id=%s", (request_id,)).fetchone()[0]
    assert status == "requested", "escalation decides nothing"
    db.execute("UPDATE group_evidence_requests SET status='no_proof' WHERE id=%s", (request_id,))
    db.commit()
    db.execute("DELETE FROM group_reminders_sent")
    db.commit()
    assert _run_all(db, parent, child, sibling) == 0, "a closed request is never chased"


def test_a_published_policy_left_undecided_reminds_the_receiving_organization(group_world):
    db, parent, child, sibling, users, _ = group_world
    relation = _activate(db, parent, child, users)
    old = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S")
    rights = _id(db, "group_document_rights", source_org_id=parent, evidence_id=1, file_hash="h", rights_state="owned",
                 permit_group_view=1, permit_group_download=0, basis="Owned", reviewed_by=users["parent_admin"]["id"])
    publication = _id(db, "group_document_publications", relationship_id=relation, source_org_id=parent,
                      viewer_org_id=child, evidence_id=1, version=1, file_hash="h", title="Secret policy title",
                      category="policy", classification="internal", purpose="Group governance", rights_id=rights,
                      expires_at=_at(30), approved_by=users["viewer"]["id"], created_at=old)
    assert _run_all(db, parent, child, sibling) == 1
    message = _inbox(db, users["publisher"])
    assert [t for t, _ in message] == ["Group policy awaiting adoption"]
    assert "Secret policy title" not in message[0][1] and "Parent Co" in message[0][1]
    assert _inbox(db, users["sibling"]) == [] and _inbox(db, users["viewer"]) == []
    db.execute("INSERT INTO group_policy_adoptions (publication_id,source_org_id,viewer_org_id,proposed_state,reason,"
               "review_due_at,proposed_by) VALUES (%s,%s,%s,'adopted','Checked',%s,%s)",
               (publication, parent, child, _at(300), users["publisher"]["id"]))
    db.execute("DELETE FROM group_reminders_sent")
    db.commit()
    assert _run_all(db, parent, child, sibling) == 0, "a decision in progress stops the reminder"


def test_run_visits_every_organization_and_survives_a_failure(group_world, monkeypatch):
    db, parent, child, sibling, users, _ = group_world
    relation = _activate(db, parent, child, users)
    request_id = requests.create_request(db, users["viewer"], relation, "Parent control 9", "Need proof", _future(14))
    db.execute("UPDATE group_evidence_requests SET needed_by=%s WHERE id=%s", (_at(-2), request_id))
    db.commit()
    real = reminders.remind

    def flaky(org_id, now=None):
        if org_id == parent:
            raise RuntimeError("one organization failing")
        return real(org_id, now)
    monkeypatch.setattr(reminders, "remind", flaky)
    assert reminders.run() == 1, "the child is still reminded when the parent's pass fails"


def test_when_nobody_can_act_the_administrators_are_told_to_staff_the_role(group_world):
    db, parent, child, sibling, users, _ = group_world
    relation = _activate(db, parent, child, users)
    request_id = requests.create_request(db, users["viewer"], relation, "Parent control 4", "Need proof", _future(14))
    db.execute("UPDATE group_evidence_requests SET needed_by=%s WHERE id=%s", (_at(-2), request_id))
    # Nobody in the child holds a role that reviews proof requests any more.
    db.execute("DELETE FROM user_roles WHERE user_id IN (%s,%s)", (users["legal"]["id"], users["privacy"]["id"]))
    db.commit()
    assert _run_all(db, child) == 1
    assert [t for t, _ in _inbox(db, users["ack"])] == ["Nobody can act on a group item"]
    assert "Assign the role to a second person" in _inbox(db, users["ack"])[0][1]
    assert _run_all(db, child) == 0
    db.execute("INSERT INTO user_roles (user_id,role_key) VALUES (%s,'compliance_manager')", (users["legal"]["id"],))
    db.commit()
    assert _run_all(db, child) == 1, "once the role is staffed the reviewer is reminded as usual"
    assert [t for t, _ in _inbox(db, users["legal"])] == ["Group proof request overdue"]
