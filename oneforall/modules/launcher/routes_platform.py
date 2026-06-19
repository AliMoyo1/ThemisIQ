"""
Launcher sub-router: Platform utilities — Calendar, Analytics, Bulk import/export,
Task board, Trainer, Reminders, Notifications, Global search.
"""
import json as json_lib
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from database import insert_returning_id, sql_date_offset

from modules.launcher._route_helpers import (
    _JSONResp, require_auth, has_capability, log_audit,
    require_capability as _require_cap,
    shell_ctx, shell_templates, settings, get_db,
)

router = APIRouter()


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
        rows = db.execute(
            "SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT 50",
            (uid,)
        ).fetchall()
        unread = db.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = %s AND is_read = 0",
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
    """Search across all modules."""
    q = request.query_params.get("q", "").strip()
    if not q or len(q) < 2:
        return _JSONResp({"results": []})

    db = get_db()
    results = []
    search_term = f"%{q}%"
    try:
        # Unified controls
        for r in db.execute(
            "SELECT c.id, c.ref, c.name, f.name as framework_name "
            "FROM controls c JOIN frameworks f ON c.framework_id = f.id "
            "WHERE c.name LIKE %s OR c.ref LIKE %s LIMIT 10",
            (search_term, search_term)
        ).fetchall():
            results.append({"module": "aria", "type": "control", "id": r["id"],
                            "title": r["ref"] + " - " + r["name"],
                            "subtitle": r["framework_name"], "link": "/aria/"})

        # ARIA documents
        for r in db.execute(
            "SELECT id, doc_id, title FROM aria_documents WHERE title LIKE %s OR doc_id LIKE %s LIMIT 10",
            (search_term, search_term)
        ).fetchall():
            results.append({"module": "aria", "type": "document", "id": r["id"],
                            "title": r["title"], "subtitle": r["doc_id"], "link": "/aria/"})

        # Sentinel RoPA
        for r in db.execute(
            "SELECT id, ref_number, processing_name FROM sentinel_ropa WHERE processing_name LIKE %s OR ref_number LIKE %s LIMIT 10",
            (search_term, search_term)
        ).fetchall():
            results.append({"module": "sentinel", "type": "ropa", "id": r["id"],
                            "title": r["processing_name"], "subtitle": r["ref_number"] or "", "link": "/sentinel/"})

        # GRID audits
        for r in db.execute(
            "SELECT id, name FROM grid_audits WHERE name LIKE %s LIMIT 10",
            (search_term,)
        ).fetchall():
            results.append({"module": "grid", "type": "audit", "id": r["id"],
                            "title": r["name"], "subtitle": "Audit", "link": "/grid/"})

        # BCM plans
        for r in db.execute(
            "SELECT id, title FROM bcm_plans WHERE title LIKE %s LIMIT 10",
            (search_term,)
        ).fetchall():
            results.append({"module": "bcm", "type": "plan", "id": r["id"],
                            "title": r["title"], "subtitle": "BCM Plan", "link": "/bcm/"})

        # Risk register
        for r in db.execute(
            "SELECT id, title, source_module FROM risk_register WHERE title LIKE %s LIMIT 10",
            (search_term,)
        ).fetchall():
            results.append({"module": "platform", "type": "risk", "id": r["id"],
                            "title": r["title"], "subtitle": r["source_module"] or "Risk", "link": "/risk-register"})

        # Evidence
        for r in db.execute(
            "SELECT id, title, category FROM evidence_items WHERE title LIKE %s OR tags LIKE %s LIMIT 10",
            (search_term, search_term)
        ).fetchall():
            results.append({"module": "platform", "type": "evidence", "id": r["id"],
                            "title": r["title"], "subtitle": r["category"], "link": "/evidence/"})

        # Sentinel breaches
        for r in db.execute(
            "SELECT id, ref_number, title, severity FROM sentinel_breaches WHERE title LIKE %s OR ref_number LIKE %s LIMIT 10",
            (search_term, search_term)
        ).fetchall():
            results.append({"module": "sentinel", "type": "breach", "id": r["id"],
                            "title": r["title"], "subtitle": f"{r['ref_number']} — {r['severity'] or 'Breach'}",
                            "link": "/sentinel/"})

        # Sentinel DPIAs
        for r in db.execute(
            "SELECT id, ref_number, title FROM sentinel_dpias WHERE title LIKE %s OR ref_number LIKE %s LIMIT 10",
            (search_term, search_term)
        ).fetchall():
            results.append({"module": "sentinel", "type": "dpia", "id": r["id"],
                            "title": r["title"], "subtitle": r["ref_number"] or "DPIA", "link": "/sentinel/"})

        # Sentinel DSRs
        for r in db.execute(
            "SELECT id, ref_number, requester_name, request_type FROM sentinel_dsr WHERE requester_name LIKE %s OR ref_number LIKE %s LIMIT 10",
            (search_term, search_term)
        ).fetchall():
            results.append({"module": "sentinel", "type": "dsr", "id": r["id"],
                            "title": r["requester_name"] or r["ref_number"],
                            "subtitle": f"{r['ref_number']} — {r['request_type'] or 'DSR'}", "link": "/sentinel/"})

        # Sentinel vendors
        for r in db.execute(
            "SELECT id, name, type FROM sentinel_vendors WHERE name LIKE %s LIMIT 10",
            (search_term,)
        ).fetchall():
            results.append({"module": "sentinel", "type": "vendor", "id": r["id"],
                            "title": r["name"], "subtitle": r["type"] or "Vendor", "link": "/sentinel/"})

        # ERM enterprise risks
        for r in db.execute(
            "SELECT id, title, category, status FROM erm_enterprise_risks WHERE title LIKE %s LIMIT 10",
            (search_term,)
        ).fetchall():
            results.append({"module": "erm", "type": "risk", "id": r["id"],
                            "title": r["title"], "subtitle": f"{r['category'] or 'Risk'} — {r['status'] or ''}",
                            "link": "/erm/"})

        # ERM regulatory obligations
        for r in db.execute(
            "SELECT id, regulation_name, regulator, obligation FROM erm_regulatory_obligations WHERE regulation_name LIKE %s OR obligation LIKE %s LIMIT 10",
            (search_term, search_term)
        ).fetchall():
            results.append({"module": "erm", "type": "obligation", "id": r["id"],
                            "title": r["regulation_name"], "subtitle": r["regulator"] or "Obligation",
                            "link": "/erm/"})

        # ORM events
        for r in db.execute(
            "SELECT id, title, event_type, severity FROM orm_events WHERE title LIKE %s LIMIT 10",
            (search_term,)
        ).fetchall():
            results.append({"module": "orm", "type": "event", "id": r["id"],
                            "title": r["title"], "subtitle": f"{r['event_type'] or 'Event'} — {r['severity'] or ''}",
                            "link": "/orm/"})

        # ORM KRIs
        for r in db.execute(
            "SELECT id, name, description FROM orm_kris WHERE name LIKE %s LIMIT 10",
            (search_term,)
        ).fetchall():
            results.append({"module": "orm", "type": "kri", "id": r["id"],
                            "title": r["name"], "subtitle": "Key Risk Indicator", "link": "/orm/"})
    finally:
        db.close()

    return _JSONResp({"results": results[:30], "total": len(results)})


# ═════════════════════════════════════════════════════════════════════════════
# COMPLIANCE CALENDAR
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/calendar", response_class=HTMLResponse)
@require_auth
async def calendar_page(request: Request):
    """Compliance calendar page."""
    ctx = shell_ctx(request, active_module="platform", active_section="calendar")
    return shell_templates.TemplateResponse(request, "calendar.html", ctx)


@router.get("/api/calendar/events")
@require_auth
async def api_calendar_events(request: Request):
    """Get calendar events within a date range."""
    db = get_db()
    try:
        start = request.query_params.get("start", "")
        end = request.query_params.get("end", "")
        module = request.query_params.get("module", "")
        event_type = request.query_params.get("type", "")

        where = ["1=1"]
        params = []
        if start:
            where.append("ce.start_date >= %s"); params.append(start)
        if end:
            where.append("ce.start_date <= %s"); params.append(end)
        if module:
            where.append("ce.module = %s"); params.append(module)
        if event_type:
            where.append("ce.event_type = %s"); params.append(event_type)

        rows = db.execute(
            f"SELECT ce.*, u.full_name as assigned_name "
            f"FROM calendar_events ce LEFT JOIN users u ON ce.assigned_to = u.id "
            f"WHERE {' AND '.join(where)} ORDER BY ce.start_date",
            params
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/calendar/events", status_code=201)
@require_auth
async def api_calendar_event_create(request: Request):
    """Create a calendar event."""
    data = await request.json()
    db = get_db()
    try:
        eid = insert_returning_id(
            db,
            "INSERT INTO calendar_events (title, description, event_type, module, entity_type, "
            "entity_id, start_date, end_date, all_day, recurrence, assigned_to, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                data.get("title", ""),
                data.get("description", ""),
                data.get("event_type", "other"),
                data.get("module", ""),
                data.get("entity_type", ""),
                data.get("entity_id"),
                data.get("start_date", ""),
                data.get("end_date", ""),
                1 if data.get("all_day", True) else 0,
                data.get("recurrence", ""),
                data.get("assigned_to"),
                request.state.user["id"],
            )
        )
        db.commit()
    finally:
        db.close()
    return _JSONResp({"id": eid}, status_code=201)


@router.put("/api/calendar/events/{eid}")
@require_auth
async def api_calendar_event_update(request: Request, eid: int):
    """Update a calendar event."""
    data = await request.json()
    db = get_db()
    try:
        fields, params = [], []
        for key in ("title", "description", "event_type", "module", "start_date", "end_date",
                    "all_day", "recurrence", "assigned_to", "status"):
            if key in data:
                fields.append(f"{key} = %s"); params.append(data[key])
        if fields:
            params.append(eid)
            db.execute(f"UPDATE calendar_events SET {', '.join(fields)} WHERE id = %s", params)
            db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/calendar/events/{eid}")
@require_auth
async def api_calendar_event_delete(request: Request, eid: int):
    """Delete a calendar event."""
    db = get_db()
    try:
        db.execute("DELETE FROM calendar_events WHERE id = %s", (eid,))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


# ═════════════════════════════════════════════════════════════════════════════
# ANALYTICS & TRENDS
# ═════════════════════════════════════════════════════════════════════════════

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
        total_controls = db.execute("SELECT COUNT(*) FROM aria_controls").fetchone()[0]
        compliant = db.execute("SELECT COUNT(*) FROM aria_controls WHERE status = 'compliant'").fetchone()[0]
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
    """Export entities as JSON."""
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

    data = await request.json()
    records = data.get("records", [])
    if not records:
        return _JSONResp({"error": "No records provided"}, status_code=400)

    if entity_type not in ("controls", "risks", "evidence", "ropa"):
        return _JSONResp({"error": f"Import not supported for: {entity_type}"}, status_code=400)

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
                    "INSERT INTO aria_controls (framework_id, control_id, title, description, status, evidence_notes) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (rec.get("framework_id", 1), rec.get("control_id", ""), rec.get("title", ""),
                     rec.get("description", ""), rec.get("status", "not_implemented"), rec.get("evidence_notes", ""))
                )
        elif entity_type == "risks":
            for rec in records:
                lh = int(rec.get("likelihood", 3))
                imp = int(rec.get("impact", 3))
                score = lh * imp
                level = "critical" if score >= 20 else "high" if score >= 12 else "medium" if score >= 6 else "low"
                db.execute(
                    "INSERT INTO risk_register (title, description, source_module, category, "
                    "likelihood, impact, risk_level, treatment, status, created_by) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (rec.get("title", ""), rec.get("description", ""), rec.get("source_module", ""),
                     rec.get("category", "operational"), lh, imp, level,
                     rec.get("treatment", "mitigate"), rec.get("status", "open"), request.state.user["id"])
                )
        elif entity_type == "evidence":
            for rec in records:
                db.execute(
                    "INSERT INTO evidence_items (title, description, category, tags, created_by) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (rec.get("title", ""), rec.get("description", ""), rec.get("category", "policy"),
                     rec.get("tags", ""), request.state.user["id"])
                )
        elif entity_type == "ropa":
            for rec in records:
                db.execute(
                    "INSERT INTO sentinel_ropa (ref_number, processing_name, purpose, legal_basis, "
                    "data_subjects, data_categories, status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (rec.get("ref_number", ""), rec.get("processing_name") or rec.get("name", ""), rec.get("purpose", ""),
                     rec.get("legal_basis") or rec.get("lawful_basis", ""), rec.get("data_subjects", ""),
                     rec.get("data_categories", ""), rec.get("status", "active"))
                )
        db.commit()
    except Exception as e:
        db.rollback()
        return _JSONResp({"error": str(e), "imported": 0}, status_code=500)
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
    """Return active users for assignment dropdowns (platform-wide)."""
    db = get_db()
    try:
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
    """List tasks with filters."""
    db = get_db()
    try:
        status = request.query_params.get("status", "")
        module = request.query_params.get("module", "")
        assigned = request.query_params.get("assigned_to", "")
        my_tasks = request.query_params.get("mine", "")

        where = ["1=1"]
        params = []
        if status:
            where.append("t.status = %s"); params.append(status)
        if module:
            where.append("t.module = %s"); params.append(module)
        if assigned:
            where.append("t.assigned_to = %s"); params.append(int(assigned))
        if my_tasks:
            where.append("t.assigned_to = %s"); params.append(request.state.user["id"])

        rows = db.execute(
            f"SELECT t.*, u.full_name as assigned_name, c.full_name as creator_name "
            f"FROM task_board t "
            f"LEFT JOIN users u ON t.assigned_to = u.id "
            f"LEFT JOIN users c ON t.created_by = c.id "
            f"WHERE {' AND '.join(where)} ORDER BY "
            f"CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
            f"t.due_date ASC NULLS LAST, t.created_at DESC "
            f"LIMIT 200",
            params
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/tasks", status_code=201)
@require_auth
async def api_task_create(request: Request):
    """Create a task."""
    data = await request.json()
    db = get_db()
    try:
        tid = insert_returning_id(
            db,
            "INSERT INTO task_board (title, description, module, entity_type, entity_id, "
            "assigned_to, priority, status, due_date, tags, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                data.get("title", ""),
                data.get("description", ""),
                data.get("module", ""),
                data.get("entity_type", ""),
                data.get("entity_id"),
                data.get("assigned_to"),
                data.get("priority", "medium"),
                data.get("status", "todo"),
                data.get("due_date", ""),
                data.get("tags", ""),
                request.state.user["id"],
            )
        )
        db.commit()
    finally:
        db.close()
    # Notify assignee
    if data.get("assigned_to"):
        db2 = get_db()
        try:
            db2.execute(
                "INSERT INTO notifications (user_id, title, message, link, category) VALUES (%s,%s,%s,%s,%s)",
                (data["assigned_to"], f"New Task: {data.get('title','')}", data.get("description","")[:100],
                 "/tasks", "task")
            )
            db2.commit()
        finally:
            db2.close()
    return _JSONResp({"id": tid}, status_code=201)


@router.put("/api/tasks/{tid}")
@require_auth
async def api_task_update(request: Request, tid: int):
    """Update a task (including status changes for drag-drop)."""
    data = await request.json()
    db = get_db()
    try:
        fields, params = [], []
        for key in ("title", "description", "module", "assigned_to", "priority", "status", "due_date", "tags"):
            if key in data:
                fields.append(f"{key} = %s"); params.append(data[key])
        if fields:
            fields.append("updated_at = CURRENT_TIMESTAMP")
            params.append(tid)
            db.execute(f"UPDATE task_board SET {', '.join(fields)} WHERE id = %s", params)
            db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/tasks/{tid}")
@require_auth
async def api_task_delete(request: Request, tid: int):
    """Delete a task."""
    db = get_db()
    try:
        db.execute("DELETE FROM task_board WHERE id = %s", (tid,))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.get("/api/tasks/stats")
@require_auth
async def api_tasks_stats(request: Request):
    """Task board statistics."""
    uid = request.state.user["id"]
    db = get_db()
    try:
        by_status = db.execute(
            "SELECT status, COUNT(*) as c FROM task_board GROUP BY status"
        ).fetchall()
        my_pending = db.execute(
            "SELECT COUNT(*) FROM task_board WHERE assigned_to = %s AND status NOT IN ('done','cancelled')",
            (uid,)
        ).fetchone()[0]
        overdue = db.execute(
            "SELECT COUNT(*) FROM task_board WHERE due_date < CURRENT_DATE AND status NOT IN ('done','cancelled')"
        ).fetchone()[0]
    finally:
        db.close()
    return _JSONResp({
        "by_status": {r["status"]: r["c"] for r in by_status},
        "my_pending": my_pending,
        "overdue": overdue,
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  PLATFORM TRAINER
# ═══════════════════════════════════════════════════════════════════════════════

# Knowledge base for the platform trainer — answers about features and navigation
_TRAINER_KB = {
    "/": "The Command Centre is your home dashboard showing key metrics across all modules. Use the icon sidebar on the left to navigate between modules.",
    "/aria": "ARIA is the policy & compliance module. Here you manage frameworks (ISO 27001, SOC 2, etc.), controls, policies, documents, and track implementation status.",
    "/grid": "GRID is the audit management module. Create and run audits, track findings, manage non-conformities, and collect evidence.",
    "/bcm": "BCM handles business continuity management. Build BIAs, recovery plans, run exercises, track incidents, and manage dependencies.",
    "/sentinel": "Sentinel manages data protection. Handle DPIAs, breach reporting, DSR tracking, RoPA records, vendor assessments, and consent management.",
    "workflows": "Workflows let you define multi-step approval chains. Create a definition with steps, then start instances that route through approvers.",
    "reports": "The reporting engine generates compliance reports on demand. Supported types include compliance summary, risk register, SLA performance, and audit status.",
    "task board": "The Task Board is a kanban-style view. Drag tasks between columns (To Do, In Progress, Review, Done) to update their status.",
    "calendar": "The Compliance Calendar shows upcoming events — audits, reviews, training sessions, deadlines, and exercises across all modules.",
    "analytics": "Analytics captures daily snapshots of your compliance metrics and shows trend charts over time. Click Capture Snapshot to record today's data.",
    "api keys": "API keys allow external systems to authenticate with the platform. Generate a key, copy it immediately (it won't be shown again), and use it as a Bearer token.",
    "webhooks": "Webhooks send HTTP POST notifications to external URLs when events occur — e.g., when a risk is created or an SLA is breached.",
    "notifications": "Click the bell icon in the topbar to see notifications. The system generates alerts for task assignments, workflow decisions, SLA breaches, and more.",
    "search": "Use the global search in the topbar to find risks, controls, documents, audits, and other entities across all modules.",
    "sla": "SLA definitions set response and resolution time targets. When an SLA instance is created, the system tracks whether targets are met or breached.",
    "dark mode": "Use the theme toggle in the topbar to switch between light and dark mode.",
    "tooltip mode": "Tooltip mode highlights interactive elements on the page. Hover over highlighted items to see explanations of what they do.",
    "import export": "Bulk import/export supports JSON format. Export entities to back up data, import to populate the system from external sources.",
}


@router.post("/api/trainer/ask")
@require_auth
async def api_trainer_ask(request: Request):
    """Platform Trainer — answer questions about how to use the platform."""
    data = await request.json()
    question = (data.get("question") or "").strip().lower()
    page = data.get("page", "/")

    if not question:
        return _JSONResp({"answer": "Please ask a question about the platform."})

    # Simple keyword matching against the knowledge base
    best_answer = None
    best_score = 0

    for key, answer in _TRAINER_KB.items():
        # Score based on keyword overlap
        key_words = key.lower().replace("/", " ").split()
        score = sum(1 for w in key_words if w in question)
        # Bonus for exact key match in question
        if key.strip("/") and key.strip("/").lower() in question:
            score += 3
        if score > best_score:
            best_score = score
            best_answer = answer

    # Context-aware fallback using current page
    if best_score < 1:
        page_key = page.rstrip("/")
        for key, answer in _TRAINER_KB.items():
            if key in page_key or page_key in key:
                best_answer = f"You're currently on the {key.strip('/').upper() or 'home'} page. {answer}"
                break

    if not best_answer:
        best_answer = (
            "I'm not sure about that specific feature. Here are some things I can help with: "
            "navigating between modules (ARIA, GRID, BCM, Sentinel), using workflows and approvals, "
            "the task board, compliance calendar, analytics, API keys, webhooks, notifications, "
            "search, SLA tracking, import/export, and tooltip mode. "
            "Try asking about any of these topics!"
        )

    return _JSONResp({"answer": best_answer})


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
    data = await request.json()
    user = request.state.user

    title = (data.get("title") or "").strip()
    if not title:
        return _JSONResp({"error": "Title is required"}, status_code=400)

    remind_at = data.get("remind_at", "")
    if not remind_at:
        return _JSONResp({"error": "Reminder date/time is required"}, status_code=400)

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
