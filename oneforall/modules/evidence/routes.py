"""
Evidence Repository — Cross-module evidence vault.

Upload, tag, search, and link evidence to controls/audits/frameworks
across ARIA, GRID, BCM, and Sentinel modules.
"""
import logging
import os
import uuid
import hashlib
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core.best_effort import swallowed
from core.middleware import require_auth, require_capability
from core.rbac import has_capability, user_modules
from core.shell_context import shell_ctx
from database import get_db, insert_returning_id, sql_date_offset, sql_current_date
from modules.evidence.scope import current_library_sql, evidence_scope_sql, evidence_search_sql
from modules.governance.data_service import bu_scope_ids

router = APIRouter(prefix="/evidence", tags=["evidence"])
log = logging.getLogger("oneforall.evidence")

# PLAN-36 P06: registers this list's exact query-param names (matching
# GET /api/items below) as the allowlist a saved view may store for this
# module -- the only things saved_views.create_saved_view will ever accept
# into filter_json, which closes off "malicious filter JSON" by never
# letting it hold anything else.
from modules.saved_views.data_service import register_view_schema as _register_view_schema
_register_view_schema(
    "evidence", "items_list",
    allowed_params={"category", "status", "q", "module", "view"},
    sortable_fields={"updated_at", "title", "expiry_date", "status"},
    available_columns={"title", "category", "status", "expiry_date", "uploaded_by_name", "link_count"},
)

EVIDENCE_DIR = Path(os.getenv("EVIDENCE_DIR", "data/evidence"))
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
_PAGE_SIZES = (25, 50)

# Known magic-byte signatures keyed by extension: list of (signature, offset) pairs.
# Only extensions with reliable binary headers are listed; text formats (.txt/.csv/etc.) are omitted.
_MAGIC: dict = {
    ".pdf":  [(b"%PDF", 0)],
    ".png":  [(b"\x89PNG\r\n\x1a\n", 0)],
    ".jpg":  [(b"\xff\xd8\xff", 0)],
    ".jpeg": [(b"\xff\xd8\xff", 0)],
    ".gif":  [(b"GIF87a", 0), (b"GIF89a", 0)],
    ".webp": [(b"RIFF", 0)],
    ".docx": [(b"PK\x03\x04", 0), (b"PK\x05\x06", 0)],
    ".xlsx": [(b"PK\x03\x04", 0), (b"PK\x05\x06", 0)],
    ".pptx": [(b"PK\x03\x04", 0), (b"PK\x05\x06", 0)],
    ".zip":  [(b"PK\x03\x04", 0), (b"PK\x05\x06", 0), (b"PK\x07\x08", 0)],
    ".doc":  [(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0)],
    ".xls":  [(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0)],
    ".ppt":  [(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0)],
}

shell_templates = Jinja2Templates(directory=["templates", "modules/evidence/templates"])


# ── Helper ──────────────────────────────────────────────────────────────────

def _uid(request: Request) -> int:
    return request.state.user["id"]


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    from core.sanitize import sanitize_dict
    return sanitize_dict(body)


def _scoped_evidence_item(db, eid: int, user: dict):
    """Fetch an evidence row only if the caller may see it (org and business unit scope, super admin
    unrestricted). None for a missing id and an out-of-scope id alike, so a 404 never confirms an id."""
    scope_sql, scope_params = evidence_scope_sql(user)
    return db.execute(
        f"SELECT e.* FROM evidence_items e WHERE e.id = %s AND {scope_sql}", [eid, *scope_params]
    ).fetchone()


# ── SPA Page ────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
@require_auth
async def evidence_page(request: Request):
    """Evidence repository SPA page."""
    ctx = shell_ctx(request, active_module="evidence", active_section="evidence")
    ctx["can_bulk_archive"] = has_capability(request.state.user, "evidence.delete")
    return shell_templates.TemplateResponse(request, "evidence_index.html", ctx)


# ── CRUD API ────────────────────────────────────────────────────────────────

@router.get("/api/items")
@require_auth
async def api_evidence_list(request: Request):
    """List one page of evidence items: {items, total, page, page_size, pages}."""
    qp = request.query_params
    try:
        page_size = int(qp.get("page_size", ""))
    except ValueError:
        page_size = _PAGE_SIZES[0]
    if page_size not in _PAGE_SIZES:
        page_size = _PAGE_SIZES[0]
    try:
        page = max(1, int(qp.get("page", "1")))
    except ValueError:
        page = 1

    scope_sql, scope_params = evidence_scope_sql(request.state.user)
    search_sql, search_params = evidence_search_sql(qp.get("q", ""))
    where = [scope_sql, search_sql]
    params = [*scope_params, *search_params]
    if qp.get("category"):
        where.append("e.category = %s")
        params.append(qp["category"])
    if qp.get("module"):
        where.append(
            "e.id IN (SELECT evidence_id FROM evidence_links WHERE module = %s AND deleted_at IS NULL)"
        )
        params.append(qp["module"])

    view = qp.get("view", "")
    if view == "archived":
        where.append("e.status = 'archived'")
    elif view == "superseded":
        where.append("e.status = 'superseded'")
    elif view == "expiring":
        where.append(
            "e.status = 'current' AND e.expiry_date IS NOT NULL "
            f"AND e.expiry_date <= {sql_date_offset('+30 days')} AND e.expiry_date > {sql_current_date()}"
        )
    elif view == "unlinked":
        where.append(current_library_sql())
        where.append(
            "NOT EXISTS (SELECT 1 FROM evidence_links el WHERE el.evidence_id = e.id AND el.deleted_at IS NULL)"
        )
    else:
        where.append("e.status != 'archived'")
        if qp.get("status"):
            where.append("e.status = %s")
            params.append(qp["status"])
        else:
            where.append("e.status != 'superseded'")

    where_sql = " AND ".join(where)
    db = get_db()
    try:
        total = db.execute(f"SELECT COUNT(*) FROM evidence_items e WHERE {where_sql}", params).fetchone()[0]
        pages = max(1, -(-total // page_size))
        page = min(page, pages)
        rows = db.execute(
            f"SELECT e.*, u.full_name as uploaded_by_name, "
            f"(SELECT COUNT(*) FROM evidence_links el WHERE el.evidence_id = e.id AND el.deleted_at IS NULL) as link_count "
            f"FROM evidence_items e LEFT JOIN users u ON e.uploaded_by = u.id "
            f"WHERE {where_sql} ORDER BY e.updated_at DESC, e.id DESC LIMIT %s OFFSET %s",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    finally:
        db.close()
    return JSONResponse({
        "items": [dict(r) for r in rows], "total": total,
        "page": page, "page_size": page_size, "pages": pages,
    })


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
    user = request.state.user
    if not user.get("is_super_admin") and not user.get("org_id"):
        raise HTTPException(403, "Your account has no organization to upload evidence for")
    org_id = None if user.get("is_super_admin") else user.get("org_id")

    from core.sanitize import sanitize_str as _s
    title, description, category, tags = _s(title), _s(description), _s(category), _s(tags)
    expiry_date = _s(expiry_date)
    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large (max 100MB)")

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    content = await file.read()

    # Magic-byte check: verify content matches declared extension
    original_ext_check = Path(file.filename or "file").suffix.lower()
    sigs = _MAGIC.get(original_ext_check)
    if sigs:
        header = content[:16]
        if not any(header[off: off + len(sig)] == sig for sig, off in sigs):
            return JSONResponse(
                {"error": "File content does not match its declared type."},
                status_code=400,
            )

    file_hash = hashlib.sha256(content).hexdigest()

    # ── Duplicate detection (scoped to the caller's own org -- a hash match
    # in another org must never confirm that org's document exists) ────────
    db = get_db()
    try:
        if user.get("is_super_admin"):
            existing = db.execute(
                "SELECT id, title, status FROM evidence_items WHERE file_hash = %s AND status != 'archived'",
                (file_hash,),
            ).fetchone()
        else:
            existing = db.execute(
                "SELECT id, title, status FROM evidence_items "
                "WHERE file_hash = %s AND status != 'archived' AND org_id = %s",
                (file_hash, org_id),
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

        # Block dangerous executable extensions (including HTML/SVG which can carry XSS)
        blocked_extensions = frozenset({
            ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".js", ".jse",
            ".wsf", ".wsh", ".msi", ".scr", ".com", ".pif", ".hta", ".cpl",
            ".inf", ".reg", ".dll", ".sys", ".drv", ".lnk", ".html", ".htm",
            ".svg", ".xhtml",
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
            "text/plain", "text/csv", "text/xml",
            "application/json", "application/xml",
            "image/png", "image/jpeg", "image/gif", "image/webp",
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
                parent_row = _scoped_evidence_item(db, rid, user)
                if parent_row and parent_row["status"] == "archived":
                    parent_row = None
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
            "file_hash, mime_type, category, tags, version, parent_id, uploaded_by, expiry_date, org_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                display_title, description, str(stored_name), original_name,
                len(content), file_hash, declared_mime,
                category, tags, version_num, parent_id, _uid(request), exp, org_id,
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
        if not _scoped_evidence_item(db, eid, request.state.user):
            raise HTTPException(404, "Evidence not found")
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
    result["can_delete"] = has_capability(request.state.user, "evidence.delete")
    return JSONResponse(result)


def _canonical_controls_linked_to(db, evidence_ids):
    """Canonical controls with a live link to any of these items. Read it before the change:
    archiving or deleting an item removes the links this looks for."""
    if not evidence_ids:
        return []
    marks = ",".join(["%s"] * len(evidence_ids))
    rows = db.execute(
        "SELECT DISTINCT entity_id FROM evidence_links WHERE entity_type = 'canonical_control' "
        f"AND deleted_at IS NULL AND evidence_id IN ({marks})",
        list(evidence_ids),
    ).fetchall()
    return [r[0] for r in rows]


def _rescore_controls(control_ids):
    """Rescore these canonical controls once the change that affects them has committed, so the
    stored score (and the ERM residual risk worked out from it) does not wait for the 03:00 UTC
    job. A failure is logged and never raised: the user's action already succeeded."""
    if not control_ids:
        return
    from modules.governance.effectiveness import recompute_controls_by_ids
    db = get_db()
    try:
        recompute_controls_by_ids(db, sorted(set(control_ids)))
        db.commit()
    except Exception as exc:
        log.warning("Control rescore after an evidence change failed: %s", exc)
    finally:
        db.close()


@router.put("/api/items/bulk-archive")
@require_auth
async def api_evidence_bulk_archive(request: Request):
    """PLAN-36 P06: the evidence module's own first bulk action, built on
    the generic modules.saved_views.execute_bulk_action engine. Every id is
    independently re-authorized through the exact same _scoped_evidence_item
    org-scope check and evidence.delete capability the single-item
    DELETE /api/items/{eid} already enforces -- the posted id list is never
    itself treated as authorization.

    Registered before PUT /api/items/{eid} below: Starlette matches routes
    in registration order and only converts a path param to its declared
    type (eid: int) *after* a pattern match, so if the parameterized route
    were registered first it would "steal" this exact URL and fail int
    conversion on the literal string 'bulk-archive' with its own 422,
    before this route ever got a chance -- confirmed directly (first draft
    of this endpoint sat after {eid} and every request to it 422'd)."""
    from modules.saved_views.data_service import execute_bulk_action
    user = request.state.user
    if not has_capability(user, "evidence.delete"):
        return JSONResponse({"error": "Permission denied"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    ids = body.get("ids", [])
    if not ids or not isinstance(ids, list):
        raise HTTPException(400, "ids (list of evidence item IDs) required")

    def _authorize(db, actor, eid):
        item = _scoped_evidence_item(db, eid, actor)
        if not item:
            return False, "Not found or outside your organization."
        if item["status"] == "archived":
            return False, "Already archived."
        return True, None

    touched_controls = []

    def _execute(db, actor, eid):
        touched_controls.extend(_canonical_controls_linked_to(db, [eid]))
        db.execute(
            "UPDATE evidence_items SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (eid,),
        )
        db.execute(
            "UPDATE evidence_links SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s "
            "WHERE evidence_id = %s AND deleted_at IS NULL",
            (actor["id"], eid),
        )

    db = get_db()
    try:
        result = execute_bulk_action(
            db, user, module="evidence", action_name="bulk_archive", record_ids=ids,
            authorize_fn=_authorize, execute_fn=_execute,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
    finally:
        db.close()
    _rescore_controls(touched_controls)
    return JSONResponse({"ok": True, **result})


@router.put("/api/items/{eid}")
@require_auth
async def api_evidence_update(request: Request, eid: int):
    """Update evidence metadata."""
    data = await _json_body(request)
    db = get_db()
    try:
        if not _scoped_evidence_item(db, eid, request.state.user):
            raise HTTPException(404, "Evidence not found")
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
        recompute_confidence(db, eid)
        db.commit()
        # Status and expiry decide whether the item still counts towards a control's score.
        touched_controls = (
            _canonical_controls_linked_to(db, [eid]) if ("status" in data or "expiry_date" in data) else []
        )
    finally:
        db.close()
    _rescore_controls(touched_controls)
    return JSONResponse({"success": True})


@router.delete("/api/items/{eid}")
@require_auth
async def api_evidence_delete(request: Request, eid: int):
    """Archive evidence: set status to archived and cascade-unlink from all modules."""
    if not has_capability(request.state.user, "evidence.delete"):
        return JSONResponse({"error": "Permission denied"}, 403)
    user = request.state.user
    db = get_db()
    try:
        if not _scoped_evidence_item(db, eid, user):
            raise HTTPException(404, "Evidence not found")
        touched_controls = _canonical_controls_linked_to(db, [eid])
        db.execute(
            "UPDATE evidence_items SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (eid,),
        )
        db.execute(
            "UPDATE evidence_links SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s "
            "WHERE evidence_id = %s AND deleted_at IS NULL",
            (_uid(request), eid),
        )
        db.commit()
    finally:
        db.close()
    _rescore_controls(touched_controls)
    from core.middleware import log_audit
    log_audit(user, "evidence", "Archived evidence and removed all links", "evidence", eid)
    return JSONResponse({"success": True})


@router.post("/api/items/{eid}/restore")
@require_auth
async def api_evidence_restore(request: Request, eid: int):
    """Restore archived evidence back to current status."""
    if not has_capability(request.state.user, "evidence.delete"):
        return JSONResponse({"error": "Permission denied"}, 403)
    db = get_db()
    try:
        if not _scoped_evidence_item(db, eid, request.state.user):
            raise HTTPException(404, "Evidence not found")
        db.execute(
            "UPDATE evidence_items SET status = 'current', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (eid,),
        )
        db.commit()
    finally:
        db.close()
    from core.middleware import log_audit
    log_audit(request.state.user, "evidence", "Restored evidence from archive", "evidence", eid)
    return JSONResponse({"success": True})


@router.delete("/api/items/{eid}/permanent")
@require_auth
async def api_evidence_permanent_delete(request: Request, eid: int):
    """Permanently delete an archived evidence item and its file."""
    if not has_capability(request.state.user, "evidence.delete"):
        return JSONResponse({"error": "Permission denied"}, 403)
    db = get_db()
    try:
        item = _scoped_evidence_item(db, eid, request.state.user)
        if not item:
            return JSONResponse({"error": "Not found"}, 404)
        if item["status"] != "archived":
            return JSONResponse({"error": "Only archived items can be permanently deleted"}, 400)
        touched_controls = _canonical_controls_linked_to(db, [eid])
        db.execute("DELETE FROM evidence_links WHERE evidence_id = %s", (eid,))
        db.execute("UPDATE evidence_items SET parent_id = NULL WHERE parent_id = %s", (eid,))
        db.execute("DELETE FROM evidence_items WHERE id = %s", (eid,))
        db.commit()
    finally:
        db.close()
    _rescore_controls(touched_controls)
    if item["file_path"]:
        try:
            fp = (EVIDENCE_DIR / item["file_path"]).resolve()
            if str(fp).startswith(str(EVIDENCE_DIR.resolve())) and fp.exists():
                fp.unlink()
        except Exception:
            pass
    from core.middleware import log_audit
    log_audit(request.state.user, "evidence", "Permanently deleted evidence", "evidence", eid)
    return JSONResponse({"success": True})


@router.get("/api/items/{eid}/download")
@require_auth
async def api_evidence_download(request: Request, eid: int):
    """Download evidence file.

    Checks the evidence directory first. If not found, falls back to the
    source module's directory for ARIA-linked evidence (so existing records
    created before file-copy was implemented still work).
    """
    db = get_db()
    try:
        item = _scoped_evidence_item(db, eid, request.state.user)
        if not item:
            raise HTTPException(404, "Evidence not found")

        fp_rel = item["file_path"] or ""
        fname = item["file_name"] or "download"
        mime = item["mime_type"] or "application/octet-stream"

        # PLAN-35 T09 (section 10.3): a managed-policy evidence item stores
        # this virtual pointer, never a real path, so download always
        # re-authorizes through ARIA's own version-scoped endpoint instead
        # of resolving a path here. This also fixes the "current-document
        # fallback" gap below for a managed document: that block reads
        # aria_documents.file_path/branded_file_path, which decide_approval
        # never sets (content lives on the immutable version row instead),
        # so without this branch a version-keyed item 404's rather than
        # ever risking a wrong/stale version being served.
        if fp_rel.startswith("aria://policy-versions/"):
            version_id = fp_rel.rsplit("/", 1)[-1]
            return RedirectResponse(url=f"/aria/api/policy-versions/{version_id}/download", status_code=302)

        # Primary: look in the evidence directory
        if fp_rel:
            candidate = (EVIDENCE_DIR / fp_rel).resolve()
            if (str(candidate).startswith(str(EVIDENCE_DIR.resolve()))
                    and candidate.exists()):
                return FileResponse(str(candidate), filename=fname, media_type=mime)

        # Fallback: for ARIA-linked evidence, try the ARIA uploads directory
        aria_dir = Path(os.getenv("ARIA_UPLOAD_DIR", "data/aria_uploads"))
        link = db.execute(
            "SELECT entity_id FROM evidence_links "
            "WHERE evidence_id=%s AND module='aria' AND entity_type='document' "
            "AND deleted_at IS NULL LIMIT 1",
            (eid,),
        ).fetchone()
        if link:
            aria_doc = db.execute(
                "SELECT branded_file_path, file_path, file_name "
                "FROM aria_documents WHERE id=%s",
                (link["entity_id"],),
            ).fetchone()
            if aria_doc:
                src_rel = aria_doc["branded_file_path"] or aria_doc["file_path"]
                if src_rel:
                    src_abs = (aria_dir / src_rel).resolve()
                    if (str(src_abs).startswith(str(aria_dir.resolve()))
                            and src_abs.exists()):
                        dl_name = aria_doc["file_name"] or fname
                        dl_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        return FileResponse(str(src_abs), filename=dl_name, media_type=dl_mime)
    finally:
        db.close()

    raise HTTPException(404, "File not found on disk")


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
        item = _scoped_evidence_item(db, eid, request.state.user)
        if not item:
            raise HTTPException(404, "Evidence not found")

        # PLAN-35 T09: a managed-policy evidence item's preview is a PDF
        # already built at approval time -- redirect to ARIA's own
        # version-scoped preview rather than on-demand LibreOffice
        # conversion of a path this row doesn't actually have.
        fp_rel = item["file_path"] or ""
        if fp_rel.startswith("aria://policy-versions/"):
            version_id = fp_rel.rsplit("/", 1)[-1]
            return RedirectResponse(url=f"/aria/api/policy-versions/{version_id}/preview", status_code=302)

        # Resolve the actual file (same fallback logic as download)
        file_path = None
        if fp_rel:
            candidate = (EVIDENCE_DIR / fp_rel).resolve()
            if str(candidate).startswith(str(EVIDENCE_DIR.resolve())) and candidate.exists():
                file_path = candidate

        if not file_path:
            aria_dir = Path(os.getenv("ARIA_UPLOAD_DIR", "data/aria_uploads"))
            link = db.execute(
                "SELECT entity_id FROM evidence_links "
                "WHERE evidence_id=%s AND module='aria' AND entity_type='document' "
                "AND deleted_at IS NULL LIMIT 1",
                (eid,),
            ).fetchone()
            if link:
                aria_doc = db.execute(
                    "SELECT branded_file_path, file_path, file_name "
                    "FROM aria_documents WHERE id=%s",
                    (link["entity_id"],),
                ).fetchone()
                if aria_doc:
                    src_rel = aria_doc["branded_file_path"] or aria_doc["file_path"]
                    if src_rel:
                        src_abs = (aria_dir / src_rel).resolve()
                        if str(src_abs).startswith(str(aria_dir.resolve())) and src_abs.exists():
                            file_path = src_abs
                            if not item["file_name"]:
                                item = dict(item)
                                item["file_name"] = aria_doc["file_name"] or "document.docx"
                                item["mime_type"] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    finally:
        db.close()

    if not file_path:
        raise HTTPException(404, "File not found on disk")

    mime = (item["mime_type"] or "").lower()
    fname = item["file_name"] or "document"

    # Detect actual file type from extension when MIME is missing or invalid
    ext = file_path.suffix.lower()
    ext_to_mime = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint",
        ".pdf": "application/pdf",
    }
    if ext in ext_to_mime:
        mime = ext_to_mime[ext]

    if mime == "application/pdf":
        return FileResponse(str(file_path), filename=fname, media_type="application/pdf")

    convertible_mimes = set(ext_to_mime.values()) - {"application/pdf"}
    if mime not in convertible_mimes:
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
        if not _scoped_evidence_item(db, eid, request.state.user):
            raise HTTPException(404, "Evidence not found")
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
        item = _scoped_evidence_item(db, eid, request.state.user)
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


# ── Confidence Score ───────────────────────────────────────────────────────

_VALID_VERIFICATION_METHODS = {
    "self_asserted", "peer_reviewed", "auditor_signed", "digitally_signed",
}

_VERIFICATION_WEIGHTS = {
    "self_asserted": 10,
    "peer_reviewed": 25,
    "auditor_signed": 40,
    "digitally_signed": 50,
}


def compute_confidence(verification_method, expiry_date, link_count, file_hash):
    """Pure function: compute a 0-100 confidence score for an evidence item."""
    score = 0
    score += _VERIFICATION_WEIGHTS.get(verification_method or "", 0)

    if expiry_date:
        from datetime import datetime, timedelta
        try:
            exp = datetime.fromisoformat(expiry_date.replace("Z", "+00:00"))
            now = datetime.utcnow()
            days_left = (exp - now).days
            if days_left > 90:
                score += 25
            elif days_left > 30:
                score += 15
            elif days_left > 0:
                score += 5
        except (ValueError, TypeError):
            pass
    else:
        score += 15

    if link_count and link_count >= 3:
        score += 15
    elif link_count and link_count >= 1:
        score += 10

    if file_hash:
        score += 10

    return min(score, 100)


def recompute_confidence(db, eid):
    """Recompute and persist the confidence score for one evidence item."""
    row = db.execute(
        "SELECT verification_method, expiry_date, file_hash FROM evidence_items WHERE id = %s",
        (eid,),
    ).fetchone()
    if not row:
        return
    link_count = db.execute(
        "SELECT COUNT(*) FROM evidence_links WHERE evidence_id = %s AND deleted_at IS NULL",
        (eid,),
    ).fetchone()[0]
    score = compute_confidence(
        row["verification_method"], row["expiry_date"], link_count, row["file_hash"],
    )
    db.execute(
        "UPDATE evidence_items SET confidence_score = %s WHERE id = %s",
        (score, eid),
    )


@router.post("/api/items/{eid}/confidence-verify")
@require_auth
async def api_evidence_set_verification(request: Request, eid: int):
    """Set verification method on an evidence item, recompute confidence."""
    data = await _json_body(request)
    method = data.get("verification_method", "")
    if method not in _VALID_VERIFICATION_METHODS:
        return JSONResponse({"error": "Invalid verification method"}, status_code=400)

    uid = _uid(request)
    db = get_db()
    try:
        if not _scoped_evidence_item(db, eid, request.state.user):
            raise HTTPException(404, "Evidence not found")
        db.execute(
            "UPDATE evidence_items SET verification_method = %s, verified_by = %s, "
            "verified_at = CURRENT_TIMESTAMP WHERE id = %s",
            (method, uid, eid),
        )
        recompute_confidence(db, eid)
        db.commit()
    finally:
        db.close()
    return JSONResponse({"success": True, "verification_method": method})


@router.delete("/api/items/{eid}/confidence-verify")
@require_auth
async def api_evidence_remove_verification(request: Request, eid: int):
    """Remove verification from an evidence item, recompute confidence."""
    db = get_db()
    try:
        if not _scoped_evidence_item(db, eid, request.state.user):
            raise HTTPException(404, "Evidence not found")
        db.execute(
            "UPDATE evidence_items SET verification_method = NULL, verified_by = NULL, "
            "verified_at = NULL WHERE id = %s",
            (eid,),
        )
        recompute_confidence(db, eid)
        db.commit()
    finally:
        db.close()
    return JSONResponse({"success": True})


# ── Linking API ─────────────────────────────────────────────────────────────

@router.post("/api/items/{eid}/links", status_code=201)
@require_auth
async def api_evidence_link_create(request: Request, eid: int):
    """Link evidence to a module entity (control, audit, risk, etc.).

    If the entity is a grid_control that has IMS-equivalent mappings, the
    evidence is automatically inherited by all mapped controls so a single
    upload satisfies multiple frameworks.
    """
    data = await _json_body(request)
    module      = data.get("module", "")
    entity_type = data.get("entity_type", "")
    entity_id   = data.get("entity_id")
    user_id     = _uid(request)
    try:
        entity_id = int(entity_id)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid link target")

    db = get_db()
    try:
        if not _scoped_evidence_item(db, eid, request.state.user):
            raise HTTPException(404, "Evidence not found")
        if not _visible_target(db, (module, entity_type), entity_id, request.state.user):
            raise HTTPException(404, "Link target not found")
        lid = insert_returning_id(
            db,
            "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s,%s,%s,%s,%s)",
            (eid, module, entity_type, entity_id, user_id)
        )
        db.commit()

        # ── IMS evidence inheritance ──────────────────────────────────────
        # When evidence is linked to a grid_control that is part of an IMS audit,
        # auto-create evidence_links for all ims_equivalent mapped controls.
        if module == "grid" and entity_type == "control" and entity_id:
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
                if not exists and _visible_target(db, (module, entity_type), mapped_id, request.state.user):
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
                if not exists and _visible_target(db, ("aria", "control"), mr[0], request.state.user):
                    db.execute(
                        "INSERT INTO evidence_links "
                        "(evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (eid, "aria", "control", mr[0], user_id)
                    )
            db.commit()
        recompute_confidence(db, eid)
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
        link_row = db.execute(
            "SELECT evidence_id, entity_type, entity_id FROM evidence_links WHERE id = %s", (lid,)
        ).fetchone()
        if not link_row or not _scoped_evidence_item(db, link_row["evidence_id"], request.state.user):
            raise HTTPException(404, "Link not found")
        db.execute(
            "UPDATE evidence_links SET deleted_at = CURRENT_TIMESTAMP, deleted_by = %s WHERE id = %s",
            (_uid(request), lid),
        )
        db.commit()
        recompute_confidence(db, link_row["evidence_id"])
        db.commit()
    finally:
        db.close()
    if link_row["entity_type"] == "canonical_control":
        _rescore_controls([link_row["entity_id"]])
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
        item = _scoped_evidence_item(db, eid, request.state.user)
        if not item:
            raise HTTPException(404, "Evidence not found")
        existing = [dict(r) for r in db.execute(
            "SELECT module, entity_type, entity_id FROM evidence_links WHERE evidence_id = %s AND deleted_at IS NULL", (eid,)
        ).fetchall()]
        def candidates(key, columns, extra_join="", extra_where="", limit=50):
            if key[0] not in user_modules(request.state.user):
                return []
            joins, where, params = _target_scope_sql(key, request.state.user)
            if extra_where:
                where.append(extra_where)
            table = _ENTITY_RESOLVERS[key][0]
            sql = f"SELECT {columns} FROM {table} t{joins}{extra_join}"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += f" LIMIT {limit}"
            return [dict(row) for row in db.execute(sql, params).fetchall()]

        controls = candidates(
            ("aria", "control"),
            "t.id, t.ref AS reference_code, t.name AS title, f.name AS framework_name",
            " JOIN frameworks f ON f.id = t.framework_id", limit=100,
        )
        audits = candidates(
            ("grid", "audit"),
            "t.id, t.name, f.name AS framework_name",
            " LEFT JOIN grid_frameworks f ON f.id = t.framework_id",
            "t.status != 'closed'", limit=30,
        )
        risks = candidates(
            ("erm", "risk"), "t.id, t.title AS name, t.category", limit=50,
        )
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
        "module and entity_type must be one of aria/control, grid/audit, erm/risk; "
        "entity_id (int), "
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
    allowed = {("aria", "control"), ("grid", "audit"), ("erm", "risk")}
    existing_keys = {(r["module"], r["entity_type"], r["entity_id"]) for r in existing}
    safe = []
    seen = set()
    db = get_db()
    try:
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue
            key = (suggestion.get("module"), suggestion.get("entity_type"))
            if key not in allowed:
                continue
            try:
                target_id = int(suggestion.get("entity_id"))
            except (TypeError, ValueError):
                continue
            identity = (*key, target_id)
            if identity in existing_keys or identity in seen:
                continue
            target = _visible_target(db, key, target_id, request.state.user)
            if not target:
                continue
            safe.append({
                "module": key[0], "entity_type": key[1], "entity_id": target_id,
                "entity_name": target[_ENTITY_RESOLVERS[key][1]],
                "reason": str(suggestion.get("reason") or "")[:240],
            })
            seen.add(identity)
            if len(safe) == 5:
                break
    finally:
        db.close()
    return JSONResponse({"suggestions": safe})


@router.get("/api/items/{eid}/audit")
@require_auth
async def api_evidence_audit(request: Request, eid: int):
    """Full link history for an evidence item — active and soft-deleted."""
    db = get_db()
    try:
        if not _scoped_evidence_item(db, eid, request.state.user):
            raise HTTPException(404, "Evidence not found")
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
    try:
        entity_id = int(entity_id)
    except ValueError:
        return JSONResponse({"error": "entity_id must be an integer"}, status_code=400)
    scope_sql, scope_params = evidence_scope_sql(request.state.user)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT e.*, el.id as link_id FROM evidence_items e "
            "JOIN evidence_links el ON e.id = el.evidence_id "
            "WHERE el.module = %s AND el.entity_type = %s AND el.entity_id = %s "
            f"AND el.deleted_at IS NULL AND e.status != 'archived' AND {scope_sql} "
            "ORDER BY e.updated_at DESC, e.id DESC",
            [module, entity_type, entity_id, *scope_params],
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

    scope_sql, scope_params = evidence_scope_sql(request.state.user)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT e.id, e.title, e.description, e.category, e.tags, "
            "e.status, e.created_at, e.updated_at, el.id as link_id "
            "FROM evidence_items e "
            "JOIN evidence_links el ON e.id = el.evidence_id "
            "WHERE el.module = %s AND el.entity_type = %s AND el.entity_id = %s "
            f"AND el.deleted_at IS NULL AND e.tags LIKE '%%auto%%' AND e.status != 'archived' AND {scope_sql} "
            "ORDER BY e.created_at DESC, e.id DESC",
            [mod, etype, entity_id, *scope_params],
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
    ("aria", "control"):    ("controls", "name", "/aria/frameworks"),
    ("aria", "document"):   ("aria_documents", "title", "/aria/documents?open={doc_id}"),
    ("aria", "risk"):       ("aria_risks", "description", "/aria/risks"),
    ("aria", "framework"):  ("frameworks", "name", "/aria/frameworks"),
    ("grid", "audit"):      ("grid_audits", "name", "/grid/audits/{id}"),
    ("grid", "control"):    ("grid_controls", "name", "/grid/controls"),
    ("grid", "nc"):         ("grid_non_conformances", "title", "/grid/?open=nc:{id}"),
    ("grid", "non_conformance"): ("grid_non_conformances", "title", "/grid/?open=nc:{id}"),
    ("bcm", "plan"):        ("bcm_plans", "title", "/bcm/plans"),
    ("bcm", "incident"):    ("bcm_incidents", "title", "/bcm/?open=incident:{id}"),
    ("bcm", "risk"):        ("bcm_risks", "title", "/bcm/risks"),
    ("bcm", "bia"):         ("bcm_bia_records", "process_name", "/bcm/bia"),
    ("bcm", "compliance_control"): ("bcm_compliance_controls", "title", "/bcm/compliance"),
    ("sentinel", "ropa"):   ("sentinel_ropa", "processing_name", "/sentinel/?open=ropa:{id}"),
    ("sentinel", "dpia"):   ("sentinel_dpias", "title", "/sentinel/?open=dpia:{id}"),
    ("sentinel", "breach"): ("sentinel_breaches", "title", "/sentinel/?open=breach:{id}"),
    ("sentinel", "dsr"):    ("sentinel_dsr", "requester_name", "/sentinel/?open=dsr:{id}"),
    ("sentinel", "vendor"): ("sentinel_vendors", "name", "/sentinel/vendors"),
    ("erm", "risk"):        ("erm_enterprise_risks", "title", "/erm/register?open=risk:{id}"),
}


_TARGET_BU_COLUMNS = {
    ("aria", "document"): "t.business_unit_id",
    ("grid", "audit"): "t.business_unit_id",
    ("grid", "control"): "a.business_unit_id",
    ("grid", "nc"): "a.business_unit_id",
    ("grid", "non_conformance"): "a.business_unit_id",
    ("bcm", "plan"): "t.business_unit_id",
    ("bcm", "incident"): "t.business_unit_id",
    ("bcm", "bia"): "t.business_unit_id",
    ("sentinel", "ropa"): "t.business_unit_id",
    ("sentinel", "dpia"): "t.business_unit_id",
    ("sentinel", "breach"): "t.business_unit_id",
    ("sentinel", "dsr"): "t.business_unit_id",
    ("erm", "risk"): "t.business_unit_id",
}


def _target_scope_sql(key, user):
    joins = " JOIN grid_audits a ON a.id = t.audit_id" if key in {
        ("grid", "control"), ("grid", "nc"), ("grid", "non_conformance")
    } else ""
    where, params = [], []
    if not user.get("is_super_admin"):
        if key[0] not in user_modules(user):
            where.append("1 = 0")
        if key == ("aria", "document"):
            if not user.get("org_id"):
                where.append("1 = 0")
            else:
                where.append("t.org_id = %s")
                params.append(user["org_id"])
        bu_col = _TARGET_BU_COLUMNS.get(key)
        scope = bu_scope_ids(user)
        if bu_col and scope is not None:
            if scope:
                where.append(f"({bu_col} IS NULL OR {bu_col} IN ({','.join('%s' for _ in scope)}))")
                params.extend(scope)
            else:
                where.append(f"{bu_col} IS NULL")
    return joins, where, params


def _visible_target(db, key, entity_id, user):
    resolver = _ENTITY_RESOLVERS.get(key)
    if not resolver or entity_id <= 0:
        return None
    joins, where, params = _target_scope_sql(key, user)
    sql = f"SELECT t.* FROM {resolver[0]} t{joins} WHERE t.id = %s"
    if where:
        sql += " AND " + " AND ".join(where)
    return db.execute(sql, (entity_id, *params)).fetchone()


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

    try:
        evidence_id = int(request.query_params.get("evidence_id", "0"))
    except (TypeError, ValueError):
        evidence_id = 0
    results = []
    db = get_db()
    try:
        if not evidence_id or not _scoped_evidence_item(db, evidence_id, request.state.user):
            return JSONResponse({"error": "Evidence item not found"}, status_code=404)
        for spec in link_specs:
            if not isinstance(spec, dict):
                return JSONResponse({"error": "Invalid link specification"}, status_code=400)
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
                linked = db.execute(
                    "SELECT 1 FROM evidence_links WHERE evidence_id = %s AND module = %s "
                    "AND entity_type = %s AND entity_id = %s AND deleted_at IS NULL",
                    (evidence_id, module, entity_type, entity_id),
                ).fetchone()
                if not linked:
                    results.append(entry)
                    continue
                _, name_col, url_tpl = resolver
                row = _visible_target(db, (module, entity_type), entity_id, request.state.user)
                if row:
                    from urllib.parse import quote
                    entry["name"] = row[name_col]
                    entry["url"] = url_tpl.replace("{id}", str(entity_id)).replace(
                        "{doc_id}", quote(row["doc_id"], safe="") if (module, entity_type) == ("aria", "document") else ""
                    )

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

    valid_modules = frozenset({"aria", "grid", "bcm", "sentinel", "erm"})
    if module not in valid_modules:
        return JSONResponse({"error": "Invalid module"}, 400)

    # Map (module, entity_type) → (table, name_col, id_col)
    entity_map = {
        ("aria", "control"): ("controls", "name", "id"),
        ("aria", "document"): ("aria_documents", "title", "id"),
        ("aria", "risk"): ("aria_risks", "description", "id"),
        ("aria", "framework"): ("frameworks", "name", "id"),
        ("grid", "audit"): ("grid_audits", "name", "id"),
        ("grid", "control"): ("grid_controls", "name", "id"),
        ("grid", "nc"): ("grid_non_conformances", "title", "id"),
        ("grid", "non_conformance"): ("grid_non_conformances", "title", "id"),
        ("bcm", "plan"): ("bcm_plans", "title", "id"),
        ("bcm", "incident"): ("bcm_incidents", "title", "id"),
        ("bcm", "risk"): ("bcm_risks", "title", "id"),
        ("bcm", "bia"): ("bcm_bia_records", "process_name", "id"),
        ("bcm", "compliance_control"): ("bcm_compliance_controls", "title", "id"),
        ("sentinel", "ropa"): ("sentinel_ropa", "processing_name", "id"),
        ("sentinel", "dpia"): ("sentinel_dpias", "title", "id"),
        ("sentinel", "breach"): ("sentinel_breaches", "title", "id"),
        ("sentinel", "dsr"): ("sentinel_dsr", "requester_name", "id"),
        ("sentinel", "vendor"): ("sentinel_vendors", "name", "id"),
        ("erm", "risk"): ("erm_enterprise_risks", "title", "id"),
    }

    key = (module, entity_type)
    if key not in entity_map:
        return JSONResponse({"error": "Unknown entity type"}, 400)

    table, name_col, id_col = entity_map[key]
    db = get_db()
    try:
        joins, where, params = _target_scope_sql(key, request.state.user)
        if q:
            where.append(f"LOWER(t.{name_col}) LIKE LOWER(%s)")
            params.append(f"%{q}%")
        sql = f"SELECT t.{id_col} AS id, t.{name_col} AS name FROM {table} t{joins}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY t.{name_col} LIMIT 50"
        rows = db.execute(sql, params).fetchall()
    except Exception:
        swallowed("api_search_entities")
        return JSONResponse({"error": "Entity search unavailable"}, status_code=503)
    finally:
        db.close()
    return JSONResponse([dict(r) for r in rows])


@router.get("/api/coverage")
@require_auth
async def api_evidence_coverage(request: Request):
    """Count linkable records and active evidence within the caller's scope."""
    user = request.state.user
    allowed_modules = set(user_modules(user))
    checks = [
        ("aria", "control", ("control",)),
        ("aria", "document", ("document",)),
        ("aria", "risk", ("risk",)),
        ("aria", "framework", ("framework",)),
        ("grid", "audit", ("audit",)),
        ("grid", "control", ("control",)),
        ("grid", "non_conformance", ("non_conformance", "nc")),
        ("bcm", "plan", ("plan",)),
        ("bcm", "incident", ("incident",)),
        ("bcm", "risk", ("risk",)),
        ("bcm", "bia", ("bia",)),
        ("bcm", "compliance_control", ("compliance_control",)),
        ("sentinel", "dpia", ("dpia",)),
        ("sentinel", "breach", ("breach",)),
        ("sentinel", "ropa", ("ropa",)),
        ("sentinel", "dsr", ("dsr",)),
        ("sentinel", "vendor", ("vendor",)),
        ("erm", "risk", ("risk",)),
    ]
    coverage = {}
    scope_sql, scope_params = evidence_scope_sql(user)
    db = get_db()
    try:
        for module, entity_type, link_types in checks:
            if module not in allowed_modules:
                continue
            key = (module, entity_type)
            table = _ENTITY_RESOLVERS[key][0]
            joins, target_where, target_params = _target_scope_sql(key, user)
            base = f" FROM {table} t{joins}"
            total_sql = "SELECT COUNT(DISTINCT t.id)" + base
            if target_where:
                total_sql += " WHERE " + " AND ".join(target_where)
            total = db.execute(total_sql, target_params).fetchone()[0]

            marks = ",".join("%s" for _ in link_types)
            linked_sql = (
                "SELECT COUNT(DISTINCT t.id)" + base
                + " JOIN evidence_links el ON el.entity_id = t.id"
                + " JOIN evidence_items e ON e.id = el.evidence_id"
                + f" WHERE el.module = %s AND el.entity_type IN ({marks})"
                + " AND el.deleted_at IS NULL AND e.status != 'archived'"
            )
            linked_params = [module, *link_types]
            if target_where:
                linked_sql += " AND " + " AND ".join(target_where)
                linked_params.extend(target_params)
            linked_sql += f" AND {scope_sql}"
            linked_params.extend(scope_params)
            with_evidence = db.execute(linked_sql, linked_params).fetchone()[0]
            data = coverage.setdefault(module, {"total": 0, "with_evidence": 0, "entities": []})
            data["total"] += total
            data["with_evidence"] += with_evidence
            data["entities"].append({
                "type": entity_type,
                "total": total,
                "with_evidence": with_evidence,
                "pct": round(with_evidence / total * 100) if total else 0,
            })
        for data in coverage.values():
            data["pct"] = round(data["with_evidence"] / data["total"] * 100) if data["total"] else 0
    finally:
        db.close()
    return JSONResponse(coverage)


@router.get("/api/stats")
@require_auth
async def api_evidence_stats(request: Request):
    """Evidence repository statistics with per-module breakdown."""
    scope_sql, scope_params = evidence_scope_sql(request.state.user)
    library = current_library_sql()
    live_link = "el.deleted_at IS NULL"

    db = get_db()
    try:
        total = db.execute(
            f"SELECT COUNT(*) FROM evidence_items e WHERE {library} AND {scope_sql}", scope_params,
        ).fetchone()[0]
        by_category = db.execute(
            f"SELECT e.category, COUNT(*) as c FROM evidence_items e WHERE {library} AND {scope_sql} "
            "GROUP BY e.category",
            scope_params,
        ).fetchall()
        expiring_soon = db.execute(
            "SELECT COUNT(*) FROM evidence_items e WHERE e.status = 'current' "
            f"AND e.expiry_date IS NOT NULL AND e.expiry_date <= {sql_date_offset('+30 days')} "
            f"AND e.expiry_date > {sql_current_date()} AND {scope_sql}",
            scope_params,
        ).fetchone()[0]
        total_links = db.execute(
            "SELECT COUNT(*) FROM evidence_links el JOIN evidence_items e ON el.evidence_id = e.id "
            f"WHERE {live_link} AND {library} AND {scope_sql}",
            scope_params,
        ).fetchone()[0]
        unlinked = db.execute(
            f"SELECT COUNT(*) FROM evidence_items e WHERE {library} AND {scope_sql} "
            f"AND NOT EXISTS (SELECT 1 FROM evidence_links el WHERE el.evidence_id = e.id AND {live_link})",
            scope_params,
        ).fetchone()[0]
        by_module = db.execute(
            "SELECT el.module, COUNT(DISTINCT el.evidence_id) as c "
            "FROM evidence_links el JOIN evidence_items e ON el.evidence_id = e.id "
            f"WHERE {library} AND {live_link} AND {scope_sql} GROUP BY el.module",
            scope_params,
        ).fetchall()
        expiring_7 = db.execute(
            "SELECT COUNT(*) FROM evidence_items e WHERE e.status = 'current' "
            f"AND e.expiry_date IS NOT NULL AND e.expiry_date <= {sql_date_offset('+7 days')} "
            f"AND e.expiry_date > {sql_current_date()} AND {scope_sql}",
            scope_params,
        ).fetchone()[0]
        recent_rows = db.execute(
            "SELECT e.id, e.title, e.category, e.file_name, e.created_at "
            f"FROM evidence_items e WHERE {library} AND {scope_sql} "
            "ORDER BY e.created_at DESC, e.id DESC LIMIT 5",
            scope_params,
        ).fetchall()
        archived_count = db.execute(
            f"SELECT COUNT(*) FROM evidence_items e WHERE e.status = 'archived' AND {scope_sql}", scope_params,
        ).fetchone()[0]
    finally:
        db.close()
    result = {
        "total": total,
        "by_category": {r["category"]: r["c"] for r in by_category},
        "by_module": {r["module"]: r["c"] for r in by_module},
        "expiring_soon": expiring_soon,
        "expiring_7_days": expiring_7,
        "total_links": total_links,
        "unlinked": unlinked,
        "recently_added": [dict(r) for r in recent_rows],
        "archived": archived_count,
    }
    result["can_delete"] = has_capability(request.state.user, "evidence.delete")
    return JSONResponse(result)
