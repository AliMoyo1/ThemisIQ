"""
Super-admin routes: org management, tenant provisioning, licence assignment.

Only accessible to users with is_super_admin=1.
All data reads/writes use the public schema (no tenant context needed here).
"""
import re
import logging
from functools import wraps

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from config import settings
from core.middleware import get_current_user
from database import get_db, provision_tenant_schema, insert_returning_id

log = logging.getLogger("oneforall.super_admin")
router = APIRouter(prefix="/super-admin", tags=["super-admin"])
templates = Jinja2Templates(directory=["modules/launcher/templates", "templates"])


def require_super_admin(func):
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user = await get_current_user(request)
        if not user:
            from fastapi.responses import RedirectResponse
            return RedirectResponse("/login", status_code=303)
        if not user.get("is_super_admin"):
            raise HTTPException(status_code=403, detail="Super admin access required.")
        request.state.user = user
        return await func(request, *args, **kwargs)
    return wrapper


def _json_body(request):
    import asyncio
    return request.json()


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
@require_super_admin
async def super_admin_dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "super_admin.html",
        {"user": request.state.user},
    )


# ── Orgs API ─────────────────────────────────────────────────────────────────

@router.get("/api/orgs")
@require_super_admin
async def list_orgs(request: Request):
    db = get_db()
    try:
        orgs = db.execute(
            "SELECT o.id, o.name, o.slug, o.plan, o.status, o.created_at, "
            "COUNT(u.id) AS user_count "
            "FROM organizations o "
            "LEFT JOIN users u ON u.org_id = o.id "
            "GROUP BY o.id, o.name, o.slug, o.plan, o.status, o.created_at "
            "ORDER BY o.created_at DESC"
        ).fetchall()
        result = []
        for o in orgs:
            lic = db.execute(
                "SELECT module_keys, seats, valid_until FROM licenses WHERE org_id = %s ORDER BY id DESC LIMIT 1",
                (o["id"],),
            ).fetchone()
            result.append({
                "id": o["id"],
                "name": o["name"],
                "slug": o["slug"],
                "plan": o["plan"],
                "status": o["status"],
                "created_at": str(o["created_at"]),
                "user_count": o["user_count"],
                "modules": lic["module_keys"].split(",") if lic else [],
                "seats": lic["seats"] if lic else 0,
                "valid_until": str(lic["valid_until"]) if lic and lic["valid_until"] else None,
            })
        return JSONResponse(result)
    finally:
        db.close()


@router.post("/api/orgs")
@require_super_admin
async def create_org(request: Request):
    body = await request.json()
    name    = (body.get("name") or "").strip()
    plan    = (body.get("plan") or "starter").strip()
    modules = (body.get("modules") or "aria,bcm,erm,grid,orm,sentinel").strip()
    seats   = int(body.get("seats") or 10)

    if not name:
        return JSONResponse({"error": "Organisation name is required."}, status_code=422)

    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not slug:
        return JSONResponse({"error": "Name produces an empty slug."}, status_code=422)

    db = get_db()
    try:
        existing = db.execute(
            "SELECT id FROM organizations WHERE slug = %s", (slug,)
        ).fetchone()
        if existing:
            return JSONResponse({"error": f"Slug '{slug}' already exists."}, status_code=409)

        org_id = insert_returning_id(
            db,
            "INSERT INTO organizations (name, slug, plan, status) VALUES (%s, %s, %s, 'active')",
            (name, slug, plan),
        )
        db.execute(
            "INSERT INTO licenses (org_id, module_keys, seats) VALUES (%s, %s, %s)",
            (org_id, modules, seats),
        )
        db.commit()

        # Provision the tenant schema (PostgreSQL only; no-op on SQLite).
        if settings.is_postgres():
            try:
                provision_tenant_schema(slug)
                log.info("Provisioned tenant schema for org %d (slug=%s)", org_id, slug)
            except Exception as exc:
                log.error("Schema provision failed for %s: %s", slug, exc)
                return JSONResponse(
                    {"error": f"Org created but schema provisioning failed: {exc}"},
                    status_code=500,
                )

        return JSONResponse({"id": org_id, "slug": slug}, status_code=201)
    finally:
        db.close()


@router.put("/api/orgs/{org_id}")
@require_super_admin
async def update_org(request: Request, org_id: int):
    body = await request.json()
    db = get_db()
    try:
        if "status" in body:
            db.execute(
                "UPDATE organizations SET status = %s WHERE id = %s",
                (body["status"], org_id),
            )
        if "plan" in body:
            db.execute(
                "UPDATE organizations SET plan = %s WHERE id = %s",
                (body["plan"], org_id),
            )
        if "modules" in body or "seats" in body:
            lic = db.execute(
                "SELECT id FROM licenses WHERE org_id = %s ORDER BY id DESC LIMIT 1",
                (org_id,),
            ).fetchone()
            if lic:
                if "modules" in body:
                    db.execute(
                        "UPDATE licenses SET module_keys = %s WHERE id = %s",
                        (body["modules"], lic["id"]),
                    )
                if "seats" in body:
                    db.execute(
                        "UPDATE licenses SET seats = %s WHERE id = %s",
                        (int(body["seats"]), lic["id"]),
                    )
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()


# ── Users API ─────────────────────────────────────────────────────────────────

@router.get("/api/orgs/{org_id}/users")
@require_super_admin
async def list_org_users(request: Request, org_id: int):
    db = get_db()
    try:
        users = db.execute(
            "SELECT u.id, u.username, u.email, u.full_name, u.is_active, u.created_at, "
            "COALESCE(u.is_super_admin, 0) AS is_super_admin "
            "FROM users u WHERE u.org_id = %s ORDER BY u.created_at DESC",
            (org_id,),
        ).fetchall()
        return JSONResponse([
            {
                "id": u["id"],
                "username": u["username"],
                "email": u["email"],
                "full_name": u["full_name"],
                "is_active": bool(u["is_active"]),
                "is_super_admin": bool(u["is_super_admin"]),
                "created_at": str(u["created_at"]),
            }
            for u in users
        ])
    finally:
        db.close()


@router.post("/api/orgs/{org_id}/users")
@require_super_admin
async def create_org_user(request: Request, org_id: int):
    body = await request.json()
    username  = (body.get("username") or "").strip()
    email     = (body.get("email") or "").strip()
    full_name = (body.get("full_name") or "").strip()
    password  = (body.get("password") or "").strip()
    role      = (body.get("role") or "viewer").strip()

    if not username or not email or not password:
        return JSONResponse({"error": "username, email, and password are required."}, status_code=422)

    import bcrypt
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

    db = get_db()
    try:
        existing = db.execute(
            "SELECT id FROM users WHERE username = %s OR email = %s",
            (username, email),
        ).fetchone()
        if existing:
            return JSONResponse({"error": "Username or email already exists."}, status_code=409)

        user_id = insert_returning_id(
            db,
            "INSERT INTO users (username, email, full_name, password_hash, org_id, must_change_password) "
            "VALUES (%s, %s, %s, %s, %s, 1)",
            (username, email, full_name or username, pw_hash, org_id),
        )
        db.execute(
            "INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (user_id, role),
        )
        db.commit()
        return JSONResponse({"id": user_id}, status_code=201)
    finally:
        db.close()
