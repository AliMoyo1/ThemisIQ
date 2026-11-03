"""Subsidiary review of an exact, accessible parent policy publication.

Publication is a distribution decision; adoption is a separate local decision.
An old version's adoption never transfers to a newer publication.
"""

from datetime import date

from fastapi import HTTPException

from config import settings
from core.rbac import has_capability
from core.timeutils import utcnow
from database import get_db, insert_returning_id, tenant_context
from modules.evidence import group_documents
from modules.governance.entity_scope import canonical_key, describe_record, describe_records, entity_scope_sql


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
            adoption["controls"] = (_controls(db, actor, adoption["id"])
                                    if adoption["state"] in DECIDED else [])
            adoption["can_link"] = adoption["state"] in DECIDED and has_capability(actor, "group.policy.propose")
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


# ── Local controls that carry out an adopted policy (plan 22, C5) ──────────

DECIDED = ("adopted", "adapted")
CONTROL_KEYS = {("aria", "control"), ("grid", "control"), ("bcm", "compliance_control"), ("orm", "ai_control")}


def _decided(db, actor, adoption_id):
    row = db.execute(f"SELECT * FROM {_table('group_policy_adoptions')} WHERE id=%s AND viewer_org_id=%s",
                     (adoption_id, actor.get("org_id"))).fetchone()
    if not row or row["state"] not in DECIDED:
        raise HTTPException(404, "Adopted policy not found")
    _publication(db, actor, row["publication_id"])
    return row


def _controls(db, actor, adoption_id):
    """The linked local controls this user may open; a control they may not open is left out."""
    rows = db.execute(f"SELECT id,module,entity_type,entity_id FROM {_table('group_adoption_controls')} "
                      "WHERE adoption_id=%s AND viewer_org_id=%s AND removed_at IS NULL ORDER BY id",
                      (adoption_id, actor["org_id"])).fetchall()
    out = []
    for key in {(r["module"], r["entity_type"]) for r in rows}:
        mine = [r for r in rows if (r["module"], r["entity_type"]) == key]
        described = describe_records(db, key, [r["entity_id"] for r in mine], {**actor, "is_super_admin": False})
        out += [{"id": r["id"], "module": key[0], "entity_type": key[1], "entity_id": r["entity_id"],
                 **described[r["entity_id"]]} for r in mine if r["entity_id"] in described]
    return sorted(out, key=lambda c: c["id"])


def link_control(db, actor, adoption_id, module, entity_type, entity_id):
    """Record that one of this organization's own controls carries out an adopted parent policy.

    A link is the subsidiary's own statement. It never reaches the parent and is not proof that the control works."""
    if not has_capability(actor, "group.policy.propose"):
        raise HTTPException(403, "Group policy proposal capability required")
    _decided(db, actor, adoption_id)
    key = canonical_key(module, entity_type)
    if key not in CONTROL_KEYS or not isinstance(entity_id, int) or entity_id <= 0:
        raise HTTPException(422, "Choose one of your controls")
    if not describe_record(db, key, entity_id, {**actor, "is_super_admin": False}):
        raise HTTPException(404, "Control not found")
    existing = db.execute(f"SELECT id,removed_at FROM {_table('group_adoption_controls')} WHERE adoption_id=%s "
                          "AND viewer_org_id=%s AND module=%s AND entity_type=%s AND entity_id=%s",
                          (adoption_id, actor["org_id"], key[0], key[1], entity_id)).fetchone()
    if existing and existing["removed_at"] is None:
        raise HTTPException(409, "This control is already linked")
    if existing:
        db.execute(f"UPDATE {_table('group_adoption_controls')} SET removed_at=NULL,removed_by=NULL,"
                   "linked_by=%s,linked_at=%s WHERE id=%s AND viewer_org_id=%s",
                   (actor["id"], utcnow().isoformat(), existing["id"], actor["org_id"]))
        return existing["id"]
    return insert_returning_id(db, f"INSERT INTO {_table('group_adoption_controls')} "
                               "(adoption_id,viewer_org_id,module,entity_type,entity_id,linked_by,linked_at) "
                               "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                               (adoption_id, actor["org_id"], key[0], key[1], entity_id, actor["id"],
                                utcnow().isoformat()))


def unlink_control(db, actor, link_id):
    if not has_capability(actor, "group.policy.propose"):
        raise HTTPException(403, "Group policy proposal capability required")
    row = db.execute(f"SELECT * FROM {_table('group_adoption_controls')} WHERE id=%s AND viewer_org_id=%s "
                     "AND removed_at IS NULL", (link_id, actor.get("org_id"))).fetchone()
    if not row:
        raise HTTPException(404, "Link not found")
    _decided(db, actor, row["adoption_id"])
    db.execute(f"UPDATE {_table('group_adoption_controls')} SET removed_at=%s,removed_by=%s "
               "WHERE id=%s AND viewer_org_id=%s AND removed_at IS NULL",
               (utcnow().isoformat(), actor["id"], link_id, actor["org_id"]))


# ── The parent's view of its subsidiaries' decisions (plan 22, C5) ─────────

def _shown_state(row):
    """What the parent sees: a reviewed outcome, or that a decision is in progress or missing. Never the reasons."""
    if row is None or row["state"] == "rejected":
        return "no_decision"
    return "in_review" if row["state"] == "pending_review" else row["state"]


def rollup(db, actor):
    """For the organization that published a policy: each receiving organization's decision on each live version.

    The decision rows belong to the receiving organization, so they are read in its own tenant context, only the
    state and dates, and only for versions this organization published to it. Reasons, local versions and control
    links stay with the subsidiary."""
    if not actor.get("org_id") or not (has_capability(actor, "group.document.publish")
                                       or has_capability(actor, "group.policy.review")):
        raise HTTPException(403, "Group policy access required")
    publications = db.execute(
        f"SELECT p.id,p.title,p.version,p.viewer_org_id,p.created_at,o.name AS viewer_name,o.slug AS viewer_slug "
        f"FROM {_table('group_document_publications')} p "
        f"JOIN {_table('org_relationships')} r ON r.id=p.relationship_id AND r.status='active' "
        "AND r.parent_org_id=p.source_org_id AND r.child_org_id=p.viewer_org_id "
        "JOIN organizations o ON o.id=p.viewer_org_id AND o.status='active' "
        "WHERE p.source_org_id=%s AND p.category='policy' AND p.revoked_at IS NULL AND p.expires_at>%s "
        "ORDER BY p.id DESC LIMIT 100", (actor["org_id"], utcnow().isoformat())).fetchall()
    by_viewer = {}
    for row in publications:
        by_viewer.setdefault((row["viewer_org_id"], row["viewer_slug"]), []).append(row["id"])
    decisions = {}
    for (viewer, slug), ids in by_viewer.items():
        with tenant_context(viewer, slug, is_super_admin=False):
            child = get_db()
            try:
                for row in child.execute(
                        f"SELECT publication_id,state,effective_at,review_due_at,reviewed_at "
                        f"FROM {_table('group_policy_adoptions')} WHERE viewer_org_id=%s AND source_org_id=%s "
                        f"AND publication_id IN ({','.join(['%s'] * len(ids))}) ORDER BY id",
                        (viewer, actor["org_id"], *ids)).fetchall():
                    decisions[row["publication_id"]] = dict(row)
            finally:
                child.close()
    items = []
    for row in publications:
        decision = decisions.get(row["id"])
        state = _shown_state(decision)
        decided = state not in ("no_decision", "in_review")
        items.append({"publication_id": row["id"], "title": row["title"], "version": row["version"],
                      "organization": row["viewer_name"], "published_at": row["created_at"], "state": state,
                      "decided_at": decision["reviewed_at"] if decided else None,
                      "effective_at": decision["effective_at"] if decided else None,
                      "review_due_at": decision["review_due_at"] if decided else None})
    return {"items": items}
