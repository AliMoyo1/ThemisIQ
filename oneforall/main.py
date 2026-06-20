"""
One For All - Unified Compliance Platform.

Main FastAPI application.  Mounts all module routers and shared middleware.
"""
import logging
import os
import sqlite3
import sys

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.gzip import GZipMiddleware

from config import settings
from database import init_db, get_db, OperationalError
from core.middleware import security_headers_middleware, csrf_origin_middleware, tenant_context_middleware
import core.event_handlers  # noqa: F401 - registers cross-module event handlers

# -- Logging ------------------------------------------------------------------
# Level is env-driven: LOG_LEVEL overrides; DEBUG mode defaults to DEBUG-level.
_default_level = "DEBUG" if settings.DEBUG else "INFO"
_log_level = os.getenv("LOG_LEVEL", _default_level).upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("oneforall")

# -- App ----------------------------------------------------------------------
app = FastAPI(
    title="ThemisIQ",
    description="Unified GRC Platform — Governance, Risk, Compliance, Privacy & Resilience",
    version="1.0.0",
    docs_url=None,   # Disable Swagger UI in production
    redoc_url=None,
)

# -- Middleware ---------------------------------------------------------------
# GZip: compresses all text responses >= 1 KB automatically.
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Order matters: outermost first. Security headers wrap everything,
# CSRF origin check runs before the route handler.
app.middleware("http")(security_headers_middleware)
app.middleware("http")(csrf_origin_middleware)
app.middleware("http")(tenant_context_middleware)

# -- Static files -------------------------------------------------------------
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# -- Startup ------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    from core.monitoring import init_monitoring
    init_monitoring(settings)

    log.info("Initialising database...")
    init_db()
    from modules.aria.ask_service import init_index as _ask_init_index
    try:
        _ask_init_index()
    except Exception as _e:
        log.warning("aria_ask_index init skipped: %s", _e)

    # Auto-seed if no users exist
    db = get_db()
    try:
        count = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    finally:
        db.close()

    if count == 0:
        log.info("No users found - running seed...")
        from seeds.seed import run_seed
        run_seed()

    # Ensure the default organisation exists and all users are assigned to it.
    # This is idempotent — safe to run on every startup.
    if settings.is_postgres():
        db3 = get_db()
        try:
            org = db3.execute(
                "SELECT id FROM organizations WHERE slug = 'public'"
            ).fetchone()
            if not org:
                db3.execute(
                    "INSERT INTO organizations (name, slug, plan, status) "
                    "VALUES ('Default', 'public', 'enterprise', 'active') "
                    "ON CONFLICT (slug) DO NOTHING"
                )
                db3.commit()
                org = db3.execute(
                    "SELECT id FROM organizations WHERE slug = 'public'"
                ).fetchone()
                db3.execute(
                    "INSERT INTO licenses (org_id, module_keys, seats) "
                    "VALUES (%s, 'aria,bcm,erm,grid,orm,sentinel', 999) "
                    "ON CONFLICT DO NOTHING",
                    (org["id"],),
                )
                db3.commit()
                log.info("Created default organisation (slug=public)")
            # Assign any users with no org to the default org.
            if org:
                db3.execute(
                    "UPDATE users SET org_id = %s WHERE org_id IS NULL",
                    (org["id"],),
                )
                db3.commit()
        except Exception as exc:
            log.warning("Default org seed failed (non-fatal): %s", exc)
        finally:
            db3.close()

    if False:
        pass
    else:
        # Migrate: ensure unified frameworks table is populated from legacy table
        db2 = get_db()
        try:
            unified = db2.execute("SELECT COUNT(*) as c FROM frameworks").fetchone()["c"]
            if unified == 0:
                legacy = db2.execute(
                    "SELECT name, description, color, relevant_modules, is_active "
                    "FROM aria_frameworks"
                ).fetchall()
                if legacy:
                    for r in legacy:
                        db2.execute(
                            "INSERT INTO frameworks "
                            "(name, description, color, relevant_modules, is_active) "
                            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                            (r["name"], r["description"], r["color"],
                             r["relevant_modules"], r["is_active"]),
                        )
                    db2.commit()
                    log.info("Migrated %d frameworks from legacy table", len(legacy))
        finally:
            db2.close()

        # Ensure controls are populated for existing deployments
        from seeds.seed import seed_controls
        seed_controls()

        # Ensure pre-built control mappings are loaded
        try:
            from seeds.control_mappings import seed_control_mappings
            count = seed_control_mappings()
            if count:
                log.info("Seeded %d pre-built control mappings", count)
        except Exception as exc:
            log.warning("Control mapping seed failed (non-fatal): %s", exc)

    # Start GRID background scheduler (reminders, escalations, backups, etc.)
    try:
        from modules.grid.scheduler import start_scheduler
        start_scheduler()
    except Exception as exc:
        log.warning("GRID scheduler failed to start: %s", exc)

    # Start Sentinel background scheduler (breach 72h, DSR 30d, retention reviews)
    try:
        from modules.sentinel.scheduler import start_scheduler as sentinel_start
        sentinel_start()
    except Exception as exc:
        log.warning("Sentinel scheduler failed to start: %s", exc)

    # Start BCM background scheduler (plan reviews, exercise alerts, training reminders)
    try:
        from modules.bcm.scheduler import start_scheduler as bcm_start
        bcm_start()
    except Exception as exc:
        log.warning("BCM scheduler failed to start: %s", exc)

    # Start Evidence Vault scheduler (expiry notifications at 30/7/1 days)
    try:
        from modules.evidence.scheduler import start_scheduler as evidence_start
        evidence_start()
    except Exception as exc:
        log.warning("Evidence scheduler failed to start: %s", exc)

    # Start reminder scheduler (auto-processes email_reminders table every 5 minutes)
    try:
        from core.reminder_scheduler import start_scheduler as reminder_start
        reminder_start()
    except Exception as exc:
        log.warning("Reminder scheduler failed to start: %s", exc)

    # ── Startup config validation ─────────────────────────────────────────────
    _provider = (settings.AI_PROVIDER or "anthropic").lower()
    if _provider == "anthropic" and not settings.ANTHROPIC_API_KEY:
        log.warning(
            "ANTHROPIC_API_KEY is not set. AI features (policy generation, "
            "risk scoring, chat) will not work until configured in .env"
        )
    if not getattr(settings, "SECRET_KEY", None):
        log.warning("SECRET_KEY not set — using auto-generated key. Sessions will break on restart.")

    log.info("ThemisIQ is ready at http://%s:%s", settings.HOST, settings.PORT)


@app.on_event("shutdown")
async def shutdown():
    try:
        from modules.grid.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    try:
        from modules.sentinel.scheduler import stop_scheduler as sentinel_stop
        sentinel_stop()
    except Exception:
        pass
    try:
        from modules.bcm.scheduler import stop_scheduler as bcm_stop
        bcm_stop()
    except Exception:
        pass
    try:
        from modules.evidence.scheduler import stop_scheduler as evidence_stop
        evidence_stop()
    except Exception:
        pass
    try:
        from core.reminder_scheduler import stop_scheduler as reminder_stop
        reminder_stop()
    except Exception:
        pass
    log.info("ThemisIQ shutting down")


# -- Health / readiness probes ------------------------------------------------
# Unauthenticated by design — used by load balancers / orchestrators.
# /health is liveness (process up); /ready is readiness (DB reachable).

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    try:
        db = get_db()
        try:
            db.execute("SELECT 1").fetchone()
        finally:
            db.close()
        return {"status": "ready"}
    except Exception as exc:
        log.warning("Readiness probe failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": str(exc)},
        )


_DEMO_CORS = {"Access-Control-Allow-Origin": "https://themisiq.net",
               "Access-Control-Allow-Methods": "POST, OPTIONS",
               "Access-Control-Allow-Headers": "Content-Type"}


@app.options("/api/demo-request")
async def demo_request_preflight():
    return JSONResponse({}, headers=_DEMO_CORS)


@app.post("/api/demo-request")
async def demo_request(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid request."}, status_code=400, headers=_DEMO_CORS)

    name    = (body.get("name") or "").strip()
    email   = (body.get("email") or "").strip()
    company = (body.get("company") or "").strip()
    plan    = (body.get("plan") or "").strip()

    if not name or not email or "@" not in email:
        return JSONResponse({"ok": False, "error": "Name and valid email are required."}, status_code=422, headers=_DEMO_CORS)

    log.info("Demo request: name=%s email=%s company=%s plan=%s", name, email, company, plan)

    try:
        from core.email import send_email
        admin_to = settings.ADMIN_EMAIL or settings.SMTP_USER
        if admin_to:
            plan_line = f"<p><strong>Plan interested in:</strong> {plan}</p>" if plan else ""
            send_email(
                to=admin_to,
                subject=f"Demo Request: {name} ({company or 'no company'})",
                body_html=(
                    f"<h2>New Demo Request</h2>"
                    f"<p><strong>Name:</strong> {name}</p>"
                    f"<p><strong>Email:</strong> {email}</p>"
                    f"<p><strong>Company:</strong> {company or 'Not provided'}</p>"
                    f"{plan_line}"
                ),
                body_text=f"Demo request\nName: {name}\nEmail: {email}\nCompany: {company}\nPlan: {plan}",
            )
    except Exception as exc:
        log.warning("Demo request email failed (request still logged): %s", exc)

    return JSONResponse({"ok": True}, headers=_DEMO_CORS)


# -- Routers ------------------------------------------------------------------
from modules.launcher.routes import router as launcher_router
from modules.launcher.routes_super_admin import router as super_admin_router
from modules.launcher.routes_api_v1 import router as api_v1_router
from modules.aria.routes import router as aria_router
from modules.grid.routes import router as grid_router
from modules.bcm.routes import router as bcm_router
from modules.sentinel.routes import router as sentinel_router
from modules.evidence.routes import router as evidence_router
from modules.erm.routes import router as erm_router
from modules.orm.routes import router as orm_router

app.include_router(super_admin_router)
app.include_router(api_v1_router)
app.include_router(launcher_router)
app.include_router(aria_router)
app.include_router(grid_router)
app.include_router(bcm_router)
app.include_router(sentinel_router)
app.include_router(evidence_router)
app.include_router(erm_router)
app.include_router(orm_router)


# -- SPA catch-all routes (must be AFTER module routers) ---------------------
# GRID, BCM, and Sentinel are SPAs: one HTML template serves all sub-paths.
# Without catch-all routes, sidebar links like /sentinel/ropa return 404.

@app.get("/sentinel/{path:path}", response_class=HTMLResponse)
async def sentinel_spa_fallback(request: Request, path: str):
    """Catch-all for Sentinel SPA sub-paths."""
    if path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "API endpoint not found"})
    from modules.sentinel.routes import sentinel_index
    return await sentinel_index(request)


@app.get("/grid/{path:path}", response_class=HTMLResponse)
async def grid_spa_fallback(request: Request, path: str):
    """Catch-all for GRID SPA sub-paths."""
    if path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "API endpoint not found"})
    from modules.grid.routes import grid_index
    return await grid_index(request)


@app.get("/bcm/{path:path}", response_class=HTMLResponse)
async def bcm_spa_fallback(request: Request, path: str):
    """Catch-all for BCM SPA sub-paths."""
    if path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "API endpoint not found"})
    from modules.bcm.routes import bcm_spa
    return await bcm_spa(request)


@app.get("/erm/{path:path}", response_class=HTMLResponse)
async def erm_spa_fallback(request: Request, path: str):
    """Catch-all for ERM SPA sub-paths."""
    if path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "API endpoint not found"})
    from modules.erm.routes import erm_spa
    return await erm_spa(request)


@app.get("/orm/{path:path}", response_class=HTMLResponse)
async def orm_spa_fallback(request: Request, path: str):
    """Catch-all for ORM SPA sub-paths."""
    if path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "API endpoint not found"})
    from modules.orm.routes import orm_spa
    return await orm_spa(request)


# -- Global error handler ----------------------------------------------------

@app.exception_handler(OperationalError)
async def db_lock_handler(request: Request, exc: OperationalError):
    """Convert SQLite write-lock timeouts into a friendly 503 so the UI
    can show 'please retry' instead of an unhandled crash page."""
    msg = str(exc).lower()
    if "database is locked" in msg or "unable to open database" in msg:
        log.warning("DB lock on %s %s — returning 503 retry", request.method, request.url.path)
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "detail": "The system is briefly busy processing another request. "
                          "Please retry in a moment.",
                "retry": True,
            },
            headers={"Retry-After": "2"},
        )
    # Unexpected SQLite error — log it and return a generic 500
    log.exception("Unexpected SQLite error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "detail": "A database error occurred. Please contact support."},
    )


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    return JSONResponse(
        status_code=403,
        content={"detail": "You do not have permission to access this resource."},
    )


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"detail": "The requested resource was not found."},
    )


# -- Run ------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level="info",
    )
