"""Subsidiary review of an exact, accessible parent policy publication.

Publication is a distribution decision; adoption is a separate local decision.
An old version's adoption never transfers to a newer publication.
"""

from datetime import date

from fastapi import HTTPException

from config import settings
from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.evidence import group_documents
from modules.governance.entity_scope import entity_scope_sql


def _table(name):
    return f"public.{name}" if settings.is_postgres() else name


def _publication(db, actor, publication_id):
    row, item = group_documents.released_item(db, actor, publication_id)
    relation = group_documents._relationship(db, row["relationship_id"])
    if (row["category"] != "policy" or item["category"] != "policy"
            or row["source_org_id"] != relation["parent_org_id"]
            or row["viewer_org_id"] != relation["child_org_id"]
            or row["viewer_org_id"] != actor.get("org_id")):
        raise HTTPException(404, "Published parent policy not found")
    return row


def _date(value, label, *, required=False):
    if not value:
        if required:
            raise HTTPException(422, f"Record the {label}")
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise HTTPException(422, f"Choose a valid {label}") from None


def _reason(value):
    if not isinstance(value, str) or not 5 <= len(value.strip()) <= 1000:
        raise HTTPException(422, "Record a reason of 5 to 1000 characters")
    return value.strip()


def list_policies(db, actor, *, page=1):
    if not (has_capability(actor, "group.policy.propose") or
            has_capability(actor, "group.policy.review")):
        raise HTTPException(403, "Group policy review capability required")
    if not 1 <= page <= 10000:
        raise HTTPException(422, "Invalid policy page")
    # Reuse the exact-version, source-rechecked catalogue. The view includes
    # only named grants; a child administrator is not entitled by title alone.
    visible = group_documents.catalogue(db, actor, page=page, page_size=50,
                                        category="policy")
    items = []
    for publication in visible:
        try:
            _publication(db, actor, publication["id"])
        except HTTPException:
            continue
        latest = db.execute(f"SELECT id,proposed_state,state,reason,effective_at,review_due_at,"
                            "local_policy_version_id,proposed_at,reviewed_at,review_reason,proposed_by "
                            f"FROM {_table('group_policy_adoptions')} "
                            "WHERE publication_id=%s AND viewer_org_id=%s ORDER BY id DESC LIMIT 1",
                            (publication["id"], actor["org_id"])).fetchone()
        adoption = dict(latest) if latest else None
        if adoption:
            adoption["can_review"] = (adoption.pop("proposed_by") != actor["id"] and
                                      adoption["state"] == "pending_review" and
                                      has_capability(actor, "group.policy.review"))
        items.append({**publication, "adoption": adoption})
    has_more = bool(group_documents.catalogue(db, actor, page=page + 1,
                                               page_size=50, category="policy"))
    return {"items": items, "page": page, "has_more": has_more,
            "can_propose": has_capability(actor, "group.policy.propose"),
            "can_review": has_capability(actor, "group.policy.review")}


def propose(db, actor, publication_id, proposed_state, reason,
            review_due_at, effective_at=None, local_policy_version_id=None):
    if not has_capability(actor, "group.policy.propose"):
        raise HTTPException(403, "Group policy proposal capability required")
    row = _publication(db, actor, publication_id)
    if proposed_state not in ("adopted", "adapted", "exception_requested", "declined"):
        raise HTTPException(422, "Choose a policy outcome")
    latest = db.execute(f"SELECT state FROM {_table('group_policy_adoptions')} "
                        "WHERE publication_id=%s AND viewer_org_id=%s ORDER BY id DESC LIMIT 1",
                        (publication_id, actor["org_id"])).fetchone()
    if latest and latest["state"] != "rejected":
        raise HTTPException(409, "This version already has a proposal or decision")
    due = _date(review_due_at, "review date", required=True)
    if due <= utcnow().date().isoformat():
        raise HTTPException(422, "Choose a future review date")
    effective = _date(effective_at, "effective date",
                      required=proposed_state in ("adopted", "adapted"))
    if effective and effective > due:
        raise HTTPException(422, "Effective date must precede review")
    local_version = None
    if proposed_state == "adapted":
        try:
            local_version = int(local_policy_version_id)
        except (TypeError, ValueError):
            raise HTTPException(422, "Choose an approved local policy version") from None
        scope, params = entity_scope_sql(("aria", "document"),
                                         {**actor, "is_super_admin": False}, "d")
        if local_version <= 0 or not db.execute(
                "SELECT v.id FROM aria_policy_versions v "
                "JOIN aria_documents d ON d.id=v.document_id AND d.org_id=v.org_id "
                f"WHERE v.id=%s AND v.org_id=%s AND v.state='approved' AND {scope}",
                [local_version, actor["org_id"], *params]).fetchone():
            raise HTTPException(404, "Local policy version not found")
    elif local_policy_version_id:
        raise HTTPException(422, "A local version belongs only to an adapted policy")
    adoption_id = insert_returning_id(db, f"INSERT INTO {_table('group_policy_adoptions')} "
        "(publication_id,source_org_id,viewer_org_id,proposed_state,reason,"
        "local_policy_version_id,effective_at,review_due_at,proposed_by) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (publication_id, row["source_org_id"], actor["org_id"], proposed_state,
         _reason(reason), local_version, effective, due, actor["id"]))
    _event(db, row, actor, "policy_adoption_proposed", adoption_id)
    return adoption_id


def review(db, actor, adoption_id, decision, reason):
    if not has_capability(actor, "group.policy.review"):
        raise HTTPException(403, "Independent policy review required")
    adoption = db.execute(f"SELECT * FROM {_table('group_policy_adoptions')} "
                          "WHERE id=%s AND viewer_org_id=%s AND state='pending_review'",
                          (adoption_id, actor.get("org_id"))).fetchone()
    if not adoption:
        raise HTTPException(404, "Policy proposal not found")
    if adoption["proposed_by"] == actor["id"]:
        raise HTTPException(409, "A different specialist must review this proposal")
    row = _publication(db, actor, adoption["publication_id"])
    if decision not in ("approve", "reject"):
        raise HTTPException(422, "Choose approval or rejection")
    state = adoption["proposed_state"] if decision == "approve" else "rejected"
    db.execute(f"UPDATE {_table('group_policy_adoptions')} SET state=%s,reviewed_by=%s,"
               "reviewed_at=%s,review_reason=%s WHERE id=%s AND viewer_org_id=%s "
               "AND state='pending_review'",
               (state, actor["id"], utcnow().isoformat(), _reason(reason),
                adoption_id, actor["org_id"]))
    _event(db, row, actor, "policy_adoption_" + decision, adoption_id)
    return state


def _event(db, row, actor, action, adoption_id):
    db.execute(f"INSERT INTO {_table('group_access_events')} "
               "(relationship_id,source_org_id,viewer_org_id,publication_id,actor_id,action,detail) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s)",
               (row["relationship_id"], row["source_org_id"], row["viewer_org_id"],
                row["id"], actor["id"], action, str(adoption_id)))
