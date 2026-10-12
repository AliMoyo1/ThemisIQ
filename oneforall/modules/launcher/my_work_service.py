"""PLAN-36 P01 federated, scoped, read-only My Work feed.

Every adapter reads the canonical source. Source failures are isolated and
reported as unavailable; no action is completed here.
"""
from database import get_db, sql_date_offset
from config import settings
from core.rbac import has_capability
from modules.governance.data_service import bu_scope_ids
import logging
import base64
import binascii
import json
from modules.saved_views.data_service import register_view_schema

register_view_schema("platform", "my_work", allowed_params={"source", "section", "q"})

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
        due_10 = str(due_date)[:10]
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
    bu_where, bu_params = _bu_filter("d.business_unit_id", bu_scope_ids(user))
    rows = db.execute(
        "SELECT a.id, a.status, a.requested_at, d.doc_id, d.title, d.org_id, d.business_unit_id "
        "FROM aria_document_approvals a "
        "JOIN aria_documents d ON d.id = a.document_id "
        f"WHERE a.approver_id=%s AND a.status='pending' AND d.org_id=%s AND {bu_where} "
        "ORDER BY a.requested_at",
        [user["id"], user.get("org_id")] + bu_params,
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "source_module": "aria", "entity_type": "policy_approval", "entity_id": r["id"],
            "action": "decide_approval",
            "title": f"Approve: {r['doc_id']} {r['title']}",
            "due_date": None, "priority": "high",
            "org_id": r["org_id"], "business_unit_id": r["business_unit_id"],
            "link": f"/aria/documents?open={r['doc_id']}",
            "section": "needs_my_action",
        })
    return items


def _evidence_expiring(db, user: dict) -> list[dict]:
    """Mirrors modules/evidence/routes.py's own "expiring" view (+30 days)
    and _scoped_evidence_item's org check (F14) -- NULL org_id is
    super-admin-only there too, so mirrored here rather than loosened."""
    where = "status = 'current' AND expiry_date IS NOT NULL " \
            f"AND expiry_date <= {sql_date_offset('+30 days')} "
    params: list = []
    if not user.get("is_super_admin"):
        where += " AND org_id = %s"
        params.append(user.get("org_id"))
    bu_where, bu_params = _bu_filter("business_unit_id", bu_scope_ids(user))
    rows = db.execute(
        f"SELECT id, title, expiry_date, org_id, business_unit_id FROM evidence_items "
        f"WHERE {where} AND {bu_where} ORDER BY expiry_date ASC LIMIT 100",
        params + bu_params,
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "source_module": "evidence", "entity_type": "evidence_item", "entity_id": r["id"],
            "action": "renew_or_review",
            "title": f"Evidence expiring: {r['title']}",
            "due_date": r["expiry_date"], "priority": "medium",
            "org_id": r["org_id"], "business_unit_id": r["business_unit_id"],
            "link": f"/evidence/?open=item:{r['id']}",
            "section": _section_for("open", r["expiry_date"]),
        })
    return items


def _my_tasks(db, user: dict) -> list[dict]:
    """Restrict to personal tasks and the same BU visibility as Task Board."""
    bu_where, bu_params = _bu_filter("business_unit_id", bu_scope_ids(user))
    rows = db.execute(
        "SELECT id, title, status, priority, due_date, assigned_to, created_by, business_unit_id "
        "FROM task_board WHERE (assigned_to = %s OR created_by = %s) "
        f"AND status NOT IN ('cancelled') AND {bu_where} ORDER BY "
        "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC LIMIT 100",
        [user["id"], user["id"]] + bu_params,
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
            "org_id": user.get("org_id"), "business_unit_id": r["business_unit_id"],
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
            "org_id": user.get("org_id"), "business_unit_id": None,
            "link": r["link"] if (r["link"] or "").startswith("/") and not (r["link"] or "").startswith("//") else "/",
            "section": "needs_my_action",
        })
    return items



log = logging.getLogger("launcher.my_work")


def _bu_filter(column: str, scope, *, require_explicit=False):
    """Return a parameterized SBU predicate; strict mode protects orgless SQLite tables."""
    if require_explicit and not settings.is_postgres():
        if scope is None or scope == [-1]:
            return "1=0", []
        marks = ",".join(["%s"] * len(scope))
        return f"{column} IN ({marks})", list(scope)
    if scope is None:
        return "1=1", []
    marks = ",".join(["%s"] * len(scope)) if scope else "NULL"
    return f"({column} IS NULL OR {column} IN ({marks}))", list(scope)


def _module_ok(user, module):
    if not has_capability(user, f"module.{module}.access"):
        return False
    licensed = user.get("licensed_modules")
    return user.get("is_super_admin") or licensed is None or module in licensed


def _workflow_actions(db, user):
    rows = db.execute(
        "SELECT wa.id,wa.action_type,wa.due_at,wi.id AS instance_id,"
        "wd.name AS workflow_name,wi.entity_module "
        "FROM workflow_actions wa JOIN workflow_instances wi ON wi.id=wa.instance_id "
        "JOIN workflow_definitions wd ON wd.id=wi.definition_id "
        "JOIN users starter ON starter.id=wi.started_by "
        "WHERE wa.assigned_to=%s AND wa.status='pending' AND wi.status='active' "
        "AND COALESCE(wi.org_id,starter.org_id)=%s "
        "ORDER BY wa.due_at,wa.id LIMIT 100",
        (user["id"], user.get("org_id")),
    ).fetchall()
    items = []
    for row in rows:
        module = (row["entity_module"] or "").lower()
        if module in ("aria","grid","bcm","sentinel","erm","orm") and not _module_ok(user,module):
            continue
        items.append({
            "source_module": module or "platform", "entity_type": "workflow_action",
            "entity_id": row["id"], "action": "decide_workflow",
            "title": f"Workflow decision: {row['workflow_name']}",
            "due_date": row["due_at"], "priority": "high",
            "org_id": user.get("org_id"), "business_unit_id": None,
            "link": f"/workflows?instance={row['instance_id']}",
            "section": _section_for("open", row["due_at"]),
        })
    return items


def _grid_ncs(db, user, scope):
    where, params = _bu_filter("a.business_unit_id", scope)
    rows = db.execute(
        "SELECT nc.id,nc.audit_id,nc.title,nc.severity,nc.due_date,nc.assigned_to,"
        "a.business_unit_id FROM grid_non_conformances nc "
        "JOIN grid_audits a ON a.id=nc.audit_id "
        f"WHERE nc.status='open' AND (nc.assigned_to=%s OR a.lead_id=%s) AND {where} "
        "ORDER BY nc.due_date,nc.id LIMIT 100",
        [user["id"], user["id"]] + params,
    ).fetchall()
    return [{
        "source_module": "grid", "entity_type": "non_conformance", "entity_id": r["id"],
        "action": "resolve_non_conformance", "title": f"Audit finding: {r['title']}",
        "due_date": r["due_date"], "priority": r["severity"] or "medium",
        "org_id": user.get("org_id"), "business_unit_id": r["business_unit_id"],
        "link": f"/grid/?open=nc:{r['id']}", "section": _section_for(
            "open" if r["assigned_to"] == user["id"] else "waiting", r["due_date"]),
    } for r in rows]


def _erm_reviews(db, user, scope):
    where, params = _bu_filter("business_unit_id", scope)
    rows = db.execute(
        "SELECT id,title,review_date,status,owner_id,reviewer_id,business_unit_id "
        "FROM erm_enterprise_risks WHERE (owner_id=%s OR reviewer_id=%s) "
        f"AND status NOT IN ('closed','archived') AND {where} "
        "ORDER BY review_date,id LIMIT 100",
        [user["id"], user["id"]] + params,
    ).fetchall()
    return [{
        "source_module": "erm", "entity_type": "risk_review", "entity_id": r["id"],
        "action": "review_risk", "title": f"Risk review: {r['title']}",
        "due_date": r["review_date"], "priority": "medium",
        "org_id": user.get("org_id"), "business_unit_id": r["business_unit_id"],
        "link": f"/erm/?open=risk:{r['id']}", "section": _section_for(
            "open" if r["reviewer_id"] == user["id"] else "waiting", r["review_date"]),
    } for r in rows]


def _orm_reviews(db, user, scope):
    where, params = _bu_filter("business_unit_id", scope)
    rows = db.execute(
        "SELECT id,title,severity,status,owner_id,business_unit_id,response_due_at "
        "FROM orm_events WHERE owner_id=%s AND status NOT IN ('closed','resolved') "
        f"AND {where} ORDER BY response_due_at,id LIMIT 100",
        [user["id"]] + params,
    ).fetchall()
    return [{
        "source_module": "orm", "entity_type": "operational_event", "entity_id": r["id"],
        "action": "review_event", "title": f"Operational event: {r['title']}",
        "due_date": r["response_due_at"], "priority": r["severity"] or "medium",
        "org_id": user.get("org_id"), "business_unit_id": r["business_unit_id"],
        "link": f"/orm/?open=event:{r['id']}", "section": _section_for("open", r["response_due_at"]),
    } for r in rows]


def _bcm_incidents(db, user, scope):
    where, params = _bu_filter("business_unit_id", scope, require_explicit=True)
    rows = db.execute(
        "SELECT id,title,severity,status,business_unit_id FROM bcm_incidents "
        f"WHERE status NOT IN ('closed','resolved') AND {where} "
        "ORDER BY updated_at DESC LIMIT 100",
        params,
    ).fetchall()
    return [{
        "source_module": "bcm", "entity_type": "incident", "entity_id": r["id"],
        "action": "update_incident", "title": f"BCM incident: {r['title']}",
        "due_date": None, "priority": r["severity"] or "high",
        "org_id": user.get("org_id"), "business_unit_id": r["business_unit_id"],
        "link": f"/bcm/?open=incident:{r['id']}", "section": "needs_my_action",
    } for r in rows]


def _privacy_deadlines(db, user, scope):
    where, params = _bu_filter("business_unit_id", scope, require_explicit=True)
    dsrs = db.execute(
        "SELECT id,ref_number,deadline_date,business_unit_id FROM sentinel_dsr "
        f"WHERE status NOT IN ('completed','closed','cancelled') AND {where} "
        "ORDER BY deadline_date,id LIMIT 100", params,
    ).fetchall()
    result = [{
        "source_module": "sentinel", "entity_type": "dsr", "entity_id": r["id"],
        "action": "respond_to_dsr", "title": f"Data subject request {r['ref_number']}",
        "due_date": r["deadline_date"], "priority": "high",
        "org_id": user.get("org_id"), "business_unit_id": r["business_unit_id"],
        "link": f"/sentinel/?open=dsr:{r['id']}", "section": _section_for("open", r["deadline_date"]),
    } for r in dsrs]
    if has_capability(user, "sentinel.breach.manage"):
        breaches = db.execute(
            "SELECT id,title,severity,business_unit_id,notify_deadline "
            "FROM sentinel_breaches "
            f"WHERE notification_required=1 AND authority_notified=0 AND {where} "
            "ORDER BY created_at DESC LIMIT 100", params,
        ).fetchall()
        result.extend({
            "source_module": "sentinel", "entity_type": "breach", "entity_id": r["id"],
            "action": "notify_authority", "title": f"Breach notification: {r['title']}",
            "due_date": r["notify_deadline"], "priority": r["severity"] or "high",
            "org_id": user.get("org_id"), "business_unit_id": r["business_unit_id"],
            "link": f"/sentinel/?open=breach:{r['id']}",
            "section": _section_for("open", r["notify_deadline"]),
        } for r in breaches)
    return result


def _ai_governance_work(db, user: dict, scope) -> list[dict]:
    """AI Governance as the person meets it: decisions to make or waiting on, requests to review or to fix, conditions
    that fall due and approvals that need a new decision. Read through the same unit scope as the module's own pages."""
    from core import ai_rollout
    from modules.governance.entity_scope import entity_scope_sql
    if not ai_rollout.is_enabled(user.get("org_id")):
        return []
    items = []
    org = user.get("org_id")
    app_scope, app_params = entity_scope_sql(("governance", "application"), user, "a")

    def add(entity_type, entity_id, action, title, link, bucket, due=None, unit=None, priority="medium"):
        items.append({
            "source_module": "ai_governance", "entity_type": entity_type, "entity_id": entity_id, "action": action,
            "title": title, "due_date": due, "priority": priority, "org_id": org, "business_unit_id": unit,
            "link": link, "section": _section_for(bucket, due)})

    if has_capability(user, "ai_literacy.take"):
        from modules.ai_governance import literacy
        for course in literacy.my_courses(db, user)["items"]:
            if course["state"] in ("to_do", "overdue", "expired"):
                add("ai_literacy_course", course["id"], "complete_ai_literacy",
                    f"Complete AI literacy: {course['title']}",
                    f"/ai-governance/literacy/{course['id']}", "open",
                    due=course["due_at"][:10] if course["due_at"] else None,
                    priority="high" if course["state"] in ("overdue", "expired") else "medium")

    # decisions waiting
    can_decide = has_capability(user, "ai_use.decide")
    separation = ai_rollout.separation_required(org)
    for r in db.execute(
            "SELECT d.id, d.application_id, d.requested_by, d.business_unit_id, a.name, a.owner_user_id "
            "FROM ai_use_decisions d JOIN applications a ON a.id = d.application_id "
            f"WHERE d.status = 'proposed' AND {app_scope} ORDER BY d.id LIMIT 100", app_params).fetchall():
        mine = r["requested_by"] == user["id"] or r["owner_user_id"] == user["id"]
        link = f"/ai-governance/systems/{r['application_id']}#decisions"
        if can_decide and not (separation and mine):
            add("ai_decision", r["id"], "decide_ai_use", f"Decide: {r['name']}", link, "open", unit=r["business_unit_id"], priority="high")
        elif mine:
            add("ai_decision_waiting", r["id"], "view", f"Waiting for a decision: {r['name']}", link, "waiting", unit=r["business_unit_id"])

    # approvals that need a new decision, for the owner and the deciders
    for r in db.execute(
            "SELECT d.id, d.application_id, d.expires_at, d.decided_at, d.profile_fingerprint, d.tier, d.business_unit_id, a.name, a.owner_user_id, "
            "p.fingerprint AS now_fingerprint, p.provisional_tier, p.adopted_tier FROM ai_use_decisions d "
            "JOIN applications a ON a.id = d.application_id JOIN ai_use_profiles p ON p.application_id = d.application_id "
            "WHERE d.status IN ('approved', 'approved_with_conditions') AND d.revoked_at IS NULL AND a.is_active = 1 "
            "AND d.id = (SELECT MAX(x.id) FROM ai_use_decisions x WHERE x.application_id = d.application_id "
            "AND x.status IN ('approved', 'approved_with_conditions', 'rejected')) "
            f"AND {app_scope} ORDER BY d.id LIMIT 100", app_params).fetchall():
        if not (r["owner_user_id"] == user["id"] or can_decide):
            continue
        from modules.ai_governance import rules
        tier_now = rules.effective_tier(r["provisional_tier"], r["adopted_tier"])
        expired = bool(r["expires_at"]) and str(r["expires_at"])[:10] < _today()
        from modules.ai_governance import decisions as _decisions
        if (r["now_fingerprint"] != r["profile_fingerprint"] or tier_now != r["tier"] or expired
                or _decisions.reopening_facts(db, r["application_id"], r["decided_at"])):
            add("ai_re_review", r["id"], "request_decision", f"Needs a new decision: {r['name']}",
                f"/ai-governance/systems/{r['application_id']}#decisions", "open", unit=r["business_unit_id"])

    # conditions that fall due: the owner's and the asker's
    for r in db.execute(
            "SELECT c.id, c.text, c.due_date, d.application_id, d.requested_by, d.business_unit_id, a.name, a.owner_user_id "
            "FROM ai_use_decision_conditions c JOIN ai_use_decisions d ON d.id = c.decision_id "
            "JOIN applications a ON a.id = d.application_id "
            "WHERE c.status = 'open' AND c.due_date IS NOT NULL AND d.revoked_at IS NULL "
            f"AND (a.owner_user_id = %s OR d.requested_by = %s) AND {app_scope} ORDER BY c.due_date LIMIT 100",
            [user["id"], user["id"], *app_params]).fetchall():
        add("ai_condition", r["id"], "meet_condition", f"Condition due: {r['text']} ({r['name']})",
            f"/ai-governance/systems/{r['application_id']}#decisions", "open", due=r["due_date"], unit=r["business_unit_id"])

    # regulatory changes proposed for a use, for the reviewer
    if has_capability(user, "ai_use.review"):
        for r in db.execute(
                "SELECT i.id, i.business_unit_id, u.title, a.name FROM ai_regulatory_impacts i "
                "JOIN regulatory_updates u ON u.id = i.update_id JOIN applications a ON a.id = i.application_id "
                f"WHERE i.status = 'candidate' AND {app_scope} ORDER BY i.id LIMIT 100", app_params).fetchall():
            add("ai_regulatory_review", r["id"], "review_regulatory_change", f"Review regulatory change: {r['title']} ({r['name']})",
                "/ai-governance/regulatory", "open", unit=r["business_unit_id"])

    # intake requests: for the reviewer, waiting; for the author, sent back
    if has_capability(user, "ai_use.review"):
        where, params = _bu_filter("r.business_unit_id", scope)
        for r in db.execute(
                "SELECT r.id, r.payload, r.business_unit_id FROM ai_use_intake_requests r "
                f"WHERE r.status = 'submitted' AND r.submitted_by != %s AND {where} ORDER BY r.submitted_at LIMIT 100",
                [user["id"], *params]).fetchall():
            add("ai_intake_review", r["id"], "review_ai_request", f"Review AI use request: {_intake_name(r['payload'])}",
                "/ai-governance/review", "open", unit=r["business_unit_id"])
    for r in db.execute(
            "SELECT r.id, r.payload, r.business_unit_id FROM ai_use_intake_requests r "
            "WHERE r.status = 'returned' AND r.submitted_by = %s ORDER BY r.updated_at DESC LIMIT 50", (user["id"],)).fetchall():
        add("ai_intake_returned", r["id"], "update_ai_request", f"Update your AI use request: {_intake_name(r['payload'])}",
            f"/ai-governance/requests/{r['id']}", "open", unit=r["business_unit_id"])
    return items


def _intake_name(payload) -> str:
    try:
        return (json.loads(payload or "{}").get("name") or "An AI use").strip()
    except (TypeError, ValueError):
        return "An AI use"


def _today() -> str:
    from core.timeutils import utcnow
    return utcnow().strftime("%Y-%m-%d")


def _item_key(item: dict) -> tuple:
    return (SECTIONS.index(item["section"]), item["due_date"] or "9999-99-99",
            item["source_module"], str(item["entity_id"]), item["entity_type"])


def _decode_cursor(value: str | None) -> tuple | None:
    if not value:
        return None
    if len(value) > 512:
        raise ValueError("Invalid cursor.")
    try:
        key = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error):
        raise ValueError("Invalid cursor.") from None
    if not isinstance(key, list) or len(key) != 5 or not isinstance(key[0], int) or not all(isinstance(v, str) for v in key[1:]):
        raise ValueError("Invalid cursor.")
    if key[0] not in range(len(SECTIONS)):
        raise ValueError("Invalid cursor.")
    return tuple(key)


def get_my_work(user: dict, *, source: str = "", section: str = "",
                q: str = "", cursor: str | None = None, page_size: int = 50) -> dict:
    """Federate live sources with stable keyset paging and personal filters."""
    if section and section not in SECTIONS:
        raise ValueError("Invalid section.")
    if len(source) > 40 or len(q) > 100 or page_size < 1 or page_size > 100:
        raise ValueError("Invalid filter.")
    after = _decode_cursor(cursor)
    db = get_db()
    scope = bu_scope_ids(user)
    sources = [
        ("aria_approvals", "aria", lambda: _aria_approvals(db, user)),
        ("evidence_expiry", None, lambda: _evidence_expiring(db, user)),
        ("task_board", None, lambda: _my_tasks(db, user)),
        ("notifications", None, lambda: _unread_notifications(db, user)),
        ("workflow_actions", None, lambda: _workflow_actions(db, user)),
        ("grid_non_conformances", "grid", lambda: _grid_ncs(db, user, scope)),
        ("erm_reviews", "erm", lambda: _erm_reviews(db, user, scope)),
        ("orm_reviews", "orm", lambda: _orm_reviews(db, user, scope)),
        ("bcm_incidents", "bcm", lambda: _bcm_incidents(db, user, scope)),
        ("privacy_deadlines", "sentinel", lambda: _privacy_deadlines(db, user, scope)),
        ("ai_governance", None, lambda: _ai_governance_work(db, user, scope)),
    ]
    all_items = []
    source_states = []
    try:
        for name, module, load in sources:
            if module and not _module_ok(user, module):
                source_states.append({"source": name, "state": "disabled"})
                continue
            if name == "bcm_incidents" and not has_capability(user, "bcm.incident.update"):
                continue
            if name == "privacy_deadlines" and not has_capability(user, "sentinel.dsr.manage"):
                continue
            try:
                items = load()
                all_items.extend(items)
                limited = (name in ("bcm_incidents", "privacy_deadlines")
                           and not settings.is_postgres())
                source_states.append({"source": name, "state": "scope_limited" if limited else "available",
                                      "count": len(items),
                                      "truncated": len(items) >= (50 if name == "notifications" else 100)})
            except Exception:
                db.rollback()
                log.exception("My Work source failed: %s", name)
                source_states.append({"source": name, "state": "degraded"})
    finally:
        db.close()
    sections = {name: [] for name in SECTIONS}
    for item in all_items:
        if item["due_date"] is not None:
            item["due_date"] = str(item["due_date"])
    visible = [item for item in all_items
               if (not source or item["source_module"] == source)
               and (not section or item["section"] == section)
               and (not q or q.casefold() in item["title"].casefold())]
    counts = {name: sum(item["section"] == name for item in visible) for name in SECTIONS}
    visible.sort(key=_item_key)
    if after is not None:
        visible = [item for item in visible if _item_key(item) > after]
    page = visible[:page_size]
    for item in page:
        sections[item["section"]].append(item)
    next_cursor = None
    if len(visible) > page_size:
        raw = json.dumps(_item_key(page[-1]), separators=(",", ":")).encode("utf-8")
        next_cursor = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return {"sections": sections, "source_states": source_states, "pending_sources": [],
            "counts": counts, "next_cursor": next_cursor, "total_count": sum(counts.values())}
