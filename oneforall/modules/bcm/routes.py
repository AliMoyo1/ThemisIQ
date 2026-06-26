"""
BCM module - Business Continuity Management.
All routes serve JSON APIs at /bcm/api/* except the SPA index at GET /bcm/.
"""
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from core.middleware import require_module, require_capability, check_ai_rate_limit, record_ai_call
from core.shell_context import shell_ctx
from database import get_db
from core.events import (
    emit, BCM_INCIDENT_DECLARED, BCM_INCIDENT_RESOLVED,
    BCM_RISK_ESCALATED, BCM_PLAN_APPROVED,
    BCM_PLAN_ACTIVATED, BCM_PLAN_DEACTIVATED,
)

router = APIRouter(prefix="/bcm", tags=["bcm"])
templates = Jinja2Templates(directory=["modules/bcm/templates", "templates"])

from modules.bcm import data_service as ds

def _uid(request: Request) -> int:
    return request.state.user["id"]

def _uname(request: Request) -> str:
    return request.state.user.get("full_name", "Unknown")


async def _json_body(request: Request) -> dict:
    try:
        body = await _json_body(request)
    except Exception:
        return {}
    from core.sanitize import sanitize_dict
    return sanitize_dict(body)


@router.get("/", response_class=HTMLResponse)
@require_module("bcm")
async def bcm_spa(request: Request):
    user = request.state.user
    return templates.TemplateResponse(request, "index.html", {
        "user": user,
        **shell_ctx(request, active_module="bcm"),
    })


# SPA catch-all — lets browser refresh on /bcm/bia etc. work
_SPA_PAGES = {
    "bia","plans","incidents","exercises","risks","dependencies",
    "training","reports","chat",
    "documents","compliance","vendors",       # backend already existed
    "comms","contacts","scenarios",           # BCM-14/15/16
}

@router.get("/{page}", response_class=HTMLResponse)
@require_module("bcm")
async def bcm_spa_page(request: Request, page: str):
    if page.startswith("api") or page not in _SPA_PAGES:
        raise HTTPException(404)
    return await bcm_spa(request)


@router.get("/api/dashboard")
@require_capability("module.bcm.access")
async def api_dashboard(request: Request):
    return JSONResponse(ds.get_dashboard_stats())


@router.get("/api/bia")
@require_capability("module.bcm.access")
async def api_bia_list(request: Request):
    return JSONResponse(ds.list_bia())


@router.get("/api/bia/{bia_id}")
@require_capability("module.bcm.access")
async def api_bia_detail(request: Request, bia_id: int):
    rec = ds.get_bia(bia_id)
    if not rec:
        raise HTTPException(404, "BIA record not found")
    rec["plan_links"] = ds.list_bia_plan_links(bia_id=bia_id)
    return JSONResponse(rec)


@router.post("/api/bia")
@require_capability("bcm.bia.manage")
async def api_bia_create(request: Request):
    body = await _json_body(request)
    bid = ds.create_bia(body)
    if body.get("plan_ids"):
        for pid in body["plan_ids"]:
            ds.create_bia_plan_link({"bia_id": bid, "plan_id": pid, "created_by": _uname(request)})
    return JSONResponse({"id": bid}, status_code=201)


@router.put("/api/bia/{bia_id}")
@require_capability("bcm.bia.manage")
async def api_bia_update(request: Request, bia_id: int):
    body = await _json_body(request)
    ds.update_bia(bia_id, body)
    if "plan_ids" in body:
        existing = {l["plan_id"] for l in ds.list_bia_plan_links(bia_id=bia_id)}
        wanted = set(body["plan_ids"])
        for pid in wanted - existing:
            ds.create_bia_plan_link({"bia_id": bia_id, "plan_id": pid, "created_by": _uname(request)})
        for link in ds.list_bia_plan_links(bia_id=bia_id):
            if link["plan_id"] not in wanted:
                ds.delete_bia_plan_link(link["id"])
    return JSONResponse({"ok": True})


@router.delete("/api/bia/{bia_id}")
@require_capability("bcm.bia.manage")
async def api_bia_delete(request: Request, bia_id: int):
    ds.delete_bia(bia_id)
    return JSONResponse({"ok": True})


@router.post("/api/bia/{bia_id}/calculate")
@require_capability("module.bcm.access")
async def api_bia_calculate(request: Request, bia_id: int):
    """BCM-12/13: Calculate criticality + MTPD guidance from BIA data."""
    result = ds.calculate_bia_metrics(bia_id)
    if not result:
        raise HTTPException(404, "BIA record not found")
    return JSONResponse(result)


# ── Crisis Communication Templates (BCM-14) ─────────────────────────────────

@router.get("/api/comms")
@require_capability("module.bcm.access")
async def api_comms_list(request: Request):
    category = request.query_params.get("category")
    return JSONResponse(ds.list_comm_templates(category=category))


@router.get("/api/comms/{tid}")
@require_capability("module.bcm.access")
async def api_comms_detail(request: Request, tid: int):
    t = ds.get_comm_template(tid)
    if not t:
        raise HTTPException(404)
    return JSONResponse(t)


@router.post("/api/comms")
@require_capability("bcm.plan.manage")
async def api_comms_create(request: Request):
    body = await _json_body(request)
    body["created_by"] = _uname(request)
    tid = ds.create_comm_template(body)
    return JSONResponse({"id": tid}, status_code=201)


@router.put("/api/comms/{tid}")
@require_capability("bcm.plan.manage")
async def api_comms_update(request: Request, tid: int):
    body = await _json_body(request)
    ds.update_comm_template(tid, body)
    return JSONResponse({"ok": True})


@router.delete("/api/comms/{tid}")
@require_capability("bcm.plan.manage")
async def api_comms_delete(request: Request, tid: int):
    ds.delete_comm_template(tid)
    return JSONResponse({"ok": True})


# ── Emergency Contact Tree (BCM-15) ─────────────────────────────────────────

@router.get("/api/contacts")
@require_capability("module.bcm.access")
async def api_contacts_list(request: Request):
    return JSONResponse(ds.list_contact_nodes())


@router.get("/api/contacts/tree")
@require_capability("module.bcm.access")
async def api_contacts_tree(request: Request):
    return JSONResponse(ds.get_contact_tree())


@router.get("/api/contacts/{nid}")
@require_capability("module.bcm.access")
async def api_contacts_detail(request: Request, nid: int):
    n = ds.get_contact_node(nid)
    if not n:
        raise HTTPException(404)
    return JSONResponse(n)


@router.post("/api/contacts")
@require_capability("bcm.plan.manage")
async def api_contacts_create(request: Request):
    body = await _json_body(request)
    nid = ds.create_contact_node(body)
    return JSONResponse({"id": nid}, status_code=201)


@router.put("/api/contacts/{nid}")
@require_capability("bcm.plan.manage")
async def api_contacts_update(request: Request, nid: int):
    body = await _json_body(request)
    ds.update_contact_node(nid, body)
    return JSONResponse({"ok": True})


@router.delete("/api/contacts/{nid}")
@require_capability("bcm.plan.manage")
async def api_contacts_delete(request: Request, nid: int):
    ds.delete_contact_node(nid)
    return JSONResponse({"ok": True})


# ── Exercise Scenario Library (BCM-16) ──────────────────────────────────────

@router.get("/api/scenarios")
@require_capability("module.bcm.access")
async def api_scenarios_list(request: Request):
    category = request.query_params.get("category")
    return JSONResponse(ds.list_scenarios(category=category))


@router.get("/api/scenarios/{sid}")
@require_capability("module.bcm.access")
async def api_scenarios_detail(request: Request, sid: int):
    s = ds.get_scenario(sid)
    if not s:
        raise HTTPException(404)
    return JSONResponse(s)


@router.post("/api/scenarios")
@require_capability("bcm.exercise.manage")
async def api_scenarios_create(request: Request):
    body = await _json_body(request)
    sid = ds.create_scenario(body)
    return JSONResponse({"id": sid}, status_code=201)


@router.delete("/api/scenarios/{sid}")
@require_capability("bcm.exercise.manage")
async def api_scenarios_delete(request: Request, sid: int):
    ds.delete_scenario(sid)
    return JSONResponse({"ok": True})


@router.post("/api/scenarios/{sid}/use")
@require_capability("bcm.exercise.manage")
async def api_scenarios_use(request: Request, sid: int):
    """Spawn an exercise from a scenario template."""
    scenario = ds.get_scenario(sid)
    if not scenario:
        raise HTTPException(404)
    body = await _json_body(request)
    exercise_data = {
        "title": body.get("title") or scenario["title"] + " Exercise",
        "type": "Tabletop",
        "scenario": scenario["description"],
        "objectives": scenario["objectives"],
        "scheduled_date": body.get("scheduled_date"),
        "duration_minutes": scenario.get("estimated_duration_minutes", 120),
        "facilitator": body.get("facilitator", _uname(request)),
        "participants": body.get("participants", ""),
        "status": "planned",
    }
    eid = ds.create_exercise(exercise_data)
    return JSONResponse({"id": eid, "exercise_id": eid}, status_code=201)


@router.get("/api/risks")
@require_capability("module.bcm.access")
async def api_risks_list(request: Request):
    return JSONResponse(ds.list_risks())


@router.get("/api/risks/{risk_id}")
@require_capability("module.bcm.access")
async def api_risk_detail(request: Request, risk_id: int):
    r = ds.get_risk(risk_id)
    if not r:
        raise HTTPException(404)
    return JSONResponse(r)


@router.post("/api/risks")
@require_capability("bcm.risk.manage")
async def api_risk_create(request: Request):
    body = await _json_body(request)
    rid = ds.create_risk(body)

    # Emit risk escalated if severity is high/critical
    severity = (body.get("severity") or body.get("risk_level") or "").lower()
    if severity in ("high", "critical"):
        emit(
            BCM_RISK_ESCALATED,
            source_module="bcm",
            entity_type="risk",
            entity_id=rid,
            payload={
                "title": body.get("title", ""),
                "description": body.get("description", ""),
                "severity": severity,
                "category": body.get("category", ""),
            },
            user_id=_uid(request),
        )
    return JSONResponse({"id": rid}, status_code=201)


@router.put("/api/risks/{risk_id}")
@require_capability("bcm.risk.manage")
async def api_risk_update(request: Request, risk_id: int):
    body = await _json_body(request)
    ds.update_risk(risk_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/risks/{risk_id}")
@require_capability("bcm.risk.manage")
async def api_risk_delete(request: Request, risk_id: int):
    ds.delete_risk(risk_id)
    return JSONResponse({"ok": True})


@router.get("/api/plans")
@require_capability("module.bcm.access")
async def api_plans_list(request: Request):
    return JSONResponse(ds.list_plans())


@router.get("/api/plans/active")
@require_capability("module.bcm.access")
async def api_active_plans(request: Request):
    """Return all currently activated plans."""
    return JSONResponse(ds.list_active_plans())


@router.get("/api/plans/{plan_id}")
@require_capability("module.bcm.access")
async def api_plan_detail(request: Request, plan_id: int):
    p = ds.get_plan(plan_id)
    if not p:
        raise HTTPException(404)
    p["bia_links"] = ds.list_bia_plan_links(plan_id=plan_id)
    p["reviews"] = ds.list_plan_reviews(plan_id)
    # Attach linked evidence from vault
    db = get_db()
    try:
        ev = [dict(r) for r in db.execute(
            "SELECT e.id, e.title, e.category, e.status, e.created_at "
            "FROM evidence_items e "
            "JOIN evidence_links el ON e.id=el.evidence_id "
            "WHERE el.module='bcm' AND el.entity_type='plan' AND el.entity_id=%s "
            "AND e.status != 'archived' ORDER BY e.created_at DESC",
            (plan_id,),
        ).fetchall()]
    finally:
        db.close()
    p["evidence"] = ev
    p["evidence_count"] = len(ev)
    return JSONResponse(p)


@router.post("/api/plans")
@require_capability("bcm.plan.manage")
async def api_plan_create(request: Request):
    body = await _json_body(request)
    pid = ds.create_plan(body)
    if body.get("bia_ids"):
        for bid in body["bia_ids"]:
            ds.create_bia_plan_link({"bia_id": bid, "plan_id": pid, "created_by": _uname(request)})
    return JSONResponse({"id": pid}, status_code=201)


@router.put("/api/plans/{plan_id}")
@require_capability("bcm.plan.manage")
async def api_plan_update(request: Request, plan_id: int):
    body = await _json_body(request)
    ds.update_plan(plan_id, body)

    # Emit plan approved event when status changes to approved
    new_status = (body.get("status") or "").lower()
    if new_status == "approved":
        plan = ds.get_plan(plan_id)
        emit(
            BCM_PLAN_APPROVED,
            source_module="bcm",
            entity_type="plan",
            entity_id=plan_id,
            payload={
                "name": plan.get("name", "") if plan else "",
                "plan_type": plan.get("plan_type", "") if plan else "",
            },
            user_id=_uid(request),
        )
    return JSONResponse({"ok": True})


@router.delete("/api/plans/{plan_id}")
@require_capability("bcm.plan.manage")
async def api_plan_delete(request: Request, plan_id: int):
    ds.delete_plan(plan_id)
    return JSONResponse({"ok": True})


@router.get("/api/plans/{plan_id}/reviews")
@require_capability("module.bcm.access")
async def api_plan_reviews(request: Request, plan_id: int):
    return JSONResponse(ds.list_plan_reviews(plan_id))


@router.post("/api/plans/{plan_id}/activate")
@require_capability("bcm.plan.manage")
async def api_plan_activate(request: Request, plan_id: int):
    """Activate a continuity plan (BCM-17)."""
    plan = ds.get_plan(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    body = await _json_body(request)
    reason = body.get("reason", "")
    incident_id = body.get("incident_id")

    ds.activate_plan(
        plan_id=plan_id,
        activated_by=_uname(request),
        activated_by_id=_uid(request),
        reason=reason,
        incident_id=incident_id,
    )

    emit(
        BCM_PLAN_ACTIVATED,
        source_module="bcm",
        entity_type="plan",
        entity_id=plan_id,
        payload={
            "title": plan.get("title", ""),
            "reason": reason,
            "incident_id": incident_id,
            "activated_by": _uname(request),
        },
        user_id=_uid(request),
    )
    return JSONResponse({"ok": True, "plan_id": plan_id, "activated_by": _uname(request)})


@router.post("/api/plans/{plan_id}/deactivate")
@require_capability("bcm.plan.manage")
async def api_plan_deactivate(request: Request, plan_id: int):
    """Stand down an activated plan."""
    plan = ds.get_plan(plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    if not plan.get("is_active_plan"):
        raise HTTPException(400, "Plan is not currently active")
    body = await _json_body(request)
    reason = body.get("reason", "")

    ds.deactivate_plan(
        plan_id=plan_id,
        deactivated_by=_uname(request),
        deactivated_by_id=_uid(request),
        reason=reason,
    )

    emit(
        BCM_PLAN_DEACTIVATED,
        source_module="bcm",
        entity_type="plan",
        entity_id=plan_id,
        payload={
            "title": plan.get("title", ""),
            "reason": reason,
            "deactivated_by": _uname(request),
        },
        user_id=_uid(request),
    )
    return JSONResponse({"ok": True, "plan_id": plan_id})


@router.get("/api/plans/{plan_id}/activations")
@require_capability("module.bcm.access")
async def api_plan_activations(request: Request, plan_id: int):
    """Return the activation history for a plan."""
    return JSONResponse(ds.list_plan_activations(plan_id))


@router.post("/api/plans/{plan_id}/reviews")
@require_capability("bcm.plan.manage")
async def api_plan_review_create(request: Request, plan_id: int):
    from modules.bcm import ai_service as ai
    plan = ds.get_plan(plan_id)
    if not plan:
        raise HTTPException(404)
    try:
        result = ai.review_plan(plan)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    result["plan_id"] = plan_id
    result["reviewer_id"] = _uid(request)
    result["reviewer_name"] = _uname(request)
    result["provider"] = "anthropic"
    rid = ds.create_plan_review(result)
    result["id"] = rid
    return JSONResponse(result, status_code=201)


@router.get("/api/incidents")
@require_capability("module.bcm.access")
async def api_incidents_list(request: Request):
    status = request.query_params.get("status")
    return JSONResponse(ds.list_incidents(status=status))


@router.get("/api/incidents/{inc_id}")
@require_capability("module.bcm.access")
async def api_incident_detail(request: Request, inc_id: int):
    inc = ds.get_incident(inc_id)
    if not inc:
        raise HTTPException(404)
    inc["updates"] = ds.list_incident_updates(inc_id)
    inc["actions"] = ds.list_incident_actions(inc_id)
    inc["decisions"] = ds.list_incident_decisions(inc_id)
    inc["stakeholders"] = ds.list_incident_stakeholders(inc_id)
    inc["plan_links"] = ds.list_incident_plan_links(inc_id)
    # Attach linked evidence from vault
    db = get_db()
    try:
        ev = [dict(r) for r in db.execute(
            "SELECT e.id, e.title, e.category, e.status, e.created_at "
            "FROM evidence_items e "
            "JOIN evidence_links el ON e.id=el.evidence_id "
            "WHERE el.module='bcm' AND el.entity_type='incident' AND el.entity_id=%s "
            "AND e.status != 'archived' ORDER BY e.created_at DESC",
            (inc_id,),
        ).fetchall()]
    finally:
        db.close()
    inc["evidence"] = ev
    inc["evidence_count"] = len(ev)
    return JSONResponse(inc)


@router.post("/api/incidents")
@require_capability("bcm.incident.manage")
async def api_incident_create(request: Request):
    body = await _json_body(request)
    iid = ds.create_incident(body)

    # Emit incident declared event
    emit(
        BCM_INCIDENT_DECLARED,
        source_module="bcm",
        entity_type="incident",
        entity_id=iid,
        payload={
            "title": body.get("title", ""),
            "severity": body.get("severity", "medium"),
            "commander": body.get("commander", ""),
            "affected_systems": body.get("affected_systems", ""),
        },
        user_id=_uid(request),
    )
    return JSONResponse({"id": iid}, status_code=201)


@router.put("/api/incidents/{inc_id}")
@require_capability("bcm.incident.manage")
async def api_incident_update(request: Request, inc_id: int):
    body = await _json_body(request)
    ds.update_incident(inc_id, body)

    # Emit incident resolved event when status changes to resolved
    new_status = (body.get("status") or "").lower()
    if new_status == "resolved":
        inc = ds.get_incident(inc_id)
        emit(
            BCM_INCIDENT_RESOLVED,
            source_module="bcm",
            entity_type="incident",
            entity_id=inc_id,
            payload={
                "title": inc.get("title", "") if inc else "",
                "severity": inc.get("severity", "") if inc else "",
                "resolved_at": inc.get("resolved_at", "") if inc else "",
            },
            user_id=_uid(request),
        )
    return JSONResponse({"ok": True})


@router.delete("/api/incidents/{inc_id}")
@require_capability("bcm.incident.manage")
async def api_incident_delete(request: Request, inc_id: int):
    ds.delete_incident(inc_id)
    return JSONResponse({"ok": True})


@router.get("/api/incidents/{inc_id}/updates")
@require_capability("module.bcm.access")
async def api_incident_updates(request: Request, inc_id: int):
    return JSONResponse(ds.list_incident_updates(inc_id))


@router.post("/api/incidents/{inc_id}/updates")
@require_capability("bcm.incident.manage")
async def api_incident_update_create(request: Request, inc_id: int):
    body = await _json_body(request)
    uid = ds.create_incident_update(inc_id, _uname(request), body.get("note", ""))
    return JSONResponse({"id": uid}, status_code=201)


@router.get("/api/incidents/{inc_id}/actions")
@require_capability("module.bcm.access")
async def api_incident_actions_list(request: Request, inc_id: int):
    return JSONResponse(ds.list_incident_actions(inc_id))


@router.post("/api/incidents/{inc_id}/actions")
@require_capability("bcm.incident.manage")
async def api_incident_action_create(request: Request, inc_id: int):
    body = await _json_body(request)
    body["created_by"] = _uname(request)
    aid = ds.create_incident_action(inc_id, body)
    return JSONResponse({"id": aid}, status_code=201)


@router.put("/api/incidents/{inc_id}/actions/{action_id}")
@require_capability("bcm.incident.manage")
async def api_incident_action_update(request: Request, inc_id: int, action_id: int):
    body = await _json_body(request)
    ds.update_incident_action(action_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/incidents/{inc_id}/actions/{action_id}")
@require_capability("bcm.incident.manage")
async def api_incident_action_delete(request: Request, inc_id: int, action_id: int):
    ds.delete_incident_action(action_id)
    return JSONResponse({"ok": True})


@router.get("/api/incidents/{inc_id}/decisions")
@require_capability("module.bcm.access")
async def api_incident_decisions_list(request: Request, inc_id: int):
    return JSONResponse(ds.list_incident_decisions(inc_id))


@router.post("/api/incidents/{inc_id}/decisions")
@require_capability("bcm.incident.manage")
async def api_incident_decision_create(request: Request, inc_id: int):
    body = await _json_body(request)
    body["decided_by"] = body.get("decided_by", _uname(request))
    did = ds.create_incident_decision(inc_id, body)
    return JSONResponse({"id": did}, status_code=201)


@router.get("/api/incidents/{inc_id}/stakeholders")
@require_capability("module.bcm.access")
async def api_incident_stakeholders_list(request: Request, inc_id: int):
    return JSONResponse(ds.list_incident_stakeholders(inc_id))


@router.post("/api/incidents/{inc_id}/stakeholders")
@require_capability("bcm.incident.manage")
async def api_incident_stakeholder_create(request: Request, inc_id: int):
    body = await _json_body(request)
    sid = ds.create_incident_stakeholder(inc_id, body)
    return JSONResponse({"id": sid}, status_code=201)


@router.put("/api/incidents/{inc_id}/stakeholders/{sh_id}")
@require_capability("bcm.incident.manage")
async def api_incident_stakeholder_update(request: Request, inc_id: int, sh_id: int):
    body = await _json_body(request)
    ds.update_incident_stakeholder(sh_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/incidents/{inc_id}/stakeholders/{sh_id}")
@require_capability("bcm.incident.manage")
async def api_incident_stakeholder_delete(request: Request, inc_id: int, sh_id: int):
    ds.delete_incident_stakeholder(sh_id)
    return JSONResponse({"ok": True})


@router.get("/api/incidents/{inc_id}/plan-links")
@require_capability("module.bcm.access")
async def api_incident_plan_links(request: Request, inc_id: int):
    return JSONResponse(ds.list_incident_plan_links(inc_id))


@router.post("/api/incidents/{inc_id}/plan-links")
@require_capability("bcm.incident.manage")
async def api_incident_plan_link_create(request: Request, inc_id: int):
    body = await _json_body(request)
    lid = ds.link_incident_plan(inc_id, body.get("plan_id"), _uname(request))
    return JSONResponse({"id": lid}, status_code=201)


@router.delete("/api/incidents/{inc_id}/plan-links/{link_id}")
@require_capability("bcm.incident.manage")
async def api_incident_plan_link_delete(request: Request, inc_id: int, link_id: int):
    ds.unlink_incident_plan(link_id)
    return JSONResponse({"ok": True})


@router.post("/api/incidents/{inc_id}/ai-suggest")
@require_capability("bcm.ai.use")
async def api_incident_ai_suggest(request: Request, inc_id: int):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    from modules.bcm import ai_service as ai
    inc = ds.get_incident(inc_id)
    if not inc:
        raise HTTPException(404)
    inc["updates"] = ds.list_incident_updates(inc_id)
    inc["actions"] = ds.list_incident_actions(inc_id)
    try:
        suggestions = ai.suggest_incident_actions(inc)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return JSONResponse({"suggestions": suggestions})


@router.get("/api/exercises")
@require_capability("module.bcm.access")
async def api_exercises_list(request: Request):
    return JSONResponse(ds.list_exercises())


@router.get("/api/exercises/{ex_id}")
@require_capability("module.bcm.access")
async def api_exercise_detail(request: Request, ex_id: int):
    ex = ds.get_exercise(ex_id)
    if not ex:
        raise HTTPException(404)
    return JSONResponse(ex)


@router.post("/api/exercises")
@require_capability("bcm.exercise.manage")
async def api_exercise_create(request: Request):
    body = await _json_body(request)
    eid = ds.create_exercise(body)
    return JSONResponse({"id": eid}, status_code=201)


@router.put("/api/exercises/{ex_id}")
@require_capability("bcm.exercise.manage")
async def api_exercise_update(request: Request, ex_id: int):
    body = await _json_body(request)
    ds.update_exercise(ex_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/exercises/{ex_id}")
@require_capability("bcm.exercise.manage")
async def api_exercise_delete(request: Request, ex_id: int):
    ds.delete_exercise(ex_id)
    return JSONResponse({"ok": True})


@router.get("/api/vendors")
@require_capability("module.bcm.access")
async def api_vendors_list(request: Request):
    return JSONResponse(ds.list_vendors())


@router.get("/api/vendors/{vid}")
@require_capability("module.bcm.access")
async def api_vendor_detail(request: Request, vid: int):
    v = ds.get_vendor(vid)
    if not v:
        raise HTTPException(404)
    v["assessments"] = ds.list_vendor_assessments(vid)
    return JSONResponse(v)


@router.post("/api/vendors")
@require_capability("bcm.vendor.manage")
async def api_vendor_create(request: Request):
    body = await _json_body(request)
    vid = ds.create_vendor(body)
    vendor = ds.get_vendor(vid)
    emit("vendor.created", source_module="bcm", entity_type="vendor", entity_id=vid,
         payload={"name": (vendor or {}).get("name", ""), "canonical_id": (vendor or {}).get("canonical_id"),
                  "source_module": "bcm"},
         user_id=request.state.user["id"])
    return JSONResponse({"id": vid}, status_code=201)


@router.put("/api/vendors/{vid}")
@require_capability("bcm.vendor.manage")
async def api_vendor_update(request: Request, vid: int):
    body = await _json_body(request)
    ds.update_vendor(vid, body)
    return JSONResponse({"ok": True})


@router.delete("/api/vendors/{vid}")
@require_capability("bcm.vendor.manage")
async def api_vendor_delete(request: Request, vid: int):
    ds.delete_vendor(vid)
    return JSONResponse({"ok": True})


@router.get("/api/vendors/{vid}/cross-module")
@require_capability("module.bcm.access")
async def api_vendor_cross_module(request: Request, vid: int):
    v = ds.get_vendor(vid)
    if not v or not v.get("canonical_id"):
        return JSONResponse({"modules": {}, "flags": [], "canonical_id": None})
    from core.vendor_link import get_cross_module_profile
    db = get_db()
    try:
        return JSONResponse(get_cross_module_profile(db, v["canonical_id"]))
    finally:
        db.close()


@router.post("/api/vendors/{vid}/assessments")
@require_capability("bcm.vendor.manage")
async def api_vendor_assessment_create(request: Request, vid: int):
    body = await _json_body(request)
    aid = ds.create_vendor_assessment(vid, body)
    return JSONResponse({"id": aid}, status_code=201)


@router.get("/api/compliance")
@require_capability("module.bcm.access")
async def api_compliance_list(request: Request):
    fw = request.query_params.get("framework")
    return JSONResponse(ds.list_compliance_controls(framework=fw))


@router.get("/api/compliance/{cid}")
@require_capability("module.bcm.access")
async def api_compliance_detail(request: Request, cid: int):
    c = ds.get_compliance_control(cid)
    if not c:
        raise HTTPException(404)
    c["evidence"] = ds.list_compliance_evidence(cid)
    return JSONResponse(c)


@router.post("/api/compliance")
@require_capability("bcm.compliance.manage")
async def api_compliance_create(request: Request):
    body = await _json_body(request)
    cid = ds.create_compliance_control(body)
    return JSONResponse({"id": cid}, status_code=201)


@router.put("/api/compliance/{cid}")
@require_capability("bcm.compliance.manage")
async def api_compliance_update(request: Request, cid: int):
    body = await _json_body(request)
    ds.update_compliance_control(cid, body)
    return JSONResponse({"ok": True})


@router.delete("/api/compliance/{cid}")
@require_capability("bcm.compliance.manage")
async def api_compliance_delete(request: Request, cid: int):
    ds.delete_compliance_control(cid)
    return JSONResponse({"ok": True})


@router.post("/api/compliance/{cid}/evidence")
@require_capability("bcm.compliance.manage")
async def api_compliance_evidence_create(request: Request, cid: int):
    body = await _json_body(request)
    body["uploaded_by"] = _uname(request)
    eid = ds.create_compliance_evidence(cid, body)
    # Mirror to central Evidence Vault so BCM evidence is visible cross-module
    try:
        ds.sync_bcm_compliance_evidence_to_vault(eid, cid, _uid(request))
    except Exception:
        pass  # Vault sync is non-critical; don't fail the primary operation
    return JSONResponse({"id": eid}, status_code=201)


@router.delete("/api/compliance/{cid}/evidence/{eid}")
@require_capability("bcm.compliance.manage")
async def api_compliance_evidence_delete(request: Request, cid: int, eid: int):
    ds.delete_compliance_evidence(eid)
    return JSONResponse({"ok": True})


@router.get("/api/training")
@require_capability("module.bcm.access")
async def api_training_list(request: Request):
    return JSONResponse(ds.list_training_modules())


@router.get("/api/training/attestations/all")
@require_capability("bcm.training.manage")
async def api_attestation_log(request: Request):
    return JSONResponse(ds.list_attestations())


@router.get("/api/training/{mid}")
@require_capability("module.bcm.access")
async def api_training_detail(request: Request, mid: int):
    m = ds.get_training_module(mid)
    if not m:
        raise HTTPException(404)
    m["attestations"] = ds.list_attestations(module_id=mid)
    return JSONResponse(m)


@router.post("/api/training")
@require_capability("bcm.training.manage")
async def api_training_create(request: Request):
    body = await _json_body(request)
    mid = ds.create_training_module(body)
    return JSONResponse({"id": mid}, status_code=201)


@router.put("/api/training/{mid}")
@require_capability("bcm.training.manage")
async def api_training_update(request: Request, mid: int):
    body = await _json_body(request)
    ds.update_training_module(mid, body)
    return JSONResponse({"ok": True})


@router.delete("/api/training/{mid}")
@require_capability("bcm.training.manage")
async def api_training_delete(request: Request, mid: int):
    ds.delete_training_module(mid)
    return JSONResponse({"ok": True})


@router.post("/api/training/{mid}/attest")
@require_capability("module.bcm.access")
async def api_training_attest(request: Request, mid: int):
    body = await _json_body(request)
    user = request.state.user
    data = {
        "module_id": mid,
        "user_id": user["id"],
        "user_name": user.get("full_name"),
        "user_email": user.get("email"),
        "signature": body.get("signature"),
        "score": body.get("score"),
        "ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "expires_at": body.get("expires_at"),
    }
    aid = ds.create_attestation(data)
    return JSONResponse({"id": aid}, status_code=201)


@router.get("/api/documents")
@require_capability("module.bcm.access")
async def api_documents_list(request: Request):
    return JSONResponse(ds.list_documents())


@router.get("/api/documents/{doc_id}")
@require_capability("module.bcm.access")
async def api_document_detail(request: Request, doc_id: int):
    d = ds.get_document(doc_id)
    if not d:
        raise HTTPException(404)
    d["chunks"] = ds.get_chunks(doc_id=doc_id)
    return JSONResponse(d)


@router.post("/api/documents")
@require_capability("bcm.document.manage")
async def api_document_create(request: Request):
    body = await _json_body(request)
    body["uploaded_by"] = _uname(request)
    did = ds.create_document(body)
    if body.get("content"):
        from modules.bcm import ai_service as ai
        chunks = ai.chunk_text(body["content"])
        ds.save_chunks(did, chunks)
    return JSONResponse({"id": did}, status_code=201)


@router.post("/api/documents/{doc_id}/reindex")
@require_capability("bcm.document.manage")
async def api_document_reindex(request: Request, doc_id: int):
    doc = ds.get_document(doc_id)
    if not doc or not doc.get("content"):
        raise HTTPException(400, "No content to index")
    from modules.bcm import ai_service as ai
    chunks = ai.chunk_text(doc["content"])
    ds.save_chunks(doc_id, chunks)
    return JSONResponse({"chunk_count": len(chunks)})


@router.delete("/api/documents/{doc_id}")
@require_capability("bcm.document.manage")
async def api_document_delete(request: Request, doc_id: int):
    ds.delete_document(doc_id)
    return JSONResponse({"ok": True})


@router.post("/api/documents/ask")
@require_capability("bcm.ai.use")
async def api_document_ask(request: Request):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    from modules.bcm import ai_service as ai
    body = await _json_body(request)
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(400, "Question required")
    try:
        answer, cited_ids = ai.rag_ask(question)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    ds.save_document_query(_uid(request), question, answer,
                           ",".join(str(i) for i in cited_ids), "anthropic")
    return JSONResponse({"answer": answer, "cited_chunk_ids": cited_ids})


@router.get("/api/dependencies/graph")
@require_capability("module.bcm.access")
async def api_dependency_graph(request: Request):
    return JSONResponse(ds.get_dependency_graph())


@router.get("/api/dependencies/nodes")
@require_capability("module.bcm.access")
async def api_dependency_nodes_list(request: Request):
    return JSONResponse(ds.list_dependency_nodes())


@router.get("/api/dependencies/nodes/{nid}")
@require_capability("module.bcm.access")
async def api_dependency_node_detail(request: Request, nid: int):
    n = ds.get_dependency_node(nid)
    if not n:
        raise HTTPException(404)
    return JSONResponse(n)


@router.post("/api/dependencies/nodes")
@require_capability("bcm.dependency.manage")
async def api_dependency_node_create(request: Request):
    body = await _json_body(request)
    nid = ds.create_dependency_node(body)
    return JSONResponse({"id": nid}, status_code=201)


@router.put("/api/dependencies/nodes/{nid}")
@require_capability("bcm.dependency.manage")
async def api_dependency_node_update(request: Request, nid: int):
    body = await _json_body(request)
    ds.update_dependency_node(nid, body)
    return JSONResponse({"ok": True})


@router.delete("/api/dependencies/nodes/{nid}")
@require_capability("bcm.dependency.manage")
async def api_dependency_node_delete(request: Request, nid: int):
    ds.delete_dependency_node(nid)
    return JSONResponse({"ok": True})


@router.get("/api/dependencies/edges")
@require_capability("module.bcm.access")
async def api_dependency_edges_list(request: Request):
    source = request.query_params.get("source_id")
    return JSONResponse(ds.list_dependency_edges(source_id=int(source) if source else None))


@router.post("/api/dependencies/edges")
@require_capability("bcm.dependency.manage")
async def api_dependency_edge_create(request: Request):
    body = await _json_body(request)
    eid = ds.create_dependency_edge(body)
    return JSONResponse({"id": eid}, status_code=201)


@router.delete("/api/dependencies/edges/{eid}")
@require_capability("bcm.dependency.manage")
async def api_dependency_edge_delete(request: Request, eid: int):
    ds.delete_dependency_edge(eid)
    return JSONResponse({"ok": True})


@router.get("/api/dependencies/impact/{nid}")
@require_capability("module.bcm.access")
async def api_dependency_impact(request: Request, nid: int):
    chain = ds.get_impact_chain(nid)
    return JSONResponse({"node_id": nid, "impacted": chain})


@router.get("/api/coverage")
@require_capability("module.bcm.access")
async def api_coverage(request: Request):
    summary = ds.get_coverage_summary()
    bia_list = ds.list_bia()
    for b in bia_list:
        b["plan_links"] = ds.list_bia_plan_links(bia_id=b["id"])
    summary["bia_records"] = bia_list
    return JSONResponse(summary)


@router.post("/api/coverage/links")
@require_capability("bcm.bia.manage")
async def api_coverage_link_create(request: Request):
    body = await _json_body(request)
    body["created_by"] = _uname(request)
    lid = ds.create_bia_plan_link(body)
    return JSONResponse({"id": lid}, status_code=201)


@router.delete("/api/coverage/links/{link_id}")
@require_capability("bcm.bia.manage")
async def api_coverage_link_delete(request: Request, link_id: int):
    ds.delete_bia_plan_link(link_id)
    return JSONResponse({"ok": True})


@router.get("/api/chat")
@require_capability("module.bcm.access")
async def api_chat_history(request: Request):
    msgs = ds.list_chat_messages(_uid(request))
    msgs.reverse()
    return JSONResponse(msgs)


@router.post("/api/chat")
@require_capability("bcm.ai.use")
async def api_chat_send(request: Request):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    from modules.bcm import ai_service as ai
    body = await _json_body(request)
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(400, "Message required")
    uid = _uid(request)
    ds.save_chat_message(uid, "user", message)
    history = ds.list_chat_messages(uid, limit=20)
    history.reverse()
    try:
        reply = ai.chat(history)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    ds.save_chat_message(uid, "assistant", reply, "anthropic")
    return JSONResponse({"reply": reply})


@router.post("/api/chat/clear")
@require_capability("module.bcm.access")
async def api_chat_clear(request: Request):
    ds.clear_chat_history(_uid(request))
    return JSONResponse({"ok": True})


@router.post("/api/ai/generate-plan")
@require_capability("bcm.ai.use")
async def api_ai_generate_plan(request: Request):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    from modules.bcm import ai_service as ai
    body = await _json_body(request)
    try:
        content = ai.generate_plan(
            scenario=body.get("scenario", "Business Continuity"),
            scope=body.get("scope", ""),
            industry=body.get("industry", ""),
            extra_context=body.get("extra_context", ""),
        )
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return JSONResponse({"content": content})


@router.post("/api/ai/generate-plan/save")
@require_capability("bcm.plan.manage")
async def api_ai_save_generated_plan(request: Request):
    body = await _json_body(request)
    pid = ds.create_plan({
        "title": body.get("title", "AI-Generated Plan"),
        "scope": body.get("scope"),
        "owner": _uname(request),
        "content": body.get("content"),
        "status": "draft",
    })
    return JSONResponse({"id": pid}, status_code=201)


# ── CSV Export ────────────────────────────────────────────────────────────────

@router.get("/api/export/csv")
@require_capability("module.bcm.access")
async def api_export_csv(request: Request):
    import csv
    import io
    from starlette.responses import StreamingResponse
    db = get_db()
    try:
        rows = db.execute(
            "SELECT title, description, severity, status, commander, "
            "affected_systems, impact, assigned_to, declared_at, resolved_at, created_at "
            "FROM bcm_incidents ORDER BY created_at DESC"
        ).fetchall()
    finally:
        db.close()
    columns = ["title", "description", "severity", "status", "commander",
               "affected_systems", "impact", "assigned_to", "declared_at", "resolved_at", "created_at"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for r in rows:
        writer.writerow([r[c] if c in r.keys() else "" for c in columns])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bcm_incidents_export.csv"},
    )


@router.get("/api/reports/summary")
@require_capability("module.bcm.access")
async def api_reports_summary(request: Request):
    return JSONResponse(ds.get_dashboard_stats())


@router.post("/api/reports/board")
@require_capability("bcm.report.generate")
async def api_reports_board(request: Request):
    from modules.bcm import ai_service as ai
    stats = ds.get_dashboard_stats()
    try:
        narrative = ai.generate_board_narrative(stats)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return JSONResponse({"stats": stats, "narrative": narrative})
