"""
Launcher sub-router: P01 My Work action centre.

See modules/launcher/my_work_service.py for the federated read model this
wraps. This file is deliberately thin: no business queries live here, only
the page render and the JSON API the page's JS calls.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from modules.launcher._route_helpers import _JSONResp, require_auth, shell_ctx, shell_templates
from modules.launcher.my_work_service import get_my_work

router = APIRouter()


@router.get("/my-work", response_class=HTMLResponse)
@require_auth
async def my_work_page(request: Request):
    ctx = shell_ctx(request, active_module="platform", active_section="my-work")
    return shell_templates.TemplateResponse(request, "my_work.html", ctx)


@router.get("/api/my-work")
@require_auth
async def api_my_work(request: Request):
    return _JSONResp(get_my_work(request.state.user))
