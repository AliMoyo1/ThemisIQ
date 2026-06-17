"""
One For All — security middleware.

- Session-based auth dependency for FastAPI
- CSRF protection
- Security headers
- Rate limiting (login endpoint)
- Audit logging helper
"""
import time
import secrets
from datetime import datetime
from collections import defaultdict
from functools import wraps
from typing import Optional

from fastapi import Request, Response, HTTPException
from fastapi.responses import RedirectResponse

from config import settings
from core.auth import get_session_user
from core.rbac import has_capability, user_modules
from database import get_db


# ── Paths exempt from forced password change ────────────────────────────────
_PW_CHANGE_EXEMPT = {"/change-password", "/logout", "/api/auth/me",
                     "/static", "/favicon.ico"}


# ── Auth dependency ──────────────────────────────────────────────────────────

async def get_current_user(request: Request) -> Optional[dict]:
    """Extract user from session cookie. Returns None if not logged in."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None
    return get_session_user(token)


def require_auth(func):
    """Decorator: redirect to login if not authenticated.
    Also enforces must_change_password redirect."""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user = await get_current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        # Enforce password change before any other page
        path = request.url.path
        if user.get("must_change_password") and not any(
            path.startswith(p) for p in _PW_CHANGE_EXEMPT
        ):
            return RedirectResponse("/change-password", status_code=303)
        request.state.user = user
        return await func(request, *args, **kwargs)
    return wrapper


def require_capability(*capabilities: str):
    """Decorator factory: require at least one of the given capabilities."""
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            user = await get_current_user(request)
            if not user:
                return RedirectResponse("/login", status_code=303)
            # Enforce password change
            path = request.url.path
            if user.get("must_change_password") and not any(
                path.startswith(p) for p in _PW_CHANGE_EXEMPT
            ):
                return RedirectResponse("/change-password", status_code=303)
            if not any(has_capability(user, c) for c in capabilities):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            request.state.user = user
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_module(module: str):
    """Decorator: require access to a specific module."""
    return require_capability(f"module.{module}.access")


# ── CSRF Protection ──────────────────────────────────────────────────────────

def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def validate_csrf(request: Request, form_token: str) -> bool:
    """Validate CSRF token from form against session."""
    session_token = request.cookies.get("csrf_token")
    if not session_token or not form_token:
        return False
    return secrets.compare_digest(session_token, form_token)


# ── Rate Limiting (in-memory, per-IP) ────────────────────────────────────────

_login_attempts: dict[str, list[float]] = defaultdict(list)
_MAX_LOGIN_ATTEMPTS = 5
_WINDOW_SECONDS = 300  # 5 minutes
_LAST_CLEANUP = 0.0


def check_rate_limit(ip: str) -> bool:
    """Return True if the request is allowed, False if rate-limited."""
    global _LAST_CLEANUP
    now = time.time()
    # Periodically clean up stale IPs (every 10 min)
    if now - _LAST_CLEANUP > 600:
        stale = [k for k, v in _login_attempts.items()
                 if not v or now - v[-1] > _WINDOW_SECONDS]
        for k in stale:
            del _login_attempts[k]
        _LAST_CLEANUP = now
    attempts = _login_attempts[ip]
    # Remove old attempts
    _login_attempts[ip] = [t for t in attempts if now - t < _WINDOW_SECONDS]
    if len(_login_attempts[ip]) >= _MAX_LOGIN_ATTEMPTS:
        return False
    return True


def record_failed_login(ip: str):
    """Record a FAILED login attempt for rate-limiting purposes."""
    _login_attempts[ip].append(time.time())


def clear_login_attempts(ip: str):
    """Clear rate limit history on successful login."""
    _login_attempts.pop(ip, None)


# ── CSRF Origin Check ────────────────────────────────────────────────────────

def _is_same_origin(request: Request) -> bool:
    """Check that Origin or Referer header matches the request host.

    Returns True if:
    - The request has an Origin header matching the server, or
    - The request has a Referer header with a matching host, or
    - Neither header is present (same-origin requests from older browsers)
    """
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    if origin:
        # Origin: http://localhost:8000 or https://example.com
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        origin_host = parsed.netloc  # includes port
        return origin_host == host

    referer = request.headers.get("referer")
    if referer:
        from urllib.parse import urlparse
        parsed = urlparse(referer)
        referer_host = parsed.netloc
        return referer_host == host

    # Neither Origin nor Referer — this happens on same-origin requests
    # from some browsers. Combined with SameSite=Strict cookies, this is safe.
    return True


async def csrf_origin_middleware(request: Request, call_next):
    """Reject cross-origin mutating requests (defense-in-depth).

    All POST/PUT/DELETE/PATCH requests must come from the same origin.
    This blocks CSRF even if SameSite cookies are somehow bypassed.
    Login is excluded because it's the entry point before a session exists.
    """
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        path = request.url.path
        # Public endpoints with no session to protect
        _CSRF_EXEMPT = {"/login", "/api/demo-request"}
        if path not in _CSRF_EXEMPT:
            if not _is_same_origin(request):
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin request blocked."},
                )
    return await call_next(request)


# ── Security Headers ─────────────────────────────────────────────────────────

async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)

    # Long-lived cache for immutable static assets (JS, CSS, fonts, images).
    # Auth pages set their own no-store header which takes precedence.
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"

    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # CSP: still allows inline styles/scripts (templates rely on them); the
    # extra directives below restrict everything we don't actually use.
    # Removing 'unsafe-inline' is tracked as a separate template refactor.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    return response


# ── Audit Logging ────────────────────────────────────────────────────────────

def log_audit(user: Optional[dict], module: str, action: str,
              entity_type: str = "", entity_id: int = 0,
              details: str = "", ip: str = ""):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO audit_log (user_id, username, module, action, entity_type, "
            "entity_id, details, ip_address) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                user["id"] if user else None,
                user["username"] if user else "system",
                module,
                action,
                entity_type,
                entity_id,
                details,
                ip,
            ),
        )
        db.commit()
    finally:
        db.close()
