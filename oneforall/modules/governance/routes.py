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

from core.middleware import require_capability
from core.shell_context import shell_ctx
from core.rbac import has_capability
from modules.governance import data_service as ds


router = APIRouter(prefix="/governance", tags=["governance"])
templates = Jinja2Templates(directory=["modules/governance/templates", "templates"])


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    from core.sanitize import sanitize_dict
    return sanitize_dict(body)


# ── SPA ──────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
@require_capability("governance.entities.view")
async def governance_spa(request: Request):
    user = request.state.user
    return templates.TemplateResponse(request, "index.html", {
        "user": user,
        "can_manage": has_capability(user, "governance.entities.manage"),
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
        raise HTTPException(409, "Cannot delete — BU has children or is referenced by scoped entities")
    return JSONResponse({"ok": True})


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
        bu_id=bu_id, dept_id=dept_id, include_inactive=include_inactive
    ))


@router.post("/api/business-processes")
@require_capability("governance.entities.manage")
async def api_bp_create(request: Request):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    new_id = ds.create_business_process(body)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/business-processes/{bp_id}")
@require_capability("governance.entities.manage")
async def api_bp_update(request: Request, bp_id: int):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    ds.update_business_process(bp_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/business-processes/{bp_id}")
@require_capability("governance.entities.manage")
async def api_bp_delete(request: Request, bp_id: int):
    ds.delete_business_process(bp_id)
    return JSONResponse({"ok": True})


# ── Applications ────────────────────────────────────────────────────────────

@router.get("/api/applications")
@require_capability("governance.entities.view")
async def api_app_list(request: Request):
    p = request.query_params
    bu_id = int(p["bu_id"]) if p.get("bu_id") else None
    include_inactive = p.get("include_inactive") == "1"
    return JSONResponse(ds.list_applications(bu_id=bu_id, include_inactive=include_inactive))


@router.post("/api/applications")
@require_capability("governance.entities.manage")
async def api_app_create(request: Request):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    new_id = ds.create_application(body)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/applications/{app_id}")
@require_capability("governance.entities.manage")
async def api_app_update(request: Request, app_id: int):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    ds.update_application(app_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/applications/{app_id}")
@require_capability("governance.entities.manage")
async def api_app_delete(request: Request, app_id: int):
    ok = ds.delete_application(app_id)
    if not ok:
        raise HTTPException(409, "Cannot delete — application is referenced by data assets")
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
        bu_id=bu_id, classification=classification, include_inactive=include_inactive
    ))


@router.post("/api/data-assets")
@require_capability("governance.entities.manage")
async def api_da_create(request: Request):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    new_id = ds.create_data_asset(body)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/data-assets/{asset_id}")
@require_capability("governance.entities.manage")
async def api_da_update(request: Request, asset_id: int):
    body = await _json_body(request)
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")
    ds.update_data_asset(asset_id, body)
    return JSONResponse({"ok": True})


@router.delete("/api/data-assets/{asset_id}")
@require_capability("governance.entities.manage")
async def api_da_delete(request: Request, asset_id: int):
    ds.delete_data_asset(asset_id)
    return JSONResponse({"ok": True})
