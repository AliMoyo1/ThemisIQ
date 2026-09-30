"""
Launcher sub-router: P09 capability-state endpoints.

Deliberately its own small file, not added to routes_platform.py (2,100+
lines, one of T10/findings.md F11's own named oversized files) -- P09 and
P02 will both grow this file over time as more capabilities get a real
state instead of an ad-hoc check, and starting it separately avoids adding
to the exact regression pressure T10 exists to reduce.
"""
from fastapi import APIRouter, Request

from modules.launcher._route_helpers import _JSONResp, require_auth

router = APIRouter()


@router.get("/api/capability-state/ai")
@require_auth
async def api_capability_state_ai(request: Request):
    """Whether the platform's AI provider is configured -- the first of
    task_plan.md P09's named areas (ARIA authoring/preview/AI) to get a real
    state object instead of each caller's own ad-hoc `is_configured()`
    check and message string."""
    from core.ai_client import get_capability_state
    return _JSONResp(get_capability_state().to_dict())
