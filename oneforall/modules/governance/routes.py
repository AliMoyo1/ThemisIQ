"""
Governance module — HTTP routes for the Governance Graph node types
(Tier 1 T1.1): business_units, departments, business_processes, applications,
data_assets.

SPA at GET /governance/ with JSON APIs under /governance/api/*.
Gated by governance.entities.view (read) / governance.entities.manage (write).
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from database import get_db

from core.middleware import require_auth, require_capability
from core.shell_context import shell_ctx
from core.rbac import has_capability
from modules.governance import data_service as ds


router = APIRouter(prefix="/governance", tags=["governance"])
templates = Jinja2Templates(directory=["modules/governance/templates", "templates"])


def _may_open(request: Request, kind: str, record_id: int) -> None:
    """404 unless the caller may open this governance record: a record in another unit does not exist for them."""
    from modules.governance.entity_scope import describe_record
    db = get_db()
    try:
        shown = describe_record(db, ("governance", kind), record_id, request.state.user)
    finally:
        db.close()
    if not shown:
        raise HTTPException(404, "Not found")


def _unit_in_scope(request: Request, body: dict) -> None:
    """A record is filed under, or moved to, only a unit the caller belongs to (organization wide stays allowed)."""
    unit = body.get("business_unit_id")
    if unit in (None, ""):
        return
    scope = ds.bu_scope_ids(request.state.user)
    try:
        in_scope = scope is None or int(unit) in scope
    except (TypeError, ValueError):
        in_scope = False
    if not in_scope:
        raise HTTPException(400, "Choose a business unit you belong to")


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    from core.sanitize import sanitize_dict
    return sanitize_dict(body)


# ── Connected view and changes to look at ────────────────────────────────────

import re as _re

_SEGMENT = _re.compile(r"^[a-z][a-z_]{0,39}$")


def _shown_or_404(request: Request, module: str, entity_type: str, entity_id: int):
    from modules.governance import entity360
    if not (_SEGMENT.match(module) and _SEGMENT.match(entity_type)):
        raise HTTPException(404, "Not found")
    db = get_db()
    try:
        got = entity360.get_connected(db, request.state.user, module, entity_type, entity_id)
    finally:
        db.close()
    if got is None:
        raise HTTPException(404, "Not found")
    return got


@router.get("/connected/{module}/{entity_type}/{entity_id}", response_class=HTMLResponse)
@require_auth
async def connected_page(request: Request, module: str, entity_type: str, entity_id: int):
    _shown_or_404(request, module, entity_type, entity_id)
    return templates.TemplateResponse(request, "connected.html", {
        "user": request.state.user, "page_kind": "entity", "page_title": "Connected view", "module": module,
        "entity_type": entity_type, "entity_id": entity_id, **shell_ctx(request, active_module="governance")})


@router.get("/api/connected/{module}/{entity_type}/{entity_id}")
@require_auth
async def api_connected(request: Request, module: str, entity_type: str, entity_id: int):
    response = JSONResponse(_shown_or_404(request, module, entity_type, entity_id))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/group/figures/", response_class=HTMLResponse)
@require_auth
async def group_figures_page(request: Request):
    if not has_capability(request.state.user, "group.figure.view_exact"):
        raise HTTPException(404, "Not found")
    return templates.TemplateResponse(request, "group_figures.html", {
        "user": request.state.user, **shell_ctx(request, active_module="governance")})


@router.get("/api/group/figures/views")
@require_auth
async def api_group_figure_views(request: Request):
    from modules.governance import group_figures
    db = get_db()
    try:
        response = JSONResponse(group_figures.views(db, request.state.user))
    finally:
        db.close()
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/api/group/figures")
@require_auth
async def api_group_figures(request: Request):
    from modules.governance import group_figures
    which = request.query_params.get("view", "own")
    raw = request.query_params.get("org_id")
    try:
        org_id = int(raw) if raw not in (None, "") else None
    except ValueError:
        raise HTTPException(422, "Choose a company")
    db = get_db()
    try:
        data = group_figures.view(db, request.state.user, which, org_id)
        db.commit()  # the read is recorded in the shared access log
    finally:
        db.close()
    response = JSONResponse(data)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/api/group/figures/restatements")
@require_auth
async def api_group_figure_restatements(request: Request):
    from modules.governance import group_figures
    db = get_db()
    try:
        response = JSONResponse({"items": group_figures.list_restatements(db, request.state.user)})
    finally:
        db.close()
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.post("/api/group/figures/restatements", status_code=201)
@require_auth
async def api_group_figure_restatement_propose(request: Request):
    from modules.governance import group_figures
    body = await _json_body(request)
    db = get_db()
    try:
        new_id = group_figures.propose_restatement(db, request.state.user, body.get("measure_key"),
                                                   body.get("new_value"), body.get("reason"), body.get("period") or "")
        db.commit()
    finally:
        db.close()
    return JSONResponse({"id": new_id}, status_code=201)


@router.post("/api/group/figures/restatements/{restatement_id}/review")
@require_auth
async def api_group_figure_restatement_review(request: Request, restatement_id: int):
    from modules.governance import group_figures
    body = await _json_body(request)
    db = get_db()
    try:
        result = group_figures.review_restatement(db, request.state.user, restatement_id,
                                                  body.get("decision"), body.get("reason"))
        db.commit()
    finally:
        db.close()
    return JSONResponse(result)


@router.post("/api/group/figures/publish")
@require_auth
async def api_group_figures_publish(request: Request):
    """Platform operator: freeze one organization's figures now (the schedule does the same for every party)."""
    from database import get_db_bypass_rls
    from modules.governance import group_figures
    if not has_capability(request.state.user, "group.relationship.manage"):
        raise HTTPException(404, "Not found")
    body = await _json_body(request)
    try:
        org_id = int(body.get("org_id"))
    except (TypeError, ValueError):
        raise HTTPException(422, "Choose an organization")
    db = get_db_bypass_rls()
    try:
        org = db.execute("SELECT id, slug FROM organizations WHERE id=%s AND status='active'", (org_id,)).fetchone()
    finally:
        db.close()
    if not org:
        raise HTTPException(404, "Organization not found")
    return JSONResponse({"written": group_figures.publish_tenant(org["id"], org["slug"])})


@router.get("/changes", response_class=HTMLResponse)
@require_auth
async def changes_page(request: Request):
    return templates.TemplateResponse(request, "connected.html", {
        "user": request.state.user, "page_kind": "changes", "page_title": "Changes to look at",
        **shell_ctx(request, active_module="governance")})


@router.get("/api/changes")
@require_auth
async def api_changes(request: Request):
    from modules.governance import change_signals
    db = get_db()
    try:
        items = change_signals.list_open(db, request.state.user)
    finally:
        db.close()
    response = JSONResponse({"items": items})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.post("/api/changes/{target_id}/decide")
@require_auth
async def api_change_decide(request: Request, target_id: int):
    from modules.governance import change_signals
    body = await _json_body(request)
    user = request.state.user
    db = get_db()
    try:
        done = change_signals.decide(db, user, target_id, body.get("decision"), body.get("reason"))
        db.commit()
    except change_signals.SignalError as exc:
        db.rollback()
        return JSONResponse({"error": exc.message}, status_code=exc.status)
    finally:
        db.close()
    from core.middleware import log_audit
    action, entity, entity_id, detail = done["audit"]
    log_audit(user, "governance", action, entity, entity_id, details=detail)
    return JSONResponse({"ok": True, "status": done["status"], "task_id": done["task_id"]})

# ── SPA ──────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
@require_capability("governance.entities.view")
async def governance_spa(request: Request):
    user = request.state.user
    return templates.TemplateResponse(request, "index.html", {
        "user": user,
        "can_manage": has_capability(user, "governance.entities.manage"),
        "can_review_source": has_capability(user, "governance.entities.manage") and
                             has_capability(user, "module.sentinel.access"),
        "can_assign_bu": has_capability(user, "governance.bu.assign"),
        **shell_ctx(request, active_module="governance"),
    })


# ── Summary ─────────────────────────────────────────────────────────────────

@router.get("/api/summary")
@require_capability("governance.entities.view")
async def api_summary(request: Request):
    return JSONResponse(ds.get_governance_summary())


# ── Business Units ──────────────────────────────────────────────────────────

@router.get("/api/business-units")
@require_capability("governance.entities.view")
async def api_bu_list(request: Request):
    include_inactive = request.query_params.get("include_inactive") == "1"
    return JSONResponse(ds.list_business_units(include_inactive=include_inactive))


@router.get("/api/business-units/tree")
@require_capability("governance.entities.view")
async def api_bu_tree(request: Request):
    return JSONResponse(ds.get_business_unit_tree())


@router.get("/api/business-units/{bu_id}")
@require_capability("governance.entities.view")
async def api_bu_detail(request: Request, bu_id: int):
    bu = ds.get_business_unit(bu_id)
    if not bu:
        raise HTTPException(404, "Business unit not found")
    return JSONResponse(bu)


@router.post("/api/business-units")
@require_capability("governance.entities.manage")
async def api_bu_create(request: Request):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    new_id = ds.create_business_unit(body)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/business-units/{bu_id}")
@require_capability("governance.entities.manage")
async def api_bu_update(request: Request, bu_id: int):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    ok = ds.update_business_unit(bu_id, body)
    if not ok:
        raise HTTPException(400, "Update rejected — cycle detected or invalid parent")
    return JSONResponse({"ok": True})


@router.delete("/api/business-units/{bu_id}")
@require_capability("governance.entities.manage")
async def api_bu_delete(request: Request, bu_id: int):
    ok = ds.delete_business_unit(bu_id)
    if not ok:
        raise HTTPException(
            409,
            "Cannot delete: the business unit has children, is referenced by records, "
            "or has assignment or transfer history. Deactivate it instead.",
        )
    return JSONResponse({"ok": True})


# ── People / BU assignment ───────────────────────────────────────────────────

@router.get("/api/users")
@require_capability("governance.bu.assign")
async def api_assignable_users(request: Request):
    return JSONResponse(ds.list_assignable_users(request.state.user))


@router.patch("/api/users/{uid}/business-unit")
@require_capability("governance.bu.assign")
async def api_assign_user_bu(request: Request, uid: int):
    raise HTTPException(
        409,
        "Direct assignment is disabled. Use Administration > Users > Move SBU "
        "so the transfer is validated and recorded.",
    )


# ── Departments ─────────────────────────────────────────────────────────────

@router.get("/api/departments")
@require_capability("governance.entities.view")
async def api_dept_list(request: Request):
    p = request.query_params
    bu_id = int(p["bu_id"]) if p.get("bu_id") else None
    include_inactive = p.get("include_inactive") == "1"
    return JSONResponse(ds.list_departments(bu_id=bu_id, include_inactive=include_inactive))


@router.post("/api/departments")
@require_capability("governance.entities.manage")
async def api_dept_create(request: Request):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    new_id = ds.create_department(body)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/departments/{dept_id}")
@require_capability("governance.entities.manage")
async def api_dept_update(request: Request, dept_id: int):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    ds.update_department(dept_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/departments/{dept_id}")
@require_capability("governance.entities.manage")
async def api_dept_delete(request: Request, dept_id: int):
    ok = ds.delete_department(dept_id)
    if not ok:
        raise HTTPException(409, "Cannot delete — department is referenced by processes or applications")
    return JSONResponse({"ok": True})


# ── Business Processes ──────────────────────────────────────────────────────

@router.get("/api/business-processes")
@require_capability("governance.entities.view")
async def api_bp_list(request: Request):
    p = request.query_params
    bu_id = int(p["bu_id"]) if p.get("bu_id") else None
    dept_id = int(p["dept_id"]) if p.get("dept_id") else None
    include_inactive = p.get("include_inactive") == "1"
    return JSONResponse(ds.list_business_processes(
        bu_id=bu_id, dept_id=dept_id, include_inactive=include_inactive, user=request.state.user
    ))


@router.post("/api/business-processes")
@require_capability("governance.entities.manage")
async def api_bp_create(request: Request):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    _unit_in_scope(request, body)
    new_id = ds.create_business_process(body)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/business-processes/{bp_id}")
@require_capability("governance.entities.manage")
async def api_bp_update(request: Request, bp_id: int):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    _may_open(request, "process", bp_id)
    _unit_in_scope(request, body)
    ds.update_business_process(bp_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/business-processes/{bp_id}")
@require_capability("governance.entities.manage")
async def api_bp_delete(request: Request, bp_id: int):
    _may_open(request, "process", bp_id)
    ds.delete_business_process(bp_id)
    return JSONResponse({"ok": True})


# ── Applications ────────────────────────────────────────────────────────────

@router.get("/api/applications")
@require_capability("governance.entities.view")
async def api_app_list(request: Request):
    p = request.query_params
    bu_id = int(p["bu_id"]) if p.get("bu_id") else None
    include_inactive = p.get("include_inactive") == "1"
    return JSONResponse(ds.list_applications(bu_id=bu_id, include_inactive=include_inactive, user=request.state.user))


@router.post("/api/applications")
@require_capability("governance.entities.manage")
async def api_app_create(request: Request):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    _unit_in_scope(request, body)
    new_id = ds.create_application(body)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/applications/{app_id}")
@require_capability("governance.entities.manage")
async def api_app_update(request: Request, app_id: int):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    _may_open(request, "application", app_id)
    _unit_in_scope(request, body)
    ds.update_application(app_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/applications/{app_id}")
@require_capability("governance.entities.manage")
async def api_app_delete(request: Request, app_id: int):
    _may_open(request, "application", app_id)
    still = ds.application_references(app_id)
    if still:
        raise HTTPException(409, "Cannot delete: it still has " + ", ".join(still) + ". Retire it instead, which keeps its history.")
    ds.delete_application(app_id)
    return JSONResponse({"ok": True})


# ── Data Assets ─────────────────────────────────────────────────────────────

@router.get("/api/data-assets")
@require_capability("governance.entities.view")
async def api_da_list(request: Request):
    p = request.query_params
    bu_id = int(p["bu_id"]) if p.get("bu_id") else None
    classification = p.get("classification")
    include_inactive = p.get("include_inactive") == "1"
    return JSONResponse(ds.list_data_assets(
        bu_id=bu_id, classification=classification, include_inactive=include_inactive, user=request.state.user
    ))


@router.post("/api/data-assets")
@require_capability("governance.entities.manage")
async def api_da_create(request: Request):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    _unit_in_scope(request, body)
    new_id = ds.create_data_asset(body)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/data-assets/{asset_id}")
@require_capability("governance.entities.manage")
async def api_da_update(request: Request, asset_id: int):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    _may_open(request, "data_asset", asset_id)
    _unit_in_scope(request, body)
    ds.update_data_asset(asset_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/data-assets/{asset_id}")
@require_capability("governance.entities.manage")
async def api_da_delete(request: Request, asset_id: int):
    _may_open(request, "data_asset", asset_id)
    ds.delete_data_asset(asset_id)
    return JSONResponse({"ok": True})


# ── Canonical Controls ──────────────────────────────────────────────────────

@router.get("/api/controls")
@require_capability("governance.entities.view")
async def api_ctrl_list(request: Request):
    p = request.query_params
    bu_id = int(p["bu_id"]) if p.get("bu_id") else None
    include_inactive = p.get("include_inactive") == "1"
    return JSONResponse(ds.list_canonical_controls(bu_id=bu_id, include_inactive=include_inactive))


@router.post("/api/controls")
@require_capability("governance.entities.manage")
async def api_ctrl_create(request: Request):
    body = await _json_body(request)
    if not body.get("title", "").strip():
        raise HTTPException(400, "title is required")
    new_id = ds.create_canonical_control(body)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/controls/{cid}")
@require_capability("governance.entities.manage")
async def api_ctrl_update(request: Request, cid: int):
    body = await _json_body(request)
    if not body.get("title", "").strip():
        raise HTTPException(400, "title is required")
    ds.update_canonical_control(cid, body)
    return JSONResponse({"ok": True})


@router.delete("/api/controls/{cid}")
@require_capability("governance.entities.manage")
async def api_ctrl_delete(request: Request, cid: int):
    ok = ds.delete_canonical_control(cid)
    if not ok:
        return JSONResponse({"ok": False, "error": "Control is linked to one or more risks"}, status_code=409)
    return JSONResponse({"ok": True})


@router.get("/api/controls/{cid}/effectiveness")
@require_capability("governance.entities.view")
async def api_ctrl_effectiveness(request: Request, cid: int):
    """Return the stored effectiveness score for a control, or compute it on-demand."""
    db = get_db()
    try:
        from modules.governance.effectiveness import get_control_score, recompute_control
        score_row = get_control_score(db, cid)
        if score_row is None:
            # First request: compute and store now
            recompute_control(db, cid)
            db.commit()
            score_row = get_control_score(db, cid)
        if score_row is None:
            raise HTTPException(404, "Control not found or could not be scored")
        return JSONResponse(score_row)
    finally:
        db.close()


@router.post("/api/controls/{cid}/effectiveness/recompute")
@require_capability("governance.entities.manage")
async def api_ctrl_recompute(request: Request, cid: int):
    """Force recompute of a control's effectiveness score."""
    db = get_db()
    try:
        from modules.governance.effectiveness import recompute_control
        score = recompute_control(db, cid)
        db.commit()
        return JSONResponse({"ok": True, "score": score})
    finally:
        db.close()


# ── Regulatory Inbox (PLAN-13 T4.2-lite) ─────────────────────────────────────

@router.get("/api/regulatory-source-candidates")
@require_capability("governance.entities.manage")
async def api_reg_source_candidates(request: Request):
    from modules.governance import source_candidates
    if not has_capability(request.state.user, "module.sentinel.access"):
        raise HTTPException(403, "Sentinel access is required to inspect source captures")
    return JSONResponse(source_candidates.list_pending(request.state.user["org_id"]),
                        headers={"Cache-Control": "private, no-store"})


@router.post("/api/regulatory-source-candidates", status_code=201)
@require_capability("governance.entities.manage")
async def api_reg_source_propose(request: Request):
    from modules.governance import source_candidates
    from core.middleware import log_audit
    if not has_capability(request.state.user, "module.sentinel.access"):
        raise HTTPException(403, "Sentinel access is required to cite the capture")
    body = await _json_body(request)
    try:
        capture_id = int(body.get("capture_id"))
        if capture_id < 1:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(400, "Choose a source capture") from None
    try:
        candidate_id = source_candidates.propose(request.state.user["org_id"], capture_id,
            request.state.user["id"], body)
    except LookupError:
        raise HTTPException(404, "Capture not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    log_audit(request.state.user, "governance", "regulatory_source_proposed",
              "regulatory_source_candidate", candidate_id)
    return JSONResponse({"id": candidate_id}, status_code=201)


@router.post("/api/regulatory-source-candidates/{candidate_id}/decision")
@require_capability("governance.entities.manage")
async def api_reg_source_decide(request: Request, candidate_id: int):
    from modules.governance import source_candidates
    from core.middleware import log_audit
    if not has_capability(request.state.user, "module.sentinel.access"):
        raise HTTPException(403, "Sentinel access is required to inspect source captures")
    body = await _json_body(request)
    try:
        result = source_candidates.decide(request.state.user["org_id"], candidate_id,
            request.state.user["id"], body.get("decision"), body.get("note"))
    except LookupError:
        raise HTTPException(404, "Candidate not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    log_audit(request.state.user, "governance", "regulatory_source_decided",
              "regulatory_source_candidate", candidate_id, details=result["decision"])
    return JSONResponse(result)

@router.get("/api/regulatory-frameworks")
@require_capability("governance.entities.view")
async def api_reg_frameworks(request: Request):
    db = get_db()
    try:
        rows = db.execute("SELECT name FROM frameworks ORDER BY name").fetchall()
        return JSONResponse([r["name"] for r in rows])
    finally:
        db.close()


@router.get("/api/regulatory-updates")
@require_capability("governance.entities.view")
async def api_reg_list(request: Request):
    status = request.query_params.get("status") or None
    rows = ds.list_regulatory_updates(status=status)
    for row in rows:
        if row["ai_review_state"] != "approved" and not has_capability(
                request.state.user, "governance.entities.manage"):
            row["ai_summary"] = None
    return JSONResponse(rows)


@router.post("/api/regulatory-updates")
@require_capability("governance.entities.manage")
async def api_reg_create(request: Request):
    body = await _json_body(request)
    if not body.get("framework_name", "").strip():
        raise HTTPException(400, "framework_name is required")
    if not body.get("title", "").strip():
        raise HTTPException(400, "title is required")
    body["created_by"] = request.state.user.get("id") if request.state.user else None
    new_id = ds.create_regulatory_update(body)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/regulatory-updates/{rid}")
@require_capability("governance.entities.manage")
async def api_reg_update(request: Request, rid: int):
    body = await _json_body(request)
    if not body.get("framework_name", "").strip():
        raise HTTPException(400, "framework_name is required")
    if not body.get("title", "").strip():
        raise HTTPException(400, "title is required")
    ds.update_regulatory_update(rid, body)
    return JSONResponse({"ok": True})


@router.post("/api/regulatory-updates/{rid}/dismiss")
@require_capability("governance.entities.manage")
async def api_reg_dismiss(request: Request, rid: int):
    ds.dismiss_regulatory_update(rid)
    return JSONResponse({"ok": True})


@router.delete("/api/regulatory-updates/{rid}")
@require_capability("governance.entities.manage")
async def api_reg_delete(request: Request, rid: int):
    ds.delete_regulatory_update(rid)
    return JSONResponse({"ok": True})


@router.post("/api/regulatory-updates/{rid}/ai-review")
@require_capability("governance.entities.manage")
async def api_regulatory_ai_review(request: Request, rid: int):
    """Review the optional AI draft separately from deterministic drift tasks."""
    import hashlib
    import json

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid request body") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid request body")
    decision = body.get("decision")
    reason = str(body.get("reason") or "").strip()
    if decision not in ("approved", "rejected") or not 10 <= len(reason) <= 500:
        raise HTTPException(400, "Choose approve or reject and explain the review")
    db = get_db()
    try:
        row = db.execute("SELECT ai_summary FROM regulatory_updates WHERE id=%s", (rid,)).fetchone()
        if row is None:
            raise HTTPException(404, "Update not found")
        summary = row["ai_summary"] or ""
        if not summary.strip():
            raise HTTPException(409, "No AI draft awaits review")
        digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()
        db.execute(
            "INSERT INTO regulatory_ai_reviews "
            "(update_id,summary_hash,decision,reason,reviewed_by) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT(update_id) DO UPDATE SET summary_hash=excluded.summary_hash,"
            "decision=excluded.decision,reason=excluded.reason,reviewed_by=excluded.reviewed_by,"
            "reviewed_at=CURRENT_TIMESTAMP",
            (rid, digest, decision, reason, request.state.user["id"]),
        )
        db.commit()
    finally:
        db.close()
    from core.middleware import log_audit
    log_audit(request.state.user, "governance", "regulatory_ai_review", "regulatory_update", rid,
              json.dumps({"decision": decision, "summary_hash": digest[:16]}))
    return JSONResponse({"decision": decision})


@router.post("/api/regulatory-updates/run-drift")
@require_capability("governance.entities.manage")
async def api_run_drift(request: Request):
    db = get_db()
    try:
        result = ds.run_drift_check(db)
        return JSONResponse(result)
    finally:
        db.close()
