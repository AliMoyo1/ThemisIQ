"""Requirement-led requests between reviewed group members.

The parent names its own requirement, never an undisclosed child document.
The child's local record mapping is held in a source-only table.
"""

from datetime import date

from fastapi import HTTPException

from config import settings
from core.rbac import has_capability
from core.timeutils import utcnow
from database import get_db, insert_returning_id, tenant_context
from modules.evidence import group_documents
from modules.evidence.scope import evidence_scope_sql
from modules.governance.entity_scope import canonical_key, describe_record, is_linkable


def _table(name):
    return f"public.{name}" if settings.is_postgres() else name


def _required(value, label, maximum):
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= maximum:
        raise HTTPException(422, f"Record the {label}")
    return value.strip()


def _period(start, end):
    if not start and not end:
        return None, None
    try:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
        if a > b:
            raise ValueError
        return a.isoformat(), b.isoformat()
    except (TypeError, ValueError):
        raise HTTPException(422, "Choose a valid start and end date") from None


def _request(db, actor, request_id, *, source=False):
    key = "source_org_id" if source else "requester_org_id"
    row = db.execute(f"SELECT * FROM {_table('group_evidence_requests')} WHERE id=%s AND {key}=%s",
                     (request_id, actor.get("org_id"))).fetchone()
    if not row:
        raise HTTPException(404, "Request not found")
    return row


def _event(db, row, actor, action):
    # Only the request ID enters the shared log. The source mapping and
    # potentially sensitive explanation remain in their respective tables.
    db.execute(f"INSERT INTO {_table('group_access_events')} "
               "(relationship_id,source_org_id,viewer_org_id,actor_id,action,detail) "
               "VALUES (%s,%s,%s,%s,%s,%s)",
               (row["relationship_id"], row["source_org_id"], row["requester_org_id"],
                actor["id"], action, str(row["id"])))


def _verdict(db, row):
    if not row["publication_id"]:
        return None
    return db.execute(f"SELECT outcome,reason,reviewed_by,reviewed_at FROM {_table('group_request_verdicts')} "
                      "WHERE request_id=%s AND requester_org_id=%s AND publication_id=%s",
                      (row["id"], row["requester_org_id"], row["publication_id"])).fetchone()


def create_request(db, actor, relation_id, requirement_ref, purpose, needed_by,
                   period_start=None, period_end=None):
    if not has_capability(actor, "group.request.create"):
        raise HTTPException(403, "Group request capability required")
    relation = group_documents._relationship(db, relation_id)
    if relation["parent_org_id"] != actor.get("org_id"):
        raise HTTPException(404, "Relationship not found")
    group_documents._assert_edge(db, relation)
    start, end = _period(period_start, period_end)
    request_id = insert_returning_id(db, f"INSERT INTO {_table('group_evidence_requests')} "
        "(relationship_id,requester_org_id,source_org_id,requested_by,requirement_ref,purpose,needed_by,period_start,period_end) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (relation_id, actor["org_id"], relation["child_org_id"], actor["id"],
         _required(requirement_ref, "parent requirement", 200),
         _required(purpose, "request purpose", 500), group_documents._deadline(needed_by), start, end))
    _event(db, _request(db, actor, request_id), actor, "request_created")
    return request_id


def list_requests(db, actor, *, page=1):
    if not actor.get("org_id") or not 1 <= page <= 10000:
        raise HTTPException(422, "Invalid request page")
    source = any(has_capability(actor, cap) for cap in ("group.request.review", "group.request.fulfill"))
    parent = has_capability(actor, "group.request.manage")
    own = has_capability(actor, "group.request.create")
    if not (source or parent or own):
        raise HTTPException(403, "Group request access required")
    clauses, args = [], []
    if source:
        clauses.append("source_org_id=%s")
        args.append(actor["org_id"])
    if parent:
        clauses.append("requester_org_id=%s")
        args.append(actor["org_id"])
    elif own:
        clauses.append("(requester_org_id=%s AND requested_by=%s)")
        args.extend((actor["org_id"], actor["id"]))
    args.extend((51, (page - 1) * 50))
    rows = db.execute(
        f"SELECT id,relationship_id,requester_org_id,source_org_id,requested_by,requirement_ref,"
        "purpose,needed_by,period_start,period_end,status,decision_reason,reviewed_by,"
        f"publication_id,created_at FROM {_table('group_evidence_requests')} "
        f"WHERE {' OR '.join(f'({clause})' for clause in clauses)} "
        "ORDER BY id DESC LIMIT %s OFFSET %s", args).fetchall()
    has_more = len(rows) > 50
    result = []
    for row in rows[:50]:
        item = dict(row)
        # A viewer sees the status and its own request text, not the source's
        # internal record mapping or a bare publication identifier.
        publication_id = item.pop("publication_id")
        item.pop("reviewed_by")
        item.pop("requested_by")
        item["is_source"] = item["source_org_id"] == actor["org_id"]
        item["can_map"] = item["is_source"] and has_capability(actor, "group.request.review")
        item["can_fulfill"] = item["is_source"] and has_capability(actor, "group.request.fulfill")
        item["can_revise"] = row["requested_by"] == actor["id"] and item["status"] == "clarification"
        verdict = _verdict(db, row)
        item["verdict"] = verdict["outcome"] if verdict else None
        # A returned release needs an actionable explanation for the source
        # team. Accepted-claim reasoning belongs to the requesting tenant.
        item["verdict_reason"] = (verdict["reason"] if verdict and
            (not item["is_source"] or verdict["outcome"] == "returned") else None)
        item["can_review_verdict"] = (not item["is_source"] and parent and
            row["requested_by"] != actor["id"] and row["status"] == "fulfilled" and not verdict)
        item["can_refulfill"] = bool(item["is_source"] and item["status"] == "fulfilled" and
                                      verdict and verdict["outcome"] == "returned" and
                                      has_capability(actor, "group.request.fulfill"))
        item["released_publication_id"] = None
        if publication_id and not item["is_source"]:
            try:
                group_documents.released_item(db, actor, publication_id)
                item["released_publication_id"] = publication_id
            except HTTPException:
                pass
        if item["is_source"]:
            mapping = db.execute(f"SELECT module,entity_type,entity_id FROM {_table('group_request_mappings')} "
                                 "WHERE request_id=%s AND source_org_id=%s",
                                 (item["id"], actor["org_id"])).fetchone()
            item["source_mapping"] = (dict(mapping) if mapping and describe_record(
                db, (mapping["module"], mapping["entity_type"]), mapping["entity_id"],
                {**actor, "is_super_admin": False}) else None)
        result.append(item)
    relationships = []
    if own:
        relationships = [dict(r) for r in db.execute(
            f"SELECT r.id,r.purpose,c.name AS source_name FROM {_table('org_relationships')} r "
            "JOIN organizations c ON c.id=r.child_org_id AND c.status='active' "
            "WHERE r.parent_org_id=%s AND r.status='active' AND r.review_due_at>%s "
            "ORDER BY c.name,r.id LIMIT 100", (actor["org_id"], utcnow().isoformat())).fetchall()]
    return {"items": result, "page": page, "has_more": has_more, "relationships": relationships}


def map_request(db, actor, request_id, module, entity_type, entity_id):
    if not has_capability(actor, "group.request.review"):
        raise HTTPException(403, "Source review required")
    row = _request(db, actor, request_id, source=True)
    if row["status"] not in ("requested", "clarification"):
        raise HTTPException(409, "Request is no longer awaiting review")
    key = canonical_key(module, entity_type)
    if not is_linkable(key) or not isinstance(entity_id, int) or entity_id <= 0:
        raise HTTPException(422, "Choose a source record")
    if not describe_record(db, key, entity_id, {**actor, "is_super_admin": False}):
        raise HTTPException(404, "Source record not found")
    existing = db.execute(f"SELECT request_id FROM {_table('group_request_mappings')} WHERE request_id=%s",
                          (request_id,)).fetchone()
    if existing:
        db.execute(f"UPDATE {_table('group_request_mappings')} SET module=%s,entity_type=%s,entity_id=%s,"
                   "mapped_by=%s,mapped_at=%s WHERE request_id=%s AND source_org_id=%s",
                   (key[0], key[1], entity_id, actor["id"], utcnow().isoformat(), request_id, actor["org_id"]))
    else:
        db.execute(f"INSERT INTO {_table('group_request_mappings')} "
                   "(request_id,source_org_id,module,entity_type,entity_id,mapped_by) "
                   "VALUES (%s,%s,%s,%s,%s,%s)",
                   (request_id, actor["org_id"], key[0], key[1], entity_id, actor["id"]))
    _event(db, row, actor, "request_mapped")


def review_request(db, actor, request_id, decision, reason):
    if not has_capability(actor, "group.request.review"):
        raise HTTPException(403, "Source review required")
    row = _request(db, actor, request_id, source=True)
    if row["status"] != "requested":
        raise HTTPException(409, "Request is no longer awaiting review")
    if decision not in ("approved", "clarification", "no_proof", "declined"):
        raise HTTPException(422, "Choose a review decision")
    if decision == "approved":
        mapping = db.execute(f"SELECT module,entity_type,entity_id FROM {_table('group_request_mappings')} "
                             "WHERE request_id=%s AND source_org_id=%s", (request_id, actor["org_id"])).fetchone()
        if not mapping or not describe_record(db, (mapping["module"], mapping["entity_type"]),
                                               mapping["entity_id"], {**actor, "is_super_admin": False}):
            raise HTTPException(409, "Map this request to an accessible source record first")
    db.execute(f"UPDATE {_table('group_evidence_requests')} SET status=%s,decision_reason=%s,"
               "reviewed_by=%s,reviewed_at=%s WHERE id=%s AND source_org_id=%s AND status='requested'",
               (decision, _required(reason, "decision explanation", 500), actor["id"],
                utcnow().isoformat(), request_id, actor["org_id"]))
    _event(db, row, actor, "request_" + decision)


def revise_request(db, actor, request_id, requirement_ref, purpose, needed_by,
                   period_start=None, period_end=None):
    row = _request(db, actor, request_id)
    if row["requested_by"] != actor["id"] or row["status"] != "clarification":
        raise HTTPException(404, "Request not found")
    group_documents._assert_edge(db, group_documents._relationship(db, row["relationship_id"]))
    start, end = _period(period_start, period_end)
    db.execute(f"UPDATE {_table('group_evidence_requests')} SET requirement_ref=%s,purpose=%s,"
               "needed_by=%s,period_start=%s,period_end=%s,status='requested',decision_reason=NULL,"
               "reviewed_by=NULL,reviewed_at=NULL WHERE id=%s AND requester_org_id=%s",
               (_required(requirement_ref, "parent requirement", 200), _required(purpose, "request purpose", 500),
                group_documents._deadline(needed_by), start, end, request_id, actor["org_id"]))
    _event(db, row, actor, "request_revised")


def release_candidates(db, actor, request_id):
    if not has_capability(actor, "group.request.fulfill"):
        raise HTTPException(403, "Source fulfillment required")
    row = _request(db, actor, request_id, source=True)
    if row["status"] != "approved" and not (row["status"] == "fulfilled" and
            (verdict := _verdict(db, row)) and verdict["outcome"] == "returned"):
        raise HTTPException(409, "Request is not approved for fulfillment")
    scope, params = evidence_scope_sql({**actor, "is_super_admin": False})
    rows = db.execute(
        f"SELECT p.id,p.title,p.version FROM {_table('group_document_publications')} p "
        "JOIN evidence_items e ON e.id=p.evidence_id AND e.org_id=p.source_org_id "
        "AND e.file_hash=p.file_hash AND e.status='current' "
        "WHERE p.relationship_id=%s AND p.source_org_id=%s AND p.viewer_org_id=%s "
        f"AND p.revoked_at IS NULL AND p.expires_at>%s AND {scope} "
        f"AND NOT EXISTS (SELECT 1 FROM {_table('group_request_verdicts')} v "
        "WHERE v.request_id=%s AND v.publication_id=p.id) "
        "ORDER BY p.id DESC LIMIT 100",
        [row["relationship_id"], actor["org_id"], row["requester_org_id"],
         utcnow().isoformat(), *params, request_id]).fetchall()
    return [dict(item) for item in rows]


def fulfill_request(db, actor, request_id, publication_id):
    if not has_capability(actor, "group.request.fulfill"):
        raise HTTPException(403, "Source fulfillment required")
    row = _request(db, actor, request_id, source=True)
    returned = row["status"] == "fulfilled" and (verdict := _verdict(db, row)) and verdict["outcome"] == "returned"
    if (row["status"] != "approved" and not returned) or row["reviewed_by"] == actor["id"]:
        raise HTTPException(409, "A different authorized fulfiller is required")
    if returned and publication_id == row["publication_id"]:
        raise HTTPException(409, "Choose a different released version after a return")
    if db.execute(f"SELECT id FROM {_table('group_request_verdicts')} "
                  "WHERE request_id=%s AND publication_id=%s",
                  (request_id, publication_id)).fetchone():
        raise HTTPException(409, "This release was already reviewed for this request")
    group_documents._assert_edge(db, group_documents._relationship(db, row["relationship_id"]))
    publication = db.execute(
        f"SELECT * FROM {_table('group_document_publications')} "
        "WHERE id=%s AND relationship_id=%s AND source_org_id=%s AND viewer_org_id=%s "
        "AND revoked_at IS NULL AND expires_at>%s",
        (publication_id, row["relationship_id"], actor["org_id"],
         row["requester_org_id"], utcnow().isoformat())).fetchone()
    if not publication:
        raise HTTPException(404, "Release not found")
    scope, params = evidence_scope_sql({**actor, "is_super_admin": False})
    source_item = db.execute("SELECT e.id FROM evidence_items e "
                             f"WHERE e.id=%s AND e.org_id=%s AND e.file_hash=%s AND e.status='current' AND {scope}",
                             [publication["evidence_id"], actor["org_id"], publication["file_hash"], *params]).fetchone()
    if not source_item:
        raise HTTPException(404, "Release not found")
    viewer = group_documents._org(db, row["requester_org_id"])
    with tenant_context(row["requester_org_id"], viewer["slug"], is_super_admin=False):
        target_db = get_db()
        try:
            user = target_db.execute("SELECT id,org_id,is_active,deleted_at FROM users WHERE id=%s AND org_id=%s",
                                     (row["requested_by"], row["requester_org_id"])).fetchone()
            if not user or not user["is_active"] or user["deleted_at"]:
                raise HTTPException(409, "Requester access is unavailable")
            roles = [r["role_key"] for r in target_db.execute(
                "SELECT role_key FROM user_roles WHERE user_id=%s", (user["id"],)).fetchall()]
            group_documents.released_item(target_db, {"id": user["id"], "org_id": user["org_id"],
                                                      "roles": roles}, publication_id)
        except HTTPException:
            raise HTTPException(409, "Grant the named requester access to this release first") from None
        finally:
            target_db.close()
    changed = db.execute(f"UPDATE {_table('group_evidence_requests')} SET status='fulfilled',publication_id=%s,"
               "fulfilled_by=%s,fulfilled_at=%s WHERE id=%s AND source_org_id=%s "
               "AND ((status='approved' AND publication_id IS NULL) OR "
               f"(status='fulfilled' AND publication_id=%s AND EXISTS "
               f"(SELECT 1 FROM {_table('group_request_verdicts')} v WHERE v.request_id=%s "
               "AND v.publication_id=%s AND v.outcome='returned')))",
               (publication_id, actor["id"], utcnow().isoformat(), request_id,
                actor["org_id"], row["publication_id"], request_id, row["publication_id"]))
    if changed.rowcount != 1:
        raise HTTPException(409, "The request changed; review it again")
    _event(db, row, actor, "request_refulfilled" if returned else "request_fulfilled")


def review_release(db, actor, request_id, outcome, reason):
    """Independent decision on this exact published version for the parent's claim."""
    if not has_capability(actor, "group.request.manage"):
        raise HTTPException(403, "Independent parent review required")
    row = _request(db, actor, request_id)
    if row["status"] != "fulfilled" or not row["publication_id"]:
        raise HTTPException(409, "Request has no released proof to review")
    if row["requested_by"] == actor["id"]:
        raise HTTPException(409, "A different specialist must review the proof")
    if outcome not in ("accepted", "returned"):
        raise HTTPException(422, "Choose accepted or returned")
    if _verdict(db, row):
        raise HTTPException(409, "This exact release already has a verdict")
    if outcome == "accepted":
        group_documents.released_item(db, actor, row["publication_id"])
    explanation = _required(reason, "verdict explanation", 500)
    insert_returning_id(db, f"INSERT INTO {_table('group_request_verdicts')} "
        "(request_id,requester_org_id,publication_id,outcome,reason,reviewed_by) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (request_id, actor["org_id"], row["publication_id"], outcome, explanation, actor["id"]))
    _event(db, row, actor, "request_proof_" + outcome)
    return outcome
