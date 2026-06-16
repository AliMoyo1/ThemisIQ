"""
Launcher sub-router: Frameworks — Admin framework management, unified framework
APIs, cross-module links.
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from database import insert_returning_id
from modules.launcher._route_helpers import (
    _JSONResp, require_auth, require_capability, has_capability, log_audit,
    shell_ctx, shell_templates, get_db,
)

router = APIRouter()


# ═════════════════════════════════════════════════════════════════════════════
# ADMIN — FRAMEWORK MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/admin/frameworks", response_class=HTMLResponse)
@require_auth
async def admin_frameworks_page(request: Request):
    """Framework management page — accessible from Command Centre."""
    from core.framework_service import list_frameworks, list_controls, bulk_create_controls

    # Ensure controls are seeded for all frameworks
    try:
        from seeds.framework_controls import FRAMEWORK_CONTROLS
        all_fws = list_frameworks(active_only=False)
        for fw in all_fws:
            if fw["total_controls"] == 0:
                seed_data = FRAMEWORK_CONTROLS.get(fw["name"])
                if seed_data:
                    existing = list_controls(fw["id"])
                    if not existing:
                        bulk_create_controls(fw["id"], seed_data)
    except Exception:
        pass

    frameworks = list_frameworks(active_only=False)
    ctx = shell_ctx(request, active_module="platform", active_section="frameworks")
    ctx.update({"frameworks": frameworks})
    return shell_templates.TemplateResponse(request, "admin_frameworks.html", ctx)


@router.post("/admin/api/frameworks")
@require_auth
async def admin_create_framework(request: Request):
    """Create a custom framework."""
    admin = request.state.user
    if not has_capability(admin, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    body = await request.json()
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    color = body.get("color", "#1E3A5F")
    relevant_modules = (body.get("relevant_modules") or "aria").strip()
    if not name or not description:
        return _JSONResp({"error": "Name and description required"}, status_code=400)
    db = get_db()
    try:
        existing = db.execute("SELECT id FROM frameworks WHERE name = %s", (name,)).fetchone()
        if existing:
            return _JSONResp({"error": "Framework already exists"}, status_code=409)
        # Insert into unified frameworks table (primary)
        fw_id = insert_returning_id(
            db,
            "INSERT INTO frameworks (name, description, color, relevant_modules, is_active) "
            "VALUES (%s, %s, %s, %s, 1)",
            (name, description, color, relevant_modules),
        )
        db.commit()
        log_audit(admin, "platform", "framework_created", details=f"Created framework: {name}")
    finally:
        db.close()
    return _JSONResp({"id": fw_id, "name": name})


@router.post("/admin/api/frameworks/{fw_id}/toggle")
@require_auth
async def admin_toggle_framework(request: Request, fw_id: int):
    """Toggle a framework's is_active status using the unified table."""
    admin = request.state.user
    if not has_capability(admin, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    from core.framework_service import get_framework, activate_framework, deactivate_framework
    fw = get_framework(fw_id)
    if not fw:
        return _JSONResp({"error": "Not found"}, status_code=404)
    if fw["is_active"]:
        deactivate_framework(fw_id, user_id=admin["id"])
        new_state = 0
    else:
        activate_framework(fw_id, user_id=admin["id"])
        new_state = 1
    log_audit(admin, "platform", "framework_toggle",
              details=f"{'Activated' if new_state else 'Deactivated'} {fw['name']}")
    return _JSONResp({"id": fw_id, "is_active": new_state})


@router.post("/admin/api/frameworks/seed-controls")
@require_auth
async def admin_seed_controls(request: Request):
    """Force-seed controls for all frameworks that are missing them."""
    admin = request.state.user
    if not has_capability(admin, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    from seeds.framework_controls import seed_all_controls
    count = seed_all_controls()
    log_audit(admin, "platform", "controls_seeded", details=f"Seeded {count} controls")
    return _JSONResp({"seeded": count})


# ═════════════════════════════════════════════════════════════════════════════
# UNIFIED FRAMEWORK APIs
# ═════════════════════════════════════════════════════════════════════════════
# COMPLIANCE PROJECTS PAGE
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/projects", response_class=HTMLResponse)
@require_auth
async def projects_page(request: Request):
    """Compliance Projects — active frameworks as project cards."""
    from core.framework_service import list_frameworks
    frameworks = list_frameworks(active_only=True)
    db = get_db()
    try:
        for fw in frameworks:
            fid = fw["id"]
            total = fw.get("total_controls") or db.execute(
                "SELECT COUNT(*) FROM controls WHERE framework_id=%s", (fid,)
            ).fetchone()[0]
            compliant = db.execute(
                "SELECT COUNT(*) FROM controls "
                "WHERE framework_id=%s AND status IN ('Implemented','Compliant','Complete')",
                (fid,),
            ).fetchone()[0]
            fw["compliance_pct"] = round(compliant / total * 100) if total else 0
            fw["compliant_controls"] = compliant
            fw["total_controls_actual"] = total or 0
    finally:
        db.close()

    ctx = shell_ctx(request, active_module="platform", active_section="projects")
    ctx["frameworks"] = frameworks
    ctx["active_projects"] = len(frameworks)
    return shell_templates.TemplateResponse(request, "projects.html", ctx)


# ═════════════════════════════════════════════════════════════════════════════

@router.get("/api/frameworks/active")
@require_auth
async def api_active_frameworks(request: Request):
    """Return active frameworks, optionally filtered by module."""
    from core.framework_service import list_frameworks
    module = request.query_params.get("module")
    return _JSONResp(list_frameworks(module=module, active_only=True))


@router.get("/api/frameworks")
@require_auth
async def api_frameworks_list(request: Request):
    """List all unified frameworks."""
    from core.framework_service import list_frameworks
    module = request.query_params.get("module")
    active_only = request.query_params.get("active_only", "true") == "true"
    return _JSONResp(list_frameworks(module=module, active_only=active_only))


@router.get("/api/frameworks/stats/summary")
@require_auth
async def api_framework_stats(request: Request):
    """Get aggregate framework stats."""
    from core.framework_service import get_framework_stats
    return _JSONResp(get_framework_stats())


@router.get("/api/frameworks/{fid}")
@require_auth
async def api_framework_detail(request: Request, fid: int):
    """Get framework details with controls."""
    from core.framework_service import get_framework, list_controls
    fw = get_framework(fid)
    if not fw:
        raise HTTPException(404, "Framework not found")
    fw["controls"] = list_controls(fid)
    return _JSONResp(fw)


@router.post("/api/frameworks/{fid}/activate")
@require_auth
@require_capability("manage_frameworks")
async def api_framework_activate(request: Request, fid: int):
    """Activate a framework globally."""
    from core.framework_service import activate_framework
    uid = request.state.user["id"]
    activate_framework(fid, user_id=uid)
    return _JSONResp({"status": "activated"})


@router.post("/api/frameworks/{fid}/deactivate")
@require_auth
@require_capability("manage_frameworks")
async def api_framework_deactivate(request: Request, fid: int):
    """Deactivate a framework globally."""
    from core.framework_service import deactivate_framework
    uid = request.state.user["id"]
    deactivate_framework(fid, user_id=uid)
    return _JSONResp({"status": "deactivated"})


@router.get("/api/frameworks/{fid}/controls")
@require_auth
async def api_framework_controls(request: Request, fid: int):
    """List controls for a framework (lazy-seeds if empty)."""
    from core.framework_service import list_controls, get_framework, bulk_create_controls
    status = request.query_params.get("status")
    controls = list_controls(fid, status=status)
    if not controls and not status:
        # Lazy-seed from seed data
        try:
            fw = get_framework(fid)
            if fw:
                from seeds.framework_controls import FRAMEWORK_CONTROLS
                seed_data = FRAMEWORK_CONTROLS.get(fw["name"])
                if seed_data:
                    bulk_create_controls(fid, seed_data)
                    controls = list_controls(fid)
        except Exception:
            pass
    return _JSONResp(controls)


@router.post("/api/frameworks/{fid}/controls")
@require_auth
@require_capability("manage_frameworks")
async def api_framework_create_control(request: Request, fid: int):
    """Create a single control."""
    from core.framework_service import create_control
    data = await request.json()
    uid = request.state.user["id"]
    control_id = create_control(
        framework_id=fid,
        ref=data.get("ref", ""),
        name=data.get("name", ""),
        description=data.get("description", ""),
        category=data.get("category", ""),
        doc_type=data.get("doc_type", "Policy"),
        priority=data.get("priority", "High"),
        user_id=uid,
    )
    return _JSONResp({"id": control_id}, status_code=201)


@router.post("/api/frameworks/{fid}/controls/bulk")
@require_auth
@require_capability("manage_frameworks")
async def api_framework_bulk_controls(request: Request, fid: int):
    """Bulk create controls for a framework."""
    from core.framework_service import bulk_create_controls
    data = await request.json()
    uid = request.state.user["id"]
    count = bulk_create_controls(fid, data.get("controls", []), user_id=uid)
    return _JSONResp({"inserted": count})


@router.post("/api/frameworks/{fid}/controls/ai-generate")
@require_auth
@require_capability("manage_frameworks")
async def api_framework_ai_generate_controls(request: Request, fid: int):
    """Use AI to generate controls for a framework (custom frameworks without seed data)."""
    from core.framework_service import get_framework, list_controls, bulk_create_controls
    from core.ai_controls import generate_controls_for_framework

    fw = get_framework(fid)
    if not fw:
        return _JSONResp({"error": "Framework not found"}, 404)

    # Don't overwrite existing controls unless forced
    data = await request.json() if request.headers.get("content-type") == "application/json" else {}
    force = data.get("force", False)
    count_hint = data.get("count", 15)

    existing = list_controls(fid)
    if existing and not force:
        return _JSONResp({
            "error": "Framework already has %d controls. Set force=true to regenerate." % len(existing),
            "existing_count": len(existing),
        }, 409)

    try:
        controls = generate_controls_for_framework(
            framework_name=fw["name"],
            framework_description=fw.get("description", ""),
            relevant_modules=fw.get("relevant_modules", ""),
            count_hint=count_hint,
        )
        uid = request.state.user["id"]
        inserted = bulk_create_controls(fid, controls, user_id=uid)
        return _JSONResp({
            "generated": len(controls),
            "inserted": inserted,
            "framework": fw["name"],
        })
    except RuntimeError as e:
        return _JSONResp({"error": str(e)}, 500)


# ── Cross-Module Links ──────────────────────────────────────────────────────

@router.get("/api/links")
@require_auth
async def api_links_get(request: Request):
    """Get cross-module links for an entity."""
    from core.framework_service import get_links
    module = request.query_params.get("module", "")
    entity_type = request.query_params.get("type", "")
    entity_id = int(request.query_params.get("id", "0"))
    if not module or not entity_type or not entity_id:
        return _JSONResp([])
    return _JSONResp(get_links(module, entity_type, entity_id))


@router.post("/api/links")
@require_auth
async def api_links_create(request: Request):
    """Create a cross-module link."""
    from core.framework_service import create_link
    data = await request.json()
    uid = request.state.user["id"]
    link_id = create_link(
        source_module=data.get("source_module", ""),
        source_type=data.get("source_type", ""),
        source_id=data.get("source_id", 0),
        target_module=data.get("target_module", ""),
        target_type=data.get("target_type", ""),
        target_id=data.get("target_id", 0),
        relationship=data.get("relationship", "related"),
        user_id=uid,
    )
    return _JSONResp({"id": link_id}, status_code=201)
