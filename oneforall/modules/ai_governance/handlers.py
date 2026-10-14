"""
AI governance: what happens when an AI use request changes hands.

The handlers only tell people: a notification for each person who has to act or who is waiting. They never change the
request or the application. Each notification carries the event it came from, so delivering the same event twice (a
retry after a failure, or a sweep that overlaps a slow first delivery) tells nobody twice.
"""
import json
import logging

from core import events
from core.rbac import CAPABILITIES
from database import get_db
from modules.governance.data_service import bu_scope_ids

log = logging.getLogger("oneforall.ai_governance")


def _intake(db, intake_id):
    return db.execute("SELECT * FROM ai_use_intake_requests WHERE id = %s", (intake_id,)).fetchone()


def _name(row) -> str:
    try:
        return (json.loads(row["payload"] or "{}").get("name") or "An AI use").strip()
    except (TypeError, ValueError):
        return "An AI use"


def _notify(db, event_id, user_id, title, message, link) -> None:
    db.execute(
        "INSERT INTO notifications (user_id, module, title, message, link, source_event_id) "
        "VALUES (%s, 'ai_governance', %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (user_id, title, message, link, event_id))


def _reviewers(db, row, org_id) -> list:
    """People who hold the review capability and may see this request: its organization, and its business unit or one
    above it (an organization-wide request reaches every reviewer). The author is not told about their own request."""
    roles = sorted(CAPABILITIES["ai_use.review"])
    sql = ("SELECT DISTINCT u.id, u.business_unit_id FROM users u JOIN user_roles ur ON ur.user_id = u.id "
           f"WHERE u.is_active = 1 AND u.deleted_at IS NULL AND ur.role_key IN ({','.join(['%s'] * len(roles))}) AND u.id != %s")
    params = [*roles, row["submitted_by"]]
    if org_id is not None:
        sql, params = sql + " AND u.org_id = %s", [*params, org_id]
    found = []
    for person in db.execute(sql, params).fetchall():
        if row["business_unit_id"] is None:
            found.append(person["id"])
            continue
        scope = bu_scope_ids({"business_unit_id": person["business_unit_id"], "is_super_admin": False})
        if scope is not None and row["business_unit_id"] in scope:
            found.append(person["id"])
    return found


@events.on(events.AI_USE_SUBMITTED)
def tell_reviewers(*, payload=None, event_id=None, org_id=None, **kw):
    db = get_db()
    try:
        row = _intake(db, (payload or {}).get("intake_id"))
        if row is None or row["status"] != "submitted":
            return  # withdrawn or already decided since: nobody is waiting on it any more
        for reviewer in _reviewers(db, row, org_id):
            _notify(db, event_id, reviewer, "AI use waiting for review", f"{_name(row)} was submitted for review.",
                    "/ai-governance/review")
        db.commit()
    finally:
        db.close()


def _tell_author(title_for, link_for):
    def handler(*, payload=None, event_id=None, user_id=None, **kw):
        db = get_db()
        try:
            row = _intake(db, (payload or {}).get("intake_id"))
            if row is None or row["submitted_by"] == user_id:
                return
            title, message = title_for(row)
            _notify(db, event_id, row["submitted_by"], title, message, link_for(row))
            db.commit()
        finally:
            db.close()
    return handler


def _reason(row) -> str:
    return (row["review_note"] or "").strip()


events.on(events.AI_USE_RETURNED)(_tell_author(
    lambda row: ("Your AI use request needs changes", f"{_name(row)}: {_reason(row)}"),
    lambda row: f"/ai-governance/requests/{row['id']}"))
events.on(events.AI_USE_REJECTED)(_tell_author(
    lambda row: ("Your AI use request was not accepted", f"{_name(row)}: {_reason(row)}"),
    lambda row: f"/ai-governance/requests/{row['id']}"))
events.on(events.AI_USE_APPROVED)(_tell_author(
    lambda row: ("Your AI use request was accepted", f"{_name(row)} is now in the AI inventory."),
    lambda row: f"/ai-governance/systems/{row['application_id']}" if row["application_id"] else "/ai-governance/"))


# ── Decisions ───────────────────────────────────────────────────────────────

def _application(db, application_id):
    return db.execute("SELECT id, name, owner_user_id, business_unit_id FROM applications WHERE id = %s", (application_id,)).fetchone()


def _holders(db, capability, unit_id, org_id, exclude=()) -> list:
    """People who hold a capability and may open a system in this unit: its organization, and this unit or one above it
    (an organization-wide system reaches every holder)."""
    roles = sorted(CAPABILITIES[capability])
    sql = ("SELECT DISTINCT u.id, u.business_unit_id FROM users u JOIN user_roles ur ON ur.user_id = u.id "
           f"WHERE u.is_active = 1 AND u.deleted_at IS NULL AND ur.role_key IN ({','.join(['%s'] * len(roles))})")
    params = list(roles)
    if org_id is not None:
        sql, params = sql + " AND u.org_id = %s", [*params, org_id]
    found = []
    for person in db.execute(sql, params).fetchall():
        if person["id"] in exclude:
            continue
        if unit_id is None:
            found.append(person["id"])
            continue
        scope = bu_scope_ids({"business_unit_id": person["business_unit_id"], "is_super_admin": False})
        if scope is not None and unit_id in scope:
            found.append(person["id"])
    return found


def _decision(db, decision_id):
    return db.execute("SELECT * FROM ai_use_decisions WHERE id = %s", (decision_id,)).fetchone()


def _system_link(app) -> str:
    return f"/ai-governance/systems/{app['id']}#decisions"


@events.on(events.AI_DECISION_REQUESTED)
def tell_deciders(*, payload=None, event_id=None, org_id=None, **kw):
    from core import ai_rollout
    db = get_db()
    try:
        row = _decision(db, (payload or {}).get("decision_id"))
        if row is None or row["status"] != "proposed":
            return  # withdrawn or decided since: nobody is waiting on it any more
        app = _application(db, row["application_id"])
        skip = {row["requested_by"]}
        if ai_rollout.separation_required(org_id):
            skip.add(app["owner_user_id"])  # they may not decide it, so being told to would be a dead end
        for person in _holders(db, "ai_use.decide", app["business_unit_id"], org_id, exclude=skip):
            _notify(db, event_id, person, "AI use waiting for a decision", f"{app['name']} was put forward for a decision.", _system_link(app))
        db.commit()
    finally:
        db.close()


_OUTCOME_WORDS = {"approved": "approved", "approved_with_conditions": "approved with conditions",
                  "rejected": "not approved", "returned": "returned for changes"}


@events.on(events.AI_DECISION_MADE)
def tell_asker_and_owner(*, payload=None, event_id=None, user_id=None, **kw):
    db = get_db()
    try:
        row = _decision(db, (payload or {}).get("decision_id"))
        if row is None:
            return
        app = _application(db, row["application_id"])
        message = f"{app['name']}: {_OUTCOME_WORDS.get(row['status'], row['status'])}."
        if row["rationale"]:
            message += " " + row["rationale"].strip()
        for person in {row["requested_by"], app["owner_user_id"]} - {None, user_id}:
            _notify(db, event_id, person, "A decision was made on your AI use", message, _system_link(app))
        db.commit()
    finally:
        db.close()


@events.on(events.AI_DECISION_REVOKED)
def tell_about_revocation(*, payload=None, event_id=None, user_id=None, **kw):
    db = get_db()
    try:
        row = _decision(db, (payload or {}).get("decision_id"))
        if row is None:
            return
        app = _application(db, row["application_id"])
        for person in {row["requested_by"], app["owner_user_id"]} - {None, user_id}:
            _notify(db, event_id, person, "An approval was revoked", f"{app['name']}: {row['revoked_reason'] or 'revoked'}.", _system_link(app))
        db.commit()
    finally:
        db.close()


def _standing_approval(db, application_id):
    """The approval that is in force for this use: the latest decision that stands, if it is an approval and not revoked."""
    return db.execute(
        "SELECT d.id FROM ai_use_decisions d WHERE d.application_id = %s AND d.status IN ('approved', 'approved_with_conditions') "
        "AND d.revoked_at IS NULL AND d.id = (SELECT MAX(x.id) FROM ai_use_decisions x WHERE x.application_id = d.application_id "
        "AND x.status IN ('approved', 'approved_with_conditions', 'rejected'))", (application_id,)).fetchone()


@events.on(events.AI_USE_MATERIAL_CHANGE)
def tell_about_re_review(*, payload=None, event_id=None, org_id=None, user_id=None, **kw):
    """A fact an approval covered changed: the owner and the deciders hear that it needs a new decision."""
    from core import ai_rollout
    db = get_db()
    try:
        application_id = (payload or {}).get("application_id")
        standing = _standing_approval(db, application_id)
        app = _application(db, application_id) if standing else None
        if app is None:
            return  # nothing was approved, so there is nothing to re-review
        skip = {user_id}
        people = set(_holders(db, "ai_use.decide", app["business_unit_id"], org_id, exclude=skip))
        if app["owner_user_id"] is not None:
            people.add(app["owner_user_id"])
        for person in people - {user_id}:
            _notify(db, event_id, person, "An approved AI use needs a new decision",
                    f"{app['name']} changed in a way the approval covered.", _system_link(app))
        db.commit()
    finally:
        db.close()


# ── What the records connected to an AI use are told ────────────────────────

_STANDING_LABEL = {"approved": "Approved", "approved_with_conditions": "Approved with conditions", "rejected": "Not approved",
                   None: "No decision"}


def _tell_connected_records(db, application_id, kind, before, after, user_id, org_id) -> None:
    """A processing record, an assessment, a control, an audit or a risk connected to this AI use is told what changed, and
    its owner decides whether it matters. Nothing in any of them is changed here, and a failure is logged, not raised."""
    from modules.governance import change_signals
    change_signals.publish(db, source=("governance", "application", application_id), kind=kind,
                           before={"state": before}, after={"state": after}, fields={"state": "AI use"},
                           actor_id=user_id, org_id=org_id)
    db.commit()


@events.on(events.AI_DECISION_MADE)
def tell_connected_records_about_a_decision(*, payload=None, user_id=None, org_id=None, **kw):
    db = get_db()
    try:
        row = _decision(db, (payload or {}).get("decision_id"))
        if row is None or row["status"] not in _STANDING_LABEL:
            return  # a return for changes is not a standing outcome
        earlier = db.execute(
            "SELECT status FROM ai_use_decisions WHERE application_id = %s AND id < %s AND revoked_at IS NULL "
            "AND status IN ('approved', 'approved_with_conditions', 'rejected') ORDER BY id DESC LIMIT 1",
            (row["application_id"], row["id"])).fetchone()
        _tell_connected_records(db, row["application_id"], "ai_use_decided",
                                _STANDING_LABEL[earlier["status"] if earlier else None], _STANDING_LABEL[row["status"]],
                                user_id, org_id)
    finally:
        db.close()


@events.on(events.AI_DECISION_REVOKED)
def tell_connected_records_about_a_revocation(*, payload=None, user_id=None, org_id=None, **kw):
    db = get_db()
    try:
        row = _decision(db, (payload or {}).get("decision_id"))
        if row is None:
            return
        _tell_connected_records(db, row["application_id"], "ai_use_revoked",
                                _STANDING_LABEL.get(row["status"], row["status"]), "Approval revoked", user_id, org_id)
    finally:
        db.close()


@events.on(events.AI_USE_MATERIAL_CHANGE)
def tell_connected_records_about_a_changed_use(*, payload=None, user_id=None, org_id=None, **kw):
    db = get_db()
    try:
        application_id = (payload or {}).get("application_id")
        if application_id is None or _standing_approval(db, application_id) is None:
            return  # nothing was approved, so no approval was covering what changed
        _tell_connected_records(db, application_id, "ai_use_changed", "As the approval described it",
                                "Changed since", user_id, org_id)
    finally:
        db.close()


# ── Evaluations and regulatory changes ──────────────────────────────────────

@events.on(events.EVALUATION_FAILED)
def tell_about_failed_evaluation(*, payload=None, event_id=None, org_id=None, user_id=None, **kw):
    """A run failed or did not finish: the owner and the deciders hear once, whoever recorded it excepted."""
    db = get_db()
    try:
        data = payload or {}
        if not data.get("application_id"):
            return  # a platform level run names no application
        app = _application(db, data["application_id"])
        if app is None:
            return
        people = set(_holders(db, "ai_use.decide", app["business_unit_id"], org_id, exclude={user_id}))
        if app["owner_user_id"] is not None:
            people.add(app["owner_user_id"])
        word = "failed" if data.get("state") == "failed" else "did not finish"
        for person in people - {user_id}:
            _notify(db, event_id, person, "An AI evaluation did not pass", f"An evaluation of {app['name']} {word}.",
                    f"/ai-governance/systems/{app['id']}#monitoring")
        db.commit()
    finally:
        db.close()


@events.on(events.AI_REGULATORY_CONFIRMED)
def tell_owner_about_regulatory_change(*, payload=None, event_id=None, user_id=None, **kw):
    db = get_db()
    try:
        app = _application(db, (payload or {}).get("application_id"))
        if app is None or app["owner_user_id"] in (None, user_id):
            return
        _notify(db, event_id, app["owner_user_id"], "A regulatory change was confirmed for your AI use",
                f"{app['name']}: there is a task for it.", f"/ai-governance/systems/{app['id']}#monitoring")
        db.commit()
    finally:
        db.close()


# ── Review packs and AI literacy ────────────────────────────────────────────

@events.on(events.AI_PACK_ISSUED)
def tell_recipient_of_pack(*, payload=None, event_id=None, user_id=None, **kw):
    """The named recipient hears that a pack was shared with them, once."""
    db = get_db()
    try:
        data = payload or {}
        row = db.execute("SELECT id, name, application_name, status FROM ai_review_packs WHERE id = %s", (data.get("pack_id"),)).fetchone()
        if row is None or row["status"] != "issued" or data.get("recipient_id") in (None, user_id):
            return
        _notify(db, event_id, data["recipient_id"], "A review pack was shared with you",
                f"{row['name']}: {row['application_name']}.", f"/ai-governance/packs/{row['id']}")
        db.commit()
    finally:
        db.close()


@events.on(events.AI_LITERACY_PUBLISHED)
def tell_assignees_of_course(*, payload=None, event_id=None, org_id=None, user_id=None, **kw):
    """People a published course applies to hear once that it is theirs to complete, whoever published it excepted."""
    from modules.ai_governance import literacy
    db = get_db()
    try:
        data = payload or {}
        for person in literacy.assignees_of(db, data.get("course_id"), org_id):
            if person != user_id:
                _notify(db, event_id, person, "An AI literacy course was assigned to you",
                        f"{data.get('title') or 'A course'} is due within {data.get('due_days') or 30} days.",
                        f"/ai-governance/literacy/{data.get('course_id')}")
        db.commit()
    finally:
        db.close()
