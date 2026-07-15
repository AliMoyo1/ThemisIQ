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
        from fastapi.responses import RedirectResponse
        user = await get_current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        if user.get("mfa_pending"):
            return RedirectResponse("/mfa/verify", status_code=303)
        if user.get("must_change_password"):
            return RedirectResponse("/change-password", status_code=303)
        if not user.get("is_super_admin"):
            raise HTTPException(status_code=403, detail="Super admin access required.")
        request.state.user = user
        return await func(request, *args, **kwargs)
    return wrapper


async def _json_body(request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    from core.sanitize import sanitize_dict
    return sanitize_dict(body)


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
    body = await _json_body(request)
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
                    {"error": "Org created but schema provisioning failed"},
                    status_code=500,
                )

        return JSONResponse({"id": org_id, "slug": slug}, status_code=201)
    finally:
        db.close()


@router.put("/api/orgs/{org_id}")
@require_super_admin
async def update_org(request: Request, org_id: int):
    body = await _json_body(request)
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
        if "modules" in body or "seats" in body or "valid_until" in body:
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
                if "valid_until" in body:
                    vu = body["valid_until"] or None
                    db.execute(
                        "UPDATE licenses SET valid_until = %s WHERE id = %s",
                        (vu, lic["id"]),
                    )
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()


@router.delete("/api/orgs/{org_id}")
@require_super_admin
async def delete_org(request: Request, org_id: int):
    db = get_db()
    try:
        org = db.execute(
            "SELECT slug FROM organizations WHERE id = %s", (org_id,)
        ).fetchone()
        if not org:
            return JSONResponse({"error": "Organisation not found."}, status_code=404)
        if org["slug"] == "public":
            return JSONResponse(
                {"error": "Cannot delete the default organisation."},
                status_code=400,
            )
        users = db.execute(
            "SELECT COUNT(*) AS c FROM users WHERE org_id = %s", (org_id,)
        ).fetchone()
        if users and users["c"] > 0:
            return JSONResponse(
                {"error": f"Org has {users['c']} users. Remove or reassign them first."},
                status_code=409,
            )
        # Null out org references in tables that preserve their rows after org removal.
        db.execute("UPDATE audit_log SET org_id=NULL WHERE org_id=%s", (org_id,))
        # Remove API keys that belonged to this org.
        db.execute("DELETE FROM api_keys WHERE org_id=%s", (org_id,))
        db.execute("DELETE FROM licenses WHERE org_id = %s", (org_id,))
        db.execute("DELETE FROM organizations WHERE id = %s", (org_id,))
        db.commit()
        if settings.is_postgres():
            safe = re.sub(r"[^a-z0-9_]", "", (org["slug"] or "").lower())
            if safe:
                try:
                    db.execute(f"DROP SCHEMA IF EXISTS tenant_{safe} CASCADE")
                    db.commit()
                except Exception as exc:
                    log.warning("Schema drop for %s failed: %s", safe, exc)
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
    body = await _json_body(request)
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
        lic = db.execute(
            "SELECT seats FROM licenses WHERE org_id=%s ORDER BY id DESC LIMIT 1",
            (org_id,),
        ).fetchone()
        if lic and lic["seats"]:
            current_count = db.execute(
                "SELECT COUNT(*) FROM users WHERE org_id=%s AND is_active=1",
                (org_id,),
            ).fetchone()[0]
            if current_count >= lic["seats"]:
                return JSONResponse(
                    {"error": f"Seat limit ({lic['seats']}) reached for this organisation."},
                    status_code=422,
                )

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


@router.delete("/api/orgs/{org_id}/users/{user_id}")
@require_super_admin
async def delete_org_user(request: Request, org_id: int, user_id: int):
    db = get_db()
    try:
        user = db.execute(
            "SELECT id FROM users WHERE id=%s AND org_id=%s",
            (user_id, org_id),
        ).fetchone()
        if not user:
            return JSONResponse({"error": "User not found in this organisation."}, status_code=404)

        uid = user_id

        # NULL out nullable created_by columns so historical records are preserved.
        for tbl in (
            "events", "risk_register", "workflow_definitions", "comm_templates",
            "report_definitions", "api_keys", "webhooks", "calendar_events",
            "task_board", "email_reminders", "cross_module_links",
            "aria_doc_templates", "aria_control_mappings",
            "grid_share_links", "grid_remote_sessions",
            "sentinel_lia", "erm_enterprise_risks",
            "erm_regulatory_obligations", "erm_assessments", "orm_rcsa_assessments",
        ):
            try:
                db.execute(f"UPDATE {tbl} SET created_by=NULL WHERE created_by=%s", (uid,))
            except Exception:
                pass

        # NULL out nullable user_id columns that are references, not ownership.
        for tbl in (
            "audit_log",
            "grid_control_comments", "grid_remote_participants",
            "grid_remote_notes", "bcm_training_attestations",
        ):
            try:
                db.execute(f"UPDATE {tbl} SET user_id=NULL WHERE user_id=%s", (uid,))
            except Exception:
                pass

        # Delete records owned by the user.
        for tbl in ("notifications", "user_preferences", "grid_reminders",
                    "grid_audit_signoffs", "bcm_chat_messages",
                    "erm_chat_messages", "orm_chat_messages",
                    "grid_digest_subscriptions",
                    "user_roles", "sessions"):
            try:
                db.execute(f"DELETE FROM {tbl} WHERE user_id=%s", (uid,))
            except Exception:
                pass

        db.execute("DELETE FROM users WHERE id=%s AND org_id=%s", (uid, org_id))
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()


# ── Demo Requests ─────────────────────────────────────────────────────────────

@router.get("/api/demo-requests")
@require_super_admin
async def list_demo_requests(request: Request):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, name, email, company, plan, ip_address, contacted, "
            "contacted_at, notes, created_at FROM demo_requests ORDER BY created_at DESC"
        ).fetchall()
        return JSONResponse([dict(r) for r in rows])
    finally:
        db.close()


@router.post("/api/demo-requests/{req_id}/contacted")
@require_super_admin
async def mark_demo_contacted(request: Request, req_id: int):
    db = get_db()
    try:
        from core.timeutils import utcnow
        db.execute(
            "UPDATE demo_requests SET contacted=1, contacted_at=%s WHERE id=%s",
            (utcnow().strftime("%Y-%m-%d %H:%M:%S"), req_id),
        )
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()


@router.delete("/api/demo-requests/{req_id}")
@require_super_admin
async def delete_demo_request(request: Request, req_id: int):
    db = get_db()
    try:
        db.execute("DELETE FROM demo_requests WHERE id=%s", (req_id,))
        db.commit()
        return JSONResponse({"ok": True})
    finally:
        db.close()
