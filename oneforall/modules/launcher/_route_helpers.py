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


def _group_users_by_bu(user_rows, bu_parent_names):
    """Bucket a list of user rows (dicts with business_unit_id/
    business_unit_name/is_active/must_change_password) by their business
    unit. Users with no business_unit_id land in a single 'Org-wide (no
    unit)' bucket, sorted last; named BUs are sorted alphabetically.

    bu_parent_names: {bu_id: parent_bu_name_or_None}, used to show each SBU's
    parent company context in the group header (e.g. 'Ecocash · under Econet').
    """
    from collections import OrderedDict
    groups = OrderedDict()
    for r in user_rows:
        bu_id = r.get("business_unit_id")
        key = bu_id or 0
        if key not in groups:
            groups[key] = {
                "bu_id": bu_id,
                "bu_name": r.get("business_unit_name") or "Org-wide (no unit)",
                "bu_parent_name": bu_parent_names.get(bu_id) if bu_id else None,
                "users": [],
                "active_count": 0,
                "inactive_count": 0,
                "pw_pending_count": 0,
            }
        groups[key]["users"].append(r)
        if r.get("is_active"):
            groups[key]["active_count"] += 1
        else:
            groups[key]["inactive_count"] += 1
        if r.get("must_change_password"):
            groups[key]["pw_pending_count"] += 1
    return sorted(groups.values(), key=lambda g: (g["bu_id"] is None, g["bu_name"].lower()))


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
                "u.org_id, o.name AS org_name, o.slug AS org_slug, o.plan AS org_plan, "
                "u.business_unit_id, "
                "(SELECT name FROM business_units WHERE id=u.business_unit_id) AS business_unit_name "
                "FROM users u LEFT JOIN organizations o ON o.id=u.org_id "
                "WHERE u.org_id=%s ORDER BY u.is_active DESC, u.username",
                (caller_org_id,),
            ).fetchall()
        else:
            raw_users = db.execute(
                "SELECT u.id, u.username, u.email, u.full_name, u.is_active, "
                "u.must_change_password, u.created_at, u.last_login, u.avatar_initials, "
                "u.org_id, o.name AS org_name, o.slug AS org_slug, o.plan AS org_plan, "
                "u.business_unit_id, "
                "(SELECT name FROM business_units WHERE id=u.business_unit_id) AS business_unit_name "
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

        # {bu_id: parent BU name or None} -- used to show each SBU's parent
        # company context in the People-management grouping below.
        bu_parent_names = {}
        try:
            for bu_row in db.execute(
                "SELECT bu.id, parent.name AS parent_name "
                "FROM business_units bu LEFT JOIN business_units parent "
                "ON parent.id = bu.parent_id"
            ).fetchall():
                bu_parent_names[bu_row["id"]] = bu_row["parent_name"]
        except Exception:
            pass

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
            for og in orgs_grouped:
                og["bu_groups"] = _group_users_by_bu(og["users"], bu_parent_names)
            # All orgs (for the New User org selector, includes orgs with zero users)
            org_rows = db.execute(
                "SELECT id, name, slug FROM organizations "
                "WHERE status='active' ORDER BY name"
            ).fetchall()
            all_orgs = [{"id": o["id"], "name": o["name"], "slug": o["slug"]}
                        for o in org_rows]

        try:
            bu_rows = db.execute(
                "SELECT id, name FROM business_units WHERE is_active=1 ORDER BY name"
            ).fetchall()
            business_units = [{"id": b["id"], "name": b["name"]} for b in bu_rows]
        except Exception:
            business_units = []

        # Top-level BU grouping for the single-org (org-admin) view. The
        # super-admin view instead nests a bu_groups list inside each entry
        # of orgs_grouped (built above), one grouping per organization.
        bu_groups = [] if is_super else _group_users_by_bu(rows, bu_parent_names)
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
        "business_units": business_units,
        "bu_groups":      bu_groups,
        "can_assign_bu":  has_capability(user, "governance.bu.assign"),
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


async def _json_body(request: Request) -> dict:
    """Parse JSON request body and sanitize all string values."""
    try:
        body = await request.json()
    except Exception:
        return {}
    from core.sanitize import sanitize_dict
    return sanitize_dict(body)
