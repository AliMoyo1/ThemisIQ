"""
PLAN-36 P07: ERM scenario analysis and board-pack snapshot routes.

Own file for the same T10 file-size reason routes_diagnostics.py,
routes_my_work.py, routes_capability_state.py, and routes_workbench.py
already are, rather than growing the already-oversized routes.py further.

Route-ordering note (confirmed the hard way during P06, see
oneforall/modules/evidence/routes.py): any literal path segment that shares
a prefix shape with a parameterized route (e.g. GET /api/board-packs/verify-chain
vs GET /api/board-packs/{pack_id}) MUST be registered before the
parameterized one, or Starlette's int conversion on the literal segment
fails with the parameterized route's own 422 before the literal route is
ever tried.
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from core.middleware import require_capability, check_ai_rate_limit, record_ai_call
from core.shell_context import shell_ctx
from core.rbac import has_capability
from modules.erm.routes import _json_body, _uid
from modules.governance.data_service import bu_scope_ids
from modules.erm import scenarios as sv
from modules.erm import scenario_ai as sai
from modules.erm import scenario_support as sup
from modules.erm import scenario_templates as tpl

router = APIRouter(prefix="/erm", tags=["erm-scenarios"])
templates = Jinja2Templates(directory=["modules/erm/templates", "templates"])


def _error_response(exc, status=400):
    return JSONResponse({"error": str(exc)}, status_code=status)


# ── Page ──────────────────────────────────────────────────────────────────────

@router.get("/scenario-studio", response_class=HTMLResponse)
@require_capability("erm.scenario.view")
async def scenario_studio_page(request: Request):
    user = request.state.user
    ctx = shell_ctx(request, active_module="erm", active_section="scenario-studio")
    return templates.TemplateResponse(request, "scenario_studio.html", {
        "user": user,
        "can_manage_frameworks": has_capability(user, "erm.framework.manage"),
        "can_view_scenarios": has_capability(user, "erm.scenario.view"),
        "can_manage_scenarios": has_capability(user, "erm.scenario.manage"),
        "can_use_ai": has_capability(user, "erm.scenario.manage") and has_capability(user, "erm.ai.use"),
        "can_rehearse": has_capability(user, "erm.scenario.manage") and has_capability(user, "bcm.exercise.manage"),
        "can_generate_boardpacks": has_capability(user, "erm.boardpack.generate"),
        "can_publish_boardpacks": has_capability(user, "erm.boardpack.publish"),
        **ctx,
    })


# ── Scenarios ────────────────────────────────────────────────────────────────

@router.get("/api/scenarios")
@require_capability("erm.scenario.view")
async def api_scenarios_list(request: Request):
    status = request.query_params.get("status")
    return JSONResponse(sv.list_scenarios(status=status, bu_scope=bu_scope_ids(request.state.user)))


@router.post("/api/scenarios")
@require_capability("erm.scenario.manage")
async def api_scenarios_create(request: Request):
    body = await _json_body(request)
    try:
        new_id = sv.create_scenario(body, request.state.user)
    except sv.ForbiddenScopeError as exc:
        return _error_response(exc, 403)
    except sv.ScenarioError as exc:
        return _error_response(exc)
    sup.link_origin(new_id, body.get("origin"), request.state.user)
    return JSONResponse({"ok": True, "id": new_id}, status_code=201)


# Literal paths below are registered before GET /api/scenarios/{scenario_id}: the integer conversion of that
# parameterized route would otherwise answer 422 for them.

@router.get("/api/scenario-templates")
@require_capability("erm.scenario.view")
async def api_scenario_templates(request: Request):
    return JSONResponse({"templates": tpl.public_templates(), "types": tpl.SCENARIO_TYPES})


@router.get("/api/scenarios/candidates")
@require_capability("erm.scenario.view")
async def api_scenario_candidates(request: Request):
    qp = request.query_params
    try:
        rows = sup.candidates(qp.get("type", ""), request.state.user, qp.get("q", ""), qp.get("template") or None)
    except sv.ScenarioError as exc:
        return _error_response(exc)
    return JSONResponse(rows)


@router.get("/api/scenarios/seed")
@require_capability("erm.scenario.manage")
async def api_scenario_seed(request: Request):
    qp = request.query_params
    try:
        record_id = int(qp.get("id", ""))
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(400, "id must be an integer")
    try:
        return JSONResponse(sup.seed_from_record(qp.get("module", ""), qp.get("type", ""), record_id, request.state.user))
    except sv.ScenarioError as exc:
        return _error_response(exc, 404)


def _ai_gate(request):
    """AI help needs the right to edit scenarios and to use ERM's assistant, and the hourly allowance."""
    user = request.state.user
    if not has_capability(user, "erm.ai.use"):
        raise HTTPException(403, "You do not have access to the AI assistant in ERM")
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    return None


@router.post("/api/scenarios/ai/draft")
@require_capability("erm.scenario.manage")
async def api_scenario_ai_draft(request: Request):
    refused = _ai_gate(request)
    if refused:
        return refused
    body = await _json_body(request)
    try:
        return JSONResponse(sai.draft(body.get("sentence"), request.state.user))
    except sv.ScenarioError as exc:
        return _error_response(exc)


@router.get("/api/scenarios/{scenario_id}")
@require_capability("erm.scenario.view")
async def api_scenario_detail(request: Request, scenario_id: int):
    try:
        scenario = sv.get_scenario(scenario_id, bu_scope=bu_scope_ids(request.state.user))
    except sv.ForbiddenScopeError:
        raise HTTPException(404, "Scenario not found")
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    scenario["links"] = sv.list_scenario_links(scenario_id)
    return JSONResponse(scenario)


@router.put("/api/scenarios/{scenario_id}")
@require_capability("erm.scenario.manage")
async def api_scenario_update(request: Request, scenario_id: int):
    body = await _json_body(request)
    try:
        sv.update_scenario(scenario_id, body, request.state.user)
    except sv.ForbiddenScopeError:
        raise HTTPException(404, "Scenario not found")
    except sv.ScenarioError as exc:
        status = 404 if str(exc) == "scenario not found" else 400
        return _error_response(exc, status)
    return JSONResponse({"ok": True})


@router.delete("/api/scenarios/{scenario_id}")
@require_capability("erm.scenario.manage")
async def api_scenario_delete(request: Request, scenario_id: int):
    try:
        ok = sv.delete_scenario(scenario_id, request.state.user)
    except sv.ForbiddenScopeError:
        raise HTTPException(404, "Scenario not found")
    except sv.ScenarioError as exc:
        return _error_response(exc)
    if not ok:
        raise HTTPException(404, "Scenario not found")
    return JSONResponse({"ok": True})


@router.post("/api/scenarios/{scenario_id}/links")
@require_capability("erm.scenario.manage")
async def api_scenario_link_add(request: Request, scenario_id: int):
    body = await _json_body(request)
    link_type = body.get("link_type")
    link_id = body.get("link_id")
    if not link_type or link_id is None:
        raise HTTPException(400, "link_type and link_id are required")
    try:
        link_id_int = int(link_id)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(400, "link_id must be an integer")
    try:
        new_id = sv.add_scenario_link(scenario_id, link_type, link_id_int, body.get("delta"), request.state.user)
    except sv.ForbiddenScopeError as exc:
        return _error_response(exc, 403)
    except sv.ScenarioError as exc:
        status = 404 if "not found" in str(exc) else 400
        return _error_response(exc, status)
    return JSONResponse({"ok": True, "id": new_id}, status_code=201)


@router.delete("/api/scenarios/{scenario_id}/links/{link_type}/{link_id}")
@require_capability("erm.scenario.manage")
async def api_scenario_link_remove(request: Request, scenario_id: int, link_type: str, link_id: int):
    try:
        ok = sv.remove_scenario_link(scenario_id, link_type, link_id, request.state.user)
    except sv.ForbiddenScopeError:
        raise HTTPException(404, "Scenario not found")
    if not ok:
        raise HTTPException(404, "Scenario not found")
    return JSONResponse({"ok": True})


@router.get("/api/scenarios/{scenario_id}/impact")
@require_capability("erm.scenario.view")
async def api_scenario_impact(request: Request, scenario_id: int):
    try:
        scenario = sv.get_scenario(scenario_id, bu_scope=bu_scope_ids(request.state.user))
    except sv.ForbiddenScopeError:
        raise HTTPException(404, "Scenario not found")
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    impact = sv.compute_scenario_impact(scenario_id)
    impact["headline"] = sup.headline(impact)
    return JSONResponse(impact)


def _visible_or_404(request, scenario_id):
    try:
        scenario = sv.get_scenario(scenario_id, bu_scope=bu_scope_ids(request.state.user))
    except sv.ForbiddenScopeError:
        raise HTTPException(404, "Scenario not found")
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    return scenario


@router.get("/api/scenarios/{scenario_id}/context")
@require_capability("erm.scenario.view")
async def api_scenario_context(request: Request, scenario_id: int):
    _visible_or_404(request, scenario_id)
    return JSONResponse(sup.context(scenario_id, request.state.user))


@router.post("/api/scenarios/{scenario_id}/actions")
@require_capability("erm.scenario.manage")
async def api_scenario_action(request: Request, scenario_id: int):
    _visible_or_404(request, scenario_id)
    body = await _json_body(request)
    try:
        task_id = sup.create_action(scenario_id, body, request.state.user)
    except sv.ScenarioError as exc:
        return _error_response(exc)
    return JSONResponse({"ok": True, "task_id": task_id}, status_code=201)


@router.post("/api/scenarios/{scenario_id}/rehearse")
@require_capability("erm.scenario.manage")
async def api_scenario_rehearse(request: Request, scenario_id: int):
    _visible_or_404(request, scenario_id)
    if not has_capability(request.state.user, "bcm.exercise.manage"):
        raise HTTPException(403, "You need to be allowed to plan exercises in BCM")
    try:
        exercise_id = sup.rehearse_in_bcm(scenario_id, request.state.user)
    except sv.ScenarioError as exc:
        return _error_response(exc)
    return JSONResponse({"ok": True, "exercise_id": exercise_id, "url": "/bcm/exercises"}, status_code=201)


_AI_ACTIONS = {"shocks": sai.shocks, "gaps": sai.gaps, "explain": sai.explain, "challenge": sai.challenge}


@router.post("/api/scenarios/{scenario_id}/ai/{action}")
@require_capability("erm.scenario.manage")
async def api_scenario_ai(request: Request, scenario_id: int, action: str):
    run = _AI_ACTIONS.get(action)
    if run is None:
        raise HTTPException(404, "Unknown AI action")
    _visible_or_404(request, scenario_id)
    refused = _ai_gate(request)
    if refused:
        return refused
    try:
        return JSONResponse(run(scenario_id, request.state.user))
    except sv.ScenarioError as exc:
        return _error_response(exc)


# ── Board packs ──────────────────────────────────────────────────────────────

@router.get("/api/board-packs")
@require_capability("erm.boardpack.view")
async def api_board_packs_list(request: Request):
    qp = request.query_params
    scenario_id = qp.get("scenario_id")
    try:
        parsed_scenario_id = int(scenario_id) if scenario_id else None
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(400, "scenario_id must be an integer")
    return JSONResponse(sv.list_board_packs(
        scenario_id=parsed_scenario_id,
        status=qp.get("status"),
        bu_scope=bu_scope_ids(request.state.user),
    ))


# Literal route -- must be registered before GET /api/board-packs/{pack_id}.
@router.get("/api/board-packs/verify-chain")
@require_capability("erm.boardpack.view")
async def api_board_pack_verify_chain(request: Request):
    return JSONResponse({"problems": sv.verify_board_pack_chain(bu_scope=bu_scope_ids(request.state.user))})


@router.post("/api/board-packs")
@require_capability("erm.boardpack.generate")
async def api_board_pack_generate(request: Request):
    body = await _json_body(request)
    scenario_id = body.get("scenario_id")
    try:
        parsed_scenario_id = int(scenario_id) if scenario_id is not None else None
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(400, "scenario_id must be an integer")
    try:
        new_id = sv.generate_board_pack(
            scenario_id=parsed_scenario_id,
            filters=body.get("filters"),
            actor=request.state.user,
        )
    except sv.ForbiddenScopeError as exc:
        return _error_response(exc, 403)
    except sv.ScenarioError as exc:
        return _error_response(exc, 404)
    return JSONResponse({"ok": True, "id": new_id}, status_code=201)


@router.get("/api/board-packs/{pack_id}")
@require_capability("erm.boardpack.view")
async def api_board_pack_detail(request: Request, pack_id: int):
    try:
        pack = sv.get_board_pack(pack_id, bu_scope=bu_scope_ids(request.state.user))
    except sv.ForbiddenScopeError:
        raise HTTPException(404, "Board pack not found")
    if not pack:
        raise HTTPException(404, "Board pack not found")
    return JSONResponse(pack)


@router.put("/api/board-packs/{pack_id}/narrative")
@require_capability("erm.boardpack.generate")
async def api_board_pack_narrative_update(request: Request, pack_id: int):
    body = await _json_body(request)
    try:
        sv.update_board_pack_narrative(
            pack_id, body.get("narrative", ""), body.get("citations", []),
            body.get("source", "human"), request.state.user,
        )
    except sv.ForbiddenScopeError:
        raise HTTPException(404, "Board pack not found")
    except sv.ScenarioError as exc:
        status = 404 if str(exc) == "board pack not found" else 400
        return _error_response(exc, status)
    return JSONResponse({"ok": True})


@router.post("/api/board-packs/{pack_id}/generate-narrative")
@require_capability("erm.boardpack.generate")
async def api_board_pack_narrative_generate(request: Request, pack_id: int):
    if not check_ai_rate_limit(str(_uid(request))):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(str(_uid(request)))
    try:
        result = sv.generate_board_pack_narrative(pack_id, request.state.user)
    except sv.ForbiddenScopeError:
        raise HTTPException(404, "Board pack not found")
    except sv.ScenarioError as exc:
        status = 404 if str(exc) == "board pack not found" else 400
        return _error_response(exc, status)
    return JSONResponse(result)


@router.post("/api/board-packs/{pack_id}/publish")
@require_capability("erm.boardpack.publish")
async def api_board_pack_publish(request: Request, pack_id: int):
    try:
        sv.publish_board_pack(pack_id, request.state.user)
    except sv.ForbiddenScopeError:
        raise HTTPException(404, "Board pack not found")
    except sv.ScenarioError as exc:
        status = 404 if str(exc) == "board pack not found" else 400
        return _error_response(exc, status)
    return JSONResponse({"ok": True})
