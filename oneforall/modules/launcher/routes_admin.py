"""
Admin routes — user management, audit logs, API keys, webhooks.
"""
import ipaddress
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Form
from core.sanitize import sanitize_str as _s
from fastapi.responses import HTMLResponse, RedirectResponse

from database import insert_returning_id
from modules.sentinel.data_service import get_setting, set_setting  # org policy
from modules.launcher._route_helpers import (
    _JSONResp, _require_cap, require_auth, has_capability, log_audit,
    get_db, hash_password, shell_ctx, templates, shell_templates, secrets,
    _gen_temp_password, _render_admin_users, _hash_api_key,
    generate_csrf_token, validate_csrf,
    EMPLOYEE, ALL_ROLES, ROLE_LABELS,
    csv, io, json_lib, Response,
    _json_body,)

router = APIRouter()

_SSRF_BLOCKED_PREFIXES = ("127.", "0.", "169.254.", "10.", "192.168.", "172.")


def _target_user(db, uid: int, admin: dict):
    """Return user row scoped to admin's org, or None if not found / wrong org.

    Platform super-admins (is_super_admin=1) bypass the org filter so they can
    act on any user. Org-level admins are restricted to their own org_id.
    """
    if admin.get("is_super_admin"):
        return db.execute(
            "SELECT id, username, full_name, org_id FROM users WHERE id=%s", (uid,)
        ).fetchone()
    return db.execute(
        "SELECT id, username, full_name, org_id FROM users WHERE id=%s AND org_id=%s",
        (uid, admin.get("org_id")),
    ).fetchone()


def _validate_webhook_url(url: str) -> None:
    """Raise HTTP 400 if the URL is not HTTPS or resolves to a private/loopback address."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Webhook URL must use HTTPS")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=400, detail="Invalid webhook URL")
    if host in ("localhost", "::1", "0.0.0.0"):
        raise HTTPException(status_code=400, detail="Webhook URL targets a blocked address")
    for prefix in _SSRF_BLOCKED_PREFIXES:
        if host.startswith(prefix):
            raise HTTPException(status_code=400, detail="Webhook URL targets a blocked address")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(status_code=400, detail="Webhook URL targets a blocked address")
    except ValueError:
        pass  # domain name, not an IP literal


# ── Admin User Management ───────────────────────────────────────────────────

@router.get("/admin/users", response_class=HTMLResponse)
@_require_cap("platform.manage_users")
async def admin_users_page(request: Request):
    return _render_admin_users(request, request.state.user)


@router.post("/admin/users/create")
@_require_cap("platform.manage_users")
async def admin_create_user(request: Request,
                             username: str = Form(...),
                             email: str = Form(...),
                             full_name: str = Form(...),
                             target_org_id: str = Form(""),
                             csrf_token: str = Form("")):
    admin = request.state.user
    if not validate_csrf(request, csrf_token):
        return _render_admin_users(request, admin,
            {"type": "error", "message": "Invalid request. Please try again."})
    username = _s(username or "")
    email = _s(email or "").lower()
    full_name = _s(full_name or "")
    if not (username and email and full_name):
        return _render_admin_users(request, admin,
            {"type": "error", "message": "Username, email, and full name are all required."})

    # Determine target org. Super admins may target any active org; other admins
    # can only create users in their own org.
    target_oid = admin.get("org_id")
    if admin.get("is_super_admin") and target_org_id:
        try:
            target_oid = int(target_org_id)
        except (TypeError, ValueError):
            return _render_admin_users(request, admin,
                {"type": "error", "message": "Invalid organization selection."})

    db = get_db()
    try:
        # Validate target org exists and is active (super admins only path).
        if admin.get("is_super_admin"):
            org_row = db.execute(
                "SELECT id FROM organizations WHERE id=%s AND status='active'",
                (target_oid,),
            ).fetchone()
            if not org_row:
                return _render_admin_users(request, admin,
                    {"type": "error", "message": "Target organization not found or inactive."})

        dup = db.execute(
            "SELECT id FROM users WHERE username=%s OR email=%s",
            (username, email),
        ).fetchone()
        if dup:
            return _render_admin_users(request, admin,
                {"type": "error", "message": "A user with that username or email already exists."})

        temp_pw = _gen_temp_password()
        initials = "".join(w[0].upper() for w in full_name.split()[:2]) or "?"
        new_id = insert_returning_id(db, """
            INSERT INTO users
            (username, email, full_name, password_hash, is_active,
             must_change_password, avatar_initials, org_id)
            VALUES (%s, %s, %s, %s, 1, 1, %s, %s)
        """, (username, email, full_name, hash_password(temp_pw), initials,
              target_oid))
        db.execute(
            "INSERT INTO user_roles (user_id, role_key, granted_by) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (new_id, EMPLOYEE, int(admin["id"])),
        )
        db.commit()
        log_audit(admin, "platform", "Created user " + username,
                  "user", new_id)
    finally:
        db.close()

    return _render_admin_users(request, admin, {
        "type": "new_user",
        "username": username,
        "full_name": full_name,
        "temp_password": temp_pw,
    })


@router.post("/admin/users/{uid}/roles/grant")
@_require_cap("platform.manage_users")
async def admin_grant_role(request: Request, uid: int,
                            role_key: str = Form(...),
                            csrf_token: str = Form("")):
    admin = request.state.user
    if not validate_csrf(request, csrf_token):
        return _render_admin_users(request, admin,
            {"type": "error", "message": "Invalid request. Please try again."})
    role_key = (role_key or "").strip()
    if role_key not in ALL_ROLES:
        return _render_admin_users(request, admin,
            {"type": "error", "message": "Unknown role: " + role_key})
    db = get_db()
    try:
        target = _target_user(db, uid, admin)
        if not target:
            return _render_admin_users(request, admin,
                {"type": "error", "message": "User not found."})
        db.execute(
            "INSERT INTO user_roles (user_id, role_key, granted_by) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (uid, role_key, int(admin["id"])),
        )
        db.commit()
        log_audit(admin, "platform",
                  "Granted role '" + role_key + "' to " + target["username"],
                  "user", uid, role_key)
    finally:
        db.close()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/admin/users/{uid}/roles/revoke")
@_require_cap("platform.manage_users")
async def admin_revoke_role(request: Request, uid: int,
                             role_key: str = Form(...),
                             csrf_token: str = Form("")):
    admin = request.state.user
    if not validate_csrf(request, csrf_token):
        return _render_admin_users(request, admin,
            {"type": "error", "message": "Invalid request. Please try again."})
    db = get_db()
    try:
        target = _target_user(db, uid, admin)
        if not target:
            return _render_admin_users(request, admin,
                {"type": "error", "message": "User not found."})

        # Safety: never let the last org-level admin lose their role.
        from core.rbac import SUPER_ADMIN
        if role_key == SUPER_ADMIN:
            scope_org_id = target["org_id"]
            others = db.execute(
                "SELECT COUNT(*) FROM user_roles ur "
                "JOIN users u ON u.id = ur.user_id "
                "WHERE ur.role_key=%s AND ur.user_id!=%s AND u.org_id=%s",
                (SUPER_ADMIN, uid, scope_org_id),
            ).fetchone()[0]
            if others == 0:
                return _render_admin_users(request, admin, {
                    "type": "error",
                    "message": "Cannot revoke the last admin role."
                })

        db.execute(
            "DELETE FROM user_roles WHERE user_id=%s AND role_key=%s",
            (uid, role_key),
        )
        # Ensure every user keeps at least one role.
        remaining = db.execute(
            "SELECT 1 FROM user_roles WHERE user_id=%s LIMIT 1", (uid,)
        ).fetchone()
        if not remaining:
            db.execute(
                "INSERT INTO user_roles (user_id, role_key, granted_by) "
                "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (uid, EMPLOYEE, int(admin["id"])),
            )
        db.commit()
        log_audit(admin, "platform",
                  "Revoked role '" + role_key + "' from " + target["username"],
                  "user", uid, role_key)
    finally:
        db.close()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/admin/users/{uid}/deactivate")
@_require_cap("platform.manage_users")
async def admin_deactivate_user(request: Request, uid: int,
                                 csrf_token: str = Form("")):
    admin = request.state.user
    if not validate_csrf(request, csrf_token):
        return _render_admin_users(request, admin,
            {"type": "error", "message": "Invalid request. Please try again."})
    if int(admin["id"]) == uid:
        return _render_admin_users(request, admin,
            {"type": "error", "message": "You cannot deactivate your own account."})
    db = get_db()
    try:
        target = _target_user(db, uid, admin)
        if not target:
            return _render_admin_users(request, admin,
                {"type": "error", "message": "User not found."})

        from core.rbac import SUPER_ADMIN
        is_target_admin = db.execute(
            "SELECT 1 FROM user_roles WHERE user_id=%s AND role_key=%s",
            (uid, SUPER_ADMIN),
        ).fetchone()
        if is_target_admin:
            scope_org_id = target["org_id"]
            other_active = db.execute("""
                SELECT COUNT(*) FROM users u
                JOIN user_roles ur ON ur.user_id=u.id
                WHERE ur.role_key=%s AND u.is_active=1 AND u.id!=%s AND u.org_id=%s
            """, (SUPER_ADMIN, uid, scope_org_id)).fetchone()[0]
            if other_active == 0:
                return _render_admin_users(request, admin, {
                    "type": "error",
                    "message": "Cannot deactivate the last active admin."
                })

        db.execute("UPDATE users SET is_active=0 WHERE id=%s", (uid,))
        db.commit()
        log_audit(admin, "platform",
                  "Deactivated user " + target["username"],
                  "user", uid)
    finally:
        db.close()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/admin/users/{uid}/activate")
@_require_cap("platform.manage_users")
async def admin_activate_user(request: Request, uid: int,
                               csrf_token: str = Form("")):
    admin = request.state.user
    if not validate_csrf(request, csrf_token):
        return _render_admin_users(request, admin,
            {"type": "error", "message": "Invalid request. Please try again."})
    db = get_db()
    try:
        target = _target_user(db, uid, admin)
        if not target:
            return _render_admin_users(request, admin,
                {"type": "error", "message": "User not found."})
        db.execute("UPDATE users SET is_active=1 WHERE id=%s", (uid,))
        db.commit()
        log_audit(admin, "platform",
                  "Activated user " + target["username"],
                  "user", uid)
    finally:
        db.close()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/admin/users/{uid}/reset-password")
@_require_cap("platform.manage_users")
async def admin_reset_password(request: Request, uid: int,
                                csrf_token: str = Form("")):
    admin = request.state.user
    if not validate_csrf(request, csrf_token):
        return _render_admin_users(request, admin,
            {"type": "error", "message": "Invalid request. Please try again."})
    db = get_db()
    try:
        target = _target_user(db, uid, admin)
        if not target:
            return _render_admin_users(request, admin,
                {"type": "error", "message": "User not found."})
        temp_pw = _gen_temp_password()
        db.execute(
            "UPDATE users SET password_hash=%s, must_change_password=1 WHERE id=%s",
            (hash_password(temp_pw), uid),
        )
        db.commit()
        log_audit(admin, "platform",
                  "Reset password for " + target["username"],
                  "user", uid)
    finally:
        db.close()
    return _render_admin_users(request, admin, {
        "type": "reset_pw",
        "username": target["username"],
        "full_name": target["full_name"],
        "temp_password": temp_pw,
    })


@router.patch("/api/admin/users/{uid}")
@_require_cap("platform.manage_users")
async def api_admin_patch_user(request: Request, uid: int):
    """Edit a user's full_name and/or email. Accepts JSON, returns JSON."""
    import re as _re
    admin = request.state.user

    # JSON API endpoints rely on session auth + same-origin middleware,
    # not a form token — consistent with all other /api/admin/* endpoints.

    try:
        data = await _json_body(request)
    except Exception:
        return _JSONResp({"success": False, "error": "Invalid JSON body."}, status_code=400)

    full_name = (data.get("full_name") or "").strip()
    email     = (data.get("email") or "").strip().lower()

    if not full_name:
        return _JSONResp({"success": False, "error": "Full name cannot be empty."})
    if len(full_name) > 120:
        return _JSONResp({"success": False, "error": "Full name must be 120 characters or fewer."})
    if not email or not _re.match(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$", email):
        return _JSONResp({"success": False, "error": "Enter a valid email address."})
    if len(email) > 254:
        return _JSONResp({"success": False, "error": "Email address is too long."})

    db = get_db()
    try:
        target = _target_user(db, uid, admin)
        if not target:
            return _JSONResp({"success": False, "error": "User not found."}, status_code=404)

        conflict = db.execute(
            "SELECT id FROM users WHERE email=%s AND id!=%s", (email, uid)
        ).fetchone()
        if conflict:
            return _JSONResp(
                {"success": False, "error": "That email address is already in use by another account."}
            )

        avatar_initials = "".join(w[0].upper() for w in full_name.split()[:2]) or "?"
        db.execute(
            "UPDATE users SET full_name=%s, email=%s, avatar_initials=%s, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=%s",
            (full_name, email, avatar_initials, uid),
        )
        db.commit()
        log_audit(
            admin, "platform",
            f"Updated profile for {target['username']}: full_name='{full_name}', email='{email}'",
            "user", uid,
        )
    finally:
        db.close()

    return _JSONResp({
        "success": True,
        "full_name": full_name,
        "email": email,
        "avatar_initials": avatar_initials,
    })


# ═════════════════════════════════════════════════════════════════════════════
# ADMIN — PLATFORM AUDIT LOG
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/admin/logs", response_class=HTMLResponse)
@_require_cap("platform.manage_users")
async def admin_logs_page(request: Request):
    """Platform-wide audit log page."""
    ctx = shell_ctx(request, active_module="platform", active_section="logs")
    return shell_templates.TemplateResponse(request, "admin_logs.html", ctx)


@router.get("/admin/api/logs")
@_require_cap("platform.manage_users")
async def admin_api_logs(request: Request):
    """JSON API for audit logs with filtering and pagination."""
    db = get_db()
    try:
        # Filters
        module = request.query_params.get("module", "")
        action = request.query_params.get("action", "")
        user_filter = request.query_params.get("user", "")
        date_from = request.query_params.get("from", "")
        date_to = request.query_params.get("to", "")
        page = max(1, int(request.query_params.get("page", "1")))
        per_page = min(500, max(1, int(request.query_params.get("per_page", "50"))))

        caller = getattr(request.state, "user", {}) or {}
        is_super = caller.get("is_super_admin")
        caller_org_id = caller.get("org_id")

        where_clauses = []
        params = []

        # Org isolation: non-super-admins only see their own org's logs.
        if not is_super:
            if caller_org_id is not None:
                where_clauses.append("al.org_id = %s")
                params.append(caller_org_id)
            else:
                where_clauses.append("al.user_id = %s")
                params.append(caller.get("id"))

        if module:
            where_clauses.append("al.module = %s")
            params.append(module)
        if action:
            where_clauses.append("al.action LIKE %s")
            params.append(f"%{action}%")
        if user_filter:
            where_clauses.append("(al.username LIKE %s OR u.full_name LIKE %s)")
            params.extend([f"%{user_filter}%", f"%{user_filter}%"])
        if date_from:
            where_clauses.append("al.created_at >= %s")
            params.append(date_from)
        if date_to:
            where_clauses.append("al.created_at <= %s")
            params.append(date_to + " 23:59:59")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        total = db.execute(
            f"SELECT COUNT(*) FROM audit_log al LEFT JOIN users u ON al.user_id = u.id WHERE {where_sql}",
            params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = db.execute(
            f"SELECT al.*, u.full_name FROM audit_log al "
            f"LEFT JOIN users u ON al.user_id = u.id "
            f"WHERE {where_sql} ORDER BY al.created_at DESC LIMIT %s OFFSET %s",
            params + [per_page, offset]
        ).fetchall()

        # Get distinct modules for filter dropdown (scoped to visible logs).
        modules = db.execute(
            f"SELECT DISTINCT al.module FROM audit_log al WHERE {where_sql} AND al.module IS NOT NULL ORDER BY al.module",
            params
        ).fetchall()
    finally:
        db.close()

    return _JSONResp({
        "logs": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "modules": [r["module"] for r in modules],
    })


@router.get("/admin/api/logs/export")
@_require_cap("platform.manage_users")
async def admin_api_logs_export(request: Request):
    """Export audit logs as CSV."""
    db = get_db()
    try:
        module = request.query_params.get("module", "")
        date_from = request.query_params.get("from", "")
        date_to = request.query_params.get("to", "")

        caller = getattr(request.state, "user", {}) or {}
        is_super = caller.get("is_super_admin")
        caller_org_id = caller.get("org_id")

        where_clauses = []
        params = []

        # Org isolation: non-super-admins only see their own org's logs.
        if not is_super:
            if caller_org_id is not None:
                where_clauses.append("al.org_id = %s")
                params.append(caller_org_id)
            else:
                where_clauses.append("al.user_id = %s")
                params.append(caller.get("id"))

        if module:
            where_clauses.append("al.module = %s")
            params.append(module)
        if date_from:
            where_clauses.append("al.created_at >= %s")
            params.append(date_from)
        if date_to:
            where_clauses.append("al.created_at <= %s")
            params.append(date_to + " 23:59:59")

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        rows = db.execute(
            f"SELECT al.*, u.full_name FROM audit_log al "
            f"LEFT JOIN users u ON al.user_id = u.id "
            f"WHERE {where_sql} ORDER BY al.created_at DESC",
            params
        ).fetchall()
    finally:
        db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Timestamp", "User", "Module", "Action", "Entity Type", "Entity ID", "Details", "IP Address"])
    for r in rows:
        writer.writerow([
            r["id"], r["created_at"], r["full_name"] or r["username"] or "system",
            r["module"], r["action"], r["entity_type"] or "", r["entity_id"] or "",
            r["details"] or "", r["ip_address"] or ""
        ])

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log_export.csv"}
    )


# ═════════════════════════════════════════════════════════════════════════════
# API KEY MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/admin/api-keys", response_class=HTMLResponse)
@_require_cap("platform.manage_users")
async def admin_api_keys_page(request: Request):
    """API key management page."""
    ctx = shell_ctx(request, active_module="platform", active_section="api-keys")
    return shell_templates.TemplateResponse(request, "admin_api_keys.html", ctx)


@router.get("/api/admin/api-keys")
@_require_cap("platform.manage_users")
async def api_keys_list(request: Request):
    """List all API keys (without exposing full key)."""
    db = get_db()
    try:
        org_id = request.state.user.get("org_id")
        rows = db.execute(
            "SELECT ak.id, ak.name, ak.key_prefix, ak.scopes, ak.is_active, "
            "ak.last_used_at, ak.expires_at, ak.created_at, u.full_name as creator_name "
            "FROM api_keys ak LEFT JOIN users u ON ak.created_by = u.id "
            "WHERE (ak.org_id = %s OR (ak.org_id IS NULL AND %s IS NULL)) "
            "ORDER BY ak.created_at DESC",
            (org_id, org_id),
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/admin/api-keys", status_code=201)
@_require_cap("platform.manage_users")
async def api_key_create(request: Request):
    """Generate a new API key."""
    data = await _json_body(request)

    # Generate a secure random key
    raw_key = "ofa_" + secrets.token_urlsafe(32)
    key_hash = _hash_api_key(raw_key)
    key_prefix = raw_key[:12] + "..."

    db = get_db()
    try:
        kid = insert_returning_id(
            db,
            "INSERT INTO api_keys (name, key_hash, key_prefix, scopes, expires_at, created_by, org_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                data.get("name", "Unnamed Key"),
                key_hash,
                key_prefix,
                data.get("scopes", "read"),
                data.get("expires_at"),
                request.state.user["id"],
                request.state.user.get("org_id"),
            )
        )
        db.commit()
    finally:
        db.close()
    log_audit(request.state.user, "platform", "api_key_create", details=f"Created API key: {data.get('name')}")
    # Return the full key ONLY on creation
    return _JSONResp({"id": kid, "key": raw_key, "prefix": key_prefix}, status_code=201)


@router.delete("/api/admin/api-keys/{kid}")
@_require_cap("platform.manage_users")
async def api_key_revoke(request: Request, kid: int):
    """Revoke an API key (org-scoped)."""
    user = request.state.user
    org_id = user.get("org_id")
    db = get_db()
    try:
        if user.get("is_super_admin"):
            row = db.execute("SELECT name, key_prefix FROM api_keys WHERE id = %s", (kid,)).fetchone()
        else:
            row = db.execute(
                "SELECT name, key_prefix FROM api_keys WHERE id = %s AND org_id = %s",
                (kid, org_id),
            ).fetchone()
        if not row:
            return _JSONResp({"success": False, "error": "Not found"}, status_code=404)
        db.execute("UPDATE api_keys SET is_active = 0 WHERE id = %s", (kid,))
        db.commit()
    finally:
        db.close()
    label = f"{row['name']} ({row['key_prefix']}...)"
    log_audit(user, "platform", "api_key_revoke", details=f"Revoked API key: {label}")
    return _JSONResp({"success": True})


# ═════════════════════════════════════════════════════════════════════════════
# WEBHOOKS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/admin/webhooks", response_class=HTMLResponse)
@_require_cap("platform.manage_users")
async def admin_webhooks_page(request: Request):
    """Webhook management page."""
    ctx = shell_ctx(request, active_module="platform", active_section="webhooks")
    return shell_templates.TemplateResponse(request, "admin_webhooks.html", ctx)


@router.get("/api/admin/webhooks")
@_require_cap("platform.manage_users")
async def api_webhooks_list(request: Request):
    """List webhooks scoped to the caller's org."""
    user = request.state.user
    org_id = user.get("org_id")
    db = get_db()
    try:
        if user.get("is_super_admin"):
            rows = db.execute(
                "SELECT w.*, u.full_name as creator_name "
                "FROM webhooks w LEFT JOIN users u ON w.created_by = u.id "
                "ORDER BY w.created_at DESC"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT w.*, u.full_name as creator_name "
                "FROM webhooks w LEFT JOIN users u ON w.created_by = u.id "
                "WHERE w.org_id = %s ORDER BY w.created_at DESC",
                (org_id,),
            ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/admin/webhooks", status_code=201)
@_require_cap("platform.manage_users")
async def api_webhook_create(request: Request):
    """Create a webhook."""
    data = await _json_body(request)
    _validate_webhook_url(data.get("url", ""))
    webhook_secret = secrets.token_urlsafe(24)

    db = get_db()
    try:
        wid = insert_returning_id(
            db,
            "INSERT INTO webhooks (name, url, secret, events, created_by, org_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                data.get("name", ""),
                data.get("url", ""),
                webhook_secret,
                ",".join(data.get("events", [])),
                request.state.user["id"],
                request.state.user.get("org_id"),
            )
        )
        db.commit()
    finally:
        db.close()
    return _JSONResp({"id": wid, "secret": webhook_secret}, status_code=201)


def _get_webhook_for_admin(db, wid: int, user: dict):
    """Return webhook row only if the caller owns it (or is super admin)."""
    if user.get("is_super_admin"):
        return db.execute("SELECT * FROM webhooks WHERE id = %s", (wid,)).fetchone()
    return db.execute(
        "SELECT * FROM webhooks WHERE id = %s AND org_id = %s",
        (wid, user.get("org_id")),
    ).fetchone()


@router.put("/api/admin/webhooks/{wid}")
@_require_cap("platform.manage_users")
async def api_webhook_update(request: Request, wid: int):
    """Update a webhook."""
    data = await _json_body(request)
    user = request.state.user
    db = get_db()
    try:
        if not _get_webhook_for_admin(db, wid, user):
            return _JSONResp({"error": "Not found"}, status_code=404)
        fields, params = [], []
        if "name" in data:
            fields.append("name = %s"); params.append(data["name"])
        if "url" in data:
            _validate_webhook_url(data["url"])
            fields.append("url = %s"); params.append(data["url"])
        if "events" in data:
            fields.append("events = %s"); params.append(",".join(data["events"]))
        if "is_active" in data:
            fields.append("is_active = %s"); params.append(1 if data["is_active"] else 0)
        if fields:
            params.append(wid)
            db.execute(f"UPDATE webhooks SET {', '.join(fields)} WHERE id = %s", params)
            db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/admin/webhooks/{wid}")
@_require_cap("platform.manage_users")
async def api_webhook_delete(request: Request, wid: int):
    """Delete a webhook."""
    user = request.state.user
    db = get_db()
    try:
        row = _get_webhook_for_admin(db, wid, user)
        if not row:
            return _JSONResp({"error": "Not found"}, status_code=404)
        db.execute("DELETE FROM webhooks WHERE id = %s", (wid,))
        db.commit()
    finally:
        db.close()
    label = f"{row['name']} ({row['url']})"
    log_audit(user, "platform", "webhook_delete", details=f"Deleted webhook: {label}")
    return _JSONResp({"success": True})


@router.get("/api/admin/webhooks/{wid}/logs")
@_require_cap("platform.manage_users")
async def api_webhook_logs(request: Request, wid: int):
    """Get delivery logs for a webhook."""
    user = request.state.user
    db = get_db()
    try:
        if not _get_webhook_for_admin(db, wid, user):
            return _JSONResp({"error": "Not found"}, status_code=404)
        rows = db.execute(
            "SELECT * FROM webhook_logs WHERE webhook_id = %s ORDER BY attempted_at DESC LIMIT 50",
            (wid,)
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


@router.post("/api/admin/webhooks/{wid}/test")
@_require_cap("platform.manage_users")
async def api_webhook_test(request: Request, wid: int):
    """Send a test ping to a webhook."""
    user = request.state.user
    db = get_db()
    try:
        wh = _get_webhook_for_admin(db, wid, user)
        if not wh:
            return _JSONResp({"error": "Not found"}, status_code=404)

        payload = {"event": "test.ping", "timestamp": "now", "data": {"message": "Webhook test from ThemisIQ"}}
        db.execute(
            "INSERT INTO webhook_logs (webhook_id, event, payload_json, response_code, success) VALUES (%s,%s,%s,%s,%s)",
            (wid, "test.ping", json_lib.dumps(payload), 200, 1)
        )
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True, "message": "Test ping logged"})


# ═════════════════════════════════════════════════════════════════════════════
# ADMIN — EMAIL SETTINGS
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/admin/email", response_class=HTMLResponse)
@_require_cap("platform.manage_users")
async def admin_email_page(request: Request):
    """Email provider configuration page."""
    ctx = shell_ctx(request, active_module="platform", active_section="email")
    return shell_templates.TemplateResponse(request, "admin_email.html", ctx)


@router.get("/api/admin/email-config")
@_require_cap("platform.manage_users")
async def api_email_config_get(request: Request):
    """Return current email configuration with passwords masked."""
    from core.email import _get_setting, _resolve_provider

    provider = _resolve_provider()

    def _masked(key: str) -> str:
        val = _get_setting(key, "")
        return "__unchanged__" if val else ""

    cfg = {
        "provider":          _get_setting("email_provider", ""),
        "smtp_host":         _get_setting("smtp_host", ""),
        "smtp_port":         _get_setting("smtp_port", "587"),
        "smtp_user":         _get_setting("smtp_user", ""),
        "smtp_pass":         _masked("smtp_pass_enc"),
        "smtp_from":         _get_setting("smtp_from", ""),
        "ms_tenant_id":      _get_setting("ms_tenant_id", ""),
        "ms_client_id":      _get_setting("ms_client_id", ""),
        "ms_client_secret":  _masked("ms_client_secret_enc"),
        "resolved_provider": provider,
        "last_test_result":  _get_setting("email_last_test_result", ""),
        "last_test_at":      _get_setting("email_last_test_at", ""),
    }
    return _JSONResp(cfg)


@router.post("/api/admin/email-config")
@_require_cap("platform.manage_users")
async def api_email_config_save(request: Request):
    """Save email configuration to the settings table."""
    from core.email import encrypt_setting

    data = await _json_body(request)
    db = get_db()
    try:
        def _save(key: str, val: str):
            db.execute(
                "INSERT INTO settings(key,value) VALUES(%s,%s) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, val),
            )

        _save("email_provider", data.get("provider", "").strip().lower())
        _save("smtp_host",      data.get("smtp_host", "").strip())
        _save("smtp_port",      str(data.get("smtp_port", "587")).strip())
        _save("smtp_user",      data.get("smtp_user", "").strip())
        _save("smtp_from",      data.get("smtp_from", "").strip())
        _save("ms_tenant_id",   data.get("ms_tenant_id", "").strip())
        _save("ms_client_id",   data.get("ms_client_id", "").strip())

        # Only update passwords if a non-masked value was submitted
        raw_pass = data.get("smtp_pass", "")
        if raw_pass and raw_pass != "__unchanged__":
            _save("smtp_pass_enc", encrypt_setting(raw_pass))

        raw_secret = data.get("ms_client_secret", "")
        if raw_secret and raw_secret != "__unchanged__":
            _save("ms_client_secret_enc", encrypt_setting(raw_secret))

        db.commit()
    finally:
        db.close()

    log_audit(request.state.user, "platform", "email_config_update",
              details=f"Email provider set to: {data.get('provider','')}")
    return _JSONResp({"success": True})


@router.post("/api/admin/email-test")
@_require_cap("platform.manage_users")
async def api_email_test(request: Request):
    """Send a test email to the requesting admin's address."""
    from core.email import send_email, test_connection, _get_setting
    import datetime as _dt

    admin       = request.state.user
    admin_email = admin.get("email", "")
    if not admin_email:
        return _JSONResp({"ok": False, "detail": "Your user account has no email address set."})

    # First validate config without sending
    check = test_connection()
    if not check["ok"] and check["provider"] not in ("console",):
        _save_test_result(check.get("detail", "Connection failed"), ok=False)
        return _JSONResp({"ok": False, "provider": check.get("provider", "unknown"), "detail": "Email connection test failed"})

    # Send a real test message
    body_html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:24px">
      <div style="background:#1e3a8a;color:white;padding:16px 20px;border-radius:8px 8px 0 0;font-size:16px;font-weight:700">
        ✅ ThemisIQ — Email Test
      </div>
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 8px 8px;padding:20px">
        <p>This is a test email from <strong>ThemisIQ</strong>.</p>
        <p>If you received this, your email configuration is working correctly.</p>
        <table style="margin-top:16px;font-size:12px;color:#64748b;border-collapse:collapse">
          <tr><td style="padding:3px 10px 3px 0;font-weight:600">Sent to:</td><td>{admin_email}</td></tr>
          <tr><td style="padding:3px 10px 3px 0;font-weight:600">Sent at:</td><td>{_dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</td></tr>
          <tr><td style="padding:3px 10px 3px 0;font-weight:600">Provider:</td><td>{check['provider']}</td></tr>
        </table>
      </div>
    </div>
    """

    result = send_email(
        to=admin_email,
        subject="[ThemisIQ] Email configuration test",
        body_html=body_html,
    )

    ok = result["ok"]
    provider = result.get("provider", "unknown")
    detail = ("Sent via " + provider) if ok else "Email delivery failed"
    _save_test_result(result.get("error") or detail, ok=ok)
    log_audit(request.state.user, "platform", "email_test",
              details=f"Test email to {admin_email}: {'ok' if ok else 'failed'}")
    return _JSONResp({"ok": ok, "provider": provider, "detail": detail, "to": admin_email})


def _save_test_result(detail: str, ok: bool):
    """Persist the last test result to the settings table."""
    import datetime as _dt
    db = get_db()
    try:
        for key, val in [
            ("email_last_test_result", (("OK " if ok else "FAIL ") + detail[:200])),
            ("email_last_test_at",     _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
        ]:
            db.execute(
                "INSERT INTO settings(key,value) VALUES(%s,%s) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, val),
            )
        db.commit()
    finally:
        db.close()


@router.get("/admin/connectors", response_class=HTMLResponse)
@_require_cap("platform.manage_users")
async def admin_connectors_page(request: Request):
    """Slack and Teams webhook configuration page."""
    ctx = shell_ctx(request, active_module="platform", active_section="connectors")
    return shell_templates.TemplateResponse(request, "admin_connectors.html", ctx)


# ── Connectors (Slack / Teams) ────────────────────────────────────────────────

def _connectors_get_setting(key: str) -> str:
    db = get_db()
    try:
        row = db.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
        return row[0] if row else ""
    finally:
        db.close()


def _connectors_save(key: str, val: str):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO settings(key,value) VALUES(%s,%s) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, val),
        )
        db.commit()
    finally:
        db.close()


@router.get("/api/admin/connectors")
@_require_cap("platform.manage_users")
async def api_connectors_get(request: Request):
    """Return current Slack and Teams webhook config (URLs masked for display)."""
    def _masked(key: str) -> str:
        val = _connectors_get_setting(key)
        return "__unchanged__" if val else ""

    return _JSONResp({
        "slack_webhook_url":  _masked("slack_webhook_url"),
        "teams_webhook_url":  _masked("teams_webhook_url"),
        "slack_configured":   bool(_connectors_get_setting("slack_webhook_url")),
        "teams_configured":   bool(_connectors_get_setting("teams_webhook_url")),
    })


@router.post("/api/admin/connectors")
@_require_cap("platform.manage_users")
async def api_connectors_save(request: Request):
    """Save Slack and Teams webhook URLs to the settings table."""
    data = await _json_body(request)

    slack_url = data.get("slack_webhook_url", "")
    if slack_url and slack_url != "__unchanged__":
        try:
            _validate_webhook_url(slack_url.strip())
        except HTTPException as exc:
            return _JSONResp({"ok": False, "detail": f"Slack URL: {exc.detail}"}, status_code=400)
        _connectors_save("slack_webhook_url", slack_url.strip())

    teams_url = data.get("teams_webhook_url", "")
    if teams_url and teams_url != "__unchanged__":
        try:
            _validate_webhook_url(teams_url.strip())
        except HTTPException as exc:
            return _JSONResp({"ok": False, "detail": f"Teams URL: {exc.detail}"}, status_code=400)
        _connectors_save("teams_webhook_url", teams_url.strip())

    log_audit(request.state.user, "platform", "connectors_updated",
              details="Slack/Teams webhook URLs updated")
    return _JSONResp({"ok": True})


@router.delete("/api/admin/connectors/slack")
@_require_cap("platform.manage_users")
async def api_connectors_delete_slack(request: Request):
    """Remove the Slack webhook URL."""
    _connectors_save("slack_webhook_url", "")
    log_audit(request.state.user, "platform", "connectors_updated", details="Slack webhook removed")
    return _JSONResp({"ok": True})


@router.delete("/api/admin/connectors/teams")
@_require_cap("platform.manage_users")
async def api_connectors_delete_teams(request: Request):
    """Remove the Teams webhook URL."""
    _connectors_save("teams_webhook_url", "")
    log_audit(request.state.user, "platform", "connectors_updated", details="Teams webhook removed")
    return _JSONResp({"ok": True})


@router.post("/api/admin/connectors/test-slack")
@_require_cap("platform.manage_users")
async def api_connectors_test_slack(request: Request):
    """Send a test message to the configured Slack webhook."""
    from core.notifications import send_slack
    ok = send_slack("[ThemisIQ] Slack connector test — configuration is working.")
    return _JSONResp({"ok": ok, "detail": "Message sent" if ok else "Not configured or send failed"})


@router.post("/api/admin/connectors/test-teams")
@_require_cap("platform.manage_users")
async def api_connectors_test_teams(request: Request):
    """Send a test message to the configured Teams webhook."""
    from core.notifications import send_teams
    ok = send_teams("[ThemisIQ] Teams connector test — configuration is working.")
    return _JSONResp({"ok": ok, "detail": "Message sent" if ok else "Not configured or send failed"})


# ── Org security policy (MFA enforcement) ────────────────────────────────────

_VALID_MFA_POLICIES = ("off", "admins", "all")


@router.get("/api/admin/security-settings")
@_require_cap("platform.manage_users")
async def api_security_settings_get(request: Request):
    """Return the current org security policy (MFA requirement)."""
    policy = (get_setting("security.require_mfa", "off") or "off").strip().lower()
    if policy not in _VALID_MFA_POLICIES:
        policy = "off"
    return _JSONResp({"security": {"require_mfa": policy}})


@router.put("/api/admin/security-settings")
@_require_cap("platform.manage_users")
async def api_security_settings_put(request: Request):
    """Update the org security policy.

    Body: {"security": {"require_mfa": "off" | "admins" | "all"}}
    """
    try:
        body = await request.json()
    except Exception:
        return _JSONResp({"ok": False, "error": "Invalid JSON body."}, status_code=400)
    sec = (body or {}).get("security") or {}
    policy = (sec.get("require_mfa") or "off")
    if not isinstance(policy, str) or policy.strip().lower() not in _VALID_MFA_POLICIES:
        return _JSONResp(
            {"ok": False, "error": "require_mfa must be one of: off, admins, all."},
            status_code=400,
        )
    policy = policy.strip().lower()
    set_setting("security.require_mfa", policy)
    log_audit(request.state.user, "platform", "security_settings_updated",
              details=f"security.require_mfa={policy}")
    return _JSONResp({"ok": True, "security": {"require_mfa": policy}})


@router.get("/admin/security", response_class=HTMLResponse)
@_require_cap("platform.manage_users")
async def admin_security_page(request: Request):
    """Org security settings UI: MFA enforcement policy + per-user MFA status."""
    policy = (get_setting("security.require_mfa", "off") or "off").strip().lower()
    if policy not in _VALID_MFA_POLICIES:
        policy = "off"
    db = get_db()
    try:
        rows = db.execute(
            "SELECT u.id, u.username, u.full_name, u.email, "
            "COALESCE(um.is_enabled, 0) AS mfa_enabled "
            "FROM users u "
            "LEFT JOIN user_mfa um ON um.user_id = u.id "
            "WHERE u.is_active = 1 "
            "ORDER BY u.username"
        ).fetchall()
    finally:
        db.close()
    users = [
        {
            "id": r["id"],
            "username": r["username"],
            "full_name": r["full_name"],
            "email": r["email"],
            "mfa_enabled": bool(r["mfa_enabled"]),
        }
        for r in rows
    ]
    ctx = shell_ctx(request, active_module="platform", active_section="security")
    ctx["current_policy"] = policy
    ctx["users"] = users
    return shell_templates.TemplateResponse(request, "admin_security.html", ctx)
