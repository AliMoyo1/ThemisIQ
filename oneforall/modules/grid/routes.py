"""
GRID module — Audit management routes.

FastAPI router ported from the original Node/Express AuditSphere.
GRID is an SPA: one HTML template serves the UI, everything else is JSON API.
All routes are prefixed with /grid and guarded by capability-based RBAC.
"""
import io
import os
import json
import uuid
import shutil
import zipfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from database import get_db, insert_returning_id
from core.middleware import require_module, require_capability
from core.shell_context import shell_ctx
from modules.grid import data_service as ds
from modules.grid import ai_service as ai
from modules.grid.email_service import send_email, nc_alert_html
from core.events import (
    emit, GRID_AUDIT_COMPLETED, GRID_FINDING_CREATED, GRID_NC_RAISED,
    GRID_POLICY_REQUESTED,
)

router = APIRouter(prefix="/grid", tags=["grid"])

UPLOAD_DIR = Path(os.getenv("GRID_UPLOAD_DIR", "data/grid_uploads"))
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# ── Helper ──────────────────────────────────────────────────────────────────

async def _json_body(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


def _uid(request: Request) -> int:
    return request.state.user["id"]


def _check_locked(fn, *args, **kwargs):
    """Call fn; if audit is locked, raise 423."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        if "locked" in str(exc).lower():
            raise HTTPException(423, "Audit is locked and cannot be modified")
        raise


# ═════════════════════════════════════════════════════════════════════════════
# SPA INDEX
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
@require_module("grid")
async def grid_index(request: Request):
    """Serve the GRID SPA shell."""
    tpl_dir = os.path.join(os.path.dirname(__file__), "templates")
    tpl = Jinja2Templates(directory=[tpl_dir, "templates"])
    # Determine active section from the URL for sidebar highlighting
    path = request.url.path.rstrip("/")
    section_map = {
        "/grid": "dashboard",
        "/grid/audits": "audits",
        "/grid/controls": "controls",
        "/grid/evidence": "evidence",
        "/grid/findings": "findings",
        "/grid/frameworks": "frameworks",
        "/grid/vendors": "vendors",
        "/grid/reports": "reports",
        "/grid/chat": "chat",
    }
    active_section = section_map.get(path, "dashboard")
    return tpl.TemplateResponse(request, "index.html", {
        "user": request.state.user,
        "module": "grid",
        **shell_ctx(request, active_module="grid", active_section=active_section),
    })


# ═════════════════════════════════════════════════════════════════════════════
# FRAMEWORKS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/frameworks")
@require_capability("module.grid.access")
async def api_frameworks_list(request: Request):
    return JSONResponse(ds.list_frameworks())


@router.post("/api/frameworks")
@require_capability("grid.audit.create")
async def api_frameworks_create(request: Request):
    body = await _json_body(request)
    fid = ds.create_framework(body)
    ds.log_activity(_uid(request), "create_framework", "grid_frameworks", fid)
    return JSONResponse({"id": fid}, status_code=201)


@router.delete("/api/frameworks/{fid}")
@require_capability("grid.audit.delete")
async def api_frameworks_delete(request: Request, fid: int):
    ds.delete_framework(fid)
    ds.log_activity(_uid(request), "delete_framework", "grid_frameworks", fid)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# AUDITS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/audits")
@require_capability("module.grid.access")
async def api_audits_list(request: Request):
    return JSONResponse(ds.list_audits())


@router.get("/api/audits/{aid}")
@require_capability("module.grid.access")
async def api_audits_detail(request: Request, aid: int):
    audit = ds.get_audit(aid)
    if not audit:
        raise HTTPException(404, "Audit not found")
    return JSONResponse(audit)


@router.post("/api/audits")
@require_capability("grid.audit.create")
async def api_audits_create(request: Request):
    body = await _json_body(request)
    body.setdefault("lead_id", _uid(request))
    aid = ds.create_audit(body)
    ds.log_activity(_uid(request), "create_audit", "grid_audits", aid, body.get("name"))
    return JSONResponse({"id": aid}, status_code=201)


@router.put("/api/audits/{aid}")
@require_capability("grid.audit.edit")
async def api_audits_update(request: Request, aid: int):
    body = await _json_body(request)
    _check_locked(ds.update_audit, aid, body)
    ds.log_activity(_uid(request), "update_audit", "grid_audits", aid)

    # Emit audit completed event when status changes to Completed
    new_status = (body.get("status") or "").lower()
    if new_status in ("completed", "closed"):
        audit = ds.get_audit(aid)
        emit(
            GRID_AUDIT_COMPLETED,
            source_module="grid",
            entity_type="audit",
            entity_id=aid,
            payload={
                "name": audit.get("name", "") if audit else "",
                "audit_type": audit.get("audit_type", "") if audit else "",
                "framework_id": audit.get("framework_id") if audit else None,
                "status": new_status,
            },
            user_id=_uid(request),
        )
    return JSONResponse({"ok": True})


@router.delete("/api/audits/{aid}")
@require_capability("grid.audit.delete")
async def api_audits_delete(request: Request, aid: int):
    ds.delete_audit(aid)
    ds.log_activity(_uid(request), "delete_audit", "grid_audits", aid)
    return JSONResponse({"ok": True})


@router.get("/api/audits/{aid}/stats")
@require_capability("module.grid.access")
async def api_audits_stats(request: Request, aid: int):
    return JSONResponse(ds.get_audit_stats(aid))


@router.post("/api/audits/{aid}/populate-controls")
@require_capability("grid.audit.create")
async def api_populate_audit_controls(request: Request, aid: int):
    """Populate grid_controls from the unified controls table for an audit."""
    db = get_db()
    try:
        audit = db.execute(
            "SELECT framework_id FROM grid_audits WHERE id=%s", (aid,)
        ).fetchone()
        if not audit:
            raise HTTPException(404, "Audit not found")

        # Check if controls already exist
        existing = db.execute(
            "SELECT COUNT(*) FROM grid_controls WHERE audit_id=%s", (aid,)
        ).fetchone()[0]
        if existing:
            return JSONResponse({"message": "Controls already loaded", "count": existing})

        grid_fw_id = audit[0]
        if not grid_fw_id:
            return JSONResponse({"message": "No framework assigned to this audit", "count": 0})

        # Match grid_framework name → unified framework → controls
        gf = db.execute(
            "SELECT name FROM grid_frameworks WHERE id=%s", (grid_fw_id,)
        ).fetchone()
        if not gf:
            return JSONResponse({"message": "Framework not found", "count": 0})

        uf_id = ds._find_unified_framework(db, gf[0])
        if not uf_id:
            return JSONResponse({
                "message": f"No unified controls found for '{gf[0]}'", "count": 0
            })

        rows = db.execute(
            "SELECT ref, name, description, priority "
            "FROM controls WHERE framework_id=%s ORDER BY ref",
            (uf_id,),
        ).fetchall()

        for c in rows:
            db.execute(
                "INSERT INTO grid_controls "
                "(audit_id, framework_id, control_id, name, description, risk_level) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (aid, grid_fw_id, c[0], c[1], c[2], c[3] or "Medium"),
            )
        db.commit()
        ds.log_activity(
            _uid(request), "populate_controls", "grid_controls", aid,
            f"{len(rows)} controls from {gf[0]}"
        )
        return JSONResponse({"count": len(rows)}, status_code=201)
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# CONTROLS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/controls")
@require_capability("module.grid.access")
async def api_controls_list(request: Request):
    import json as _json
    audit_id = request.query_params.get("audit_id")
    status = request.query_params.get("status")
    risk = request.query_params.get("risk_level")
    controls = ds.list_controls(
        audit_id=int(audit_id) if audit_id else None,
        status=status,
        risk_level=risk,
    )

    # When no audit-specific controls exist (no audits created yet),
    # show framework controls from the unified table so the page isn't empty
    if not controls and not audit_id:
        db = get_db()
        try:
            rows = db.execute(
                "SELECT c.id, c.ref AS control_id, c.name, c.description, "
                "c.status, c.priority AS risk_level, c.category, "
                "f.name AS framework_name, '' AS assignee_name "
                "FROM controls c "
                "JOIN frameworks f ON c.framework_id = f.id "
                "WHERE f.is_active = 1 AND f.relevant_modules LIKE '%grid%' "
                "ORDER BY f.name, c.ref"
            ).fetchall()
            controls = [dict(r) for r in rows]
        finally:
            db.close()

    # IMS enrichment: for controls belonging to an IMS audit, add ims_status badge
    if audit_id and controls:
        db = get_db()
        try:
            audit = db.execute(
                "SELECT is_integrated, framework_ids FROM grid_audits WHERE id=%s",
                (int(audit_id),)
            ).fetchone()
            if audit and audit["is_integrated"]:
                try:
                    fw_ids = _json.loads(audit["framework_ids"] or "[]")
                except Exception:
                    fw_ids = []
                if len(fw_ids) >= 2:
                    from core.auto_mapper import get_ims_status_bulk
                    # Build ctrl dicts using their grid_controls.framework_id
                    # (we need the unified framework_id from controls table via grid_controls.control_id)
                    ctrl_info = []
                    for c in controls:
                        # Look up the unified controls row for this grid control
                        unified = db.execute(
                            "SELECT c2.id AS uid, c2.framework_id "
                            "FROM controls c2 JOIN grid_controls gc ON gc.control_id=c2.ref "
                            "WHERE gc.id=%s LIMIT 1",
                            (c["id"],)
                        ).fetchone()
                        ctrl_info.append({
                            "id": c["id"],
                            "framework_id": unified["framework_id"] if unified else 0,
                        })
                    # Use grid_control_mappings (ims_equivalent) for status
                    for c in controls:
                        mapped_count = db.execute("""
                            SELECT COUNT(DISTINCT
                                CASE WHEN gcm.source_control_id=%s THEN
                                    (SELECT gc2.framework_id FROM grid_controls gc2 WHERE gc2.id=gcm.target_control_id)
                                ELSE
                                    (SELECT gc2.framework_id FROM grid_controls gc2 WHERE gc2.id=gcm.source_control_id)
                                END)
                            FROM grid_control_mappings gcm
                            WHERE (gcm.source_control_id=%s OR gcm.target_control_id=%s)
                              AND gcm.mapping_type='ims_equivalent'
                        """, (c["id"], c["id"], c["id"])).fetchone()[0] or 0

                        total_other = len(fw_ids) - 1
                        if mapped_count >= total_other:
                            c["ims_status"] = "integrated"
                        elif mapped_count > 0:
                            c["ims_status"] = "partial"
                        else:
                            c["ims_status"] = "unique"
        finally:
            db.close()

    return JSONResponse(controls)


@router.get("/api/controls/{cid}")
@require_capability("module.grid.access")
async def api_controls_detail(request: Request, cid: int):
    ctrl = ds.get_control(cid)
    if not ctrl:
        raise HTTPException(404, "Control not found")
    return JSONResponse(ctrl)


@router.post("/api/controls")
@require_capability("grid.control.assign")
async def api_controls_create(request: Request):
    body = await _json_body(request)
    cid = ds.create_control(body)
    ds.log_activity(_uid(request), "create_control", "grid_controls", cid)
    return JSONResponse({"id": cid}, status_code=201)


@router.post("/api/controls/bulk")
@require_capability("grid.control.assign")
async def api_controls_bulk_create(request: Request):
    body = await _json_body(request)
    audit_id = body.get("audit_id")
    framework_id = body.get("framework_id")
    controls = body.get("controls", [])
    if not audit_id or not controls:
        raise HTTPException(400, "audit_id and controls required")
    ids = ds.create_controls_bulk(audit_id, framework_id, controls)
    ds.log_activity(_uid(request), "bulk_create_controls", "grid_controls", audit_id,
                    f"{len(ids)} controls")
    return JSONResponse({"ids": ids, "count": len(ids)}, status_code=201)


@router.put("/api/controls/{cid}")
@require_capability("grid.control.update_own")
async def api_controls_update(request: Request, cid: int):
    body = await _json_body(request)
    _check_locked(ds.update_control, cid, body)
    ds.log_activity(_uid(request), "update_control", "grid_controls", cid)
    return JSONResponse({"ok": True})


@router.delete("/api/controls/{cid}")
@require_capability("grid.audit.delete")
async def api_controls_delete(request: Request, cid: int):
    ds.delete_control(cid)
    ds.log_activity(_uid(request), "delete_control", "grid_controls", cid)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# EVIDENCE
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/evidence/{control_id}")
@require_capability("module.grid.access")
async def api_evidence_list(request: Request, control_id: int):
    return JSONResponse(ds.get_evidence(control_id))


@router.post("/api/evidence/{control_id}/upload")
@require_capability("grid.evidence.upload")
async def api_evidence_upload(request: Request, control_id: int,
                              file: UploadFile = File(...),
                              evidence_item_id: int = Form(None),
                              notes: str = Form(None)):
    # Validate size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)")

    # Save file
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name
    file_path.write_bytes(content)

    efid = ds.create_evidence_file({
        "control_id": control_id,
        "evidence_item_id": evidence_item_id,
        "filename": safe_name,
        "original_name": file.filename,
        "file_path": str(file_path),
        "file_size": len(content),
        "mime_type": file.content_type or "",
        "uploaded_by": _uid(request),
        "notes": notes,
    })
    ds.log_activity(_uid(request), "upload_evidence", "grid_evidence_files", efid, file.filename)
    return JSONResponse({"id": efid, "filename": safe_name}, status_code=201)


@router.get("/api/evidence/file/{eid}")
@require_capability("module.grid.access")
async def api_evidence_file_detail(request: Request, eid: int):
    ef = ds.get_evidence_file(eid)
    if not ef:
        raise HTTPException(404, "Evidence file not found")
    return JSONResponse(ef)


@router.put("/api/evidence/file/{eid}/approve")
@require_capability("grid.evidence.approve")
async def api_evidence_approve(request: Request, eid: int):
    body = await _json_body(request)
    status = body.get("status", "approved")
    ds.approve_evidence(eid, status, _uid(request))
    ds.log_activity(_uid(request), "approve_evidence", "grid_evidence_files", eid, status)
    return JSONResponse({"ok": True})


@router.get("/api/evidence/file/{eid}/versions")
@require_capability("module.grid.access")
async def api_evidence_versions(request: Request, eid: int):
    """Return version history for an evidence file."""
    return JSONResponse(ds.get_evidence_versions(eid))


@router.post("/api/evidence/{control_id}/replace/{eid}")
@require_capability("grid.evidence.upload")
async def api_evidence_replace(request: Request, control_id: int, eid: int,
                                file: UploadFile = File(...),
                                notes: str = Form(None),
                                expires_at: str = Form(None)):
    """Upload a new version of an existing evidence file."""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name
    file_path.write_bytes(content)

    fid = ds.create_evidence_file({
        "replace_id": eid,
        "control_id": control_id,
        "filename": safe_name,
        "original_name": file.filename,
        "file_path": str(file_path),
        "file_size": len(content),
        "mime_type": file.content_type or "",
        "uploaded_by": _uid(request),
        "notes": notes,
        "expires_at": expires_at,
    })
    ds.log_activity(_uid(request), "replace_evidence", "grid_evidence_files", fid,
                    f"v{ds.get_evidence_file(fid).get('version', '?')} — {file.filename}")
    return JSONResponse({"id": fid, "filename": safe_name}, status_code=201)


@router.delete("/api/evidence/file/{eid}")
@require_capability("grid.evidence.delete")
async def api_evidence_delete(request: Request, eid: int):
    # Remove physical file
    ef = ds.get_evidence_file(eid)
    if ef and ef.get("file_path"):
        p = Path(ef["file_path"])
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass  # file already gone or permission issue
    ds.delete_evidence_file(eid)
    ds.log_activity(_uid(request), "delete_evidence", "grid_evidence_files", eid)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# EVIDENCE DOWNLOAD
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/evidence/file/{eid}/download")
@require_capability("module.grid.access")
async def api_evidence_download(request: Request, eid: int):
    """Download a single evidence file."""
    ef = ds.get_evidence_file(eid)
    if not ef:
        raise HTTPException(404, "Evidence file not found")
    fp = Path(ef["file_path"])
    if not fp.exists():
        raise HTTPException(404, "Physical file missing")
    # Sanitise original name for Content-Disposition
    safe_orig = (ef.get("original_name") or ef.get("filename") or "file").replace('"', "'")
    return FileResponse(
        path=str(fp),
        filename=safe_orig,
        media_type=ef.get("mime_type") or "application/octet-stream",
    )


@router.get("/api/evidence/{control_id}/download-all")
@require_capability("module.grid.access")
async def api_evidence_download_all(request: Request, control_id: int):
    """Download all evidence files for a control as a ZIP archive."""
    ev = ds.get_evidence(control_id)
    files = ev.get("files", []) if ev else []
    if not files:
        raise HTTPException(404, "No evidence files for this control")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen_names: dict[str, int] = {}
        for f in files:
            fp = Path(f["file_path"])
            if not fp.exists():
                continue
            orig = f.get("original_name") or f.get("filename") or "file"
            # De-duplicate names inside the ZIP
            if orig in seen_names:
                seen_names[orig] += 1
                base, ext = os.path.splitext(orig)
                orig = f"{base}_{seen_names[orig]}{ext}"
            else:
                seen_names[orig] = 0
            zf.write(fp, orig)
    buf.seek(0)

    ctrl = ds.get_control(control_id)
    ctrl_label = (ctrl.get("control_id") or ctrl.get("name") or str(control_id)) if ctrl else str(control_id)
    zip_name = f"evidence_{ctrl_label}.zip".replace(" ", "_")

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


# ═════════════════════════════════════════════════════════════════════════════
# BULK EVIDENCE OPERATIONS
# ═════════════════════════════════════════════════════════════════════════════

@router.put("/api/evidence/bulk-approve")
@require_capability("grid.evidence.approve")
async def api_evidence_bulk_approve(request: Request):
    """Approve or reject multiple evidence files at once."""
    body = await _json_body(request)
    eids = body.get("ids", [])
    status = body.get("status", "Approved")
    if not eids or not isinstance(eids, list):
        raise HTTPException(400, "ids (list of evidence file IDs) required")
    if status not in ("Approved", "Rejected"):
        raise HTTPException(400, "status must be Approved or Rejected")
    count = ds.bulk_approve_evidence(eids, status, _uid(request))
    ds.log_activity(_uid(request), "bulk_approve_evidence", "grid_evidence_files", 0,
                    f"{count} files → {status}")
    return JSONResponse({"ok": True, "count": count})


@router.get("/api/evidence-all")
@require_capability("module.grid.access")
async def api_evidence_all(request: Request):
    """List all evidence files across audits with optional filters."""
    audit_id = request.query_params.get("audit_id")
    status = request.query_params.get("status")
    mime_type = request.query_params.get("mime_type")
    return JSONResponse(ds.get_all_evidence(
        audit_id=int(audit_id) if audit_id else None,
        status=status or None,
        mime_type=mime_type or None,
    ))


@router.get("/api/evidence-completeness/{audit_id}")
@require_capability("module.grid.access")
async def api_evidence_completeness(request: Request, audit_id: int):
    """Return evidence completeness stats for an audit."""
    return JSONResponse(ds.get_evidence_completeness(audit_id))


@router.get("/api/evidence/audit/{audit_id}/download-all")
@require_capability("module.grid.access")
async def api_evidence_audit_download_all(request: Request, audit_id: int):
    """Download all evidence files for an entire audit as a ZIP."""
    audit = ds.get_audit(audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found")

    all_files = ds.get_all_evidence(audit_id=audit_id)
    if not all_files:
        raise HTTPException(404, "No evidence files for this audit")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seen_names: dict[str, int] = {}
        for f in all_files:
            fp = Path(f.get("file_path", ""))
            if not fp.exists():
                continue
            # Organise into folders by control ref
            ctrl_ref = f.get("ctrl_ref") or f.get("control_name") or "unknown"
            orig = f.get("original_name") or f.get("filename") or "file"
            arc_name = f"{ctrl_ref}/{orig}"
            if arc_name in seen_names:
                seen_names[arc_name] += 1
                base, ext = os.path.splitext(arc_name)
                arc_name = f"{base}_{seen_names[arc_name]}{ext}"
            else:
                seen_names[arc_name] = 0
            zf.write(fp, arc_name)
    buf.seek(0)

    audit_name = (audit.get("name") or f"audit_{audit_id}").replace(" ", "_")
    zip_name = f"evidence_{audit_name}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


# ═════════════════════════════════════════════════════════════════════════════
# EVIDENCE CHECKLIST ITEMS CRUD
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/evidence-items/{control_id}")
@require_capability("module.grid.access")
async def api_evidence_items_list(request: Request, control_id: int):
    """List evidence checklist items for a control, including approved-file counts."""
    return JSONResponse(ds.get_evidence_items(control_id))


@router.post("/api/evidence-items/{control_id}")
@require_capability("grid.evidence.upload")
async def api_evidence_items_create(request: Request, control_id: int):
    body = await _json_body(request)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Item name is required")
    desc = (body.get("description") or "").strip()
    required = body.get("required", 1)
    iid = ds.create_evidence_item(control_id, name, desc, required)
    return JSONResponse({"id": iid}, status_code=201)


@router.delete("/api/evidence-items/{item_id}")
@require_capability("grid.evidence.upload")
async def api_evidence_items_delete(request: Request, item_id: int):
    ds.delete_evidence_item(item_id)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# COMMENTS
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/api/controls/{cid}/comments")
@require_capability("grid.control.update_own")
async def api_comments_add(request: Request, cid: int):
    body = await _json_body(request)
    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(400, "Comment content required")
    cmid = ds.add_comment(cid, _uid(request), content)
    return JSONResponse({"id": cmid}, status_code=201)


# ═════════════════════════════════════════════════════════════════════════════
# USERS (for assignee dropdown)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/users")
@require_capability("module.grid.access")
async def api_users_list(request: Request):
    user = request.state.user
    org_id = user.get("org_id")
    db = get_db()
    try:
        if org_id:
            rows = db.execute(
                "SELECT id, username, full_name, email FROM users "
                "WHERE is_active=1 AND org_id=%s ORDER BY full_name", (org_id,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, username, full_name, email FROM users "
                "WHERE is_active=1 ORDER BY full_name"
            ).fetchall()
        return JSONResponse([dict(r) for r in rows])
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# REMINDERS
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/api/reminders")
@require_capability("grid.reminder.manage")
async def api_reminders_create(request: Request):
    body = await _json_body(request)
    body["user_id"] = _uid(request)
    rid = ds.create_reminder(body)
    return JSONResponse({"id": rid}, status_code=201)


@router.get("/api/reminders/{audit_id}/pending")
@require_capability("grid.reminder.manage")
async def api_reminders_pending(request: Request, audit_id: int):
    return JSONResponse(ds.get_pending_reminders(audit_id))


# ═════════════════════════════════════════════════════════════════════════════
# NON-CONFORMANCES
# ═════════════════════════════════════════════════════════════════════════════

def _send_nc_assignment_email(ncid: int, assigner_id: int | None = None) -> None:
    """Fire-and-forget email to the assignee of an NC."""
    try:
        nc = ds.get_nc(ncid)
        if not nc or not nc.get("assigned_to"):
            return
        db = get_db()
        try:
            user = db.execute(
                "SELECT full_name, email FROM users WHERE id=%s",
                (nc["assigned_to"],)
            ).fetchone()
            assigner = db.execute(
                "SELECT full_name FROM users WHERE id=%s",
                (assigner_id,)
            ).fetchone() if assigner_id else None
        finally:
            db.close()
        if not user or not user["email"]:
            return
        send_email(
            to=user["email"],
            subject=f"[G.R.I.D AI] NC Assigned: {nc.get('title', '')}",
            body_html=nc_alert_html(
                owner_name=user["full_name"] or "",
                nc_title=nc.get("title", ""),
                severity=nc.get("severity", ""),
                due_date=nc.get("due_date") or nc.get("response_deadline") or "",
                raised_by=(assigner["full_name"] if assigner else "") or "",
                audit_name=nc.get("audit_name", ""),
            ),
        )
    except Exception:
        pass  # Email is best-effort; never block the API response


@router.get("/api/ncs")
@require_capability("grid.nc.manage")
async def api_ncs_list(request: Request):
    audit_id = request.query_params.get("audit_id")
    status = request.query_params.get("status")
    cap_status = request.query_params.get("cap_status")
    return JSONResponse(ds.list_ncs(
        audit_id=int(audit_id) if audit_id else None,
        status=status,
        cap_status=cap_status,
    ))


@router.get("/api/ncs/{ncid}")
@require_capability("grid.nc.manage")
async def api_ncs_detail(request: Request, ncid: int):
    nc = ds.get_nc(ncid)
    if not nc:
        raise HTTPException(404, "Non-conformance not found")
    return JSONResponse(nc)


@router.post("/api/ncs")
@require_capability("grid.nc.manage")
async def api_ncs_create(request: Request):
    body = await _json_body(request)
    ncid = _check_locked(ds.create_nc, body)
    ds.log_activity(_uid(request), "create_nc", "grid_non_conformances", ncid)

    # Emit NC raised event
    nc_severity = body.get("severity", "minor")
    emit(
        GRID_NC_RAISED,
        source_module="grid",
        entity_type="non_conformance",
        entity_id=ncid,
        payload={
            "title": body.get("title", ""),
            "severity": nc_severity,
            "audit_id": body.get("audit_id"),
            "control_id": body.get("control_id"),
            "description": body.get("description", ""),
        },
        user_id=_uid(request),
    )
    # GAP-5: Major/critical NCs also fire GRID_FINDING_CREATED so that
    # finding_triggers_sentinel_check and finding_elevates_to_erm handlers run.
    if nc_severity in ("major", "critical"):
        emit(
            GRID_FINDING_CREATED,
            source_module="grid",
            entity_type="non_conformance",
            entity_id=ncid,
            payload={
                "title": body.get("title", ""),
                "severity": nc_severity,
                "audit_id": body.get("audit_id"),
                "description": body.get("description", ""),
                "finding_type": "non_conformance",
            },
            user_id=_uid(request),
        )
    return JSONResponse({"id": ncid}, status_code=201)


@router.put("/api/ncs/{ncid}")
@require_capability("grid.nc.manage")
async def api_ncs_update(request: Request, ncid: int):
    body = await _json_body(request)
    # Check if assignment is changing — fetch old NC first
    new_assignee = body.get("assigned_to")
    old_nc = ds.get_nc(ncid) if new_assignee is not None else None
    _check_locked(ds.update_nc, ncid, body)
    ds.log_activity(_uid(request), "update_nc", "grid_non_conformances", ncid)
    # Send assignment email if assigned_to changed to a new user
    if (new_assignee is not None and old_nc
            and new_assignee != old_nc.get("assigned_to") and new_assignee):
        _send_nc_assignment_email(ncid, _uid(request))
    return JSONResponse({"ok": True})


@router.delete("/api/ncs/{ncid}")
@require_capability("grid.nc.manage")
async def api_ncs_delete(request: Request, ncid: int):
    ds.delete_nc(ncid)
    ds.log_activity(_uid(request), "delete_nc", "grid_non_conformances", ncid)
    return JSONResponse({"ok": True})


@router.put("/api/ncs/{ncid}/advance")
@require_capability("grid.nc.manage")
async def api_ncs_advance(request: Request, ncid: int):
    """Advance NC to next CAP lifecycle step."""
    new_status = ds.advance_cap_status(ncid, _uid(request))
    if new_status is None:
        raise HTTPException(404, "Non-conformance not found")
    ds.log_activity(_uid(request), "advance_cap", "grid_non_conformances", ncid, new_status)
    return JSONResponse({"ok": True, "cap_status": new_status})


@router.put("/api/ncs/{ncid}/revert")
@require_capability("grid.nc.manage")
async def api_ncs_revert(request: Request, ncid: int):
    """Revert NC to previous CAP lifecycle step."""
    new_status = ds.revert_cap_status(ncid)
    if new_status is None:
        raise HTTPException(404, "Non-conformance not found")
    ds.log_activity(_uid(request), "revert_cap", "grid_non_conformances", ncid, new_status)
    return JSONResponse({"ok": True, "cap_status": new_status})


@router.put("/api/ncs/{ncid}/mgmt-response")
@require_capability("grid.nc.manage")
async def api_ncs_mgmt_response(request: Request, ncid: int):
    """Manager approves or rejects a CAP with optional response text and deadline."""
    body = await _json_body(request)
    status = body.get("status")
    if status not in ("Approved", "Rejected"):
        raise HTTPException(400, "status must be 'Approved' or 'Rejected'")
    response_text = body.get("response") or None
    response_deadline = body.get("response_deadline") or None
    new_cap = ds.submit_mgmt_response(
        ncid, _uid(request), status,
        response_text=response_text,
        response_deadline=response_deadline,
    )
    if new_cap is None:
        raise HTTPException(404, "Non-conformance not found")
    action = "approve_cap" if status == "Approved" else "reject_cap"
    ds.log_activity(_uid(request), action, "grid_non_conformances", ncid, new_cap)
    return JSONResponse({"ok": True, "cap_status": new_cap, "mgmt_status": status})


# ── NC-Evidence Links ──────────────────────────────────────────────────────

@router.get("/api/ncs/{ncid}/evidence")
@require_capability("grid.nc.manage")
async def api_nc_evidence_list(request: Request, ncid: int):
    """List all evidence files linked to a non-conformance."""
    return JSONResponse(ds.list_nc_evidence(ncid))


@router.get("/api/ncs/{ncid}/evidence/available")
@require_capability("grid.nc.manage")
async def api_nc_evidence_available(request: Request, ncid: int):
    """List evidence files from the same audit that are not yet linked."""
    return JSONResponse(ds.get_available_evidence_for_nc(ncid))


@router.post("/api/ncs/{ncid}/evidence")
@require_capability("grid.nc.manage")
async def api_nc_evidence_link(request: Request, ncid: int):
    """Link an evidence file to an NC."""
    body = await _json_body(request)
    eid = body.get("evidence_file_id")
    if not eid:
        raise HTTPException(400, "evidence_file_id required")
    link_id = ds.link_evidence_to_nc(
        ncid, int(eid),
        linked_by=_uid(request),
        notes=body.get("notes"),
    )
    if link_id is None:
        raise HTTPException(409, "Evidence already linked to this NC")
    ds.log_activity(_uid(request), "link_nc_evidence", "grid_nc_evidence", link_id)
    return JSONResponse({"ok": True, "link_id": link_id})


@router.delete("/api/ncs/{ncid}/evidence/{link_id}")
@require_capability("grid.nc.manage")
async def api_nc_evidence_unlink(request: Request, ncid: int, link_id: int):
    """Remove an NC-evidence link."""
    ds.unlink_evidence_from_nc(link_id)
    ds.log_activity(_uid(request), "unlink_nc_evidence", "grid_nc_evidence", link_id)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# VENDORS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/vendors")
@require_capability("grid.vendor.manage")
async def api_vendors_list(request: Request):
    status = request.query_params.get("status")
    risk = request.query_params.get("risk_level")
    return JSONResponse(ds.list_vendors(status=status, risk_level=risk))


@router.get("/api/vendors/{vid}")
@require_capability("grid.vendor.manage")
async def api_vendors_detail(request: Request, vid: int):
    v = ds.get_vendor(vid)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return JSONResponse(v)


@router.post("/api/vendors")
@require_capability("grid.vendor.manage")
async def api_vendors_create(request: Request):
    body = await _json_body(request)
    vid = ds.create_vendor(body)
    ds.log_activity(_uid(request), "create_vendor", "grid_vendors", vid)
    vendor = ds.get_vendor(vid)
    emit("vendor.created", source_module="grid", entity_type="vendor", entity_id=vid,
         payload={"name": (vendor or {}).get("name", ""), "canonical_id": (vendor or {}).get("canonical_id"),
                  "source_module": "grid"},
         user_id=_uid(request))
    return JSONResponse({"id": vid}, status_code=201)


@router.put("/api/vendors/{vid}")
@require_capability("grid.vendor.manage")
async def api_vendors_update(request: Request, vid: int):
    body = await _json_body(request)
    ds.update_vendor(vid, body)
    ds.log_activity(_uid(request), "update_vendor", "grid_vendors", vid)
    return JSONResponse({"ok": True})


@router.delete("/api/vendors/{vid}")
@require_capability("grid.vendor.manage")
async def api_vendors_delete(request: Request, vid: int):
    ds.delete_vendor(vid)
    ds.log_activity(_uid(request), "delete_vendor", "grid_vendors", vid)
    return JSONResponse({"ok": True})


@router.get("/api/vendors/{vid}/cross-module")
@require_capability("grid.vendor.manage")
async def api_vendor_cross_module(request: Request, vid: int):
    v = ds.get_vendor(vid)
    if not v or not v.get("canonical_id"):
        return JSONResponse({"modules": {}, "flags": [], "canonical_id": None})
    from core.vendor_link import get_cross_module_profile
    db = get_db()
    try:
        return JSONResponse(get_cross_module_profile(db, v["canonical_id"]))
    finally:
        db.close()


@router.post("/api/vendors/{vid}/assessments")
@require_capability("grid.vendor.manage")
async def api_vendor_assessments_create(request: Request, vid: int):
    body = await _json_body(request)
    body["assessed_by"] = _uid(request)
    vasid = ds.create_vendor_assessment(vid, body)
    ds.log_activity(_uid(request), "create_assessment", "grid_vendor_assessments", vasid)
    return JSONResponse({"id": vasid}, status_code=201)


# ═════════════════════════════════════════════════════════════════════════════
# APPROVALS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/approvals/{evidence_id}")
@require_capability("module.grid.access")
async def api_approvals_list(request: Request, evidence_id: int):
    return JSONResponse(ds.get_approvals(evidence_id))


@router.post("/api/approvals/{evidence_id}")
@require_capability("grid.evidence.approve")
async def api_approvals_request(request: Request, evidence_id: int):
    body = await _json_body(request)
    approver_id = body.get("approver_id", _uid(request))
    apid = ds.request_approval(evidence_id, approver_id)
    return JSONResponse({"id": apid}, status_code=201)


@router.put("/api/approvals/{approval_id}/decide")
@require_capability("grid.evidence.approve")
async def api_approvals_decide(request: Request, approval_id: int):
    body = await _json_body(request)
    status = body.get("status", "approved")
    comments = body.get("comments")
    ds.decide_approval(approval_id, status, comments)
    ds.log_activity(_uid(request), "decide_approval", "grid_approvals", approval_id, status)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# CROSS-MAPPINGS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/mappings/{audit_id}")
@require_capability("grid.cross_mapping.manage")
async def api_mappings_list(request: Request, audit_id: int):
    return JSONResponse(ds.list_mappings(audit_id))


@router.post("/api/mappings")
@require_capability("grid.cross_mapping.manage")
async def api_mappings_create(request: Request):
    body = await _json_body(request)
    mid = ds.create_mapping(
        body["source_control_id"], body["target_control_id"],
        body.get("mapping_type", "equivalent"), body.get("confidence"),
    )
    return JSONResponse({"id": mid}, status_code=201)


@router.post("/api/mappings/bulk")
@require_capability("grid.cross_mapping.manage")
async def api_mappings_bulk(request: Request):
    body = await _json_body(request)
    mappings = body.get("mappings", [])
    ds.save_mappings_bulk(mappings)
    ds.log_activity(_uid(request), "bulk_save_mappings", "grid_control_mappings", 0,
                    f"{len(mappings)} mappings")
    return JSONResponse({"ok": True, "count": len(mappings)})


@router.delete("/api/mappings/{mid}")
@require_capability("grid.cross_mapping.manage")
async def api_mappings_delete(request: Request, mid: int):
    ds.delete_mapping(mid)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# SHARE LINKS
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/api/share-links")
@require_capability("grid.share.manage")
async def api_share_create(request: Request):
    body = await _json_body(request)
    result = ds.create_share_link(
        body["audit_id"], _uid(request),
        body.get("auditor_email"), body.get("expires_days", 30),
    )
    ds.log_activity(_uid(request), "create_share_link", "grid_share_links", result["id"])

    # ── Send email notification if auditor_email provided ───────────────
    auditor_email = (body.get("auditor_email") or "").strip()
    if auditor_email:
        from modules.grid.email_service import send_email, audit_share_html

        audit = ds.get_audit(body["audit_id"])
        audit_name = audit.get("name", "Audit") if audit else "Audit"

        # Build the share URL from request origin
        origin = str(request.base_url).rstrip("/")
        share_url = f"{origin}/grid/api/share-links/validate/{result['token']}"

        creator = request.state.user.get("full_name") or request.state.user.get("username", "")

        send_email(
            to=auditor_email,
            subject=f"[G.R.I.D AI] Audit access: {audit_name}",
            body_html=audit_share_html(
                auditor_name=body.get("auditor_name", ""),
                audit_name=audit_name,
                share_url=share_url,
                expires_at=result.get("expires_at", ""),
                created_by=creator,
            ),
        )

    return JSONResponse(result, status_code=201)


@router.get("/api/share-links/{audit_id}")
@require_capability("grid.share.manage")
async def api_share_list(request: Request, audit_id: int):
    return JSONResponse(ds.list_share_links(audit_id))


@router.get("/api/share-links/validate/{token}")
@require_capability("module.grid.access")
async def api_share_validate(request: Request, token: str):
    link = ds.validate_share_link(token)
    if not link:
        raise HTTPException(404, "Invalid or expired share link")
    return JSONResponse(link)


@router.put("/api/share-links/{sid}/revoke")
@require_capability("grid.share.manage")
async def api_share_revoke(request: Request, sid: int):
    ds.revoke_share_link(sid)
    ds.log_activity(_uid(request), "revoke_share_link", "grid_share_links", sid)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# TIMELINE
# ═════════════════════════════════════════════════════════════════════════════

@router.put("/api/timeline/{tid}")
@require_capability("grid.audit.edit")
async def api_timeline_update(request: Request, tid: int):
    body = await _json_body(request)
    ds.update_timeline(tid, body)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# COMPLIANCE SCORES
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/api/scores/{audit_id}")
@require_capability("grid.audit.edit")
async def api_scores_record(request: Request, audit_id: int):
    body = await _json_body(request)
    sid = ds.record_score(audit_id, body.get("score", 0), body.get("details"))
    return JSONResponse({"id": sid}, status_code=201)


@router.get("/api/scores/{audit_id}")
@require_capability("module.grid.access")
async def api_scores_list(request: Request, audit_id: int):
    limit = int(request.query_params.get("limit", "60"))
    return JSONResponse(ds.list_scores(audit_id, limit))


# ═════════════════════════════════════════════════════════════════════════════
# ACTIVITY LOG
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/activity")
@require_capability("module.grid.access")
async def api_activity_list(request: Request):
    limit = int(request.query_params.get("limit", "50"))
    return JSONResponse(ds.list_activity(limit))


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS (all audits)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/dashboard")
@require_capability("module.grid.access")
async def api_dashboard(request: Request):
    """Summary stats across all audits for the dashboard view."""
    audits = ds.list_audits()
    total_audits = len(audits)
    total_controls = sum(a.get("total_controls", 0) for a in audits)
    complete_controls = sum(a.get("complete_controls", 0) for a in audits)
    return JSONResponse({
        "totalAudits": total_audits,
        "totalControls": total_controls,
        "completeControls": complete_controls,
        "completionPct": round(complete_controls / total_controls * 100) if total_controls else 0,
        "audits": audits,
    })


# ═════════════════════════════════════════════════════════════════════════════
# AI ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/api/ai/parse-checklist")
@require_capability("grid.ai.parse_checklist")
async def api_ai_parse_checklist(request: Request,
                                  file: UploadFile = File(...),
                                  framework_name: str = Form("ISO 27001"),
                                  skip_ai: str = Form("false")):
    """Upload a checklist file (Excel/CSV) and extract controls with AI risk scoring."""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)")

    ext = Path(file.filename or "").suffix.lower() if file.filename else ""
    do_skip = skip_ai.lower() == "true"

    try:
        controls = ai.parse_checklist_file(content, framework_name, do_skip, ext)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    if not controls:
        raise HTTPException(400, "No controls found in this file.")

    return JSONResponse({
        "success": True,
        "controls": controls,
        "count": len(controls),
        "ai_scored": not do_skip,
        "message": (
            f"Extracted {len(controls)} controls (no AI scoring)"
            if do_skip
            else f"Extracted and AI-scored {len(controls)} controls"
        ),
    }, status_code=201)


@router.get("/api/ai/gap-analysis/{audit_id}")
@require_capability("grid.ai.gap_analysis")
async def api_ai_gap_analysis(request: Request, audit_id: int):
    """Run AI gap analysis for an audit."""
    audit = ds.get_audit(audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found")

    controls = audit.get("controls", [])
    framework = audit.get("framework_name", "Unknown")

    try:
        analysis = ai.generate_gap_analysis(controls, framework)
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    return JSONResponse({"success": True, "analysis": analysis})


@router.post("/api/ai/suggest-control")
@require_capability("grid.ai.gap_analysis")
async def api_ai_suggest_control(request: Request):
    """Get AI-suggested details for a control."""
    body = await _json_body(request)
    name = body.get("name", "")
    framework = body.get("framework", "")
    if not name or not framework:
        raise HTTPException(400, "name and framework required")

    try:
        suggestion = ai.suggest_control_details(
            body.get("control_id", ""), name, framework
        )
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    return JSONResponse({"success": True, "suggestion": suggestion})


@router.post("/api/ai/generate-report/{audit_id}")
@require_capability("grid.ai.report")
async def api_ai_generate_report(request: Request, audit_id: int):
    """Generate AI narrative for an audit report."""
    audit = ds.get_audit(audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found")

    controls = audit.get("controls", [])
    total = len(controls)
    complete = sum(1 for c in controls if c.get("status") == "Complete")
    overdue = sum(
        1 for c in controls
        if c.get("status") != "Complete" and c.get("due_date", "") and c["due_date"] < date.today().isoformat()
    )
    pending = total - complete - overdue
    critical_gaps = [
        c["name"] for c in controls
        if c.get("risk_level") == "Critical" and c.get("status") != "Complete"
    ][:5]

    try:
        narrative = ai.generate_report_narrative({
            "auditName": audit.get("name"),
            "framework": audit.get("framework_name"),
            "completionPct": round(complete / total * 100) if total else 0,
            "totalControls": total,
            "complete": complete,
            "pending": pending,
            "overdue": overdue,
            "auditDate": audit.get("audit_date"),
            "criticalGaps": critical_gaps,
        })
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    return JSONResponse({"success": True, "narrative": narrative})


@router.post("/api/ai/chat")
@require_capability("grid.ai.gap_analysis")
async def api_ai_chat(request: Request):
    """Compliance assistant chat."""
    body = await _json_body(request)
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(400, "message required")

    context = {}
    audit_id = body.get("audit_id")
    if audit_id:
        audit = ds.get_audit(int(audit_id))
        if audit:
            controls = audit.get("controls", [])
            complete = sum(1 for c in controls if c.get("status") == "Complete")
            context = {
                "framework": audit.get("framework_name"),
                "total": len(controls),
                "complete": complete,
                "pct": round(complete / len(controls) * 100) if controls else 0,
            }

    try:
        answer = ai.ask_compliance_ai(message, context)
    except RuntimeError as e:
        raise HTTPException(502, str(e))

    return JSONResponse({"success": True, "answer": answer})


# ═════════════════════════════════════════════════════════════════════════════
# REMOTE AUDIT SESSIONS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/remote-sessions")
@require_capability("grid.audits.manage")
async def api_remote_sessions_list(request: Request):
    """List remote audit sessions, optionally filtered by audit_id."""
    from database import get_db
    db = get_db()
    try:
        audit_id = request.query_params.get("audit_id")
        if audit_id:
            rows = db.execute(
                "SELECT rs.*, u.full_name as auditor_name FROM grid_remote_sessions rs "
                "LEFT JOIN users u ON rs.auditor_id = u.id "
                "WHERE rs.audit_id = %s ORDER BY rs.scheduled_start DESC", (int(audit_id),)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT rs.*, u.full_name as auditor_name FROM grid_remote_sessions rs "
                "LEFT JOIN users u ON rs.auditor_id = u.id "
                "ORDER BY rs.scheduled_start DESC"
            ).fetchall()
    finally:
        db.close()
    return JSONResponse([dict(r) for r in rows])


@router.post("/api/remote-sessions", status_code=201)
@require_capability("grid.audits.manage")
async def api_remote_session_create(request: Request):
    """Create a new remote audit session."""
    data = await _json_body(request)
    from database import get_db
    db = get_db()
    try:
        sid = insert_returning_id(
            db,
            "INSERT INTO grid_remote_sessions "
            "(audit_id, title, description, session_type, scheduled_start, scheduled_end, "
            "meeting_link, auditor_id, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                data.get("audit_id"),
                data.get("title", "Remote Audit Session"),
                data.get("description", ""),
                data.get("session_type", "video"),
                data.get("scheduled_start"),
                data.get("scheduled_end"),
                data.get("meeting_link", ""),
                data.get("auditor_id"),
                _uid(request),
            )
        )
        db.commit()
        # Add participants if provided
        participants = data.get("participants", [])
        for p in participants:
            db.execute(
                "INSERT INTO grid_remote_participants (session_id, user_id, external_name, external_email, role) "
                "VALUES (%s,%s,%s,%s,%s)",
                (sid, p.get("user_id"), p.get("name", ""), p.get("email", ""), p.get("role", "auditee"))
            )
        db.commit()
        ds.log_activity(_uid(request), "create_remote_session", "grid_remote_sessions", sid)
    finally:
        db.close()
    return JSONResponse({"id": sid}, status_code=201)


@router.get("/api/remote-sessions/{sid}")
@require_capability("grid.audits.manage")
async def api_remote_session_get(request: Request, sid: int):
    """Get a remote session with participants and findings."""
    from database import get_db
    db = get_db()
    try:
        session = db.execute(
            "SELECT rs.*, u.full_name as auditor_name FROM grid_remote_sessions rs "
            "LEFT JOIN users u ON rs.auditor_id = u.id WHERE rs.id = %s", (sid,)
        ).fetchone()
        if not session:
            raise HTTPException(404, "Session not found")
        result = dict(session)
        result["participants"] = [dict(r) for r in db.execute(
            "SELECT rp.*, u.full_name FROM grid_remote_participants rp "
            "LEFT JOIN users u ON rp.user_id = u.id WHERE rp.session_id = %s", (sid,)
        ).fetchall()]
        result["findings"] = [dict(r) for r in db.execute(
            "SELECT rf.*, u.full_name as raised_by_name FROM grid_remote_findings rf "
            "LEFT JOIN users u ON rf.raised_by = u.id WHERE rf.session_id = %s ORDER BY rf.created_at", (sid,)
        ).fetchall()]
        result["notes"] = [dict(r) for r in db.execute(
            "SELECT rn.*, u.full_name FROM grid_remote_notes rn "
            "LEFT JOIN users u ON rn.user_id = u.id WHERE rn.session_id = %s ORDER BY rn.created_at", (sid,)
        ).fetchall()]
    finally:
        db.close()
    return JSONResponse(result)


@router.put("/api/remote-sessions/{sid}")
@require_capability("grid.audits.manage")
async def api_remote_session_update(request: Request, sid: int):
    """Update a remote session (status, times, link, etc.)."""
    data = await _json_body(request)
    from database import get_db
    db = get_db()
    try:
        allowed = ["title", "description", "status", "scheduled_start", "scheduled_end",
                   "actual_start", "actual_end", "meeting_link", "auditor_id", "session_type"]
        sets = []
        vals = []
        for k in allowed:
            if k in data:
                sets.append(f"{k} = %s")
                vals.append(data[k])
        if not sets:
            return JSONResponse({"error": "Nothing to update"}, status_code=400)
        sets.append("updated_at = CURRENT_TIMESTAMP")
        vals.append(sid)
        db.execute(f"UPDATE grid_remote_sessions SET {', '.join(sets)} WHERE id = %s", vals)
        db.commit()
        ds.log_activity(_uid(request), "update_remote_session", "grid_remote_sessions", sid)
    finally:
        db.close()
    return JSONResponse({"success": True})


@router.post("/api/remote-sessions/{sid}/start")
@require_capability("grid.audits.manage")
async def api_remote_session_start(request: Request, sid: int):
    """Mark a session as in-progress (started)."""
    from database import get_db
    db = get_db()
    try:
        db.execute(
            "UPDATE grid_remote_sessions SET status = 'in_progress', actual_start = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = %s", (sid,)
        )
        db.commit()
    finally:
        db.close()
    return JSONResponse({"success": True, "status": "in_progress"})


@router.post("/api/remote-sessions/{sid}/end")
@require_capability("grid.audits.manage")
async def api_remote_session_end(request: Request, sid: int):
    """Mark a session as completed."""
    from database import get_db
    db = get_db()
    try:
        db.execute(
            "UPDATE grid_remote_sessions SET status = 'completed', actual_end = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = %s", (sid,)
        )
        db.commit()
    finally:
        db.close()
    return JSONResponse({"success": True, "status": "completed"})


# ── Remote Session Findings ──────────────────────────────────────────────────

@router.post("/api/remote-sessions/{sid}/findings", status_code=201)
@require_capability("grid.audits.manage")
async def api_remote_finding_create(request: Request, sid: int):
    """Capture a finding during a remote audit session."""
    data = await _json_body(request)
    from database import get_db
    db = get_db()
    try:
        fid = insert_returning_id(
            db,
            "INSERT INTO grid_remote_findings "
            "(session_id, control_id, finding_type, severity, title, description, evidence_ref, raised_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                sid,
                data.get("control_id"),
                data.get("finding_type", "observation"),
                data.get("severity", "minor"),
                data.get("title", "Untitled finding"),
                data.get("description", ""),
                data.get("evidence_ref", ""),
                _uid(request),
            )
        )
        db.commit()
    finally:
        db.close()
    # Emit GRID_FINDING_CREATED so ERM/event handlers can auto-create risks
    severity = data.get("severity", "minor")
    if severity in ("major", "critical"):
        emit(
            GRID_FINDING_CREATED,
            source_module="grid",
            entity_type="finding",
            entity_id=fid,
            payload={
                "title": data.get("title", ""),
                "severity": severity,
                "session_id": sid,
                "description": data.get("description", ""),
                "finding_type": data.get("finding_type", "observation"),
            },
            user_id=_uid(request),
        )
    return JSONResponse({"id": fid}, status_code=201)


@router.put("/api/remote-findings/{fid}")
@require_capability("grid.audits.manage")
async def api_remote_finding_update(request: Request, fid: int):
    """Update a remote finding (status, severity, description)."""
    data = await _json_body(request)
    from database import get_db
    db = get_db()
    try:
        allowed = ["finding_type", "severity", "title", "description", "evidence_ref", "status"]
        sets = []
        vals = []
        for k in allowed:
            if k in data:
                sets.append(f"{k} = %s")
                vals.append(data[k])
        if sets:
            vals.append(fid)
            db.execute(f"UPDATE grid_remote_findings SET {', '.join(sets)} WHERE id = %s", vals)
            db.commit()
    finally:
        db.close()
    return JSONResponse({"success": True})


# ── Remote Session Notes ─────────────────────────────────────────────────────

@router.post("/api/remote-sessions/{sid}/notes", status_code=201)
@require_capability("grid.audits.manage")
async def api_remote_note_create(request: Request, sid: int):
    """Add a timestamped note during a remote session."""
    data = await _json_body(request)
    from database import get_db
    db = get_db()
    try:
        nid = insert_returning_id(
            db,
            "INSERT INTO grid_remote_notes (session_id, user_id, content, timestamp_offset) VALUES (%s,%s,%s,%s)",
            (sid, _uid(request), data.get("content", ""), data.get("timestamp_offset", 0))
        )
        db.commit()
    finally:
        db.close()
    return JSONResponse({"id": nid}, status_code=201)


# ── Remote Session Participants ──────────────────────────────────────────────

@router.post("/api/remote-sessions/{sid}/participants", status_code=201)
@require_capability("grid.audits.manage")
async def api_remote_participant_add(request: Request, sid: int):
    """Add a participant to a remote session."""
    data = await _json_body(request)
    from database import get_db
    db = get_db()
    try:
        pid = insert_returning_id(
            db,
            "INSERT INTO grid_remote_participants (session_id, user_id, external_name, external_email, role) "
            "VALUES (%s,%s,%s,%s,%s)",
            (sid, data.get("user_id"), data.get("name", ""), data.get("email", ""), data.get("role", "auditee"))
        )
        db.commit()
    finally:
        db.close()
    return JSONResponse({"id": pid}, status_code=201)


# ── Report Downloads ────────────────────────────────────────────────────────

@router.get("/api/reports/pdf/{audit_id}")
@require_capability("grid.ai.report")
async def api_report_pdf(request: Request, audit_id: int):
    """Generate and download a branded PDF audit report."""
    from modules.grid import report_service as rpt

    audit = ds.get_audit(audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found")

    # Build AI narrative (best-effort — report still works without it)
    narrative = None
    try:
        controls = audit.get("controls", [])
        total = len(controls)
        complete = sum(1 for c in controls if c.get("status") == "Complete")
        overdue = sum(
            1 for c in controls
            if c.get("status") != "Complete"
            and c.get("due_date", "")
            and c["due_date"] < date.today().isoformat()
        )
        narrative = ai.generate_report_narrative({
            "auditName": audit.get("name"),
            "framework": audit.get("framework_name"),
            "completionPct": round(complete / total * 100) if total else 0,
            "totalControls": total,
            "complete": complete,
            "pending": total - complete - overdue,
            "overdue": overdue,
            "auditDate": audit.get("audit_date"),
            "criticalGaps": [
                c["name"] for c in controls
                if c.get("risk_level") == "Critical" and c.get("status") != "Complete"
            ][:5],
        })
    except Exception:
        pass  # AI unavailable — generate report without narrative

    result = rpt.generate_pdf_report(audit_id, narrative)

    # Auto-save report record
    try:
        fp = Path(result["filePath"])
        ds.create_report({
            "audit_id": audit_id,
            "report_type": "pdf",
            "title": f"{audit.get('name', 'Audit')} — PDF Report",
            "filename": result["fileName"],
            "file_path": result["filePath"],
            "file_size": fp.stat().st_size if fp.exists() else 0,
            "generated_by": _uid(request),
        })
    except Exception:
        pass  # Best-effort persistence

    return FileResponse(
        result["filePath"],
        media_type="application/pdf",
        filename=result["fileName"],
    )


@router.get("/api/reports/docx/{audit_id}")
@require_capability("grid.ai.report")
async def api_report_docx(request: Request, audit_id: int):
    """Generate and download a branded DOCX audit report."""
    from modules.grid import report_service as rpt

    audit = ds.get_audit(audit_id)
    if not audit:
        raise HTTPException(404, "Audit not found")

    # Build AI narrative (best-effort)
    narrative = None
    try:
        controls = audit.get("controls", [])
        total = len(controls)
        complete = sum(1 for c in controls if c.get("status") == "Complete")
        overdue = sum(
            1 for c in controls
            if c.get("status") != "Complete"
            and c.get("due_date", "")
            and c["due_date"] < date.today().isoformat()
        )
        narrative = ai.generate_report_narrative({
            "auditName": audit.get("name"),
            "framework": audit.get("framework_name"),
            "completionPct": round(complete / total * 100) if total else 0,
            "totalControls": total,
            "complete": complete,
            "pending": total - complete - overdue,
            "overdue": overdue,
            "auditDate": audit.get("audit_date"),
            "criticalGaps": [
                c["name"] for c in controls
                if c.get("risk_level") == "Critical" and c.get("status") != "Complete"
            ][:5],
        })
    except Exception:
        pass

    result = rpt.generate_docx_report(audit_id, narrative)

    # Auto-save report record
    try:
        fp = Path(result["filePath"])
        ds.create_report({
            "audit_id": audit_id,
            "report_type": "docx",
            "title": f"{audit.get('name', 'Audit')} — DOCX Report",
            "filename": result["fileName"],
            "file_path": result["filePath"],
            "file_size": fp.stat().st_size if fp.exists() else 0,
            "generated_by": _uid(request),
        })
    except Exception:
        pass  # Best-effort persistence

    return FileResponse(
        result["filePath"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=result["fileName"],
    )


@router.get("/api/reports/list")
@require_capability("grid.audits.view")
async def api_reports_list(request: Request):
    """List all audits with stats for the reports view."""
    audits = ds.list_audits()
    result = []
    for a in audits:
        stats = ds.get_audit_stats(a["id"])
        result.append({
            "id": a["id"],
            "name": a.get("name", ""),
            "framework_name": a.get("framework_name", ""),
            "audit_type": a.get("audit_type", ""),
            "status": a.get("status", ""),
            "audit_date": a.get("audit_date", ""),
            "completionPct": stats.get("completionPct", 0) if stats else 0,
            "totalControls": stats.get("total", 0) if stats else 0,
            "completeControls": stats.get("complete", 0) if stats else 0,
            "overdueControls": stats.get("overdue", 0) if stats else 0,
        })
    return JSONResponse(result)


# ═════════════════════════════════════════════════════════════════════════════
# REPORT PERSISTENCE (saved generated reports)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/reports/saved")
@require_capability("grid.ai.report")
async def api_saved_reports_list(request: Request):
    """List all saved report records, optionally filtered by audit_id."""
    audit_id = request.query_params.get("audit_id")
    return JSONResponse(ds.list_reports(
        audit_id=int(audit_id) if audit_id else None,
    ))


@router.get("/api/reports/saved/{rid}")
@require_capability("grid.ai.report")
async def api_saved_report_detail(request: Request, rid: int):
    rpt = ds.get_report(rid)
    if not rpt:
        raise HTTPException(404, "Report not found")
    return JSONResponse(rpt)


@router.get("/api/reports/saved/{rid}/download")
@require_capability("grid.ai.report")
async def api_saved_report_download(request: Request, rid: int):
    """Download a previously saved report file."""
    rpt = ds.get_report(rid)
    if not rpt:
        raise HTTPException(404, "Report not found")
    fp = Path(rpt["file_path"])
    if not fp.exists():
        raise HTTPException(404, "Report file missing from disk")
    media = (
        "application/pdf" if rpt.get("report_type") == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(
        path=str(fp),
        filename=rpt.get("filename") or fp.name,
        media_type=media,
    )


@router.post("/api/reports/saved")
@require_capability("grid.ai.report")
async def api_saved_report_create(request: Request):
    """Save a report record (called after PDF/DOCX generation)."""
    body = await _json_body(request)
    audit_id = body.get("audit_id")
    if not audit_id:
        raise HTTPException(400, "audit_id required")
    body["generated_by"] = _uid(request)
    rid = ds.create_report(body)
    ds.log_activity(_uid(request), "save_report", "grid_reports", rid)
    return JSONResponse({"id": rid}, status_code=201)


@router.delete("/api/reports/saved/{rid}")
@require_capability("grid.ai.report")
async def api_saved_report_delete(request: Request, rid: int):
    """Delete a saved report record and its file."""
    rpt = ds.get_report(rid)
    if rpt and rpt.get("file_path"):
        fp = Path(rpt["file_path"])
        try:
            if fp.exists():
                fp.unlink()
        except OSError:
            pass
    ds.delete_report(rid)
    ds.log_activity(_uid(request), "delete_report", "grid_reports", rid)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# FOLLOW-UP AUDIT LINKING
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/api/audits/{aid}/followup")
@require_capability("grid.audit.create")
async def api_audit_create_followup(request: Request, aid: int):
    """Create a follow-up audit linked to the parent. Optionally carries forward open NCs."""
    body = await _json_body(request)
    body.setdefault("lead_id", _uid(request))
    new_aid = ds.create_followup_audit(aid, body)
    if new_aid is None:
        raise HTTPException(404, "Parent audit not found")
    ds.log_activity(_uid(request), "create_followup_audit", "grid_audits", new_aid,
                    f"follow-up of audit {aid}")

    # Auto-carry forward open NCs if requested (default: yes)
    carry = body.get("carry_forward_ncs", True)
    nc_count = 0
    if carry:
        nc_count = ds.carry_forward_ncs(aid, new_aid)
        if nc_count:
            ds.log_activity(_uid(request), "carry_forward_ncs", "grid_non_conformances",
                            new_aid, f"{nc_count} NCs from audit {aid}")

    return JSONResponse({
        "id": new_aid,
        "parent_audit_id": aid,
        "carried_forward_ncs": nc_count,
    }, status_code=201)


@router.get("/api/audits/{aid}/lineage")
@require_capability("module.grid.access")
async def api_audit_lineage(request: Request, aid: int):
    """Return the audit chain: ancestors → current → children."""
    lineage = ds.get_audit_lineage(aid)
    return JSONResponse(lineage)


@router.get("/api/audits/{aid}/cross-cycle")
@require_capability("grid.nc.manage")
async def api_audit_cross_cycle(request: Request, aid: int):
    """Compare NC status between this audit and its parent."""
    return JSONResponse(ds.get_cross_cycle_comparison(aid))


# ═════════════════════════════════════════════════════════════════════════════
# AUDIT SIGN-OFF & LOCKING
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/audits/{aid}/signoffs")
@require_capability("module.grid.access")
async def api_audit_signoffs(request: Request, aid: int):
    """List sign-offs for an audit."""
    return JSONResponse(ds.get_signoffs(aid))


@router.post("/api/audits/{aid}/signoffs")
@require_capability("grid.audit.edit")
async def api_audit_signoff(request: Request, aid: int):
    """Record a sign-off (lead or reviewer)."""
    body = await _json_body(request)
    role = body.get("role")
    if role not in ("lead", "reviewer"):
        raise HTTPException(400, "role must be 'lead' or 'reviewer'")
    sid = ds.sign_off_audit(aid, _uid(request), role, body.get("comment"))
    if sid is None:
        raise HTTPException(
            409,
            "Cannot sign off: lead must sign before reviewer"
            if role == "reviewer"
            else "Invalid sign-off role",
        )
    ds.log_activity(_uid(request), f"signoff_{role}", "grid_audit_signoffs", sid)
    return JSONResponse({"ok": True, "id": sid})


@router.delete("/api/audits/{aid}/signoffs/{role}")
@require_capability("grid.audit.edit")
async def api_audit_revoke_signoff(request: Request, aid: int, role: str):
    """Revoke a sign-off (also unlocks the audit)."""
    if role not in ("lead", "reviewer"):
        raise HTTPException(400, "role must be 'lead' or 'reviewer'")
    ds.revoke_signoff(aid, role)
    ds.log_activity(_uid(request), f"revoke_signoff_{role}", "grid_audit_signoffs", aid)
    return JSONResponse({"ok": True})


@router.post("/api/audits/{aid}/lock")
@require_capability("grid.audit.edit")
async def api_audit_lock(request: Request, aid: int):
    """Lock the audit (requires both lead + reviewer sign-offs)."""
    result = ds.lock_audit(aid, _uid(request))
    if result is None:
        raise HTTPException(409, "Both lead and reviewer must sign off before locking")
    ds.log_activity(_uid(request), "lock_audit", "grid_audits", aid)
    return JSONResponse({"ok": True})


@router.post("/api/audits/{aid}/unlock")
@require_capability("grid.audit.delete")
async def api_audit_unlock(request: Request, aid: int):
    """Unlock an audit (admin action — clears all sign-offs)."""
    ds.unlock_audit(aid)
    ds.log_activity(_uid(request), "unlock_audit", "grid_audits", aid)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# PROGRAM DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/program-dashboard")
@require_capability("module.grid.access")
async def api_program_dashboard(request: Request):
    """Multi-audit program overview: posture, trends, NC summary."""
    return JSONResponse(ds.get_program_dashboard())


# ═════════════════════════════════════════════════════════════════════════════
# ARIA POLICY INTEGRATION
# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
# EVIDENCE VAULT INTEGRATION
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/vault-evidence")
@require_capability("module.grid.access")
async def api_vault_evidence(request: Request):
    """Browse central Evidence Vault items with filters."""
    category = request.query_params.get("category")
    module = request.query_params.get("module")
    search = request.query_params.get("q")
    return JSONResponse(ds.list_vault_evidence(
        category=category, module=module, search=search,
    ))


@router.post("/api/controls/{cid}/attach-vault")
@require_capability("grid.evidence.upload")
async def api_attach_vault_item(request: Request, cid: int):
    """Attach a central vault evidence item to a GRID control."""
    body = await _json_body(request)
    vault_id = body.get("vault_evidence_id")
    if not vault_id:
        raise HTTPException(400, "vault_evidence_id required")
    eid = ds.attach_vault_item_to_grid_control(cid, int(vault_id), _uid(request))
    if eid is None:
        raise HTTPException(404, "Vault evidence item not found or archived")
    ds.log_activity(_uid(request), "attach_vault_evidence", "grid_evidence_files", eid,
                    f"vault #{vault_id}")
    return JSONResponse({"ok": True, "evidence_file_id": eid}, status_code=201)


@router.get("/api/aria-policies")
@require_capability("module.grid.access")
async def api_aria_policies(request: Request):
    """List approved ARIA policies available for evidence linking."""
    framework = request.query_params.get("framework")
    control_ref = request.query_params.get("control_ref")
    return JSONResponse(ds.list_aria_policies(
        framework_name=framework,
        control_ref=control_ref,
    ))


@router.post("/api/controls/{cid}/attach-aria-policy")
@require_capability("grid.evidence.upload")
async def api_attach_aria_policy(request: Request, cid: int):
    """Attach an approved ARIA policy document as evidence to a control."""
    body = await _json_body(request)
    aria_doc_id = body.get("aria_document_id")
    if not aria_doc_id:
        raise HTTPException(400, "aria_document_id required")
    eid = ds.attach_aria_policy_as_evidence(cid, int(aria_doc_id), _uid(request))
    if eid is None:
        raise HTTPException(404, "ARIA document not found")
    ds.log_activity(_uid(request), "attach_aria_policy", "grid_evidence_files", eid,
                    f"ARIA doc #{aria_doc_id}")
    return JSONResponse({"ok": True, "evidence_file_id": eid}, status_code=201)


@router.get("/api/policy-requests")
@require_capability("grid.nc.manage")
async def api_policy_requests_list(request: Request):
    """List policy requests, optionally filtered by audit_id."""
    audit_id = request.query_params.get("audit_id")
    status = request.query_params.get("status")
    return JSONResponse(ds.list_policy_requests(
        audit_id=int(audit_id) if audit_id else None,
        status=status,
    ))


@router.post("/api/policy-requests")
@require_capability("grid.nc.manage")
async def api_policy_request_create(request: Request):
    """Request a policy from ARIA when none is available."""
    body = await _json_body(request)
    audit_id = body.get("audit_id")
    if not audit_id:
        raise HTTPException(400, "audit_id required")
    body["requested_by"] = _uid(request)
    rid = ds.create_policy_request(body)
    ds.log_activity(_uid(request), "request_policy", "grid_policy_requests", rid)

    # Get audit name for the event payload
    audit = ds.get_audit(int(audit_id))
    audit_name = audit.get("name", "") if audit else ""

    # Emit cross-module event → creates ARIA task + notification
    emit(
        GRID_POLICY_REQUESTED,
        source_module="grid",
        entity_type="policy_request",
        entity_id=rid,
        payload={
            "title": body.get("title", "Policy needed"),
            "framework_name": body.get("framework_name", ""),
            "control_ref": body.get("control_ref", ""),
            "audit_name": audit_name,
            "description": body.get("description", ""),
        },
        user_id=_uid(request),
    )
    return JSONResponse({"id": rid}, status_code=201)


@router.get("/api/scheduler/status")
@require_capability("grid.audits.manage")
async def api_scheduler_status(request: Request):
    """Return GRID scheduler status and next run times."""
    from modules.grid.scheduler import get_scheduler_status
    return JSONResponse(get_scheduler_status())
