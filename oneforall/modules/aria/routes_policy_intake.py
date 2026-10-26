"""Existing-policy intake and independent external-approval attestation."""
from __future__ import annotations

import json
import asyncio

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from core.middleware import require_module, log_audit
from core.rbac import has_capability
from database import get_db
from modules.aria import policy_intake as intake
from modules.aria import policy_composition as composition
from modules.aria import policy_pdf_rendition as pdf_rendition
from modules.aria import policy_workflow_service as workflow
from modules.aria import policy_storage as storage
from modules.aria.routes import _aria_render
from modules.aria.policy_access import document_read_ok

router = APIRouter(prefix="/aria", tags=["aria-policy-intake"])


def _error(exc: intake.IntakeError):
    return JSONResponse({"ok": False, "error": exc.message}, status_code=exc.status)


def _authoring_gate(actor: dict) -> JSONResponse | None:
    from modules.aria.policy_access import policy_authoring_enabled_for
    if policy_authoring_enabled_for(actor.get("org_id")):
        return None
    return JSONResponse({"ok": False, "error": "Policy intake is not enabled for this organization."},
                        status_code=403)


@router.get("/policy-imports")
@require_module("aria")
async def import_workspace(request: Request):
    actor = request.state.user
    if not has_capability(actor, "aria.policy.create") and not has_capability(actor, "aria.policy.approve"):
        return JSONResponse({"error": "Policy review permission required."}, 403)
    db = get_db()
    try:
        entries = intake.list_imports(db, actor)
    finally:
        db.close()
    return _aria_render(request, "policy_imports.html", {"imports": entries, "user": actor},
                        active_section="documents")


@router.post("/api/policy-imports")
@require_module("aria")
async def stage(request: Request, file: UploadFile = File(...),
                business_unit_id: str = Form(""), org_wide: bool = Form(False)):
    actor = request.state.user
    if not has_capability(actor, "aria.policy.create"):
        return JSONResponse({"ok": False, "error": "Policy author permission required."}, 403)
    if denied := _authoring_gate(actor):
        return denied
    data = await file.read(intake.MAX_FILE + 1)
    try:
        result = await asyncio.to_thread(_stage_sync, actor, data, file.filename or "", business_unit_id or None, org_wide)
        log_audit(actor, "aria", "Staged existing policy for review", "policy_import", 0,
                  details=result["id"])
        return JSONResponse({"ok": True, **result}, status_code=201)
    except intake.IntakeError as exc:
        return _error(exc)


def _stage_sync(actor, data, filename, business_unit_id, org_wide):
    db = get_db()
    try:
        return intake.stage_import(db, actor, data, filename, business_unit_id, org_wide)
    finally:
        db.close()


@router.get("/api/policy-imports/{import_id}")
@require_module("aria")
async def get_detail(request: Request, import_id: str):
    db = get_db()
    try:
        return JSONResponse({"ok": True, **intake.detail(db, request.state.user, import_id)})
    except intake.IntakeError as exc:
        return _error(exc)
    finally:
        db.close()


@router.get("/api/policy-import-controls")
@require_module("aria")
async def import_control_search(request: Request, q: str = ""):
    db = get_db()
    try:
        return JSONResponse({"ok": True, "controls": intake.search_controls(db, request.state.user, q)})
    except intake.IntakeError as exc:
        return _error(exc)
    finally:
        db.close()


@router.get("/api/policy-imports/{import_id}/version-candidates")
@require_module("aria")
async def version_candidates(request: Request, import_id: str, q: str = ""):
    db = get_db()
    try:
        return JSONResponse({"ok": True, "documents": intake.version_candidates(db, request.state.user,
                                                                                      import_id, q)})
    except intake.IntakeError as exc:
        return _error(exc)
    finally:
        db.close()


@router.post("/api/policy-imports/{import_id}/manual-link")
@require_module("aria")
async def manual_link(request: Request, import_id: str):
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"ok": False, "error": "Invalid mapping data."}, 400)
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "Invalid mapping data."}, 422)
    db = get_db()
    try:
        result = intake.add_manual_link(db, request.state.user, import_id,
                                        payload.get("control_id"), payload.get("anchor"),
                                        payload.get("relationship", "related"))
        log_audit(request.state.user, "aria", "Added a policy-control mapping for review", "policy_import", 0,
                  details=import_id)
        return JSONResponse({"ok": True, **result})
    except intake.IntakeError as exc:
        db.rollback()
        return _error(exc)
    finally:
        db.close()


@router.get("/api/policy-imports/{import_id}/source")
@require_module("aria")
async def source(request: Request, import_id: str):
    db = get_db()
    try:
        row = intake.get_import(db, request.state.user, import_id)
        path = intake._source_path(row)
        if not path.is_file():
            return JSONResponse({"ok": False, "error": "Source unavailable."}, 404)
        if row["state"] == "registered":
            doc = db.execute("SELECT * FROM aria_documents WHERE id=%s AND org_id=%s",
                             (row["document_id"], row["org_id"])).fetchone()
            if not doc or not document_read_ok(request.state.user, dict(doc)):
                return JSONResponse({"ok": False, "error": "Import not found."}, 404)
        response = FileResponse(path, media_type=row["mime_type"], filename=row["file_name"],
                                content_disposition_type="inline" if row["mime_type"] == intake.MIME[".pdf"] else "attachment")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except intake.IntakeError as exc:
        return _error(exc)
    finally:
        db.close()


@router.post("/api/policy-imports/{import_id}/register")
@require_module("aria")
async def register(request: Request, import_id: str):
    if denied := _authoring_gate(request.state.user):
        return denied
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"ok": False, "error": "Invalid request."}, 400)
    if not isinstance(payload, dict) or not isinstance(payload.get("metadata", {}), dict) or not isinstance(payload.get("accepted_link_ids", []), list):
        return JSONResponse({"ok": False, "error": "Invalid review data."}, 422)
    db = get_db()
    try:
        result = intake.register_import(db, request.state.user, import_id,
                                        payload.get("metadata", {}), payload.get("accepted_link_ids", []),
                                        payload.get("existing_document_id"))
        log_audit(request.state.user, "aria", "Registered existing policy after review", "document", result["document_id"])
        return JSONResponse({"ok": True, **result})
    except intake.IntakeError as exc:
        db.rollback()
        return _error(exc)
    finally:
        db.close()


@router.post("/api/policy-imports/{import_id}/verify-external")
@require_module("aria")
async def verify_external(request: Request, import_id: str):
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"ok": False, "error": "Invalid request."}, 400)
    if not isinstance(payload, dict) or any(not isinstance(payload.get(k, ""), str) for k in ("approver", "approved_at", "proof")):
        return JSONResponse({"ok": False, "error": "Invalid approval evidence."}, 422)
    db = get_db()
    try:
        result = intake.verify_external(db, request.state.user, import_id,
                                        approver=payload.get("approver", ""),
                                        approved_at=payload.get("approved_at", ""),
                                        proof=payload.get("proof", ""))
        log_audit(request.state.user, "aria", "Verified external policy approval evidence", "document", result["document_id"])
        return JSONResponse({"ok": True, **result})
    except intake.IntakeError as exc:
        db.rollback()
        return _error(exc)
    finally:
        db.close()


@router.get("/api/policy-imports/{import_id}/outline")
@require_module("aria")
async def source_outline(request: Request, import_id: str):
    try:
        return JSONResponse({"ok": True, "blocks": await asyncio.to_thread(_outline_sync, request.state.user, import_id)})
    except intake.IntakeError as exc:
        return _error(exc)


def _outline_sync(actor, import_id):
    db = get_db()
    try:
        return composition.outline(db, actor, import_id)
    finally:
        db.close()


@router.get("/api/policy-imports/{import_id}/pdf-pages")
@require_module("aria")
async def pdf_pages(request: Request, import_id: str):
    try:
        return JSONResponse({"ok": True, **await asyncio.to_thread(_pdf_pages_sync, request.state.user, import_id)})
    except intake.IntakeError as exc:
        return _error(exc)


def _pdf_pages_sync(actor, import_id):
    db = get_db()
    try:
        return {**pdf_rendition.page_count(db, actor, import_id),
                "latest": pdf_rendition.latest(db, actor, import_id)}
    finally:
        db.close()


def _pdf_create_sync(actor, import_id, boundary):
    db = get_db()
    try:
        return pdf_rendition.create(db, actor, import_id, boundary)
    finally:
        db.close()


@router.post("/api/policy-imports/{import_id}/pdf-cover")
@require_module("aria")
async def pdf_cover(request: Request, import_id: str):
    if denied := _authoring_gate(request.state.user):
        return denied
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"ok": False, "error": "Invalid cover selection."}, 400)
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "Invalid cover selection."}, 422)
    try:
        result = await asyncio.to_thread(_pdf_create_sync, request.state.user, import_id, payload.get("first_body_page"))
        log_audit(request.state.user, "aria", "Prepared PDF policy cover rendition", "policy_import", 0,
                  details=import_id)
        return JSONResponse({"ok": True, **result})
    except intake.IntakeError as exc:
        return _error(exc)


@router.get("/api/policy-imports/{import_id}/pdf-cover/{rendition_id}")
@require_module("aria")
async def pdf_cover_file(request: Request, import_id: str, rendition_id: str):
    db = get_db()
    try:
        _, path, _ = pdf_rendition.get_rendition(db, request.state.user, import_id, rendition_id)
        return FileResponse(path, media_type=intake.MIME[".pdf"],
                            filename=f"policy-cover-{rendition_id[:8]}.pdf",
                            content_disposition_type="inline",
                            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
    except (intake.IntakeError, storage.PathContainmentError):
        return JSONResponse({"ok": False, "error": "Rendition not found."}, 404)
    finally:
        db.close()


def _pdf_decide_sync(actor, import_id, rendition_id, approve, note):
    db = get_db()
    try:
        return pdf_rendition.decide(db, actor, import_id, rendition_id, approve, note)
    finally:
        db.close()


@router.post("/api/policy-imports/{import_id}/pdf-cover/{rendition_id}/decide")
@require_module("aria")
async def pdf_cover_decide(request: Request, import_id: str, rendition_id: str):
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"ok": False, "error": "Invalid review decision."}, 400)
    if not isinstance(payload, dict) or not isinstance(payload.get("approve"), bool) or not isinstance(payload.get("note"), str):
        return JSONResponse({"ok": False, "error": "Invalid review decision."}, 422)
    try:
        result = await asyncio.to_thread(_pdf_decide_sync, request.state.user, import_id, rendition_id,
                                         payload["approve"], payload["note"])
        log_audit(request.state.user, "aria", "Reviewed PDF policy cover rendition", "policy_import", 0,
                  details=import_id)
        return JSONResponse({"ok": True, **result})
    except intake.IntakeError as exc:
        return _error(exc)


def _compose_sync(actor: dict, import_id: str, payload: dict):
    db = get_db()
    try:
        return composition.create_candidate(db, actor, import_id, payload)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/api/policy-imports/{import_id}/compose")
@require_module("aria")
async def compose(request: Request, import_id: str):
    if denied := _authoring_gate(request.state.user):
        return denied
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"ok": False, "error": "Invalid composition data."}, 400)
    try:
        result = await asyncio.to_thread(_compose_sync, request.state.user, import_id, payload)
        log_audit(request.state.user, "aria", "Composed imported policy candidate", "policy_draft", 0,
                  details=result["draft_id"])
        return JSONResponse({"ok": True, **result})
    except intake.IntakeError as exc:
        return _error(exc)
    except workflow.PolicyWorkflowError as exc:
        return JSONResponse({"ok": False, "error": exc.message}, status_code=exc.http_status)


@router.get("/api/policy-imports/{import_id}/candidate/{draft_id}")
@require_module("aria")
async def candidate_file(request: Request, import_id: str, draft_id: str):
    db = get_db()
    try:
        row = intake.get_import(db, request.state.user, import_id)
        draft = workflow.get_draft(db, request.state.user, draft_id)
        manifest = json.loads(draft.get("renderer_manifest_json") or "{}")
        if (row["state"] != "registered" or draft.get("source_document_id") != row["document_id"]
                or manifest.get("source_import_id") != import_id
                or draft.get("content_kind") != "uploaded_docx"):
            return JSONResponse({"ok": False, "error": "Candidate not found."}, 404)
        path = storage.resolve_stored_path(draft["uploaded_source_path"])
        if not path.is_file() or storage.sha256_file(path) != draft["uploaded_source_sha256"]:
            return JSONResponse({"ok": False, "error": "Candidate unavailable."}, 409)
        return FileResponse(path, media_type=intake.MIME[".docx"],
                            filename=f"policy-candidate-{draft_id[:8]}.docx",
                            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
    except (intake.IntakeError, workflow.PolicyWorkflowError, storage.PathContainmentError):
        return JSONResponse({"ok": False, "error": "Candidate not found."}, 404)
    finally:
        db.close()
