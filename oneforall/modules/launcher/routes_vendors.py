"""
Launcher sub-router: Unified Vendor Directory.

Provides a cross-module vendor registry view — all canonical vendors with
their presence in Sentinel (Privacy), GRID (Audit), and BCM (Resilience),
plus smart gap flags and risk summaries.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from modules.launcher._route_helpers import (
    require_auth, shell_ctx, shell_templates, get_db,
)
from core.vendor_link import get_vendor_directory, get_cross_module_profile

router = APIRouter()


@router.get("/vendors", response_class=HTMLResponse)
@require_auth
async def vendor_directory_page(request: Request):
    ctx = shell_ctx(request, active_module="platform", active_section="vendors")
    return shell_templates.TemplateResponse(request, "vendor_directory.html", ctx)


@router.get("/api/vendors/directory")
@require_auth
async def api_vendor_directory(request: Request):
    db = get_db()
    try:
        vendors = get_vendor_directory(db)
        return JSONResponse({"items": vendors, "total": len(vendors)})
    finally:
        db.close()


@router.get("/api/vendors/{canonical_id}/profile")
@require_auth
async def api_vendor_profile(request: Request, canonical_id: int):
    db = get_db()
    try:
        profile = get_cross_module_profile(db, canonical_id)
        return JSONResponse(profile)
    finally:
        db.close()


@router.post("/api/vendors/directory")
@require_auth
async def api_vendor_directory_create(request: Request):
    """Create a canonical vendor record (without attaching it to a specific module)."""
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    db = get_db()
    try:
        from core.vendor_link import ensure_canonical
        cid = ensure_canonical(db, name, body.get("contact_email"))
        # Also update optional canonical fields
        for field in ("contact_name", "contact_email", "website", "country", "services",
                      "risk_level", "notes"):
            if body.get(field):
                db.execute(
                    f"UPDATE canonical_vendors SET {field}=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (body[field], cid),
                )
        db.commit()
        vendor = dict(db.execute("SELECT * FROM canonical_vendors WHERE id=%s", (cid,)).fetchone())
        return JSONResponse({"id": cid, "vendor": vendor}, status_code=201)
    finally:
        db.close()
