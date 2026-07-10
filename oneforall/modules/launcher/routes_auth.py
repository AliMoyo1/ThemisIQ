"""
Launcher sub-router: Authentication — Login, Logout, Change Password, /api/auth/me.
"""
import hashlib
import hmac
import re
import secrets
from fastapi import APIRouter, Request, Form
from core.sanitize import sanitize_str as _s
from fastapi.responses import HTMLResponse, RedirectResponse

from modules.launcher._route_helpers import (
    _JSONResp, require_auth, get_current_user, generate_csrf_token,
    validate_csrf, check_rate_limit, record_failed_login, clear_login_attempts,
    log_audit, authenticate_user, create_session, destroy_session,
    hash_password, verify_password, _must_change_pw,
    settings, templates, shell_templates, shell_ctx, get_db,
)
from modules.sentinel.data_service import get_setting  # org policy (settings table)
from core.mfa import mfa_required_for

router = APIRouter()

_SECURE = not settings.DEBUG  # Require HTTPS cookies in production


def _pw_change_csrf(request: Request) -> str:
    """Derive a CSRF token for the change-password page from the session cookie.

    Uses HMAC so the token is bound to the session without needing a separate
    CSRF cookie — avoids breakage when the cookie is stripped by a proxy or
    lost in the redirect chain.
    """
    session_tok = request.cookies.get(settings.SESSION_COOKIE_NAME, "")
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"change-password:{session_tok}".encode(),
        hashlib.sha256,
    ).hexdigest()


# ── Password complexity ─────────────────────────────────────────────────────

_PW_MIN_LEN = 8
_PW_RULES = [
    (r"[A-Z]", "at least one uppercase letter"),
    (r"[a-z]", "at least one lowercase letter"),
    (r"[0-9]", "at least one digit"),
    (r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", "at least one special character"),
]


def _validate_password(pw: str) -> str | None:
    """Return an error message if pw is weak, else None."""
    if len(pw) < _PW_MIN_LEN:
        return f"Password must be at least {_PW_MIN_LEN} characters."
    for pattern, desc in _PW_RULES:
        if not re.search(pattern, pw):
            return f"Password must contain {desc}."
    return None


# ── Login ────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = await get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=303)
    csrf = generate_csrf_token()
    response = templates.TemplateResponse(request, "login.html", _login_ctx(csrf))
    response.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600, secure=_SECURE)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


def _login_ctx(csrf: str, error: str | None = None) -> dict:
    return {
        "error": error,
        "csrf_token": csrf,
        "posthog_api_key": settings.POSTHOG_API_KEY,
        "posthog_host": settings.POSTHOG_HOST,
    }


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request,
                       username: str = Form(...),
                       password: str = Form(...),
                       csrf_token: str = Form("")):
    # CSRF check
    if not validate_csrf(request, csrf_token):
        csrf = generate_csrf_token()
        resp = templates.TemplateResponse(request, "login.html",
                                          _login_ctx(csrf, "Invalid request. Please try again."))
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600, secure=_SECURE)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    # Rate limit
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        csrf = generate_csrf_token()
        resp = templates.TemplateResponse(request, "login.html",
                                          _login_ctx(csrf, "Too many login attempts. Please wait 5 minutes."))
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600, secure=_SECURE)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    username = _s(username)
    user = authenticate_user(username, password)
    if not user:
        record_failed_login(client_ip)
        log_audit(None, "platform", "login_failed",
                  details=f"username={username}", ip=client_ip)
        csrf = generate_csrf_token()
        resp = templates.TemplateResponse(request, "login.html",
                                          _login_ctx(csrf, "Invalid username or password."))
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600, secure=_SECURE)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    # Successful login — clear rate limit history for this IP
    clear_login_attempts(client_ip)

    from core import mfa as mfa_helper
    enrolled = mfa_helper.is_enabled(user["id"])
    # Org policy can require MFA even if the user hasn't opted in.
    policy = (get_setting("security.require_mfa", "off") or "off").strip().lower()
    policy_requires = (not enrolled) and mfa_required_for(user, policy)
    needs_mfa = enrolled or policy_requires

    token = create_session(
        user["id"], ip=client_ip,
        user_agent=request.headers.get("user-agent", ""),
        mfa_pending=needs_mfa,
    )
    log_audit(user, "platform", "login_pending_mfa" if needs_mfa else "login",
              details=f"mfa_policy={policy}" if policy_requires else None,
              ip=client_ip)

    if needs_mfa:
        # If the user hasn't actually enrolled yet (policy-enforced), send them
        # to setup rather than the verify page (which would bounce them home).
        target = "/mfa/setup" if policy_requires else "/mfa/verify"
    elif user.get("must_change_password"):
        target = "/change-password"
    else:
        target = "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        settings.SESSION_COOKIE_NAME, token,
        httponly=True, samesite="strict", path="/",
        secure=_SECURE, max_age=settings.SESSION_MAX_AGE,
    )
    return response


# ── Logout ───────────────────────────────────────────────────────────────────

@router.post("/logout")
@require_auth
async def logout(request: Request):
    """POST-only logout to prevent CSRF-based logouts."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    user = request.state.user
    log_audit(user, "platform", "logout",
              ip=request.client.host if request.client else "")
    destroy_session(token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/", samesite="strict", secure=_SECURE)
    return response


@router.get("/logout")
async def logout_get(request: Request):
    """GET /logout — redirect to login without destroying the session.

    Destroying the session on GET is vulnerable to logout-CSRF via <img> tags.
    Users must POST to /logout (from the sidebar button) to actually sign out.
    """
    return RedirectResponse("/login", status_code=303)


# ── Profile Page ─────────────────────────────────────────────────────────────

@router.get("/profile", response_class=HTMLResponse)
@require_auth
async def profile_page(request: Request):
    user = request.state.user
    db = get_db()
    try:
        sessions = db.execute(
            "SELECT id, created_at, last_active FROM sessions WHERE user_id = %s ORDER BY last_active DESC LIMIT 10",
            (user["id"],)
        ).fetchall()
        session_count = len(sessions)
    except Exception:
        sessions = []
        session_count = 0
    finally:
        db.close()
    ctx = shell_ctx(request, active_module="platform", active_section="profile", show_sidebar=False)
    ctx["profile_user"] = user
    ctx["sessions"] = [dict(s) for s in sessions]
    ctx["session_count"] = session_count
    return shell_templates.TemplateResponse(request, "profile.html", ctx)


# ── Change Password ─────────────────────────────────────────────────────────

@router.get("/change-password", response_class=HTMLResponse)
@require_auth
async def change_password_page(request: Request):
    user = request.state.user
    csrf = _pw_change_csrf(request)
    ctx = shell_ctx(request, active_module="platform", active_section="", show_sidebar=False)
    ctx["forced"] = _must_change_pw(user["id"])
    ctx["csrf_token"] = csrf
    response = shell_templates.TemplateResponse(request, "change_password.html", ctx)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


@router.post("/change-password", response_class=HTMLResponse)
@require_auth
async def change_password_submit(request: Request,
                                  current_password: str = Form(""),
                                  new_password: str = Form(...),
                                  confirm_password: str = Form(...),
                                  csrf_token: str = Form("")):
    user = request.state.user
    forced = _must_change_pw(user["id"])
    ctx = shell_ctx(request, active_module="platform", active_section="", show_sidebar=False)
    ctx["forced"] = forced

    # CSRF: token is derived from the session cookie via HMAC, so no separate
    # CSRF cookie is needed and cookie-delivery issues can't break this.
    expected_csrf = _pw_change_csrf(request)
    if not secrets.compare_digest(expected_csrf, csrf_token or ""):
        ctx["csrf_token"] = expected_csrf
        ctx["error"] = "Invalid request. Please try again."
        resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        return resp

    # Re-derive for re-renders on later validation errors.
    csrf = expected_csrf
    ctx["csrf_token"] = csrf

    if not forced and not check_rate_limit(f"pw:{user['id']}"):
        ctx["error"] = "Too many failed attempts. Please wait 5 minutes."
        resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    if new_password != confirm_password:
        ctx["error"] = "The two new password fields don't match."
        resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    # Password complexity check
    pw_error = _validate_password(new_password)
    if pw_error:
        ctx["error"] = pw_error
        resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp

    db = get_db()
    try:
        row = db.execute(
            "SELECT password_hash FROM users WHERE id=%s", (int(user["id"]),)
        ).fetchone()
        if not forced:
            if not current_password or not verify_password(current_password, row["password_hash"]):
                record_failed_login(f"pw:{user['id']}")
                ctx["error"] = "Current password is incorrect."
                resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
                resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600, secure=_SECURE)
                return resp

        # Prevent reusing the same password
        if verify_password(new_password, row["password_hash"]):
            ctx["error"] = "New password must be different from your current password."
            resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
            resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600, secure=_SECURE)
            return resp

        db.execute(
            "UPDATE users SET password_hash=%s, must_change_password=0 WHERE id=%s",
            (hash_password(new_password), int(user["id"])),
        )
        db.commit()
        clear_login_attempts(f"pw:{user['id']}")
        log_audit(user, "platform", "Changed own password",
                  "user", user["id"])
    finally:
        db.close()

    return RedirectResponse("/", status_code=302)


# ── Auth API ────────────────────────────────────────────────────────────────

@router.get("/api/auth/me")
@require_auth
async def api_auth_me(request: Request):
    """Return current user info as JSON."""
    u = request.state.user
    return _JSONResp({
        "id": u["id"],
        "username": u["username"],
        "full_name": u.get("full_name", ""),
        "email": u.get("email", ""),
        "avatar_initials": u.get("avatar_initials", ""),
    })


# ── Two-Factor Authentication ───────────────────────────────────────────────

from core import mfa as mfa_helper
from core.auth import promote_mfa_session


@router.get("/mfa/verify", response_class=HTMLResponse)
async def mfa_verify_page(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.get("mfa_pending"):
        return RedirectResponse("/", status_code=303)
    csrf = generate_csrf_token()
    resp = templates.TemplateResponse(request, "mfa_verify.html", {
        "csrf_token": csrf,
    })
    resp.set_cookie("csrf_token", csrf, httponly=True, samesite="lax",
                    path="/", max_age=3600, secure=_SECURE)
    return resp


@router.post("/mfa/verify", response_class=HTMLResponse)
async def mfa_verify_submit(request: Request,
                             code: str = Form(...),
                             csrf_token: str = Form("")):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not user.get("mfa_pending"):
        return RedirectResponse("/", status_code=303)

    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(f"mfa:{client_ip}"):
        csrf = generate_csrf_token()
        resp = templates.TemplateResponse(request, "mfa_verify.html", {
            "csrf_token": csrf,
            "error": "Too many failed attempts. Please wait 5 minutes.",
        })
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="lax",
                        path="/", max_age=3600, secure=_SECURE)
        return resp

    if not validate_csrf(request, csrf_token):
        csrf = generate_csrf_token()
        resp = templates.TemplateResponse(request, "mfa_verify.html", {
            "csrf_token": csrf,
            "error": "Invalid request. Please try again.",
        })
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="lax",
                        path="/", max_age=3600, secure=_SECURE)
        return resp

    if not mfa_helper.verify_code(user["id"], code):
        record_failed_login(f"mfa:{client_ip}")
        csrf = generate_csrf_token()
        resp = templates.TemplateResponse(request, "mfa_verify.html", {
            "csrf_token": csrf,
            "error": "That code didn't match. Try again or use a backup code.",
        })
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="lax",
                        path="/", max_age=3600, secure=_SECURE)
        return resp

    clear_login_attempts(f"mfa:{client_ip}")
    token = request.cookies.get(settings.SESSION_COOKIE_NAME, "")
    promote_mfa_session(token)
    log_audit(user, "platform", "mfa_verified", "user", user["id"])
    target = "/change-password" if user.get("must_change_password") else "/"
    return RedirectResponse(target, status_code=303)


@router.get("/mfa/setup", response_class=HTMLResponse)
@require_auth
async def mfa_setup_page(request: Request):
    user = request.state.user
    csrf = generate_csrf_token()
    ctx = shell_ctx(request, active_module="platform", active_section="security")
    ctx["csrf_token"] = csrf
    ctx["mfa_active"] = mfa_helper.is_enabled(user["id"])
    policy = (get_setting("security.require_mfa", "off") or "off").strip().lower()
    ctx["mfa_required_by_policy"] = mfa_required_for(user, policy)
    if ctx["mfa_active"]:
        row = mfa_helper.get_mfa_row(user["id"]) or {}
        ctx["enrolled_at"] = row.get("enrolled_at")
    else:
        secret, codes = mfa_helper.start_enrollment(user["id"])
        ctx["secret"] = secret
        ctx["qr"] = mfa_helper.qr_png_data_uri(user["username"], secret)
        ctx["backup_codes"] = codes
    resp = shell_templates.TemplateResponse(request, "mfa_setup.html", ctx)
    resp.set_cookie("csrf_token", csrf, httponly=True, samesite="lax",
                    path="/", max_age=3600, secure=_SECURE)
    return resp


@router.post("/mfa/enable", response_class=HTMLResponse)
@require_auth
async def mfa_enable_submit(request: Request,
                             code: str = Form(...),
                             csrf_token: str = Form("")):
    user = request.state.user
    if not validate_csrf(request, csrf_token):
        return RedirectResponse("/mfa/setup", status_code=303)
    if mfa_helper.confirm_enrollment(user["id"], code):
        log_audit(user, "platform", "mfa_enabled", "user", user["id"])
        return RedirectResponse("/mfa/setup?ok=1", status_code=303)
    return RedirectResponse("/mfa/setup?bad=1", status_code=303)


@router.post("/mfa/disable", response_class=HTMLResponse)
@require_auth
async def mfa_disable_submit(request: Request,
                              password: str = Form(...),
                              csrf_token: str = Form("")):
    user = request.state.user
    if not validate_csrf(request, csrf_token):
        return RedirectResponse("/mfa/setup", status_code=303)
    db = get_db()
    try:
        row = db.execute(
            "SELECT password_hash FROM users WHERE id=%s", (int(user["id"]),)
        ).fetchone()
    finally:
        db.close()
    if not row or not verify_password(password, row["password_hash"]):
        return RedirectResponse("/mfa/setup?badpw=1", status_code=303)
    mfa_helper.disable(user["id"])
    log_audit(user, "platform", "mfa_disabled", "user", user["id"])
    return RedirectResponse("/mfa/setup?off=1", status_code=303)
