"""
Evidence Repository — Cross-module evidence vault.

Upload, tag, search, and link evidence to controls/audits/frameworks
across ARIA, GRID, BCM, and Sentinel modules.
"""
import logging
import os
import uuid
import hashlib
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool
from starlette.background import BackgroundTask
from fastapi.templating import Jinja2Templates

from core.best_effort import swallowed
from core.middleware import require_auth, require_capability
from core.rbac import has_capability, user_modules
from core.shell_context import shell_ctx
from core.sql_like import ci_like, like_pattern
from database import get_db, insert_returning_id, sql_date_offset, sql_date_ts, sql_current_date
from modules.evidence import company_views, find as finder, group_adoption, group_documents, group_requests, inspector, ownership, proof, vault_views
from modules.evidence.indexer import indexing_enabled, snippets_for_page
from modules.evidence.scope import current_library_sql, evidence_scope_sql, evidence_search_sql
from modules.governance.entity_scope import _KINDS, canonical_key, describe_record, describe_records, entity_scope_sql, record_unit

router = APIRouter(prefix="/evidence", tags=["evidence"])
log = logging.getLogger("oneforall.evidence")
_PDF_CONVERSION_SLOTS = threading.BoundedSemaphore(2)
_PDF_INPUT_LIMIT = 50 * 1024 * 1024
_PDF_OUTPUT_LIMIT = 75 * 1024 * 1024


def _convert_office_preview(file_path: Path) -> tuple[Path, str]:
    """Convert in a bounded worker, returning a temporary PDF and its directory."""
    if file_path.stat().st_size > _PDF_INPUT_LIMIT:
        raise HTTPException(413, "This document is too large for PDF conversion.")
    if not _PDF_CONVERSION_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "PDF conversion is busy. Please try again shortly.")
    tmpdir = None
    success = False
    try:
        tmpdir = tempfile.mkdtemp(prefix="themisiq-preview-")
        profile = (Path(tmpdir) / "profile").as_uri()
        try:
            result = subprocess.run(
                ["libreoffice", f"-env:UserInstallation={profile}",
                 "--headless", "--convert-to", "pdf", "--outdir", tmpdir,
                 str(file_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
            )
        except FileNotFoundError:
            raise HTTPException(503, "PDF conversion is unavailable on this server.") from None
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "PDF conversion timed out.") from None
        if result.returncode != 0:
            raise HTTPException(500, "PDF conversion failed.")
        pdf_path = Path(tmpdir) / (file_path.stem + ".pdf")
        if not pdf_path.exists():
            candidates = list(Path(tmpdir).glob("*.pdf"))
            if not candidates:
                raise HTTPException(500, "PDF conversion produced no output.")
            pdf_path = candidates[0]
        if pdf_path.stat().st_size > _PDF_OUTPUT_LIMIT:
            raise HTTPException(413, "The converted PDF is too large to download.")
        success = True
        return pdf_path, tmpdir
    finally:
        _PDF_CONVERSION_SLOTS.release()
        if tmpdir and not success:
            shutil.rmtree(tmpdir, ignore_errors=True)


@router.get("/api/legacy-files")
@require_auth
async def legacy_files(request: Request):
    """Migration inventory for a tenant administrator. No historical paths leave the server."""
    user = request.state.user
    if not user.get("org_id") or not has_capability(user, "platform.manage_users"):
        raise HTTPException(403, "Forbidden")
    from modules.evidence import legacy_migration as migration
    can_grid = has_capability(user, "module.grid.access")
    can_bcm = has_capability(user, "module.bcm.access")
    return JSONResponse({"grid_files": migration.grid_inventory(user) if can_grid else [],
                         "grid_versions": migration.grid_version_inventory(user) if can_grid else [],
                         "bcm_files": migration.bcm_inventory(user) if can_bcm else [],
                         "grid_access": can_grid, "bcm_access": can_bcm,
                         "grid_migrate": has_capability(user, "grid.evidence.upload"),
                         "bcm_reconcile": has_capability(user, "bcm.compliance.manage")})


@router.post("/api/legacy-files/grid/{source_id}/migrate")
@require_auth
async def migrate_legacy_grid(request: Request, source_id: int):
    user = request.state.user
    if not user.get("org_id") or not has_capability(user, "platform.manage_users"):
        raise HTTPException(403, "Forbidden")
    from modules.evidence import legacy_migration as migration
    try:
        vault_id = migration.migrate_grid_file(source_id, user)
    except LookupError:
        raise HTTPException(404, "File not found") from None
    except PermissionError:
        raise HTTPException(403, "Forbidden") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    from core.middleware import log_audit
    log_audit(user, "evidence", "Migrated historical GRID file", "grid_evidence_files", source_id,
              details=f"Vault item {vault_id}")
    return JSONResponse({"vault_evidence_id": vault_id})


@router.post("/api/legacy-files/grid-versions/{version_id}/migrate")
@require_auth
async def migrate_legacy_grid_version(request: Request, version_id: int):
    user = request.state.user
    if not user.get("org_id") or not has_capability(user, "platform.manage_users"):
        raise HTTPException(403, "Forbidden")
    from modules.evidence import legacy_migration as migration
    try:
        vault_id = migration.migrate_grid_version(version_id, user)
    except LookupError:
        raise HTTPException(404, "Version not found") from None
    except PermissionError:
        raise HTTPException(403, "Forbidden") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    from core.middleware import log_audit
    log_audit(user, "evidence", "Migrated historical GRID version", "grid_evidence_versions", version_id,
              details=f"Vault item {vault_id}")
    return JSONResponse({"vault_evidence_id": vault_id})


@router.post("/api/legacy-files/bcm/{source_id}/reconcile")
@require_auth
async def reconcile_legacy_bcm(request: Request, source_id: int):
    user = request.state.user
    if not user.get("org_id") or not has_capability(user, "platform.manage_users"):
        raise HTTPException(403, "Forbidden")
    body = await _json_body(request)
    vault_id = body.get("vault_evidence_id")
    if type(vault_id) is not int or vault_id < 1:
        raise HTTPException(400, "Choose a Vault artifact")
    from modules.evidence import legacy_migration as migration
    try:
        linked_id = migration.reconcile_bcm_file(source_id, vault_id, user)
    except LookupError:
        raise HTTPException(404, "BCM reference or artifact not found") from None
    except PermissionError:
        raise HTTPException(403, "Forbidden") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    from core.middleware import log_audit
    log_audit(user, "evidence", "Reconciled historical BCM reference", "bcm_compliance_evidence", source_id,
              details=f"Vault item {linked_id}")
    return JSONResponse({"vault_evidence_id": linked_id})

# PLAN-36 P06: registers this list's exact query-param names (matching
# GET /api/items below) as the allowlist a saved view may store for this
# module -- the only things saved_views.create_saved_view will ever accept
# into filter_json, which closes off "malicious filter JSON" by never
# letting it hold anything else.
from modules.saved_views.data_service import register_view_schema as _register_view_schema
_register_view_schema(
    "evidence", "items_list",
    allowed_params={"category", "status", "q", "module", "view", "folder", "filing_scope"},
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


_STATUSES = ("current", "superseded", "archived", "expired", "draft")
_DAY_LABELS = {"expiry_date": "expiry date", "review_due_date": "review date", "period_start": "start of the period",
               "period_end": "end of the period"}


def _clean_day(value, what):
    """(ISO day or None, problem). A blank value clears the date."""
    if value in (None, ""):
        return None, None
    from datetime import datetime
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").strftime("%Y-%m-%d"), None
    except ValueError:
        return None, f"Write the {what} as YYYY-MM-DD."


def _clean_owner(db, user: dict, value):
    """(user id or None, problem). The owner is an active person of the caller's own organization."""
    if value in (None, ""):
        return None, None
    try:
        owner_id = int(value)
    except (TypeError, ValueError):
        return None, "Choose the owner from the people in your organization."
    row = db.execute("SELECT org_id, is_active, deleted_at FROM users WHERE id = %s", (owner_id,)).fetchone()
    if not row or not row["is_active"] or row["deleted_at"]:
        return None, "Choose the owner from the people in your organization."
    if not user.get("is_super_admin") and row["org_id"] != user.get("org_id"):
        return None, "Choose the owner from the people in your organization."
    return owner_id, None


def _clean_field(db, user: dict, field: str, value):
    """(value, problem) for one editable field of an item."""
    if field in _DAY_LABELS:
        return _clean_day(value, _DAY_LABELS[field])
    if field == "status":
        if value not in _STATUSES:
            return None, "Choose one of: " + ", ".join(_STATUSES) + "."
        return value, None
    if field == "owner_user_id":
        return _clean_owner(db, user, value)
    return value, None


_LIVE_ACTIVE = ("EXISTS (SELECT 1 FROM evidence_links el WHERE el.evidence_id = e.id AND el.deleted_at IS NULL "
                "AND COALESCE(el.review_status, 'pending') != 'out_of_scope')")


def _not_expired() -> str:
    return f"(e.expiry_date IS NULL OR e.expiry_date > {sql_current_date()})"


_VIEWS = ("all", "needs_filing", "unlinked", "for_review", "review_due", "recent", "expiring", "archived", "superseded", "generated_history")


def _view_where(view: str, user: dict) -> tuple[list, list]:
    """(clauses, params) of one library view. The list, its tab counts and the stats all take their rows from here, so a
    number and the list it opens cannot disagree."""
    if view == "archived":
        return ["e.status = 'archived'"], []
    if view == "superseded":
        return ["e.status = 'superseded'"], []
    if view == "generated_history":
        return ["e.status = 'superseded' AND e.category = 'generated_record' AND e.id IN ("
                "SELECT d.evidence_id FROM generated_record_documents d WHERE "
                "(SELECT COUNT(*) FROM generated_record_documents newer WHERE "
                "newer.source_module=d.source_module AND newer.source_type=d.source_type "
                "AND newer.source_id=d.source_id AND newer.file_format=d.file_format "
                "AND newer.sequence>d.sequence) BETWEEN 1 AND 2)"], []
    if view == "expiring":
        return ["e.status = 'current' AND e.expiry_date IS NOT NULL "
                f"AND e.expiry_date <= {sql_date_offset('+30 days')} AND e.expiry_date > {sql_current_date()}"], []
    if view in ("unlinked", "needs_filing"):
        return [current_library_sql(), _not_expired(), f"NOT {_LIVE_ACTIVE}"], []
    if view == "for_review":
        if not has_capability(user, "evidence.link.review"):
            return ["(1 = 0)"], []
        return ["e.status = 'current'", _not_expired(), "(e.uploaded_by IS NULL OR e.uploaded_by != %s)",
                "EXISTS (SELECT 1 FROM evidence_links el WHERE el.evidence_id = e.id AND el.deleted_at IS NULL "
                "AND COALESCE(el.review_status, 'pending') = 'pending' AND (el.linked_by IS NULL OR el.linked_by != %s))"
                ], [user["id"], user["id"]]
    if view == "review_due":
        return [current_library_sql(), "e.review_due_date IS NOT NULL",
                f"e.review_due_date <= {sql_date_offset('+30 days')}"], []
    if view == "recent":
        # updated_at is a timestamp on PostgreSQL and text on SQLite: sql_date_ts gives the matching type for each
        return [current_library_sql(), f"e.updated_at >= {sql_date_ts('-14 days')}"], []
    return ["e.status != 'archived'", "e.status != 'superseded'"], []


_PENDING_LINK = ("EXISTS (SELECT 1 FROM evidence_links el WHERE el.evidence_id = e.id AND el.deleted_at IS NULL "
                 "AND COALESCE(el.review_status, 'pending') = 'pending')")
_RETURNED_LINK = ("EXISTS (SELECT 1 FROM evidence_links el WHERE el.evidence_id = e.id AND el.deleted_at IS NULL "
                  "AND COALESCE(el.review_status, 'pending') IN ('returned', 'rejected'))")


def _state_where(state: str) -> list:
    """Clauses for the one state a row shows (proof.item_state), so that filtering by a state returns exactly the rows that
    say it. The five states partition the current files: expired first, then needs filing, returned, awaiting review."""
    if state == "expired":
        return [f"(e.status = 'expired' OR (e.status = 'current' AND e.expiry_date IS NOT NULL "
                f"AND e.expiry_date <= {sql_current_date()}))"]
    base = ["e.status = 'current'", _not_expired()]
    if state == "needs_filing":
        return base + [f"NOT {_LIVE_ACTIVE}"]
    if state == "returned":
        return base + [_LIVE_ACTIVE, _RETURNED_LINK]
    if state == "awaiting_review":
        return base + [_LIVE_ACTIVE, f"NOT {_RETURNED_LINK}", _PENDING_LINK]
    if state == "accepted":
        return base + [_LIVE_ACTIVE, f"NOT {_RETURNED_LINK}", f"NOT {_PENDING_LINK}"]
    return []


def _claims_for(db, user: dict, evidence_ids: list) -> dict:
    """{evidence_id: {"claims": up to two {title, url, module, entity_type}, "more": n, "hidden": n}} for the records each
    item supports. A record the caller may not open is only counted, never named."""
    if not evidence_ids:
        return {}
    marks = ",".join(["%s"] * len(evidence_ids))
    rows = db.execute(
        f"SELECT evidence_id, module, entity_type, entity_id FROM evidence_links WHERE evidence_id IN ({marks}) "
        "AND deleted_at IS NULL ORDER BY id", list(evidence_ids)).fetchall()
    wanted = {}
    for r in rows:
        wanted.setdefault(canonical_key(r["module"], r["entity_type"]), set()).add(r["entity_id"])
    shown = {key: describe_records(db, key, sorted(ids), user) for key, ids in wanted.items()}
    out = {}
    for r in rows:
        entry = out.setdefault(r["evidence_id"], {"claims": [], "more": 0, "hidden": 0})
        found = shown[canonical_key(r["module"], r["entity_type"])].get(r["entity_id"])
        if found is None:
            entry["hidden"] += 1
        elif len(entry["claims"]) < 2:
            entry["claims"].append({"title": found["title"], "url": found["url"], "module": r["module"],
                                    "entity_type": r["entity_type"]})
        else:
            entry["more"] += 1
    return out


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
    ctx["can_manage_company"] = has_capability(request.state.user, "evidence.company.manage") or has_capability(request.state.user, "evidence.company.review")
    ctx["can_manage_legacy"] = bool(
        request.state.user.get("org_id") and
        has_capability(request.state.user, "platform.manage_users"))
    ctx["can_manage_group"] = bool(request.state.user.get("org_id") and any(
        has_capability(request.state.user, cap) for cap in (
            "group.relationship.manage", "group.relationship.ack", "group.terms.privacy",
            "group.terms.legal", "group.grant.manage", "group.rights.review",
            "group.document.publish")))
    ctx["can_group_requests"] = bool(request.state.user.get("org_id") and any(
        has_capability(request.state.user, cap) for cap in (
            "group.request.create", "group.request.manage", "group.request.review",
            "group.request.fulfill")))
    ctx["can_group_adoption"] = bool(request.state.user.get("org_id") and any(
        has_capability(request.state.user, cap) for cap in (
            "group.policy.propose", "group.policy.review")))
    return shell_templates.TemplateResponse(request, "evidence_index.html", ctx)


@router.get("/group/", response_class=HTMLResponse)
@require_auth
async def group_sharing_page(request: Request):
    db = get_db()
    try:
        group_documents.management_workspace(db, request.state.user)
    finally:
        db.close()
    ctx = shell_ctx(request, active_module="evidence", active_section="evidence")
    return shell_templates.TemplateResponse(request, "group_sharing.html", ctx)


@router.get("/group/requests/", response_class=HTMLResponse)
@require_auth
async def group_requests_page(request: Request):
    db = get_db()
    try:
        group_requests.list_requests(db, request.state.user)
    finally:
        db.close()
    ctx = shell_ctx(request, active_module="evidence", active_section="evidence")
    return shell_templates.TemplateResponse(request, "group_requests.html", ctx)


@router.get("/group/adoption/", response_class=HTMLResponse)
@require_auth
async def group_adoption_page(request: Request):
    db = get_db()
    try:
        group_adoption.list_policies(db, request.state.user)
    finally:
        db.close()
    ctx = shell_ctx(request, active_module="evidence", active_section="evidence")
    return shell_templates.TemplateResponse(request, "group_adoption.html", ctx)


@router.get("/batch/", response_class=HTMLResponse)
@require_auth
async def evidence_batch_page(request: Request):
    ctx = shell_ctx(request, active_module="evidence", active_section="evidence")
    return shell_templates.TemplateResponse(request, "evidence_batch.html", ctx)


@router.post("/api/batch/suggest")
@require_auth
async def api_evidence_batch_suggest(request: Request, file: UploadFile = File(...)):
    """Parse a selected file in the existing isolated worker; return hints only."""
    from tempfile import TemporaryDirectory
    from modules.aria.policy_intake import MAX_FILE, IntakeError, _extract_isolated
    from modules.aria.policy_storage import DocxValidationError, validate_docx

    if not request.state.user.get("org_id"):
        raise HTTPException(403, "Select an organization")
    name = Path(file.filename or "").name[:180]
    extension = Path(name).suffix.lower()
    if extension not in (".docx", ".pdf"):
        raise HTTPException(422, "Suggestions support DOCX and PDF files")
    content = await file.read(MAX_FILE + 1)
    if not content or len(content) > MAX_FILE:
        raise HTTPException(422, "Choose a nonempty document under 25 MB")
    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(422, "The PDF file signature is invalid")
    try:
        with TemporaryDirectory(prefix="themisiq-batch-extract-") as folder:
            source = Path(folder) / ("source" + extension)
            source.write_bytes(content)
            if extension == ".docx":
                validate_docx(source)
            extracted = _extract_isolated(source, extension, name)
    except (DocxValidationError, IntakeError) as exc:
        raise HTTPException(422, "Local extraction could not safely read this file") from exc
    metadata = extracted.get("metadata", {})
    allowed = ("title", "doc_type", "version", "owner", "approver", "effective_date", "review_date")
    suggestions = {field: metadata[field] for field in allowed if field in metadata}
    return JSONResponse({"suggestions": suggestions, "parser": extracted.get("parser"),
                         "text_status": extracted.get("text_status")})


@router.get("/api/batch/version-candidates")
@require_auth
async def api_evidence_batch_version_candidates(request: Request):
    """Small, scope-exact picker for a new immutable version; no cross-tenant totals."""
    user = request.state.user
    if not user.get("org_id"):
        raise HTTPException(403, "Select an organization")
    term = (request.query_params.get("q") or "").strip()
    filing_scope = (request.query_params.get("filing_scope") or "").strip()
    if len(term) < 2 or len(term) > 100:
        raise HTTPException(422, "Search using 2 to 100 characters")
    db = get_db()
    try:
        unit_id = company_views.selected_unit(db, user, filing_scope, for_filing=True)
        visible_sql, visible_params = evidence_scope_sql(user)
        unit_sql = "e.business_unit_id IS NULL" if unit_id is None else "e.business_unit_id = %s"
        rows = db.execute(
            "SELECT e.id,e.title,e.version,e.category,e.review_due_date,e.file_name "
            "FROM evidence_items e WHERE e.org_id=%s AND " + visible_sql +
            " AND " + unit_sql + " AND e.status='current' AND e.category != 'generated_record' "
            f"AND ({ci_like('e.title')} OR {ci_like('e.file_name')}) "
            "ORDER BY e.updated_at DESC,e.id DESC LIMIT 15",
            [user["org_id"], *visible_params, *([unit_id] if unit_id is not None else []),
             like_pattern(term), like_pattern(term)],
        ).fetchall()
        return JSONResponse({"items": [dict(row) for row in rows]})
    finally:
        db.close()


@router.post("/api/batch/duplicate-check")
@require_auth
async def api_evidence_batch_duplicate_check(
    request: Request, file: UploadFile = File(...), filing_scope: str = Form(""),
):
    """Advisory exact-byte check in one authorized filing scope; upload rechecks."""
    user = request.state.user
    if not user.get("org_id"):
        raise HTTPException(403, "Select an organization")
    db = get_db()
    try:
        unit_id = company_views.selected_unit(db, user, filing_scope.strip(), for_filing=True)
        content = await file.read(MAX_FILE_SIZE + 1)
        if not content or len(content) > MAX_FILE_SIZE:
            raise HTTPException(413, "Choose a nonempty file under 100 MB")
        digest = hashlib.sha256(content).hexdigest()
        visible_sql, visible_params = evidence_scope_sql({**user, "is_super_admin": False})
        unit_sql = "e.business_unit_id IS NULL" if unit_id is None else "e.business_unit_id = %s"
        rows = db.execute(
            "SELECT e.id,e.title,e.version,e.status FROM evidence_items e "
            "WHERE e.org_id=%s AND " + visible_sql + " AND " + unit_sql +
            " AND e.file_hash=%s AND e.status!='archived' "
            "ORDER BY CASE WHEN e.status='current' THEN 0 ELSE 1 END,e.id DESC LIMIT 5",
            [user["org_id"], *visible_params, *([unit_id] if unit_id is not None else []), digest],
        ).fetchall()
        return JSONResponse({"items": [dict(row) for row in rows]})
    finally:
        db.close()


@router.get("/companies/", response_class=HTMLResponse)
@require_auth
async def evidence_companies_page(request: Request):
    if not (has_capability(request.state.user, "evidence.company.manage") or
            has_capability(request.state.user, "evidence.company.review")):
        raise HTTPException(403, "Company review permission required")
    ctx = shell_ctx(request, active_module="evidence", active_section="evidence")
    return shell_templates.TemplateResponse(request, "evidence_companies.html", ctx)


# ── CRUD API ────────────────────────────────────────────────────────────────

_SORTS = {
    "updated": "e.updated_at DESC, e.id DESC",
    "title": "LOWER(e.title) ASC, e.id DESC",
    "review_due": "CASE WHEN e.review_due_date IS NULL THEN 1 ELSE 0 END, e.review_due_date ASC, e.id DESC",
    "expiry": "CASE WHEN e.expiry_date IS NULL THEN 1 ELSE 0 END, e.expiry_date ASC, e.id DESC",
}


@router.get("/api/items")
@require_auth
async def api_evidence_list(request: Request):
    """List one page of evidence items: {items, total, page, page_size, pages}. A row carries what the library shows: its
    owner and review date, how its links stand, up to two claims it supports that the caller may open, and one state."""
    return JSONResponse(_library_page(request.state.user, request.query_params))


@router.get("/api/company-views")
@require_auth
async def api_company_views(request: Request):
    db = get_db()
    try:
        return JSONResponse(company_views.facets(db, request.state.user))
    finally:
        db.close()


@router.get("/api/companies")
@require_auth
async def api_evidence_companies(request: Request):
    db = get_db()
    try:
        return JSONResponse({**ownership.facets(db, request.state.user),
                             "catalogue": ownership.companies(db, request.state.user),
                             "can_manage": has_capability(request.state.user, "evidence.company.manage"),
                             "can_review": has_capability(request.state.user, "evidence.company.review")})
    finally:
        db.close()


@router.post("/api/companies", status_code=201)
@require_auth
async def api_evidence_company_create(request: Request):
    data = await _group_body(request)
    db = get_db()
    try:
        company_id = ownership.create_company(db, request.state.user, data.get("name"))
        db.commit()
        from core.middleware import log_audit
        log_audit(request.state.user, "evidence", "Created company label", "evidence_company", company_id)
        return JSONResponse({"id": company_id}, status_code=201)
    finally:
        db.close()


@router.post("/api/items/{eid}/company/propose")
@require_auth
async def api_evidence_company_propose(request: Request, eid: int):
    data = await _group_body(request)
    db = get_db()
    try:
        ownership.propose(db, request.state.user, eid, data.get("company_id"), data.get("reason"))
        db.commit()
        from core.middleware import log_audit
        log_audit(request.state.user, "evidence", "Proposed company label", "evidence", eid)
        return JSONResponse({"state": "pending"})
    finally:
        db.close()


@router.post("/api/items/{eid}/company/review")
@require_auth
async def api_evidence_company_review(request: Request, eid: int):
    data = await _group_body(request)
    db = get_db()
    try:
        state = ownership.review(db, request.state.user, eid, data.get("decision"), data.get("reason"))
        db.commit()
        from core.middleware import log_audit
        log_audit(request.state.user, "evidence", "Reviewed company label: " + state, "evidence", eid)
        return JSONResponse({"state": state})
    finally:
        db.close()


@router.get("/api/items/{eid}/company/history")
@require_auth
async def api_evidence_company_history(request: Request, eid: int):
    db = get_db()
    try:
        return JSONResponse({"events": ownership.history(db, request.state.user, eid)})
    finally:
        db.close()


@router.get("/api/unit-company-mappings")
@require_auth
async def api_unit_company_mappings(request: Request):
    db = get_db()
    try:
        return JSONResponse({"units": ownership.unit_mappings(db, request.state.user)})
    finally:
        db.close()


@router.post("/api/units/{unit_id}/company/propose")
@require_auth
async def api_unit_company_propose(request: Request, unit_id: int):
    data = await _group_body(request)
    db = get_db()
    try:
        ownership.propose_unit_mapping(db, request.state.user, unit_id,
                                       data.get("company_id"), data.get("reason"))
        db.commit()
        from core.middleware import log_audit
        log_audit(request.state.user, "evidence", "Proposed unit company mapping", "business_unit", unit_id)
        return JSONResponse({"status": "pending"})
    finally:
        db.close()


@router.post("/api/units/{unit_id}/company/review")
@require_auth
async def api_unit_company_review(request: Request, unit_id: int):
    data = await _group_body(request)
    db = get_db()
    try:
        decision = ownership.review_unit_mapping(db, request.state.user, unit_id,
                                                 data.get("decision"), data.get("reason"))
        db.commit()
        from core.middleware import log_audit
        log_audit(request.state.user, "evidence", "Reviewed unit company mapping", "business_unit", unit_id)
        return JSONResponse({"status": decision})
    finally:
        db.close()


async def _group_body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(422, "Provide a JSON request") from None
    if not isinstance(data, dict):
        raise HTTPException(422, "Provide a JSON object")
    return data


@router.get("/api/group/workspace")
@require_auth
async def api_group_workspace(request: Request):
    db = get_db()
    try:
        return JSONResponse(group_documents.management_workspace(db, request.state.user))
    finally:
        db.close()


@router.get("/api/group/source-candidates")
@require_auth
async def api_group_source_candidates(request: Request):
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        raise HTTPException(422, "Invalid document search page") from None
    db = get_db()
    try:
        return JSONResponse(group_documents.source_candidates(
            db, request.state.user, request.query_params.get("q", ""), page))
    finally:
        db.close()


@router.get("/api/group/requests")
@require_auth
async def api_group_requests(request: Request):
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        raise HTTPException(422, "Invalid request page") from None
    db = get_db()
    try:
        return JSONResponse(group_requests.list_requests(db, request.state.user, page=page))
    finally:
        db.close()


@router.get("/api/group/adoptions")
@require_auth
async def api_group_adoptions(request: Request):
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        raise HTTPException(422, "Invalid policy page") from None
    db = get_db()
    try:
        return JSONResponse(group_adoption.list_policies(db, request.state.user, page=page))
    finally:
        db.close()


@router.post("/api/group/publications/{publication_id}/adoptions", status_code=201)
@require_auth
async def api_group_adoption_propose(request: Request, publication_id: int):
    body = await _group_body(request)
    adoption_id = _group_operation(lambda db: group_adoption.propose(
        db, request.state.user, publication_id, body.get("proposed_state"),
        body.get("reason"), body.get("review_due_at"), body.get("effective_at"),
        body.get("local_policy_version_id")))
    return JSONResponse({"id": adoption_id, "status": "pending_review"}, status_code=201)


@router.post("/api/group/adoptions/{adoption_id}/review")
@require_auth
async def api_group_adoption_review(request: Request, adoption_id: int):
    body = await _group_body(request)
    state = _group_operation(lambda db: group_adoption.review(
        db, request.state.user, adoption_id, body.get("decision"), body.get("reason")))
    return JSONResponse({"status": state})


@router.get("/api/group/requests/{request_id}/release-candidates")
@require_auth
async def api_group_request_release_candidates(request: Request, request_id: int):
    db = get_db()
    try:
        return JSONResponse({"items": group_requests.release_candidates(
            db, request.state.user, request_id)})
    finally:
        db.close()


@router.post("/api/group/relationships/{relation_id}/requests", status_code=201)
@require_auth
async def api_group_request_create(request: Request, relation_id: int):
    body = await _group_body(request)
    request_id = _group_operation(lambda db: group_requests.create_request(
        db, request.state.user, relation_id, body.get("requirement_ref"), body.get("purpose"),
        body.get("needed_by"), body.get("period_start"), body.get("period_end")))
    return JSONResponse({"id": request_id, "status": "requested"}, status_code=201)


@router.post("/api/group/requests/{request_id}/mapping")
@require_auth
async def api_group_request_map(request: Request, request_id: int):
    body = await _group_body(request)
    try:
        entity_id = int(body.get("entity_id"))
    except (TypeError, ValueError):
        raise HTTPException(422, "Choose a source record") from None
    _group_operation(lambda db: group_requests.map_request(
        db, request.state.user, request_id, body.get("module"), body.get("entity_type"), entity_id))
    return JSONResponse({"status": "mapped"})


@router.post("/api/group/requests/{request_id}/decisions")
@require_auth
async def api_group_request_review(request: Request, request_id: int):
    body = await _group_body(request)
    _group_operation(lambda db: group_requests.review_request(
        db, request.state.user, request_id, body.get("decision"), body.get("reason")))
    return JSONResponse({"status": body.get("decision")})


@router.post("/api/group/requests/{request_id}/revision")
@require_auth
async def api_group_request_revise(request: Request, request_id: int):
    body = await _group_body(request)
    _group_operation(lambda db: group_requests.revise_request(
        db, request.state.user, request_id, body.get("requirement_ref"), body.get("purpose"),
        body.get("needed_by"), body.get("period_start"), body.get("period_end")))
    return JSONResponse({"status": "requested"})


@router.post("/api/group/requests/{request_id}/fulfillment")
@require_auth
async def api_group_request_fulfill(request: Request, request_id: int):
    body = await _group_body(request)
    try:
        publication_id = int(body.get("publication_id"))
    except (TypeError, ValueError):
        raise HTTPException(422, "Choose a released document") from None
    _group_operation(lambda db: group_requests.fulfill_request(
        db, request.state.user, request_id, publication_id))
    return JSONResponse({"status": "fulfilled"})


def _group_operation(work):
    db = get_db()
    try:
        result = work(db)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@router.post("/api/group/relationships", status_code=201)
@require_auth
async def api_group_relationship_propose(request: Request):
    body = await _group_body(request)
    try:
        parent_id, child_id = int(body.get("parent_org_id")), int(body.get("child_org_id"))
    except (TypeError, ValueError):
        raise HTTPException(422, "Choose parent and child organizations") from None
    relation_id = _group_operation(lambda db: group_documents.propose_relationship(
        db, request.state.user, parent_id, child_id, str(body.get("purpose") or ""),
        body.get("terms"), body.get("review_due_at")))
    return JSONResponse({"id": relation_id, "status": "proposed"}, status_code=201)


@router.post("/api/group/relationships/{relation_id}/decisions")
@require_auth
async def api_group_relationship_decision(request: Request, relation_id: int):
    body = await _group_body(request)
    result = _group_operation(lambda db: group_documents.record_relationship_decision(
        db, request.state.user, relation_id, body.get("kind")))
    return JSONResponse(result)


@router.post("/api/group/relationships/{relation_id}/grants", status_code=201)
@require_auth
async def api_group_grant(request: Request, relation_id: int):
    body = await _group_body(request)
    try:
        recipient_id = int(body.get("user_id"))
    except (TypeError, ValueError):
        raise HTTPException(422, "Choose a recipient") from None
    grant_id = _group_operation(lambda db: group_documents.grant_view(
        db, request.state.user, relation_id, recipient_id, body.get("capability"),
        body.get("expires_at"), body.get("review_due_at")))
    return JSONResponse({"id": grant_id}, status_code=201)


@router.get("/api/group/relationships/{relation_id}/exit-impact")
@require_auth
async def api_group_exit_impact(request: Request, relation_id: int):
    db = get_db()
    try:
        return JSONResponse(group_documents.exit_impact(db, request.state.user, relation_id))
    finally:
        db.close()


@router.delete("/api/group/relationships/{relation_id}")
@require_auth
async def api_group_relationship_end(request: Request, relation_id: int):
    body = await _group_body(request)
    _group_operation(lambda db: group_documents.end_relationship(
        db, request.state.user, relation_id, body.get("reason")))
    return JSONResponse({"status": "ended"})


@router.delete("/api/group/grants/{grant_id}")
@require_auth
async def api_group_grant_revoke(request: Request, grant_id: int):
    _group_operation(lambda db: group_documents.revoke_grant(db, request.state.user, grant_id))
    return JSONResponse({"status": "revoked"})


@router.post("/api/group/grants/{grant_id}/review")
@require_auth
async def api_group_grant_review(request: Request, grant_id: int):
    body = await _group_body(request)
    result = _group_operation(lambda db: group_documents.review_grant(
        db, request.state.user, grant_id, body.get("decision"), body.get("reason"),
        body.get("expires_at"), body.get("review_due_at")))
    return JSONResponse(result)


@router.post("/api/group/rights/{eid}")
@require_auth
async def api_group_rights(request: Request, eid: int):
    body = await _group_body(request)
    rights_id = _group_operation(lambda db: group_documents.reviewed_rights(
        db, request.state.user, eid, body.get("rights_state"),
        body.get("permit_group_view") is True, body.get("permit_group_download") is True,
        str(body.get("basis") or "")))
    return JSONResponse({"id": rights_id})


@router.post("/api/group/relationships/{relation_id}/publications", status_code=201)
@require_auth
async def api_group_publish(request: Request, relation_id: int):
    body = await _group_body(request)
    try:
        eid = int(body.get("evidence_id"))
    except (TypeError, ValueError):
        raise HTTPException(422, "Choose evidence") from None
    pub_id = _group_operation(lambda db: group_documents.publish(
        db, request.state.user, relation_id, eid, body.get("classification"),
        str(body.get("purpose") or ""), body.get("expires_at")))
    return JSONResponse({"id": pub_id}, status_code=201)


@router.get("/api/group/publications")
@require_auth
async def api_group_catalogue(request: Request):
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        raise HTTPException(422, "Invalid catalogue page") from None
    db = get_db()
    try:
        return JSONResponse({"items": group_documents.catalogue(db, request.state.user, page=page),
                             "page": page})
    finally:
        db.close()


@router.get("/api/group/companies")
@require_auth
async def api_group_source_companies(request: Request):
    db = get_db()
    try:
        return JSONResponse({"companies": group_documents.source_companies(db, request.state.user)})
    finally:
        db.close()


@router.get("/api/group/companies/{source_org_id}/publications")
@require_auth
async def api_group_company_publications(request: Request, source_org_id: int):
    raw = request.query_params.get("before", "")
    try:
        before = int(raw) if raw else None
    except ValueError:
        raise HTTPException(422, "Invalid catalogue cursor") from None
    db = get_db()
    try:
        return JSONResponse(group_documents.catalogue_cursor(
            db, request.state.user, source_org_id=source_org_id, before_id=before))
    finally:
        db.close()


@router.delete("/api/group/publications/{publication_id}")
@require_auth
async def api_group_publication_revoke(request: Request, publication_id: int):
    _group_operation(lambda db: group_documents.revoke_publication(db, request.state.user, publication_id))
    return JSONResponse({"status": "revoked"})


@router.get("/api/group/publications/{publication_id}")
@require_auth
async def api_group_publication(request: Request, publication_id: int):
    db = get_db()
    try:
        row, _ = group_documents.released_item(db, request.state.user, publication_id)
        group_documents.access_event(db, row, request.state.user, "open")
        db.commit()
        return JSONResponse({"id": row["id"], "title": row["title"], "version": row["version"],
                             "category": row["category"], "source_name": row["source_name"],
                             "classification": row["classification"], "expires_at": row["expires_at"]})
    finally:
        db.close()


@router.get("/api/group/publications/{publication_id}/download")
@require_auth
async def api_group_publication_download(request: Request, publication_id: int):
    db = get_db()
    try:
        row, item = group_documents.released_item(db, request.state.user, publication_id, download=True)
        rel = item["file_path"] or ""
        if not rel or rel.startswith("aria://"):
            raise HTTPException(404, "Publication file unavailable")
        candidate = (EVIDENCE_DIR / rel).resolve()
        if not candidate.is_relative_to(EVIDENCE_DIR.resolve()) or not candidate.is_file():
            raise HTTPException(404, "Publication file unavailable")
        group_documents.access_event(db, row, request.state.user, "download")
        db.commit()
        return FileResponse(str(candidate), filename=item["file_name"] or "download",
                            media_type=item["mime_type"] or "application/octet-stream")
    finally:
        db.close()


@router.get("/api/folders")
@require_auth
async def api_evidence_folders(request: Request):
    db = get_db()
    try:
        return JSONResponse({"folders": vault_views.folder_counts(db, request.state.user)})
    finally:
        db.close()


@router.get("/api/folders/{group}/records")
@require_auth
async def api_evidence_record_folders(request: Request, group: str):
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        page = 1
    db = get_db()
    try:
        try:
            data = vault_views.record_folders(db, request.state.user, group, page,
                                              request.query_params.get("q", ""))
        except ValueError:
            raise HTTPException(404, "Folder not found") from None
        return JSONResponse(data)
    finally:
        db.close()


def _library_page(user: dict, qp, size: int = None) -> dict:
    """One page of the library for `user` from list parameters (a mapping with .get). `size` overrides the page sizes the
    list offers: Find evidence uses it to take the first few."""
    try:
        page_size = int(qp.get("page_size", ""))
    except ValueError:
        page_size = _PAGE_SIZES[0]
    if page_size not in _PAGE_SIZES:
        page_size = _PAGE_SIZES[0]
    if size is not None:
        page_size = size
    try:
        page = max(1, int(qp.get("page", "1")))
    except ValueError:
        page = 1

    scope_sql, scope_params = evidence_scope_sql(user)
    search_sql, search_params = evidence_search_sql(qp.get("q", ""))
    where = [scope_sql, search_sql]
    params = [*scope_params, *search_params]
    filing_scope = qp.get("filing_scope", "")
    if filing_scope:
        db_scope = get_db()
        try:
            chosen_unit = company_views.selected_unit(db_scope, user, filing_scope)
        finally:
            db_scope.close()
        if filing_scope == "organization":
            where.append("e.business_unit_id IS NULL")
        else:
            where.append("e.business_unit_id = %s")
            params.append(chosen_unit)
    company_view = qp.get("company", "")
    if company_view:
        db_scope = get_db()
        try:
            company_id = ownership.selected_company(db_scope, user, company_view)
        finally:
            db_scope.close()
        if company_view == "unconfirmed":
            where.append("NOT EXISTS (SELECT 1 FROM evidence_companies c WHERE c.id=e.company_id "
                         "AND c.org_id=e.org_id AND c.is_active=1 AND e.company_state='confirmed')")
        else:
            where.append("e.company_id = %s AND e.company_state = 'confirmed'")
            params.append(company_id)
    for word in str(qp.get("words") or "").split()[:finder.WORDS_MAX]:  # Find evidence: every word must match
        word_sql, word_params = evidence_search_sql(word)
        where.append(word_sql)
        params += word_params
    if qp.get("category"):
        where.append("e.category = %s")
        params.append(qp["category"])
    if qp.get("module"):
        where.append(
            "e.id IN (SELECT evidence_id FROM evidence_links WHERE module = %s AND deleted_at IS NULL)"
        )
        params.append(qp["module"])
    owner = qp.get("owner", "")
    if owner == "me":
        where.append("e.owner_user_id = %s")
        params.append(user["id"])
    elif owner.isdigit():
        where.append("e.owner_user_id = %s")
        params.append(int(owner))

    view = qp.get("view", "")
    view = view if view in _VIEWS else "all"
    view_clauses, view_params = _view_where(view, user)
    if view == "all":
        # The default list hides archived and superseded rows unless a status asks for one.
        if qp.get("status"):
            view_clauses = ["e.status != 'archived'", "e.status = %s"]
            view_params = [qp["status"]]
    where += view_clauses
    params += view_params
    state = qp.get("state", "")
    if state in finder.STATES:
        where += _state_where(state)
    sort_key = qp.get("sort", "")
    order = _SORTS.get(sort_key) or (_SORTS["review_due"] if view == "review_due" else _SORTS["updated"])

    db = get_db()
    try:
        try:
            folder_where, folder_params = vault_views.folder_sql(qp.get("folder", ""), user, db)
        except ValueError:
            raise HTTPException(404, "Folder not found") from None
        where.append(folder_where)
        params.extend(folder_params)
        where_sql = " AND ".join(where)
        total = db.execute(f"SELECT COUNT(*) FROM evidence_items e WHERE {where_sql}", params).fetchone()[0]
        pages = max(1, -(-total // page_size))
        page = min(page, pages)
        live = "el.evidence_id = e.id AND el.deleted_at IS NULL"
        rows = db.execute(
            "SELECT e.*, u.full_name as uploaded_by_name, ou.full_name as owner_name, "
            "bu.name as filing_unit_name, "
            f"(SELECT COUNT(*) FROM evidence_links el WHERE {live}) as link_count, "
            f"(SELECT COUNT(*) FROM evidence_links el WHERE {live} AND COALESCE(el.review_status, 'pending') = 'accepted') as links_accepted, "
            f"(SELECT COUNT(*) FROM evidence_links el WHERE {live} AND COALESCE(el.review_status, 'pending') = 'pending') as links_pending, "
            f"(SELECT COUNT(*) FROM evidence_links el WHERE {live} AND COALESCE(el.review_status, 'pending') IN ('returned', 'rejected')) as links_returned, "
            f"(SELECT COUNT(*) FROM evidence_links el WHERE {live} AND COALESCE(el.review_status, 'pending') = 'out_of_scope') as links_out_of_scope "
            "FROM evidence_items e LEFT JOIN users u ON e.uploaded_by = u.id LEFT JOIN users ou ON e.owner_user_id = ou.id "
            "LEFT JOIN business_units bu ON bu.id = e.business_unit_id "
            f"WHERE {where_sql} ORDER BY {order} LIMIT %s OFFSET %s",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        claims = _claims_for(db, user, [r["id"] for r in rows])
        terms = [str(qp.get("q") or "").strip(), *str(qp.get("words") or "").split()[:finder.WORDS_MAX]]
        snippets = snippets_for_page(db, rows, terms)
    finally:
        db.close()
    today = proof.today()
    items = []
    for r in rows:
        item = dict(r)
        item["state"] = proof.item_state(
            status=item["status"], expiry_date=item.get("expiry_date"),
            links_active=item["link_count"] - item["links_out_of_scope"], links_pending=item["links_pending"],
            links_returned=item["links_returned"], on=today)
        item["review_due"] = proof.due(item.get("review_due_date"), today, within_days=30)
        shown = claims.get(item["id"], {"claims": [], "more": 0, "hidden": 0})
        item["claims"], item["claims_more"], item["claims_hidden"] = shown["claims"], shown["more"], shown["hidden"]
        item["text_match"] = snippets.get(item["id"])
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size, "pages": pages}


@router.get("/api/inspector")
@require_auth
async def api_evidence_inspector(request: Request):
    """Concrete defects in what the caller may open, most serious first, each with the rule and where to put it right."""
    qp = request.query_params
    rule = qp.get("rule") or None
    if rule is not None and rule not in inspector.RULES:
        return JSONResponse({"error": "Unknown check."}, status_code=400)
    try:
        limit = int(qp.get("limit", "50"))
    except ValueError:
        limit = 50
    db = get_db()
    try:
        return JSONResponse(inspector.inspect(db, request.state.user, rule=rule, limit=limit))
    finally:
        db.close()


@router.get("/api/items/{eid}/checks")
@require_auth
async def api_evidence_checks(request: Request, eid: int):
    """The same checks for one file."""
    db = get_db()
    try:
        if not _scoped_evidence_item(db, eid, request.state.user):
            raise HTTPException(404, "Evidence not found")
        return JSONResponse(inspector.inspect(db, request.state.user, evidence_id=eid))
    finally:
        db.close()


@router.post("/api/find")
@require_auth
async def api_evidence_find(request: Request):
    """Find evidence: a question in the caller's words becomes editable filters over the same scoped list, and up to five
    files come back with why each matched. Read-only. `filters` (from an earlier answer, edited) skips the reading."""
    data = await _json_body(request)
    user = request.state.user
    question = data.get("question")
    if data.get("filters") is not None:
        filters, mode, note = finder.clean_filters(data.get("filters")), "edited", None
    else:
        if not isinstance(question, str) or not question.strip():
            return JSONResponse({"error": "Ask a question, for example: expired test reports that are mine."}, status_code=422)
        if len(question) > finder.QUESTION_MAX:
            return JSONResponse({"error": f"Keep the question to {finder.QUESTION_MAX} characters or fewer."}, status_code=422)
        got = finder.parse(question, use_ai=bool(data.get("use_ai", True)))
        filters, mode, note = got["filters"], got["mode"], got["note"]
    qp = finder.list_params(filters)
    page = _library_page(user, qp, size=finder.RESULT_LIMIT)
    results = [{"id": r["id"], "title": r["title"], "version": r["version"], "state": r["state"],
                "expiry_date": r.get("expiry_date"), "review_due_date": r.get("review_due_date"),
                "owner_name": r.get("owner_name"), "claims": r["claims"], "claims_hidden": r["claims_hidden"],
                "url": f"/evidence/?open=item:{r['id']}", "why": finder.reasons(r, filters),
                "text_match": r.get("text_match")} for r in page["items"]]
    return JSONResponse({"filters": filters, "mode": mode, "note": note, "total": page["total"], "results": results,
                         "message": None if results else "No accessible match. Nothing you may open fits those filters.",
                         "vocabulary": finder.vocabulary()})


@router.get("/api/people")
@require_auth
async def api_evidence_people(request: Request):
    """Colleagues to name as an owner: names only, the caller's own organization only, found by typing."""
    user = request.state.user
    q = (request.query_params.get("q") or "").strip()
    db = get_db()
    try:
        sql, params = "SELECT id, full_name FROM users WHERE is_active = 1 AND deleted_at IS NULL", []
        if user.get("org_id") is not None:
            sql, params = sql + " AND org_id = %s", [user["org_id"]]
        elif not user.get("is_super_admin"):
            return JSONResponse({"items": []})
        if q:
            sql, params = sql + f" AND ({ci_like('full_name')} OR {ci_like('username')})", [*params, like_pattern(q), like_pattern(q)]
        rows = db.execute(sql + " ORDER BY full_name LIMIT 30", params).fetchall()
    finally:
        db.close()
    return JSONResponse({"items": [{"id": r["id"], "name": r["full_name"]} for r in rows]})


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
    owner_user_id: str = Form(""),
    review_due_date: str = Form(""),
    period_start: str = Form(""),
    period_end: str = Form(""),
    link_module: str = Form(""),
    link_entity_type: str = Form(""),
    link_entity_id: str = Form(""),
    filing_scope: str = Form(""),
):
    """Upload a file and optionally create a pending link in one transaction."""
    user = request.state.user
    if not user.get("is_super_admin") and not user.get("org_id"):
        raise HTTPException(403, "Your account has no organization to upload evidence for")
    org_id = None if user.get("is_super_admin") else user.get("org_id")

    from core.sanitize import sanitize_str as _s
    title, description, category, tags = _s(title), _s(description), _s(category), _s(tags)
    if category == "generated_record":
        return JSONResponse({"error": "Generated records are filed from their source module."}, status_code=422)
    expiry_date = _s(expiry_date)
    days, problems = {}, []
    for name, value in (("expiry_date", expiry_date), ("review_due_date", _s(review_due_date)),
                        ("period_start", _s(period_start)), ("period_end", _s(period_end))):
        days[name], problem = _clean_day(value, _DAY_LABELS[name])
        if problem:
            problems.append(problem)
    if days["period_start"] and days["period_end"] and days["period_end"] < days["period_start"]:
        problems.append("The period cannot end before it starts.")
    if problems:
        return JSONResponse({"error": " ".join(problems)}, status_code=422)
    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large (max 100MB)")

    # Direct callers in the route tests omit the optional Form fields.
    link_module = _s(link_module) if isinstance(link_module, str) else ""
    link_entity_type = _s(link_entity_type) if isinstance(link_entity_type, str) else ""
    link_entity_id = _s(link_entity_id) if isinstance(link_entity_id, str) else ""
    filing_scope = filing_scope.strip() if isinstance(filing_scope, str) else ""
    selected_target = bool(link_module or link_entity_type or link_entity_id)
    if selected_target and not all((link_module, link_entity_type, link_entity_id)):
        return JSONResponse({"error": "Choose a complete claim to link."}, status_code=422)
    target_id = None
    if selected_target:
        try:
            target_id = int(link_entity_id)
        except ValueError:
            return JSONResponse({"error": "Choose a valid claim."}, status_code=422)
        if target_id <= 0:
            return JSONResponse({"error": "Choose a valid claim."}, status_code=422)

    # Validate filing and referenced-record authority before processing bytes.
    # An unlinked upload never silently inherits a broad or unit scope.
    if not selected_target and not filing_scope:
        return JSONResponse({"error": "Choose an authorized filing scope."}, status_code=422)
    requested_unit = None
    scope_db = get_db()
    try:
        if filing_scope:
            requested_unit = company_views.selected_unit(scope_db, user, filing_scope, for_filing=True)
        if selected_target and not _visible_target(scope_db, (link_module, link_entity_type), target_id, user):
            raise HTTPException(404, "Link target not found")
        replacement_for_access = replace_id.strip() if isinstance(replace_id, str) else ""
        if replacement_for_access:
            if not replacement_for_access.isdigit() or int(replacement_for_access) < 1:
                return JSONResponse({"error": "Choose a valid version to replace."}, status_code=422)
            if not _scoped_evidence_item(scope_db, int(replacement_for_access), user):
                raise HTTPException(404, "Evidence not found")
    finally:
        scope_db.close()

    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "File too large (max 100MB)")

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
    dest = None
    try:
        if selected_target and not _visible_target(db, (link_module, link_entity_type), target_id, user):
            raise HTTPException(404, "Link target not found")
        # An unlinked upload by a unit-scoped user belongs to that unit.
        # Otherwise a private file silently becomes visible organization-wide.
        target_unit = user.get("business_unit_id") if not selected_target else None
        if selected_target:
            _, target_unit = record_unit(db, link_module, link_entity_type, target_id, user=user)
        if filing_scope:
            if selected_target and requested_unit != target_unit:
                return JSONResponse({"error": "Filing scope must match the linked record."}, status_code=422)
            if not selected_target:
                target_unit = requested_unit
        elif target_unit is None and not user.get("is_super_admin") and not company_views.can_file_org_wide(user):
            return JSONResponse({"error": "Choose an authorized filing scope."}, status_code=422)

        parent_id = None
        parent_row = None
        version_num = 1
        replacement = replace_id.strip() if isinstance(replace_id, str) else ""
        if replacement:
            try:
                rid = int(replacement)
            except ValueError:
                return JSONResponse({"error": "Choose a valid version to replace."}, status_code=422)
            if rid <= 0:
                return JSONResponse({"error": "Choose a valid version to replace."}, status_code=422)
            parent_row = _scoped_evidence_item(db, rid, user)
            if not parent_row:
                raise HTTPException(404, "Evidence not found")
            if parent_row["category"] == "generated_record":
                return JSONResponse({"error": "Generated records are versioned from their source module."}, status_code=409)
            if parent_row["status"] != "current":
                return JSONResponse({"error": "Only the current version can be replaced."}, status_code=409)
            if filing_scope and parent_row["business_unit_id"] != requested_unit:
                return JSONResponse({"error": "A new version keeps the original filing scope."}, status_code=422)
            parent_id = rid
            version_num = parent_row["version"] + 1
            if selected_target and target_unit is not None and parent_row["business_unit_id"] != target_unit:
                return JSONResponse({"error": "The selected claim belongs to a different business unit."}, status_code=422)

        owner, owner_problem = _clean_owner(db, user, owner_user_id) if str(owner_user_id).strip() else (None, None)
        if owner_problem:
            return JSONResponse({"error": owner_problem}, status_code=422)
        if owner is None and parent_row is not None:
            owner = parent_row["owner_user_id"]
        if owner is None:
            owner = _uid(request)

        dupe_scope, dupe_params = evidence_scope_sql(user)
        existing = db.execute(
            "SELECT e.id, e.title, e.status FROM evidence_items e "
            f"WHERE e.file_hash = %s AND e.status != 'archived' AND {dupe_scope}",
            [file_hash, *dupe_params],
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

        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(content)

        display_title = title or original_name or "Untitled"

        if parent_id is not None:
            changed = db.execute(
                "UPDATE evidence_items SET status = 'superseded', updated_at = CURRENT_TIMESTAMP "
                "WHERE id = %s AND status = 'current'", (parent_id,),
            )
            if changed.rowcount != 1:
                raise HTTPException(409, "The current version changed. Reload and try again.")
        exp = days["expiry_date"]

        eid = insert_returning_id(
            db,
            "INSERT INTO evidence_items (title, description, file_path, file_name, file_size, "
            "file_hash, mime_type, category, tags, version, parent_id, uploaded_by, expiry_date, org_id, "
            "owner_user_id, review_due_date, period_start, period_end, business_unit_id, company_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                display_title, description, str(stored_name), original_name,
                len(content), file_hash, declared_mime,
                category, tags, version_num, parent_id, _uid(request), exp, org_id,
                owner, days["review_due_date"], days["period_start"], days["period_end"],
                (parent_row["business_unit_id"] if parent_row is not None else target_unit),
                (parent_row["company_id"] if parent_row is not None else None),
            )
        )
        if parent_id is None and target_unit is not None and org_id is not None:
            # A reviewed unit map is only a suggestion for this document. A
            # different specialist still has to confirm its company label.
            suggested = ownership.suggested_company_for_unit(db, user, target_unit)
            if suggested is not None:
                why = "Suggested from reviewed business-unit mapping; confirm this document's owner"
                db.execute("UPDATE evidence_items SET company_id=%s,company_state='pending',"
                           "company_proposed_by=%s,company_reason=%s WHERE id=%s AND org_id=%s",
                           (suggested, _uid(request), why, eid, org_id))
                db.execute("INSERT INTO evidence_company_events "
                           "(org_id,evidence_id,company_id,action,actor_id,reason) "
                           "VALUES(%s,%s,%s,'proposed',%s,%s)",
                           (org_id, eid, suggested, _uid(request), why))
        impact = None
        touched_controls = []
        if parent_id is not None:
            touched_controls = _canonical_controls_linked_to(db, [parent_id])
            impact = proof.carry_forward(db, user, parent_id, eid)
            # The records the replaced version supported are told, and each owner says whether it needs a second look.
            from modules.governance import change_signals
            change_signals.publish(
                db, source=("evidence", "item", eid), kind="evidence_replaced",
                before={"version": parent_row["version"]}, after={"version": version_num}, fields={"version": "Version"},
                actor_id=_uid(request), org_id=org_id,
                extra_targets=[(r["module"], r["entity_type"], r["entity_id"]) for r in db.execute(
                    "SELECT module, entity_type, entity_id FROM evidence_links WHERE evidence_id = %s AND deleted_at IS NULL",
                    (parent_id,)).fetchall()])
        link = None
        if selected_target:
            # A replacement may already have proposed this link through carry_forward.
            present = db.execute(
                "SELECT id FROM evidence_links WHERE evidence_id = %s AND module = %s AND entity_type = %s "
                "AND entity_id = %s AND deleted_at IS NULL",
                (eid, link_module, link_entity_type, target_id),
            ).fetchone()
            lid = present["id"] if present else insert_returning_id(
                db,
                "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) "
                "VALUES (%s,%s,%s,%s,%s)",
                (eid, link_module, link_entity_type, target_id, _uid(request)),
            )
            link = {"id": lid, "module": link_module, "entity_type": link_entity_type,
                    "entity_id": target_id, "review_status": "pending"}
        if selected_target or (impact and impact["carried"]):
            recompute_confidence(db, eid)
        db.commit()
    except Exception:
        db.rollback()
        if dest is not None:
            dest.unlink(missing_ok=True)
        raise
    finally:
        db.close()
    _rescore_controls(touched_controls)

    return JSONResponse({
        "id": eid, "title": display_title, "version": version_num,
        "file_hash": file_hash, "duplicate": False, "impact": impact, "link": link,
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
            "SELECT e.*, u.full_name as uploaded_by_name, ou.full_name as owner_name FROM evidence_items e "
            "LEFT JOIN users u ON e.uploaded_by = u.id LEFT JOIN users ou ON e.owner_user_id = ou.id "
            "WHERE e.id = %s", (eid,)
        ).fetchone()
        if not item:
            raise HTTPException(404, "Evidence not found")
        result = dict(item)
        index_row = db.execute(
            "SELECT status,error_code FROM evidence_text_index "
            "WHERE evidence_id=%s AND file_hash=%s AND COALESCE(org_id,-1)=COALESCE(%s,-1) "
            "AND COALESCE(business_unit_id,-1)=COALESCE(%s,-1)",
            (eid, result["file_hash"] or "", result["org_id"], result["business_unit_id"]),
        ).fetchone()
        result["text_index"] = (dict(index_row) if index_row else
                                {"status": ("pending" if indexing_enabled() else "disabled")
                                 if result["file_path"] else "not_applicable",
                                 "error_code": None})
        links = []
        for r in db.execute(
            "SELECT el.*, u.full_name as linked_by_name, ru.full_name as reviewed_by_name FROM evidence_links el "
            "LEFT JOIN users u ON el.linked_by = u.id LEFT JOIN users ru ON el.reviewed_by = ru.id "
            "WHERE el.evidence_id = %s AND el.deleted_at IS NULL "
            "ORDER BY el.created_at DESC",
            (eid,)
        ).fetchall():
            link = dict(r)
            link["review_status"] = link.get("review_status") or "pending"
            link["review_label"] = proof.OUTCOME_LABELS[link["review_status"]]
            links.append(link)
        result["links"] = links
    finally:
        db.close()
    active = [l for l in links if l["review_status"] != "out_of_scope"]
    result["state"] = proof.item_state(
        status=result["status"], expiry_date=result.get("expiry_date"), links_active=len(active),
        links_pending=sum(1 for l in active if l["review_status"] == "pending"),
        links_returned=sum(1 for l in active if l["review_status"] in ("returned", "rejected")))
    result["can_delete"] = has_capability(request.state.user, "evidence.delete")
    result["can_review_links"] = has_capability(request.state.user, "evidence.link.review")
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
        if item["category"] == "generated_record":
            return False, "Generated records follow their own retention history."
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
        item = _scoped_evidence_item(db, eid, request.state.user)
        if not item:
            raise HTTPException(404, "Evidence not found")
        if item["category"] == "generated_record":
            return JSONResponse({"error": "Edit generated records in their source module."}, status_code=409)
        if data.get("category") == "generated_record":
            return JSONResponse({"error": "Generated records are filed from their source module."}, status_code=422)
        allowed = ["title", "description", "category", "tags", "status", "expiry_date", "owner_user_id",
                   "review_due_date", "period_start", "period_end"]
        sets = []
        vals = []
        for k in allowed:
            if k in data:
                value, problem = _clean_field(db, request.state.user, k, data[k])
                if problem:
                    return JSONResponse({"error": problem}, status_code=422)
                sets.append(f"{k} = %s")
                vals.append(value)
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
        item = _scoped_evidence_item(db, eid, user)
        if not item:
            raise HTTPException(404, "Evidence not found")
        if item["category"] == "generated_record":
            return JSONResponse({"error": "Generated records follow their own retention history."}, status_code=409)
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
        item = _scoped_evidence_item(db, eid, request.state.user)
        if not item:
            raise HTTPException(404, "Evidence not found")
        if item["category"] == "generated_record":
            return JSONResponse({"error": "Generated records follow their own retention history."}, status_code=409)
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
        if item["category"] == "generated_record":
            return JSONResponse({"error": "Generated records follow their own retention history."}, status_code=409)
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
            if fp.is_relative_to(EVIDENCE_DIR.resolve()) and fp.exists():
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
            if (candidate.is_relative_to(EVIDENCE_DIR.resolve())
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
                    if (src_abs.is_relative_to(aria_dir.resolve())
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
            if candidate.is_relative_to(EVIDENCE_DIR.resolve()) and candidate.exists():
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
                        if src_abs.is_relative_to(aria_dir.resolve()) and src_abs.exists():
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

    pdf_path, tmpdir = await run_in_threadpool(_convert_office_preview, file_path)
    from core.report_kit.identity import safe_filename
    return FileResponse(
        str(pdf_path), filename=safe_filename(Path(fname).stem or "evidence", "pdf"),
        media_type="application/pdf",
        background=BackgroundTask(shutil.rmtree, tmpdir, ignore_errors=True),
    )


# ── Version History ────────────────────────────────────────────────────────

@router.get("/api/items/{eid}/versions")
@require_auth
async def api_evidence_versions(request: Request, eid: int):
    """Get only versions this viewer can open (newest first)."""
    db = get_db()
    try:
        user = request.state.user
        if not _scoped_evidence_item(db, eid, user):
            raise HTTPException(404, "Evidence not found")
        # Walk only through versions the viewer may open. A hidden ancestor
        # does not disclose siblings or the shape of its private branch.
        root_id = eid
        seen = {root_id}
        while True:
            row = _scoped_evidence_item(db, root_id, user)
            if not row or not row["parent_id"]:
                break
            if row["parent_id"] in seen:
                break  # safety: prevent infinite loop on corrupt data
            if not _scoped_evidence_item(db, row["parent_id"], user):
                break
            seen.add(row["parent_id"])
            root_id = row["parent_id"]

        # Walk down from the visible root, excluding hidden branches at SQL level.
        versions = []
        queue = [root_id]
        visited = set()
        child_scope, child_params = evidence_scope_sql(user)
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            item = _scoped_evidence_item(db, current, user)
            if item:
                versions.append({"id": item["id"], "title": item["title"], "version": item["version"],
                                 "status": item["status"], "created_at": str(item["created_at"])})
            children = db.execute(
                f"SELECT e.id FROM evidence_items e WHERE e.parent_id = %s AND {child_scope}",
                [current, *child_params],
            ).fetchall()
            queue.extend(c["id"] for c in children)

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
    if not file_on_disk.is_relative_to(EVIDENCE_DIR.resolve()):
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
        item = _scoped_evidence_item(db, eid, request.state.user)
        if not item:
            raise HTTPException(404, "Evidence not found")
        if not _visible_target(db, (module, entity_type), entity_id, request.state.user):
            raise HTTPException(404, "Link target not found")
        if item["status"] in ("superseded", "archived"):
            return JSONResponse({"error": "This version has been replaced or archived. Link the current version "
                                          "instead."}, status_code=409)
        already = db.execute(
            "SELECT id FROM evidence_links WHERE evidence_id = %s AND module = %s AND entity_type = %s "
            "AND entity_id = %s AND deleted_at IS NULL", (eid, module, entity_type, entity_id)).fetchone()
        if already:
            return JSONResponse({"id": already["id"], "existing": True}, status_code=201)
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


@router.post("/api/links/{lid}/review")
@require_auth
async def api_evidence_link_review(request: Request, lid: int):
    """A reviewer's verdict on one link: accepted, returned, rejected, does not apply, or back to waiting."""
    data = await _json_body(request)
    user = request.state.user
    db = get_db()
    try:
        done = proof.review_link(db, user, lid, data.get("outcome"), data.get("note"), data.get("expected_status"))
        db.commit()
    except proof.ReviewError as exc:
        db.rollback()
        return JSONResponse({"error": exc.message, **exc.extra}, status_code=exc.status)
    finally:
        db.close()
    if done["entity_type"] == "canonical_control":
        _rescore_controls([done["entity_id"]])
    from core.middleware import log_audit
    action, entity, entity_id, detail = done["audit"]
    log_audit(user, "evidence", action, entity, entity_id, details=detail)
    return JSONResponse({"link": done["link"]})


@router.get("/api/items/{eid}/impact")
@require_auth
async def api_evidence_impact(request: Request, eid: int):
    """What this version did to the claims the version it replaced was supporting."""
    db = get_db()
    try:
        got = proof.impact(db, request.state.user, eid)
    finally:
        db.close()
    if got is None:
        raise HTTPException(404, "Evidence not found")
    return JSONResponse(got)


@router.delete("/api/links/{lid}")
@require_auth
async def api_evidence_link_delete(request: Request, lid: int):
    """Soft-delete an evidence link (preserves audit trail)."""
    db = get_db()
    try:
        link_row = db.execute(
            "SELECT evidence_id, module, entity_type, entity_id FROM evidence_links WHERE id = %s", (lid,)
        ).fetchone()
        if not link_row or not _scoped_evidence_item(db, link_row["evidence_id"], request.state.user):
            raise HTTPException(404, "Link not found")
        generated = db.execute(
            "SELECT source_module, source_type, source_id FROM generated_record_documents WHERE evidence_id = %s",
            (link_row["evidence_id"],),
        ).fetchone()
        if (generated and link_row["module"] == generated["source_module"]
                and link_row["entity_type"] == generated["source_type"]
                and link_row["entity_id"] == generated["source_id"]):
            return JSONResponse({"error": "A generated record must stay linked to its source."}, status_code=409)
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
            feature="evidence.api_evidence_suggest_links",
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
                "entity_name": target["title"],
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

# The record kinds an evidence item can be linked to. What each one is (table, title, deep link) and who may
# open it (capability and business unit) comes from the shared registry in modules/governance/entity_scope.py,
# the one place Related Items, search and the AI workspace use too, so the Vault cannot show a record that the
# owning module would not.
_VAULT_TARGETS = (
    ("aria", "control"), ("aria", "document"), ("aria", "risk"), ("aria", "framework"),
    ("grid", "audit"), ("grid", "control"), ("grid", "nc"),
    ("bcm", "plan"), ("bcm", "incident"), ("bcm", "risk"), ("bcm", "bia"), ("bcm", "compliance_control"),
    ("sentinel", "ropa"), ("sentinel", "dpia"), ("sentinel", "breach"), ("sentinel", "dsr"), ("sentinel", "vendor"),
    ("erm", "risk"), ("erm", "scenario"),
    ("governance", "application"),  # proof for an AI use: shown on the Evidence tab of its workspace
)
# (module, entity_type) -> (table_name, name_column, url_template)
_ENTITY_RESOLVERS: dict[tuple[str, str], tuple[str, str, str]] = {
    key: (_KINDS[key].table, _KINDS[key].title, _KINDS[key].url) for key in _VAULT_TARGETS
}
# Evidence links already stored under the other spelling of a non-conformance keep resolving.
_ENTITY_RESOLVERS[("grid", "non_conformance")] = _ENTITY_RESOLVERS[("grid", "nc")]


def _target_scope_sql(key, user):
    """(joins, where list, params) limiting a query over the target's table, aliased t, to what the user may open."""
    scope, params = entity_scope_sql(canonical_key(*key), user, "t")
    return "", ([] if scope == "(1 = 1)" else [scope]), params


def _visible_target(db, key, entity_id, user):
    """{"title", "url"} of the target when the user may open it, else None (missing and hidden answer alike)."""
    if key not in _ENTITY_RESOLVERS or entity_id <= 0:
        return None
    return describe_record(db, canonical_key(*key), entity_id, user)


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
                shown = _visible_target(db, (module, entity_type), entity_id, request.state.user)
                if shown:
                    entry["name"] = shown["title"]
                    entry["url"] = shown["url"]

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

    valid_modules = frozenset({"aria", "grid", "bcm", "sentinel", "erm", "governance"})
    if module not in valid_modules:
        return JSONResponse({"error": "Invalid module"}, 400)

    key = (module, entity_type)
    if key not in _ENTITY_RESOLVERS:
        return JSONResponse({"error": "Unknown entity type"}, 400)

    table, name_col, _ = _ENTITY_RESOLVERS[key]
    id_col = "id"
    db = get_db()
    try:
        joins, where, params = _target_scope_sql(key, request.state.user)
        if q:
            where.append(f"LOWER(t.{name_col}) LIKE LOWER(%s)")
            params.append(f"%{q}%")
        only_id = request.query_params.get("entity_id", "")
        if only_id:  # one named record, still inside the caller's scope (the ?attach= deep link)
            try:
                where.append(f"t.{id_col} = %s")
                params.append(int(only_id))
            except ValueError:
                return JSONResponse({"error": "entity_id must be an integer"}, status_code=400)
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


@router.get("/api/coverage/definitions")
@require_auth
async def api_evidence_coverage_definitions(request: Request):
    """What each coverage measure means, so a number is never shown without its definition."""
    return JSONResponse({
        "as_of": proof.today(),
        "denominator": "Records of this kind that you may open in the owning module. A record you cannot open is not counted.",
        "empty_denominator": "Not measured means there are no eligible records in this scope. It is not zero coverage.",
        "measures": {
            "linked": {
                "label": "Has a live link",
                "means": "At least one link to evidence that is not archived. The evidence may have expired or been replaced, "
                         "and nobody has checked that it supports the record."},
            "current": {
                "label": "Has current proof",
                "means": "At least one link to the current version of an item that has not expired and that a reviewer has "
                         "not returned, rejected or ruled out. It still waits for a reviewer until it is accepted."},
            "accepted": {
                "label": "Accepted by a reviewer",
                "means": "At least one current link that a reviewer of the record accepted for that version. A hash, a link "
                         "count or the metadata health score never makes a link accepted."},
        },
        "exclusions": "Removed links, archived items, replaced versions and expired items never count as current proof.",
    })


@router.get("/api/coverage")
@require_auth
async def api_evidence_coverage(request: Request):
    """For each module and kind of record the caller may open: how many have a live link, current proof, and an accepted
    link. `with_evidence` and `pct` keep their old meaning (a live link); see /api/coverage/definitions."""
    return JSONResponse(coverage_for(request.state.user))


def coverage_for(user) -> dict:
    """The coverage of one person's scope: per module, how many records they may open and how many of those have a
    live link, current proof and an accepted link. Read by the Evidence Vault and by the Command Centre."""
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

    def pct(part, whole):
        return round(part / whole * 100) if whole else None

    coverage = {}
    scope_sql, scope_params = evidence_scope_sql(user)
    today = proof.today()
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
            measured_sql = (
                "SELECT COUNT(DISTINCT t.id), "
                f"COUNT(DISTINCT CASE WHEN {proof.current_sql()} THEN t.id END), "
                f"COUNT(DISTINCT CASE WHEN {proof.accepted_sql()} THEN t.id END)"
                + base
                + " JOIN evidence_links el ON el.entity_id = t.id"
                + " JOIN evidence_items e ON e.id = el.evidence_id"
                + f" WHERE el.module = %s AND el.entity_type IN ({marks})"
                + " AND el.deleted_at IS NULL AND e.status != 'archived'"
            )
            measured_params = [today, today, module, *link_types]
            if target_where:
                measured_sql += " AND " + " AND ".join(target_where)
                measured_params.extend(target_params)
            measured_sql += f" AND {scope_sql}"
            measured_params.extend(scope_params)
            row = db.execute(measured_sql, measured_params).fetchone()
            linked, current, accepted = row[0], row[1], row[2]
            data = coverage.setdefault(module, {"total": 0, "linked": 0, "current": 0, "accepted": 0, "entities": []})
            data["total"] += total
            data["linked"] += linked
            data["current"] += current
            data["accepted"] += accepted
            data["entities"].append({
                "type": entity_type, "total": total, "linked": linked, "current": current, "accepted": accepted,
                "with_evidence": linked, "pct": pct(linked, total),
                "pct_linked": pct(linked, total), "pct_current": pct(current, total), "pct_accepted": pct(accepted, total),
            })
        for data in coverage.values():
            data["with_evidence"] = data["linked"]
            data["pct"] = data["pct_linked"] = pct(data["linked"], data["total"])
            data["pct_current"] = pct(data["current"], data["total"])
            data["pct_accepted"] = pct(data["accepted"], data["total"])
    finally:
        db.close()
    return coverage


@router.get("/api/stats")
@require_auth
async def api_evidence_stats(request: Request):
    """Evidence repository statistics with per-module breakdown. The counts of the work views come from the predicates the
    list uses, so each number is the length of the list it opens."""
    user = request.state.user
    scope_sql, scope_params = evidence_scope_sql(user)
    library = current_library_sql()
    live_link = "el.deleted_at IS NULL"

    def counted(db, view):
        clauses, extra = _view_where(view, user)
        return db.execute(
            f"SELECT COUNT(*) FROM evidence_items e WHERE {scope_sql} AND " + " AND ".join(clauses),
            [*scope_params, *extra]).fetchone()[0]

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
        expiring_soon = counted(db, "expiring")
        total_links = db.execute(
            "SELECT COUNT(*) FROM evidence_links el JOIN evidence_items e ON el.evidence_id = e.id "
            f"WHERE {live_link} AND {library} AND {scope_sql}",
            scope_params,
        ).fetchone()[0]
        needs_filing = counted(db, "needs_filing")
        for_review = counted(db, "for_review")
        review_due = counted(db, "review_due")
        recent = counted(db, "recent")
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
        open_requests = 0
        if user.get("org_id") is not None:
            open_requests = db.execute(
                "SELECT COUNT(*) FROM evidence_requests WHERE org_id = %s AND (assignee_id = %s OR reviewer_id = %s) "
                "AND status IN ('requested', 'submitted', 'in_review', 'returned', 'overdue')",
                (user["org_id"], user["id"], user["id"])).fetchone()[0]
    finally:
        db.close()
    result = {
        "total": total,
        "by_category": {r["category"]: r["c"] for r in by_category},
        "by_module": {r["module"]: r["c"] for r in by_module},
        "expiring_soon": expiring_soon,
        "expiring_7_days": expiring_7,
        "total_links": total_links,
        "unlinked": needs_filing,
        "needs_filing": needs_filing,
        "for_review": for_review,
        "review_due": review_due,
        "recently_updated": recent,
        "open_requests": open_requests,
        "recently_added": [dict(r) for r in recent_rows],
        "archived": archived_count,
    }
    result["can_delete"] = has_capability(user, "evidence.delete")
    result["can_review_links"] = has_capability(user, "evidence.link.review")
    return JSONResponse(result)
