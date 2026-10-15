"""
Naming the person who reviews a request or decides a use (plans/2026-10-governance-rework/06 sections 3 and 4).

Nobody is named by default: a request still goes to everyone who may review it, and a decision request to everyone who
may decide it, in the app only. Naming one person makes that person's turn explicit. They are told in the app and by
email, and everybody else sees the item as waiting on them. Nothing here reviews or decides anything, and a named person
has no more right than their role gives them: the assignee must hold the capability, be able to open the record, and not
be a person the separation rules keep away from it.

Like the rest of the module, every function takes the caller's connection and the signed-in user, checks the capability
and the scope itself, never commits, and returns the audit entries and events the route delivers once it has committed.
"""
from core import ai_rollout, events
from core.rbac import CAPABILITIES, has_capability
from modules.ai_governance import decisions, service
from modules.ai_governance.service import ServiceError
from modules.governance.data_service import bu_scope_ids

_LIMIT = 100


def eligible(db, user, capability: str, unit_id, exclude=()) -> list:
    """[{"id", "name"}] of the active people of the organization who hold `capability` and whose own scope covers a record
    of `unit_id` (an organization wide record reaches everybody who holds it), minus `exclude`."""
    roles = sorted(CAPABILITIES[capability])
    marks = ",".join(["%s"] * len(roles))
    sql = ("SELECT DISTINCT u.id, u.full_name, u.business_unit_id, u.is_super_admin FROM users u "
           "JOIN user_roles ur ON ur.user_id = u.id "
           f"WHERE u.is_active = 1 AND u.deleted_at IS NULL AND ur.role_key IN ({marks})")
    params = list(roles)
    if user.get("org_id") is not None:
        sql, params = sql + " AND u.org_id = %s", [*params, user["org_id"]]
    found = []
    for person in db.execute(sql + " ORDER BY u.full_name, u.id", params).fetchall():
        if person["id"] in exclude:
            continue
        if unit_id is not None and not person["is_super_admin"]:
            scope = bu_scope_ids({"business_unit_id": person["business_unit_id"], "is_super_admin": False})
            if scope is not None and unit_id not in scope:
                continue
        found.append({"id": person["id"], "name": person["full_name"]})
        if len(found) >= _LIMIT:
            break
    return found


def _check(people: list, assignee_id, what: str) -> int:
    if isinstance(assignee_id, bool) or not isinstance(assignee_id, int):
        raise ServiceError(422, f"Choose the person who will {what}.")
    if assignee_id not in {p["id"] for p in people}:
        raise ServiceError(422, f"That person cannot be named: they must be active in this organization, hold the right "
                                f"to {what}, be able to open this record, and not be someone who has to stay out of it.")
    return assignee_id


# ── A request waiting for review ────────────────────────────────────────────

def reviewers_for(db, user, intake_id: int) -> list:
    row = service._review_intake(db, user, intake_id)
    return eligible(db, user, "ai_use.review", row["business_unit_id"], exclude={row["submitted_by"]})


def assign_reviewer(db, user, intake_id: int, assignee_id) -> dict:
    """Name the reviewer of a request that is waiting for review, or (assignee_id None) take the name off again."""
    row = service._review_intake(db, user, intake_id)
    if row["status"] != "submitted":
        raise ServiceError(409, "Only a request that is waiting for review can be assigned.", status_now=row["status"])
    if assignee_id is None:
        db.execute("UPDATE ai_use_intake_requests SET assigned_reviewer_id = NULL, updated_at = %s WHERE id = %s",
                   (service._now(), intake_id))
        changed, evs = row["assigned_reviewer_id"] is not None, []
        audit = [("ai_use_reviewer_cleared", "ai_use_intake", intake_id, "no reviewer is named")] if changed else []
    else:
        who = _check(eligible(db, user, "ai_use.review", row["business_unit_id"], exclude={row["submitted_by"]}),
                     assignee_id, "review this request")
        if row["assigned_reviewer_id"] == who:
            return {"intake": service._with_names(db, [service._intake(row)])[0], "events": [], "audit": [], "changed": False}
        db.execute("UPDATE ai_use_intake_requests SET assigned_reviewer_id = %s, updated_at = %s "
                   "WHERE id = %s AND status = 'submitted'", (who, service._now(), intake_id))
        changed = True
        evs = [events.enqueue(
            db, events.AI_REVIEWER_ASSIGNED, "ai_governance", "ai_use_intake", intake_id,
            {"intake_id": intake_id, "assignee_id": who}, user_id=user["id"], org_id=user.get("org_id"),
            dedup_key=f"ai_use.reviewer_assigned:{intake_id}:{who}:{service._now()}")]
        audit = [("ai_use_reviewer_assigned", "ai_use_intake", intake_id, f"assigned to user {who}")]
    return {"intake": service._with_names(db, [service._intake(service._load(db, intake_id))])[0],
            "events": evs, "audit": audit, "changed": changed}


# ── A decision request ──────────────────────────────────────────────────────

def _decision_conflicts(db, user, decision_row, app) -> set:
    """The people who may not decide this one: whoever asked, and the system's owner while separation of duties is on."""
    out = {decision_row["requested_by"]}
    if ai_rollout.separation_required(user.get("org_id")):
        out.add(app["owner_user_id"])
    return {i for i in out if i is not None}


def deciders_for(db, user, decision_id: int) -> list:
    service._require(user, "ai_use.view")
    row = decisions._load(db, user, decision_id)
    app = decisions._app(db, user, row["application_id"])
    return eligible(db, user, "ai_use.decide", app["business_unit_id"], exclude=_decision_conflicts(db, user, row, app))


def assign_decider(db, user, decision_id: int, assignee_id) -> dict:
    """Name who decides an open decision request, or (assignee_id None) take the name off again. A reviewer or a decider
    may do it; the person named must hold the right to decide and may not be the one who asked, nor the owner while
    separation of duties is on."""
    service._require(user, "ai_use.view")
    if not (has_capability(user, "ai_use.review") or has_capability(user, "ai_use.decide")):
        raise ServiceError(403, "Access denied.")
    row = decisions._load(db, user, decision_id)
    if row["status"] != "proposed":
        raise ServiceError(409, "Only a request that is waiting for a decision can be assigned.", status_now=row["status"])
    app = decisions._app(db, user, row["application_id"])
    if assignee_id is None:
        db.execute("UPDATE ai_use_decisions SET assigned_decider_id = NULL WHERE id = %s AND status = 'proposed'",
                   (decision_id,))
        changed, evs = row["assigned_decider_id"] is not None, []
        audit = [("ai_decider_cleared", "application", row["application_id"], "no decider is named")] if changed else []
    else:
        who = _check(eligible(db, user, "ai_use.decide", app["business_unit_id"],
                              exclude=_decision_conflicts(db, user, row, app)), assignee_id, "decide this request")
        if row["assigned_decider_id"] == who:
            return {"decision": decisions._present(db, [row])[0], "events": [], "audit": [], "changed": False}
        db.execute("UPDATE ai_use_decisions SET assigned_decider_id = %s WHERE id = %s AND status = 'proposed'",
                   (who, decision_id))
        changed = True
        evs = [events.enqueue(
            db, events.AI_DECIDER_ASSIGNED, "ai_governance", "application", row["application_id"],
            {"decision_id": decision_id, "application_id": row["application_id"], "assignee_id": who},
            user_id=user["id"], org_id=user.get("org_id"),
            dedup_key=f"ai_use.decider_assigned:{decision_id}:{who}:{service._now()}")]
        audit = [("ai_decider_assigned", "application", row["application_id"],
                  f"decision {decision_id} assigned to user {who}")]
    fresh = db.execute("SELECT * FROM ai_use_decisions WHERE id = %s", (decision_id,)).fetchone()
    return {"decision": decisions._present(db, [fresh])[0], "events": evs, "audit": audit, "changed": changed}
