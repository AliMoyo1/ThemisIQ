"""
Launcher sub-router: Risk Register — page and CRUD APIs.
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from database import insert_returning_id
from modules.launcher._route_helpers import (
    _JSONResp, require_auth, shell_ctx, shell_templates, get_db,
)

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# CROSS-MODULE RISK REGISTER
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/risk-register", response_class=HTMLResponse)
@require_auth
async def risk_register_page(request: Request):
    """Unified risk register page."""
    ctx = shell_ctx(request, active_module="platform", active_section="risk-register")
    return shell_templates.TemplateResponse(request, "risk_register.html", ctx)


@router.get("/api/risks")
@require_auth
async def api_risks_list(request: Request):
    """List all risks — unified view of risk_register + erm_enterprise_risks."""
    db = get_db()
    try:
        module = request.query_params.get("module", "")
        status = request.query_params.get("status", "")
        level  = request.query_params.get("level", "")

        # ── Unified UNION query ────────────────────────────────────────────
        # risk_register rows tagged with register_source='platform'
        # erm_enterprise_risks rows tagged with register_source='erm'
        rr_where, rr_params = ["1=1"], []
        erm_where, erm_params = ["1=1"], []

        if module:
            if module == "erm":
                rr_where.append("0=1")           # exclude platform rows
            else:
                rr_where.append("r.source_module=%s"); rr_params.append(module)
                erm_where.append("0=1")           # exclude erm rows
        if status:
            rr_where.append("r.status=%s");    rr_params.append(status)
            erm_where.append("e.status=%s");   erm_params.append(status)
        if level:
            # platform register has risk_level text; erm has score
            score_map = {"critical": 20, "high": 12, "medium": 6, "low": 0}
            min_s = score_map.get(level, 0)
            rr_where.append("r.risk_level=%s");      rr_params.append(level)
            if level == "critical":
                erm_where.append("(e.likelihood*e.impact)>=20")
            elif level == "high":
                erm_where.append("(e.likelihood*e.impact)>=12 AND (e.likelihood*e.impact)<20")
            elif level == "medium":
                erm_where.append("(e.likelihood*e.impact)>=6 AND (e.likelihood*e.impact)<12")
            else:
                erm_where.append("(e.likelihood*e.impact)<6")

        rr_sql  = " AND ".join(rr_where)
        erm_sql = " AND ".join(erm_where)

        rr_rows = db.execute(
            f"SELECT r.id, r.title, r.description, r.source_module, "
            f"r.source_entity_type, r.source_entity_id, r.category, "
            f"r.likelihood, r.impact, r.risk_score, r.risk_level, "
            f"r.owner_id, r.treatment, r.treatment_plan, r.status, "
            f"r.review_date, r.created_by, r.created_at, "
            f"u.full_name as owner_name, cb.full_name as created_by_name, "
            f"'platform' as register_source "
            f"FROM risk_register r "
            f"LEFT JOIN users u ON r.owner_id=u.id "
            f"LEFT JOIN users cb ON r.created_by=cb.id "
            f"WHERE {rr_sql}",
            rr_params
        ).fetchall()

        erm_rows = db.execute(
            f"SELECT e.id, e.title, e.description, e.source_module, "
            f"'enterprise_risk' as source_entity_type, e.source_risk_id as source_entity_id, "
            f"e.category, e.likelihood, e.impact, "
            f"(e.likelihood*e.impact) as risk_score, "
            f"CASE WHEN (e.likelihood*e.impact)>=20 THEN 'critical' "
            f"     WHEN (e.likelihood*e.impact)>=12 THEN 'high' "
            f"     WHEN (e.likelihood*e.impact)>=6  THEN 'medium' "
            f"     ELSE 'low' END as risk_level, "
            f"e.owner_id, e.treatment, e.treatment_plan, e.status, "
            f"e.review_date, e.created_by, e.created_at, "
            f"u.full_name as owner_name, cb.full_name as created_by_name, "
            f"'erm' as register_source "
            f"FROM erm_enterprise_risks e "
            f"LEFT JOIN users u ON e.owner_id=u.id "
            f"LEFT JOIN users cb ON e.created_by=cb.id "
            f"WHERE {erm_sql}",
            erm_params
        ).fetchall()

        all_rows = [dict(r) for r in rr_rows] + [dict(r) for r in erm_rows]
        all_rows.sort(key=lambda x: (x.get("risk_score") or 0), reverse=True)
    finally:
        db.close()
    return _JSONResp(all_rows)


@router.post("/api/risks", status_code=201)
@require_auth
async def api_risk_create(request: Request):
    """Create a new risk entry."""
    data = await request.json()
    db = get_db()
    try:
        likelihood = int(data.get("likelihood", 3))
        impact = int(data.get("impact", 3))
        score = likelihood * impact
        level = "critical" if score >= 20 else "high" if score >= 12 else "medium" if score >= 6 else "low"
        rid = insert_returning_id(
            db,
            "INSERT INTO risk_register (title, description, source_module, source_entity_type, "
            "source_entity_id, category, likelihood, impact, risk_level, owner_id, treatment, "
            "treatment_plan, status, review_date, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                data.get("title", "Untitled Risk"),
                data.get("description", ""),
                data.get("source_module", ""),
                data.get("source_entity_type", ""),
                data.get("source_entity_id"),
                data.get("category", "operational"),
                likelihood, impact, level,
                data.get("owner_id"),
                data.get("treatment", "mitigate"),
                data.get("treatment_plan", ""),
                data.get("status", "open"),
                data.get("review_date"),
                request.state.user["id"],
            )
        )
        db.commit()
    finally:
        db.close()
    return _JSONResp({"id": rid, "risk_level": level, "risk_score": score}, status_code=201)


@router.get("/api/risks/stats")
@require_auth
async def api_risk_stats(request: Request):
    """Risk register statistics — unified (risk_register + erm_enterprise_risks)."""
    db = get_db()
    try:
        # Platform register
        rr_total = db.execute("SELECT COUNT(*) FROM risk_register WHERE status != 'closed'").fetchone()[0]
        rr_by_level = {r["risk_level"]: r["c"] for r in db.execute(
            "SELECT risk_level, COUNT(*) as c FROM risk_register WHERE status != 'closed' GROUP BY risk_level"
        ).fetchall()}
        rr_by_module = {(r["source_module"] or "unassigned"): r["c"] for r in db.execute(
            "SELECT source_module, COUNT(*) as c FROM risk_register WHERE status != 'closed' GROUP BY source_module"
        ).fetchall()}
        # ERM enterprise risks
        erm_total = db.execute("SELECT COUNT(*) FROM erm_enterprise_risks WHERE status != 'closed'").fetchone()[0]
        erm_by_level = {}
        for row in db.execute(
            "SELECT CASE WHEN (likelihood*impact)>=20 THEN 'critical' "
            "WHEN (likelihood*impact)>=12 THEN 'high' WHEN (likelihood*impact)>=6 THEN 'medium' "
            "ELSE 'low' END as lvl, COUNT(*) as c "
            "FROM erm_enterprise_risks WHERE status != 'closed' GROUP BY lvl"
        ).fetchall():
            erm_by_level[row["lvl"]] = row["c"]

        # Merge
        by_level = {}
        for k in ("critical", "high", "medium", "low"):
            by_level[k] = rr_by_level.get(k, 0) + erm_by_level.get(k, 0)
        by_module = dict(rr_by_module)
        by_module["erm"] = by_module.get("erm", 0) + erm_total

        heat_data = db.execute(
            "SELECT likelihood, impact, COUNT(*) as c FROM risk_register WHERE status != 'closed' GROUP BY likelihood, impact"
        ).fetchall()
    finally:
        db.close()
    return _JSONResp({
        "total": rr_total + erm_total,
        "by_level": by_level,
        "by_module": by_module,
        "heat_map": [{"likelihood": r["likelihood"], "impact": r["impact"], "count": r["c"]} for r in heat_data],
    })


@router.get("/api/risks/{rid}")
@require_auth
async def api_risk_get(request: Request, rid: int):
    """Get a single risk with full details."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT r.*, u.full_name as owner_name FROM risk_register r "
            "LEFT JOIN users u ON r.owner_id = u.id WHERE r.id = %s", (rid,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Risk not found")
    finally:
        db.close()
    return _JSONResp(dict(row))


@router.put("/api/risks/{rid}")
@require_auth
async def api_risk_update(request: Request, rid: int):
    """Update a risk entry."""
    data = await request.json()
    db = get_db()
    try:
        allowed = ["title", "description", "category", "likelihood", "impact",
                   "owner_id", "treatment", "treatment_plan", "status", "review_date",
                   "source_module", "source_entity_type", "source_entity_id"]
        sets = []
        vals = []
        for k in allowed:
            if k in data:
                sets.append(f"{k} = %s")
                vals.append(data[k])
        # Recalculate risk_level if likelihood or impact changed
        if "likelihood" in data or "impact" in data:
            current = db.execute("SELECT likelihood, impact FROM risk_register WHERE id = %s", (rid,)).fetchone()
            l = int(data.get("likelihood", current["likelihood"]))
            i = int(data.get("impact", current["impact"]))
            score = l * i
            level = "critical" if score >= 20 else "high" if score >= 12 else "medium" if score >= 6 else "low"
            sets.append("risk_level = %s")
            vals.append(level)
        if sets:
            sets.append("updated_at = CURRENT_TIMESTAMP")
            vals.append(rid)
            db.execute(f"UPDATE risk_register SET {', '.join(sets)} WHERE id = %s", vals)
            db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/risks/{rid}")
@require_auth
async def api_risk_delete(request: Request, rid: int):
    """Close/archive a risk."""
    db = get_db()
    try:
        db.execute("UPDATE risk_register SET status = 'closed', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (rid,))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})
