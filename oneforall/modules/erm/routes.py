"""
ERM module — Enterprise Risk Management.
SPA at GET /erm/ with JSON APIs at /erm/api/*.
"""
import json
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from core.middleware import require_module, require_capability, check_ai_rate_limit, record_ai_call
from core.shell_context import shell_ctx
from core.rbac import has_capability
from core.events import emit, ERM_APPETITE_BREACHED, ERM_RISK_CLOSED, ERM_RISK_IDENTIFIED
from core.timeutils import utcnow, to_dt
from modules.erm import data_service as ds
from modules.erm import ai_service as ai

router = APIRouter(prefix="/erm", tags=["erm"])
templates = Jinja2Templates(directory=["modules/erm/templates", "templates"])


def _uid(request: Request) -> int:
    return request.state.user["id"]


def _uname(request: Request) -> str:
    return request.state.user.get("full_name", "Unknown")


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    from core.sanitize import sanitize_dict
    return sanitize_dict(body)


# ── SPA ───────────────────────────────────────────────────────────────────────

_SPA_PAGES = {"register", "appetite", "library", "obligations", "assessments", "reports", "chat", "indicators", "statements", "rating-guide", "framework-admin"}


@router.get("/", response_class=HTMLResponse)
@require_module("erm")
async def erm_spa(request: Request):
    user = request.state.user
    return templates.TemplateResponse(request, "index.html", {
        "user": user,
        "can_manage_frameworks": has_capability(user, "erm.framework.manage"),
        **shell_ctx(request, active_module="erm"),
    })


@router.get("/{page}", response_class=HTMLResponse)
@require_module("erm")
async def erm_spa_page(request: Request, page: str):
    if page.startswith("api") or page not in _SPA_PAGES:
        raise HTTPException(404)
    return await erm_spa(request)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/api/dashboard")
@require_capability("module.erm.access")
async def api_dashboard(request: Request):
    stats = ds.get_dashboard_stats()
    stats["register_stats"] = ds.get_register_stats()
    stats["appetite_status"] = ds.get_appetite_status()
    stats["risk_feed"] = ds.get_risk_feed(limit=10)
    return JSONResponse(stats)


# ── Enterprise Risks ──────────────────────────────────────────────────────────

@router.get("/api/risks")
@require_capability("erm.risk.view")
async def api_risks_list(request: Request):
    p = request.query_params
    return JSONResponse(ds.list_enterprise_risks(
        category=p.get("category"),
        status=p.get("status"),
        source_module=p.get("source_module"),
        board_only=p.get("board_only") == "1",
        bu_id=int(p["bu_id"]) if p.get("bu_id") and p["bu_id"].isdigit() else None,
    ))


@router.get("/api/risks/{risk_id}")
@require_capability("erm.risk.view")
async def api_risk_detail(request: Request, risk_id: int):
    r = ds.get_enterprise_risk(risk_id)
    if not r:
        raise HTTPException(404, "Risk not found")
    return JSONResponse(r)


@router.post("/api/risks")
@require_capability("erm.risk.manage")
async def api_risk_create(request: Request):
    body = await _json_body(request)
    body["created_by"] = _uid(request)
    rid = ds.create_enterprise_risk(body)
    emit(
        ERM_RISK_IDENTIFIED,
        source_module="erm",
        entity_type="enterprise_risk",
        entity_id=rid,
        payload={
            "title": body.get("title", ""),
            "category": body.get("category", ""),
            "severity": body.get("severity", "high"),
            "likelihood": body.get("likelihood", 3),
            "impact": body.get("impact", 3),
            "erm_risk_id": rid,
        },
        user_id=body.get("created_by"),
    )
    return JSONResponse({"id": rid}, status_code=201)


@router.put("/api/risks/{risk_id}")
@require_capability("erm.risk.manage")
async def api_risk_update(request: Request, risk_id: int):
    body = await _json_body(request)
    ds.update_enterprise_risk(risk_id, body)
    # Emit ERM_RISK_CLOSED so appetite recalculates and linked modules are notified
    if (body.get("status") or "").lower() == "closed":
        risk = ds.get_enterprise_risk(risk_id)
        if risk:
            emit(
                ERM_RISK_CLOSED,
                source_module="erm",
                entity_type="enterprise_risk",
                entity_id=risk_id,
                payload={
                    "title": risk.get("title", ""),
                    "category": risk.get("category", ""),
                    "source_module": risk.get("source_module", "erm"),
                    "source_risk_id": risk.get("source_risk_id"),
                },
                user_id=request.state.user.get("id") if request.state.user else None,
            )
    return JSONResponse({"ok": True})


@router.delete("/api/risks/{risk_id}")
@require_capability("erm.risk.manage")
async def api_risk_delete(request: Request, risk_id: int):
    ds.delete_enterprise_risk(risk_id)
    return JSONResponse({"ok": True})


# ── Delete platform risk_register entry (cross-module risks visible in ERM) ───

@router.delete("/api/register-entry/{reg_id}")
@require_capability("erm.risk.manage")
async def api_register_entry_delete(request: Request, reg_id: int):
    """Delete a platform risk_register row that was auto-created from another module.
    Only deletes rows in risk_register; erm_enterprise_risks has its own DELETE route."""
    from database import get_db as _get_db
    db = _get_db()
    try:
        row = db.execute("SELECT id FROM risk_register WHERE id=%s", (reg_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Risk register entry not found")
        db.execute("DELETE FROM risk_register WHERE id=%s", (reg_id,))
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()


# ── Unified Register ──────────────────────────────────────────────────────────

@router.get("/api/register")
@require_capability("erm.risk.view")
async def api_register(request: Request):
    p = request.query_params
    return JSONResponse(ds.get_unified_register(filters={
        "category": p.get("category"),
        "status": p.get("status"),
    }))


@router.get("/api/register/stats")
@require_capability("erm.risk.view")
async def api_register_stats(request: Request):
    return JSONResponse(ds.get_register_stats())


# ── Risk Rating Framework ─────────────────────────────────────────────────────
# Read-only reference data — gated behind erm.risk.view (same access any ERM
# user already has to view risks) rather than a manage-level capability, since
# this is guidance meant to help pick a score, not an editing surface.

@router.get("/api/framework/active")
@require_capability("erm.risk.view")
async def api_framework_active(request: Request):
    fw = ds.get_active_framework()
    if not fw:
        raise HTTPException(404, "No active risk rating framework configured")
    return JSONResponse(fw)


# ── Risk Rating Frameworks (admin: create/edit/activate/import/export) ────────
# GETs use the same broad erm.risk.view as /api/framework/active above — these
# populate the editor UI, not a different sensitivity tier. Mutations require
# erm.framework.manage; the nav entry point to this whole surface is gated on
# that same capability so non-managers are never shown buttons that just 403.

@router.get("/api/frameworks")
@require_capability("erm.risk.view")
async def api_frameworks_list(request: Request):
    return JSONResponse(ds.list_frameworks())


@router.get("/api/frameworks/{framework_id}")
@require_capability("erm.risk.view")
async def api_framework_detail(request: Request, framework_id: int):
    fw = ds.get_framework_detail(framework_id)
    if not fw:
        raise HTTPException(404, "Framework not found")
    return JSONResponse(fw)


@router.post("/api/frameworks")
@require_capability("erm.framework.manage")
async def api_framework_create(request: Request):
    body = await _json_body(request)
    name = (body.get("name") or "").strip()
    clone_from_id = body.get("clone_from_id")
    if not name:
        raise HTTPException(400, "name is required")
    if not clone_from_id:
        raise HTTPException(400, "clone_from_id is required — new frameworks are always cloned from an existing one")
    try:
        new_id = ds.create_framework_from_clone(name, body.get("description", ""), clone_from_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/frameworks/{framework_id}")
@require_capability("erm.framework.manage")
async def api_framework_update(request: Request, framework_id: int):
    body = await _json_body(request)
    errors = ds.validate_framework_payload(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    try:
        ds.update_framework(framework_id, body)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    return JSONResponse({"ok": True})


@router.delete("/api/frameworks/{framework_id}")
@require_capability("erm.framework.manage")
async def api_framework_delete(request: Request, framework_id: int):
    try:
        ds.delete_framework(framework_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    return JSONResponse({"ok": True})


@router.post("/api/frameworks/{framework_id}/activate")
@require_capability("erm.framework.manage")
async def api_framework_activate(request: Request, framework_id: int):
    try:
        ds.activate_framework(framework_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    return JSONResponse({"ok": True})


@router.get("/api/frameworks/{framework_id}/export")
@require_capability("erm.risk.view")
async def api_framework_export(request: Request, framework_id: int):
    import re
    from starlette.responses import StreamingResponse
    detail = ds.get_framework_detail(framework_id)
    if not detail:
        raise HTTPException(404, "Framework not found")
    body = json.dumps({**detail, "schema_version": 1}, indent=2)
    slug = re.sub(r"[^a-z0-9]+", "_", detail["name"].lower()).strip("_") or "framework"
    return StreamingResponse(
        iter([body]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={slug}_framework.json"},
    )


@router.post("/api/frameworks/import")
@require_capability("erm.framework.manage")
async def api_framework_import(request: Request):
    body = await _json_body(request)
    schema_version = body.get("schema_version")
    if schema_version is not None and schema_version != 1:
        return JSONResponse({"errors": [f"Unsupported schema_version {schema_version!r}"]}, status_code=400)
    errors = ds.validate_framework_payload(body)
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    new_id = ds.import_framework(body)
    return JSONResponse({"id": new_id}, status_code=201)


# ── Risk Appetite ─────────────────────────────────────────────────────────────

@router.get("/api/appetite")
@require_capability("module.erm.access")
async def api_appetite_list(request: Request):
    return JSONResponse(ds.list_appetite())


@router.delete("/api/appetite/{appetite_id}")
@require_capability("erm.appetite.manage")
async def api_appetite_delete(request: Request, appetite_id: int):
    ds.delete_appetite(appetite_id)
    return JSONResponse({"ok": True})


# NOTE: /status must be registered BEFORE /{appetite_id} to avoid param capture
@router.get("/api/appetite/status")
@require_capability("module.erm.access")
async def api_appetite_status(request: Request):
    statuses = ds.get_appetite_status()
    now = utcnow()
    for a in statuses:
        if a.get("breached"):
            last = a.get("last_breach_notified_at")
            last_dt = to_dt(last) if last else None
            already_notified = last_dt and (now - last_dt).total_seconds() < 86400
            if not already_notified:
                emit(
                    ERM_APPETITE_BREACHED,
                    source_module="erm",
                    entity_type="appetite",
                    entity_id=a.get("id", 0),
                    payload={
                        "category": a.get("category", ""),
                        "max_score": a.get("max_score", 0),
                        "current_score": a.get("current_max_score", 0),
                    },
                    user_id=None,
                )
                ds.mark_appetite_notified(a["id"], True)
        elif a.get("last_breach_notified_at"):
            ds.mark_appetite_notified(a["id"], False)
    return JSONResponse(statuses)


@router.post("/api/appetite")
@require_capability("erm.appetite.manage")
async def api_appetite_upsert(request: Request):
    body = await _json_body(request)
    aid = ds.upsert_appetite(body)
    return JSONResponse({"id": aid}, status_code=201)


@router.put("/api/appetite/{appetite_id}")
@require_capability("erm.appetite.manage")
async def api_appetite_update(request: Request, appetite_id: int):
    body = await _json_body(request)
    ds.update_appetite(appetite_id, body)
    return JSONResponse({"ok": True})


# ── Risk Library ──────────────────────────────────────────────────────────────

@router.get("/api/library")
@require_capability("module.erm.access")
async def api_library_list(request: Request):
    p = request.query_params
    return JSONResponse(ds.list_library(
        category=p.get("category"),
        industry=p.get("industry"),
    ))


@router.post("/api/library")
@require_capability("erm.library.manage")
async def api_library_create(request: Request):
    body = await _json_body(request)
    lid = ds.create_library_item(body)
    return JSONResponse({"id": lid}, status_code=201)


@router.put("/api/library/{item_id}")
@require_capability("erm.library.manage")
async def api_library_update(request: Request, item_id: int):
    body = await _json_body(request)
    ds.update_library_item(item_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/library/{item_id}")
@require_capability("erm.library.manage")
async def api_library_delete(request: Request, item_id: int):
    ds.delete_library_item(item_id)
    return JSONResponse({"ok": True})


@router.post("/api/library/{item_id}/use")
@require_capability("erm.risk.manage")
async def api_library_use(request: Request, item_id: int):
    """Spawn an enterprise risk from a library template."""
    template = ds.get_library_item(item_id)
    if not template:
        raise HTTPException(404, "Library item not found")
    body = await _json_body(request)
    risk_data = {
        "title": body.get("title") or template["title"],
        "description": template.get("description") or "",
        "category": template.get("category", "operational"),
        "likelihood": body.get("likelihood") or template.get("default_likelihood", 3),
        "impact": body.get("impact") or template.get("default_impact", 3),
        "treatment": template.get("typical_treatment", "mitigate"),
        "treatment_plan": template.get("suggested_controls") or "",
        "source_module": "erm",
        "created_by": _uid(request),
    }
    rid = ds.create_enterprise_risk(risk_data)
    emit(
        ERM_RISK_IDENTIFIED,
        source_module="erm",
        entity_type="enterprise_risk",
        entity_id=rid,
        payload={
            "title": risk_data.get("title", ""),
            "category": risk_data.get("category", ""),
            "severity": "high",
            "likelihood": risk_data.get("likelihood", 3),
            "impact": risk_data.get("impact", 3),
            "erm_risk_id": rid,
        },
        user_id=_uid(request),
    )
    return JSONResponse({"id": rid}, status_code=201)


# ── Regulatory Obligations ────────────────────────────────────────────────────

@router.get("/api/obligations")
@require_capability("module.erm.access")
async def api_obligations_list(request: Request):
    p = request.query_params
    return JSONResponse(ds.list_obligations(
        status=p.get("status"),
        regulator=p.get("regulator"),
    ))


@router.post("/api/obligations")
@require_capability("erm.obligations.manage")
async def api_obligation_create(request: Request):
    body = await _json_body(request)
    body["created_by"] = _uid(request)
    oid = ds.create_obligation(body)
    return JSONResponse({"id": oid}, status_code=201)


@router.put("/api/obligations/{obl_id}")
@require_capability("erm.obligations.manage")
async def api_obligation_update(request: Request, obl_id: int):
    body = await _json_body(request)
    ds.update_obligation(obl_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/obligations/{obl_id}")
@require_capability("erm.obligations.manage")
async def api_obligation_delete(request: Request, obl_id: int):
    ds.delete_obligation(obl_id)
    return JSONResponse({"ok": True})


# ── Self-Assessments ──────────────────────────────────────────────────────────

@router.get("/api/assessments")
@require_capability("module.erm.access")
async def api_assessments_list(request: Request):
    return JSONResponse(ds.list_assessments())


@router.post("/api/assessments")
@require_capability("erm.assessment.manage")
async def api_assessment_create(request: Request):
    body = await _json_body(request)
    body["created_by"] = _uid(request)
    aid = ds.create_assessment(body)
    return JSONResponse({"id": aid}, status_code=201)


@router.put("/api/assessments/{assessment_id}")
@require_capability("erm.assessment.manage")
async def api_assessment_update(request: Request, assessment_id: int):
    body = await _json_body(request)
    ds.update_assessment(assessment_id, body)
    return JSONResponse({"ok": True})


@router.get("/api/assessments/{assessment_id}")
@require_capability("module.erm.access")
async def api_assessment_detail(request: Request, assessment_id: int):
    a = ds.get_assessment(assessment_id)
    if not a:
        raise HTTPException(404)
    return JSONResponse(a)


@router.post("/api/assessments/{assessment_id}/questions")
@require_capability("erm.assessment.manage")
async def api_add_question(request: Request, assessment_id: int):
    body = await _json_body(request)
    qid = ds.add_question(assessment_id, body)
    return JSONResponse({"id": qid}, status_code=201)


@router.delete("/api/assessments/{assessment_id}/questions/{question_id}")
@require_capability("erm.assessment.manage")
async def api_delete_question(request: Request, assessment_id: int, question_id: int):
    ds.delete_question(question_id)
    return JSONResponse({"ok": True})


@router.delete("/api/assessments/{assessment_id}")
@require_capability("erm.assessment.manage")
async def api_assessment_delete(request: Request, assessment_id: int):
    ds.delete_assessment(assessment_id)
    return JSONResponse({"ok": True})


@router.get("/api/assessments/{assessment_id}/responses")
@require_capability("module.erm.access")
async def api_assessment_responses(request: Request, assessment_id: int):
    return JSONResponse(ds.list_responses(assessment_id))


@router.post("/api/assessments/{assessment_id}/respond")
@require_capability("module.erm.access")
async def api_submit_response(request: Request, assessment_id: int):
    body = await _json_body(request)
    body["respondent_id"] = _uid(request)
    body["assessment_id"] = assessment_id
    responses = body.get("responses", [body])
    saved_ids = []
    for r in responses:
        r["respondent_id"] = _uid(request)
        r["assessment_id"] = assessment_id
        saved_ids.append(ds.save_response(r))
    return JSONResponse({"saved": len(saved_ids)}, status_code=201)


# ── Users list (for owner pickers) ───────────────────────────────────────────

@router.get("/api/users")
@require_capability("module.erm.access")
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


# ── Risk Event Feed ───────────────────────────────────────────────────────────

@router.get("/api/feed")
@require_capability("module.erm.access")
async def api_feed(request: Request):
    return JSONResponse(ds.get_risk_feed())


# ── AI Endpoints ──────────────────────────────────────────────────────────────

@router.post("/api/ai/score-risk/{risk_id}")
@require_capability("erm.ai.use")
async def api_ai_score_risk(request: Request, risk_id: int):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    r = ds.get_enterprise_risk(risk_id)
    if not r:
        raise HTTPException(404)
    result = ai.score_risk(
        r.get("title", ""),
        r.get("description", ""),
        r.get("category", "")
    )
    # Update the risk with AI-scored fields
    update_data = {}
    if "likelihood" in result:
        update_data["likelihood"] = result["likelihood"]
    if "impact" in result:
        update_data["impact"] = result["impact"]
    if update_data:
        ds.update_enterprise_risk(risk_id, update_data)
    return JSONResponse(result)


@router.post("/api/ai/suggest-scores")
@require_capability("erm.ai.use")
async def api_ai_suggest_scores(request: Request):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    body = await _json_body(request)
    fw = ds.get_active_framework()
    framework_context = {
        "dimensions": fw.get("dimensions", []) if fw else [],
        "likelihood": fw.get("likelihood", []) if fw else [],
    }
    result = ai.suggest_scores(
        body.get("title", ""),
        body.get("description", ""),
        body.get("category", ""),
        framework_context,
    )
    return JSONResponse(result)


@router.post("/api/ai/suggest-treatment")
@require_capability("erm.ai.use")
async def api_ai_suggest_treatment(request: Request):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    body = await _json_body(request)
    result = ai.suggest_treatment(
        body.get("title", ""),
        body.get("description", ""),
        body.get("category", "operational"),
        body.get("likelihood", 3),
        body.get("impact", 3),
    )
    return JSONResponse(result)


@router.post("/api/ai/board-report")
@require_capability("erm.report.generate")
async def api_ai_board_report(request: Request):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    stats = ds.get_dashboard_stats()
    appetite_status = ds.get_appetite_status()
    narrative = ai.generate_board_narrative(stats, appetite_status)
    return JSONResponse({"narrative": narrative, "stats": stats})


@router.post("/api/chat")
@require_capability("erm.ai.use")
async def api_chat_send(request: Request):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
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
@require_capability("module.erm.access")
async def api_chat_history(request: Request):
    return JSONResponse(ds.list_chat(_uid(request)))


@router.post("/api/chat/clear")
@require_capability("module.erm.access")
async def api_chat_clear(request: Request):
    ds.clear_chat(_uid(request))
    return JSONResponse({"ok": True})


# ── KRIs ──────────────────────────────────────────────────────────────────────

@router.get("/api/kris")
@require_capability("module.erm.access")
async def api_kris_list(request: Request):
    linked = request.query_params.get("linked_risk_id")
    return JSONResponse(ds.list_kris(int(linked) if linked else None))


@router.post("/api/kris")
@require_capability("erm.kri.manage")
async def api_kris_create(request: Request):
    body = await _json_body(request)
    kri_id = ds.create_kri(body)
    return JSONResponse({"ok": True, "id": kri_id}, status_code=201)


@router.put("/api/kris/{kri_id}")
@require_capability("erm.kri.manage")
async def api_kris_update(request: Request, kri_id: int):
    body = await _json_body(request)
    ds.update_kri(kri_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/kris/{kri_id}")
@require_capability("erm.kri.manage")
async def api_kris_delete(request: Request, kri_id: int):
    ds.delete_kri(kri_id)
    return JSONResponse({"ok": True})


@router.get("/api/kris/{kri_id}/history")
@require_capability("module.erm.access")
async def api_kri_history(request: Request, kri_id: int):
    return JSONResponse(ds.get_kri_history(kri_id))


# ── Workflow ──────────────────────────────────────────────────────────────────

@router.post("/api/risks/{risk_id}/workflow")
@require_capability("erm.risk.manage")
async def api_risk_workflow_transition(request: Request, risk_id: int):
    body = await _json_body(request)
    to_step = body.get("step")
    if not to_step:
        raise HTTPException(400, "step is required")
    try:
        new_step = ds.transition_workflow(risk_id, to_step, _uid(request), body.get("notes"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    # Emit ERM_RISK_CLOSED when workflow reaches 'closed' so event handlers fire
    # (appetite check, linked risk/breach closure notifications, etc.)
    if new_step == "closed":
        risk = ds.get_enterprise_risk(risk_id)
        if risk:
            emit(
                ERM_RISK_CLOSED,
                source_module="erm",
                entity_type="enterprise_risk",
                entity_id=risk_id,
                payload={
                    "title": risk.get("title", ""),
                    "category": risk.get("category", ""),
                    "source_module": risk.get("source_module", "erm"),
                    "source_risk_id": risk.get("source_risk_id"),
                },
                user_id=_uid(request),
            )
    return JSONResponse({"ok": True, "step": new_step})


@router.get("/api/risks/{risk_id}/workflow")
@require_capability("module.erm.access")
async def api_risk_workflow_history(request: Request, risk_id: int):
    return JSONResponse(ds.get_workflow_history(risk_id))


# ── Risk Statement Library ────────────────────────────────────────────────────

@router.get("/api/statements")
@require_capability("module.erm.access")
async def api_statements_list(request: Request):
    cat = request.query_params.get("category")
    tags = request.query_params.get("tags")
    return JSONResponse(ds.list_statements(cat, tags))


@router.post("/api/statements")
@require_capability("erm.statements.manage")
async def api_statements_create(request: Request):
    body = await _json_body(request)
    stmt_id = ds.create_statement(body)
    return JSONResponse({"ok": True, "id": stmt_id}, status_code=201)


@router.put("/api/statements/{stmt_id}")
@require_capability("erm.statements.manage")
async def api_statements_update(request: Request, stmt_id: int):
    body = await _json_body(request)
    ds.update_statement(stmt_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/statements/{stmt_id}")
@require_capability("erm.statements.manage")
async def api_statements_delete(request: Request, stmt_id: int):
    ds.delete_statement(stmt_id)
    return JSONResponse({"ok": True})


@router.post("/api/statements/{stmt_id}/use")
@require_capability("module.erm.access")
async def api_statements_use(request: Request, stmt_id: int):
    stmt = ds.use_statement(stmt_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")
    return JSONResponse(stmt)


# ── Reporting ─────────────────────────────────────────────────────────────────

@router.get("/api/reports/trend")
@require_capability("erm.report.generate")
async def api_reports_trend(request: Request):
    period = int(request.query_params.get("period", 30))
    return JSONResponse(ds.get_trend_data(max(7, min(period, 365))))


@router.get("/api/reports/aging")
@require_capability("erm.report.generate")
async def api_reports_aging(request: Request):
    return JSONResponse(ds.get_risk_aging())


@router.get("/api/dashboard/executive")
@require_capability("module.erm.access")
async def api_executive_dashboard(request: Request):
    return JSONResponse(ds.get_executive_dashboard())


# ── Smart Assessment (AI) ─────────────────────────────────────────────────────

@router.post("/api/assessments/{assessment_id}/suggest-questions")
@require_capability("erm.ai.use")
async def api_suggest_questions(request: Request, assessment_id: int):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    body = await _json_body(request)
    assessment = ds.get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(404, "Assessment not found")
    existing_q = [q.get("question", "") for q in (assessment.get("questions") or [])]
    linked_risks = body.get("linked_risk_titles", [])
    suggestions = ai.suggest_assessment_questions(
        assessment.get("type", "risk"), linked_risks, existing_q
    )
    return JSONResponse({"ok": True, "suggestions": suggestions})


@router.post("/api/assessments/{assessment_id}/identify-risks")
@require_capability("erm.ai.use")
async def api_identify_risks(request: Request, assessment_id: int):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    responses = ds.list_responses(assessment_id)
    assessment = ds.get_assessment(assessment_id)
    if not assessment:
        raise HTTPException(404, "Assessment not found")
    # Build a readable text of question + response pairs
    lines = []
    for r in responses:
        lines.append(f"Q: {r.get('question', 'Unknown')} — A: {r.get('response', '')}")
    responses_text = "\n".join(lines)
    candidates = ai.identify_risks_from_responses(responses_text, assessment.get("title", ""))
    return JSONResponse({"ok": True, "candidates": candidates})


# ── AI: Risk Statement Generation ─────────────────────────────────────────────

@router.post("/api/ai/generate-statement")
@require_capability("erm.ai.use")
async def api_generate_statement(request: Request):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    body = await _json_body(request)
    result = ai.generate_risk_statement(
        body.get("category", "operational"), body.get("description", "")
    )
    return JSONResponse({"ok": True, **result})


# ── AI: Smart Remediation Plan ────────────────────────────────────────────────

@router.post("/api/ai/remediation-plan/{risk_id}")
@require_capability("erm.ai.use")
async def api_remediation_plan(request: Request, risk_id: int):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    risk = ds.get_enterprise_risk(risk_id)
    if not risk:
        raise HTTPException(404, "Risk not found")
    score = risk.get("inherent_score") or (risk.get("likelihood", 3) * risk.get("impact", 3))
    plan = ai.smart_remediation_plan(
        risk.get("title", ""), risk.get("description", ""),
        risk.get("category", ""), score
    )
    return JSONResponse({"ok": True, **plan})


# ── CSV Export ────────────────────────────────────────────────────────────────

@router.get("/api/export/csv")
@require_capability("erm.risk.view")
async def api_export_csv(request: Request):
    import csv
    import io
    from starlette.responses import StreamingResponse
    from database import get_db
    db = get_db()
    try:
        rows = db.execute(
            "SELECT name, category, risk_level, status, likelihood, impact, "
            "owner_name, source_module, created_at, updated_at "
            "FROM risk_register ORDER BY created_at DESC"
        ).fetchall()
    finally:
        db.close()
    columns = ["name", "category", "risk_level", "status", "likelihood", "impact",
               "owner_name", "source_module", "created_at", "updated_at"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for r in rows:
        writer.writerow([r[c] if c in r.keys() else "" for c in columns])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=erm_risk_register.csv"},
    )


@router.post("/api/risks/import-preview")
@require_capability("erm.risk.manage")
async def api_risks_import_preview(request: Request, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls", ".xlsm")):
        return JSONResponse({"error": "Please upload an Excel file (.xlsx)"}, status_code=400)
    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        return JSONResponse({"error": "File too large (max 10 MB)"}, status_code=400)
    try:
        result = ds.parse_risk_register_excel(contents)
    except Exception as exc:
        return JSONResponse({"error": f"Could not parse Excel file: {exc}"}, status_code=400)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


@router.post("/api/risks/import-commit")
@require_capability("erm.risk.manage")
async def api_risks_import_commit(request: Request):
    body = await _json_body(request)
    rows = body.get("rows")
    if not rows or not isinstance(rows, list):
        return JSONResponse({"error": "No rows provided"}, status_code=400)
    if len(rows) > 500:
        return JSONResponse({"error": "Maximum 500 risks per import"}, status_code=400)
    cat_overrides = body.get("category_overrides", {})
    own_overrides = body.get("owner_overrides", {})
    result = ds.bulk_import_risks(rows, _uid(request), cat_overrides, own_overrides)
    if result["imported"] > 0:
        emit(ERM_RISK_IDENTIFIED, source_module="erm",
             entity_type="enterprise_risk", entity_id=0,
             payload={"title": f"Bulk import: {result['imported']} risks", "status": "open"})
    return JSONResponse({"ok": True, **result})
