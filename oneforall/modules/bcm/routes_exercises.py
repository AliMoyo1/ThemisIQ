"""PLAN-36 P08 exercise workspace routes; mounted under /bcm by routes.py."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from core.middleware import require_capability
from core.sanitize import sanitize_dict
from modules.bcm import exercise_service as svc

router = APIRouter()


async def _body(request: Request) -> dict:
    try:
        value = await request.json()
    except Exception:
        raise HTTPException(400, "Expected JSON object") from None
    if not isinstance(value, dict):
        raise HTTPException(400, "Expected JSON object")
    return sanitize_dict(value)


def _call(fn, *args):
    try:
        return fn(*args)
    except svc.ExerciseError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@router.get("/api/exercises/{ex_id}/participants/eligible")
@require_capability("bcm.exercise.manage")
async def eligible_participants(request: Request, ex_id: int):
    return JSONResponse(_call(svc.eligible_participants, request.state.user, ex_id))


@router.get("/api/exercises/{ex_id}/workspace")
@require_capability("module.bcm.access")
async def exercise_workspace(request: Request, ex_id: int):
    return JSONResponse(_call(svc.get_workspace, request.state.user, ex_id))


@router.post("/api/exercises/{ex_id}/transition")
@require_capability("bcm.exercise.manage")
async def exercise_transition(request: Request, ex_id: int):
    body = await _body(request)
    _call(svc.transition, request.state.user, ex_id, body.get("target"), body.get("reason", ""))
    return JSONResponse({"ok": True})


@router.put("/api/exercises/{ex_id}/readiness/{item_id}")
@require_capability("bcm.exercise.manage")
async def exercise_readiness(request: Request, ex_id: int, item_id: int):
    body = await _body(request)
    if type(body.get("done")) is not bool:
        raise HTTPException(400, "done must be a boolean")
    _call(svc.set_readiness, request.state.user, ex_id, item_id, body["done"])
    return JSONResponse({"ok": True})


@router.post("/api/exercises/{ex_id}/participants", status_code=201)
@require_capability("bcm.exercise.manage")
async def exercise_add_participant(request: Request, ex_id: int):
    body = await _body(request)
    _call(svc.add_participant, request.state.user, ex_id, body.get("user_id"), body.get("role"))
    return JSONResponse({"ok": True}, status_code=201)


@router.post("/api/exercises/{ex_id}/participants/confirm")
@require_capability("module.bcm.access")
async def exercise_confirm_participation(request: Request, ex_id: int):
    _call(svc.confirm_participation, request.state.user, ex_id)
    return JSONResponse({"ok": True})


@router.post("/api/exercises/{ex_id}/events", status_code=201)
@require_capability("bcm.exercise.manage")
async def exercise_log_event(request: Request, ex_id: int):
    body = await _body(request)
    _call(svc.log_event, request.state.user, ex_id, body.get("event_type"), body.get("note"))
    return JSONResponse({"ok": True}, status_code=201)


@router.put("/api/exercises/{ex_id}/review")
@require_capability("bcm.exercise.manage")
async def exercise_save_review(request: Request, ex_id: int):
    _call(svc.save_review, request.state.user, ex_id, await _body(request))
    return JSONResponse({"ok": True})


@router.post("/api/exercises/{ex_id}/review/sign-off")
@require_capability("bcm.exercise.manage")
async def exercise_sign_review(request: Request, ex_id: int):
    _call(svc.sign_review, request.state.user, ex_id)
    return JSONResponse({"ok": True})


@router.post("/api/exercises/{ex_id}/actions", status_code=201)
@require_capability("bcm.exercise.manage")
async def exercise_add_action(request: Request, ex_id: int):
    action_id = _call(svc.add_action, request.state.user, ex_id, await _body(request))
    return JSONResponse({"id": action_id}, status_code=201)


@router.post("/api/exercises/{ex_id}/actions/{action_id}/verify")
@require_capability("bcm.exercise.manage")
async def exercise_verify_action(request: Request, ex_id: int, action_id: int):
    body = await _body(request)
    _call(svc.verify_action, request.state.user, ex_id, action_id, body.get("evidence_id"))
    return JSONResponse({"ok": True})


@router.get("/api/exercises/{ex_id}/report")
@require_capability("module.bcm.access")
async def exercise_report(request: Request, ex_id: int):
    content = _call(svc.get_report, request.state.user, ex_id)
    return Response(
        content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="bcm-exercise-{ex_id}-after-action.json"',
            "Cache-Control": "no-store",
        },
    )