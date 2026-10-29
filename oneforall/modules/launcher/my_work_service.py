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

register_view_schema("platform", "my_work", allowed_params={"source", "section", "q", "group"})

SECTIONS = ("needs_my_action", "waiting_on_others", "due_soon", "overdue", "recently_changed", "recently_completed")
# How the list can be grouped (plans/2026-10-governance-rework/04 section 3). Grouping is presentation only: it never
# changes which items are returned or how they page.
GROUPS = ("", "source", "business_unit", "parent", "vendor", "process")


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


def _group_proof_requests(db, user: dict) -> list[dict]:
    """Surface the same scoped request rows as the group work page."""
    from modules.evidence.group_requests import list_requests

    if not any(has_capability(user, cap) for cap in (
        "group.request.create", "group.request.manage", "group.request.review", "group.request.fulfill"
    )):
        return []
    items = []
    for page in (1, 2):
        batch = list_requests(db, user, page=page)
        for row in batch["items"]:
            if row["is_source"]:
                if row["status"] == "requested" and row["can_map"]:
                    action, bucket = "review_group_request", "open"
                elif row["status"] == "approved" and row["can_fulfill"]:
                    action, bucket = "fulfill_group_request", "open"
                elif row["can_refulfill"]:
                    action, bucket = "replace_group_proof", "open"
                else:
                    continue
            elif row["can_revise"]:
                action, bucket = "clarify_group_request", "open"
            elif row["can_review_verdict"]:
                action, bucket = "decide_group_proof", "open"
            elif row["status"] in ("requested", "approved", "fulfilled"):
                action, bucket = "await_group_proof", "waiting"
            else:
                continue
            items.append({
                "source_module": "evidence", "entity_type": "group_proof_request",
                "entity_id": row["id"], "action": action,
                "title": f"Group proof: {row['requirement_ref']}",
                "due_date": row["needed_by"], "priority": "high",
                "org_id": user["org_id"], "business_unit_id": None,
                "link": "/evidence/group/requests/",
                "section": _section_for(bucket, row["needed_by"]) if bucket == "open" else "waiting_on_others",
            })
        if not batch["has_more"]:
            break
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
    # A retired literacy notice has no live page to open; keep it in history, not in My Work.
    rows = db.execute(
        "SELECT id, module, title, message, link, created_at FROM notifications "
        "WHERE user_id = %s AND is_read = 0 "
        "AND (link IS NULL OR link NOT LIKE '/ai-governance/literacy%') "
        "ORDER BY created_at DESC LIMIT 50",
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
            "section": "recently_changed",
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
        "a.business_unit_id,a.name AS audit_name FROM grid_non_conformances nc "
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
        "context": {"kind": "audit", "id": r["audit_id"], "title": r["audit_name"]},
        "group_source": ("grid", "nc", r["id"]),
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
        "group_source": ("erm", "risk", r["id"]),
    } for r in rows]


def _erm_scenarios(db, user, scope):
    """Scenarios the person owns that are not archived, due on their review date."""
    where, params = _bu_filter("business_unit_id", scope)
    rows = db.execute(
        "SELECT id,title,review_date,status,business_unit_id FROM erm_scenarios "
        f"WHERE owner_id=%s AND status<>'archived' AND {where} ORDER BY review_date,id LIMIT 100",
        [user["id"]] + params,
    ).fetchall()
    return [{
        "source_module": "erm", "entity_type": "scenario_review", "entity_id": r["id"],
        "action": "review_scenario", "title": f"Scenario review: {r['title']}",
        "due_date": r["review_date"], "priority": "medium",
        "org_id": user.get("org_id"), "business_unit_id": r["business_unit_id"],
        "link": f"/erm/scenario-studio?open={r['id']}", "section": _section_for("open", r["review_date"]),
        "group_source": ("erm", "scenario", r["id"]),
    } for r in rows]


def _erm_acceptance_actions(db, user, scope):
    """Project pending decisions and due reviews from ERM's own decision record."""
    if not (has_capability(user, "erm.acceptance.decide") or
            has_capability(user, "erm.acceptance.propose")):
        return []
    from core.timeutils import utcnow
    from modules.erm.acceptance import _snapshot
    where, params = _bu_filter("r.business_unit_id", scope)
    rows = db.execute(
        "SELECT a.id AS acceptance_id, a.risk_id, a.status AS acceptance_status, "
        "a.proposed_by, a.review_on, a.expires_on, "
        "a.source_hash, r.* FROM erm_risk_acceptances a "
        "JOIN erm_enterprise_risks r ON r.id=a.risk_id "
        f"WHERE a.org_id=%s AND a.status IN ('submitted','approved') AND {where} "
        "ORDER BY a.id DESC LIMIT 100",
        [user.get("org_id"), *params],
    ).fetchall()
    today = utcnow().strftime("%Y-%m-%d")
    items = []
    for row in rows:
        r = dict(row)
        if r["acceptance_status"] == "submitted":
            if not has_capability(user, "erm.acceptance.decide") or r["proposed_by"] == user["id"]:
                continue
            label, due, action = "Decide risk acceptance", None, "decide_risk_acceptance"
        else:
            if r["owner_id"] != user["id"]:
                continue
            _, fingerprint = _snapshot(db, r)
            changed = fingerprint != r["source_hash"]
            if not changed and str(r["review_on"])[:10] > today and str(r["expires_on"])[:10] > today:
                continue
            label = "Reassess changed acceptance" if changed else "Review expiring acceptance"
            due, action = today if changed else r["review_on"], "review_risk_acceptance"
        items.append({
            "source_module": "erm", "entity_type": "risk_acceptance", "entity_id": r["acceptance_id"],
            "action": action, "title": f"{label}: {r['title']}",
            "due_date": due, "priority": "high", "org_id": user.get("org_id"),
            "business_unit_id": r["business_unit_id"],
            "link": f"/erm/?open=risk:{r['risk_id']}", "section": _section_for("open", due),
            "group_source": ("erm", "risk", r["risk_id"]),
        })
    return items


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
        "group_source": ("orm", "event", r["id"]),
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
        "group_source": ("bcm", "incident", r["id"]),
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
        "group_source": ("sentinel", "dsr", r["id"]),
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
            "group_source": ("sentinel", "breach", r["id"]),
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

    def add(entity_type, entity_id, action, title, link, bucket, due=None, unit=None, priority="medium", use=None,
            assigned=False):
        items.append({
            "source_module": "ai_governance", "entity_type": entity_type, "entity_id": entity_id, "action": action,
            "title": title, "due_date": due, "priority": priority, "org_id": org, "business_unit_id": unit,
            "link": link, "section": _section_for(bucket, due), "assigned": assigned,
            "context": {"kind": "ai_use", "id": use[0], "title": use[1]} if use else None})

    if not has_capability(user, "ai_use.view"):
        # Former authors may open only their own requests. They cannot open a
        # system, decision or condition through the specialist workspace.
        if has_capability(user, "ai_use.submit"):
            for row in db.execute(
                    "SELECT id, payload, business_unit_id FROM ai_use_intake_requests "
                    "WHERE status = 'returned' AND submitted_by = %s ORDER BY updated_at DESC LIMIT 50",
                    (user["id"],)).fetchall():
                add("ai_intake_returned", row["id"], "view",
                    f"View your AI use request: {_intake_name(row['payload'])}",
                    f"/ai-governance/requests/{row['id']}", "open", unit=row["business_unit_id"])
        return items

    # decisions waiting
    can_decide = has_capability(user, "ai_use.decide")
    separation = ai_rollout.separation_required(org)
    for r in db.execute(
            "SELECT d.id, d.application_id, d.requested_by, d.business_unit_id, d.assigned_decider_id, a.name, "
            "a.owner_user_id FROM ai_use_decisions d JOIN applications a ON a.id = d.application_id "
            f"WHERE d.status = 'proposed' AND {app_scope} ORDER BY d.id LIMIT 100", app_params).fetchall():
        mine = r["requested_by"] == user["id"] or r["owner_user_id"] == user["id"]
        link = f"/ai-governance/systems/{r['application_id']}#decisions"
        named = r["assigned_decider_id"]
        if can_decide and not (separation and mine) and named not in (None, user["id"]):
            # someone else was named: this is their turn, and the others are not asked to act on it
            add("ai_decision", r["id"], "view", f"Assigned to another decider: {r['name']}", link, "waiting",
                unit=r["business_unit_id"], use=(r["application_id"], r["name"]))
        elif can_decide and not (separation and mine):
            add("ai_decision", r["id"], "decide_ai_use", f"Decide: {r['name']}", link, "open", unit=r["business_unit_id"],
                priority="high", use=(r["application_id"], r["name"]), assigned=named == user["id"])
        elif mine:
            add("ai_decision_waiting", r["id"], "view", f"Waiting for a decision: {r['name']}", link, "waiting",
                unit=r["business_unit_id"], use=(r["application_id"], r["name"]))

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
                f"/ai-governance/systems/{r['application_id']}#decisions", "open", unit=r["business_unit_id"],
                use=(r["application_id"], r["name"]))

    # conditions that fall due: the owner's and the asker's
    for r in db.execute(
            "SELECT c.id, c.text, c.due_date, d.application_id, d.requested_by, d.business_unit_id, a.name, a.owner_user_id "
            "FROM ai_use_decision_conditions c JOIN ai_use_decisions d ON d.id = c.decision_id "
            "JOIN applications a ON a.id = d.application_id "
            "WHERE c.status = 'open' AND c.due_date IS NOT NULL AND d.revoked_at IS NULL "
            f"AND (a.owner_user_id = %s OR d.requested_by = %s) AND {app_scope} ORDER BY c.due_date LIMIT 100",
            [user["id"], user["id"], *app_params]).fetchall():
        add("ai_condition", r["id"], "meet_condition", f"Condition due: {r['text']} ({r['name']})",
            f"/ai-governance/systems/{r['application_id']}#decisions", "open", due=r["due_date"], unit=r["business_unit_id"],
            use=(r["application_id"], r["name"]))

    # Live oversight actions are read from current versions only. A draft is
    # offered to another decider only when complete and bound to the current profile.
    if has_capability(user, "ai_use.view") and (has_capability(user, "ai_use.review") or can_decide):
        for r in db.execute(
                "SELECT h.application_id, h.track, v.version, v.profile_version, v.status, v.authored_by, "
                "v.responsible_user_id, v.monitoring_method, v.intervention_method, v.stop_procedure, "
                "v.escalation_path, person.is_active AS person_active, person.deleted_at AS person_deleted, "
                "p.version AS current_profile_version, a.name, a.owner_user_id, "
                "a.business_unit_id FROM ai_oversight_heads h "
                "JOIN ai_oversight_versions v ON v.application_id = h.application_id "
                "AND v.track = h.track AND v.version = h.content_version "
                "JOIN ai_use_profiles p ON p.application_id = h.application_id "
                "JOIN applications a ON a.id = h.application_id "
                "LEFT JOIN users person ON person.id = v.responsible_user_id "
                f"WHERE a.is_active = 1 AND {app_scope} ORDER BY h.application_id, h.track LIMIT 100",
                app_params).fetchall():
            link = f"/ai-governance/systems/{r['application_id']}#oversight"
            label = "Design" if r["track"] == "design" else "Operation"
            kind = f"ai_oversight_{r['track']}"
            stale = r["profile_version"] != r["current_profile_version"]
            mine = r["authored_by"] == user["id"] or r["owner_user_id"] == user["id"]
            complete = (all(r[field] for field in ("responsible_user_id", "monitoring_method",
                                                    "intervention_method", "stop_procedure", "escalation_path"))
                        and bool(r["person_active"]) and not r["person_deleted"])
            if stale and mine and has_capability(user, "ai_use.review"):
                add(kind, r["application_id"], "update_ai_oversight",
                    f"Update {label.lower()} oversight after profile change: {r['name']}",
                    link, "open", unit=r["business_unit_id"], use=(r["application_id"], r["name"]))
            elif r["status"] == "draft" and not stale:
                if not complete and r["authored_by"] == user["id"] and has_capability(user, "ai_use.review"):
                    add(kind, r["application_id"], "complete_ai_oversight",
                        f"Complete {label.lower()} oversight: {r['name']}",
                        link, "open", unit=r["business_unit_id"], use=(r["application_id"], r["name"]))
                elif complete and can_decide and r["authored_by"] != user["id"]:
                    add(kind, r["application_id"], "review_ai_oversight",
                        f"Review {label.lower()} oversight: {r['name']}",
                        link, "open", unit=r["business_unit_id"], use=(r["application_id"], r["name"]))
                elif complete and r["authored_by"] == user["id"]:
                    add(kind, r["application_id"], "view",
                        f"Waiting for {label.lower()} oversight review: {r['name']}",
                        link, "waiting", unit=r["business_unit_id"], use=(r["application_id"], r["name"]))

    # regulatory changes proposed for a use, for the reviewer
    if has_capability(user, "ai_use.review"):
        for r in db.execute(
                "SELECT i.id, i.application_id, i.business_unit_id, u.title, a.name FROM ai_regulatory_impacts i "
                "JOIN regulatory_updates u ON u.id = i.update_id JOIN applications a ON a.id = i.application_id "
                f"WHERE i.status = 'candidate' AND {app_scope} ORDER BY i.id LIMIT 100", app_params).fetchall():
            add("ai_regulatory_review", r["id"], "review_regulatory_change", f"Review regulatory change: {r['title']} ({r['name']})",
                "/ai-governance/regulatory", "open", unit=r["business_unit_id"], use=(r["application_id"], r["name"]))

    # intake requests: for the reviewer, waiting; for the author, sent back
    if has_capability(user, "ai_use.review"):
        where, params = _bu_filter("r.business_unit_id", scope)
        for r in db.execute(
                "SELECT r.id, r.payload, r.business_unit_id, r.assigned_reviewer_id FROM ai_use_intake_requests r "
                f"WHERE r.status = 'submitted' AND r.submitted_by != %s AND {where} ORDER BY r.submitted_at LIMIT 100",
                [user["id"], *params]).fetchall():
            if r["assigned_reviewer_id"] not in (None, user["id"]):
                add("ai_intake_review", r["id"], "view", f"Assigned to another reviewer: {_intake_name(r['payload'])}",
                    "/ai-governance/review", "waiting", unit=r["business_unit_id"])
                continue
            add("ai_intake_review", r["id"], "review_ai_request", f"Review AI use request: {_intake_name(r['payload'])}",
                "/ai-governance/review", "open", unit=r["business_unit_id"],
                assigned=r["assigned_reviewer_id"] == user["id"])
    for r in db.execute(
            "SELECT r.id, r.payload, r.business_unit_id FROM ai_use_intake_requests r "
            "WHERE r.status = 'returned' AND r.submitted_by = %s ORDER BY r.updated_at DESC LIMIT 50", (user["id"],)).fetchall():
        can_edit = has_capability(user, "ai_use.intake_create")
        add("ai_intake_returned", r["id"], "update_ai_request" if can_edit else "view",
            f"{'Update' if can_edit else 'View'} your AI use request: {_intake_name(r['payload'])}",
            f"/ai-governance/requests/{r['id']}", "open", unit=r["business_unit_id"])
    return items


def _change_reviews(db, user: dict) -> list[dict]:
    """Connected records whose owner is asked to say whether a change elsewhere needs a second look."""
    from modules.governance import change_signals
    items = []
    for entry in change_signals.list_open(db, user, limit=100):
        title = f"Look again at {entry['target']['title']}: {entry['source']['title']} changed"
        items.append({
            "source_module": "governance", "entity_type": "change_review", "entity_id": entry["id"],
            "action": "review_change", "title": title[:200], "due_date": None, "priority": "medium",
            "org_id": user.get("org_id"), "business_unit_id": None,
            "link": f"/governance/changes#target-{entry['id']}", "section": "needs_my_action"})
    return items


def _evidence_reviews(db, user: dict) -> list[dict]:
    """Links between a file and a record that wait for a reviewer other than the person who attached them."""
    from modules.evidence import proof
    return [{
        "source_module": "evidence", "entity_type": "link_review", "entity_id": r["link_id"], "action": "review_evidence",
        "title": f"Review evidence: {r['title']} for {r['claim']}"[:200], "due_date": None, "priority": "medium",
        "org_id": user.get("org_id"), "business_unit_id": None, "link": f"/evidence/?open=item:{r['evidence_id']}",
        "section": "needs_my_action"} for r in proof.pending_reviews(db, user, limit=100)]


def _intake_name(payload) -> str:
    try:
        return (json.loads(payload or "{}").get("name") or "An AI use").strip()
    except (TypeError, ValueError):
        return "An AI use"


def _today() -> str:
    from core.timeutils import utcnow
    return utcnow().strftime("%Y-%m-%d")


_KIND = (("decide", "decide"), ("review", "review"), ("respond", "respond"), ("notify", "respond"),
         ("resolve", "do"), ("update", "do"), ("complete", "do"), ("meet", "do"), ("renew", "renew"),
         ("acknowledge", "acknowledge"), ("request", "decide"))
_STATUTORY = ("notify_authority", "respond_to_dsr")
_CONTEXT_LABELS = {"ai_use": "AI use", "audit": "Audit"}
_WORK_GROUP_TABLES = {
    ("orm", "event"): "orm_events", ("erm", "risk"): "erm_enterprise_risks",
    ("grid", "nc"): "grid_non_conformances", ("bcm", "incident"): "bcm_incidents",
    ("sentinel", "dsr"): "sentinel_dsr", ("sentinel", "breach"): "sentinel_breaches",
}


def _link_source_type(key: tuple, column: str) -> tuple[str, list]:
    """Accept the older GRID non_conformance spelling on saved links."""
    if key == ("grid", "nc"):
        return f"{column} IN (%s,%s)", ["nc", "non_conformance"]
    return f"{column}=%s", [key[1]]


def _linked_group_contexts(db, user: dict, items: list, group: str) -> None:
    """Add vendor or process display groups to already authorized work.

    Only confirmed source relationships qualify. Both endpoints are scoped again
    at query time; a hidden process never contributes a title, ID, or count.
    """
    app_ids = sorted({item["context"]["id"] for item in items
                      if item.get("context") and item["context"].get("kind") == "ai_use"})
    from modules.governance.entity_scope import entity_scope_sql, may_view_kind

    found: dict[tuple, list[dict]] = {}
    if group == "vendor":
        if app_ids:
            app_scope, app_params = entity_scope_sql(("governance", "application"), user, "a")
            marks = ",".join(["%s"] * len(app_ids))
            rows = db.execute(
                "SELECT a.id AS app_id, cv.id AS group_id, cv.name AS group_name "
                "FROM applications a JOIN canonical_vendors cv ON cv.id=a.vendor_id "
                f"WHERE a.id IN ({marks}) AND {app_scope}",
                [*app_ids, *app_params],
            ).fetchall()
            for row in rows:
                found[("governance", "application", row["app_id"])] = [
                    {"kind": "vendor", "id": row["group_id"], "title": row["group_name"]}]
        vendor_tables = {("grid", "vendor"): "grid_vendors", ("bcm", "vendor"): "bcm_vendors",
                         ("sentinel", "vendor"): "sentinel_vendors"}
        for source_key, source_table in _WORK_GROUP_TABLES.items():
            source_ids = sorted({item["group_source"][2] for item in items
                                 if item.get("group_source") and item["group_source"][:2] == source_key})
            if not source_ids:
                continue
            source_scope, source_params = entity_scope_sql(source_key, user, "a")
            marks = ",".join(["%s"] * len(source_ids))
            for vendor_key, vendor_table in vendor_tables.items():
                if not may_view_kind(user, vendor_key):
                    continue
                vendor_scope, vendor_params = entity_scope_sql(vendor_key, user, "v")
                for source_col, vendor_col in (("source", "target"), ("target", "source")):
                    source_type_sql, source_type_params = _link_source_type(source_key, f"l.{source_col}_type")
                    rows = db.execute(
                        "SELECT a.id AS record_id, v.id AS vendor_id, v.name AS vendor_name, "
                        "cv.id AS canonical_id, cv.name AS canonical_name FROM cross_module_links l "
                        f"JOIN {source_table} a ON a.id=l.{source_col}_id "
                        f"JOIN {vendor_table} v ON v.id=l.{vendor_col}_id "
                        "LEFT JOIN canonical_vendors cv ON cv.id=v.canonical_id "
                        f"WHERE l.{source_col}_module=%s AND {source_type_sql} "
                        f"AND l.{vendor_col}_module=%s AND l.{vendor_col}_type=%s "
                        "AND COALESCE(l.status,'confirmed')='confirmed' "
                        f"AND a.id IN ({marks}) AND {source_scope} AND {vendor_scope}",
                        [source_key[0], *source_type_params, *vendor_key, *source_ids,
                         *source_params, *vendor_params],
                    ).fetchall()
                    for row in rows:
                        canonical_id = row["canonical_id"]
                        context = {"kind": "vendor",
                                   "id": canonical_id if canonical_id else f"{vendor_key[0]}:{row['vendor_id']}",
                                   "title": row["canonical_name"] if canonical_id else
                                   f"{vendor_key[0].upper()}: {row['vendor_name']}"}
                        contexts = found.setdefault((*source_key, row["record_id"]), [])
                        if not any(existing["id"] == context["id"] for existing in contexts):
                            contexts.append(context)
        for contexts in found.values():
            contexts.sort(key=lambda context: str(context["id"]))
    else:
        process_scope, process_params = entity_scope_sql(("governance", "process"), user, "bp")
        sources = {("governance", "application"): ("applications", set(app_ids))}
        sources.update({key: (table, set()) for key, table in _WORK_GROUP_TABLES.items()})
        for item in items:
            source = item.get("group_source")
            if source and source[:2] in sources:
                sources[source[:2]][1].add(source[2])
        for key, (table, ids) in sources.items():
            if not ids:
                continue
            source_scope, source_params = entity_scope_sql(key, user, "a")
            marks = ",".join(["%s"] * len(ids))
            for source_col, process_col in (("source", "target"), ("target", "source")):
                source_type_sql, source_type_params = _link_source_type(key, f"l.{source_col}_type")
                rows = db.execute(
                    "SELECT a.id AS record_id, bp.id AS group_id, bp.name AS group_name "
                    "FROM cross_module_links l "
                    f"JOIN {table} a ON a.id=l.{source_col}_id "
                    f"JOIN business_processes bp ON bp.id=l.{process_col}_id "
                    f"WHERE l.{source_col}_module=%s AND {source_type_sql} "
                    f"AND l.{process_col}_module='governance' AND l.{process_col}_type='process' "
                    "AND l.relationship IN ('related','supports','depends_on') "
                    "AND COALESCE(l.status,'confirmed')='confirmed' "
                    f"AND a.id IN ({marks}) AND {source_scope} AND {process_scope}",
                    [key[0], *source_type_params, *sorted(ids), *source_params, *process_params],
                ).fetchall()
                for row in rows:
                    context = {"kind": "process", "id": row["group_id"], "title": row["group_name"]}
                    contexts = found.setdefault((*key, row["record_id"]), [])
                    if not any(existing["id"] == context["id"] for existing in contexts):
                        contexts.append(context)
        for contexts in found.values():
            contexts.sort(key=lambda context: context["id"])
    for item in items:
        context = item.get("context")
        if context and context.get("kind") == "ai_use":
            item["group_contexts"] = found.get(("governance", "application", context["id"]), [])
        elif item.get("group_source"):
            item["group_contexts"] = found.get(tuple(item["group_source"]), [])


def _action_kind(action: str) -> str:
    """One of decide, review, respond, do, renew, acknowledge or wait: what the person is being asked to do."""
    for prefix, kind in _KIND:
        if action.startswith(prefix):
            return kind
    return "wait" if action == "view" else "do"


def _enrich(item: dict) -> dict:
    """Every item carries who acts, what kind of action it is, the state of its source and why it is ranked as it is, so
    that the list can be filtered and grouped without reading the title."""
    section = item["section"]
    bucket = "done" if section == "recently_completed" else "waiting" if section == "waiting_on_others" else "open"
    if item["action"] in _STATUTORY:
        basis = "A statutory deadline"
    elif item["due_date"]:
        basis = f"Due {str(item['due_date'])[:10]}"
    else:
        basis = f"Priority: {item['priority']}"
    item.update(action_kind=_action_kind(item["action"]), source_state=bucket,
                responsible="others" if bucket == "waiting" else "you", priority_basis=basis,
                context=item.get("context"))
    return item


def _dedupe(items: list) -> list:
    """The same obligation is shown once. An unread notification that points at the page of an item already listed adds
    nothing to it, and the item says it was also notified. Two items with different owners stay two items."""
    seen, out = set(), []
    for item in items:
        key = (item["source_module"], item["entity_type"], str(item["entity_id"]), item["action"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    by_link = {i["link"]: i for i in out if i["entity_type"] != "notification" and i["link"] != "/"}
    kept = []
    for item in out:
        twin = by_link.get(item["link"]) if item["entity_type"] == "notification" else None
        if twin is not None:
            twin["also_notified"] = twin.get("also_notified", 0) + 1
            continue
        kept.append(item)
    return kept


_SOURCE_LABELS = {"aria": "ARIA", "grid": "GRID", "bcm": "BCM", "sentinel": "Sentinel", "erm": "ERM", "orm": "ORM",
                  "evidence": "Evidence", "platform": "Platform", "ai_governance": "AI Governance",
                  "governance": "Governance"}


def _group_of(item: dict, how: str, unit_names: dict) -> tuple:
    """(key, label) of the group an item belongs to."""
    if how == "source":
        return item["source_module"], _SOURCE_LABELS.get(item["source_module"], item["source_module"])
    if how == "business_unit":
        unit = item.get("business_unit_id")
        return str(unit or 0), unit_names.get(unit) or "Whole organization"
    if how in ("vendor", "process"):
        contexts = item.get("group_contexts") or []
        if contexts:
            first = contexts[0]
            return f"{first['kind']}:{first['id']}", f"{first['kind'].title()}: {first['title']}"
        if item.get("group_source"):
            return "unlinked_record", f"Source records with no visible linked {how}"
        if (item.get("context") or {}).get("kind") == "ai_use":
            return "unlinked_ai_use", f"AI uses with no visible linked {how}"
        return "other_work", "Other work (source grouping pending)"
    ctx = item.get("context")
    if ctx:
        return f"{ctx['kind']}:{ctx['id']}", f"{_CONTEXT_LABELS.get(ctx['kind'], ctx['kind'])}: {ctx['title']}"
    return "none", "No parent record"


def _groups_of(item: dict, how: str, unit_names: dict) -> list[tuple]:
    """An action linked to several vendors or processes belongs to each group."""
    if how in ("vendor", "process") and item.get("group_contexts"):
        return [(f"{ctx['kind']}:{ctx['id']}", f"{ctx['kind'].title()}: {ctx['title']}")
                for ctx in item["group_contexts"]]
    return [_group_of(item, how, unit_names)]


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


def _collect(db, user: dict, scope, only=None) -> tuple:
    """(items, source_states): everything the sources hold for this person, read through the unit scope given.
    `only` names the sources to read (all of them when None)."""
    sources = [
        ("aria_approvals", "aria", lambda: _aria_approvals(db, user)),
        ("evidence_expiry", None, lambda: _evidence_expiring(db, user)),
        ("group_proof_requests", None, lambda: _group_proof_requests(db, user)),
        ("task_board", None, lambda: _my_tasks(db, user)),
        ("notifications", None, lambda: _unread_notifications(db, user)),
        ("workflow_actions", None, lambda: _workflow_actions(db, user)),
        ("grid_non_conformances", "grid", lambda: _grid_ncs(db, user, scope)),
        ("erm_reviews", "erm", lambda: _erm_reviews(db, user, scope)),
        ("erm_acceptances", "erm", lambda: _erm_acceptance_actions(db, user, scope)),
        ("erm_scenarios", "erm", lambda: _erm_scenarios(db, user, scope)),
        ("orm_reviews", "orm", lambda: _orm_reviews(db, user, scope)),
        ("bcm_incidents", "bcm", lambda: _bcm_incidents(db, user, scope)),
        ("privacy_deadlines", "sentinel", lambda: _privacy_deadlines(db, user, scope)),
        ("ai_governance", None, lambda: _ai_governance_work(db, user, scope)),
        ("change_reviews", None, lambda: _change_reviews(db, user)),
        ("evidence_reviews", None, lambda: _evidence_reviews(db, user)),
    ]
    all_items = []
    source_states = []
    for name, module, load in sources:
        if only is not None and name not in only:
            continue
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
    return all_items, source_states


def get_my_work(user: dict, *, source: str = "", section: str = "",
                q: str = "", cursor: str | None = None, page_size: int = 50, group: str = "",
                only_sources: frozenset[str] | None = None) -> dict:
    """Federate live sources with stable keyset paging and personal filters."""
    if section and section not in SECTIONS:
        raise ValueError("Invalid section.")
    if group not in GROUPS:
        raise ValueError("Invalid grouping.")
    if len(source) > 40 or len(q) > 100 or page_size < 1 or page_size > 100:
        raise ValueError("Invalid filter.")
    after = _decode_cursor(cursor)
    db = get_db()
    scope = bu_scope_ids(user)
    unit_names = {}
    try:
        all_items, source_states = _collect(db, user, scope, only=only_sources)
        if group in ("vendor", "process"):
            try:
                group_items = [item for item in all_items
                               if (not source or item["source_module"] == source)
                               and (not section or item["section"] == section)
                               and (not q or q.casefold() in item["title"].casefold())]
                _linked_group_contexts(db, user, group_items, group)
            except Exception:
                db.rollback()
                log.exception("My Work linked %s groups could not be read", group)
                source_states.append({"source": f"{group}_grouping", "state": "degraded"})
        if group == "business_unit":
            try:
                unit_names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM business_units").fetchall()}
            except Exception:
                db.rollback()
                log.exception("My Work business unit names could not be read")
    finally:
        db.close()
    all_items = [_enrich(item) for item in _dedupe(all_items)]
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
    groups = []
    if group:
        index = {}
        for item in visible:
            for key, label in _groups_of(item, group, unit_names):
                index.setdefault(key, {"key": key, "label": label, "count": 0})["count"] += 1
        for item in page:
            keys = [key for key, _ in _groups_of(item, group, unit_names)]
            item["group_key"] = keys[0]
            item["group_keys"] = keys
        groups = sorted(index.values(), key=lambda g: (-g["count"], g["label"]))
    for item in page:
        sections[item["section"]].append(item)
    next_cursor = None
    if len(visible) > page_size:
        raw = json.dumps(_item_key(page[-1]), separators=(",", ":")).encode("utf-8")
        next_cursor = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return {"sections": sections, "source_states": source_states, "pending_sources": [],
            "counts": counts, "next_cursor": next_cursor, "total_count": sum(counts.values()),
            "group": group, "groups": groups}


# ── The team view ───────────────────────────────────────────────────────────

TEAM_LIMIT = 25   # people read for one request; the count says how many there are
TEAM_TOP = 5      # overdue items named for each person
# What is assigned to a person, as against a queue that anyone with the capability sees (evidence expiring, open
# incidents, statutory deadlines, evidence waiting for any reviewer). Only assigned work is counted against a person,
# so the same shared item is not charged to everyone on the team.
_ASSIGNED_SOURCES = ("aria_approvals", "task_board", "workflow_actions", "grid_non_conformances", "erm_reviews",
                     "orm_reviews", "change_reviews", "ai_governance")
_ASSIGNED_AI = ("ai_condition", "ai_intake_returned", "ai_decision_waiting")
_TEAM_SECTIONS = ("overdue", "due_soon", "needs_my_action", "waiting_on_others")
_LICENSED_MODULES = ("aria", "grid", "bcm", "sentinel", "erm", "orm")


def _may_name(viewer: dict, module: str) -> bool:
    """True when the viewer could open records of this source, so that a title from it may be shown to them."""
    if module in _LICENSED_MODULES:
        return _module_ok(viewer, module)
    if module == "ai_governance":
        return has_capability(viewer, "ai_use.view")
    return module == "platform"   # a source this function does not know is not named


def team_units(db, user: dict, scope) -> list:
    """Ids of the active units the person heads that lie inside their own scope, and of every active unit below them.
    Heading a unit does not widen what a person may see: a unit outside their own scope is not part of the team."""
    rows = db.execute("SELECT id, parent_id, head_user_id FROM business_units WHERE is_active = 1").fetchall()
    children: dict = {}
    for r in rows:
        if r["parent_id"]:
            children.setdefault(int(r["parent_id"]), []).append(int(r["id"]))
    queue = [int(r["id"]) for r in rows
             if r["head_user_id"] == user["id"] and (scope is None or int(r["id"]) in scope)]
    found: list = []
    while queue:
        current = queue.pop()
        if current in found:
            continue
        found.append(current)
        queue.extend(children.get(current, []))
    return sorted(found)


def get_team_work(user: dict, unit_id: "int | None" = None) -> dict:
    """The work assigned to each person in the units the viewer heads: four counts and the oldest overdue items.

    Every item is read the way the person's own My Work reads it, then kept only when it lies in the viewer's own unit
    scope, so the view never shows more than the viewer could see. A title from a module the viewer may not open is
    counted and not named. Notifications and shared queues are not counted against anyone."""
    from core.email_outbox import user_for_scope
    db = get_db()
    try:
        scope = bu_scope_ids(user)
        units = team_units(db, user, scope)
        if not units:
            return {"is_manager": False, "units": [], "members": [], "total_members": 0, "truncated": False}
        names = {r["id"]: r["name"] for r in db.execute(
            f"SELECT id, name FROM business_units WHERE id IN ({','.join(['%s'] * len(units))})", units).fetchall()}
        chosen = units
        if unit_id is not None:
            if unit_id not in units:
                raise ValueError("That unit is not one of yours.")
            chosen = [unit_id]
        where, params = ["business_unit_id IN (" + ",".join(["%s"] * len(chosen)) + ")", "is_active = 1",
                         "deleted_at IS NULL", "id != %s"], [*chosen, user["id"]]
        if user.get("org_id") is not None:
            where.append("org_id = %s")
            params.append(user["org_id"])
        people = db.execute(
            "SELECT id, username, email, full_name, org_id, is_super_admin, business_unit_id FROM users "
            f"WHERE {' AND '.join(where)} ORDER BY full_name, id", params).fetchall()
        members = []
        for row in people[:TEAM_LIMIT]:
            person = user_for_scope(db, row)
            items, states = _collect(db, person, bu_scope_ids(person), only=_ASSIGNED_SOURCES)
            mine = [_enrich(i) for i in _dedupe(items)
                    if i["source_module"] != "ai_governance" or i.get("assigned") or i["entity_type"] in _ASSIGNED_AI]
            # inside the viewer's own scope only
            mine = [i for i in mine if scope is None or i["business_unit_id"] is None or i["business_unit_id"] in scope]
            counts = {name: sum(i["section"] == name for i in mine) for name in _TEAM_SECTIONS}
            overdue = sorted((i for i in mine if i["section"] == "overdue"), key=lambda i: str(i["due_date"] or ""))
            named = [i for i in overdue if _may_name(user, i["source_module"])]
            members.append({
                "id": row["id"], "name": row["full_name"] or row["username"],
                "unit": names.get(row["business_unit_id"]) or "", "counts": counts,
                "overdue": [{"title": i["title"][:200], "due_date": str(i["due_date"] or "")[:10],
                             "source": _SOURCE_LABELS.get(i["source_module"], i["source_module"]),
                             "link": i["link"] if str(i["link"]).startswith("/") and not str(i["link"]).startswith("//") else "/"}
                            for i in named[:TEAM_TOP]],
                "overdue_not_listed": len(overdue) - min(len(named), TEAM_TOP),
                "overdue_not_named": len(overdue) - len(named),
                "incomplete": any(st["state"] == "degraded" for st in states)})
        members.sort(key=lambda m: (-m["counts"]["overdue"], -m["counts"]["due_soon"], m["name"].casefold()))
        totals = {name: sum(m["counts"][name] for m in members) for name in _TEAM_SECTIONS}
        return {"is_manager": True, "units": [{"id": i, "name": names.get(i, "")} for i in units],
                "unit_id": unit_id, "members": members, "totals": totals,
                "total_members": len(people), "truncated": len(people) > TEAM_LIMIT}
    finally:
        db.close()
