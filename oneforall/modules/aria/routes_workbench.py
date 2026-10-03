"""
PLAN-36 P03: ARIA policy lifecycle workbench.

One page, one document: current published version, working draft, candidate
awaiting/mid decision, and history, all on one screen. Every action here
delegates to the exact same PLAN-35 endpoints/service functions the AI
Generator page and the Documents modal already use -- this file adds no new
mutation, no new table, no new workflow state (task_plan.md P03 discovery
gate). Its own file for the same T10 file-size reason routes_diagnostics.py,
routes_my_work.py, and routes_capability_state.py already are, rather than
growing the already-oversized routes.py further.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from database import get_db
from core.middleware import require_module
from core.shell_context import shell_ctx
from modules.aria import policy_workflow_service as svc
from modules.aria.routes_policy_workflow import _error_response

router = APIRouter(prefix="/aria", tags=["aria-policy-workflow"])
templates = Jinja2Templates(directory=["modules/aria/templates", "templates"])


@router.get("/documents/{doc_id}/workbench", response_class=HTMLResponse)
@require_module("aria")
async def policy_workbench_page(request: Request, doc_id: str):
    ctx = shell_ctx(request, active_module="aria", active_section="documents")
    ctx["user"] = request.state.user
    ctx["doc_id"] = doc_id
    return templates.TemplateResponse(request, "policy_workbench.html", ctx)


@router.get("/api/documents/{doc_id}/workbench")
@require_module("aria")
async def api_policy_workbench_state(request: Request, doc_id: str):
    actor = request.state.user
    db = get_db()
    try:
        state = svc.get_document_workbench_state(db, actor, doc_id)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, **state})


@router.get("/api/documents/{doc_id}/compare")
@require_module("aria")
async def api_compare_policy_versions(request: Request, doc_id: str, left: int, right: int):
    from modules.aria.policy_comparison import compare_versions
    if left <= 0 or right <= 0:
        return JSONResponse({"ok": False, "error": {"code": "INVALID_INPUT",
            "message": "Positive version IDs are required."}}, status_code=400)
    db = get_db()
    try:
        result = compare_versions(db, request.state.user, doc_id, left, right)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, **result})
