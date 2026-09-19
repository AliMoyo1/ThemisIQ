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
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, FileResponse

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


@router.post("/api/policy-drafts/{draft_id}/build")
@require_module("aria")
async def api_build_policy_draft(request: Request, draft_id: str):
    """Runs the full build sequence (source -> branded -> converted PDF).
    Blocking; offloaded to a thread so it never stalls the event loop
    while it polls the conversion worker."""
    actor = request.state.user
    payload = await _json_body(request)
    template_id = payload.get("template_id")
    expected_lock_version = payload.get("expected_lock_version")
    if template_id is None or expected_lock_version is None:
        return JSONResponse(
            {"ok": False, "error": {"code": "INVALID_INPUT",
             "message": "template_id and expected_lock_version are required.", "retryable": False}},
            status_code=422,
        )
    db = get_db()
    try:
        draft = await asyncio.to_thread(
            svc.build_draft, db, actor, draft_id, template_id, expected_lock_version
        )
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({
        "ok": True, "draft": draft,
        "preview_url": f"/aria/api/policy-drafts/{draft_id}/preview?build_id={draft['build_id']}",
    })


@router.get("/api/policy-drafts/{draft_id}/preview")
@require_module("aria")
async def api_preview_policy_draft(request: Request, draft_id: str):
    """Serves the exact PDF from the draft's current ready build only --
    requires a matching build_id so a stale link (from before a rebuild)
    fails closed rather than silently serving newer content under an old
    URL, or vice versa."""
    build_id = request.query_params.get("build_id")
    actor = request.state.user
    db = get_db()
    try:
        draft = svc.get_draft(db, actor, draft_id)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()

    if draft["state"] != "ready" or not draft.get("preview_path"):
        return JSONResponse(
            {"ok": False, "error": {"code": "BUILD_REQUIRED",
             "message": "This draft has no ready build yet.", "retryable": False}},
            status_code=409,
        )
    if build_id and draft.get("build_id") != build_id:
        return JSONResponse(
            {"ok": False, "error": {"code": "STALE_DRAFT",
             "message": "That build is no longer current for this draft.", "retryable": False}},
            status_code=409,
        )

    from modules.aria import policy_storage as storage
    try:
        pdf_path = storage.resolve_stored_path(draft["preview_path"])
    except storage.PathContainmentError:
        return JSONResponse(
            {"ok": False, "error": {"code": "PREVIEW_UNAVAILABLE",
             "message": "Preview reference is invalid.", "retryable": False}},
            status_code=503,
        )
    if not pdf_path.exists():
        return JSONResponse(
            {"ok": False, "error": {"code": "PREVIEW_UNAVAILABLE",
             "message": "Preview file is missing.", "retryable": False}},
            status_code=503,
        )
    return FileResponse(
        str(pdf_path), media_type="application/pdf",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


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
