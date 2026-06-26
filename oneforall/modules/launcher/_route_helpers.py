"""
Shared imports, helpers, and decorators used across launcher sub-routers.
"""
import csv
import hashlib
import io
import json as json_lib
import secrets
import string
from datetime import datetime

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from config import settings
from core.auth import authenticate_user, create_session, destroy_session, hash_password, verify_password
from core.middleware import (
    get_current_user, require_auth, require_capability, generate_csrf_token,
    session_csrf_token,
    validate_csrf, check_rate_limit, record_failed_login, clear_login_attempts,
    log_audit,
    require_capability as _require_cap,
)
# Backward compat alias
record_login_attempt = record_failed_login
from core.rbac import (
    user_modules, has_capability, ROLE_LABELS, user_capabilities,
    ALL_ROLES, ROLE_DESCRIPTIONS, ROLE_CHIP_TONE, EMPLOYEE,
)
from core.shell_context import shell_ctx
from database import get_db

# Alias used across many routes
_JSONResp = JSONResponse

# Template directories
templates = Jinja2Templates(directory="modules/launcher/templates")
shell_templates = Jinja2Templates(directory=["templates", "modules/launcher/templates"])

# Register shared Jinja2 filters
from core.timeutils import format_dt as _format_dt
templates.env.filters["format_dt"] = _format_dt
shell_templates.env.filters["format_dt"] = _format_dt

# ── Shared utility functions ────────────────────────────────────────────────

_TEMP_PW_ALPHA = string.ascii_letters + string.digits + "!@#$%"


def _gen_temp_password(length: int = 12) -> str:
    """Generate a human-friendly one-time password for admin handoff."""
    return "".join(secrets.choice(_TEMP_PW_ALPHA) for _ in range(length))


def _must_change_pw(uid: int) -> bool:
    db = get_db()
    try:
        row = db.execute(
            "SELECT must_change_password FROM users WHERE id=%s", (uid,)
        ).fetchone()
        return bool(row and row["must_change_password"])
    finally:
        db.close()


def _render_admin_users(request, user, flash=None):
    db = get_db()
    try:
        is_super = bool(user.get("is_super_admin"))
        # Platform super-admins see everyone; org-level admins see only their org.
        caller_org_id = None if is_super else user.get("org_id")
        if caller_org_id is not None:
            raw_users = db.execute(
                "SELECT u.id, u.username, u.email, u.full_name, u.is_active, "
                "u.must_change_password, u.created_at, u.last_login, u.avatar_initials, "
                "u.org_id, o.name AS org_name, o.slug AS org_slug, o.plan AS org_plan "
                "FROM users u LEFT JOIN organizations o ON o.id=u.org_id "
                "WHERE u.org_id=%s ORDER BY u.is_active DESC, u.username",
                (caller_org_id,),
            ).fetchall()
        else:
            raw_users = db.execute(
                "SELECT u.id, u.username, u.email, u.full_name, u.is_active, "
                "u.must_change_password, u.created_at, u.last_login, u.avatar_initials, "
                "u.org_id, o.name AS org_name, o.slug AS org_slug, o.plan AS org_plan "
                "FROM users u LEFT JOIN organizations o ON o.id=u.org_id "
                "ORDER BY o.name NULLS LAST, u.is_active DESC, u.username"
            ).fetchall()
        rows = []
        for u in raw_users:
            role_rows = db.execute(
                "SELECT role_key FROM user_roles WHERE user_id=%s ORDER BY role_key",
                (u["id"],),
            ).fetchall()
            rows.append({**dict(u), "role_keys": [r[0] for r in role_rows]})

        # Group users by organization when super admin
        orgs_grouped = []
        all_orgs = []
        if is_super:
            from collections import OrderedDict
            grouped = OrderedDict()
            for r in rows:
                key = r.get("org_id") or 0
                if key not in grouped:
                    grouped[key] = {
                        "org_id":          r.get("org_id"),
                        "org_name":        r.get("org_name") or "Unassigned",
                        "org_slug":        r.get("org_slug") or "",
                        "org_plan":        r.get("org_plan") or "",
                        "users":           [],
                        "active_count":    0,
                        "inactive_count":  0,
                        "pw_pending_count": 0,
                    }
                grouped[key]["users"].append(r)
                if r.get("is_active"):
                    grouped[key]["active_count"] += 1
                else:
                    grouped[key]["inactive_count"] += 1
                if r.get("must_change_password"):
                    grouped[key]["pw_pending_count"] += 1
            orgs_grouped = list(grouped.values())
            # All orgs (for the New User org selector, includes orgs with zero users)
            org_rows = db.execute(
                "SELECT id, name, slug FROM organizations "
                "WHERE status='active' ORDER BY name"
            ).fetchall()
            all_orgs = [{"id": o["id"], "name": o["name"], "slug": o["slug"]}
                        for o in org_rows]
    finally:
        db.close()

    csrf_token = session_csrf_token(request) or generate_csrf_token()
    ctx = shell_ctx(request, active_module="platform", active_section="users", show_sidebar=True)
    ctx.update({
        "users":         rows,
        "orgs_grouped":  orgs_grouped,
        "all_orgs":      all_orgs,
        "is_super":      is_super,
        "all_roles":     ALL_ROLES,
        "role_labels":   ROLE_LABELS,
        "role_descriptions": ROLE_DESCRIPTIONS,
        "role_chip_tone":    ROLE_CHIP_TONE,
        "csrf_token":    csrf_token,
        "flash":         flash or {},
        # Stats for the summary strip
        "stat_total":      len(rows),
        "stat_active":     sum(1 for u in rows if u["is_active"]),
        "stat_inactive":   sum(1 for u in rows if not u["is_active"]),
        "stat_pw_pending": sum(1 for u in rows if u["must_change_password"]),
        "stat_orgs":       len(orgs_grouped),
    })
    response = shell_templates.TemplateResponse(request, "admin_users.html", ctx)
    # Legacy double-submit cookie for any forms still using it.
    response.set_cookie("csrf_token", csrf_token,
                        httponly=True, samesite="lax", path="/", max_age=3600,
                        secure=not settings.DEBUG)
    return response


def _hash_api_key(key: str) -> str:
    import os
    salt = os.environ.get("SECRET_KEY", "fallback-hmac-key").encode()
    return hashlib.pbkdf2_hmac("sha256", key.encode(), salt, 100_000).hex()
