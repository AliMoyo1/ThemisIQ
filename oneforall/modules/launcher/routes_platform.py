"""
Launcher sub-router: Platform utilities -- Calendar, Analytics, Bulk import/export,
Task board, Trainer, Reminders, Notifications, Global search.
"""
import json as json_lib
import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from database import sql_date_offset
from core.security import sanitize_text, sanitize_short, validate_int, validate_choice, validate_date
from core.sql_like import ci_like, like_pattern

from modules.launcher._route_helpers import (
    _JSONResp, require_auth, has_capability, log_audit,
    require_capability as _require_cap,
    shell_ctx, shell_templates, settings, get_db,
    _json_body,)
from modules.evidence.scope import current_library_sql, evidence_search_sql
from modules.governance.data_service import bu_scope_ids
from core.links import RELATIONSHIP_LABELS
from modules.governance import relationships
from modules.governance.entity_scope import entity_scope_sql
from modules.launcher import search_service
from modules.launcher.task_service import (
    create_task_with_assignment_notification, tell_new_assignee, validate_task_assignee)

router = APIRouter()
log = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/notifications")
@require_auth
async def api_notifications_list(request: Request):
    """Get notifications for current user."""
    uid = request.state.user["id"]
    db = get_db()
    try:
        # Historical literacy notices stay stored, but their destination has been removed.
        rows = db.execute(
            "SELECT * FROM notifications WHERE user_id = %s "
            "AND (link IS NULL OR link NOT LIKE '/ai-governance/literacy%') "
            "ORDER BY created_at DESC LIMIT 50",
            (uid,)
        ).fetchall()
        unread = db.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = 0 "
            "AND (link IS NULL OR link NOT LIKE '/ai-governance/literacy%')",
            (uid,)
        ).fetchone()[0]
    finally:
        db.close()
    return _JSONResp({"notifications": [dict(r) for r in rows], "unread_count": unread})


@router.post("/api/notifications/{nid}/read")
@require_auth
async def api_notification_mark_read(request: Request, nid: int):
    """Mark a notification as read."""
    uid = request.state.user["id"]
    db = get_db()
    try:
        db.execute("UPDATE notifications SET is_read = 1 WHERE id = %s AND user_id = %s", (nid, uid))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.post("/api/notifications/read-all")
@require_auth
async def api_notifications_mark_all_read(request: Request):
    """Mark all notifications as read for current user."""
    uid = request.state.user["id"]
    db = get_db()
    try:
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = %s AND is_read = 0", (uid,))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/notifications/{nid}")
@require_auth
async def api_notification_dismiss(request: Request, nid: int):
    """Dismiss (delete) a notification."""
    uid = request.state.user["id"]
    db = get_db()
    try:
        db.execute("DELETE FROM notifications WHERE id = %s AND user_id = %s", (nid, uid))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


# ═════════════════════════════════════════════════════════════════════════════
# GLOBAL SEARCH
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/search")
@require_auth
async def api_global_search(request: Request):
    """Search across all modules, showing only what the caller could open in each module.

    `case=module:type:id` searches only the records connected to that record."""
    q = sanitize_short(request.query_params.get("q", ""), 200)
    case = request.query_params.get("case", "")
    if not q or len(q) < 2:
        return _JSONResp({"results": []})

    user = request.state.user
    db = get_db()
    results = []
    like_term = like_pattern(q)

    if case:
        try:
            found = search_service.case_results(db, user, case, q)
            if found is None:
                return _JSONResp({"error": "Not found", "results": []}, status_code=404)
            search_service.enrich(db, user, found, q)
        finally:
            db.close()
        return _JSONResp({"results": found[:30], "total": len(found), "case": case})

    def scope(key, alias=""):
        """(" AND <scope>", params) for one kind; a kind the caller may not open matches nothing."""
        sql, params = entity_scope_sql(key, user, alias)
        return f" AND {sql}", list(params)

    try:
        # Unified controls
        sc, sp = scope(("aria", "control"))
        for r in db.execute(
            "SELECT c.id, c.ref, c.name, f.name as framework_name "
            "FROM controls c JOIN frameworks f ON c.framework_id = f.id "
            f"WHERE ({ci_like('c.name')} OR {ci_like('c.ref')}){sc} LIMIT 10",
            (like_term, like_term, *sp)
        ).fetchall():
            results.append({"module": "aria", "type": "control", "id": r["id"],
                            "title": r["ref"] + " - " + r["name"],
                            "subtitle": r["framework_name"], "link": f"/aria/?open=control:{r['id']}"})

        # ARIA documents -- PLAN-35 T08 (section 10.2): scoped the same way as the ARIA
        # module's own document list/detail views (organization and business unit).
        sc, sp = scope(("aria", "document"))
        for r in db.execute(
            f"SELECT id, doc_id, title FROM aria_documents "
            f"WHERE ({ci_like('title')} OR {ci_like('doc_id')}){sc} LIMIT 10",
            (like_term, like_term, *sp)
        ).fetchall():
            results.append({"module": "aria", "type": "document", "id": r["id"],
                            "title": r["title"], "subtitle": r["doc_id"], "link": f"/aria/?open=document:{r['id']}"})

        # Sentinel RoPA
        sc, sp = scope(("sentinel", "ropa"))
        for r in db.execute(
            "SELECT id, ref_number, processing_name FROM sentinel_ropa "
            f"WHERE ({ci_like('processing_name')} OR {ci_like('ref_number')}){sc} LIMIT 10",
            (like_term, like_term, *sp)
        ).fetchall():
            results.append({"module": "sentinel", "type": "ropa", "id": r["id"],
                            "title": r["processing_name"], "subtitle": r["ref_number"] or "", "link": f"/sentinel/?open=ropa:{r['id']}"})

        # GRID audits
        sc, sp = scope(("grid", "audit"))
        for r in db.execute(
            f"SELECT id, name FROM grid_audits WHERE {ci_like('name')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "grid", "type": "audit", "id": r["id"],
                            "title": r["name"], "subtitle": "Audit", "link": f"/grid/?open=audit:{r['id']}"})

        # BCM plans
        sc, sp = scope(("bcm", "plan"))
        for r in db.execute(
            f"SELECT id, title FROM bcm_plans WHERE {ci_like('title')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "bcm", "type": "plan", "id": r["id"],
                            "title": r["title"], "subtitle": "BCM Plan", "link": f"/bcm/?open=plan:{r['id']}"})

        # Risk register
        sc, sp = scope(("platform", "risk"))
        for r in db.execute(
            f"SELECT id, title, source_module FROM risk_register WHERE {ci_like('title')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            _sm = r["source_module"] or ""
            _link = f"/erm/?open=risk:{r['id']}" if _sm != "orm" else f"/orm/?open=event:{r['id']}"
            results.append({"module": "platform", "type": "risk", "id": r["id"],
                            "title": r["title"], "subtitle": r["source_module"] or "Risk", "link": _link})

        # Evidence: same scope and search rules as the Evidence Vault itself
        _ev_scope_sql, _ev_scope_params = entity_scope_sql(("evidence", "item"), user, "e")
        _ev_search_sql, _ev_search_params = evidence_search_sql(q)
        for r in db.execute(
            f"SELECT e.id, e.title, e.category FROM evidence_items e "
            f"WHERE {_ev_search_sql} AND {current_library_sql()} AND {_ev_scope_sql} "
            f"ORDER BY e.updated_at DESC, e.id DESC LIMIT 10",
            [*_ev_search_params, *_ev_scope_params]
        ).fetchall():
            results.append({"module": "platform", "type": "evidence", "id": r["id"],
                            "title": r["title"], "subtitle": r["category"], "link": f"/evidence/?open=item:{r['id']}"})

        # Sentinel breaches
        sc, sp = scope(("sentinel", "breach"))
        for r in db.execute(
            "SELECT id, ref_number, title, severity FROM sentinel_breaches "
            f"WHERE ({ci_like('title')} OR {ci_like('ref_number')}){sc} LIMIT 10",
            (like_term, like_term, *sp)
        ).fetchall():
            results.append({"module": "sentinel", "type": "breach", "id": r["id"],
                            "title": r['title'], "subtitle": f"{r['ref_number']} — {r['severity'] or 'Breach'}",
                            "link": f"/sentinel/?open=breach:{r['id']}"})

        # Sentinel DPIAs
        sc, sp = scope(("sentinel", "dpia"))
        for r in db.execute(
            "SELECT id, ref_number, title FROM sentinel_dpias "
            f"WHERE ({ci_like('title')} OR {ci_like('ref_number')}){sc} LIMIT 10",
            (like_term, like_term, *sp)
        ).fetchall():
            results.append({"module": "sentinel", "type": "dpia", "id": r["id"],
                            "title": r["title"], "subtitle": r["ref_number"] or "DPIA", "link": f"/sentinel/?open=dpia:{r['id']}"})

        # Sentinel DSRs
        sc, sp = scope(("sentinel", "dsr"))
        for r in db.execute(
            "SELECT id, ref_number, requester_name, request_type FROM sentinel_dsr "
            f"WHERE ({ci_like('requester_name')} OR {ci_like('ref_number')}){sc} LIMIT 10",
            (like_term, like_term, *sp)
        ).fetchall():
            results.append({"module": "sentinel", "type": "dsr", "id": r["id"],
                            "title": r["requester_name"] or r["ref_number"],
                            "subtitle": f"{r['ref_number']} — {r['request_type'] or 'DSR'}", "link": f"/sentinel/?open=dsr:{r['id']}"})

        # Sentinel vendors
        sc, sp = scope(("sentinel", "vendor"))
        for r in db.execute(
            f"SELECT id, name, type FROM sentinel_vendors WHERE {ci_like('name')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "sentinel", "type": "vendor", "id": r["id"],
                            "title": r["name"], "subtitle": r["type"] or "Vendor", "link": f"/sentinel/?open=vendor:{r['id']}"})

        # ERM enterprise risks
        sc, sp = scope(("erm", "risk"))
        for r in db.execute(
            f"SELECT id, title, category, status FROM erm_enterprise_risks WHERE {ci_like('title')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "erm", "type": "risk", "id": r["id"],
                            "title": r['title'], "subtitle": f"{r['category'] or 'Risk'} — {r['status'] or ''}",
                            "link": f"/erm/?open=risk:{r['id']}"})

        # ERM regulatory obligations
        sc, sp = scope(("erm", "obligation"))
        for r in db.execute(
            "SELECT id, regulation_name, regulator, obligation FROM erm_regulatory_obligations "
            f"WHERE ({ci_like('regulation_name')} OR {ci_like('obligation')}){sc} LIMIT 10",
            (like_term, like_term, *sp)
        ).fetchall():
            results.append({"module": "erm", "type": "obligation", "id": r["id"],
                            "title": r["regulation_name"], "subtitle": r["regulator"] or "Obligation",
                            "link": f"/erm/?open=obligation:{r['id']}"})

        # ORM events
        sc, sp = scope(("orm", "event"))
        for r in db.execute(
            f"SELECT id, title, event_type, severity FROM orm_events WHERE {ci_like('title')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "orm", "type": "event", "id": r["id"],
                            "title": r['title'], "subtitle": f"{r['event_type'] or 'Event'} — {r['severity'] or ''}",
                            "link": f"/orm/?open=event:{r['id']}"})

        # ORM KRIs
        sc, sp = scope(("orm", "kri"))
        for r in db.execute(
            f"SELECT id, name, description FROM orm_kris WHERE {ci_like('name')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "orm", "type": "kri", "id": r["id"],
                            "title": r["name"], "subtitle": "Key Risk Indicator", "link": f"/orm/?open=kri:{r['id']}"})
        # GRID findings and BCM incidents: both are registered with their own scope rules
        sc, sp = scope(("grid", "nc"))
        for r in db.execute(
            f"SELECT id, title, severity FROM grid_non_conformances WHERE {ci_like('title')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "grid", "type": "nc", "id": r["id"],
                            "title": r["title"], "subtitle": ("Audit finding, " + (r["severity"] or "")).rstrip(" ,"),
                            "link": f"/grid/?open=nc:{r['id']}"})

        sc, sp = scope(("bcm", "incident"))
        for r in db.execute(
            f"SELECT id, title, severity FROM bcm_incidents WHERE {ci_like('title')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "bcm", "type": "incident", "id": r["id"],
                            "title": r["title"], "subtitle": ("Incident, " + (r["severity"] or "")).rstrip(" ,"),
                            "link": f"/bcm/?open=incident:{r['id']}"})

        # AI uses, and the Governance structure they sit in: applications, business processes and data assets.
        sc, sp = scope(("governance", "application"), "a")
        for r in db.execute(
            "SELECT a.id, a.name, a.application_type, "
            "EXISTS (SELECT 1 FROM ai_use_profiles p WHERE p.application_id = a.id) AS ai_use "
            f"FROM applications a WHERE {ci_like('a.name')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "governance", "type": "application", "id": r["id"], "title": r["name"],
                            "subtitle": "AI use" if r["ai_use"] else (r["application_type"] or "Application"),
                            "link": f"/ai-governance/systems/{r['id']}"})

        sc, sp = scope(("governance", "process"))
        for r in db.execute(
            f"SELECT id, name, code FROM business_processes WHERE {ci_like('name')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "governance", "type": "process", "id": r["id"], "title": r["name"],
                            "subtitle": r["code"] or "Business process", "link": "/governance/"})

        sc, sp = scope(("governance", "data_asset"))
        for r in db.execute(
            f"SELECT id, name, category FROM data_assets WHERE {ci_like('name')}{sc} LIMIT 10",
            (like_term, *sp)
        ).fetchall():
            results.append({"module": "governance", "type": "data_asset", "id": r["id"], "title": r["name"],
                            "subtitle": r["category"] or "Data asset", "link": "/governance/"})

        # AI impact assessments (AI Governance's own capability)
        sc, sp = scope(("sentinel", "aiia"))
        for r in db.execute(
            "SELECT id, ref_number, title FROM sentinel_aiia "
            f"WHERE ({ci_like('title')} OR {ci_like('ref_number')}){sc} LIMIT 10",
            (like_term, like_term, *sp)
        ).fetchall():
            results.append({"module": "sentinel", "type": "aiia", "id": r["id"], "title": r["title"],
                            "subtitle": r["ref_number"] or "AI impact assessment",
                            "link": f"/ai-governance/assessments/{r['id']}"})

        shown = results[:30]
        search_service.enrich(db, user, shown, q)
    finally:
        db.close()

    return _JSONResp({"results": shown, "total": len(results)})


# ═════════════════════════════════════════════════════════════════════════════
# COMPLIANCE CALENDAR
# ═════════════════════════════════════════════════════════════════════════════

# Calendar handlers live in routes_calendar.py.


@router.get("/analytics", response_class=HTMLResponse)
@require_auth
async def analytics_page(request: Request):
    """Advanced analytics page."""
    ctx = shell_ctx(request, active_module="platform", active_section="analytics")
    return shell_templates.TemplateResponse(request, "analytics.html", ctx)


@router.post("/api/analytics/snapshot")
@require_auth
async def api_analytics_capture_snapshot(request: Request):
    """Capture a daily analytics snapshot (admin only)."""
    if not has_capability(request.state.user, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    db = get_db()
    today = __import__('datetime').date.today().isoformat()
    try:
        metrics = []

        # Compliance metrics
        total_controls = db.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
        compliant = db.execute("SELECT COUNT(*) FROM controls WHERE status = 'Implemented'").fetchone()[0]
        pct = round((compliant / total_controls * 100), 1) if total_controls else 0
        metrics.append(("compliance_pct", pct, "aria"))
        metrics.append(("controls_total", total_controls, "aria"))
        metrics.append(("controls_compliant", compliant, "aria"))

        # Risk metrics
        risks_open = db.execute("SELECT COUNT(*) FROM risk_register WHERE status != 'closed'").fetchone()[0]
        risks_critical = db.execute("SELECT COUNT(*) FROM risk_register WHERE risk_level = 'critical' AND status != 'closed'").fetchone()[0]
        metrics.append(("risks_open", risks_open, "platform"))
        metrics.append(("risks_critical", risks_critical, "platform"))

        # Audit metrics
        audits_active = db.execute("SELECT COUNT(*) FROM grid_audits WHERE status IN ('Planning','Active')").fetchone()[0]
        ncs_open = db.execute("SELECT COUNT(*) FROM grid_non_conformances WHERE status = 'open'").fetchone()[0]
        metrics.append(("audits_active", audits_active, "grid"))
        metrics.append(("ncs_open", ncs_open, "grid"))

        # Privacy metrics
        breaches = db.execute("SELECT COUNT(*) FROM sentinel_breaches WHERE status != 'closed'").fetchone()[0]
        dsrs = db.execute("SELECT COUNT(*) FROM sentinel_dsr WHERE status NOT IN ('completed','closed')").fetchone()[0]
        metrics.append(("breaches_open", breaches, "sentinel"))
        metrics.append(("dsrs_open", dsrs, "sentinel"))

        # SLA metrics
        sla_breached = db.execute("SELECT COUNT(*) FROM sla_instances WHERE breached = 1 AND status = 'active'").fetchone()[0]
        metrics.append(("sla_breaches_active", sla_breached, "platform"))

        # Insert with REPLACE to handle re-runs on same day
        for name, value, module in metrics:
            db.execute(
                "INSERT INTO analytics_snapshots (snapshot_date, metric_name, metric_value, module) "
                "VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (snapshot_date, metric_name, module) DO UPDATE SET "
                "metric_value=excluded.metric_value",
                (today, name, value, module)
            )
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True, "date": today, "metrics_captured": len(metrics)})


@router.get("/api/analytics/trends")
@require_auth
async def api_analytics_trends(request: Request):
    """Get trend data for specified metrics."""
    if not request.state.user.get("is_super_admin"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    db = get_db()
    try:
        metric = request.query_params.get("metric", "compliance_pct")
        days = int(request.query_params.get("days", "30"))
        module = request.query_params.get("module", "")

        where = ["metric_name = %s"]
        params = [metric]
        if module:
            where.append("module = %s"); params.append(module)
        where.append(f"snapshot_date >= {sql_date_offset(f'-{int(days)} days')}")

        rows = db.execute(
            f"SELECT snapshot_date, metric_value FROM analytics_snapshots "
            f"WHERE {' AND '.join(where)} ORDER BY snapshot_date",
            params
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([{"date": r["snapshot_date"], "value": r["metric_value"]} for r in rows])


@router.get("/api/analytics/current")
@require_auth
async def api_analytics_current(request: Request):
    """Get current (latest) values for all metrics."""
    if not request.state.user.get("is_super_admin"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT metric_name, metric_value, module, snapshot_date "
            "FROM analytics_snapshots WHERE snapshot_date = ("
            "  SELECT MAX(snapshot_date) FROM analytics_snapshots"
            ") ORDER BY module, metric_name"
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


# ═════════════════════════════════════════════════════════════════════════════
# BULK IMPORT/EXPORT
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/bulk/export/{entity_type}")
@require_auth
async def api_bulk_export(request: Request, entity_type: str):
    """Export entities as JSON. Whole tables, so only the administrator who may import them may export them."""
    if not has_capability(request.state.user, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    db = get_db()
    try:
        table_map = {
            "controls": "aria_controls",
            "risks": "risk_register",
            "evidence": "evidence_items",
            "ropa": "sentinel_ropa",
            "frameworks": "frameworks",
        }
        table = table_map.get(entity_type)
        if not table:
            return _JSONResp({"error": f"Unknown entity type: {entity_type}"}, status_code=400)

        rows = db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    finally:
        db.close()

    data = [dict(r) for r in rows]
    return Response(
        content=json_lib.dumps(data, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={entity_type}_export.json"}
    )


@router.post("/api/bulk/import/{entity_type}")
@require_auth
async def api_bulk_import(request: Request, entity_type: str):
    """Import entities from JSON payload. Returns validation results."""
    if not has_capability(request.state.user, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)

    data = await _json_body(request)
    records = data.get("records", [])
    if not records:
        return _JSONResp({"error": "No records provided"}, status_code=400)

    if entity_type not in ("controls", "risks", "evidence", "ropa"):
        return _JSONResp({"error": f"Import not supported for: {entity_type}"}, status_code=400)

    # Same ownership rule as the Evidence Vault upload route.
    evidence_org_id = None if request.state.user.get("is_super_admin") else request.state.user.get("org_id")
    if entity_type == "evidence" and not request.state.user.get("is_super_admin") and not evidence_org_id:
        return _JSONResp({"error": "Your account has no organization to import evidence for"}, status_code=403)

    # Validation pass: check types without touching the DB
    val_errors = []
    for i, rec in enumerate(records):
        if entity_type == "risks":
            try:
                int(rec.get("likelihood", 3))
                int(rec.get("impact", 3))
            except (TypeError, ValueError):
                val_errors.append({"row": i, "error": "likelihood and impact must be integers"})
        if not rec.get("title") and entity_type != "controls":
            val_errors.append({"row": i, "error": "title is required"})
    if val_errors:
        return _JSONResp({"error": "Validation failed", "errors": val_errors, "imported": 0}, status_code=400)

    db = get_db()
    try:
        if entity_type == "controls":
            for rec in records:
                db.execute(
                    "INSERT INTO aria_controls (framework_id, ref, name, description, status, evidence_ref) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (rec.get("framework_id", 1),
                     rec.get("ref", rec.get("control_id", "")),
                     rec.get("name", rec.get("title", "")),
                     rec.get("description", ""),
                     rec.get("status", "Not Started"),
                     rec.get("evidence_ref", rec.get("evidence_notes", "")))
                )
        elif entity_type == "risks":
            for rec in records:
                lh = int(rec.get("likelihood", 3))
                imp = int(rec.get("impact", 3))
                score = lh * imp
                level = "critical" if score >= 20 else "high" if score >= 12 else "medium" if score >= 6 else "low"
                # An imported risk belongs to the importer's business unit, as a risk created by hand does. Without it
                # the row would be organization wide and visible to every unit.
                db.execute(
                    "INSERT INTO risk_register (title, description, source_module, category, "
                    "likelihood, impact, risk_level, treatment, status, created_by, business_unit_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (rec.get("title", ""), rec.get("description", ""), rec.get("source_module", ""),
                     rec.get("category", "operational"), lh, imp, level,
                     rec.get("treatment", "mitigate"), rec.get("status", "open"), request.state.user["id"],
                     request.state.user.get("business_unit_id"))
                )
        elif entity_type == "evidence":
            for rec in records:
                db.execute(
                    "INSERT INTO evidence_items (title, description, category, tags, uploaded_by, org_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (rec.get("title", ""), rec.get("description", ""), rec.get("category", "policy"),
                     rec.get("tags", ""), request.state.user["id"], evidence_org_id)
                )
        elif entity_type == "ropa":
            for rec in records:
                db.execute(
                    "INSERT INTO sentinel_ropa (ref_number, processing_name, purpose, legal_basis, "
                    "data_subjects, data_categories, status, business_unit_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (rec.get("ref_number", ""), rec.get("processing_name") or rec.get("name", ""), rec.get("purpose", ""),
                     rec.get("legal_basis") or rec.get("lawful_basis", ""), rec.get("data_subjects", ""),
                     rec.get("data_categories", ""), rec.get("status", "active"),
                     request.state.user.get("business_unit_id"))
                )
        db.commit()
    except Exception as e:
        db.rollback()
        log.error("Bulk import failed: %s", e)
        return _JSONResp({"error": "Import failed", "imported": 0}, status_code=500)
    finally:
        db.close()

    imported = len(records)
    log_audit(request.state.user, "platform", "bulk_import",
              details=f"Imported {imported} {entity_type} records")
    return _JSONResp({"imported": imported, "errors": [], "total": imported})


# ═════════════════════════════════════════════════════════════════════════════
# PLATFORM USERS LIST  (used by task board assignee dropdowns)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/platform/users")
@require_auth
async def api_platform_users(request: Request):
    """Return active users for assignment dropdowns (scoped to caller's org)."""
    user = request.state.user
    org_id = user.get("org_id")
    db = get_db()
    try:
        if org_id:
            rows = db.execute(
                "SELECT id, username, full_name, email "
                "FROM users WHERE is_active = 1 AND org_id=%s ORDER BY full_name",
                (org_id,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, username, full_name, email "
                "FROM users WHERE is_active = 1 ORDER BY full_name"
            ).fetchall()
        return _JSONResp([dict(r) for r in rows])
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# CROSS-MODULE TASK BOARD
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/tasks", response_class=HTMLResponse)
@require_auth
async def task_board_page(request: Request):
    """Cross-module task board page."""
    ctx = shell_ctx(request, active_module="platform", active_section="tasks")
    return shell_templates.TemplateResponse(request, "task_board.html", ctx)


@router.get("/api/tasks")
@require_auth
async def api_tasks_list(request: Request):
    """List tasks with filters.

    PLAN-36 P06 discovery found this had no business-unit scoping at all
    despite task_board.business_unit_id existing -- any authenticated user
    saw every BU's tasks within their org. NULL business_unit_id is
    treated as org-wide-visible, the same convention used throughout this
    codebase (e.g. modules/aria/policy_access.py's document_read_ok)."""
    db = get_db()
    try:
        status = request.query_params.get("status", "")
        module = request.query_params.get("module", "")
        assigned = request.query_params.get("assigned_to", "")
        my_tasks = request.query_params.get("mine", "")

        where = ["1=1"]
        params = []
        scope = bu_scope_ids(request.state.user)
        if scope is not None:
            placeholders = ",".join(["%s"] * len(scope)) if scope else "NULL"
            where.append(f"(t.business_unit_id IS NULL OR t.business_unit_id IN ({placeholders}))")
            params.extend(scope)
        if status:
            where.append("t.status = %s"); params.append(status)
        if module:
            where.append("t.module = %s"); params.append(module)
        if assigned:
            where.append("t.assigned_to = %s"); params.append(int(assigned))
        if my_tasks:
            where.append("t.assigned_to = %s"); params.append(request.state.user["id"])
        # task_board predates org_id. Its creator owns the task's tenant;
        # only legacy system tasks fall back to the assignee's tenant.
        if not request.state.user.get("is_super_admin"):
            where.append("COALESCE(c.org_id, u.org_id) = %s")
            params.append(request.state.user.get("org_id"))

        rows = db.execute(
            f"SELECT t.*, u.full_name as assigned_name, c.full_name as creator_name "
            f"FROM task_board t "
            f"LEFT JOIN users u ON t.assigned_to = u.id "
            f"LEFT JOIN users c ON t.created_by = c.id "
            f"WHERE {' AND '.join(where)} ORDER BY "
            f"CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
            f"t.due_date ASC NULLS LAST, t.created_at DESC "
            f"LIMIT 500",
            params
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.get("/api/tasks/stats")
@require_auth
async def api_tasks_stats(request: Request):
    """Task counts use the same tenant and BU scope as the visible board."""
    user = request.state.user
    scope = bu_scope_ids(user)
    where = ["1=1"]
    params = []
    if not user.get("is_super_admin"):
        where.append(
            "COALESCE((SELECT org_id FROM users WHERE id=t.created_by), "
            "(SELECT org_id FROM users WHERE id=t.assigned_to))=%s"
        )
        params.append(user.get("org_id"))
    if scope is not None:
        placeholders = ",".join(["%s"] * len(scope)) if scope else "NULL"
        where.append(f"(t.business_unit_id IS NULL OR t.business_unit_id IN ({placeholders}))")
        params.extend(scope)
    visible = " AND ".join(where)
    db = get_db()
    try:
        by_status = db.execute(
            f"SELECT t.status, COUNT(*) as c FROM task_board t WHERE {visible} GROUP BY t.status",
            params,
        ).fetchall()
        my_pending = db.execute(
            f"SELECT COUNT(*) FROM task_board t WHERE {visible} "
            "AND t.assigned_to=%s AND t.status NOT IN ('done','cancelled')",
            params + [user["id"]],
        ).fetchone()[0]
        overdue = db.execute(
            f"SELECT COUNT(*) FROM task_board t WHERE {visible} "
            "AND t.due_date < CURRENT_DATE AND t.status NOT IN ('done','cancelled')",
            params,
        ).fetchone()[0]
    finally:
        db.close()
    return _JSONResp({
        "by_status": {r["status"]: r["c"] for r in by_status},
        "my_pending": my_pending,
        "overdue": overdue,
    })


@router.get("/api/tasks/{tid}")
@require_auth
async def api_task_detail(request: Request, tid: int):
    """Return one tenant- and business-unit-visible task for a deep link."""
    user = request.state.user
    where = ["t.id = %s"]
    params = [tid]
    if not user.get("is_super_admin"):
        where.append("COALESCE(c.org_id, u.org_id) = %s")
        params.append(user.get("org_id"))
    scope = bu_scope_ids(user)
    if scope is not None:
        placeholders = ",".join(["%s"] * len(scope)) if scope else "NULL"
        where.append(f"(t.business_unit_id IS NULL OR t.business_unit_id IN ({placeholders}))")
        params.extend(scope)
    db = get_db()
    try:
        row = db.execute(
            "SELECT t.*, u.full_name AS assigned_name, c.full_name AS creator_name "
            "FROM task_board t "
            "LEFT JOIN users u ON t.assigned_to = u.id "
            "LEFT JOIN users c ON t.created_by = c.id "
            f"WHERE {' AND '.join(where)}",
            params,
        ).fetchone()
    finally:
        db.close()
    if row is None:
        return _JSONResp({"error": "Task not found."}, 404)
    return _JSONResp(dict(row))


@router.post("/api/tasks", status_code=201)
@require_auth
async def api_task_create(request: Request):
    """Create a task."""
    data = await _json_body(request)
    title = sanitize_short(data.get("title"), 255)
    if not title:
        return _JSONResp({"error": "Title is required."}, 400)
    description = sanitize_text(data.get("description"), 5000)
    module = sanitize_short(data.get("module"), 50)
    entity_type = sanitize_short(data.get("entity_type"), 50)
    entity_id = validate_int(data.get("entity_id"))
    assigned_to = validate_int(data.get("assigned_to"))
    priority = validate_choice(data.get("priority"), {"critical", "high", "medium", "low"}, "medium")
    status = validate_choice(data.get("status"), {"todo", "in_progress", "review", "done", "cancelled"}, "todo")
    due_date = validate_date(data.get("due_date"))
    tags = sanitize_short(data.get("tags"), 500)
    uid = request.state.user["id"]
    try:
        tid = create_task_with_assignment_notification(
            title=title, description=description, module=module,
            entity_type=entity_type, entity_id=entity_id, assigned_to=assigned_to,
            priority=priority, status=status, due_date=due_date, tags=tags,
            created_by=uid,
        )
    except ValueError as exc:
        return _JSONResp({"error": str(exc)}, status_code=400)
    return _JSONResp({"id": tid}, status_code=201)


@router.put("/api/tasks/bulk")
@require_auth
async def api_tasks_bulk_update(request: Request):
    """Bulk update multiple tasks at once."""
    data = await _json_body(request)
    raw_ids = data.get("ids", [])
    updates = data.get("updates", {})
    if not raw_ids or not updates:
        return _JSONResp({"error": "ids and updates required"}, 400)
    ids = [validate_int(i) for i in raw_ids[:100]]
    ids = [i for i in ids if i is not None]
    if not ids:
        return _JSONResp({"error": "No valid task IDs."}, 400)
    uid = request.state.user["id"]
    is_admin = has_capability(request.state.user, "platform.manage_users")
    _VALIDATORS = {
        "status": lambda v: validate_choice(v, {"todo", "in_progress", "review", "done", "cancelled"}),
        "priority": lambda v: validate_choice(v, {"critical", "high", "medium", "low"}),
        "assigned_to": lambda v: validate_int(v),
    }
    fields, params = [], []
    for key, validator in _VALIDATORS.items():
        if key in updates:
            val = validator(updates[key])
            if val is not None:
                fields.append(f"{key} = %s")
                params.append(val)
    if not fields:
        return _JSONResp({"error": "No valid fields to update."}, 400)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    db = get_db()
    try:
        if updates.get("assigned_to") not in (None, ""):
            try:
                validate_task_assignee(db, uid, validate_int(updates["assigned_to"]))
            except ValueError as exc:
                return _JSONResp({"error": str(exc)}, status_code=400)
        if not is_admin:
            placeholders = ", ".join(["%s"] * len(ids))
            owned = db.execute(
                f"SELECT id FROM task_board WHERE id IN ({placeholders}) "
                f"AND (created_by = %s OR assigned_to = %s)",
                ids + [uid, uid],
            ).fetchall()
            ids = [r["id"] for r in owned]
        if not ids:
            return _JSONResp({"error": "No accessible tasks."}, 403)
        placeholders = ", ".join(["%s"] * len(ids))
        # who each task belonged to, so that only the tasks that really change hands are told about
        new_assignee = validate_int(updates.get("assigned_to")) if "assigned_to" in updates else None
        before = {r["id"]: r["assigned_to"] for r in db.execute(
            f"SELECT id, assigned_to FROM task_board WHERE id IN ({placeholders})", ids).fetchall()}
        params.extend(ids)
        sql = f"UPDATE task_board SET {', '.join(fields)} WHERE id IN ({placeholders})"
        if not is_admin:
            sql += " AND (created_by = %s OR assigned_to = %s)"
            params.extend([uid, uid])
        db.execute(sql, params)
        db.commit()
        if new_assignee is not None:
            tell_new_assignee(db, [t for t, owner in before.items() if owner != new_assignee], new_assignee, uid)
    finally:
        db.close()
    return _JSONResp({"updated": len(ids)})


@router.put("/api/tasks/{tid}")
@require_auth
async def api_task_update(request: Request, tid: int):
    """Update a task (including status changes for drag-drop)."""
    data = await _json_body(request)
    uid = request.state.user["id"]
    is_admin = has_capability(request.state.user, "platform.manage_users")
    db = get_db()
    try:
        row = db.execute("SELECT created_by, assigned_to FROM task_board WHERE id = %s", (tid,)).fetchone()
        if not row:
            return _JSONResp({"error": "Task not found."}, 404)
        if not is_admin and row["created_by"] != uid and row["assigned_to"] != uid:
            return _JSONResp({"error": "Access denied."}, 403)
        _SANITIZERS = {
            "title": lambda v: sanitize_short(v, 255),
            "description": lambda v: sanitize_text(v, 5000),
            "module": lambda v: sanitize_short(v, 50),
            "assigned_to": lambda v: validate_int(v),
            "priority": lambda v: validate_choice(v, {"critical", "high", "medium", "low"}),
            "status": lambda v: validate_choice(v, {"todo", "in_progress", "review", "done", "cancelled"}),
            "due_date": lambda v: validate_date(v),
            "tags": lambda v: sanitize_short(v, 500),
        }
        if data.get("assigned_to") not in (None, ""):
            try:
                validate_task_assignee(db, uid, validate_int(data["assigned_to"]))
            except ValueError as exc:
                return _JSONResp({"error": str(exc)}, status_code=400)
        fields, params = [], []
        for key, sanitizer in _SANITIZERS.items():
            if key in data:
                val = sanitizer(data[key])
                if val is not None:
                    fields.append(f"{key} = %s")
                    params.append(val)
        if fields:
            fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(tid)
            sql = f"UPDATE task_board SET {', '.join(fields)} WHERE id = %s"
            if not is_admin:
                sql += " AND (created_by = %s OR assigned_to = %s)"
                params.extend([uid, uid])
            cur = db.execute(sql, params)
            db.commit()
            if cur.rowcount == 0:
                return _JSONResp({"error": "Task changed or was removed; refresh and retry."}, 409)
            handed_to = validate_int(data.get("assigned_to")) if "assigned_to" in data else None
            if handed_to is not None and handed_to != row["assigned_to"]:
                tell_new_assignee(db, [tid], handed_to, uid)
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/tasks/{tid}")
@require_auth
async def api_task_delete(request: Request, tid: int):
    """Delete a task."""
    uid = request.state.user["id"]
    is_admin = has_capability(request.state.user, "platform.manage_users")
    db = get_db()
    try:
        if is_admin:
            result = db.execute("DELETE FROM task_board WHERE id = %s", (tid,))
        else:
            result = db.execute(
                "DELETE FROM task_board WHERE id = %s AND (created_by = %s OR assigned_to = %s)",
                (tid, uid, uid)
            )
        db.commit()
        if result.rowcount == 0:
            return _JSONResp({"error": "Task not found or access denied."}, 404)
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.post("/api/tasks/ai-prioritize")
@require_auth
async def api_tasks_ai_prioritize(request: Request):
    """AI-powered task prioritization for TODO tasks."""
    from core.ai_client import is_configured, create_message, safe_json_parse
    if not is_configured():
        return _JSONResp({"error": "AI not configured"}, 503)
    db = get_db()
    try:
        tasks = [dict(r) for r in db.execute(
            "SELECT id, title, description, module, priority, due_date, assigned_to "
            "FROM task_board WHERE status IN ('todo','in_progress') "
            "ORDER BY created_at DESC LIMIT 30"
        ).fetchall()]
    finally:
        db.close()
    if not tasks:
        return _JSONResp({"ranked": [], "rationale": "No open tasks to prioritize."})
    task_summary = [
        {"id": t["id"], "title": t["title"], "module": t["module"],
         "priority": t["priority"], "due_date": t["due_date"],
         "description": (t["description"] or "")[:100]}
        for t in tasks
    ]
    import json
    prompt = (
        "Here are open compliance tasks:\n"
        f"{json.dumps(task_summary, default=str)}\n\n"
        "Rank them by urgency. Consider: regulatory deadlines, risk severity, "
        "overdue dates, and module criticality. Return a JSON array of "
        "{task_id, suggested_priority (critical/high/medium/low), rank (1=most urgent), "
        "rationale (one sentence)}. Order by rank."
    )
    try:
        raw = create_message(
            [{"role": "user", "content": prompt}],
            system="You are a GRC task prioritization assistant. Respond ONLY with a JSON array.",
            max_tokens=1200,
            feature="launcher.api_tasks_ai_prioritize",
        )
        ranked = safe_json_parse(raw)
        if not isinstance(ranked, list):
            ranked = []
    except Exception:
        ranked = []
    return _JSONResp({"ranked": ranked})


# ═══════════════════════════════════════════════════════════════════════════════
#  PLATFORM TRAINER
# ═══════════════════════════════════════════════════════════════════════════════

# Themis answers from the platform knowledge base in core/platform_guide.py.
_THEMIS_AI_CACHE: dict[str, tuple[dict, float]] = {}
_THEMIS_RATE: dict[int, list[float]] = {}
_THEMIS_RATE_LIMIT = 10
_THEMIS_RATE_WINDOW = 60
_THEMIS_CACHE_TTL = 300
_THEMIS_MAX_INPUT = 500


def _themis_rate_ok(user_id: int) -> bool:
    """Return True if user_id has not exceeded the AI call rate limit."""
    import time
    now = time.time()
    window = _THEMIS_RATE.get(user_id, [])
    window = [t for t in window if now - t < _THEMIS_RATE_WINDOW]
    if len(window) >= _THEMIS_RATE_LIMIT:
        _THEMIS_RATE[user_id] = window
        return False
    window.append(now)
    _THEMIS_RATE[user_id] = window
    return True


def _themis_cached(question: str) -> dict | None:
    """Return a cached guide answer if still fresh. Keys include the retrieved entries, so they never cross roles."""
    import time
    entry = _THEMIS_AI_CACHE.get(question)
    if entry and time.time() - entry[1] < _THEMIS_CACHE_TTL:
        return entry[0]
    return None


@router.get("/api/onboarding")
@require_auth
async def api_onboarding(request: Request):
    """Guided tours and the getting-started checklist this person may use. Written content, no AI."""
    from core import mfa, onboarding
    user = request.state.user
    try:
        mfa_on = mfa.is_enabled(user["id"])
    except Exception:
        log.warning("MFA status lookup failed for the onboarding checklist", exc_info=True)
        mfa_on = False
    return _JSONResp({
        "user": user["id"],
        "tours": onboarding.tours_for(user),
        "checklist": onboarding.checklist_for(user, mfa_on),
    })


@router.post("/api/trainer/ask")
@require_auth
async def api_trainer_ask(request: Request):
    """Themis: answer a how-to question from the platform knowledge base (core.platform_guide).

    The guide never sees the page. A model, when used, receives only the masked question and the entries this
    person may use, and it can point to one of those entries; anything else is dropped.
    """
    from core import onboarding, platform_guide as guide
    from core.ai_client import create_message, is_configured, safe_json_parse
    data = await _json_body(request)
    question = str(data.get("question") or "").strip()
    page = str(data.get("page") or "/")[:200]
    if not question:
        return _JSONResp({"answer": "Please ask a question about the platform."})
    if len(question) > _THEMIS_MAX_INPUT:
        return _JSONResp({"answer": "Please keep your question shorter (under 500 characters)."})

    user = request.state.user
    masked = guide.mask(question)  # from here on the raw question is not used
    results, best_hidden = guide.search(masked, user, onboarding.open_areas(user), page=page, hidden=True)
    found = [r for r in results if r[0] >= guide.MIN_SCORE]
    if best_hidden >= guide.MIN_SCORE and (not found or best_hidden > found[0][0]):
        return _JSONResp({"answer": guide.not_for_you()})  # never names or links the page itself
    if not found:
        return _JSONResp({"answer": guide.not_covered()})
    allowed = {e["id"] for _, e in found}
    best = found[0][1]
    direct = {"answer": best["answer"], "source": "kb", "go": guide.target(best["id"], allowed)}
    if not is_configured() or not _themis_rate_ok(user.get("id", 0)):
        return _JSONResp(direct)

    cache_key = masked.lower() + "|" + ",".join(sorted(allowed))
    cached = _themis_cached(cache_key)
    if cached:
        return _JSONResp(cached)
    try:
        raw = create_message(
            [{"role": "user", "content": "Help entries:\n\n" + guide.passages(found) + "\n\nQuestion: " + masked}],
            system=guide.SYSTEM_PROMPT, max_tokens=500, feature="launcher.api_trainer_ask",
        )
    except Exception:
        log.info("Themis answered from the knowledge base: the AI call was refused or failed")
        return _JSONResp(direct)
    parsed = safe_json_parse(raw, fallback={})
    answer = str(parsed.get("answer") or "").strip() if isinstance(parsed, dict) else ""
    if not answer:
        return _JSONResp(direct)
    reply = {"answer": answer.replace("\u2014", ", "), "source": "ai",
             "go": guide.target(str(parsed.get("go") or ""), allowed)}
    import time
    _THEMIS_AI_CACHE[cache_key] = (reply, time.time())
    return _JSONResp(reply)


# ═══════════════════════════════════════════════════════════════════════════════
#  EMAIL REMINDERS (Cross-Module)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/reminders")
@require_auth
async def api_reminders_list(request: Request):
    """List reminders — optionally filter by module."""
    uid = request.state.user["id"]
    module = request.query_params.get("module", "")
    db = get_db()
    try:
        q = """SELECT r.*, u.full_name as recipient_name
               FROM email_reminders r
               LEFT JOIN users u ON r.recipient_id = u.id
               WHERE r.created_by = %s"""
        params = [uid]
        if module:
            q += " AND r.module = %s"
            params.append(module)
        q += " ORDER BY r.remind_at ASC"
        rows = db.execute(q, params).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/reminders")
@require_auth
async def api_reminders_create(request: Request):
    """Create a new email reminder."""
    data = await _json_body(request)
    user = request.state.user

    title = sanitize_short(data.get("title"), 255)
    if not title:
        return _JSONResp({"error": "Title is required."}, status_code=400)

    remind_at = validate_date(data.get("remind_at"))
    if not remind_at:
        return _JSONResp({"error": "Valid reminder date/time is required."}, status_code=400)

    # Determine recipient
    recipient_id = data.get("recipient_id") or user["id"]
    recipient_email = data.get("recipient_email", "")

    if not recipient_email:
        # Look up the user's email
        db = get_db()
        try:
            u = db.execute("SELECT email FROM users WHERE id = %s", (recipient_id,)).fetchone()
            recipient_email = u["email"] if u else user.get("email", "")
        finally:
            db.close()

    db = get_db()
    try:
        db.execute("""
            INSERT INTO email_reminders (module, entity_type, entity_id, title, message,
                                         recipient_id, recipient_email, remind_at,
                                         repeat_interval, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            data.get("module", "platform"),
            data.get("entity_type", ""),
            data.get("entity_id"),
            title,
            data.get("message", ""),
            recipient_id,
            recipient_email,
            remind_at,
            data.get("repeat_interval", "none"),
            user["id"],
        ))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/reminders/{rid}")
@require_auth
async def api_reminders_delete(request: Request, rid: int):
    """Delete a reminder."""
    uid = request.state.user["id"]
    db = get_db()
    try:
        db.execute("DELETE FROM email_reminders WHERE id = %s AND created_by = %s", (rid, uid))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.post("/api/reminders/send-due")
@_require_cap("platform.manage_users")
async def api_reminders_send_due(request: Request):
    """
    Process and send all due reminders (admin-triggered manual flush).
    The auto-scheduler in core/reminder_scheduler.py handles this automatically every 5 minutes.
    """
    from core.reminder_scheduler import _process_due_reminders
    _process_due_reminders()
    return _JSONResp({"success": True, "message": "Due reminders processed"})


# ═══════════════════════════════════════════════════════════════════════════════
# GOVERNANCE TIMELINE
# ═══════════════════════════════════════════════════════════════════════════════

_EVENT_LABELS = {
    "user_created":           "User account created",
    "user_updated":           "User account updated",
    "user_deleted":           "User account deleted",
    "user_role_changed":      "User role changed",
    "login":                  "User logged in",
    "login_failed":           "Failed login attempt",
    "mfa_enabled":            "MFA enabled",
    "mfa_disabled":           "MFA disabled",
    "password_changed":       "Password changed",
    "password_reset":         "Password reset requested",
    "connectors_updated":     "Connectors configuration updated",
    "security_policy_changed":"Security policy changed",
    "risk_created":           "Risk created",
    "risk_updated":           "Risk updated",
    "risk_deleted":           "Risk deleted",
    "audit_created":          "Audit created",
    "audit_updated":          "Audit updated",
    "audit_completed":        "Audit completed",
    "nc_created":             "Non-conformance created",
    "nc_updated":             "Non-conformance updated",
    "nc_closed":              "Non-conformance closed",
    "document_created":       "Document created",
    "document_updated":       "Document updated",
    "document_approved":      "Document approved",
    "breach_created":         "Data breach reported",
    "breach_updated":         "Data breach updated",
    "breach_closed":          "Data breach closed",
    "ropa_created":           "RoPA record created",
    "ropa_updated":           "RoPA record updated",
    "dpia_created":           "DPIA created",
    "dpia_updated":           "DPIA updated",
    "plan_created":           "BCP plan created",
    "plan_updated":           "BCP plan updated",
    "incident_created":       "Incident created",
    "incident_updated":       "Incident updated",
    "evidence_uploaded":      "Evidence uploaded",
    "evidence_updated":       "Evidence updated",
    "evidence_deleted":       "Evidence deleted",
    "evidence_linked":        "Evidence linked",
    "task_created":           "Task created",
    "task_updated":           "Task updated",
    "task_completed":         "Task completed",
    "framework_activated":    "Risk framework activated",
    "appetite_updated":       "Risk appetite updated",
    "orm_event_created":      "ORM event logged",
    "orm_event_updated":      "ORM event updated",
}

_ENTITY_TYPE_ALIAS = {
    "risk":       "Risk",
    "audit":      "Audit",
    "nc":         "Non-conformance",
    "document":   "Document",
    "breach":     "Data Breach",
    "ropa":       "RoPA Record",
    "dpia":       "DPIA",
    "plan":       "BCP Plan",
    "incident":   "Incident",
    "evidence":   "Evidence",
    "item":       "Evidence Item",
    "task":       "Task",
    "user":       "User",
    "event":      "ORM Event",
    "control":    "Control",
    "framework":  "Framework",
}

_MODULE_COLORS = {
    "erm":       "#ef4444",
    "orm":       "#f97316",
    "grid":      "#eab308",
    "aria":      "#3b82f6",
    "sentinel":  "#8b5cf6",
    "bcm":       "#06b6d4",
    "evidence":  "#10b981",
    "platform":  "#64748b",
    "governance":"#14b8a6",
}


@router.get("/api/timeline")
@require_auth
async def api_timeline(request: Request):
    """Governance timeline: paginated audit log events with human labels."""
    days = min(int(request.query_params.get("days", "30")), 365)
    module_filter = request.query_params.get("module", "")
    page = max(int(request.query_params.get("page", "1")), 1)
    per_page = 50
    offset = (page - 1) * per_page
    org_id = request.state.user.get("org_id")

    db = get_db()
    try:
        where = [f"created_at >= {sql_date_offset(f'-{days} days')}"]
        params = []
        if org_id:
            where.append("org_id = %s")
            params.append(org_id)
        if module_filter:
            where.append("module = %s")
            params.append(module_filter)

        where_sql = " AND ".join(where)

        rows = db.execute(
            f"SELECT id, user_id, username, module, action, entity_type, "
            f"entity_id, details, created_at "
            f"FROM audit_log WHERE {where_sql} "
            f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (*params, per_page, offset),
        ).fetchall()

        total = db.execute(
            f"SELECT COUNT(*) FROM audit_log WHERE {where_sql}",
            (*params,),
        ).fetchone()[0]
    finally:
        db.close()

    events = []
    for r in rows:
        action = r["action"] or ""
        events.append({
            "id": r["id"],
            "username": r["username"] or "system",
            "module": r["module"] or "platform",
            "action": action,
            "label": _EVENT_LABELS.get(action, action.replace("_", " ").title()),
            "entity_type": r["entity_type"] or "",
            "entity_type_label": _ENTITY_TYPE_ALIAS.get(r["entity_type"] or "", r["entity_type"] or ""),
            "entity_id": r["entity_id"],
            "details": r["details"] or "",
            "created_at": r["created_at"],
            "color": _MODULE_COLORS.get(r["module"] or "platform", "#64748b"),
        })

    return _JSONResp({
        "events": events,
        "total": total,
        "page": page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "modules": list(_MODULE_COLORS.keys()),
    })


# ═══════════════════════════════════════════════════════════════════════════════
# RELATED ITEMS: Cross-Module Link API
# ═══════════════════════════════════════════════════════════════════════════════
# Which records can be linked, who may see a link and how it is stored all live in the relationship service
# (modules/governance/relationships.py). These routes parse the request, commit, audit and shape the answer.

def _link_error(error):
    return _JSONResp({"error": error.message}, status_code=error.status)


@router.get("/api/links/{module}/{etype}/{eid}")
@require_auth
async def api_links_get(request: Request, module: str, etype: str, eid: int):
    """Get the cross-module links for an entity, with resolved titles and deep links.

    Only records the caller could open in their own module are listed, and only when the caller could open
    the entity itself: anything else is left out entirely (no title, id or count), so the answer is the same as
    for a record that does not exist."""
    db = get_db()
    try:
        links = relationships.list_links(db, request.state.user, (module, etype), eid)
    finally:
        db.close()
    return _JSONResp(links)


@router.get("/api/links/{module}/{etype}/{eid}/graph")
@require_auth
async def api_links_graph(request: Request, module: str, etype: str, eid: int):
    """The records within a few confirmed links of one record, each one the caller may open (bounded)."""
    try:
        depth = int(request.query_params.get("depth", 2))
    except ValueError:
        depth = 2
    db = get_db()
    try:
        graph = relationships.neighbours(db, request.state.user, (module, etype), eid, depth=depth)
    finally:
        db.close()
    return _JSONResp(graph)


@router.post("/api/links", status_code=201)
@require_auth
async def api_links_create(request: Request):
    """Create a cross-module link between two linkable entities the caller can open."""
    data = await _json_body(request)
    source = (sanitize_short(data.get("source_module", "")), sanitize_short(data.get("source_type", "")),
              validate_int(data.get("source_id")))
    target = (sanitize_short(data.get("target_module", "")), sanitize_short(data.get("target_type", "")),
              validate_int(data.get("target_id")))
    rel = validate_choice(data.get("relationship", "related"), RELATIONSHIP_LABELS, "related")
    user = request.state.user
    db = get_db()
    try:
        try:
            result = relationships.create_link(db, user, source, target, rel, note=data.get("note") or "")
        except relationships.LinkError as error:
            db.rollback()
            return _link_error(error)
        db.commit()
    finally:
        db.close()
    relationships.audit(user, result)
    return _JSONResp({"ok": True, "link_id": result["link_id"]}, status_code=201 if result["created"] else 200)


@router.post("/api/links/{link_id}/status")
@require_auth
async def api_links_status(request: Request, link_id: int):
    """Confirm or reject a candidate link."""
    data = await _json_body(request)
    user = request.state.user
    db = get_db()
    try:
        try:
            result = relationships.set_link_status(db, user, link_id, data.get("status"))
        except relationships.LinkError as error:
            db.rollback()
            return _link_error(error)
        db.commit()
    finally:
        db.close()
    relationships.audit(user, result)
    return _JSONResp({"ok": True})


@router.delete("/api/links/{link_id}")
@require_auth
async def api_links_delete(request: Request, link_id: int):
    """Delete a cross-module link. Only the creator or an admin may delete."""
    user = request.state.user
    db = get_db()
    try:
        try:
            result = relationships.remove_link(db, user, link_id)
        except relationships.LinkError as error:
            db.rollback()
            return _link_error(error)
        db.commit()
    finally:
        db.close()
    relationships.audit(user, result)
    return _JSONResp({"success": True})


@router.get("/timeline", response_class=HTMLResponse)
@require_auth
async def timeline_page(request: Request):
    """Render the Governance Timeline SPA page."""
    ctx = shell_ctx(request, active_module="timeline")
    return shell_templates.TemplateResponse(request, "timeline.html", ctx)
