"""
ORM module — Operational Risk Management.
SPA at GET /orm/ with JSON APIs at /orm/api/*.
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from core.middleware import require_module, require_capability
from core.shell_context import shell_ctx
from core.events import emit, ORM_EVENT_LOGGED, ORM_EVENT_ELEVATED, ORM_EVENT_RESOLVED
from modules.orm import data_service as ds
from modules.orm import ai_service as ai

router = APIRouter(prefix="/orm", tags=["orm"])
templates = Jinja2Templates(directory=["modules/orm/templates", "templates"])


def _uid(request: Request) -> int:
    return request.state.user["id"]


def _uname(request: Request) -> str:
    return request.state.user.get("full_name", "Unknown")


async def _json_body(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


# ── SPA ───────────────────────────────────────────────────────────────────────

_SPA_PAGES = {"events", "indicators", "reports", "chat", "assessment"}


@router.get("/", response_class=HTMLResponse)
@require_module("orm")
async def orm_spa(request: Request):
    user = request.state.user
    return templates.TemplateResponse(request, "index.html", {
        "user": user,
        **shell_ctx(request, active_module="orm"),
    })


@router.get("/{page}", response_class=HTMLResponse)
@require_module("orm")
async def orm_spa_page(request: Request, page: str):
    if page.startswith("api") or page not in _SPA_PAGES:
        raise HTTPException(404)
    return await orm_spa(request)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/api/dashboard")
@require_capability("module.orm.access")
async def api_dashboard(request: Request):
    days = int(request.query_params.get("days", 30))
    stats = ds.get_dashboard_stats(days=days)
    stats["departments"] = ds.get_distinct_departments()
    stats["active_bcm_incident"] = ds.has_active_bcm_incident()
    stats["active_sentinel_breach"] = ds.has_active_sentinel_breach()
    stats["kri_alerts"] = _get_kri_alerts()
    # sla_overdue already included in get_dashboard_stats()
    return JSONResponse(stats)


def _get_kri_alerts():
    kris = ds.list_kris()
    alerts = []
    for k in kris:
        val = k.get("current_value") or 0
        crit = k.get("threshold_crit")
        warn = k.get("threshold_warn")
        if crit and val >= crit:
            alerts.append({"name": k["name"], "value": val, "level": "critical"})
        elif warn and val >= warn:
            alerts.append({"name": k["name"], "value": val, "level": "warning"})
    return alerts


# ── Events ────────────────────────────────────────────────────────────────────

@router.get("/api/events")
@require_capability("module.orm.access")
async def api_events_list(request: Request):
    p = request.query_params
    return JSONResponse(ds.list_events(
        event_type=p.get("event_type"),
        severity=p.get("severity"),
        status=p.get("status"),
        department=p.get("department"),
        date_from=p.get("date_from"),
        date_to=p.get("date_to"),
    ))


@router.get("/api/events/{event_id}")
@require_capability("module.orm.access")
async def api_event_detail(request: Request, event_id: int):
    ev = ds.get_event(event_id)
    if not ev:
        raise HTTPException(404)
    return JSONResponse(ev)


@router.post("/api/events")
@require_capability("orm.event.log")
async def api_event_create(request: Request):
    body = await _json_body(request)
    body["reported_by"] = _uid(request)
    eid = ds.create_event(body)
    emit(
        ORM_EVENT_LOGGED,
        source_module="orm",
        entity_type="event",
        entity_id=eid,
        payload={
            "title": body.get("title", ""),
            "event_type": body.get("event_type", ""),
            "severity": body.get("severity", "medium"),
            "financial_impact": body.get("financial_impact", 0),
        },
        user_id=_uid(request),
    )
    return JSONResponse({"id": eid}, status_code=201)


@router.put("/api/events/{event_id}")
@require_capability("orm.event.manage")
async def api_event_update(request: Request, event_id: int):
    body = await _json_body(request)
    ds.update_event(event_id, body)
    new_status = (body.get("status") or "").lower()
    if new_status in ("resolved", "closed"):
        ev = ds.get_event(event_id)
        if ev:
            emit(
                ORM_EVENT_RESOLVED,
                source_module="orm", entity_type="event", entity_id=event_id,
                payload={
                    "title": ev.get("title", ""),
                    "event_type": ev.get("event_type", ""),
                    "severity": ev.get("severity", ""),
                    "financial_impact": ev.get("financial_impact", 0),
                    "closed_status": new_status,
                },
                user_id=_uid(request),
            )
    return JSONResponse({"ok": True})


@router.delete("/api/events/{event_id}")
@require_capability("orm.event.manage")
async def api_event_delete(request: Request, event_id: int):
    ds.delete_event(event_id)
    return JSONResponse({"ok": True})


@router.post("/api/events/{event_id}/elevate")
@require_capability("orm.event.manage")
async def api_event_elevate(request: Request, event_id: int):
    """Elevate an ORM event to an ERM enterprise risk."""
    ev = ds.get_event(event_id)
    if not ev:
        raise HTTPException(404)
    body = await _json_body(request)

    # Map ORM event type → ERM category
    _type_to_category = {
        "process_failure": "operational", "fraud": "operational",
        "system_failure": "technology", "human_error": "operational",
        "outage": "technology", "vendor_failure": "third_party",
        "customer_impact": "reputational",
    }
    category = _type_to_category.get(ev.get("event_type", ""), "operational")

    # Score from severity
    sev_map = {"critical": (5, 5), "high": (4, 4), "medium": (3, 3), "low": (2, 2)}
    l, i = sev_map.get(ev.get("severity", "medium"), (3, 3))

    from modules.erm import data_service as erm_ds
    risk_data = {
        "title": body.get("title") or ev["title"],
        "description": (ev.get("description") or "") + f"\n\nElevated from ORM event #{event_id}.",
        "category": category,
        "likelihood": l, "impact": i,
        "treatment": "mitigate",
        "source_module": "orm",
        "source_risk_id": event_id,
        "board_visibility": 1 if ev.get("severity") in ("critical",) else 0,
        "created_by": _uid(request),
    }
    erm_risk_id = erm_ds.create_enterprise_risk(risk_data)
    ds.link_to_erm(event_id, erm_risk_id)

    emit(
        ORM_EVENT_ELEVATED,
        source_module="orm",
        entity_type="event",
        entity_id=event_id,
        payload={
            "title": ev["title"],
            "erm_risk_id": erm_risk_id,
            "severity": ev.get("severity"),
            "financial_impact": ev.get("financial_impact", 0),
        },
        user_id=_uid(request),
    )
    return JSONResponse({"ok": True, "erm_risk_id": erm_risk_id})


# ── KRIs ──────────────────────────────────────────────────────────────────────

@router.get("/api/kris")
@require_capability("module.orm.access")
async def api_kris_list(request: Request):
    return JSONResponse(ds.list_kris())


@router.post("/api/kris")
@require_capability("orm.kri.manage")
async def api_kri_create(request: Request):
    body = await _json_body(request)
    kid = ds.create_kri(body)
    return JSONResponse({"id": kid}, status_code=201)


@router.put("/api/kris/{kri_id}")
@require_capability("orm.kri.manage")
async def api_kri_update(request: Request, kri_id: int):
    body = await _json_body(request)
    ds.update_kri(kri_id, body, user_id=_uid(request))
    return JSONResponse({"ok": True})


@router.get("/api/kris/{kri_id}/history")
@require_capability("module.orm.access")
async def api_kri_history(request: Request, kri_id: int):
    limit = int(request.query_params.get("limit", 12))
    return JSONResponse(ds.get_kri_history(kri_id, limit=limit))


@router.delete("/api/kris/{kri_id}")
@require_capability("orm.kri.manage")
async def api_kri_delete(request: Request, kri_id: int):
    ds.delete_kri(kri_id)
    return JSONResponse({"ok": True})


# ── Users list (for owner pickers) ───────────────────────────────────────────

@router.get("/api/users")
@require_capability("module.orm.access")
async def api_users_list(request: Request):
    user = request.state.user
    org_id = user.get("org_id")
    from database import get_db as _gdb
    db = _gdb()
    try:
        if org_id:
            rows = db.execute(
                "SELECT id, full_name, email FROM users "
                "WHERE is_active=1 AND org_id=%s ORDER BY full_name", (org_id,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, full_name, email FROM users "
                "WHERE is_active=1 ORDER BY full_name"
            ).fetchall()
        return JSONResponse([dict(r) for r in rows])
    finally:
        db.close()


# ── AI ────────────────────────────────────────────────────────────────────────

@router.post("/api/ai/analyze/{event_id}")
@require_capability("orm.ai.use")
async def api_ai_analyze(request: Request, event_id: int):
    ev = ds.get_event(event_id)
    if not ev:
        raise HTTPException(404)
    result = ai.analyze_event(ev)
    # Save analysis back to the event
    update = {}
    if result.get("root_cause_category"):
        update["root_cause_category"] = result["root_cause_category"]
    if result.get("corrective_action") and not ev.get("corrective_action"):
        update["corrective_action"] = result["corrective_action"]
    if result.get("preventive_action") and not ev.get("preventive_action"):
        update["preventive_action"] = result["preventive_action"]
    if update:
        ds.update_event(event_id, update)
    return JSONResponse(result)


@router.post("/api/ai/board-report")
@require_capability("orm.report.generate")
async def api_ai_board_report(request: Request):
    days = int((await _json_body(request)).get("days", 30))
    stats = ds.get_dashboard_stats(days=days)
    narrative = ai.generate_trend_narrative(stats)
    return JSONResponse({"narrative": narrative, "stats": stats})


@router.post("/api/chat")
@require_capability("orm.ai.use")
async def api_chat_send(request: Request):
    body = await _json_body(request)
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(400, "Message required")
    uid = _uid(request)
    ds.save_chat(uid, "user", message)
    history = ds.list_chat(uid, limit=20)
    msgs = [{"role": m["role"], "content": m["content"]} for m in history]
    stats = ds.get_dashboard_stats()
    reply = ai.chat(msgs, stats=stats)
    ds.save_chat(uid, "assistant", reply, "anthropic")
    return JSONResponse({"reply": reply})


@router.get("/api/chat")
@require_capability("module.orm.access")
async def api_chat_history(request: Request):
    return JSONResponse(ds.list_chat(_uid(request)))


@router.post("/api/chat/clear")
@require_capability("module.orm.access")
async def api_chat_clear(request: Request):
    ds.clear_chat(_uid(request))
    return JSONResponse({"ok": True})


# ── Event Templates ───────────────────────────────────────────────────────────

@router.get("/api/event-templates")
@require_capability("module.orm.access")
async def api_event_templates_list(request: Request):
    category = request.query_params.get("category")
    return JSONResponse(ds.list_event_templates(category=category))


@router.post("/api/event-templates")
@require_capability("orm.event.manage")
async def api_event_template_create(request: Request):
    body = await _json_body(request)
    tid = ds.create_event_template(body)
    return JSONResponse({"id": tid}, status_code=201)


@router.put("/api/event-templates/{template_id}")
@require_capability("orm.event.manage")
async def api_event_template_update(request: Request, template_id: int):
    body = await _json_body(request)
    ds.update_event_template(template_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/event-templates/{template_id}")
@require_capability("orm.event.manage")
async def api_event_template_delete(request: Request, template_id: int):
    ds.delete_event_template(template_id)
    return JSONResponse({"ok": True})


@router.post("/api/event-templates/{template_id}/activate")
@require_capability("orm.event.log")
async def api_event_template_activate(request: Request, template_id: int):
    """Instantly create an ORM event from a template."""
    tmpl = ds.get_event_template(template_id)
    if not tmpl:
        raise HTTPException(404, "Template not found")
    body = await _json_body(request)  # optional overrides
    event_data = {
        "title":                tmpl["title"],
        "description":          tmpl["description"],
        "event_type":           tmpl["event_type"],
        "severity":             tmpl["severity"],
        "department":           body.get("department") or tmpl.get("department"),
        "process_affected":     tmpl.get("process_affected"),
        "root_cause_category":  tmpl.get("root_cause_category"),
        "corrective_action":    tmpl.get("corrective_action"),
        "preventive_action":    tmpl.get("preventive_action"),
        "basel_category":       tmpl.get("basel_category"),
        "status":               "open",
        "reported_by":          _uid(request),
    }
    eid = ds.create_event(event_data)
    ds.increment_template_usage(template_id)
    emit(
        ORM_EVENT_LOGGED,
        source_module="orm", entity_type="event", entity_id=eid,
        payload={"title": event_data["title"], "event_type": event_data["event_type"],
                 "severity": event_data["severity"], "financial_impact": 0},
        user_id=_uid(request),
    )
    return JSONResponse({"id": eid, "ok": True}, status_code=201)


# ── Event Workflow ─────────────────────────────────────────────────────────────

@router.post("/api/events/{event_id}/workflow")
@require_capability("orm.event.manage")
async def api_event_workflow_advance(request: Request, event_id: int):
    body = await _json_body(request)
    to_step = body.get("step", "").strip()
    valid = ["identified", "under_investigation", "root_cause_confirmed", "remediation", "closed"]
    if to_step not in valid:
        raise HTTPException(400, f"Invalid step. Must be one of: {valid}")
    result = ds.transition_event_workflow(
        event_id, to_step, user_id=_uid(request), notes=body.get("notes")
    )
    if not result:
        raise HTTPException(404, "Event not found")
    return JSONResponse(result)


@router.get("/api/events/{event_id}/workflow")
@require_capability("module.orm.access")
async def api_event_workflow_history(request: Request, event_id: int):
    return JSONResponse(ds.get_event_workflow_history(event_id))


# ── RCSA — Risk & Control Self-Assessment ─────────────────────────────────────

@router.get("/api/rcsa")
@require_capability("module.orm.access")
async def api_rcsa_list(request: Request):
    return JSONResponse(ds.list_rcsa_assessments())


@router.post("/api/rcsa")
@require_capability("orm.event.manage")
async def api_rcsa_create(request: Request):
    body = await _json_body(request)
    body["created_by"] = _uid(request)
    aid = ds.create_rcsa_assessment(body)
    return JSONResponse({"id": aid}, status_code=201)


@router.get("/api/rcsa/{assessment_id}")
@require_capability("module.orm.access")
async def api_rcsa_get(request: Request, assessment_id: int):
    a = ds.get_rcsa_assessment(assessment_id)
    if not a:
        raise HTTPException(404)
    return JSONResponse(a)


@router.put("/api/rcsa/{assessment_id}")
@require_capability("orm.event.manage")
async def api_rcsa_update(request: Request, assessment_id: int):
    body = await _json_body(request)
    ds.update_rcsa_assessment(assessment_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/rcsa/{assessment_id}")
@require_capability("orm.event.manage")
async def api_rcsa_delete(request: Request, assessment_id: int):
    ds.delete_rcsa_assessment(assessment_id)
    return JSONResponse({"ok": True})


# ── RCSA Risks ────────────────────────────────────────────────────────────────

@router.get("/api/rcsa/{assessment_id}/risks")
@require_capability("module.orm.access")
async def api_rcsa_risks_list(request: Request, assessment_id: int):
    return JSONResponse(ds.list_rcsa_risks(assessment_id))


@router.post("/api/rcsa/{assessment_id}/risks")
@require_capability("orm.event.manage")
async def api_rcsa_risk_create(request: Request, assessment_id: int):
    body = await _json_body(request)
    body["assessment_id"] = assessment_id
    rid = ds.create_rcsa_risk(body)
    return JSONResponse({"id": rid}, status_code=201)


@router.put("/api/rcsa/risks/{risk_id}")
@require_capability("orm.event.manage")
async def api_rcsa_risk_update(request: Request, risk_id: int):
    body = await _json_body(request)
    ds.update_rcsa_risk(risk_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/rcsa/risks/{risk_id}")
@require_capability("orm.event.manage")
async def api_rcsa_risk_delete(request: Request, risk_id: int):
    ds.delete_rcsa_risk(risk_id)
    return JSONResponse({"ok": True})


# ── RCSA Controls ─────────────────────────────────────────────────────────────

@router.get("/api/rcsa/risks/{risk_id}/controls")
@require_capability("module.orm.access")
async def api_rcsa_controls_list(request: Request, risk_id: int):
    return JSONResponse(ds.list_rcsa_controls(risk_id))


@router.post("/api/rcsa/risks/{risk_id}/controls")
@require_capability("orm.event.manage")
async def api_rcsa_control_create(request: Request, risk_id: int):
    body = await _json_body(request)
    body["risk_id"] = risk_id
    cid = ds.create_rcsa_control(body)
    return JSONResponse({"id": cid}, status_code=201)


@router.put("/api/rcsa/controls/{control_id}")
@require_capability("orm.event.manage")
async def api_rcsa_control_update(request: Request, control_id: int):
    body = await _json_body(request)
    ds.update_rcsa_control(control_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/rcsa/controls/{control_id}")
@require_capability("orm.event.manage")
async def api_rcsa_control_delete(request: Request, control_id: int):
    ds.delete_rcsa_control(control_id)
    return JSONResponse({"ok": True})


# ── RCSA Actions ──────────────────────────────────────────────────────────────

@router.get("/api/rcsa/{assessment_id}/actions")
@require_capability("module.orm.access")
async def api_rcsa_actions_list(request: Request, assessment_id: int):
    return JSONResponse(ds.list_rcsa_actions(assessment_id=assessment_id))


@router.post("/api/rcsa/controls/{control_id}/actions")
@require_capability("orm.event.manage")
async def api_rcsa_action_create(request: Request, control_id: int):
    body = await _json_body(request)
    body["control_id"] = control_id
    actid = ds.create_rcsa_action(body)
    return JSONResponse({"id": actid}, status_code=201)


@router.put("/api/rcsa/actions/{action_id}")
@require_capability("orm.event.manage")
async def api_rcsa_action_update(request: Request, action_id: int):
    body = await _json_body(request)
    ds.update_rcsa_action(action_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/rcsa/actions/{action_id}")
@require_capability("orm.event.manage")
async def api_rcsa_action_delete(request: Request, action_id: int):
    ds.delete_rcsa_action(action_id)
    return JSONResponse({"ok": True})


@router.get("/api/export/csv")
@require_capability("orm.event.view")
async def api_export_csv(request: Request):
    import csv
    import io
    from starlette.responses import StreamingResponse
    from database import get_db
    db = get_db()
    try:
        rows = db.execute(
            "SELECT title, event_type, severity, status, department, financial_impact, "
            "root_cause, reporter_name, created_at, resolved_at "
            "FROM orm_events ORDER BY created_at DESC"
        ).fetchall()
    finally:
        db.close()
    columns = ["title", "event_type", "severity", "status", "department",
               "financial_impact", "root_cause", "reporter_name", "created_at", "resolved_at"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for r in rows:
        writer.writerow([r[c] if c in r.keys() else "" for c in columns])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orm_events.csv"},
    )
