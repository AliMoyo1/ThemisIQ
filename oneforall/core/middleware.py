"""
One For All — security middleware.

- Session-based auth dependency for FastAPI
- CSRF protection
- Security headers
- Rate limiting (login endpoint)
- Audit logging helper
"""
import hashlib
import hmac
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
_MFA_PENDING_EXEMPT = {"/mfa/verify", "/logout", "/static", "/favicon.ico"}


# ── Auth dependency ──────────────────────────────────────────────────────────

async def get_current_user(request: Request) -> Optional[dict]:
    """Extract user from session cookie. Returns None if not logged in."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None
    return get_session_user(token)


def require_auth(func):
    """Decorator: redirect to login if not authenticated.
    Also enforces must_change_password and mfa_pending redirects."""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        user = await get_current_user(request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        path = request.url.path
        if user.get("mfa_pending") and not any(
            path.startswith(p) for p in _MFA_PENDING_EXEMPT
        ):
            return RedirectResponse("/mfa/verify", status_code=303)
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
            path = request.url.path
            if user.get("mfa_pending") and not any(
                path.startswith(p) for p in _MFA_PENDING_EXEMPT
            ):
                return RedirectResponse("/mfa/verify", status_code=303)
            if user.get("must_change_password") and not any(
                path.startswith(p) for p in _PW_CHANGE_EXEMPT
            ):
                return RedirectResponse("/change-password", status_code=303)
            if not any(has_capability(user, c) for c in capabilities):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            # Licence check: a module capability requires the tenant licence too
            # (super admins bypass).
            if not user.get("is_super_admin"):
                licensed = user.get("licensed_modules")
                if licensed is not None:
                    licensed_set = set(licensed)
                    for cap in capabilities:
                        if cap.startswith("module.") and cap.endswith(".access"):
                            mod = cap.split(".")[1]
                            if mod not in licensed_set:
                                raise HTTPException(
                                    status_code=403,
                                    detail=f"Your organisation does not have a licence for the {mod.upper()} module.",
                                )
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


def session_csrf_token(request: Request) -> str:
    """Derive a CSRF token from the session cookie via HMAC.

    The token is bound to the user's session, so an attacker without the
    session cookie cannot forge a valid token. This avoids breakage when
    a separate CSRF cookie is stripped by a proxy or lost in a redirect
    chain.
    """
    session_tok = request.cookies.get(settings.SESSION_COOKIE_NAME, "")
    if not session_tok:
        return ""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"csrf:{session_tok}".encode(),
        hashlib.sha256,
    ).hexdigest()


def validate_csrf(request: Request, form_token: str) -> bool:
    """Validate a CSRF token from a form against the session.

    Accepts either a session-derived HMAC token (preferred) or the legacy
    double-submit cookie token. The HMAC path is robust against cookies
    being stripped by a proxy.
    """
    if not form_token:
        return False
    expected_hmac = session_csrf_token(request)
    if expected_hmac and secrets.compare_digest(expected_hmac, form_token):
        return True
    cookie_tok = request.cookies.get("csrf_token", "")
    if cookie_tok and secrets.compare_digest(cookie_tok, form_token):
        return True
    return False


# ── Rate Limiting ────────────────────────────────────────────────────────────

import logging as _log_rl
_rl_log = _log_rl.getLogger(__name__)

_login_attempts: dict[str, list[float]] = defaultdict(list)
_MAX_LOGIN_ATTEMPTS = 5
_WINDOW_SECONDS = 300  # 5 minutes
_LAST_CLEANUP = 0.0


def _use_db_rate_limit() -> bool:
    return settings.is_postgres()


def check_rate_limit(key: str) -> bool:
    """Return True if the request is allowed, False if rate-limited."""
    global _LAST_CLEANUP
    if not _use_db_rate_limit():
        now = time.time()
        if now - _LAST_CLEANUP > 600:
            stale = [k for k, v in _login_attempts.items()
                     if not v or now - v[-1] > _WINDOW_SECONDS]
            for k in stale:
                del _login_attempts[k]
            _LAST_CLEANUP = now
        _login_attempts[key] = [t for t in _login_attempts[key] if now - t < _WINDOW_SECONDS]
        return len(_login_attempts[key]) < _MAX_LOGIN_ATTEMPTS
    try:
        db = get_db()
        try:
            row = db.execute(
                "SELECT COUNT(*) FROM rate_limit_attempts"
                " WHERE key=%s AND attempted_at > NOW() - INTERVAL %s",
                (key, f"{_WINDOW_SECONDS} seconds"),
            ).fetchone()
            count = row[0] if row else 0
            db.execute(
                "DELETE FROM rate_limit_attempts"
                " WHERE attempted_at < NOW() - INTERVAL %s",
                (f"{_WINDOW_SECONDS * 2} seconds",),
            )
            db.commit()
            return count < _MAX_LOGIN_ATTEMPTS
        finally:
            db.close()
    except Exception:
        _rl_log.warning("[rate-limit] DB check failed, failing open")
        return True


def record_failed_login(key: str):
    """Record a failed login attempt for rate-limiting purposes."""
    if not _use_db_rate_limit():
        _login_attempts[key].append(time.time())
        return
    try:
        db = get_db()
        try:
            db.execute("INSERT INTO rate_limit_attempts (key) VALUES (%s)", (key,))
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        _rl_log.warning("[rate-limit] DB record failed: %s", exc)
        _login_attempts[key].append(time.time())


def clear_login_attempts(key: str):
    """Clear rate limit history on successful login."""
    if not _use_db_rate_limit():
        _login_attempts.pop(key, None)
        return
    try:
        db = get_db()
        try:
            db.execute("DELETE FROM rate_limit_attempts WHERE key=%s", (key,))
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        _rl_log.warning("[rate-limit] DB clear failed: %s", exc)
        _login_attempts.pop(key, None)


# ── AI call rate limiting ─────────────────────────────────────────────────────

_AI_WINDOW_SECONDS = 3600    # 1 hour rolling window
_AI_MAX_CALLS_PER_HOUR = 60  # per authenticated user


def check_ai_rate_limit(user_id: str) -> bool:
    """Return True if this user is allowed to make an AI call (60/hour)."""
    key = f"ai:{user_id}"
    if not _use_db_rate_limit():
        now = time.time()
        _login_attempts[key] = [t for t in _login_attempts[key] if now - t < _AI_WINDOW_SECONDS]
        return len(_login_attempts[key]) < _AI_MAX_CALLS_PER_HOUR
    try:
        db = get_db()
        try:
            row = db.execute(
                "SELECT COUNT(*) FROM rate_limit_attempts"
                " WHERE key=%s AND attempted_at > NOW() - INTERVAL %s",
                (key, f"{_AI_WINDOW_SECONDS} seconds"),
            ).fetchone()
            return (row[0] if row else 0) < _AI_MAX_CALLS_PER_HOUR
        finally:
            db.close()
    except Exception:
        _rl_log.warning("[ai-rate-limit] DB check failed, failing open")
        return True


def record_ai_call(user_id: str):
    """Record that an authenticated AI call was made by this user."""
    key = f"ai:{user_id}"
    if not _use_db_rate_limit():
        _login_attempts[key].append(time.time())
        return
    try:
        db = get_db()
        try:
            db.execute("INSERT INTO rate_limit_attempts (key) VALUES (%s)", (key,))
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        _rl_log.warning("[ai-rate-limit] DB record failed: %s", exc)
        _login_attempts[key].append(time.time())


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
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if not settings.DEBUG:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    # Fonts are self-hosted under /static/fonts/ so no CDN allowlist is needed.
    # unsafe-inline is retained until inline styles/scripts are extracted to
    # static files; that refactor is tracked separately.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com "
            "https://us.i.posthog.com https://eu.i.posthog.com "
            "https://us-assets.i.posthog.com https://eu-assets.i.posthog.com "
            "https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self' https://us.i.posthog.com https://eu.i.posthog.com "
            "https://us-assets.i.posthog.com https://eu-assets.i.posthog.com "
            "https://app.posthog.com https://*.sentry.io https://*.ingest.sentry.io "
            "https://cloudflareinsights.com; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    return response


# ── Tenant Context ────────────────────────────────────────────────────────────

async def tenant_context_middleware(request: Request, call_next):
    """Set the current tenant from the authenticated user's org_slug.

    Must run AFTER session validation. Super admins default to public schema
    unless they have explicitly switched org context (future feature).
    """
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        try:
            from core.auth import get_session_user
            from database import set_current_tenant
            user = get_session_user(token)
            if user and user.get("org_slug"):
                set_current_tenant(user["org_slug"])
                request.state.org_slug = user["org_slug"]
        except Exception:
            pass
    return await call_next(request)


# ── Global Input Sanitization ────────────────────────────────────────────────

import re as _re
import html as _html

_HTML_TAG_RE = _re.compile(r"<[^>]+>")


def _strip_tags_deep(obj):
    """Recursively strip HTML tags from all string values in a JSON structure."""
    if isinstance(obj, str):
        cleaned = _html.unescape(obj)
        cleaned = _HTML_TAG_RE.sub("", cleaned)
        if len(cleaned) > 50000:
            cleaned = cleaned[:50000]
        return cleaned
    if isinstance(obj, dict):
        return {k: _strip_tags_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_tags_deep(item) for item in obj[:1000]]
    return obj


async def sanitize_json_middleware(request: Request, call_next):
    """Strip HTML tags from all string values in JSON request bodies.

    This provides blanket XSS prevention at the input layer, complementing
    Jinja2 autoescape on output. Only applies to application/json bodies.
    """
    content_type = request.headers.get("content-type", "")
    if request.method in ("POST", "PUT", "PATCH") and "application/json" in content_type:
        body_bytes = await request.body()
        if body_bytes:
            try:
                import json as _json
                parsed = _json.loads(body_bytes)
                sanitized = _strip_tags_deep(parsed)
                sanitized_bytes = _json.dumps(sanitized).encode("utf-8")

                async def receive():
                    return {"type": "http.request", "body": sanitized_bytes}
                request._receive = receive
            except (ValueError, UnicodeDecodeError):
                pass
    return await call_next(request)


# ── Request Body Size Limit ──────────────────────────────────────────────────

_MAX_BODY_BYTES = 5 * 1024 * 1024  # 5 MB


async def body_size_limit_middleware(request: Request, call_next):
    """Reject oversized request bodies to prevent DoS via large payloads."""
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > _MAX_BODY_BYTES:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large."},
                )
        except ValueError:
            pass
    return await call_next(request)


# ── CORS Blocking ────────────────────────────────────────────────────────────

_CORS_ALLOWED_ORIGINS = {
    "https://app.themisiq.net",
    "https://themisiq.net",
    "https://www.themisiq.net",
}


async def cors_block_middleware(request: Request, call_next):
    """Block cross-origin requests from unauthorized domains.

    Rejects any request with an Origin header that does not match
    our allowed origins. Same-origin requests (no Origin header) pass through.
    Handles OPTIONS preflight for the demo endpoint.
    """
    origin = request.headers.get("origin")
    if origin:
        if settings.DEBUG and origin.startswith(("http://localhost", "http://127.0.0.1")):
            response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = origin
            return response
        if origin not in _CORS_ALLOWED_ORIGINS:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Origin not allowed."},
            )
    return await call_next(request)


# ── Audit Logging ────────────────────────────────────────────────────────────

def log_audit(user: Optional[dict], module: str, action: str,
              entity_type: str = "", entity_id: int = 0,
              details: str = "", ip: str = "", org_id: Optional[int] = None):
    effective_org_id = org_id if org_id is not None else (user.get("org_id") if user else None)
    db = get_db()
    try:
        db.execute(
            "INSERT INTO audit_log (user_id, username, module, action, entity_type, "
            "entity_id, details, ip_address, org_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                user["id"] if user else None,
                user["username"] if user else "system",
                module,
                action,
                entity_type,
                entity_id,
                details,
                ip,
                effective_org_id,
            ),
        )
        db.commit()
    finally:
        db.close()
