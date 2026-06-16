"""
Launcher sub-router: Reporting engine — definitions, runs, report generation.
"""
import json as json_lib

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from database import insert_returning_id
from modules.launcher._route_helpers import (
    _JSONResp, require_auth, has_capability, log_audit,
    shell_ctx, shell_templates, get_db,
)

router = APIRouter()


REPORT_TYPES = {
    "compliance_summary": "Compliance Summary",
    "risk_report": "Risk Report",
    "audit_status": "Audit Status",
    "privacy_overview": "Privacy Overview",
    "bcm_readiness": "BCM Readiness",
    "sla_performance": "SLA Performance",
    "executive_brief": "Executive Brief",
}


@router.get("/reports", response_class=HTMLResponse)
@require_auth
async def reports_page(request: Request):
    """Reporting engine page."""
    ctx = shell_ctx(request, active_module="platform", active_section="reports")
    ctx["report_types"] = REPORT_TYPES
    return shell_templates.TemplateResponse(request, "reports.html", ctx)


@router.get("/api/reports/definitions")
@require_auth
async def api_report_definitions(request: Request):
    """List report definitions."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT rd.*, u.full_name as creator_name "
            "FROM report_definitions rd LEFT JOIN users u ON rd.created_by = u.id "
            "ORDER BY rd.created_at DESC"
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/reports/definitions", status_code=201)
@require_auth
async def api_report_definition_create(request: Request):
    """Create a report definition."""
    data = await request.json()
    db = get_db()
    try:
        rid = insert_returning_id(
            db,
            "INSERT INTO report_definitions (name, description, report_type, modules, parameters_json, schedule, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                data.get("name", ""),
                data.get("description", ""),
                data.get("report_type", "compliance_summary"),
                data.get("modules", ""),
                json_lib.dumps(data.get("parameters", {})),
                data.get("schedule", ""),
                request.state.user["id"],
            )
        )
        db.commit()
    finally:
        db.close()
    log_audit(request.state.user, "platform", "report_create", details=f"Created report: {data.get('name')}")
    return _JSONResp({"id": rid}, status_code=201)


@router.put("/api/reports/definitions/{rid}")
@require_auth
async def api_report_definition_update(request: Request, rid: int):
    """Update a report definition."""
    data = await request.json()
    db = get_db()
    try:
        fields, params = [], []
        for key in ("name", "description", "report_type", "modules", "schedule", "is_active"):
            if key in data:
                fields.append(f"{key} = %s")
                params.append(data[key])
        if "parameters" in data:
            fields.append("parameters_json = %s")
            params.append(json_lib.dumps(data["parameters"]))
        if fields:
            params.append(rid)
            db.execute(f"UPDATE report_definitions SET {', '.join(fields)} WHERE id = %s", params)
            db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/reports/definitions/{rid}")
@require_auth
async def api_report_definition_delete(request: Request, rid: int):
    """Disable a report definition."""
    if not has_capability(request.state.user, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    db = get_db()
    try:
        db.execute("UPDATE report_definitions SET is_active = 0 WHERE id = %s", (rid,))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.post("/api/reports/{rid}/run")
@require_auth
async def api_report_run(request: Request, rid: int):
    """Generate a report (run it now)."""
    db = get_db()
    try:
        defn = db.execute("SELECT * FROM report_definitions WHERE id = %s", (rid,)).fetchone()
        if not defn:
            return _JSONResp({"error": "Report not found"}, status_code=404)

        # Create a run record
        run_id = insert_returning_id(
            db,
            "INSERT INTO report_runs (definition_id, status, triggered_by) VALUES (%s,%s,%s)",
            (rid, "running", "manual")
        )
        db.commit()

        # Generate report data based on type
        report_type = defn["report_type"]
        result = {}

        if report_type == "compliance_summary":
            result["total_controls"] = db.execute("SELECT COUNT(*) FROM controls").fetchone()[0]
            result["compliant"] = db.execute("SELECT COUNT(*) FROM controls WHERE status IN ('Implemented','Compliant','Complete')").fetchone()[0]
            result["non_compliant"] = db.execute("SELECT COUNT(*) FROM controls WHERE status IN ('Not Started','Not Implemented')").fetchone()[0]
            result["partial"] = db.execute("SELECT COUNT(*) FROM controls WHERE status IN ('In Progress','Partially Implemented')").fetchone()[0]
            fw_rows = db.execute(
                "SELECT f.name, COUNT(c.id) as total, "
                "SUM(CASE WHEN c.status IN ('Implemented','Compliant','Complete') THEN 1 ELSE 0 END) as ok "
                "FROM frameworks f LEFT JOIN controls c ON c.framework_id = f.id "
                "WHERE f.is_active = 1 GROUP BY f.id"
            ).fetchall()
            result["by_framework"] = [dict(r) for r in fw_rows]

        elif report_type == "risk_report":
            result["total_open"] = db.execute("SELECT COUNT(*) FROM risk_register WHERE status != 'closed'").fetchone()[0]
            level_rows = db.execute(
                "SELECT risk_level, COUNT(*) as c FROM risk_register WHERE status != 'closed' GROUP BY risk_level"
            ).fetchall()
            result["by_level"] = {r["risk_level"]: r["c"] for r in level_rows}
            module_rows = db.execute(
                "SELECT source_module, COUNT(*) as c FROM risk_register WHERE status != 'closed' GROUP BY source_module"
            ).fetchall()
            result["by_module"] = {r["source_module"] or "unassigned": r["c"] for r in module_rows}
            top_risks = db.execute(
                "SELECT title, risk_level, source_module, treatment, status "
                "FROM risk_register WHERE status != 'closed' ORDER BY likelihood * impact DESC LIMIT 10"
            ).fetchall()
            result["top_risks"] = [dict(r) for r in top_risks]

        elif report_type == "audit_status":
            result["total_audits"] = db.execute("SELECT COUNT(*) FROM grid_audits").fetchone()[0]
            result["active"] = db.execute("SELECT COUNT(*) FROM grid_audits WHERE status IN ('planning','in_progress')").fetchone()[0]
            result["completed"] = db.execute("SELECT COUNT(*) FROM grid_audits WHERE status = 'completed'").fetchone()[0]
            result["open_ncs"] = db.execute("SELECT COUNT(*) FROM grid_nonconformities WHERE status = 'open'").fetchone()[0]

        elif report_type == "privacy_overview":
            result["ropa_count"] = db.execute("SELECT COUNT(*) FROM sentinel_ropa").fetchone()[0]
            result["dpia_count"] = db.execute("SELECT COUNT(*) FROM sentinel_dpia").fetchone()[0]
            result["breaches_open"] = db.execute("SELECT COUNT(*) FROM sentinel_breaches WHERE status != 'closed'").fetchone()[0]
            result["dsr_open"] = db.execute("SELECT COUNT(*) FROM sentinel_dsr WHERE status NOT IN ('completed','closed')").fetchone()[0]

        elif report_type == "bcm_readiness":
            result["plans"] = db.execute("SELECT COUNT(*) FROM bcm_plans").fetchone()[0]
            result["active_incidents"] = db.execute("SELECT COUNT(*) FROM bcm_incidents WHERE status IN ('open','responding')").fetchone()[0]
            result["exercises_completed"] = db.execute("SELECT COUNT(*) FROM bcm_exercises WHERE status = 'completed'").fetchone()[0]

        elif report_type == "sla_performance":
            result["total_tracked"] = db.execute("SELECT COUNT(*) FROM sla_instances").fetchone()[0]
            result["active"] = db.execute("SELECT COUNT(*) FROM sla_instances WHERE status = 'active'").fetchone()[0]
            result["breached"] = db.execute("SELECT COUNT(*) FROM sla_instances WHERE breached = 1").fetchone()[0]
            result["resolved"] = db.execute("SELECT COUNT(*) FROM sla_instances WHERE status = 'resolved'").fetchone()[0]

        elif report_type == "executive_brief":
            result["controls_total"] = db.execute("SELECT COUNT(*) FROM aria_controls").fetchone()[0]
            result["controls_compliant"] = db.execute("SELECT COUNT(*) FROM aria_controls WHERE status = 'compliant'").fetchone()[0]
            result["risks_critical"] = db.execute("SELECT COUNT(*) FROM risk_register WHERE risk_level = 'critical' AND status != 'closed'").fetchone()[0]
            result["risks_high"] = db.execute("SELECT COUNT(*) FROM risk_register WHERE risk_level = 'high' AND status != 'closed'").fetchone()[0]
            result["audits_active"] = db.execute("SELECT COUNT(*) FROM grid_audits WHERE status IN ('planning','in_progress')").fetchone()[0]
            result["breaches_open"] = db.execute("SELECT COUNT(*) FROM sentinel_breaches WHERE status != 'closed'").fetchone()[0]
            result["sla_breaches"] = db.execute("SELECT COUNT(*) FROM sla_instances WHERE breached = 1 AND status = 'active'").fetchone()[0]

        # Update run record
        db.execute(
            "UPDATE report_runs SET status = 'completed', completed_at = CURRENT_TIMESTAMP, result_json = %s WHERE id = %s",
            (json_lib.dumps(result), run_id)
        )
        db.commit()
    finally:
        db.close()

    return _JSONResp({"run_id": run_id, "status": "completed", "result": result})


@router.get("/api/reports/runs")
@require_auth
async def api_report_runs(request: Request):
    """List report runs."""
    db = get_db()
    try:
        def_id = request.query_params.get("definition_id", "")
        where = ["1=1"]
        params = []
        if def_id:
            where.append("rr.definition_id = %s")
            params.append(int(def_id))
        rows = db.execute(
            f"SELECT rr.*, rd.name as report_name, rd.report_type "
            f"FROM report_runs rr "
            f"LEFT JOIN report_definitions rd ON rr.definition_id = rd.id "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY rr.started_at DESC LIMIT 50",
            params
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.get("/api/reports/runs/{run_id}")
@require_auth
async def api_report_run_get(request: Request, run_id: int):
    """Get a specific report run with results."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT rr.*, rd.name as report_name, rd.report_type, rd.description "
            "FROM report_runs rr LEFT JOIN report_definitions rd ON rr.definition_id = rd.id "
            "WHERE rr.id = %s", (run_id,)
        ).fetchone()
        if not row:
            return _JSONResp({"error": "Not found"}, status_code=404)
    finally:
        db.close()
    result = dict(row)
    if result.get("result_json"):
        result["result"] = json_lib.loads(result.pop("result_json"))
    else:
        result["result"] = None
        result.pop("result_json", None)
    return _JSONResp(result)
