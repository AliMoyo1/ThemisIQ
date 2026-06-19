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
        # Platform super-admins see everyone; org-level admins see only their org.
        caller_org_id = None if user.get("is_super_admin") else user.get("org_id")
        if caller_org_id is not None:
            raw_users = db.execute(
                "SELECT id, username, email, full_name, is_active, "
                "must_change_password, created_at, last_login, avatar_initials "
                "FROM users WHERE org_id=%s ORDER BY is_active DESC, username",
                (caller_org_id,),
            ).fetchall()
        else:
            raw_users = db.execute(
                "SELECT id, username, email, full_name, is_active, "
                "must_change_password, created_at, last_login, avatar_initials "
                "FROM users ORDER BY is_active DESC, username"
            ).fetchall()
        rows = []
        for u in raw_users:
            role_rows = db.execute(
                "SELECT role_key FROM user_roles WHERE user_id=%s ORDER BY role_key",
                (u["id"],),
            ).fetchall()
            rows.append({**dict(u), "role_keys": [r[0] for r in role_rows]})
    finally:
        db.close()

    csrf_token = generate_csrf_token()
    ctx = shell_ctx(request, active_module="platform", active_section="users", show_sidebar=True)
    ctx.update({
        "users": rows,
        "all_roles": ALL_ROLES,
        "role_labels": ROLE_LABELS,
        "role_descriptions": ROLE_DESCRIPTIONS,
        "role_chip_tone": ROLE_CHIP_TONE,
        "csrf_token": csrf_token,
        "flash": flash or {},
        # Stats for the summary strip
        "stat_total":      len(rows),
        "stat_active":     sum(1 for u in rows if u["is_active"]),
        "stat_inactive":   sum(1 for u in rows if not u["is_active"]),
        "stat_pw_pending": sum(1 for u in rows if u["must_change_password"]),
    })
    response = shell_templates.TemplateResponse(request, "admin_users.html", ctx)
    # Sync the CSRF cookie to the token embedded in the page so form-based
    # actions (role grant/revoke, reset PW, etc.) pass validate_csrf().
    response.set_cookie("csrf_token", csrf_token,
                        httponly=True, samesite="lax", path="/", max_age=3600)
    return response


def _hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
