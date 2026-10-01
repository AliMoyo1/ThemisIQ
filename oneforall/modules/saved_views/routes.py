"""
PLAN-36 P06: saved views -- generic CRUD routes, usable by any module that
has called register_view_schema. No capability gate beyond plain
authentication: a saved view is a personal (or org-shared, opt-in)
convenience over a list the actor can already see; it grants no access of
its own (task_plan.md's own "shared view does not grant access to
records" -- enforced because applying a view only ever replays params onto
the owning module's own, separately-capability-gated list route).
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database import get_db
from core.middleware import require_auth
from modules.saved_views import data_service as svc

router = APIRouter(prefix="/api/saved-views", tags=["saved-views"])


def _error_response(exc: svc.SavedViewError) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": exc.code, "message": exc.message}}, status_code=exc.http_status)


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


@router.get("")
@require_auth
async def api_list_saved_views(request: Request):
    user = request.state.user
    module = request.query_params.get("module", "")
    view_key = request.query_params.get("view_key", "")
    if not module or not view_key:
        return JSONResponse({"ok": False, "error": {"code": "INVALID_INPUT", "message": "module and view_key are required."}}, status_code=422)
    db = get_db()
    try:
        views = svc.list_saved_views(db, user, module, view_key)
    finally:
        db.close()
    return JSONResponse({"ok": True, "views": views})


@router.post("", status_code=201)
@require_auth
async def api_create_saved_view(request: Request):
    user = request.state.user
    payload = await _json_body(request)
    db = get_db()
    try:
        try:
            view = svc.create_saved_view(
                db, user, module=payload.get("module", ""), view_key=payload.get("view_key", ""),
                name=payload.get("name", ""), filter_params=payload.get("filter_params", {}),
                sort_field=payload.get("sort_field"), sort_dir=payload.get("sort_dir", "asc"),
                columns=payload.get("columns"), shared=bool(payload.get("shared")),
                is_default=bool(payload.get("is_default")),
            )
        except svc.SavedViewError as exc:
            return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "view": view}, status_code=201)


@router.put("/{view_id}")
@require_auth
async def api_update_saved_view(request: Request, view_id: int):
    user = request.state.user
    payload = await _json_body(request)
    db = get_db()
    try:
        try:
            view = svc.update_saved_view(db, user, view_id, **payload)
        except svc.SavedViewError as exc:
            return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "view": view})


@router.delete("/{view_id}")
@require_auth
async def api_delete_saved_view(request: Request, view_id: int):
    user = request.state.user
    db = get_db()
    try:
        try:
            svc.delete_saved_view(db, user, view_id)
        except svc.SavedViewError as exc:
            return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True})
