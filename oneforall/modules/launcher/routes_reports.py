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
    _json_body,)
from modules.launcher.scoped_metrics import scoped_count, run_scope_key, table_scope

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


def _report_result(db, user, report_type):
    """Generate only metrics and rows visible in the requesting scope."""
    c = lambda table, where="": scoped_count(db, user, table, where)
    if report_type == "compliance_summary":
        scope, params = table_scope("controls", user, "c")
        fs, fp = table_scope("frameworks", user, "f")
        framework_rows = db.execute(
            "SELECT f.name, COUNT(c.id) AS total, "
            "SUM(CASE WHEN c.status IN ('Implemented','Compliant','Complete') THEN 1 ELSE 0 END) AS ok "
            "FROM frameworks f LEFT JOIN controls c ON c.framework_id = f.id "
            f"AND {scope} WHERE f.is_active = 1 AND {fs} GROUP BY f.id",
            [*params, *fp],
        ).fetchall()
        return {
            "total_controls": c("controls"),
            "compliant": c("controls", "status IN ('Implemented','Compliant','Complete')"),
            "non_compliant": c("controls", "status IN ('Not Started','Not Implemented')"),
            "partial": c("controls", "status IN ('In Progress','Partially Implemented')"),
            "by_framework": [dict(r) for r in framework_rows],
        }
    if report_type == "risk_report":
        if not user.get("is_super_admin"):
            scope, params = table_scope("erm_enterprise_risks", user)
            rows = db.execute(
                "SELECT title, likelihood, impact, treatment, status FROM erm_enterprise_risks "
                f"WHERE {scope} AND status != 'closed' ORDER BY likelihood * impact DESC",
                params,
            ).fetchall()
            levels = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            top = []
            for r in rows:
                score = (r["likelihood"] or 0) * (r["impact"] or 0)
                level = "critical" if score >= 20 else "high" if score >= 12 else "medium" if score >= 6 else "low"
                levels[level] += 1
                if len(top) < 10:
                    top.append({"title": r["title"], "risk_level": level, "source_module": "erm",
                                "treatment": r["treatment"], "status": r["status"]})
            return {"total_open": len(rows), "by_level": levels,
                    "by_module": {"erm": len(rows)}, "top_risks": top}
        scope, params = table_scope("risk_register", user)
        levels = db.execute(
            f"SELECT risk_level, COUNT(*) AS c FROM risk_register WHERE {scope} "
            "AND status != 'closed' GROUP BY risk_level", params,
        ).fetchall()
        modules = db.execute(
            f"SELECT source_module, COUNT(*) AS c FROM risk_register WHERE {scope} "
            "AND status != 'closed' GROUP BY source_module", params,
        ).fetchall()
        rows = db.execute(
            "SELECT title, risk_level, source_module, treatment, status FROM risk_register "
            f"WHERE {scope} AND status != 'closed' ORDER BY likelihood * impact DESC LIMIT 10",
            params,
        ).fetchall()
        return {"total_open": c("risk_register", "status != 'closed'"),
                "by_level": {r["risk_level"]: r["c"] for r in levels},
                "by_module": {r["source_module"] or "unassigned": r["c"] for r in modules},
                "top_risks": [dict(r) for r in rows]}
    if report_type == "audit_status":
        return {"total_audits": c("grid_audits"),
                "active": c("grid_audits", "status IN ('Planning','Active')"),
                "completed": c("grid_audits", "status IN ('Completed','Complete')"),
                "open_ncs": c("grid_non_conformances", "status = 'open'")}
    if report_type == "privacy_overview":
        return {"ropa_count": c("sentinel_ropa"), "dpia_count": c("sentinel_dpias"),
                "breaches_open": c("sentinel_breaches", "status != 'closed'"),
                "dsr_open": c("sentinel_dsr", "status NOT IN ('completed','closed')")}
    if report_type == "bcm_readiness":
        return {"plans": c("bcm_plans"),
                "active_incidents": c("bcm_incidents", "status IN ('open','responding')"),
                "exercises_completed": c("bcm_exercises", "status = 'completed'")}
    if report_type == "sla_performance":
        return {"total_tracked": c("sla_instances"),
                "active": c("sla_instances", "status = 'active'"),
                "breached": c("sla_instances", "breached = 1"),
                "resolved": c("sla_instances", "status = 'resolved'")}
    if report_type == "executive_brief":
        return {"controls_total": c("controls"),
                "controls_compliant": c("controls", "status IN ('Implemented','Compliant','Complete')"),
                "risks_critical": c("risk_register", "risk_level = 'critical' AND status != 'closed'"),
                "risks_high": c("risk_register", "risk_level = 'high' AND status != 'closed'"),
                "audits_active": c("grid_audits", "status IN ('Planning','Active')"),
                "breaches_open": c("sentinel_breaches", "status != 'closed'"),
                "sla_breaches": c("sla_instances", "breached = 1 AND status = 'active'")}
    raise ValueError("Unknown report type")


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
    user = request.state.user
    where = "" if user.get("is_super_admin") else "WHERE rd.created_by = %s"
    params = () if user.get("is_super_admin") else (user["id"],)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT rd.*, u.full_name as creator_name "
            "FROM report_definitions rd LEFT JOIN users u ON rd.created_by = u.id "
            f"{where} ORDER BY rd.created_at DESC", params
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/reports/definitions", status_code=201)
@require_auth
async def api_report_definition_create(request: Request):
    """Create a report definition."""
    data = await _json_body(request)
    if data.get("report_type", "compliance_summary") not in REPORT_TYPES:
        return _JSONResp({"error": "Unknown report type"}, status_code=400)
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
    data = await _json_body(request)
    if "report_type" in data and data["report_type"] not in REPORT_TYPES:
        return _JSONResp({"error": "Unknown report type"}, status_code=400)
    user = request.state.user
    db = get_db()
    try:
        owner = db.execute("SELECT created_by FROM report_definitions WHERE id = %s", (rid,)).fetchone()
        if not owner or (not user.get("is_super_admin") and owner["created_by"] != user["id"]):
            return _JSONResp({"error": "Not found"}, status_code=404)
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
    user = request.state.user
    if not has_capability(user, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    db = get_db()
    try:
        owner = db.execute("SELECT created_by FROM report_definitions WHERE id = %s", (rid,)).fetchone()
        if not owner or (not user.get("is_super_admin") and owner["created_by"] != user["id"]):
            return _JSONResp({"error": "Not found"}, status_code=404)
        db.execute("UPDATE report_definitions SET is_active = 0 WHERE id = %s", (rid,))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.post("/api/reports/{rid}/run")
@require_auth
async def api_report_run(request: Request, rid: int):
    """Generate a report (run it now)."""
    user = request.state.user
    db = get_db()
    try:
        defn = db.execute("SELECT * FROM report_definitions WHERE id = %s", (rid,)).fetchone()
        if (not defn or not defn["is_active"] or
                (not user.get("is_super_admin") and defn["created_by"] != user["id"])):
            return _JSONResp({"error": "Report not found"}, status_code=404)
        if defn["report_type"] not in REPORT_TYPES:
            return _JSONResp({"error": "Unknown report type"}, status_code=400)

        # Create a run record
        run_id = insert_returning_id(
            db,
            "INSERT INTO report_runs (definition_id, status, triggered_by) VALUES (%s,%s,%s)",
            (rid, "running", run_scope_key(user))
        )
        db.commit()

        result = _report_result(db, user, defn["report_type"])

        # Update run record
        db.execute(
            "UPDATE report_runs SET status = 'completed', completed_at = CURRENT_TIMESTAMP, result_json = %s WHERE id = %s",
            (json_lib.dumps(result) if user.get("is_super_admin") else None, run_id)
        )
        db.commit()
    finally:
        db.close()

    return _JSONResp({"run_id": run_id, "status": "completed", "result": result})


@router.get("/api/reports/runs")
@require_auth
async def api_report_runs(request: Request):
    """List report runs."""
    user = request.state.user
    db = get_db()
    try:
        def_id = request.query_params.get("definition_id", "")
        where = ["1=1"]
        params = []
        if not user.get("is_super_admin"):
            where.extend(["rd.created_by = %s", "rr.triggered_by = %s"])
            params.extend([user["id"], run_scope_key(user)])
        if def_id:
            if not def_id.isdecimal():
                return _JSONResp({"error": "Invalid definition id"}, status_code=400)
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
    user = request.state.user
    db = get_db()
    try:
        access = "" if user.get("is_super_admin") else "AND rd.created_by = %s AND rr.triggered_by = %s"
        params = (run_id,) if user.get("is_super_admin") else (run_id, user["id"], run_scope_key(user))
        row = db.execute(
            "SELECT rr.*, rd.name as report_name, rd.report_type, rd.description "
            "FROM report_runs rr LEFT JOIN report_definitions rd ON rr.definition_id = rd.id "
            f"WHERE rr.id = %s {access}", params
        ).fetchone()
        if not row:
            return _JSONResp({"error": "Not found"}, status_code=404)
        current_result = None
        if not user.get("is_super_admin"):
            current_result = _report_result(db, user, row["report_type"])
    finally:
        db.close()
    result = dict(row)
    if not user.get("is_super_admin"):
        result.pop("result_json", None)
        result["result"] = current_result
    elif result.get("result_json"):
        result["result"] = json_lib.loads(result.pop("result_json"))
    else:
        result["result"] = None
        result.pop("result_json", None)
    return _JSONResp(result)


@router.post("/api/reports/executive-summary")
@require_auth
async def api_executive_summary(request: Request):
    """AI-generated cross-module executive summary."""
    from core.ai_client import is_configured, create_message
    if not is_configured():
        return _JSONResp({"error": "AI not configured"}, 503)
    user = request.state.user
    db = get_db()
    try:
        c = lambda table, where="": scoped_count(db, user, table, where)
        stats = {
            "controls_total": c("controls"),
            "controls_compliant": c("controls", "status IN ('Implemented','Compliant','Complete')"),
            "risks_open": c("risk_register", "status != 'closed'"),
            "risks_critical": c("risk_register", "risk_level = 'critical' AND status != 'closed'"),
            "audits_active": c("grid_audits", "status IN ('Planning','Active')"),
            "breaches_open": c("sentinel_breaches", "status != 'closed'"),
            "dsrs_open": c("sentinel_dsr", "status NOT IN ('completed','closed')"),
            "incidents_active": c("bcm_incidents", "status IN ('open','responding')"),
            "bcm_plans": c("bcm_plans"),
            "tasks_open": c("task_board", "status NOT IN ('done','cancelled')"),
            "tasks_overdue": c("task_board", "due_date < CURRENT_DATE "
                               "AND status NOT IN ('done','cancelled')"),
        }
        if stats["controls_total"]:
            stats["compliance_pct"] = round(stats["controls_compliant"] / stats["controls_total"] * 100)
        else:
            stats["compliance_pct"] = 0
    finally:
        db.close()
    prompt = (
        f"Compliance stats:\n{json_lib.dumps(stats)}\n\n"
        "These figures cover only records visible to the requesting user. "
        "A zero can mean no access to a module, so never claim that the organization has no "
        "such risks or events based on a zero here. "
        "Write a 3-4 paragraph executive summary for a board of directors. "
        "Cover: overall compliance posture, key risks, active audits, privacy status, "
        "and business continuity readiness. Use professional tone. "
        "Highlight urgent items requiring board attention. "
        "Do NOT use markdown or bullet points. Plain prose paragraphs only."
    )
    try:
        narrative = create_message(
            [{"role": "user", "content": prompt}],
            system="You are a GRC reporting assistant writing for a board of directors. Be concise and professional.",
            max_tokens=1500,
        )
    except Exception:
        narrative = "AI narrative generation failed. Please review the metrics below."
    from core.timeutils import utcnow
    return _JSONResp({
        "stats": stats,
        "narrative": narrative,
        "generated_at": utcnow().isoformat(),
    })
