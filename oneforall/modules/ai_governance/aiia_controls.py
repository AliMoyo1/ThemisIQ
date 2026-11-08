"""Reviewable AIIA control context derived only from visible confirmed links.

Canonical AIMS controls and ARIA controls have different identities. A title or
numeric ID match is never treated as a verified crosswalk.
"""

from core.rbac import has_capability
from modules.ai_governance import assessments, controls
from modules.ai_governance.service import ServiceError
from modules.governance import relationships
from modules.governance.entity_scope import canonical_key, describe_records


_AIIA = ("sentinel", "aiia")
_CONTROL = ("aria", "control")


def context(db, user, assessment_id: int) -> "dict | None":
    row = assessments.get_assessment(db, user, assessment_id)
    if row is None:
        return None
    sources = [
        (("governance", "application"), row.get("application_id"), "Linked to the AI system"),
        (("sentinel", "ropa"), row.get("ropa_id"), "Linked to its processing record"),
        (("sentinel", "dpia"), row.get("dpia_id"), "Linked to its DPIA"),
    ]
    ranked = {}
    for key, record_id, reason in sources:
        if not record_id:
            continue
        for link in relationships.iter_visible_links(db, user, key, record_id):
            if canonical_key(link["module"], link["entity_type"]) == _CONTROL:
                ranked.setdefault(link["entity_id"], set()).add(reason)
    existing = {link["entity_id"]: link["status"] for link in relationships.iter_visible_links(
        db, user, _AIIA, assessment_id, include_candidates=True, include_rejected=True
    ) if canonical_key(link["module"], link["entity_type"]) == _CONTROL}
    candidate_ids = [control_id for control_id in ranked if control_id not in existing][:50]
    shown = describe_records(db, _CONTROL, candidate_ids, user)
    ids = list(shown)
    details = {}
    if ids:
        marks = ",".join(["%s"] * len(ids))
        details = {r["id"]: r for r in db.execute(
            f"SELECT id,ref,status FROM controls WHERE id IN ({marks})", ids
        ).fetchall()}
    items = [
        {"control_id": control_id, "ref": details[control_id]["ref"],
         "title": record["title"], "url": record["url"],
         "status": details[control_id]["status"], "reasons": sorted(ranked[control_id])}
        for control_id, record in shown.items() if control_id in details
    ]
    ai_control_context = []
    if row.get("application_id") and has_capability(user, "ai_use.view"):
        # This is read-only AIMS context, never an ARIA control suggestion.
        ai_control_context = controls.use_controls(db, user, row["application_id"], proof_limit=3) or []
    return {"items": items, "ai_controls": ai_control_context}


def decide(db, user, assessment_id: int, control_id: int, action: str) -> dict:
    if not has_capability(user, "ai_assessment.manage"):
        raise ServiceError(403, "Access denied.")
    if action not in ("accept", "dismiss") or type(control_id) is not int:
        raise ServiceError(400, "Choose a control suggestion and accept or dismiss it.")
    available = context(db, user, assessment_id)
    if available is None or control_id not in {item["control_id"] for item in available["items"]}:
        raise ServiceError(404, "Control suggestion not found.")
    try:
        link = relationships.create_link(
            db, user, (*_AIIA, assessment_id), (*_CONTROL, control_id), "mitigates",
            provenance="system_candidate", note="AIIA specialist reviewed an existing confirmed connection",
        )
        relationships.set_link_status(db, user, link["link_id"],
                                      "confirmed" if action == "accept" else "rejected")
    except relationships.LinkError as exc:
        raise ServiceError(exc.status, exc.message) from None
    return {"status": "confirmed" if action == "accept" else "rejected", "events": [],
            "audit": [("aiia_control_suggestion_reviewed", "aiia", assessment_id,
                       f"control={control_id}; decision={action}")]}
