"""The relationship service: what a link may name, who may see it, and how it is stored.

One place for the three things Related Items, the Evidence Vault and `core/links.py` each used to do their
own way:

* WHICH records can be linked (the registry in `entity_scope`: a table, a title, a deep link, a scope rule);
* WHO may see a link: both ends must be records the viewer may open in their owning module, and a link never
  grants access to its target. A record the viewer may not open is simply left out, so no title, id, count or
  existence signal leaks, and an unknown record and a hidden one answer alike;
* HOW a link is stored: once, in one direction, with an active verb (`core.links.RELATIONSHIP_LABELS` gives the
  label for each side), with its provenance and status. A candidate proposed by a rule or an import is not shown
  until a permitted person confirms it.

Functions take the caller's connection and never commit; the caller commits and then calls `audit`, so a rolled
back change leaves no audit entry.
"""
import logging

from core.links import RELATIONSHIP_LABELS
from core.rbac import has_capability
from core.timeutils import utcnow
from modules.governance.entity_scope import (
    _KEY_ALIASES, canonical_key, describe_record, describe_records, is_linkable,
)

log = logging.getLogger("oneforall.relationships")

PROVENANCE = ("manual", "imported", "system", "system_candidate")  # who made an edge; core/links.py writes "system"
STATUSES = ("candidate", "confirmed", "rejected")
STATE_WORDS = {"confirmed": "recorded", "candidate": "suggested", "rejected": "disputed"}  # what a person is told
MAX_LIST = 200

_APP = ("governance", "application")
_PROCESS = ("governance", "process")
_ASSET = ("governance", "data_asset")
_VENDORS = (("sentinel", "vendor"), ("grid", "vendor"), ("bcm", "vendor"))

# The typed AI governance verbs and the pairs of kinds each may join. The nine older verbs join any two
# linkable kinds, as they always did. Anything not listed for a typed verb is refused.
PAIR_RULES = {
    "uses_data":   {(_APP, _ASSET)},
    "provided_by": {(_APP, vendor) for vendor in _VENDORS},
    "supports":    {(_APP, _PROCESS)},
    "assesses":    {(("sentinel", "aiia"), _APP), (("sentinel", "dpia"), _APP)},
    "covers":      {(("orm", "aims"), _APP)},
    "affects":     {(source, _APP) for source in (("bcm", "incident"), ("orm", "event"), ("sentinel", "breach"))},
    "impacts":     {(("erm", "obligation"), _APP)},
    "depends_on":  {(_APP, _PROCESS), (_PROCESS, _APP), (_APP, _APP)},
}


def _now() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


class LinkError(Exception):
    """A refused link operation. `message` is safe to show: it never names a record the viewer may not open."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _spellings(key):
    """A kind can be stored under more than one spelling (grid non_conformance is nc)."""
    return [key] + [alias for alias, canon in _KEY_ALIASES.items() if canon == key]


def _side_sql(prefix, key):
    spellings = _spellings(key)
    clause = " OR ".join(f"({prefix}_module = %s AND {prefix}_type = %s)" for _ in spellings)
    return f"({clause})", [part for spelling in spellings for part in spelling]


def _may_write(db, user, key, record_id) -> bool:
    """Creating or removing an edge on an application needs the AI use link capability, or being that
    application's owner. Other kinds keep the rule Related Items always had: open both ends."""
    if key != _APP:
        return True
    if has_capability(user, "ai_use.link"):
        return True
    row = db.execute("SELECT owner_user_id FROM applications WHERE id = %s", (record_id,)).fetchone()
    return bool(row and row[0] is not None and row[0] == user.get("id"))


def _validated_ends(db, user, source, target, relationship):
    (sm, st, sid), (tm, tt, tid) = source, target
    skey, tkey = canonical_key(sm, st), canonical_key(tm, tt)
    if not is_linkable(skey):
        raise LinkError(400, f"Unknown source entity: {sm}/{st}")
    if not is_linkable(tkey):
        raise LinkError(400, f"Unknown target entity: {tm}/{tt}")
    if not isinstance(sid, int) or not isinstance(tid, int) or isinstance(sid, bool) or isinstance(tid, bool):
        raise LinkError(400, "Invalid entity id")
    if relationship not in RELATIONSHIP_LABELS:
        raise LinkError(400, "Unknown relationship")
    if skey == tkey and sid == tid:
        raise LinkError(400, "Cannot link an entity to itself.")
    # One answer for "missing" and "not yours to open", so a link attempt cannot be used to probe for records.
    if not (describe_record(db, skey, sid, user) and describe_record(db, tkey, tid, user)):
        raise LinkError(404, "Entity not found.")
    rule = PAIR_RULES.get(relationship)
    if rule is not None and (skey, tkey) not in rule:
        raise LinkError(400, f"'{relationship}' cannot join {skey[0]}/{skey[1]} to {tkey[0]}/{tkey[1]}.")
    if not (_may_write(db, user, skey, sid) and _may_write(db, user, tkey, tid)):
        raise LinkError(403, "Access denied.")
    return skey, tkey


def create_link(db, user, source, target, relationship="related", *, provenance="manual", note="") -> dict:
    """Store one edge. `source` and `target` are (module, type, id). Returns
    {"link_id", "created": bool, "audit": (action, entity_id, details)}.

    A manual or imported edge is confirmed at once; a `system_candidate` stays a candidate. Linking again what is
    already linked returns that edge; a rejected edge linked again by a person is confirmed."""
    if provenance not in PROVENANCE:
        raise LinkError(400, "Unknown provenance")
    skey, tkey = _validated_ends(db, user, source, target, relationship)
    sid, tid = source[2], target[2]
    status = "candidate" if provenance == "system_candidate" else "confirmed"
    confirmed = status == "confirmed"
    values = (*skey, sid, *tkey, tid, relationship)
    row = db.execute(
        "INSERT INTO cross_module_links "
        "(source_module, source_type, source_id, target_module, target_type, target_id, relationship, "
        " created_by, provenance, status, confirmed_by, confirmed_at, note) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
        (*values, user["id"], provenance, status, user["id"] if confirmed else None, _now() if confirmed else None,
         (note or "")[:500] or None),
    ).fetchone()
    detail = f"{skey[0]}/{skey[1]}/{sid} -[{relationship}]-> {tkey[0]}/{tkey[1]}/{tid}"
    if row is not None:
        return {"link_id": row["id"], "created": True, "audit": ("link_create", row["id"], detail)}
    existing = db.execute(
        "SELECT id, status FROM cross_module_links WHERE source_module=%s AND source_type=%s AND source_id=%s "
        "AND target_module=%s AND target_type=%s AND target_id=%s AND relationship=%s", values,
    ).fetchone()
    if existing is None:
        raise LinkError(500, "Failed to insert link.")
    if existing["status"] == "rejected" and status == "confirmed":
        db.execute(
            "UPDATE cross_module_links SET status='confirmed', provenance=%s, confirmed_by=%s, "
            "confirmed_at=%s, created_by=%s WHERE id=%s",
            (provenance, user["id"], _now(), user["id"], existing["id"]),
        )
        return {"link_id": existing["id"], "created": True, "audit": ("link_create", existing["id"], detail)}
    return {"link_id": existing["id"], "created": False, "audit": None}


def _row_ends(row):
    return ((canonical_key(row["source_module"], row["source_type"]), row["source_id"]),
            (canonical_key(row["target_module"], row["target_type"]), row["target_id"]))


def list_links(db, user, key, record_id, *, include_candidates=False, include_rejected=False, limit=MAX_LIST) -> list:
    """The links of one record whose other end this user may also open, newest first. [] when the user may not
    open the record itself: the answer is the same as for a record that does not exist.

    Each link says what it is: `state` is recorded (somebody confirmed it), suggested (a rule or an import proposed it
    and nobody has) or disputed (somebody declined it). Suggested and disputed ones are listed only when asked for."""
    key = canonical_key(*key)
    if not is_linkable(key) or not describe_record(db, key, record_id, user):
        return []
    side_src, p_src = _side_sql("source", key)
    side_dst, p_dst = _side_sql("target", key)
    statuses = ("confirmed",) + (("candidate",) if include_candidates else ()) + (("rejected",) if include_rejected else ())
    rows = db.execute(
        "SELECT id, source_module, source_type, source_id, target_module, target_type, target_id, relationship, "
        "provenance, status, confirmed_at, created_at, note FROM cross_module_links "
        f"WHERE (({side_src} AND source_id = %s) OR ({side_dst} AND target_id = %s)) "
        f"AND COALESCE(status, 'confirmed') IN ({','.join(['%s'] * len(statuses))}) "
        "ORDER BY created_at DESC, id DESC LIMIT %s",
        [*p_src, record_id, *p_dst, record_id, *statuses, max(1, min(int(limit), MAX_LIST))],
    ).fetchall()

    wanted = {}
    placed = []
    for row in rows:
        (skey, sid), (tkey, tid) = _row_ends(row)
        outgoing = skey == key and sid == record_id
        other_key, other_id = (tkey, tid) if outgoing else (skey, sid)
        if is_linkable(other_key):
            wanted.setdefault(other_key, set()).add(other_id)
            placed.append((row, outgoing, other_key, other_id))
    described = {k: describe_records(db, k, ids, user) for k, ids in wanted.items()}

    results = []
    for row, outgoing, other_key, other_id in placed:
        shown = described.get(other_key, {}).get(other_id)
        if shown is None:
            continue
        forward, inverse = RELATIONSHIP_LABELS.get(row["relationship"], ("related to", "related to"))
        results.append({
            "link_id": row["id"], "module": other_key[0], "entity_type": other_key[1], "entity_id": other_id,
            "title": shown["title"], "url": shown["url"], "relationship": row["relationship"],
            "label": forward if outgoing else inverse, "direction": "outgoing" if outgoing else "incoming",
            "provenance": row["provenance"] or "legacy", "status": row["status"] or "confirmed",
            "state": STATE_WORDS.get(row["status"] or "confirmed", "recorded"),
        })
    return results


def remove_link(db, user, link_id) -> dict:
    """Delete one edge. Only the person who made it, an administrator, or a holder of the AI use link capability
    for an application edge may; both ends must still be records the caller may open."""
    row = db.execute(
        "SELECT id, created_by, source_module, source_type, source_id, target_module, target_type, target_id, "
        "relationship FROM cross_module_links WHERE id = %s", (link_id,),
    ).fetchone()
    if not row:
        raise LinkError(404, "Link not found.")
    (skey, sid), (tkey, tid) = _row_ends(row)
    if not (is_linkable(skey) and is_linkable(tkey)
            and describe_record(db, skey, sid, user) and describe_record(db, tkey, tid, user)):
        raise LinkError(404, "Link not found.")
    is_admin = has_capability(user, "platform.manage_users")
    app_edge = _APP in (skey, tkey) and has_capability(user, "ai_use.link")
    if not (is_admin or app_edge or row["created_by"] == user["id"]):
        raise LinkError(403, "Access denied.")
    db.execute("DELETE FROM cross_module_links WHERE id = %s", (link_id,))
    detail = (f"{row['source_module']}/{row['source_type']}/{sid} -> {row['target_module']}/{row['target_type']}/{tid}")
    return {"link_id": link_id, "audit": ("link_delete", link_id, detail)}


def set_link_status(db, user, link_id, status) -> dict:
    """Confirm or reject a candidate edge. The caller needs what creating that edge would need."""
    if status not in ("confirmed", "rejected"):
        raise LinkError(400, "Unknown status")
    row = db.execute(
        "SELECT id, source_module, source_type, source_id, target_module, target_type, target_id "
        "FROM cross_module_links WHERE id = %s", (link_id,),
    ).fetchone()
    if not row:
        raise LinkError(404, "Link not found.")
    (skey, sid), (tkey, tid) = _row_ends(row)
    if not (is_linkable(skey) and is_linkable(tkey)
            and describe_record(db, skey, sid, user) and describe_record(db, tkey, tid, user)):
        raise LinkError(404, "Link not found.")
    if not (_may_write(db, user, skey, sid) and _may_write(db, user, tkey, tid)):
        raise LinkError(403, "Access denied.")
    db.execute(
        "UPDATE cross_module_links SET status=%s, confirmed_by=%s, confirmed_at=%s WHERE id=%s",
        (status, user["id"], _now(), link_id),
    )
    return {"link_id": link_id, "audit": (f"link_{status}", link_id, f"{skey}/{sid} {status} {tkey}/{tid}")}


def neighbours(db, user, key, record_id, *, depth=2, limit=100) -> dict:
    """The records within `depth` confirmed edges of one record, each one openable by the viewer.

    Bounded on purpose: at most three hops and `limit` nodes. A record the viewer may not open is never a node,
    and never a step along the way to one that is."""
    key = canonical_key(*key)
    root = describe_record(db, key, record_id, user) if is_linkable(key) else None
    if root is None:
        return {"nodes": [], "edges": [], "truncated": False}
    depth = max(1, min(int(depth), 3))
    limit = max(1, min(int(limit), 200))
    nodes = {(key, record_id): {"module": key[0], "entity_type": key[1], "entity_id": record_id, **root}}
    edges, frontier, truncated = {}, [(key, record_id)], False
    for _ in range(depth):
        following = []
        for node_key, node_id in frontier:
            for link in list_links(db, user, node_key, node_id):
                other = (canonical_key(link["module"], link["entity_type"]), link["entity_id"])
                if other not in nodes:
                    if len(nodes) >= limit:
                        truncated = True
                        continue
                    nodes[other] = {"module": link["module"], "entity_type": link["entity_type"],
                                    "entity_id": link["entity_id"], "title": link["title"], "url": link["url"]}
                    following.append(other)
                ends = ((node_key, node_id), other) if link["direction"] == "outgoing" else (other, (node_key, node_id))
                edges[link["link_id"]] = {"link_id": link["link_id"], "relationship": link["relationship"],
                                          "from": list(ends[0][0]) + [ends[0][1]], "to": list(ends[1][0]) + [ends[1][1]]}
        frontier = following
    return {"nodes": list(nodes.values()), "edges": list(edges.values()), "truncated": truncated}


def audit(user, result) -> None:
    """Write the audit entry for a committed create, remove or status change (a no-op for a repeat)."""
    if not result or not result.get("audit"):
        return
    from core.middleware import log_audit
    action, entity_id, details = result["audit"]
    log_audit(user, "platform", action, "cross_module_link", entity_id, details=details)
