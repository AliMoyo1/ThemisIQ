"""
PLAN-36 P04: data-readiness and integrity centre -- routes.

Capability gates (core/rbac.py): platform.view_readiness for read/export,
the narrower platform.manage_readiness for acknowledge/suppress/reopen and
the on-demand scan trigger -- acting on a finding is a more consequential
step than seeing it.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from database import get_db
from core.middleware import (
    require_capability, log_audit,
    check_readiness_scan_rate_limit, record_readiness_scan,
)
from core.shell_context import shell_ctx
from modules.readiness import data_service as svc

router = APIRouter(prefix="/readiness", tags=["readiness"])
templates = Jinja2Templates(directory=["modules/readiness/templates", "templates"])


@router.get("", response_class=HTMLResponse)
@require_capability("platform.view_readiness")
async def readiness_page(request: Request):
    ctx = shell_ctx(request, active_module="readiness", active_section="readiness")
    ctx["user"] = request.state.user
    return templates.TemplateResponse(request, "index.html", ctx)


@router.get("/api/findings")
@require_capability("platform.view_readiness")
async def api_list_findings(request: Request):
    user = request.state.user
    q = request.query_params
    db = get_db()
    try:
        findings = svc.list_findings(
            db, user["org_id"],
            module=q.get("module") or None,
            severity=q.get("severity") or None,
            status=q.get("status") or None,
        )
        coverage = svc.get_rule_coverage(db, user["org_id"])
    finally:
        db.close()
    return JSONResponse({"ok": True, "findings": findings, "rule_coverage": coverage})


@router.get("/api/findings/export")
@require_capability("platform.view_readiness")
async def api_export_findings(request: Request):
    user = request.state.user
    q = request.query_params
    db = get_db()
    try:
        csv_text = svc.export_findings_csv(
            db, user["org_id"],
            module=q.get("module") or None,
            severity=q.get("severity") or None,
            status=q.get("status") or None,
        )
        log_audit(user, "readiness", "Exported readiness findings")
    finally:
        db.close()
    return PlainTextResponse(
        csv_text, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=readiness_findings.csv"},
    )


@router.post("/api/findings/{finding_id}/acknowledge")
@require_capability("platform.manage_readiness")
async def api_acknowledge_finding(request: Request, finding_id: int):
    user = request.state.user
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    reason = (payload.get("reason") or "").strip()
    expires_at = payload.get("expires_at") or None
    db = get_db()
    try:
        try:
            finding = svc.acknowledge_finding(db, user["org_id"], finding_id, user, reason, expires_at)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)
        if finding is None:
            return JSONResponse({"ok": False, "error": "Finding not found."}, status_code=404)
        log_audit(user, "readiness", f"{'Suppressed' if expires_at else 'Acknowledged'} finding {finding_id}: {reason}")
    finally:
        db.close()
    return JSONResponse({"ok": True, "finding": finding})


@router.post("/api/findings/{finding_id}/reopen")
@require_capability("platform.manage_readiness")
async def api_reopen_finding(request: Request, finding_id: int):
    user = request.state.user
    db = get_db()
    try:
        finding = svc.reopen_finding(db, user["org_id"], finding_id)
        if finding is None:
            return JSONResponse({"ok": False, "error": "Finding not found."}, status_code=404)
        log_audit(user, "readiness", f"Reopened finding {finding_id}")
    finally:
        db.close()
    return JSONResponse({"ok": True, "finding": finding})


@router.post("/api/scan")
@require_capability("platform.manage_readiness")
async def api_trigger_scan(request: Request):
    user = request.state.user
    org_id = user["org_id"]
    if not check_readiness_scan_rate_limit(org_id):
        return JSONResponse(
            {"ok": False, "error": "A scan was already triggered recently for your organization. Please wait a few minutes."},
            status_code=429,
        )
    record_readiness_scan(org_id)
    from modules.readiness.scheduler import run_scan_now
    counts = run_scan_now(org_id)
    log_audit(user, "readiness", f"Triggered an on-demand readiness scan: {counts}")
    return JSONResponse({"ok": True, "counts": counts})
