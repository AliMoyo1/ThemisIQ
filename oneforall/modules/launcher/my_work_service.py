"""
P01: Role-aware My Work action centre -- federated read model.

Discovery gate (task_plan.md P01, answered 2026-09-30): all 9 named sources
are in scope for v1 (task_board, the generic workflow engine, ARIA
approvals, evidence expiry, GRID non-conformances, ERM/ORM reviews, BCM
incidents, Sentinel/privacy deadlines, notifications); compliance_manager is
the first persona whose view must be complete; items with no trivial
in-place action are deep-link-only (no per-item quick-actions in v1).

This file wires the first, compliance_manager-facing slice: ARIA policy
approvals, evidence expiry, task_board, and notifications. The remaining
five sources (generic workflow_instances, GRID non-conformances, ERM/ORM
reviews, BCM incidents, Sentinel/privacy deadlines) are named in
_PENDING_SOURCES below rather than silently left out -- each needs the same
per-source scoping care already given to the four wired here (see F14/F16,
this same plan, for what happens when a source is queried without it), and
was not rushed just to claim "all 9" in one pass.

Per "Selected design": no new task table -- every item is normalized from
its own source table at read time. Every item has source_module,
entity_type, entity_id, action, title, due_date, priority, org_id/
business_unit_id, link, and section. Completion always happens at the
source; this module is read-only.
"""
from database import get_db, sql_date_offset, sql_current_date

_PENDING_SOURCES = [
    "workflow_instances (generic cross-module workflow engine)",
    "grid_non_conformances (GRID audit findings)",
    "erm_enterprise_risks / orm_events (ERM/ORM reviews)",
    "bcm_incidents (BCM incidents)",
    "sentinel_dsr / sentinel_breaches (privacy deadlines)",
]

SECTIONS = ("needs_my_action", "waiting_on_others", "due_soon", "overdue", "recently_completed")


def _section_for(status_bucket: str, due_date: "str | None") -> str:
    """status_bucket is one of 'open' (mine to act on now), 'waiting'
    (someone else's turn), or 'done' (already completed)."""
    if status_bucket == "done":
        return "recently_completed"
    if status_bucket == "waiting":
        return "waiting_on_others"
    if due_date:
        from core.timeutils import utcnow
        today = utcnow().strftime("%Y-%m-%d")
        due_10 = due_date[:10]
        if due_10 < today:
            return "overdue"
        # "Due soon" window matches evidence's own existing +30 day convention.
        from datetime import datetime, timedelta
        try:
            if datetime.strptime(due_10, "%Y-%m-%d") <= datetime.strptime(today, "%Y-%m-%d") + timedelta(days=30):
                return "due_soon"
        except ValueError:
            pass
    return "needs_my_action"


def _aria_approvals(db, user: dict) -> list[dict]:
    rows = db.execute(
        "SELECT a.id, a.status, a.requested_at, d.doc_id, d.title, d.org_id "
        "FROM aria_document_approvals a "
        "JOIN aria_documents d ON d.id = a.document_id "
        "WHERE a.approver_id=%s AND a.status='pending' AND d.org_id=%s "
        "ORDER BY a.requested_at",
        (user["id"], user.get("org_id")),
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "source_module": "aria", "entity_type": "policy_approval", "entity_id": r["id"],
            "action": "decide_approval",
            "title": f"Approve: {r['doc_id']} {r['title']}",
            "due_date": None, "priority": "high",
            "org_id": r["org_id"], "business_unit_id": None,
            "link": f"/aria/documents?open={r['doc_id']}",
            "section": "needs_my_action",
        })
    return items


def _evidence_expiring(db, user: dict) -> list[dict]:
    """Mirrors modules/evidence/routes.py's own "expiring" view (+30 days)
    and _scoped_evidence_item's org check (F14) -- NULL org_id is
    super-admin-only there too, so mirrored here rather than loosened."""
    where = "status = 'current' AND expiry_date IS NOT NULL " \
            f"AND expiry_date <= {sql_date_offset('+30 days')} AND expiry_date > {sql_current_date()}"
    params: list = []
    if not user.get("is_super_admin"):
        where += " AND org_id = %s"
        params.append(user.get("org_id"))
    rows = db.execute(
        f"SELECT id, title, expiry_date, org_id FROM evidence_items WHERE {where} "
        "ORDER BY expiry_date ASC LIMIT 100",
        params,
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "source_module": "evidence", "entity_type": "evidence_item", "entity_id": r["id"],
            "action": "renew_or_review",
            "title": f"Evidence expiring: {r['title']}",
            "due_date": r["expiry_date"], "priority": "medium",
            "org_id": r["org_id"], "business_unit_id": None,
            "link": f"/evidence/?open={r['id']}",
            "section": _section_for("open", r["expiry_date"]),
        })
    return items


def _my_tasks(db, user: dict) -> list[dict]:
    """No org/BU column exists on task_board -- safe without one here
    specifically because this query is already restricted to rows this
    user is personally assigned_to or created_by, not a broad listing (the
    class of gap F14/F16 fixed is an unrestricted list by id, not this)."""
    rows = db.execute(
        "SELECT id, title, status, priority, due_date, assigned_to, created_by "
        "FROM task_board WHERE (assigned_to = %s OR created_by = %s) "
        "AND status NOT IN ('cancelled') ORDER BY "
        "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC LIMIT 100",
        (user["id"], user["id"]),
    ).fetchall()
    items = []
    for r in rows:
        if r["status"] == "done":
            bucket = "done"
        elif r["assigned_to"] == user["id"]:
            bucket = "open"
        else:
            bucket = "waiting"
        items.append({
            "source_module": "platform", "entity_type": "task", "entity_id": r["id"],
            "action": "update_task",
            "title": r["title"],
            "due_date": r["due_date"], "priority": r["priority"] or "medium",
            "org_id": None, "business_unit_id": None,
            "link": f"/tasks?open={r['id']}",
            "section": _section_for(bucket, r["due_date"]),
        })
    return items


def _unread_notifications(db, user: dict) -> list[dict]:
    rows = db.execute(
        "SELECT id, module, title, message, link, created_at FROM notifications "
        "WHERE user_id = %s AND is_read = 0 ORDER BY created_at DESC LIMIT 50",
        (user["id"],),
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "source_module": r["module"] or "platform", "entity_type": "notification", "entity_id": r["id"],
            "action": "acknowledge",
            "title": r["title"],
            "due_date": None, "priority": "low",
            "org_id": None, "business_unit_id": None,
            "link": r["link"] or "/",
            "section": "needs_my_action",
        })
    return items


def get_my_work(user: dict) -> dict:
    """Returns {"sections": {name: [items]}, "pending_sources": [...]}.

    Read-only, federated across the wired sources -- see module docstring
    for which sources are wired vs. named-but-pending.
    """
    db = get_db()
    try:
        all_items = (
            _aria_approvals(db, user)
            + _evidence_expiring(db, user)
            + _my_tasks(db, user)
            + _unread_notifications(db, user)
        )
    finally:
        db.close()

    sections: dict[str, list] = {s: [] for s in SECTIONS}
    for item in all_items:
        sections[item["section"]].append(item)
    for name in sections:
        sections[name].sort(key=lambda it: (it["due_date"] or "9999-99-99"))

    return {"sections": sections, "pending_sources": _PENDING_SOURCES}
