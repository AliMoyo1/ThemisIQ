"""
Launcher sub-router: P09 capability-state endpoints.

Deliberately its own small file, not added to routes_platform.py (2,100+
lines, one of T10/findings.md F11's own named oversized files) -- P09 and
P02 will both grow this file over time as more capabilities get a real
state instead of an ad-hoc check, and starting it separately avoids adding
to the exact regression pressure T10 exists to reduce.
"""
from fastapi import APIRouter, Request, HTTPException

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
    from core.capability_metrics import record_state
    state = get_capability_state()
    record_state(request.state.user, "ai", state)
    return _JSONResp(state.to_dict())


@router.get("/api/capability-state/{area}")
@require_auth
async def api_capability_state_area(request: Request, area: str):
    """Safe states: role permission precedes feature/configuration checks."""
    from core import dependency_states as ds
    factories = {
        "aria-authoring": ds.aria_authoring_state,
        "aria-ai": ds.aria_ai_state,
        "aria-conversion": ds.aria_conversion_state,
        "erm-horizon-scan": ds.horizon_scan_state,
        "aria-export": ds.aria_export_state,
        "email": ds.email_state,
    }
    factory = factories.get(area)
    if factory is None:
        raise HTTPException(404, "Unknown capability")
    from core.capability_metrics import record_state
    state = factory(request.state.user)
    record_state(request.state.user, area, state)
    return _JSONResp(state.to_dict())


@router.get("/api/capability-state/connectors/{name}")
@require_auth
async def api_connector_state(request: Request, name: str):
    from core import dependency_states as ds
    try:
        from core.capability_metrics import record_state
        state = ds.connector_state(request.state.user, name)
        record_state(request.state.user, "connector-" + name, state)
        return _JSONResp(state.to_dict())
    except ValueError:
        raise HTTPException(404, "Unknown connector") from None
