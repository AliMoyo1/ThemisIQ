"""Read-only ARIA controls a visible continuity plan may depend on.

Only confirmed Related Items edges and BIA links are traversed. The result
describes existing records; it does not attest that a control still works.
"""

from modules.governance import relationships
from modules.governance.entity_scope import describe_record, describe_records, entity_scope_sql
from modules.governance.entity_scope import canonical_key

PLAN = ("bcm", "plan")
CONTROL = ("aria", "control")
PAGE = relationships.MAX_LIST


def _all_visible_links(db, user, key, record_id):
    """Page raw edges, since a page may contain only hidden counterpart records."""
    yield from relationships.iter_visible_links(db, user, key, record_id)


def for_plan(db, user, plan_id: int) -> "list[dict] | None":
    if describe_record(db, PLAN, plan_id, user) is None:
        return None
    candidates = {}

    def add_edges(key, record_id, reason):
        for edge in _all_visible_links(db, user, key, record_id):
            other = canonical_key(edge["module"], edge["entity_type"])
            if other == CONTROL:
                candidates.setdefault(edge["entity_id"], set()).add(reason)
            elif other in (("governance", "application"), ("bcm", "compliance_control")):
                # One extra confirmed hop; an application or BCM control is a
                # source of dependencies only if the viewer can open both ends.
                for nested in _all_visible_links(db, user, other, edge["entity_id"]):
                    if canonical_key(nested["module"], nested["entity_type"]) == CONTROL:
                        candidates.setdefault(nested["entity_id"], set()).add(
                            reason + " via " + ("an application" if other[0] == "governance" else "a BCM control")
                        )

    add_edges(PLAN, plan_id, "Linked directly to this plan")
    scope, params = entity_scope_sql(("bcm", "bia"), user, "b")
    after_id = 0
    while True:
        rows = db.execute(
            "SELECT b.id,b.business_process_id FROM bcm_bia_plan_links l "
            "JOIN bcm_bia_records b ON b.id=l.bia_id "
            f"WHERE l.plan_id=%s AND b.id>%s AND {scope} ORDER BY b.id LIMIT %s",
            [plan_id, after_id, *params, PAGE],
        ).fetchall()
        for row in rows:
            add_edges(("bcm", "bia"), row["id"], "Linked to this plan's impact analysis")
            process_id = row["business_process_id"]
            if process_id and describe_record(db, ("governance", "process"), process_id, user):
                add_edges(("governance", "process"), process_id, "Linked to a covered business process")
        if len(rows) < PAGE:
            break
        after_id = rows[-1]["id"]
    described = {}
    control_ids = list(candidates)
    for start in range(0, len(control_ids), PAGE):
        described.update(describe_records(db, CONTROL, control_ids[start:start + PAGE], user))
    if not described:
        return []
    details = {}
    described_ids = list(described)
    for start in range(0, len(described_ids), PAGE):
        ids = described_ids[start:start + PAGE]
        marks = ",".join(["%s"] * len(ids))
        details.update({r["id"]: r for r in db.execute(
            f"SELECT id,ref,status FROM controls WHERE id IN ({marks})", ids
        ).fetchall()})
    return [{"id": control_id, "ref": details[control_id]["ref"],
             "title": shown["title"], "url": shown["url"],
             "status": details[control_id]["status"], "sources": sorted(candidates[control_id]),
             "check": "Verify during activation; a recorded status is not a live test"}
            for control_id, shown in sorted(described.items()) if control_id in details]
