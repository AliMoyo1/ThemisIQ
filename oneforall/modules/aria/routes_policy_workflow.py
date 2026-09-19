"""
PLAN-35 T04: draft lifecycle routes for the ARIA policy authoring workflow.

Registered once in main.py alongside modules.aria.routes.router.
api_generate_policy itself stays in routes.py and delegates persistence to
policy_workflow_service (section 8's own instruction); this file hosts the
new draft-specific endpoints that route doesn't own.

Object-level authorization (owner/edit_any, org/BU scope) lives in
policy_access.py and policy_workflow_service.py, not in these route
functions -- @require_module("aria") here is only the coarse "has ARIA at
all" gate, per the plan's section 5 instruction not to rely solely on
route decorators.
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from database import get_db
from core.middleware import require_module
from modules.aria import policy_workflow_service as svc

router = APIRouter(prefix="/aria", tags=["aria-policy-workflow"])


def _error_response(exc: svc.PolicyWorkflowError) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": exc.code, "message": exc.message, "retryable": False}},
        status_code=exc.http_status,
    )


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


@router.get("/api/policy-drafts")
@require_module("aria")
async def api_list_policy_drafts(request: Request):
    actor = request.state.user
    db = get_db()
    try:
        drafts = svc.list_my_drafts(db, actor)
    finally:
        db.close()
    return JSONResponse({"ok": True, "drafts": drafts})


@router.get("/api/policy-drafts/{draft_id}")
@require_module("aria")
async def api_get_policy_draft(request: Request, draft_id: str):
    actor = request.state.user
    db = get_db()
    try:
        draft = svc.get_draft(db, actor, draft_id)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "draft": draft})


@router.put("/api/policy-drafts/{draft_id}")
@require_module("aria")
async def api_save_policy_draft(request: Request, draft_id: str):
    actor = request.state.user
    payload = await _json_body(request)
    if "expected_lock_version" not in payload:
        return JSONResponse(
            {"ok": False, "error": {"code": "INVALID_INPUT",
             "message": "expected_lock_version is required.", "retryable": False}},
            status_code=422,
        )
    db = get_db()
    try:
        draft = svc.save_draft_body(
            db, actor, draft_id,
            body=payload.get("body"),
            title=payload.get("title"),
            doc_type=payload.get("doc_type"),
            effective_date=payload.get("effective_date"),
            review_date=payload.get("review_date"),
            expected_lock_version=payload["expected_lock_version"],
        )
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "draft": draft})


@router.post("/api/policy-drafts/{draft_id}/discard")
@require_module("aria")
async def api_discard_policy_draft(request: Request, draft_id: str):
    actor = request.state.user
    payload = await _json_body(request)
    db = get_db()
    try:
        svc.discard_draft(db, actor, draft_id, payload.get("expected_lock_version"))
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True})


@router.post("/api/policy-drafts/{draft_id}/recover")
@require_module("aria")
async def api_recover_policy_draft(request: Request, draft_id: str):
    actor = request.state.user
    db = get_db()
    try:
        draft = svc.recover_draft(db, actor, draft_id)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "draft": draft})


@router.post("/api/documents/{doc_id}/revision-drafts")
@require_module("aria")
async def api_start_revision_draft(request: Request, doc_id: str):
    actor = request.state.user
    payload = await _json_body(request)
    db = get_db()
    try:
        draft = svc.start_revision_draft(
            db, actor, doc_id, payload.get("copied_from_version_id")
        )
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "draft": draft}, status_code=201)
