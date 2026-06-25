"""
Evidence Repository — Cross-module evidence vault.

Upload, tag, search, and link evidence to controls/audits/frameworks
across ARIA, GRID, BCM, and Sentinel modules.
"""
import os
import uuid
import hashlib
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates

from core.middleware import require_auth, require_capability
from core.shell_context import shell_ctx
from database import get_db, insert_returning_id, sql_date_offset, sql_current_date

router = APIRouter(prefix="/evidence", tags=["evidence"])

EVIDENCE_DIR = Path(os.getenv("EVIDENCE_DIR", "data/evidence"))
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

shell_templates = Jinja2Templates(directory=["templates", "modules/evidence/templates"])


# ── Helper ──────────────────────────────────────────────────────────────────

def _uid(request: Request) -> int:
    return request.state.user["id"]


# ── SPA Page ────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
@require_auth
async def evidence_page(request: Request):
    """Evidence repository SPA page."""
    ctx = shell_ctx(request, active_module="evidence", active_section="evidence")
    return shell_templates.TemplateResponse(request, "evidence_index.html", ctx)


# ── CRUD API ────────────────────────────────────────────────────────────────

@router.get("/api/items")
@require_auth
async def api_evidence_list(request: Request):
    """List evidence items with optional filters."""
    db = get_db()
    try:
        category = request.query_params.get("category", "")
        status = request.query_params.get("status", "")
        search = request.query_params.get("q", "")
        module = request.query_params.get("module", "")

        where = ["1=1"]
        params = []
        if category:
            where.append("e.category = %s")
            params.append(category)
        if status:
            where.append("e.status = %s")
            params.append(status)
        if search:
            where.append("(e.title LIKE %s OR e.tags LIKE %s OR e.description LIKE %s)")
            params.extend([f"%{search}%"] * 3)
        if module:
            where.append("e.id IN (SELECT evidence_id FROM evidence_links WHERE module = %s)")
            params.append(module)

        view = request.query_params.get("view", "")
        if view == "expiring":
            where.append(
                f"e.expiry_date IS NOT NULL AND e.expiry_date <= {sql_date_offset('+30 days')} "
                f"AND e.expiry_date > {sql_current_date()} AND e.status = 'current'"
            )
        elif view == "unlinked":
            where.append(
                "NOT EXISTS (SELECT 1 FROM evidence_links el WHERE el.evidence_id = e.id)"
            )

        where_sql = " AND ".join(where)
        rows = db.execute(
            f"SELECT e.*, u.full_name as uploaded_by_name, "
            f"(SELECT COUNT(*) FROM evidence_links el WHERE el.evidence_id = e.id) as link_count "
            f"FROM evidence_items e LEFT JOIN users u ON e.uploaded_by = u.id "
            f"WHERE {where_sql} ORDER BY e.updated_at DESC LIMIT 200",
            params
        ).fetchall()
    finally:
        db.close()
    return JSONResponse([dict(r) for r in rows])


@router.post("/api/items", status_code=201)
@require_auth
async def api_evidence_upload(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    category: str = Form("general"),
    tags: str = Form(""),
    replace_id: str = Form(""),
    expiry_date: str = Form(""),
):
    """Upload a new evidence file."""
    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large (max 100MB)")

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    file_hash = hashlib.sha256(content).hexdigest()

    # ── Duplicate detection ────────────────────────────────────────────────
    db = get_db()
    try:
        existing = db.execute(
            "SELECT id, title, status FROM evidence_items WHERE file_hash = %s AND status != 'archived'",
            (file_hash,),
        ).fetchone()
        if existing:
            return JSONResponse({
                "duplicate": True,
                "existing_id": existing["id"],
                "existing_title": existing["title"],
                "file_hash": file_hash,
                "message": f"Identical file already exists as \"{existing['title']}\" (ID {existing['id']}). "
                           "Use the link API to attach it to additional controls instead of uploading again.",
            }, status_code=409)

        # ── Sanitise and store file ────────────────────────────────────────
        original_name = file.filename or "file"
        ext = Path(original_name).suffix.lower()

        # Block dangerous executable extensions
        blocked_extensions = frozenset({
            ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse",
            ".wsf", ".wsh", ".msi", ".scr", ".com", ".pif", ".hta", ".cpl",
            ".inf", ".reg", ".dll", ".sys", ".drv", ".lnk",
        })
        if ext in blocked_extensions:
            return JSONResponse(
                {"error": f"File type '{ext}' is not allowed for security reasons."},
                status_code=400,
            )

        # Validate MIME type against allowlist
        declared_mime = (file.content_type or "application/octet-stream").lower()
        allowed_mimes = frozenset({
            "application/pdf", "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.ms-excel", "application/vnd.ms-powerpoint",
            "text/plain", "text/csv", "text/html", "text/xml",
            "application/json", "application/xml",
            "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml",
            "application/zip", "application/x-zip-compressed",
            "application/octet-stream",  # fallback for unknown — extension check is primary gate
        })
        if declared_mime not in allowed_mimes:
            return JSONResponse(
                {"error": f"MIME type '{declared_mime}' is not permitted."},
                status_code=400,
            )

        stored_name = f"{uuid.uuid4().hex}{ext}"
        dest = EVIDENCE_DIR / stored_name

        with open(dest, "wb") as f:
            f.write(content)

        display_title = title or original_name or "Untitled"

        # ── Version chain: check if this is a new version of existing item ──
        parent_id = None
        version_num = 1
        if replace_id.strip():
            try:
                rid = int(replace_id.strip())
            except (ValueError, TypeError):
                rid = None
            if rid:
                parent_row = db.execute(
                    "SELECT id, version FROM evidence_items WHERE id = %s AND status != 'archived'",
                    (rid,),
                ).fetchone()
                if parent_row:
                    parent_id = parent_row["id"]
                    version_num = parent_row["version"] + 1
                    # Mark old version as superseded
                    db.execute(
                        "UPDATE evidence_items SET status = 'superseded', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (rid,),
                    )

        exp = expiry_date.strip() if expiry_date else None

        eid = insert_returning_id(
            db,
            "INSERT INTO evidence_items (title, description, file_path, file_name, file_size, "
            "file_hash, mime_type, category, tags, version, parent_id, uploaded_by, expiry_date) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                display_title, description, str(stored_name), original_name,
                len(content), file_hash, declared_mime,
                category, tags, version_num, parent_id, _uid(request), exp,
            )
        )
        db.commit()
    finally:
        db.close()

    return JSONResponse({
        "id": eid, "title": display_title, "version": version_num,
        "file_hash": file_hash, "duplicate": False,
    }, status_code=201)


@router.get("/api/items/{eid}")
@require_auth
async def api_evidence_get(request: Request, eid: int):
    """Get evidence item details with linked entities."""
    db = get_db()
    try:
        item = db.execute(
            "SELECT e.*, u.full_name as uploaded_by_name FROM evidence_items e "
            "LEFT JOIN users u ON e.uploaded_by = u.id WHERE e.id = %s", (eid,)
        ).fetchone()
        if not item:
            raise HTTPException(404, "Evidence not found")
        result = dict(item)
        result["links"] = [dict(r) for r in db.execute(
            "SELECT el.*, u.full_name as linked_by_name FROM evidence_links el "
            "LEFT JOIN users u ON el.linked_by = u.id "
            "WHERE el.evidence_id = %s AND el.deleted_at IS NULL "
            "ORDER BY el.created_at DESC",
            (eid,)
        ).fetchall()]
    finally:
        db.close()
    return JSONResponse(result)


@router.put("/api/items/{eid}")
@require_auth
async def api_evidence_update(request: Request, eid: int):
    """Update evidence metadata."""
    data = await request.json()
    db = get_db()
    try:
        allowed = ["title", "description", "category", "tags", "status", "expiry_date"]
        sets = []
        vals = []
        for k in allowed:
            if k in data:
                sets.append(f"{k} = %s")
                vals.append(data[k])
        if not sets:
            return JSONResponse({"error": "Nothing to update"}, status_code=400)
        sets.append("updated_at = CURRENT_TIMESTAMP")
        vals.append(eid)
        db.execute(f"UPDATE evidence_items SET {', '.join(sets)} WHERE id = %s", vals)
        db.commit()
    finally:
        db.close()
    return JSONResponse({"success": True})


@router.delete("/api/items/{eid}")
@require_auth
async def api_evidence_delete(request: Request, eid: int):
    """Soft-delete evidence (mark as archived)."""
    db = get_db()
    try:
        db.execute("UPDATE evidence_items SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = %s", (eid,))
        db.commit()
    finally:
        db.close()
    return JSONResponse({"success": True})


@router.get("/api/items/{eid}/download")
@require_auth
async def api_evidence_download(request: Request, eid: int):
    """Download evidence file."""
    db = get_db()
    try:
        item = db.execute("SELECT file_path, file_name, mime_type FROM evidence_items WHERE id = %s", (eid,)).fetchone()
        if not item:
            raise HTTPException(404, "Evidence not found")
    finally:
        db.close()
    file_path = (EVIDENCE_DIR / item["file_path"]).resolve()
    # Prevent path traversal — ensure resolved path stays within EVIDENCE_DIR
    if not str(file_path).startswith(str(EVIDENCE_DIR.resolve())):
        raise HTTPException(403, "Access denied")
    if not file_path.exists():
        raise HTTPException(404, "File not found on disk")
    return FileResponse(str(file_path), filename=item["file_name"], media_type=item["mime_type"])


@router.get("/api/items/{eid}/download-pdf")
@require_auth
async def api_evidence_download_pdf(request: Request, eid: int):
    """Download evidence file converted to PDF.

    Supports DOCX conversion via LibreOffice headless. PDF and image
    files are returned as-is. Other formats return 400.
    """
    import subprocess
    import tempfile

    db = get_db()
    try:
        item = db.execute(
            "SELECT file_path, file_name, mime_type FROM evidence_items WHERE id = %s",
            (eid,),
        ).fetchone()
        if not item:
            raise HTTPException(404, "Evidence not found")
    finally:
        db.close()

    file_path = (EVIDENCE_DIR / item["file_path"]).resolve()
    if not str(file_path).startswith(str(EVIDENCE_DIR.resolve())):
        raise HTTPException(403, "Access denied")
    if not file_path.exists():
        raise HTTPException(404, "File not found on disk")

    mime = (item["mime_type"] or "").lower()
    fname = item["file_name"] or "document"

    if mime == "application/pdf":
        return FileResponse(str(file_path), filename=fname, media_type="application/pdf")

    docx_mimes = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-powerpoint",
    }
    if mime not in docx_mimes:
        raise HTTPException(
            400,
            "PDF conversion is only available for Office documents. "
            "This file type cannot be converted.",
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run(
                [
                    "libreoffice", "--headless", "--convert-to", "pdf",
                    "--outdir", tmpdir, str(file_path),
                ],
                capture_output=True, text=True, timeout=60,
            )
        except FileNotFoundError:
            raise HTTPException(
                503,
                "PDF conversion requires LibreOffice which is not installed on this server.",
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "PDF conversion timed out.")

        if result.returncode != 0:
            raise HTTPException(500, "PDF conversion failed.")

        pdf_name = Path(file_path.stem).with_suffix(".pdf")
        pdf_path = Path(tmpdir) / pdf_name
        if not pdf_path.exists():
            candidates = list(Path(tmpdir).glob("*.pdf"))
            if candidates:
                pdf_path = candidates[0]
            else:
                raise HTTPException(500, "PDF conversion produced no output.")

        pdf_bytes = pdf_path.read_bytes()

    out_name = Path(fname).stem + ".pdf"
    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


# ── Version History ────────────────────────────────────────────────────────

@router.get("/api/items/{eid}/versions")
@require_auth
async def api_evidence_versions(request: Request, eid: int):
    """Get the full version chain for an evidence item (newest first)."""
    db = get_db()
    try:
        # Walk up to find the root
        root_id = eid
        seen = {root_id}
        while True:
            row = db.execute(
                "SELECT parent_id FROM evidence_items WHERE id = %s", (root_id,)
            ).fetchone()
            if not row or not row["parent_id"]:
                break
            if row["parent_id"] in seen:
                break  # safety: prevent infinite loop on corrupt data
            seen.add(row["parent_id"])
            root_id = row["parent_id"]

        # Walk down from root collecting all versions
        versions = []
        queue = [root_id]
        visited = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            item = db.execute(
                "SELECT id, title, version, status, file_hash, file_size, file_name, "
                "parent_id, uploaded_by, created_at FROM evidence_items WHERE id = %s",
                (current,),
            ).fetchone()
            if item:
                versions.append(dict(item))
                # Find children (newer versions pointing to this as parent)
                children = db.execute(
                    "SELECT id FROM evidence_items WHERE parent_id = %s", (current,)
                ).fetchall()
                for c in children:
                    queue.append(c["id"])

        versions.sort(key=lambda v: v["version"], reverse=True)
    finally:
        db.close()
    return JSONResponse({"evidence_id": eid, "versions": versions})


# ── Integrity Verification ────────────────────────────────────────────────

@router.get("/api/items/{eid}/verify")
@require_auth
async def api_evidence_verify(request: Request, eid: int):
    """Re-hash the file on disk and compare to stored hash. Proves evidence integrity."""
    db = get_db()
    try:
        item = db.execute(
            "SELECT file_path, file_hash, file_name, title FROM evidence_items WHERE id = %s",
            (eid,),
        ).fetchone()
        if not item:
            raise HTTPException(404, "Evidence not found")
    finally:
        db.close()

    stored_hash = item["file_hash"]
    if not stored_hash:
        return JSONResponse({
            "verified": False,
            "reason": "no_hash",
            "message": "This item was uploaded before hash verification was enabled.",
        })

    file_on_disk = (EVIDENCE_DIR / item["file_path"]).resolve()
    if not str(file_on_disk).startswith(str(EVIDENCE_DIR.resolve())):
        return JSONResponse({
            "verified": False,
            "reason": "path_violation",
            "message": "Evidence file path is invalid.",
        })
    if not file_on_disk.exists():
        return JSONResponse({
            "verified": False,
            "reason": "file_missing",
            "message": "The evidence file is missing from disk storage.",
        })

    # Read and hash in chunks to handle large files without memory spikes
    h = hashlib.sha256()
    with open(file_on_disk, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    disk_hash = h.hexdigest()

    if disk_hash == stored_hash:
        return JSONResponse({
            "verified": True,
            "file_name": item["file_name"],
            "hash": stored_hash,
            "message": "File integrity verified — content matches original upload.",
        })
    else:
        return JSONResponse({
            "verified": False,
            "reason": "hash_mismatch",
            "stored_hash": stored_hash,
            "disk_hash": disk_hash,
            "message": "INTEGRITY FAILURE — file on disk does not match the original upload hash.",
        })


# ── Linking API ─────────────────────────────────────────────────────────────

@router.post("/api/items/{eid}/links", status_code=201)
@require_auth
async def api_evidence_link_create(request: Request, eid: int):
    """Link evidence to a module entity (control, audit, risk, etc.).

    If the entity is a grid_control that has IMS-equivalent mappings, the
    evidence is automatically inherited by all mapped controls so a single
    upload satisfies multiple frameworks.
    """
    data = await request.json()
    module      = data.get("module", "")
    entity_type = data.get("entity_type", "")
    entity_id   = data.get("entity_id")
    user_id     = _uid(request)

    db = get_db()
    try:
        lid = insert_returning_id(
            db,
            "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s,%s,%s,%s,%s)",
            (eid, module, entity_type, entity_id, user_id)
        )
        db.commit()

        # ── IMS evidence inheritance ──────────────────────────────────────
        # When evidence is linked to a grid_control that is part of an IMS audit,
        # auto-create evidence_links for all ims_equivalent mapped controls.
        if entity_type in ("grid_control", "control") and entity_id:
            mapped_ctrls = db.execute("""
                SELECT
                    CASE WHEN gcm.source_control_id=%s THEN gcm.target_control_id
                         ELSE gcm.source_control_id END AS mapped_ctrl_id
                FROM grid_control_mappings gcm
                WHERE (gcm.source_control_id=%s OR gcm.target_control_id=%s)
                  AND gcm.mapping_type='ims_equivalent'
            """, (entity_id, entity_id, entity_id)).fetchall()

            for mc in mapped_ctrls:
                mapped_id = mc[0]
                # Don't duplicate if already linked
                exists = db.execute(
                    "SELECT 1 FROM evidence_links WHERE evidence_id=%s AND entity_type=%s AND entity_id=%s AND deleted_at IS NULL",
                    (eid, entity_type, mapped_id)
                ).fetchone()
                if not exists:
                    db.execute(
                        "INSERT INTO evidence_links "
                        "(evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (eid, module, entity_type, mapped_id, user_id)
                    )
            db.commit()

        # ── ARIA control mapping inheritance ─────────────────────────────
        # When evidence is linked to an aria 'control', auto-inherit to mapped aria controls.
        if module == "aria" and entity_type == "control" and entity_id:
            mapped_aria = db.execute("""
                SELECT
                    CASE WHEN m.source_control_id=%s THEN m.target_control_id
                         ELSE m.source_control_id END AS mapped_id
                FROM aria_control_mappings m
                WHERE (m.source_control_id=%s OR m.target_control_id=%s)
                  AND m.mapping_type IN ('equivalent','ims_equivalent')
            """, (entity_id, entity_id, entity_id)).fetchall()
            for mr in mapped_aria:
                exists = db.execute(
                    "SELECT 1 FROM evidence_links WHERE evidence_id=%s AND module='aria' AND entity_type='control' AND entity_id=%s AND deleted_at IS NULL",
                    (eid, mr[0])
                ).fetchone()
                if not exists:
                    db.execute(
                        "INSERT INTO evidence_links "
                        "(evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (eid, "aria", "control", mr[0], user_id)
                    )
            db.commit()
    finally:
        db.close()
    return JSONResponse({"id": lid}, status_code=201)


@router.delete("/api/links/{lid}")
@require_auth
async def api_evidence_link_delete(request: Request, lid: int):
    """Soft-delete an evidence link (preserves audit trail)."""
    db = get_db()
    try:
        db.execute(
            "UPDATE evidence_links SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s WHERE id = %s",
            (_uid(request), lid),
        )
        db.commit()
    finally:
        db.close()
    return JSONResponse({"success": True})


@router.post("/api/items/{eid}/suggest-links")
@require_auth
async def api_evidence_suggest_links(request: Request, eid: int):
    """AI-powered suggestion of relevant controls and entities to link evidence to."""
    from core.ai_client import is_configured, create_message, safe_json_parse
    if not is_configured():
        return JSONResponse({"error": "AI not configured"}, status_code=503)
    db = get_db()
    try:
        item = db.execute(
            "SELECT id, title, description, category, tags FROM evidence_items WHERE id = %s", (eid,)
        ).fetchone()
        if not item:
            raise HTTPException(404, "Evidence not found")
        existing = [dict(r) for r in db.execute(
            "SELECT module, entity_type, entity_id FROM evidence_links WHERE evidence_id = %s AND deleted_at IS NULL", (eid,)
        ).fetchall()]
        controls = [dict(r) for r in db.execute(
            "SELECT id, reference_code, title, framework_name FROM aria_controls LIMIT 100"
        ).fetchall()]
        audits = [dict(r) for r in db.execute(
            "SELECT id, name, framework_name FROM grid_audits WHERE status != 'closed' LIMIT 30"
        ).fetchall()]
        risks = [dict(r) for r in db.execute(
            "SELECT id, name, category FROM erm_risks LIMIT 50"
        ).fetchall()]
    finally:
        db.close()
    evidence_info = dict(item)
    prompt = (
        "Evidence item:\n"
        f"Title: {evidence_info.get('title','')}\n"
        f"Description: {evidence_info.get('description','')}\n"
        f"Category: {evidence_info.get('category','')}\n"
        f"Tags: {evidence_info.get('tags','')}\n\n"
        f"Already linked to: {existing}\n\n"
        f"Available controls: {controls[:50]}\n\n"
        f"Available audits: {audits[:20]}\n\n"
        f"Available risks: {risks[:30]}\n\n"
        "Suggest up to 5 linkages. Return JSON array of objects with keys: "
        "module (aria/grid/erm), entity_type (control/audit/risk), entity_id (int), "
        "entity_name (str), reason (str, one sentence). "
        "Do NOT suggest items already linked. Only suggest high-confidence matches."
    )
    try:
        raw = create_message(
            [{"role": "user", "content": prompt}],
            system="You are a GRC evidence linking assistant. Respond ONLY with a JSON array, no other text.",
            max_tokens=800,
        )
        suggestions = safe_json_parse(raw)
        if not isinstance(suggestions, list):
            suggestions = []
    except Exception:
        suggestions = []
    return JSONResponse({"suggestions": suggestions})


@router.get("/api/items/{eid}/audit")
@require_auth
async def api_evidence_audit(request: Request, eid: int):
    """Full link history for an evidence item — active and soft-deleted."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT el.id, el.module, el.entity_type, el.entity_id, "
            "       el.created_at, el.deleted_at, "
            "       lu.full_name AS linked_by_name, "
            "       du.full_name AS deleted_by_name "
            "FROM evidence_links el "
            "LEFT JOIN users lu ON el.linked_by = lu.id "
            "LEFT JOIN users du ON el.deleted_by = du.id "
            "WHERE el.evidence_id = %s "
            "ORDER BY el.created_at DESC",
            (eid,),
        ).fetchall()
    finally:
        db.close()
    return JSONResponse([dict(r) for r in rows])


@router.get("/api/linked")
@require_auth
async def api_evidence_for_entity(request: Request):
    """Get all evidence linked to a specific entity."""
    module = request.query_params.get("module", "")
    entity_type = request.query_params.get("entity_type", "")
    entity_id = request.query_params.get("entity_id", "")
    if not all([module, entity_type, entity_id]):
        return JSONResponse({"error": "module, entity_type, entity_id required"}, status_code=400)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT e.*, el.id as link_id FROM evidence_items e "
            "JOIN evidence_links el ON e.id = el.evidence_id "
            "WHERE el.module = %s AND el.entity_type = %s AND el.entity_id = %s AND e.status != 'archived' "
            "ORDER BY e.updated_at DESC",
            (module, entity_type, int(entity_id))
        ).fetchall()
    finally:
        db.close()
    return JSONResponse([dict(r) for r in rows])


@router.get("/api/auto/{module}/{entity_type}/{entity_id}")
@require_auth
async def api_auto_evidence(request: Request, module: str, entity_type: str, entity_id: int):
    """Get auto-generated evidence for a specific entity.

    Auto-evidence is identified by the 'auto' tag (inserted by event handlers
    in Phase C).  Returns items newest-first with link metadata.
    """
    # Validate module to prevent SQL injection via URL path
    valid_modules = frozenset({"aria", "grid", "bcm", "sentinel", "platform"})
    mod = module.strip().lower()
    etype = entity_type.strip().lower()
    if mod not in valid_modules:
        return JSONResponse({"error": "Invalid module"}, status_code=400)

    db = get_db()
    try:
        rows = db.execute(
            "SELECT e.id, e.title, e.description, e.category, e.tags, "
            "e.status, e.created_at, e.updated_at, el.id as link_id "
            "FROM evidence_items e "
            "JOIN evidence_links el ON e.id = el.evidence_id "
            "WHERE el.module = %s AND el.entity_type = %s AND el.entity_id = %s "
            "AND e.tags LIKE '%%auto%%' AND e.status != 'archived' "
            "ORDER BY e.created_at DESC",
            (mod, etype, entity_id),
        ).fetchall()
    finally:
        db.close()
    return JSONResponse({
        "module": mod,
        "entity_type": etype,
        "entity_id": entity_id,
        "count": len(rows),
        "items": [dict(r) for r in rows],
    })


# ── Cross-Module Link Resolution ──────────────────────────────────────────

# Mapping: (module, entity_type) → (table_name, name_column, url_template)
# url_template uses {id} as placeholder for the entity_id
_ENTITY_RESOLVERS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("aria", "control"):    ("aria_controls",       "name",   "/aria#controls/{id}"),
    ("aria", "document"):   ("aria_documents",      "title",  "/aria#documents/{id}"),
    ("aria", "risk"):       ("aria_risks",          "title",  "/aria#risks/{id}"),
    ("aria", "framework"):  ("aria_frameworks",     "name",   "/aria#frameworks/{id}"),
    ("grid", "audit"):      ("grid_audits",         "name",   "/grid#audits/{id}"),
    ("grid", "control"):    ("grid_controls",       "name",   "/grid#controls/{id}"),
    ("grid", "nc"):         ("grid_non_conformances", "title", "/grid#ncs/{id}"),
    ("bcm", "plan"):        ("bcm_plans",           "name",   "/bcm#plans/{id}"),
    ("bcm", "incident"):    ("bcm_incidents",       "title",  "/bcm#incidents/{id}"),
    ("bcm", "risk"):        ("bcm_risks",           "title",  "/bcm#risks/{id}"),
    ("bcm", "bia"):         ("bcm_bia_records",     "process_name", "/bcm#bia/{id}"),
    ("sentinel", "ropa"):   ("sentinel_ropa",       "process_name", "/sentinel#ropa/{id}"),
    ("sentinel", "dpia"):   ("sentinel_dpias",      "title",  "/sentinel#dpia/{id}"),
    ("sentinel", "breach"):  ("sentinel_breaches",  "title",  "/sentinel#breaches/{id}"),
    ("sentinel", "dsr"):    ("sentinel_dsr",        "subject_name", "/sentinel#dsr/{id}"),
    ("sentinel", "vendor"):  ("sentinel_vendors",   "name",   "/sentinel#vendors/{id}"),
}


@router.get("/api/resolve-links")
@require_auth
async def api_resolve_links(request: Request):
    """Batch-resolve evidence link entity IDs to display names and URLs.

    Query params:
        links — JSON array of {module, entity_type, entity_id} objects (max 50)

    Returns list of {module, entity_type, entity_id, name, url} with name/url
    set to null for unresolvable entries.
    """
    import json as json_lib
    raw = request.query_params.get("links", "[]")
    try:
        link_specs = json_lib.loads(raw)
    except (json_lib.JSONDecodeError, ValueError):
        return JSONResponse({"error": "Invalid JSON in 'links' parameter"}, status_code=400)

    if not isinstance(link_specs, list) or len(link_specs) > 50:
        return JSONResponse({"error": "links must be an array of max 50 items"}, status_code=400)

    results = []
    db = get_db()
    try:
        for spec in link_specs:
            module = str(spec.get("module", "")).strip().lower()
            entity_type = str(spec.get("entity_type", "")).strip().lower()
            try:
                entity_id = int(spec.get("entity_id", 0))
            except (ValueError, TypeError):
                entity_id = 0

            resolver = _ENTITY_RESOLVERS.get((module, entity_type))
            entry = {
                "module": module,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "name": None,
                "url": None,
            }

            if resolver and entity_id:
                table, name_col, url_tpl = resolver
                # Use parameterised query — table/column names are from the
                # hardcoded _ENTITY_RESOLVERS dict, never from user input.
                row = db.execute(
                    f"SELECT {name_col} FROM {table} WHERE id = %s", (entity_id,)
                ).fetchone()
                if row:
                    entry["name"] = row[name_col]
                    entry["url"] = url_tpl.replace("{id}", str(entity_id))

            results.append(entry)
    finally:
        db.close()

    return JSONResponse(results)


# ── Stats ───────────────────────────────────────────────────────────────────

@router.get("/api/search-entities")
@require_auth
async def api_search_entities(request: Request):
    """Search for entities across modules to link evidence to."""
    module = request.query_params.get("module", "")
    entity_type = request.query_params.get("entity_type", "")
    q = request.query_params.get("q", "")

    valid_modules = frozenset({"aria", "grid", "bcm", "sentinel"})
    if module not in valid_modules:
        return JSONResponse({"error": "Invalid module"}, 400)

    # Map (module, entity_type) → (table, name_col, id_col)
    entity_map = {
        ("aria", "control"): ("aria_controls", "name", "id"),
        ("aria", "document"): ("aria_documents", "title", "id"),
        ("aria", "risk"): ("aria_risks", "title", "id"),
        ("aria", "framework"): ("aria_frameworks", "name", "id"),
        ("grid", "audit"): ("grid_audits", "name", "id"),
        ("grid", "control"): ("grid_controls", "name", "id"),
        ("grid", "nc"): ("grid_non_conformances", "title", "id"),
        ("bcm", "plan"): ("bcm_plans", "name", "id"),
        ("bcm", "incident"): ("bcm_incidents", "title", "id"),
        ("bcm", "risk"): ("bcm_risks", "title", "id"),
        ("sentinel", "ropa"): ("sentinel_ropa", "process_name", "id"),
        ("sentinel", "dpia"): ("sentinel_dpias", "title", "id"),
        ("sentinel", "breach"): ("sentinel_breaches", "title", "id"),
    }

    key = (module, entity_type)
    if key not in entity_map:
        return JSONResponse({"error": "Unknown entity type"}, 400)

    table, name_col, id_col = entity_map[key]
    db = get_db()
    try:
        sql = f"SELECT {id_col} AS id, {name_col} AS name FROM {table}"
        params = []
        if q:
            sql += f" WHERE {name_col} LIKE %s"
            params.append(f"%{q}%")
        sql += f" ORDER BY {name_col} LIMIT 50"
        rows = db.execute(sql, params).fetchall()
    except Exception:
        return JSONResponse([])
    finally:
        db.close()
    return JSONResponse([dict(r) for r in rows])


@router.get("/api/coverage")
@require_auth
async def api_evidence_coverage(request: Request):
    """Evidence coverage per module: entities with evidence vs without."""
    db = get_db()
    try:
        coverage = {}
        # Define countable entities per module
        checks = [
            ("aria",     "control",        "aria_controls",         "id"),
            ("aria",     "document",       "aria_documents",        "id"),
            ("aria",     "risk",           "aria_risks",            "id"),
            ("grid",     "audit",          "grid_audits",           "id"),
            ("grid",     "control",        "grid_controls",         "id"),
            ("grid",     "non_conformance","grid_non_conformances", "id"),
            ("bcm",      "plan",           "bcm_plans",             "id"),
            ("bcm",      "incident",       "bcm_incidents",         "id"),
            ("bcm",      "risk",           "bcm_risks",             "id"),
            ("sentinel", "dpia",           "sentinel_dpias",        "id"),
            ("sentinel", "breach",         "sentinel_breaches",     "id"),
            ("sentinel", "ropa",           "sentinel_ropa",         "id"),
            ("sentinel", "dsr",            "sentinel_dsr",          "id"),
            ("sentinel", "vendor",         "sentinel_vendors",      "id"),
        ]
        for mod, etype, table, id_col in checks:
            try:
                total = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                with_ev = db.execute(
                    f"SELECT COUNT(DISTINCT t.{id_col}) FROM {table} t "
                    f"JOIN evidence_links el ON el.entity_id=t.{id_col} "
                    f"AND el.module=%s AND el.entity_type=%s",
                    (mod, etype),
                ).fetchone()[0]
                if mod not in coverage:
                    coverage[mod] = {"total": 0, "with_evidence": 0, "entities": []}
                coverage[mod]["total"] += total
                coverage[mod]["with_evidence"] += with_ev
                coverage[mod]["entities"].append({
                    "type": etype, "total": total,
                    "with_evidence": with_ev,
                    "pct": round(with_ev / total * 100) if total else 0,
                })
            except Exception:
                pass  # Table may not exist yet
        # Calculate module-level percentages
        for mod in coverage:
            t = coverage[mod]["total"]
            w = coverage[mod]["with_evidence"]
            coverage[mod]["pct"] = round(w / t * 100) if t else 0
    finally:
        db.close()
    return JSONResponse(coverage)


@router.get("/api/stats")
@require_auth
async def api_evidence_stats(request: Request):
    """Evidence repository statistics with per-module breakdown."""
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM evidence_items WHERE status != 'archived'").fetchone()[0]
        by_category = db.execute(
            "SELECT category, COUNT(*) as c FROM evidence_items WHERE status != 'archived' GROUP BY category"
        ).fetchall()
        expiring_soon = db.execute(
            "SELECT COUNT(*) FROM evidence_items WHERE status = 'current' "
            f"AND expiry_date IS NOT NULL AND expiry_date <= {sql_date_offset('+30 days')} "
            f"AND expiry_date > {sql_current_date()}"
        ).fetchone()[0]
        total_links = db.execute("SELECT COUNT(*) FROM evidence_links").fetchone()[0]
        unlinked = db.execute(
            "SELECT COUNT(*) FROM evidence_items e WHERE e.status != 'archived' "
            "AND NOT EXISTS (SELECT 1 FROM evidence_links el WHERE el.evidence_id = e.id)"
        ).fetchone()[0]
        # Per-module breakdown
        by_module = db.execute(
            "SELECT el.module, COUNT(DISTINCT el.evidence_id) as c "
            "FROM evidence_links el "
            "JOIN evidence_items e ON el.evidence_id = e.id "
            "WHERE e.status != 'archived' AND el.deleted_at IS NULL "
            "GROUP BY el.module"
        ).fetchall()
        # Expiring within 7 days
        expiring_7 = db.execute(
            "SELECT COUNT(*) FROM evidence_items WHERE status = 'current' "
            f"AND expiry_date IS NOT NULL AND expiry_date <= {sql_date_offset('+7 days')} "
            f"AND expiry_date > {sql_current_date()}"
        ).fetchone()[0]
        # Recently added (last 5 non-archived)
        recent_rows = db.execute(
            "SELECT id, title, category, file_name, created_at "
            "FROM evidence_items WHERE status != 'archived' "
            "ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    finally:
        db.close()
    return JSONResponse({
        "total": total,
        "by_category": {r["category"]: r["c"] for r in by_category},
        "by_module": {r["module"]: r["c"] for r in by_module},
        "expiring_soon": expiring_soon,
        "expiring_7_days": expiring_7,
        "total_links": total_links,
        "unlinked": unlinked,
        "recently_added": [dict(r) for r in recent_rows],
    })
