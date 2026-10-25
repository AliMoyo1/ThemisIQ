"""
Sentinel module: Data Protection routes.

FastAPI router ported from the original Flask-based Data Protection Sentinel.
Sentinel is an SPA: one HTML template serves the UI, everything else is JSON API.
All routes are prefixed with /sentinel and guarded by capability-based RBAC.
"""
import asyncio
import csv
import io
import json
import logging
import os
import re
import zipfile
import httpx
from datetime import datetime
from core.timeutils import utcnow, to_dt

log = logging.getLogger("oneforall.sentinel")

from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from config import settings
from core.middleware import require_module, require_capability, check_ai_rate_limit, record_ai_call, log_audit
from core.rbac import has_capability
from core.report_kit import identity, respond
from core.report_kit.identity import download_headers
from core.report_kit.model import Actor
from core.shell_context import shell_ctx
from core.events import (
    emit, SENTINEL_BREACH_CONFIRMED, SENTINEL_BREACH_RESOLVED,
    SENTINEL_DPIA_COMPLETED, SENTINEL_DSR_OVERDUE,
)

from modules.sentinel import data_service as ds, dpia_document, export_reports as exp
from modules.sentinel.record_profiles import RECORDS as RECORD_KINDS, RecordError, get_profile, regulations as record_regulations
from modules.governance.data_service import bu_scope_ids
from core.best_effort import swallowed

router = APIRouter(prefix="/sentinel", tags=["sentinel"])

# Templates instantiated once at module load — not per-request
_tpl_dir = os.path.join(os.path.dirname(__file__), "templates")
_templates = Jinja2Templates(directory=[_tpl_dir, "templates"])


# ── Helper ───────────────────────────────────────────────────────────────────

async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    from core.sanitize import sanitize_dict
    return sanitize_dict(body)


def _own_unit(row):
    return row.get("business_unit_id")


def _ropas_unit(row):
    """A record with no unit of its own (an LIA, a data flow) sits where its RoPA entry sits: organization wide
    when it has none."""
    ropa = ds.get_ropa(row["ropa_id"]) if row.get("ropa_id") else None
    return ropa.get("business_unit_id") if ropa else None


# The record kinds that are reached through a business unit (the registry in governance/entity_scope.py names the
# first four): how to load one, what it is called when it is missing or in another unit, and where it sits.
_UNIT_RECORDS = {
    "ropa": (ds.get_ropa, "RoPA entry not found", _own_unit),
    "dpia": (ds.get_dpia, "DPIA not found", _own_unit),
    "breach": (ds.get_breach, "Breach not found", _own_unit),
    "dsr": (ds.get_dsr, "DSR not found", _own_unit),
    "consent": (ds.get_consent, "Consent record not found", _own_unit),
    "lia": (ds.get_lia, "LIA not found", _ropas_unit),
    "dataflow": (ds.get_dataflow, "Data flow not found", _ropas_unit),
}


def _visible(scope, unit) -> bool:
    """A NULL unit is organization wide; anything else has to sit inside `scope` (bu_scope_ids: None for a super
    administrator, otherwise the caller's unit and the units under it)."""
    return scope is None or unit is None or unit in scope


def _scoped_or_404(request: Request, kind: str, record_id: int) -> dict:
    """The record, when the caller may open it. One in another unit answers exactly like one that is missing."""
    load, missing, unit_of = _UNIT_RECORDS[kind]
    row = load(record_id)
    if row is None or not _visible(bu_scope_ids(request.state.user), unit_of(row)):
        raise HTTPException(404, missing)
    return row


def _check_references(request: Request, data: dict, current: "dict | None" = None) -> None:
    """A body may only file a record under a business unit, or link it to a RoPA entry or DPIA, that the writer may
    open (400 otherwise; an id that is missing answers like one in another unit). A form sends ids as text, so they
    are read as numbers, and an empty value clears the link. `current` is the record being updated: only an
    administrator may take it out of its unit, which would show it to every unit."""
    scope = bu_scope_ids(request.state.user)
    if current is None and data.get("regulation") == "Canada Bill C-11":
        raise HTTPException(400, "Bill C-11 was not enacted. Choose an applicable regulation.")
    if scope is not None and "business_unit_id" in data:
        unit = data["business_unit_id"]
        if unit in (None, ""):
            if current is not None and current.get("business_unit_id") is not None:
                raise HTTPException(400, "Only an administrator can make a record organization wide")
            data["business_unit_id"] = None
        else:
            try:
                unit = int(unit)
            except (TypeError, ValueError):
                unit = None
            if unit not in scope:
                raise HTTPException(400, "Choose a business unit you belong to")
            data["business_unit_id"] = unit
    for field, kind, label in (("ropa_id", "ropa", "RoPA entry"), ("dpia_id", "dpia", "DPIA")):
        if field not in data:
            continue
        target = data[field]
        if target in (None, ""):
            data[field] = None
            continue
        try:
            target = int(target)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Unknown {label}")
        load, _, unit_of = _UNIT_RECORDS[kind]
        row = load(target)
        if row is None or not _visible(scope, unit_of(row)):
            raise HTTPException(400, f"Unknown {label}")
        data[field] = target


# ═════════════════════════════════════════════════════════════════════════════
# SPA INDEX
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
@require_module("sentinel")
async def sentinel_index(request: Request):
    """Serve the Sentinel SPA shell."""
    # AI impact assessments moved to AI Governance (plans/ai-governance/06): an old link still lands on the right page.
    moved = re.fullmatch(r"aiia:(\d{1,9})", request.query_params.get("open", ""))
    if moved:
        return RedirectResponse(f"/ai-governance/assessments/{moved.group(1)}", status_code=302)
    templates = _templates  # use module-level instance

    # Import reference data for the SPA
    try:
        from modules.sentinel.ai_service import (
            REGULATIONS, ACTIVITY_TYPES, DATA_CATEGORIES, SPECIAL_CATEGORIES
        )
    except ImportError:
        REGULATIONS = []
        ACTIVITY_TYPES = []
        DATA_CATEGORIES = []
        SPECIAL_CATEGORIES = []

    user = request.state.user
    # Build current_user dict matching the SPA's expected format
    current_user = {
        "id": user["id"],
        "username": user["username"],
        "full_name": user.get("full_name", ""),
        "email": user.get("email", ""),
        "role": "admin" if any(
            r in user.get("roles", [])
            for r in ("super_admin", "org_admin")
        ) else "user",
        "avatar_initials": user.get("avatar_initials", "??"),
    }
    return templates.TemplateResponse(request, "index.html", {
        "user": user,
        "current_user": current_user,
        "module": "sentinel",
        "regulations": REGULATIONS,
        "activity_types": ACTIVITY_TYPES,
        "data_categories": DATA_CATEGORIES,
        "special_categories": SPECIAL_CATEGORIES,
        "can_draft_jurisdiction": has_capability(user, "sentinel.jurisdiction.draft"),
        "can_approve_jurisdiction": has_capability(user, "sentinel.jurisdiction.approve"),
        "can_ai_law": has_capability(user, "sentinel.ai.assess"),
        "can_manage_breach_obligations": has_capability(user, "sentinel.breach.manage"),
        **shell_ctx(request, active_module="sentinel", active_section="dashboard"),
    })


# SPA catch-all — lets browser refresh on /sentinel/ropa etc. work
_SPA_PAGES = {
    "ropa", "dpia", "breaches", "dsr", "vendors", "consent",
    "reports", "chat", "settings",
    # Previously API-only, now have UI (Item 4)
    "transfers", "retention", "security", "policies", "notices",
    "dataflows", "controllers", "training",
    # New features
    "lia",           # SENT-14: Legitimate Interest Assessments
    "jurisdictions", # Multi-jurisdiction manager
}

@router.get("/{page}", response_class=HTMLResponse)
@require_module("sentinel")
async def sentinel_spa_page(request: Request, page: str):
    if page == "aiia":  # moved to AI Governance
        return RedirectResponse("/ai-governance/assessments", status_code=302)
    if page.startswith("api") or page not in _SPA_PAGES:
        raise HTTPException(404)
    return await sentinel_index(request)


# ═════════════════════════════════════════════════════════════════════════════
# CROSS-MODULE: Active breach status (used by BCM, GRID, ORM dashboards)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/dashboard")
@require_capability("module.sentinel.access")
async def api_dashboard(request: Request):
    """The privacy dashboard's numbers, each with its state, read through the caller's own scope."""
    from modules.sentinel import dashboard_metrics
    response = JSONResponse(dashboard_metrics.stats(request.state.user))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/api/ropa/coverage-gaps")
@require_capability("module.sentinel.access")
async def api_ropa_coverage_gaps(request: Request):
    """Business processes the caller may open that have no processing record connected: the list behind the coverage figure."""
    from modules.sentinel import dashboard_metrics
    from database import get_db as _get_db
    db = _get_db()
    try:
        items = dashboard_metrics.coverage_gaps(db, request.state.user)
    finally:
        db.close()
    response = JSONResponse({"items": items or [], "available": items is not None})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.get("/api/active-breach")
@require_module("sentinel")
async def api_active_breach(request: Request):
    """
    Lightweight endpoint — returns {active: bool, id: int|null, severity: str|null}
    Used by BCM, GRID, and ORM module dashboards to check for active data breaches
    without coupling directly to sentinel data_service.
    """
    from database import get_db as _get_db
    db = _get_db()
    try:
        # Only a breach the caller can open: the banner names it, and the same person is refused its record otherwise.
        unit, unit_params = ds.unit_scope_sql(bu_scope_ids(request.state.user))
        row = db.execute(
            "SELECT id, title, severity FROM sentinel_breaches "
            f"WHERE status NOT IN ('closed','resolved'){unit} "
            "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END "
            "LIMIT 1",
            unit_params,
        ).fetchone()
        if row:
            # Several roles hold the module without sentinel.breach.manage and are shown this banner by BCM and GRID:
            # they learn that a breach is active and how severe, not which one (both banners fall back to generic text).
            may_open = has_capability(request.state.user, "sentinel.breach.manage")
            return JSONResponse({
                "active": True,
                "id": row["id"] if may_open else None,
                "title": row["title"] if may_open else None,
                "severity": row["severity"],
            })
        return JSONResponse({"active": False, "id": None, "title": None, "severity": None})
    except Exception:
        swallowed("api_active_breach (sentinel_breaches)")
        return JSONResponse({"active": False, "id": None, "title": None, "severity": None})
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# STATS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/stats")
@require_capability("module.sentinel.access")
async def api_stats(request: Request):
    return JSONResponse(ds.get_stats(bu_scope=bu_scope_ids(request.state.user)))


# ═════════════════════════════════════════════════════════════════════════════
# ROPA
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/ropa")
@require_capability("module.sentinel.access")
async def api_ropa_list(request: Request):
    entries = ds.list_ropa(
        search=request.query_params.get("q"),
        regulation=request.query_params.get("regulation"),
        status=request.query_params.get("status"),
        risk=request.query_params.get("risk"),
        bu_scope=bu_scope_ids(request.state.user),
    )
    return JSONResponse(entries)


@router.get("/api/record-profile/{record}")
@require_capability("module.sentinel.access")
async def api_record_profile(request: Request, record: str):
    """Field definitions and researched legal references for the selected regime."""
    if record not in RECORD_KINDS:
        raise HTTPException(404, "Unknown record type")
    regulation = (request.query_params.get("regulation") or "").strip()[:64] or ds._primary_jurisdiction_key()
    body = get_profile(record, regulation).to_json()
    body["regulations"] = record_regulations()
    response = JSONResponse(body)
    response.headers["Cache-Control"] = "private, max-age=300"
    return response


@router.post("/api/ropa", status_code=201)
@require_capability("sentinel.ropa.manage")
async def api_ropa_create(request: Request):
    data = await _json_body(request)
    _check_references(request, data)
    try:
        new_id = ds.create_ropa(data, business_unit_id=request.state.user.get("business_unit_id"))
    except RecordError as exc:
        raise HTTPException(422, str(exc)) from None
    entry = ds.get_ropa(new_id)
    return JSONResponse(entry, status_code=201)


@router.get("/api/ropa/{ropa_id}")
@require_capability("module.sentinel.access")
async def api_ropa_get(request: Request, ropa_id: int):
    return JSONResponse(_scoped_or_404(request, "ropa", ropa_id))


@router.put("/api/ropa/{ropa_id}")
@require_capability("sentinel.ropa.manage")
async def api_ropa_update(request: Request, ropa_id: int):
    current = _scoped_or_404(request, "ropa", ropa_id)
    data = await _json_body(request)
    _check_references(request, data, current)
    try:
        ds.update_ropa(ropa_id, data)
    except RecordError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse(ds.get_ropa(ropa_id))


@router.delete("/api/ropa/{ropa_id}")
@require_capability("sentinel.ropa.manage")
async def api_ropa_delete(request: Request, ropa_id: int):
    _scoped_or_404(request, "ropa", ropa_id)
    try:
        ds.delete_ropa(ropa_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return JSONResponse({"ok": True})


@router.post("/api/ropa/{ropa_id}/spawn-dpia", status_code=201)
@require_capability("sentinel.dpia.manage")
async def api_spawn_dpia_from_ropa(request: Request, ropa_id: int):
    ropa = _scoped_or_404(request, "ropa", ropa_id)
    if ropa.get("dpia_id"):
        raise HTTPException(409, "This activity already has a linked DPIA.")
    def _str(val):
        if isinstance(val, (list, dict)):
            return json.dumps(val)
        return val or ""

    dpia_data = {
        "title": f"DPIA: {ropa.get('processing_name', '')}",
        "status": "draft",
        "regulation": ropa.get("regulation", "GDPR"),
        "activity_desc": _str(ropa.get("purpose", "")),
        "purpose": _str(ropa.get("purpose", "")),
        "legal_basis": _str(ropa.get("legal_basis", "")),
        "data_categories": _str(ropa.get("data_categories", "")),
        "special_cats": _str(ropa.get("special_categories", "")),
        "data_subjects": _str(ropa.get("data_subjects", "")),
        "subject_count": _str(ropa.get("subject_count", "")),
        "retention": _str(ropa.get("retention_period", "")),
        "systems": _str(ropa.get("systems", "")),
        "processors": _str(ropa.get("processors", "")),
        "intl_transfer": _str(ropa.get("intl_transfers", "")),
        "transfer_dest": _str(ropa.get("transfer_dest", "")),
        "controller_name": _str(ropa.get("controller_name", "")),
        "dpo_name": _str(ropa.get("dpo_name", "")),
        "dpo_email": _str(ropa.get("dpo_email", "")),
        "ropa_id": ropa_id,
    }
    new_id = ds.create_dpia(dpia_data, business_unit_id=ropa.get("business_unit_id"))
    ds.update_ropa(ropa_id, {"dpia_id": new_id})
    dpia = ds.get_dpia(new_id)
    return JSONResponse({"ok": True, "dpia_id": new_id, "dpia": dpia}, status_code=201)


# ═════════════════════════════════════════════════════════════════════════════
# DPIA
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/dpias")
@require_capability("sentinel.dpia.manage")
async def api_dpia_list(request: Request):
    dpias = ds.list_dpias(
        search=request.query_params.get("q"),
        regulation=request.query_params.get("regulation"),
        status=request.query_params.get("status"),
        bu_scope=bu_scope_ids(request.state.user),
    )
    return JSONResponse(dpias)


@router.post("/api/dpias", status_code=201)
@require_capability("sentinel.dpia.manage")
async def api_dpia_create(request: Request):
    data = await _json_body(request)
    _check_references(request, data)
    ropa = ds.get_ropa(data["ropa_id"]) if data.get("ropa_id") else None
    try:
        new_id = ds.create_dpia(data, business_unit_id=(ropa.get("business_unit_id") if ropa else
                                                       request.state.user.get("business_unit_id")))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return JSONResponse(ds.get_dpia(new_id), status_code=201)


@router.get("/api/dpias/{dpia_id}")
@require_capability("sentinel.dpia.manage")
async def api_dpia_get(request: Request, dpia_id: int):
    return JSONResponse(_scoped_or_404(request, "dpia", dpia_id))


@router.get("/api/dpias/{dpia_id}/document")
@require_capability("sentinel.dpia.manage")
async def api_dpia_document(request: Request, dpia_id: int):
    """Export one DPIA through the same scoped read as its detail page."""
    dpia = _scoped_or_404(request, "dpia", dpia_id)
    fmt = respond.format_of(request)
    if fmt is None:
        raise HTTPException(400, "Choose pdf or xlsx")
    user = request.state.user
    report = dpia_document.build(user, dpia)
    reference = dpia.get("ref_number") or f"dpia_{dpia_id}"
    stem = f"ThemisIQ_privacy_{reference}"
    response = await respond.download(report, fmt, stem)
    from modules.evidence import generated_records
    from starlette.concurrency import run_in_threadpool
    vault_state, vault_id = await run_in_threadpool(
        generated_records.file_record, user, "sentinel", "dpia", dpia_id, report, fmt, response.body, stem)
    response.headers["X-ThemisIQ-Vault-Record"] = str(vault_id)
    response.headers["X-ThemisIQ-Vault-Status"] = vault_state
    log_audit(user, "sentinel", "dpia_exported", entity_type="dpia", entity_id=dpia_id,
              ip=respond.client_ip(request), details=f"ref={reference}; format={fmt}; tier={report.meta.tier}; vault={vault_id}; {vault_state}")
    return response


@router.put("/api/dpias/{dpia_id}")
@require_capability("sentinel.dpia.manage")
async def api_dpia_update(request: Request, dpia_id: int):
    current = _scoped_or_404(request, "dpia", dpia_id)
    data = await _json_body(request)
    _check_references(request, data, current)
    try:
        ds.update_dpia(dpia_id, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None

    # Emit DPIA completed event when status changes to completed/approved
    new_status = (data.get("status") or "").lower()
    previous_status = (current.get("status") or "").lower()
    if new_status in ("completed", "approved") and previous_status not in ("completed", "approved"):
        dpia = ds.get_dpia(dpia_id)
        emit(
            SENTINEL_DPIA_COMPLETED,
            source_module="sentinel",
            entity_type="dpia",
            entity_id=dpia_id,
            payload={
                "title": dpia.get("title", "") if dpia else "",
                "risk_level": (dpia.get("residual_risk") or dpia.get("overall_risk") or "") if dpia else "",
                "risk_basis": ("residual" if dpia.get("residual_risk") else "overall") if dpia else "overall",
                "recommendations": (dpia.get("mitigations") or "") if dpia else "",
                "findings": dpia.get("findings", "") if dpia else "",
            },
            user_id=request.state.user["id"],
        )
    return JSONResponse(ds.get_dpia(dpia_id))


@router.delete("/api/dpias/{dpia_id}")
@require_capability("sentinel.dpia.manage")
async def api_dpia_delete(request: Request, dpia_id: int):
    _scoped_or_404(request, "dpia", dpia_id)
    ds.delete_dpia(dpia_id)
    return JSONResponse({"ok": True})


@router.post("/api/dpias/{dpia_id}/link-ropa")
@require_capability("sentinel.dpia.manage")
async def api_dpia_link_ropa(request: Request, dpia_id: int):
    _scoped_or_404(request, "dpia", dpia_id)
    data = await _json_body(request)
    ropa_id = data.get("ropa_id")
    if not ropa_id:
        raise HTTPException(400, "ropa_id required")
    _scoped_or_404(request, "ropa", int(ropa_id))
    ok = ds.link_dpia_to_ropa(dpia_id, int(ropa_id))
    if not ok:
        raise HTTPException(409, "RoPA is already linked to a different DPIA.")
    return JSONResponse({"ok": True, "dpia": ds.get_dpia(dpia_id)})


# ═════════════════════════════════════════════════════════════════════════════
# BREACHES
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/breaches")
@require_capability("sentinel.breach.manage")
async def api_breach_list(request: Request):
    return JSONResponse(ds.list_breaches(
        search=request.query_params.get("q"),
        status=request.query_params.get("status"),
        severity=request.query_params.get("severity"),
        bu_scope=bu_scope_ids(request.state.user),
    ))


@router.post("/api/breaches", status_code=201)
@require_capability("sentinel.breach.manage")
async def api_breach_create(request: Request):
    data = await _json_body(request)
    _check_references(request, data)
    new_id = ds.create_breach(data, business_unit_id=request.state.user.get("business_unit_id"))

    # Emit breach confirmed event
    emit(
        SENTINEL_BREACH_CONFIRMED,
        source_module="sentinel",
        entity_type="breach",
        entity_id=new_id,
        payload={
            "title": data.get("title", ""),
            "severity": data.get("severity", ""),
            "category": data.get("category", ""),
            "affected_records": data.get("affected_records", 0),
            "description": data.get("description", ""),
            "regulation": data.get("regulation") or settings.DEFAULT_REGULATION,
            "active_jurisdictions": [j["jurisdiction_key"] for j in ds.get_active_jurisdictions()],
        },
        user_id=request.state.user["id"],
    )
    return JSONResponse(ds.get_breach(new_id), status_code=201)


@router.get("/api/breaches/{breach_id}")
@require_capability("sentinel.breach.manage")
async def api_breach_get(request: Request, breach_id: int):
    return JSONResponse(_scoped_or_404(request, "breach", breach_id))


@router.put("/api/breaches/{breach_id}")
@require_capability("sentinel.breach.manage")
async def api_breach_update(request: Request, breach_id: int):
    current = _scoped_or_404(request, "breach", breach_id)
    data = await _json_body(request)
    _check_references(request, data, current)
    ds.update_breach(breach_id, data)

    # Emit events based on status transition
    new_status = (data.get("status") or "").lower()
    breach = ds.get_breach(breach_id)
    if new_status == "confirmed":
        emit(
            SENTINEL_BREACH_CONFIRMED,
            source_module="sentinel",
            entity_type="breach",
            entity_id=breach_id,
            payload={
                "title": breach.get("title", "") if breach else "",
                "severity": breach.get("severity", "") if breach else "",
                "affected_records": breach.get("affected_records", 0) if breach else 0,
                "regulation": (breach.get("regulation") if breach else None) or settings.DEFAULT_REGULATION,
                "active_jurisdictions": [j["jurisdiction_key"] for j in ds.get_active_jurisdictions()],
            },
            user_id=request.state.user["id"],
        )
    elif new_status in ("closed", "resolved", "contained"):
        emit(
            SENTINEL_BREACH_RESOLVED,
            source_module="sentinel",
            entity_type="breach",
            entity_id=breach_id,
            payload={
                "title": breach.get("title", "") if breach else "",
                "severity": breach.get("severity", "") if breach else "",
                "resolution_notes": data.get("resolution_notes", ""),
                "closed_status": new_status,
            },
            user_id=request.state.user["id"],
        )
    return JSONResponse(breach)


@router.delete("/api/breaches/{breach_id}")
@require_capability("sentinel.breach.manage")
async def api_breach_delete(request: Request, breach_id: int):
    _scoped_or_404(request, "breach", breach_id)
    ds.delete_breach(breach_id)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# DSR (Data Subject Requests)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/dsrs")
@require_capability("sentinel.dsr.manage")
async def api_dsr_list(request: Request):
    return JSONResponse(ds.list_dsrs(
        search=request.query_params.get("q"),
        status=request.query_params.get("status"),
        request_type=request.query_params.get("type"),
        bu_scope=bu_scope_ids(request.state.user),
    ))


@router.post("/api/dsrs", status_code=201)
@require_capability("sentinel.dsr.manage")
async def api_dsr_create(request: Request):
    data = await _json_body(request)
    _check_references(request, data)
    data["business_unit_id"] = request.state.user.get("business_unit_id")
    new_id = ds.create_dsr(data)
    return JSONResponse(ds.get_dsr(new_id), status_code=201)


@router.get("/api/dsrs/{dsr_id}")
@require_capability("sentinel.dsr.manage")
async def api_dsr_get(request: Request, dsr_id: int):
    return JSONResponse(_scoped_or_404(request, "dsr", dsr_id))


@router.put("/api/dsrs/{dsr_id}")
@require_capability("sentinel.dsr.manage")
async def api_dsr_update(request: Request, dsr_id: int):
    current = _scoped_or_404(request, "dsr", dsr_id)
    data = await _json_body(request)
    _check_references(request, data, current)
    ds.update_dsr(dsr_id, data)

    # Check if DSR is now overdue and emit event
    dsr = ds.get_dsr(dsr_id)
    if dsr:
        deadline = dsr.get("deadline_date") or ""
        status = (dsr.get("status") or "").lower()
        if deadline and status not in ("completed", "closed"):
            try:
                due = to_dt(deadline[:10])
                if due < utcnow():
                    emit(
                        SENTINEL_DSR_OVERDUE,
                        source_module="sentinel",
                        entity_type="dsr",
                        entity_id=dsr_id,
                        payload={
                            "subject_name": dsr.get("subject_name", ""),
                            "request_type": dsr.get("request_type", ""),
                            "deadline": deadline,
                            "days_overdue": (utcnow() - due).days,
                        },
                        user_id=request.state.user["id"],
                    )
            except (ValueError, TypeError):
                pass
    return JSONResponse(ds.get_dsr(dsr_id))


@router.delete("/api/dsrs/{dsr_id}")
@require_capability("sentinel.dsr.manage")
async def api_dsr_delete(request: Request, dsr_id: int):
    _scoped_or_404(request, "dsr", dsr_id)
    ds.delete_dsr(dsr_id)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# VENDORS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/vendors")
@require_capability("sentinel.vendor.manage")
async def api_vendor_list(request: Request):
    return JSONResponse(ds.list_vendors(
        search=request.query_params.get("q"),
        risk=request.query_params.get("risk"),
        dpa_status=request.query_params.get("dpa_status"),
    ))


@router.post("/api/vendors", status_code=201)
@require_capability("sentinel.vendor.manage")
async def api_vendor_create(request: Request):
    data = await _json_body(request)
    new_id = ds.create_vendor(data)
    vendor = ds.get_vendor(new_id)
    emit("vendor.created", source_module="sentinel", entity_type="vendor", entity_id=new_id,
         payload={"name": vendor.get("name", ""), "canonical_id": vendor.get("canonical_id"),
                  "source_module": "sentinel"},
         user_id=request.state.user["id"])
    return JSONResponse(vendor, status_code=201)


@router.get("/api/vendors/{vendor_id}")
@require_capability("sentinel.vendor.manage")
async def api_vendor_get(request: Request, vendor_id: int):
    v = ds.get_vendor(vendor_id)
    if not v:
        raise HTTPException(404, "Vendor not found")
    return JSONResponse(v)


@router.put("/api/vendors/{vendor_id}")
@require_capability("sentinel.vendor.manage")
async def api_vendor_update(request: Request, vendor_id: int):
    data = await _json_body(request)
    ds.update_vendor(vendor_id, data)
    return JSONResponse(ds.get_vendor(vendor_id))


@router.delete("/api/vendors/{vendor_id}")
@require_capability("sentinel.vendor.manage")
async def api_vendor_delete(request: Request, vendor_id: int):
    ds.delete_vendor(vendor_id)
    return JSONResponse({"ok": True})


@router.get("/api/vendors/{vendor_id}/cross-module")
@require_capability("sentinel.vendor.manage")
async def api_vendor_cross_module(request: Request, vendor_id: int):
    v = ds.get_vendor(vendor_id)
    if not v or not v.get("canonical_id"):
        return JSONResponse({"modules": {}, "flags": [], "canonical_id": None})
    from core.vendor_link import get_cross_module_profile
    from database import get_db
    db = get_db()
    try:
        return JSONResponse(get_cross_module_profile(db, v["canonical_id"], request.state.user))
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# PRIVACY NOTICES
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/notices")
@require_capability("sentinel.privacy_notice.manage")
async def api_notice_list(request: Request):
    return JSONResponse(ds.list_notices())


@router.post("/api/notices", status_code=201)
@require_capability("sentinel.privacy_notice.manage")
async def api_notice_create(request: Request):
    data = await _json_body(request)
    new_id = ds.create_notice(data)
    return JSONResponse(ds.get_notice(new_id), status_code=201)


@router.get("/api/notices/{notice_id}")
@require_capability("sentinel.privacy_notice.manage")
async def api_notice_get(request: Request, notice_id: int):
    n = ds.get_notice(notice_id)
    if not n:
        raise HTTPException(404, "Notice not found")
    return JSONResponse(n)


@router.put("/api/notices/{notice_id}")
@require_capability("sentinel.privacy_notice.manage")
async def api_notice_update(request: Request, notice_id: int):
    data = await _json_body(request)
    ds.update_notice(notice_id, data)
    return JSONResponse(ds.get_notice(notice_id))


@router.delete("/api/notices/{notice_id}")
@require_capability("sentinel.privacy_notice.manage")
async def api_notice_delete(request: Request, notice_id: int):
    ds.delete_notice(notice_id)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# CONSENT RECORDS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/consent")
@require_capability("sentinel.consent.manage")
async def api_consent_list(request: Request):
    return JSONResponse(ds.list_consent(
        search=request.query_params.get("q"),
        status=request.query_params.get("status"),
        bu_scope=bu_scope_ids(request.state.user),
    ))


@router.post("/api/consent", status_code=201)
@require_capability("sentinel.consent.manage")
async def api_consent_create(request: Request):
    data = await _json_body(request)
    _check_references(request, data)
    data["business_unit_id"] = request.state.user.get("business_unit_id")  # filed under its creator's unit, as a DSR is
    new_id = ds.create_consent(data)
    return JSONResponse(ds.get_consent(new_id), status_code=201)


@router.get("/api/consent/{consent_id}")
@require_capability("sentinel.consent.manage")
async def api_consent_get(request: Request, consent_id: int):
    return JSONResponse(_scoped_or_404(request, "consent", consent_id))


@router.put("/api/consent/{consent_id}")
@require_capability("sentinel.consent.manage")
async def api_consent_update(request: Request, consent_id: int):
    current = _scoped_or_404(request, "consent", consent_id)
    data = await _json_body(request)
    _check_references(request, data, current)
    ds.update_consent(consent_id, data)
    return JSONResponse(ds.get_consent(consent_id))


@router.delete("/api/consent/{consent_id}")
@require_capability("sentinel.consent.manage")
async def api_consent_delete(request: Request, consent_id: int):
    _scoped_or_404(request, "consent", consent_id)
    ds.delete_consent(consent_id)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# CONTROLLERS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/controllers")
@require_capability("sentinel.controller.manage")
async def api_controller_list(request: Request):
    return JSONResponse(ds.list_controllers())


@router.post("/api/controllers", status_code=201)
@require_capability("sentinel.controller.manage")
async def api_controller_create(request: Request):
    data = await _json_body(request)
    try:
        new_id = ds.create_controller(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse(ds.get_controller(new_id), status_code=201)


@router.get("/api/controllers/{ctrl_id}")
@require_capability("sentinel.controller.manage")
async def api_controller_get(request: Request, ctrl_id: int):
    c = ds.get_controller(ctrl_id)
    if not c:
        raise HTTPException(404, "Controller not found")
    return JSONResponse(c)


@router.put("/api/controllers/{ctrl_id}")
@require_capability("sentinel.controller.manage")
async def api_controller_update(request: Request, ctrl_id: int):
    data = await _json_body(request)
    try:
        ds.update_controller(ctrl_id, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse(ds.get_controller(ctrl_id))


@router.delete("/api/controllers/{ctrl_id}")
@require_capability("sentinel.controller.manage")
async def api_controller_delete(request: Request, ctrl_id: int):
    ds.delete_controller(ctrl_id)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# TRANSFERS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/transfers")
@require_capability("sentinel.transfer.manage")
async def api_transfer_list(request: Request):
    return JSONResponse(ds.list_transfers())


@router.post("/api/transfers", status_code=201)
@require_capability("sentinel.transfer.manage")
async def api_transfer_create(request: Request):
    data = await _json_body(request)
    new_id = ds.create_transfer(data)
    return JSONResponse(ds.get_transfer(new_id), status_code=201)


@router.get("/api/transfers/{tid}")
@require_capability("sentinel.transfer.manage")
async def api_transfer_get(request: Request, tid: int):
    t = ds.get_transfer(tid)
    if not t:
        raise HTTPException(404, "Transfer not found")
    return JSONResponse(t)


@router.put("/api/transfers/{tid}")
@require_capability("sentinel.transfer.manage")
async def api_transfer_update(request: Request, tid: int):
    data = await _json_body(request)
    ds.update_transfer(tid, data)
    return JSONResponse(ds.get_transfer(tid))


@router.delete("/api/transfers/{tid}")
@require_capability("sentinel.transfer.manage")
async def api_transfer_delete(request: Request, tid: int):
    ds.delete_transfer(tid)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# RETENTION SCHEDULES
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/retention")
@require_capability("sentinel.retention.manage")
async def api_retention_list(request: Request):
    return JSONResponse(ds.list_retention())


@router.post("/api/retention", status_code=201)
@require_capability("sentinel.retention.manage")
async def api_retention_create(request: Request):
    data = await _json_body(request)
    new_id = ds.create_retention(data)
    return JSONResponse(ds.get_retention(new_id), status_code=201)


@router.get("/api/retention/{rid}")
@require_capability("sentinel.retention.manage")
async def api_retention_get(request: Request, rid: int):
    r = ds.get_retention(rid)
    if not r:
        raise HTTPException(404, "Retention schedule not found")
    return JSONResponse(r)


@router.put("/api/retention/{rid}")
@require_capability("sentinel.retention.manage")
async def api_retention_update(request: Request, rid: int):
    data = await _json_body(request)
    ds.update_retention(rid, data)
    return JSONResponse(ds.get_retention(rid))


@router.delete("/api/retention/{rid}")
@require_capability("sentinel.retention.manage")
async def api_retention_delete(request: Request, rid: int):
    ds.delete_retention(rid)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# SECURITY MEASURES
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/security")
@require_capability("module.sentinel.access")
async def api_security_list(request: Request):
    return JSONResponse(ds.list_security())


@router.post("/api/security", status_code=201)
@require_capability("sentinel.ropa.manage")
async def api_security_create(request: Request):
    data = await _json_body(request)
    new_id = ds.create_security(data)
    return JSONResponse(ds.get_security(new_id), status_code=201)


@router.get("/api/security/{sid}")
@require_capability("module.sentinel.access")
async def api_security_get(request: Request, sid: int):
    s = ds.get_security(sid)
    if not s:
        raise HTTPException(404, "Security measure not found")
    return JSONResponse(s)


@router.put("/api/security/{sid}")
@require_capability("sentinel.ropa.manage")
async def api_security_update(request: Request, sid: int):
    data = await _json_body(request)
    ds.update_security(sid, data)
    return JSONResponse(ds.get_security(sid))


@router.delete("/api/security/{sid}")
@require_capability("sentinel.ropa.manage")
async def api_security_delete(request: Request, sid: int):
    ds.delete_security(sid)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# POLICIES
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/policies")
@require_capability("module.sentinel.access")
async def api_policies_list(request: Request):
    return JSONResponse(ds.list_policies(
        search=request.query_params.get("q"),
        status=request.query_params.get("status"),
        policy_type=request.query_params.get("type"),
    ))


@router.post("/api/policies", status_code=201)
@require_capability("sentinel.ropa.manage")
async def api_policies_create(request: Request):
    data = await _json_body(request)
    new_id = ds.create_policy(data)
    return JSONResponse(ds.get_policy(new_id), status_code=201)


@router.get("/api/policies/{policy_id}")
@require_capability("module.sentinel.access")
async def api_policies_get(request: Request, policy_id: int):
    p = ds.get_policy(policy_id)
    if not p:
        raise HTTPException(404, "Policy not found")
    return JSONResponse(p)


@router.put("/api/policies/{policy_id}")
@require_capability("sentinel.ropa.manage")
async def api_policies_update(request: Request, policy_id: int):
    data = await _json_body(request)
    ds.update_policy(policy_id, data)
    return JSONResponse(ds.get_policy(policy_id))


@router.delete("/api/policies/{policy_id}")
@require_capability("sentinel.ropa.manage")
async def api_policies_delete(request: Request, policy_id: int):
    ds.delete_policy(policy_id)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# TRAINING
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/training")
@require_capability("module.sentinel.access")
async def api_training_list(request: Request):
    return JSONResponse(ds.list_training(
        search=request.query_params.get("q"),
        department=request.query_params.get("department"),
    ))


@router.post("/api/training", status_code=201)
@require_capability("sentinel.ropa.manage")
async def api_training_create(request: Request):
    data = await _json_body(request)
    new_id = ds.create_training(data)
    return JSONResponse(ds.get_training(new_id), status_code=201)


@router.get("/api/training/{training_id}")
@require_capability("module.sentinel.access")
async def api_training_get(request: Request, training_id: int):
    t = ds.get_training(training_id)
    if not t:
        raise HTTPException(404, "Training record not found")
    return JSONResponse(t)


@router.put("/api/training/{training_id}")
@require_capability("sentinel.ropa.manage")
async def api_training_update(request: Request, training_id: int):
    data = await _json_body(request)
    ds.update_training(training_id, data)
    return JSONResponse(ds.get_training(training_id))


@router.delete("/api/training/{training_id}")
@require_capability("sentinel.ropa.manage")
async def api_training_delete(request: Request, training_id: int):
    ds.delete_training(training_id)
    return JSONResponse({"ok": True})


@router.post("/api/training/analyse-excel")
@require_capability("sentinel.ropa.manage")
async def api_training_analyse_excel(request: Request, file: UploadFile = File(...)):
    """Accept Excel upload, parse training attendance, bulk-import, return analytics."""
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "openpyxl not installed")

    if not file.filename or not file.filename.lower().endswith(('.xlsx', '.xls', '.xlsm')):
        raise HTTPException(400, "Please upload an Excel file (.xlsx / .xls)")

    contents = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
    except Exception as e:
        raise HTTPException(400, f"Could not read Excel file: {e}")

    ws = wb.active

    # Auto-detect header row
    headers = []
    header_row_idx = None
    for row_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
        if any(c for c in row):
            headers = [str(c).strip() if c is not None else '' for c in row]
            header_row_idx = row_idx
            break

    if not headers:
        raise HTTPException(400, "Excel file appears to be empty")

    # Normalize headers
    def norm(s):
        return s.lower().replace(' ', '').replace('_', '').replace('-', '').replace('/', '')

    known = {
        'staffname': 'staff_name', 'name': 'staff_name', 'employee': 'staff_name',
        'employeename': 'staff_name', 'staffemail': 'staff_email', 'email': 'staff_email',
        'emailaddress': 'staff_email', 'department': 'department', 'dept': 'department',
        'division': 'department', 'training': 'training_name', 'trainingname': 'training_name',
        'course': 'training_name', 'coursename': 'training_name', 'module': 'training_name',
        'trainingtype': 'training_type', 'type': 'training_type',
        'completiondate': 'completion_date', 'dateofcompletion': 'completion_date',
        'completeddate': 'completion_date', 'date': 'completion_date',
        'expirydate': 'expiry_date', 'expiresdate': 'expiry_date', 'expiry': 'expiry_date',
        'result': 'passed', 'passed': 'passed', 'status': 'passed',
        'score': 'score', 'mark': 'score', 'grade': 'score',
        'certificate': 'certificate_no', 'certificateno': 'certificate_no',
        'certnumber': 'certificate_no', 'trainer': 'trainer', 'provider': 'trainer',
        'trainingprovider': 'trainer', 'regulation': 'regulation',
    }
    header_map = {}
    for i, h in enumerate(headers):
        mapped = known.get(norm(h))
        if mapped:
            header_map[i] = mapped

    # Parse rows
    records = []
    for row in ws.iter_rows(min_row=header_row_idx + 1, values_only=True):
        if not any(c for c in row):
            continue
        rec = {}
        for col_i, val in enumerate(row):
            field = header_map.get(col_i)
            if field and val is not None:
                rec[field] = str(val).strip() if not isinstance(val, (int, float)) else val
        if rec.get('staff_name') or rec.get('training_name'):
            p = str(rec.get('passed', '')).lower()
            rec['passed'] = 1 if p in ('yes', 'passed', 'true', '1', 'complete', 'completed') else 0
            records.append(rec)

    if not records:
        raise HTTPException(400, "No data rows found")

    # Analytics
    from collections import defaultdict
    sessions = defaultdict(list)
    all_staff = set()
    for r in records:
        sn = r.get('training_name', 'Unknown Training')
        staff = r.get('staff_name', 'Unknown')
        sessions[sn].append(r)
        all_staff.add(staff)

    total_staff = len(all_staff)
    session_summary = []
    for session_name, rows in sessions.items():
        attendees = [r.get('staff_name') for r in rows if r.get('passed') or r.get('completion_date')]
        passed_count = sum(1 for r in rows if r.get('passed'))
        attendance_pct = round(len(attendees) / total_staff * 100) if total_staff else 0
        pass_rate = round(passed_count / len(rows) * 100) if rows else 0
        absent = sorted(all_staff - set(attendees))
        session_summary.append({
            "session": session_name, "total_registered": len(rows),
            "attended": len(attendees), "passed": passed_count,
            "absent_count": len(absent), "attendance_pct": attendance_pct,
            "pass_rate": pass_rate, "absent_staff": absent[:20],
        })

    staff_sessions = defaultdict(lambda: {"attended": 0, "passed": 0, "sessions": []})
    for r in records:
        s = r.get('staff_name', 'Unknown')
        staff_sessions[s]["attended"] += 1 if (r.get('passed') or r.get('completion_date')) else 0
        staff_sessions[s]["passed"] += 1 if r.get('passed') else 0
        staff_sessions[s]["sessions"].append(r.get('training_name', ''))

    total_sessions = len(sessions)
    staff_summary = []
    for name, data in sorted(staff_sessions.items()):
        att = data['attended']
        overall_pct = round(att / total_sessions * 100) if total_sessions else 0
        missed = [s for s in sessions if s not in data['sessions']]
        staff_summary.append({
            "name": name, "attended": att, "passed": data['passed'],
            "total_sessions": total_sessions, "attendance_pct": overall_pct,
            "missed_sessions": missed,
        })

    total_possible = len(records)
    total_attended = sum(1 for r in records if r.get('passed') or r.get('completion_date'))
    total_passed = sum(1 for r in records if r.get('passed'))
    overall_attendance = round(total_attended / total_possible * 100) if total_possible else 0
    overall_pass = round(total_passed / total_possible * 100) if total_possible else 0

    # Bulk import
    imported = skipped = 0
    for r in records:
        try:
            ds.create_training(r)
            imported += 1
        except Exception:
            skipped += 1

    return JSONResponse({
        "ok": True,
        "summary": {
            "total_staff": total_staff, "total_sessions": total_sessions,
            "total_records": len(records), "overall_attendance_pct": overall_attendance,
            "overall_pass_rate": overall_pass, "imported": imported,
            "skipped_duplicates": skipped,
        },
        "sessions": sorted(session_summary, key=lambda x: x['attendance_pct']),
        "staff": sorted(staff_summary, key=lambda x: x['attendance_pct']),
        "headers_detected": [h for h in headers if h],
        "mapped_columns": {headers[i]: v for i, v in header_map.items()},
    })


# ═════════════════════════════════════════════════════════════════════════════
# DATA FLOWS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/dataflows")
@require_capability("module.sentinel.access")
async def api_dataflows_list(request: Request):
    return JSONResponse(ds.list_dataflows(bu_scope=bu_scope_ids(request.state.user)))


@router.get("/api/dataflows/{flow_id}")
@require_capability("module.sentinel.access")
async def api_dataflows_detail(request: Request, flow_id: int):
    return JSONResponse(_scoped_or_404(request, "dataflow", flow_id))


@router.post("/api/dataflows", status_code=201)
@require_capability("sentinel.ropa.manage")
async def api_dataflows_create(request: Request):
    data = await _json_body(request)
    _check_references(request, data)
    new_id = ds.create_dataflow(data)
    return JSONResponse({"id": new_id}, status_code=201)


@router.put("/api/dataflows/{flow_id}")
@require_capability("sentinel.ropa.manage")
async def api_dataflows_update(request: Request, flow_id: int):
    _scoped_or_404(request, "dataflow", flow_id)
    data = await _json_body(request)
    _check_references(request, data)
    ds.update_dataflow(flow_id, data)
    return JSONResponse({"ok": True})


@router.delete("/api/dataflows/{flow_id}")
@require_capability("sentinel.ropa.manage")
async def api_dataflows_delete(request: Request, flow_id: int):
    _scoped_or_404(request, "dataflow", flow_id)
    ds.delete_dataflow(flow_id)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/settings")
@require_capability("module.sentinel.access")
async def api_settings_get(request: Request):
    return JSONResponse(ds.get_all_settings())


@router.put("/api/settings")
@require_capability("sentinel.ropa.manage")
async def api_settings_update(request: Request):
    data = await _json_body(request)
    try:
        ds.update_privacy_settings(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/audit")
@require_capability("module.sentinel.access")
async def api_audit_list(request: Request):
    limit = int(request.query_params.get("limit", "200"))
    user = request.state.user
    org_id = None if (user.get("is_super_admin") or user.get("org_id") is None) else user.get("org_id")
    return JSONResponse(ds.list_audit(limit=limit, org_id=org_id))


# ═════════════════════════════════════════════════════════════════════════════
# CALENDAR & COMPLIANCE SCORE
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/compliance-score")
@require_capability("module.sentinel.access")
async def api_compliance_score(request: Request):
    return JSONResponse(ds.get_compliance_score(bu_scope=bu_scope_ids(request.state.user)))


# ═════════════════════════════════════════════════════════════════════════════
# LEGAL BASES (per regulation)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/legal-bases/{regulation}")
@require_capability("module.sentinel.access")
async def api_legal_bases(request: Request, regulation: str):
    try:
        from modules.sentinel.ai_service import LEGAL_BASES
        bases = LEGAL_BASES.get(regulation, LEGAL_BASES.get("GDPR", []))
    except ImportError:
        bases = []
    # Return both formats: list for backward compat, dict for new jurisdiction-aware UI
    return JSONResponse({"regulation": regulation, "bases": bases})


# ═════════════════════════════════════════════════════════════════════════════
# REPORTS, THE AUDIT TRAIL AND THE EVIDENCE PACK
# ═════════════════════════════════════════════════════════════════════════════

AUDIT_EXPORT_LIMIT = 100_000      # the most recent rows of the audit trail that one export carries


@router.get("/api/reports/{kind}")
@require_capability("module.sentinel.access")
async def api_report(request: Request, kind: str):
    """The record of processing activities (`ropa`), the breach register (`breach`) or the privacy compliance score
    (`compliance`) as a document: `?format=pdf` (the default) or `xlsx`. The first two are operational reports and the score is
    the short board report. Each needs the capability that opens the same records on screen."""
    spec = exp.REPORTS.get(kind)
    if spec is None:
        raise HTTPException(404, "Unknown report")
    build, capability, stem = spec
    fmt = respond.format_of(request)
    if fmt is None:
        raise HTTPException(400, "Choose pdf or xlsx")
    user = request.state.user
    if not has_capability(user, capability):
        raise HTTPException(403, "Insufficient permissions")
    report = build(user)
    log_audit(user, "sentinel", "report_export", entity_type="report", ip=respond.client_ip(request),
              details=f"report={kind}; format={fmt}; tier={report.meta.tier}")
    return await respond.download(report, fmt, stem)


@router.get("/api/audit/export")
@require_capability("module.sentinel.access")
async def api_audit_csv(request: Request):
    """The Sentinel audit trail of the caller's organization as CSV, newest first: one row per recorded action. A cell that
    a spreadsheet would read as a formula is written as text."""
    user = request.state.user
    org_id = None if (user.get("is_super_admin") or user.get("org_id") is None) else user.get("org_id")
    columns = ["created_at_utc", "username", "action", "entity_type", "entity_id", "details", "ip_address"]
    keys = ["created_at", "username", "action", "entity_type", "entity_id", "details", "ip_address"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in ds.list_audit(limit=AUDIT_EXPORT_LIMIT, org_id=org_id):
        writer.writerow(identity.csv_row([row.get(k) for k in keys]))
    log_audit(user, "sentinel", "audit_trail_export", entity_type="audit_log", ip=respond.client_ip(request), details="format=csv")
    return Response(buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers=download_headers(identity.safe_filename("ThemisIQ_privacy_audit_trail", "csv", when=utcnow())))


@router.get("/api/audit-export")
@require_capability("module.sentinel.access")
async def api_audit_export(request: Request):
    """A ZIP of JSON data sets. `type` (ropa, breach or compliance) gives that one data set; anything else gives the full
    evidence pack: RoPA, impact assessments, breach log, request log, vendors, policies, audit trail and compliance score.
    The documents (PDF, Excel) are at /api/reports/{kind}.

    Each part needs the capability that opens the same records on screen; the pack used to hand every part to anyone who
    could open the module. A part the caller may not open is left out of the full pack, and the README says so; asking for
    it alone is a 403. Every part is complete: the lists the screens show stop at 500 rows, the pack does not."""
    user = request.state.user
    now = utcnow()
    org = ds.get_all_settings() or {}
    scope = bu_scope_ids(user)
    org_id = None if (user.get("is_super_admin") or user.get("org_id") is None) else user.get("org_id")
    every = exp.EVERYTHING
    score = ds.get_compliance_score(bu_scope=scope)
    # key: (file name in the full pack, file name when asked for alone, what it holds, capability, how it is read)
    parts = {
        "ropa": ("RoPA_Register", "RoPA_Report", "Record of processing activities", "module.sentinel.access",
                 lambda: ds.list_ropa(bu_scope=scope, limit=every)),
        "dpia": ("DPIA_Summary", None, "Impact assessments", "sentinel.dpia.manage",
                 lambda: ds.list_dpias(bu_scope=scope, limit=every)),
        "breach": ("Breach_Log", "Breach_Report", "Breach log", "sentinel.breach.manage",
                   lambda: ds.list_breaches(bu_scope=scope, limit=every)),
        "dsr": ("DSR_Log", None, "Data subject request log", "sentinel.dsr.manage",
                lambda: ds.list_dsrs(bu_scope=scope, limit=every)),
        "vendor": ("Vendor_Register", None, "Vendor register", "sentinel.vendor.manage", lambda: ds.list_vendors(limit=every)),
        "audit": ("Audit_Trail", None, "Audit trail", "module.sentinel.access",
                  lambda: ds.list_audit(limit=AUDIT_EXPORT_LIMIT, org_id=org_id)),
        "policy": ("Policy_Register", None, "Policy register", "module.sentinel.access", lambda: ds.list_policies(limit=every)),
        "compliance": ("Compliance_Score", "Compliance_Score", "Privacy compliance score", "module.sentinel.access", lambda: score),
    }
    kind = request.query_params.get("type")
    alone = kind if kind in ("ropa", "breach", "compliance") else None
    stamp = now.strftime("%Y%m%d")
    included, left_out = [], []
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key in ([alone] if alone else list(parts)):
            stem, single, what, capability, load = parts[key]
            if not has_capability(user, capability):
                if alone:
                    raise HTTPException(403, "Insufficient permissions")
                left_out.append(f"{what} (needs the {capability} permission)")
                continue
            rows = load()
            name = f"{single if alone else stem}_{stamp}.json"
            zf.writestr(name, json.dumps(rows, indent=2, default=str))
            included.append(f"{name}: {what}" + (f", {len(rows)} records" if isinstance(rows, list) else ""))
        readme = [
            ("DATA PROTECTION SENTINEL: " + (parts[alone][2].upper() if alone else "AUDIT EVIDENCE PACK")),
            f"Module: {identity.module_name('sentinel')}",
            f"Generated by: {Actor.of_user(user).describe()}",
            f"Generated: {identity.format_when(now)}",
            f"Organisation: {org.get('org_name') or 'Not recorded'}",
        ]
        if not alone:
            readme += [f"DPO: {org.get('dpo_name') or 'Not recorded'} ({org.get('dpo_email') or 'no email recorded'})",
                       f"Primary regulation: {org.get('primary_regulation') or 'Not recorded'}"]
        readme.append("Overall compliance score: " + (f"{score['overall']}% (Grade {score['grade']})" if score["overall"] is not None
                                                      else "not measured (no part of the score has records to measure)"))
        readme += ["", "Contents:"] + [f"  {line}" for line in included]
        if left_out:
            readme += ["", "Left out, because you do not hold the permission that opens them:"] + [f"  {line}" for line in left_out]
        readme += ["", "The records are those of the business units open to the person who generated this file."]
        zf.writestr("README.txt", "\n".join(readme) + "\n")

    log_audit(user, "sentinel", "evidence_pack_export", entity_type="evidence_pack", ip=respond.client_ip(request),
              details=f"type={alone or 'full'}; parts={len(included)}; left_out={len(left_out)}")
    org_name = org.get("org_name") or "organisation"
    suffix = f"_{alone}" if alone else "_evidence_pack"
    return Response(zip_buf.getvalue(), media_type="application/zip",
                    headers=download_headers(identity.safe_filename(f"ThemisIQ_privacy{suffix}_{org_name}", "zip", when=now)))


# ═════════════════════════════════════════════════════════════════════════════
# AI ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
# LEGITIMATE INTEREST ASSESSMENTS (SENT-14)
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/lia")
@require_capability("module.sentinel.access")
async def api_lia_list(request: Request):
    return JSONResponse(ds.list_lia(
        ropa_id=int(request.query_params["ropa_id"]) if request.query_params.get("ropa_id") else None,
        result=request.query_params.get("result"),
        bu_scope=bu_scope_ids(request.state.user),
    ))


@router.post("/api/lia", status_code=201)
@require_capability("sentinel.ropa.manage")
async def api_lia_create(request: Request):
    data = await _json_body(request)
    _check_references(request, data)
    data["created_by"] = request.state.user["id"]
    new_id = ds.create_lia(data)
    return JSONResponse(ds.get_lia(new_id), status_code=201)


@router.get("/api/lia/{lia_id}")
@require_capability("module.sentinel.access")
async def api_lia_get(request: Request, lia_id: int):
    return JSONResponse(_scoped_or_404(request, "lia", lia_id))


@router.put("/api/lia/{lia_id}")
@require_capability("sentinel.ropa.manage")
async def api_lia_update(request: Request, lia_id: int):
    _scoped_or_404(request, "lia", lia_id)
    data = await _json_body(request)
    _check_references(request, data)
    ds.update_lia(lia_id, data)
    return JSONResponse(ds.get_lia(lia_id))


@router.delete("/api/lia/{lia_id}")
@require_capability("sentinel.ropa.manage")
async def api_lia_delete(request: Request, lia_id: int):
    _scoped_or_404(request, "lia", lia_id)
    ds.delete_lia(lia_id)
    return JSONResponse({"ok": True})


# ═════════════════════════════════════════════════════════════════════════════
# Jurisdiction Management
# ═════════════════════════════════════════════════════════════════════════════

def _law_org(request: Request) -> int:
    org_id = request.state.user.get("org_id")
    if type(org_id) is not int or org_id < 1:
        raise HTTPException(403, "Select an organization before using law monitoring")
    return org_id


@router.get("/api/law-monitor")
@require_capability("module.sentinel.access")
async def api_law_monitor(request: Request):
    from modules.sentinel import living_law
    org_id = _law_org(request)
    return JSONResponse({"cadence": living_law.get_cadence(org_id),
                         "retention_days": living_law.get_retention_days(org_id),
                         "sources": living_law.list_sources(org_id),
                         "uncovered": [row["jurisdiction_key"] for row in ds.get_active_jurisdictions()
                                       if row["jurisdiction_key"] not in {s[0] for s in living_law.SOURCES.values()}],
                         "cost_note": "Source checks and extractive answers use no AI tokens."})


@router.put("/api/law-monitor/cadence")
@require_capability("sentinel.jurisdiction.draft")
@require_module("sentinel")
async def api_law_monitor_cadence(request: Request):
    from modules.sentinel import living_law
    body = await _json_body(request)
    try:
        living_law.set_cadence(_law_org(request), body.get("cadence"), request.state.user["id"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    log_audit(request.state.user, "sentinel", "law_monitor_cadence_updated", details=str(body.get("cadence")))
    return JSONResponse({"ok": True})


@router.put("/api/law-monitor/retention")
@require_capability("sentinel.jurisdiction.approve")
@require_module("sentinel")
async def api_law_monitor_retention(request: Request):
    from modules.sentinel import living_law
    body = await _json_body(request)
    try:
        living_law.set_retention_days(_law_org(request), body.get("days"), request.state.user["id"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    log_audit(request.state.user, "sentinel", "law_capture_retention_updated",
              details=f"review_after_days={body['days']}")
    return JSONResponse({"ok": True})


@router.post("/api/law-monitor/check")
@require_capability("sentinel.jurisdiction.draft")
@require_module("sentinel")
async def api_law_monitor_check(request: Request):
    from modules.sentinel import living_law
    body = await _json_body(request)
    key = body.get("source_key")
    if type(key) is not str or key not in living_law.SOURCES:
        raise HTTPException(422, "Choose a monitored official source")
    org_id = _law_org(request)
    if living_law.checked_within_hour(org_id, key):
        raise HTTPException(429, "This source was checked within the last hour")
    try:
        result = await asyncio.to_thread(living_law.check_source, org_id, key)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    log_audit(request.state.user, "sentinel", "law_source_checked", details=f"source={key}; result={result['result']}")
    return JSONResponse(result)


@router.get("/api/law-monitor/captures/{capture_id}")
@require_capability("module.sentinel.access")
async def api_law_monitor_capture(request: Request, capture_id: int):
    from modules.sentinel import living_law
    try:
        return JSONResponse(living_law.capture_detail(_law_org(request), capture_id),
                            headers={"Cache-Control": "private, no-store"})
    except LookupError:
        raise HTTPException(404, "Capture not found") from None


@router.get("/api/law-monitor/captures/{capture_id}/impact")
@require_capability("module.sentinel.access")
async def api_law_monitor_impact(request: Request, capture_id: int):
    from modules.sentinel import living_law
    try:
        result = living_law.impact_summary(_law_org(request), capture_id,
                                           bu_scope_ids(request.state.user))
    except LookupError:
        raise HTTPException(404, "Capture not found") from None
    return JSONResponse(result, headers={"Cache-Control": "private, no-store"})


@router.post("/api/law-monitor/captures/{capture_id}/review")
@require_capability("sentinel.jurisdiction.approve")
@require_module("sentinel")
async def api_law_monitor_review(request: Request, capture_id: int):
    from modules.sentinel import living_law
    body = await _json_body(request)
    try:
        living_law.review_capture(_law_org(request), capture_id, request.state.user["id"],
                                  body.get("decision"), str(body.get("note") or ""))
    except LookupError:
        raise HTTPException(404, "Pending capture not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    log_audit(request.state.user, "sentinel", "law_source_reviewed", entity_type="law_capture",
              entity_id=capture_id, details=str(body.get("decision")))
    return JSONResponse({"ok": True})


@router.post("/api/law-monitor/captures/{capture_id}/hold")
@require_capability("sentinel.jurisdiction.approve")
@require_module("sentinel")
async def api_law_monitor_hold(request: Request, capture_id: int):
    from modules.sentinel import living_law
    body = await _json_body(request)
    try:
        living_law.set_hold(_law_org(request), capture_id, request.state.user["id"],
                            body.get("enabled"), body.get("reason"))
    except LookupError:
        raise HTTPException(404, "Capture not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    log_audit(request.state.user, "sentinel", "law_capture_hold_changed", entity_type="law_capture",
              entity_id=capture_id, details=f"enabled={body['enabled']}")
    return JSONResponse({"ok": True})


@router.post("/api/ask-law")
@require_capability("module.sentinel.access")
async def api_ask_law(request: Request):
    from modules.sentinel import living_law
    body = await _json_body(request)
    question = str(body.get("question") or "")
    try:
        result = living_law.ask(_law_org(request), question, body.get("jurisdiction"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if body.get("ai_draft") is True and result["citations"]:
        if not has_capability(request.state.user, "sentinel.ai.assess"):
            raise HTTPException(403, "AI drafting requires privacy specialist access")
        uid = str(request.state.user["id"])
        if not check_ai_rate_limit(uid):
            result["draft_status"] = "AI rate limit reached; showing cited passages instead."
        else:
            record_ai_call(uid)
            try:
                result = await asyncio.to_thread(living_law.draft_answer, question, result)
            except (RuntimeError, ValueError, httpx.HTTPError) as exc:
                log.warning("Sentinel law draft unavailable: %s", type(exc).__name__)
                result["draft_status"] = "AI draft unavailable or not approved by policy; showing cited passages instead."
    return JSONResponse(result, headers={"Cache-Control": "private, no-store"})


@router.get("/api/jurisdiction-cards")
@require_capability("module.sentinel.access")
async def api_jurisdiction_cards(request: Request):
    from modules.sentinel import obligations
    return JSONResponse({"items": obligations.list_cards(request.state.user)})


@router.post("/api/jurisdiction-cards", status_code=201)
@require_capability("sentinel.jurisdiction.draft")
async def api_jurisdiction_card_create(request: Request):
    from modules.sentinel import obligations
    try:
        card_id = obligations.create_card(await _json_body(request), request.state.user)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse({"id": card_id}, status_code=201)


@router.post("/api/jurisdiction-cards/{card_id}/approve")
@require_capability("sentinel.jurisdiction.approve")
async def api_jurisdiction_card_approve(request: Request, card_id: int):
    from modules.sentinel import obligations
    try:
        obligations.approve_card(card_id, request.state.user)
    except LookupError:
        raise HTTPException(404, "Draft rule card not found") from None
    return JSONResponse({"ok": True})


@router.get("/api/breaches/{breach_id}/obligations")
@require_capability("module.sentinel.access")
async def api_breach_obligations(request: Request, breach_id: int):
    from modules.sentinel import obligations
    try:
        items = obligations.list_obligations(breach_id, request.state.user)
    except LookupError:
        raise HTTPException(404, "Breach not found") from None
    return JSONResponse({"items": items})


@router.post("/api/breaches/{breach_id}/obligations", status_code=201)
@require_capability("sentinel.breach.manage")
async def api_breach_obligation_create(request: Request, breach_id: int):
    from modules.sentinel import obligations
    try:
        obligation_id = obligations.add_obligation(breach_id, await _json_body(request), request.state.user)
    except LookupError:
        raise HTTPException(404, "Breach or rule card not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse({"id": obligation_id}, status_code=201)


@router.post("/api/breach-obligations/{obligation_id}/decision")
@require_capability("sentinel.breach.manage")
async def api_breach_obligation_decide(request: Request, obligation_id: int):
    from modules.sentinel import obligations
    body = await _json_body(request)
    try:
        obligations.decide_obligation(obligation_id, body.get("decision"), body.get("reason") or "",
                                      request.state.user)
    except LookupError:
        raise HTTPException(404, "Obligation not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse({"ok": True})


@router.put("/api/breach-obligations/{obligation_id}/facts")
@require_capability("sentinel.breach.manage")
async def api_breach_obligation_facts(request: Request, obligation_id: int):
    from modules.sentinel import obligations
    try:
        obligations.update_obligation_facts(obligation_id, await _json_body(request), request.state.user)
    except LookupError:
        raise HTTPException(404, "Obligation not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return JSONResponse({"ok": True})


@router.get("/api/jurisdictions/rules")
@require_module("sentinel")
async def api_jurisdiction_rules(request: Request):
    """All known jurisdictions from the registry, grouped by region."""
    from modules.sentinel.jurisdictions import list_jurisdictions, jurisdictions_by_region
    return JSONResponse({
        "items": list_jurisdictions(),
        "by_region": jurisdictions_by_region(),
    })


@router.get("/api/jurisdictions/active")
@require_module("sentinel")
async def api_active_jurisdictions(request: Request):
    """Org's currently active jurisdiction configs."""
    return JSONResponse({"items": ds.get_active_jurisdictions()})


@router.post("/api/jurisdictions/active")
@require_capability("module.sentinel.access")
async def api_set_active_jurisdictions(request: Request):
    """Bulk update active jurisdictions. Body: {keys:[...], primary:'GDPR'}"""
    body = await _json_body(request)
    keys = body.get("keys", [])
    primary = body.get("primary")

    from modules.sentinel.jurisdictions import JURISDICTION_RULES
    valid_keys = [k for k in keys if k in JURISDICTION_RULES
                  and JURISDICTION_RULES[k].get("legal_status") != "proposal_not_enacted"]

    existing = {j["jurisdiction_key"] for j in ds.get_all_jurisdiction_configs()}
    for key in existing:
        if key not in valid_keys:
            ds.deactivate_jurisdiction(key)
    for key in valid_keys:
        ds.activate_jurisdiction(key, is_primary=(key == primary))

    return JSONResponse({"ok": True, "active": len(valid_keys)})


@router.get("/api/jurisdictions/{key}")
@require_module("sentinel")
async def api_jurisdiction_detail(request: Request, key: str):
    """Single jurisdiction: registry rules + org config + record counts."""
    from modules.sentinel.jurisdictions import get_jurisdiction
    rules = get_jurisdiction(key)
    if not rules:
        raise HTTPException(status_code=404, detail="Unknown jurisdiction")
    configs = ds.get_all_jurisdiction_configs()
    config = next((c for c in configs if c.get("jurisdiction_key") == key), None)
    stats_list = ds.get_jurisdiction_stats(bu_scope=bu_scope_ids(request.state.user))
    stat = next((s for s in stats_list if s["regulation"] == key),
                {"ropa": 0, "breaches": 0, "dsrs": 0, "dpias": 0})
    return JSONResponse({"key": key, "rules": rules, "config": config, "stats": stat})


@router.put("/api/jurisdictions/{key}/config")
@require_capability("module.sentinel.access")
async def api_update_jurisdiction_config(request: Request, key: str):
    """Update org-specific config for a jurisdiction (DPO, reg number, notes)."""
    from modules.sentinel.jurisdictions import get_jurisdiction
    if not get_jurisdiction(key):
        raise HTTPException(status_code=404, detail="Unknown jurisdiction")
    body = await _json_body(request)
    ds.update_jurisdiction_config(key, body)
    return JSONResponse({"ok": True})


@router.delete("/api/jurisdictions/{key}")
@require_capability("module.sentinel.access")
async def api_deactivate_jurisdiction(request: Request, key: str):
    """Deactivate a jurisdiction (keeps config row)."""
    ds.deactivate_jurisdiction(key)
    return JSONResponse({"ok": True})


@router.get("/api/jurisdiction-stats")
@require_module("sentinel")
async def api_jurisdiction_stats(request: Request):
    """Per-jurisdiction record counts across all sentinel entity types."""
    return JSONResponse({"items": ds.get_jurisdiction_stats(bu_scope=bu_scope_ids(request.state.user))})


def _require_enacted_regulations(*keys):
    """Do not ask the provider to draft legal advice under a historical proposal."""
    from modules.sentinel.jurisdictions import JURISDICTION_RULES

    if any(JURISDICTION_RULES.get(key, {}).get("legal_status") == "proposal_not_enacted" for key in keys):
        raise HTTPException(422, "Bill C-11 was not enacted. Reclassify the record under an applicable law first.")


@router.post("/api/ai/research")
@require_capability("sentinel.ai.assess")
async def api_ai_research(request: Request):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    body = await _json_body(request)
    activity = body.get("activity_type", "")
    regulation = body.get("regulation", "GDPR")
    context = body.get("context", "")
    custom_instructions = body.get("custom_instructions", "")
    _require_enacted_regulations(regulation)
    if not activity:
        raise HTTPException(400, "activity_type is required")
    from modules.sentinel.ai_service import ai_research
    text, err = await ai_research(activity, regulation, context, custom_instructions)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    return JSONResponse({"research": text})


@router.post("/api/ai/generate/{dpia_id}")
@require_capability("sentinel.ai.assess")
async def api_ai_generate(request: Request, dpia_id: int):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    dpia = _scoped_or_404(request, "dpia", dpia_id)
    _require_enacted_regulations(dpia.get("regulation"))
    body = await _json_body(request)
    custom_instructions = body.get("custom_instructions", "")
    from modules.sentinel.ai_service import ai_generate_full_dpia
    text, err = await ai_generate_full_dpia(dpia, custom_instructions)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    ds.update_dpia(dpia_id, {"ai_full_dpia": text})
    return JSONResponse({"content": text})


@router.post("/api/ai/risks")
@require_capability("sentinel.ai.assess")
async def api_ai_risks(request: Request):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    body = await _json_body(request)
    activity = body.get("activity_type", "")
    regulation = body.get("regulation", "GDPR")
    categories = body.get("data_categories", [])
    _require_enacted_regulations(regulation)
    if not activity:
        raise HTTPException(400, "activity_type is required")
    from modules.sentinel.ai_service import ai_suggest_risks
    risks, err = await ai_suggest_risks(activity, regulation, categories)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    return JSONResponse({"risks": risks})


@router.post("/api/ai/score-ropa/{ropa_id}")
@require_capability("sentinel.ai.assess")
async def api_ai_score_ropa(request: Request, ropa_id: int):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    entry = _scoped_or_404(request, "ropa", ropa_id)
    _require_enacted_regulations(entry.get("regulation"))
    from modules.sentinel.ai_service import ai_score_ropa
    result, err = await ai_score_ropa(entry)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    update_data = {
        "risk_level": result.get("risk_score", "medium"),
        "ai_risk_notes": result.get("rationale", ""),
    }
    if result.get("dpia_required"):
        update_data["dpia_required"] = 1
    ds.update_ropa(ropa_id, update_data)
    return JSONResponse(result)


@router.post("/api/ai/suggest-legal-basis")
@require_capability("sentinel.ai.assess")
async def api_ai_suggest_legal_basis(request: Request):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    body = await _json_body(request)
    purpose = body.get("purpose", "")
    regulation = body.get("regulation", "GDPR")
    activity_name = body.get("activity_name", "")
    special_categories = body.get("special_categories", "")
    _require_enacted_regulations(regulation)
    if not purpose:
        raise HTTPException(400, "purpose is required")
    from modules.sentinel.ai_service import ai_suggest_legal_basis
    result, err = await ai_suggest_legal_basis(purpose, regulation, activity_name, special_categories)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, err if "approved legal basis" in err else "AI processing failed")
    return JSONResponse(result)


@router.post("/api/ai/breach-impact/{breach_id}")
@require_capability("sentinel.ai.assess")
async def api_ai_breach_impact(request: Request, breach_id: int):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    breach = _scoped_or_404(request, "breach", breach_id)
    _require_enacted_regulations(breach.get("regulation"))
    from modules.sentinel.ai_service import ai_assess_breach
    text, err = await ai_assess_breach(breach)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    ds.update_breach(breach_id, {"ai_assessment": text})
    return JSONResponse({"assessment": text})


@router.post("/api/ai/dsr-draft/{dsr_id}")
@require_capability("sentinel.ai.assess")
async def api_ai_dsr_draft(request: Request, dsr_id: int):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    dsr = _scoped_or_404(request, "dsr", dsr_id)
    _require_enacted_regulations(dsr.get("regulation"))
    from modules.sentinel.ai_service import ai_draft_dsr_response
    text, err = await ai_draft_dsr_response(dsr)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    ds.update_dsr(dsr_id, {"ai_draft": text})
    return JSONResponse({"draft": text})


@router.post("/api/ai/privacy-notice")
@require_capability("sentinel.ai.assess")
async def api_ai_privacy_notice(request: Request):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    body = await _json_body(request)
    settings = ds.get_all_settings()
    _require_enacted_regulations(body.get("regulation", "GDPR"))
    body.setdefault("org_name", settings.get("org_name", ""))
    body.setdefault("dpo_name", settings.get("dpo_name", ""))
    body.setdefault("dpo_email", settings.get("dpo_email", ""))
    from modules.sentinel.ai_service import ai_generate_privacy_notice
    text, err = await ai_generate_privacy_notice(body)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    return JSONResponse({"notice": text})


@router.post("/api/ai/vendor-check/{vendor_id}")
@require_capability("sentinel.ai.assess")
async def api_ai_vendor_check(request: Request, vendor_id: int):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    vendor = ds.get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found")
    _require_enacted_regulations(vendor.get("regulation"))
    from modules.sentinel.ai_service import ai_vendor_check
    text, err = await ai_vendor_check(vendor)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    ds.update_vendor(vendor_id, {"ai_assessment": text})
    return JSONResponse({"assessment": text})


@router.post("/api/ai/chat")
@require_capability("sentinel.ai.assess")
async def api_ai_chat(request: Request):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    body = await _json_body(request)
    message = body.get("message", "")
    regulation = body.get("regulation")
    history = body.get("history", [])
    _require_enacted_regulations(regulation)
    if not message:
        raise HTTPException(400, "message is required")
    from modules.sentinel.ai_service import ai_chat
    text, err = await ai_chat(message, regulation=regulation, history=history)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    return JSONResponse({"response": text})


@router.post("/api/ai/gap-analysis")
@require_capability("sentinel.ai.assess")
async def api_ai_gap_analysis(request: Request):
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    body = await _json_body(request)
    reg_from = body.get("regulation_from", "GDPR")
    reg_to = body.get("regulation_to", "South Africa POPIA")
    _require_enacted_regulations(reg_from, reg_to)
    activities = body.get("activities", "")
    from modules.sentinel.ai_service import ai_gap_analysis
    text, err = await ai_gap_analysis(reg_from, reg_to, activities)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    return JSONResponse({"analysis": text})


@router.post("/api/ai/generate-policy")
@require_capability("sentinel.ai.assess")
async def api_ai_generate_policy(request: Request):
    """Draft a data protection policy document using AI."""
    uid = str(request.state.user["id"])
    if not check_ai_rate_limit(uid):
        return JSONResponse({"error": "AI rate limit exceeded. Maximum 60 requests per hour."}, status_code=429)
    record_ai_call(uid)
    body = await _json_body(request)
    policy_type = body.get("policy_type", "Data Protection Policy")
    topic = body.get("topic", "")
    regulation = body.get("regulation", "GDPR")
    _require_enacted_regulations(regulation)

    topic_clause = f" with a focus on {topic}" if topic else ""
    user_msg = (
        f"Draft a complete {policy_type}{topic_clause} for compliance with {regulation}. "
        f"Structure it with: Purpose, Scope, Policy Statement, Responsibilities, "
        f"Procedures, Review, and Definitions sections. "
        f"Return only the policy document text, ready to use."
    )
    from modules.sentinel.ai_service import ai_chat
    text, err = await ai_chat(user_msg, regulation=regulation)
    if err:
        log.error("AI service error: %s", err)
        raise HTTPException(500, "AI processing failed")
    return JSONResponse({"content": text})
