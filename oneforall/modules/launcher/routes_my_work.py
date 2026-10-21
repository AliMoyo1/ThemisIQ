"""
Launcher sub-router: P01 My Work action centre.

See modules/launcher/my_work_service.py for the federated read model this
wraps. This file is deliberately thin: no business queries live here, only
the page render and the JSON API the page's JS calls.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from modules.launcher._route_helpers import _JSONResp, require_auth, shell_ctx, shell_templates
from modules.launcher.my_work_service import get_my_work, get_team_work

router = APIRouter()


@router.get("/my-work", response_class=HTMLResponse)
@require_auth
async def my_work_page(request: Request):
    ctx = shell_ctx(request, active_module="platform", active_section="my-work")
    return shell_templates.TemplateResponse(request, "my_work.html", ctx)


@router.get("/api/my-work")
@require_auth
async def api_my_work(request: Request):
    q = request.query_params
    try:
        result = get_my_work(request.state.user, source=q.get("source", ""),
                             section=q.get("section", ""), q=q.get("q", ""),
                             cursor=q.get("cursor"), page_size=50, group=q.get("group", ""))
    except ValueError as exc:
        return _JSONResp({"error": str(exc)}, status_code=422)
    return _JSONResp(result)


@router.get("/api/my-work/team")
@require_auth
async def api_my_work_team(request: Request):
    """The work assigned to each person in the units the viewer heads. `is_manager` is false when they head none."""
    raw = request.query_params.get("unit_id")
    try:
        unit_id = int(raw) if raw not in (None, "") else None
    except ValueError:
        return _JSONResp({"error": "unit_id must be a number."}, status_code=422)
    try:
        return _JSONResp(get_team_work(request.state.user, unit_id))
    except ValueError as exc:
        return _JSONResp({"error": str(exc)}, status_code=422)
