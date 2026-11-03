"""Group oversight reminders and escalation (plan 22, slice C2).

A daily pass over each organization, inside that organization's own tenant context, so it reads only the group rows it
is a party to. It tells the people who can act, in the app, once per stage:

- grant reviews due within 14 days, and overdue ones (an overdue review has already stopped the access);
- proof requests past their needed-by date, to the source team that holds them, and 7 days later to the requesting
  managers;
- published parent policies that the receiving organization has not decided on after 30 days.

Nothing is released, renewed, granted or decided here. A message names the organization and a date, never a document
title or a person from the other organization.
"""
import logging
from datetime import timedelta

from core import email_outbox as outbox
from core.rbac import CAPABILITIES
from core.timeutils import utcnow
from database import get_db, list_active_tenants
from modules.evidence.group_documents import _table

log = logging.getLogger(__name__)

DUE_SOON_DAYS = 14
ESCALATE_AFTER_DAYS = 7
ADOPTION_AFTER_DAYS = 30
BATCH = 500


def _grants(db, org_id, now):
    soon = (now + timedelta(days=DUE_SOON_DAYS)).isoformat()
    rows = db.execute(
        f"SELECT g.id, g.user_id, g.review_due_at, o.name AS source_name FROM {_table('group_view_grants')} g "
        f"JOIN {_table('org_relationships')} r ON r.id=g.relationship_id AND r.status='active' "
        "JOIN organizations o ON o.id=g.source_org_id "
        "WHERE g.viewer_org_id=%s AND g.revoked_at IS NULL AND g.expires_at>%s AND g.review_due_at<=%s "
        "ORDER BY g.review_due_at, g.id LIMIT %s", (org_id, now.isoformat(), soon, BATCH)).fetchall()
    for row in rows:
        overdue = row["review_due_at"] <= now.isoformat()
        yield ("grant", row["id"], "overdue" if overdue else "due", "group.grant.manage",
               "Group access review overdue" if overdue else "Group access review due",
               (f"A named access grant to {row['source_name']} " +
                ("missed its review date, so it no longer opens anything. Review it to keep or revoke it."
                 if overdue else f"is due for review by {row['review_due_at'][:10]}.")),
               "/evidence/group/", {row["user_id"]})


def _requests(db, org_id, now):
    rows = db.execute(
        f"SELECT q.id, q.requester_org_id, q.source_org_id, q.status, q.needed_by, q.requirement_ref, "
        f"ro.name AS requester_name, so.name AS source_name FROM {_table('group_evidence_requests')} q "
        f"JOIN {_table('org_relationships')} r ON r.id=q.relationship_id AND r.status='active' "
        "JOIN organizations ro ON ro.id=q.requester_org_id JOIN organizations so ON so.id=q.source_org_id "
        "WHERE (q.source_org_id=%s OR q.requester_org_id=%s) AND q.status IN ('requested','approved') "
        "AND q.needed_by<%s ORDER BY q.needed_by, q.id LIMIT %s",
        (org_id, org_id, now.isoformat(), BATCH)).fetchall()
    escalate_before = (now - timedelta(days=ESCALATE_AFTER_DAYS)).isoformat()
    for row in rows:
        if row["source_org_id"] == org_id:
            capability = "group.request.review" if row["status"] == "requested" else "group.request.fulfill"
            yield ("request", row["id"], "overdue", capability, "Group proof request overdue",
                   f"The proof request {row['requirement_ref']} from {row['requester_name']} was needed by "
                   f"{row['needed_by'][:10]}. Review it or record that there is no proof.",
                   "/evidence/group/requests/", set())
        if row["requester_org_id"] == org_id and row["needed_by"] < escalate_before:
            yield ("request", row["id"], "escalated", "group.request.manage", "Group proof request escalated",
                   f"Your proof request {row['requirement_ref']} to {row['source_name']} is more than "
                   f"{ESCALATE_AFTER_DAYS} days past {row['needed_by'][:10]}. Nothing is released automatically: "
                   "follow it up with that organization or close it.",
                   "/evidence/group/requests/", set())


def _adoptions(db, org_id, now):
    before = (now - timedelta(days=ADOPTION_AFTER_DAYS)).isoformat()
    rows = db.execute(
        f"SELECT p.id, o.name AS source_name FROM {_table('group_document_publications')} p "
        f"JOIN {_table('org_relationships')} r ON r.id=p.relationship_id AND r.status='active' "
        "JOIN organizations o ON o.id=p.source_org_id "
        "WHERE p.viewer_org_id=%s AND p.category='policy' AND p.revoked_at IS NULL AND p.expires_at>%s "
        "AND p.created_at<=%s AND NOT EXISTS (SELECT 1 FROM "
        f"{_table('group_policy_adoptions')} a WHERE a.publication_id=p.id AND a.viewer_org_id=p.viewer_org_id) "
        "ORDER BY p.id LIMIT %s", (org_id, now.isoformat(), before, BATCH)).fetchall()
    for row in rows:
        yield ("adoption", row["id"], "undecided", "group.policy.propose", "Group policy awaiting adoption",
               f"A policy version published by {row['source_name']} more than {ADOPTION_AFTER_DAYS} days ago has "
               "no adoption decision. Record whether it is adopted, adapted or needs an exception.",
               "/evidence/group/adoption/", set())


def _claim(db, org_id, kind, ref_id, stage) -> bool:
    return db.execute(
        f"INSERT INTO {_table('group_reminders_sent')} (org_id,kind,ref_id,stage,sent_at) "
        "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (org_id, kind, ref_id, stage, utcnow().isoformat())).rowcount == 1


def remind(org_id: int, now=None) -> int:
    """Send this organization's reminders that have not been sent at their stage yet; returns how many were sent."""
    now = now or utcnow()
    db = get_db()
    try:
        sent = 0
        for producer in (_grants, _requests, _adoptions):
            for kind, ref_id, stage, capability, title, message, link, skip in list(producer(db, org_id, now)):
                people = [p for p in outbox.organization_people(db, org_id, CAPABILITIES[capability]) if p not in skip]
                if not people or not _claim(db, org_id, kind, ref_id, stage):
                    continue
                for user_id in people:
                    db.execute("INSERT INTO notifications (user_id, module, title, message, link) "
                               "VALUES (%s, %s, %s, %s, %s)", (user_id, "evidence", title, message, link))
                sent += 1
        db.commit()
        return sent
    finally:
        db.close()


def run() -> int:
    """Every active organization in turn; one failing does not stop the others."""
    return sum(outbox.for_each_tenant(remind, "Group oversight reminders", tenants=sorted(list_active_tenants())))
