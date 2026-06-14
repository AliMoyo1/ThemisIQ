"""
Launcher sub-router: Authentication — Login, Logout, Change Password, /api/auth/me.
"""
import re
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from modules.launcher._route_helpers import (
    _JSONResp, require_auth, get_current_user, generate_csrf_token,
    validate_csrf, check_rate_limit, record_failed_login, clear_login_attempts,
    log_audit, authenticate_user, create_session, destroy_session,
    hash_password, verify_password, _must_change_pw,
    settings, templates, shell_templates, shell_ctx, get_db,
)

router = APIRouter()


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
    response = templates.TemplateResponse(request, "login.html", {
        "error": None,
        "csrf_token": csrf,
    })
    response.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request,
                       username: str = Form(...),
                       password: str = Form(...),
                       csrf_token: str = Form("")):
    # CSRF check
    if not validate_csrf(request, csrf_token):
        csrf = generate_csrf_token()
        resp = templates.TemplateResponse(request, "login.html", {
            "error": "Invalid request. Please try again.",
            "csrf_token": csrf,
        })
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600)
        return resp

    # Rate limit
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(client_ip):
        csrf = generate_csrf_token()
        resp = templates.TemplateResponse(request, "login.html", {
            "error": "Too many login attempts. Please wait 5 minutes.",
            "csrf_token": csrf,
        })
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600)
        return resp

    user = authenticate_user(username.strip(), password)
    if not user:
        # Only record FAILED attempts for rate limiting
        record_failed_login(client_ip)
        csrf = generate_csrf_token()
        resp = templates.TemplateResponse(request, "login.html", {
            "error": "Invalid username or password.",
            "csrf_token": csrf,
        })
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600)
        return resp

    # Successful login — clear rate limit history for this IP
    clear_login_attempts(client_ip)

    token = create_session(user["id"], ip=client_ip,
                           user_agent=request.headers.get("user-agent", ""))
    log_audit(user, "platform", "login", ip=client_ip)

    # Redirect to change-password if forced, else to dashboard
    target = "/change-password" if user.get("must_change_password") else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        settings.SESSION_COOKIE_NAME, token,
        httponly=True, samesite="strict",
        max_age=settings.SESSION_MAX_AGE,
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
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return response


@router.get("/logout")
async def logout_get(request: Request):
    """GET /logout — redirect to login (no direct logout via GET for CSRF safety)."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    user = await get_current_user(request)
    if user:
        log_audit(user, "platform", "logout",
                  ip=request.client.host if request.client else "")
    destroy_session(token)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return response


# ── Change Password ─────────────────────────────────────────────────────────

@router.get("/change-password", response_class=HTMLResponse)
@require_auth
async def change_password_page(request: Request):
    user = request.state.user
    csrf = generate_csrf_token()
    ctx = shell_ctx(request, active_module="platform", active_section="", show_sidebar=False)
    ctx["forced"] = _must_change_pw(user["id"])
    ctx["csrf_token"] = csrf
    response = shell_templates.TemplateResponse(request, "change_password.html", ctx)
    response.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600)
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

    # CSRF validation
    if not validate_csrf(request, csrf_token):
        csrf = generate_csrf_token()
        ctx["csrf_token"] = csrf
        ctx["error"] = "Invalid request. Please try again."
        resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600)
        return resp

    # Generate new CSRF for re-render
    csrf = generate_csrf_token()
    ctx["csrf_token"] = csrf

    if new_password != confirm_password:
        ctx["error"] = "The two new password fields don't match."
        resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600)
        return resp

    # Password complexity check
    pw_error = _validate_password(new_password)
    if pw_error:
        ctx["error"] = pw_error
        resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
        resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600)
        return resp

    db = get_db()
    try:
        row = db.execute(
            "SELECT password_hash FROM users WHERE id=%s", (int(user["id"]),)
        ).fetchone()
        if not forced:
            if not current_password or not verify_password(current_password, row["password_hash"]):
                ctx["error"] = "Current password is incorrect."
                resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
                resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600)
                return resp

        # Prevent reusing the same password
        if verify_password(new_password, row["password_hash"]):
            ctx["error"] = "New password must be different from your current password."
            resp = shell_templates.TemplateResponse(request, "change_password.html", ctx)
            resp.set_cookie("csrf_token", csrf, httponly=True, samesite="strict", path="/", max_age=3600)
            return resp

        db.execute(
            "UPDATE users SET password_hash=%s, must_change_password=0 WHERE id=%s",
            (hash_password(new_password), int(user["id"])),
        )
        db.commit()
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
