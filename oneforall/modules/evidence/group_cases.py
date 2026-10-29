"""Parent-only group cases built from reviewed proof requests.

Cases contain the parent's position and references, never a subsidiary's
internal mapping. A child sees its own request through group_requests only.
"""

from fastapi import HTTPException

from config import settings
from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.evidence import group_documents, group_requests


def _table(name):
    return f"public.{name}" if settings.is_postgres() else name


def _case(db, actor, case_id):
    if not isinstance(case_id, int) or case_id <= 0 or not actor.get("org_id"):
        raise HTTPException(404, "Case not found")
    row = db.execute(
        f"SELECT * FROM {_table('group_cases')} WHERE id=%s AND parent_org_id=%s",
        (case_id, actor["org_id"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Case not found")
    return row


def _event(db, row, actor, action, detail):
    db.execute(
        f"INSERT INTO {_table('group_case_events')} "
        "(case_id,parent_org_id,actor_id,action,detail) VALUES (%s,%s,%s,%s,%s)",
        (row["id"], row["parent_org_id"], actor["id"], action, detail),
    )


def create_case(db, actor, reference, title, position):
    if not has_capability(actor, "group.case.manage") or not actor.get("org_id"):
        raise HTTPException(403, "Group case management required")
    ref = group_requests._required(reference, "case reference", 100)
    name = group_requests._required(title, "case title", 200)
    stance = group_requests._required(position, "parent position", 2000)
    if db.execute(
        f"SELECT id FROM {_table('group_cases')} WHERE parent_org_id=%s AND reference=%s",
        (actor["org_id"], ref),
    ).fetchone():
        raise HTTPException(409, "Case reference already exists")
    case_id = insert_returning_id(
        db, f"INSERT INTO {_table('group_cases')} "
        "(parent_org_id,reference,title,position,created_by) VALUES (%s,%s,%s,%s,%s)",
        (actor["org_id"], ref, name, stance, actor["id"]),
    )
    _event(db, _case(db, actor, case_id), actor, "created", ref)
    return case_id


def list_cases(db, actor, *, page=1):
    if not any(has_capability(actor, cap) for cap in ("group.case.manage", "group.case.review")):
        raise HTTPException(403, "Group case access required")
    if not actor.get("org_id") or not isinstance(page, int) or not 1 <= page <= 10000:
        raise HTTPException(422, "Invalid case page")
    rows = db.execute(
        f"SELECT c.id,c.reference,c.title,c.status,c.created_at,c.closed_at,"
        f"(SELECT COUNT(*) FROM {_table('group_case_requests')} cr "
        "WHERE cr.case_id=c.id AND cr.parent_org_id=c.parent_org_id) AS request_count "
        f"FROM {_table('group_cases')} c WHERE c.parent_org_id=%s "
        "ORDER BY c.id DESC LIMIT %s OFFSET %s",
        (actor["org_id"], 51, (page - 1) * 50),
    ).fetchall()
    return {"items": [dict(row) for row in rows[:50]], "page": page, "has_more": len(rows) > 50,
            "can_manage": has_capability(actor, "group.case.manage"),
            "can_review": has_capability(actor, "group.case.review")}


def case_detail(db, actor, case_id):
    if not any(has_capability(actor, cap) for cap in ("group.case.manage", "group.case.review")):
        raise HTTPException(403, "Group case access required")
    row = _case(db, actor, case_id)
    requests = db.execute(
        f"SELECT r.id,r.requester_org_id,r.requirement_ref,r.status,r.needed_by,r.source_org_id,r.publication_id "
        f"FROM {_table('group_case_requests')} cr "
        f"JOIN {_table('group_evidence_requests')} r ON r.id=cr.request_id "
        "AND r.requester_org_id=cr.parent_org_id "
        "WHERE cr.case_id=%s AND cr.parent_org_id=%s ORDER BY cr.linked_at,cr.request_id",
        (case_id, actor["org_id"]),
    ).fetchall()
    items = []
    for request in requests:
        verdict = group_requests._verdict(db, request)
        items.append({"id": request["id"], "requirement_ref": request["requirement_ref"],
                      "status": request["status"], "needed_by": request["needed_by"],
                      "source_org_id": request["source_org_id"],
                      "verdict": verdict["outcome"] if verdict else None})
    events = db.execute(
        f"SELECT actor_id,action,detail,created_at FROM {_table('group_case_events')} "
        "WHERE case_id=%s AND parent_org_id=%s ORDER BY id DESC LIMIT 100",
        (case_id, actor["org_id"]),
    ).fetchall()
    return {"case": dict(row), "requests": items, "events": [dict(event) for event in events],
            "can_manage": has_capability(actor, "group.case.manage") and row["status"] == "open",
            "can_close": has_capability(actor, "group.case.review") and row["status"] == "open"
                         and row["created_by"] != actor["id"]}


def link_request(db, actor, case_id, request_id):
    if not has_capability(actor, "group.case.manage"):
        raise HTTPException(403, "Group case management required")
    row = _case(db, actor, case_id)
    if row["status"] != "open":
        raise HTTPException(409, "Closed cases cannot be changed")
    if not isinstance(request_id, int) or request_id <= 0:
        raise HTTPException(422, "Choose a proof request")
    request = group_requests._request(db, actor, request_id)
    relation = group_documents._relationship(db, request["relationship_id"])
    if relation["parent_org_id"] != actor["org_id"]:
        raise HTTPException(404, "Request not found")
    group_documents._assert_edge(db, relation)
    if db.execute(
        f"SELECT case_id FROM {_table('group_case_requests')} WHERE request_id=%s", (request_id,)
    ).fetchone():
        raise HTTPException(409, "Request is already linked to a case")
    db.execute(
        f"INSERT INTO {_table('group_case_requests')} "
        "(case_id,request_id,parent_org_id,linked_by) VALUES (%s,%s,%s,%s)",
        (case_id, request_id, actor["org_id"], actor["id"]),
    )
    _event(db, row, actor, "request_linked", str(request_id))


def close_case(db, actor, case_id, reason):
    if not has_capability(actor, "group.case.review"):
        raise HTTPException(403, "Independent case review required")
    row = _case(db, actor, case_id)
    if row["status"] != "open":
        raise HTTPException(409, "Case is already closed")
    if row["created_by"] == actor["id"]:
        raise HTTPException(409, "A different specialist must close the case")
    explanation = group_requests._required(reason, "case conclusion", 2000)
    linked = db.execute(
        f"SELECT r.* FROM {_table('group_case_requests')} cr "
        f"JOIN {_table('group_evidence_requests')} r ON r.id=cr.request_id "
        "AND r.requester_org_id=cr.parent_org_id "
        "WHERE cr.case_id=%s AND cr.parent_org_id=%s ORDER BY cr.request_id",
        (case_id, actor["org_id"]),
    ).fetchall()
    if not linked:
        raise HTTPException(409, "Link a reviewed proof request before closing")
    gaps = False
    for request in linked:
        if request["status"] in ("no_proof", "declined"):
            gaps = True
            continue
        verdict = group_requests._verdict(db, request)
        if request["status"] != "fulfilled" or not verdict or verdict["outcome"] != "accepted":
            raise HTTPException(409, "Resolve every linked proof request before closing")
        # An earlier acceptance does not keep a revoked, expired or superseded
        # release available to this independent reviewer.
        group_documents.released_item(db, actor, request["publication_id"])
    status = "closed_with_gaps" if gaps else "closed"
    changed = db.execute(
        f"UPDATE {_table('group_cases')} SET status=%s,closed_by=%s,closed_at=%s,close_reason=%s "
        "WHERE id=%s AND parent_org_id=%s AND status='open'",
        (status, actor["id"], utcnow().isoformat(), explanation, case_id, actor["org_id"]),
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "Case changed; review it again")
    _event(db, row, actor, status, explanation)
    return status
