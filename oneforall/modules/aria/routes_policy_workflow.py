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


@router.post("/api/policy-drafts/{draft_id}/confirm")
@require_module("aria")
async def api_confirm_policy_draft(request: Request, draft_id: str):
    actor = request.state.user
    payload = await _json_body(request)
    build_id = payload.get("build_id")
    expected_lock_version = payload.get("expected_lock_version")
    if build_id is None or expected_lock_version is None:
        return JSONResponse(
            {"ok": False, "error": {"code": "INVALID_INPUT",
             "message": "build_id and expected_lock_version are required.", "retryable": False}},
            status_code=422,
        )
    db = get_db()
    try:
        result = svc.confirm_draft(db, actor, draft_id, build_id, expected_lock_version)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({
        "ok": True, **result,
        "detail_url": f"/aria/documents?open={result['doc_id']}",
    })


@router.get("/api/documents/{doc_id}/policy-versions")
@require_module("aria")
async def api_list_document_versions(request: Request, doc_id: str):
    actor = request.state.user
    db = get_db()
    try:
        versions = svc.list_document_versions(db, actor, doc_id)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "versions": versions})


@router.get("/api/policy-versions/{version_id}")
@require_module("aria")
async def api_get_policy_version(request: Request, version_id: int):
    actor = request.state.user
    db = get_db()
    try:
        version = svc.get_version(db, actor, version_id)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "version": svc._version_to_public_dict(version)})


@router.get("/api/policy-versions/{version_id}/preview")
@require_module("aria")
async def api_get_policy_version_preview(request: Request, version_id: int):
    actor = request.state.user
    db = get_db()
    try:
        pdf_path = svc.get_version_file_path(db, actor, version_id, "preview")
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return FileResponse(
        str(pdf_path), media_type="application/pdf",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/api/policy-versions/{version_id}/download")
@require_module("aria")
async def api_download_policy_version(request: Request, version_id: int):
    actor = request.state.user
    db = get_db()
    try:
        docx_path = svc.get_version_file_path(db, actor, version_id, "branded")
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return FileResponse(
        str(docx_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        filename=f"policy-v{version_id}.docx",
    )


@router.get("/api/policy-versions/{version_id}/approvers")
@require_module("aria")
async def api_list_eligible_approvers(request: Request, version_id: int):
    actor = request.state.user
    db = get_db()
    try:
        approvers = svc.list_eligible_approvers_for_version(db, actor, version_id)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "approvers": approvers})


@router.post("/api/policy-versions/{version_id}/submit-approval")
@require_module("aria")
async def api_submit_for_approval(request: Request, version_id: int):
    actor = request.state.user
    payload = await _json_body(request)
    approver_id = payload.get("approver_id")
    request_id = payload.get("request_id")
    expected_lock_version = payload.get("expected_lock_version")
    if approver_id is None or not request_id or expected_lock_version is None:
        return JSONResponse(
            {"ok": False, "error": {"code": "INVALID_INPUT",
             "message": "approver_id, request_id, and expected_lock_version are required.",
             "retryable": False}},
            status_code=422,
        )
    db = get_db()
    try:
        approval = svc.submit_for_approval(
            db, actor, version_id, approver_id, payload.get("request_note", ""),
            request_id, expected_lock_version,
        )
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "approval": approval}, status_code=201)


@router.get("/api/policy-approvals")
@require_module("aria")
async def api_list_policy_approvals(request: Request):
    if request.query_params.get("assigned_to") != "me":
        return JSONResponse(
            {"ok": False, "error": {"code": "INVALID_INPUT",
             "message": "Only ?assigned_to=me is supported.", "retryable": False}},
            status_code=422,
        )
    actor = request.state.user
    db = get_db()
    try:
        approvals = svc.list_pending_approvals_for(db, actor)
    finally:
        db.close()
    return JSONResponse({"ok": True, "approvals": approvals})


@router.post("/api/policy-approvals/{approval_id}/decide")
@require_module("aria")
async def api_decide_policy_approval(request: Request, approval_id: int):
    actor = request.state.user
    payload = await _json_body(request)
    decision = payload.get("decision")
    expected_lock_version = payload.get("expected_lock_version")
    if not decision or expected_lock_version is None:
        return JSONResponse(
            {"ok": False, "error": {"code": "INVALID_INPUT",
             "message": "decision and expected_lock_version are required.", "retryable": False}},
            status_code=422,
        )
    db = get_db()
    try:
        approval = svc.decide_approval(
            db, actor, approval_id, decision, payload.get("comments", ""), expected_lock_version,
        )
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "approval": approval})


@router.post("/api/policy-approvals/{approval_id}/withdraw")
@require_module("aria")
async def api_withdraw_policy_approval(request: Request, approval_id: int):
    actor = request.state.user
    payload = await _json_body(request)
    expected_lock_version = payload.get("expected_lock_version")
    if expected_lock_version is None:
        return JSONResponse(
            {"ok": False, "error": {"code": "INVALID_INPUT",
             "message": "expected_lock_version is required.", "retryable": False}},
            status_code=422,
        )
    db = get_db()
    try:
        approval = svc.withdraw_approval(db, actor, approval_id, payload.get("reason", ""), expected_lock_version)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "approval": approval})


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


@router.get("/api/documents/{doc_id}/publication-status")
@require_module("aria")
async def api_document_publication_status(request: Request, doc_id: str):
    """Lets a caller with read access to the document see whether its
    current approved version finished publishing to the Evidence
    Vault/GRID, so the UI can show 'evidence synchronization needs
    attention'. document_read_ok is a READ check, not an edit/approval
    one -- ARIA module access alone (any employee, an external auditor)
    is enough to pass it, so the internal last_error text and attempt
    detail (which section 10.3 frames as manager-facing) are withheld from
    anyone who isn't actually a scoped manager, not just gated by the
    weaker read check."""
    from core.rbac import has_capability
    from modules.aria.policy_access import document_read_ok
    actor = request.state.user
    db = get_db()
    try:
        doc = db.execute(
            "SELECT id, org_id, business_unit_id, policy_workflow_managed, "
            "current_policy_version_id FROM aria_documents WHERE doc_id=%s",
            (doc_id,),
        ).fetchone()
        if not doc or not document_read_ok(actor, dict(doc)):
            return JSONResponse({"ok": False, "error": {"code": "NOT_FOUND",
                                 "message": "Document not found.", "retryable": False}}, status_code=404)
        doc = dict(doc)
        if not doc.get("current_policy_version_id"):
            return JSONResponse({"ok": True, "job": None})
        job = db.execute(
            "SELECT id, state, attempts, last_error, next_attempt_at, updated_at, event_id "
            "FROM aria_policy_publication_jobs WHERE policy_version_id=%s",
            (doc["current_policy_version_id"],),
        ).fetchone()
        if not job:
            return JSONResponse({"ok": True, "job": None})
        job = dict(job)

        is_manager = (has_capability(actor, "aria.policy.approve")
                      or has_capability(actor, "aria.policy.edit_any"))
        if not is_manager:
            return JSONResponse({"ok": True, "job": {
                "state": job["state"], "needs_attention": job["state"] == "failed",
            }})

        # Section 10.3: "expose failed event-handler status" -- the job
        # itself can be 'complete' while a downstream handler still failed
        # (emit() catches and records that per-handler, on the events row,
        # separately from the job's own state).
        handler_status = None
        if job.get("event_id"):
            ev = db.execute("SELECT status FROM events WHERE id=%s", (job["event_id"],)).fetchone()
            if ev:
                handler_status = ev["status"]
        job["event_handler_status"] = handler_status
        job.pop("event_id", None)
    finally:
        db.close()
    return JSONResponse({"ok": True, "job": job})


@router.post("/api/publication-jobs/{job_id}/retry")
@require_module("aria")
async def api_retry_publication_job(request: Request, job_id: int):
    from modules.aria import policy_publication
    actor = request.state.user
    db = get_db()
    try:
        job = policy_publication.retry_now(db, actor, job_id)
    except svc.PolicyWorkflowError as exc:
        return _error_response(exc)
    finally:
        db.close()
    return JSONResponse({"ok": True, "job": job})
