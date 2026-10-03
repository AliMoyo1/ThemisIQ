"""
Launcher sub-router: P02 diagnostics/readiness centre.

Its own small file for the same T10 file-size reason
routes_capability_state.py and routes_my_work.py already are.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from modules.launcher._route_helpers import _JSONResp, require_capability, shell_ctx, shell_templates
from modules.launcher.diagnostics_service import get_diagnostics

router = APIRouter()


@router.get("/admin/diagnostics", response_class=HTMLResponse)
@require_capability("platform.manage_users", "platform.manage_org_users")
async def diagnostics_page(request: Request):
    ctx = shell_ctx(request, active_module="platform", active_section="diagnostics")
    return shell_templates.TemplateResponse(request, "diagnostics.html", ctx)


@router.get("/api/admin/diagnostics")
@require_capability("platform.manage_users", "platform.manage_org_users")
async def api_diagnostics(request: Request):
    from core.middleware import log_audit
    log_audit(request.state.user, "platform", "Viewed platform diagnostics")
    data = get_diagnostics(request.state.user)
    data["request_id"] = getattr(request.state, "request_id", None)
    return _JSONResp(data)
