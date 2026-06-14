"""
ThemisIQ — Central email utility.

Single source of truth for all outbound email across the platform.
Replaces the duplicated _send() functions in evidence/bcm/sentinel schedulers.

Supported providers (selected automatically from config):
  google          — Gmail SMTP  (smtp.gmail.com:587, STARTTLS + app password)
  microsoft_smtp  — Office 365  (smtp.office365.com:587, STARTTLS + app password)
  microsoft_graph — Entra ID service account via Microsoft Graph REST API
                    (requires MS_TENANT_ID + MS_CLIENT_ID + MS_CLIENT_SECRET)
  smtp            — Any generic SMTP server
  console         — Log-only fallback (no credentials required)

Provider resolution order:
  1. `settings` table key "email_provider"   ← set via Admin → Email Settings UI
  2. EMAIL_PROVIDER env var                  ← set in .env
  3. Auto-detect from SMTP_HOST              ← backward-compat with existing .env
  4. Console fallback                        ← always safe

Security: caller is responsible for HTML-escaping dynamic content before passing
body_html. This module does NOT re-escape content.
"""
from __future__ import annotations

import base64
import html
import json
import logging
import os
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from config import settings

log = logging.getLogger("aegis.email")

TIMEOUT_S = 15  # seconds for SMTP and HTTP connections

# ─────────────────────────────────────────────────────────────────────────────
# Settings helpers (read from DB at call time — supports live reconfiguration)
# ─────────────────────────────────────────────────────────────────────────────

def _get_setting(key: str, default: str = "") -> str:
    """Read a single key from the settings table without importing data_service."""
    try:
        from database import get_db
        db = get_db()
        try:
            row = db.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
            return row["value"] if row else default
        finally:
            db.close()
    except Exception:
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Simple reversible encryption for passwords stored in the settings table.
# Uses XOR with the first 32 bytes of SHA-256(SECRET_KEY).
# Not Fort Knox, but protects against casual DB inspection.
# ─────────────────────────────────────────────────────────────────────────────

def _derive_key() -> bytes:
    import hashlib
    return hashlib.sha256(settings.SECRET_KEY.encode()).digest()  # 32 bytes


def encrypt_setting(plaintext: str) -> str:
    """Return base64-encoded XOR-encrypted string, or empty string for empty input."""
    if not plaintext:
        return ""
    key = _derive_key()
    data = plaintext.encode("utf-8")
    enc  = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.b64encode(enc).decode("ascii")


def decrypt_setting(ciphertext: str) -> str:
    """Reverse encrypt_setting. Returns plaintext, or empty string on failure."""
    if not ciphertext:
        return ""
    try:
        key  = _derive_key()
        data = base64.b64decode(ciphertext.encode("ascii"))
        dec  = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return dec.decode("utf-8")
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Provider resolution
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_provider() -> str:
    """
    Determine which provider to use, in priority order:
      settings table → EMAIL_PROVIDER env → auto-detect from SMTP_HOST → console
    """
    # 1. Settings table (set via admin UI)
    db_provider = _get_setting("email_provider", "").strip().lower()
    if db_provider:
        return db_provider

    # 2. Environment variable
    env_provider = os.getenv("EMAIL_PROVIDER", "").strip().lower()
    if env_provider:
        return env_provider

    # 3. Auto-detect from SMTP_HOST (backward compat with existing .env)
    host = (_get_setting("smtp_host") or settings.SMTP_HOST or "").lower()
    if "gmail" in host or "google" in host:
        return "google"
    if "office365" in host or "outlook" in host or "microsoft" in host:
        return "microsoft_smtp"
    if host:
        return "smtp"

    # 4. If we have MS Graph vars, use graph
    if settings.MS_TENANT_ID and settings.MS_CLIENT_ID and settings.MS_CLIENT_SECRET:
        return "microsoft_graph"

    return "console"


# ─────────────────────────────────────────────────────────────────────────────
# SMTP config (Google or Microsoft SMTP or custom)
# ─────────────────────────────────────────────────────────────────────────────

def _smtp_config() -> dict:
    """Return SMTP connection parameters, preferring settings table over env vars."""
    host = _get_setting("smtp_host") or settings.SMTP_HOST
    port = int(_get_setting("smtp_port") or settings.SMTP_PORT or 587)
    user = _get_setting("smtp_user") or settings.SMTP_USER
    # Password may be encrypted in settings table; env var is plain text
    raw_pass = _get_setting("smtp_pass_enc")
    pw   = decrypt_setting(raw_pass) if raw_pass else settings.SMTP_PASS
    frm  = _get_setting("smtp_from") or settings.SMTP_FROM
    return {"host": host, "port": port, "user": user, "password": pw, "from": frm}


# ─────────────────────────────────────────────────────────────────────────────
# Microsoft Graph config
# ─────────────────────────────────────────────────────────────────────────────

def _graph_config() -> dict:
    """Return Microsoft Graph API parameters, preferring settings table over env vars."""
    raw_secret = _get_setting("ms_client_secret_enc")
    secret = decrypt_setting(raw_secret) if raw_secret else settings.MS_CLIENT_SECRET
    return {
        "tenant_id":     _get_setting("ms_tenant_id") or settings.MS_TENANT_ID,
        "client_id":     _get_setting("ms_client_id") or settings.MS_CLIENT_ID,
        "client_secret": secret,
        "from_address":  _get_setting("smtp_from") or settings.SMTP_FROM,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Transport implementations
# ─────────────────────────────────────────────────────────────────────────────

def _send_smtp(*, to: str, subject: str, body_html: str, cfg: dict) -> dict:
    """Send via STARTTLS SMTP (Google, Microsoft SMTP, or custom)."""
    msg = MIMEMultipart("alternative")
    msg["From"]    = cfg["from"]
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=TIMEOUT_S) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(cfg["user"], cfg["password"].replace(" ", ""))
            server.send_message(msg)
        log.info("[email-smtp] Sent → %s | %s", to, subject)
        return {"ok": True, "provider": "smtp", "host": cfg["host"]}
    except Exception as exc:
        log.warning("[email-smtp] Failed → %s | %s: %s", to, subject, exc)
        return {"ok": False, "provider": "smtp", "error": str(exc)}


def _send_graph(*, to: str, subject: str, body_html: str, cfg: dict) -> dict:
    """
    Send via Microsoft Graph API using client-credentials OAuth2 flow.

    Requires:
      - An Azure AD App Registration with Mail.Send application permission
      - Admin consent granted in the tenant
      - A mailbox matching cfg["from_address"] in the tenant

    No new pip dependencies — uses stdlib urllib only.
    """
    tenant_id  = cfg["tenant_id"]
    client_id  = cfg["client_id"]
    secret     = cfg["client_secret"]
    from_addr  = cfg["from_address"]

    # Strip display name if present ("ThemisIQ <user@domain.com>" → "user@domain.com")
    if "<" in from_addr and ">" in from_addr:
        from_addr = from_addr.split("<")[1].rstrip(">").strip()

    if not all([tenant_id, client_id, secret, from_addr]):
        log.warning("[email-graph] Incomplete Graph config — falling back to console")
        return _send_console(to=to, subject=subject, body_html=body_html)

    # ── Step 1: Acquire OAuth2 token ──────────────────────────────────────────
    token_url  = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    token_body = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": secret,
        "scope":         "https://graph.microsoft.com/.default",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            token_url,
            data=token_body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
        access_token = token_data.get("access_token", "")
        if not access_token:
            raise ValueError(f"No access_token in response: {list(token_data.keys())}")
    except Exception as exc:
        log.warning("[email-graph] Token acquisition failed: %s", exc)
        return {"ok": False, "provider": "microsoft_graph", "error": f"Token: {exc}"}

    # ── Step 2: Send mail via Graph ───────────────────────────────────────────
    send_url  = f"https://graph.microsoft.com/v1.0/users/{from_addr}/sendMail"
    mail_body = json.dumps({
        "message": {
            "subject": subject,
            "body":    {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": "false",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            send_url,
            data=mail_body,
            method="POST",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type":  "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            # Graph returns 202 Accepted on success (no body)
            status = resp.status
        if status not in (200, 202):
            raise ValueError(f"Unexpected status {status}")
        log.info("[email-graph] Sent → %s | %s", to, subject)
        return {"ok": True, "provider": "microsoft_graph"}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        log.warning("[email-graph] Send failed → %s | HTTP %s: %s", to, exc.code, err_body[:200])
        return {"ok": False, "provider": "microsoft_graph", "error": f"HTTP {exc.code}: {err_body[:200]}"}
    except Exception as exc:
        log.warning("[email-graph] Send failed → %s: %s", to, exc)
        return {"ok": False, "provider": "microsoft_graph", "error": str(exc)}


def _send_console(*, to: str, subject: str, body_html: str) -> dict:
    """Log-only fallback. No credentials required. Always returns ok=True."""
    log.info(
        "[email-console] To: %s | Subject: %s | (no email provider configured — set up in Admin → Email Settings)",
        to, subject,
    )
    return {"ok": True, "provider": "console"}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def send_email(*, to: str, subject: str, body_html: str) -> dict:
    """
    Send an email via the configured provider.

    Returns:
        {"ok": True/False, "provider": "smtp"|"microsoft_graph"|"console", ...}

    Never raises — always returns a result dict. Callers should check ["ok"].
    Console fallback always returns ok=True even when no email is sent.
    """
    if not to or not subject:
        return {"ok": False, "provider": "none", "error": "Missing to/subject"}

    provider = _resolve_provider()
    log.debug("[email] Using provider: %s for → %s", provider, to)

    if provider == "microsoft_graph":
        return _send_graph(to=to, subject=subject, body_html=body_html, cfg=_graph_config())

    if provider in ("google", "microsoft_smtp", "smtp"):
        cfg = _smtp_config()
        if not cfg["user"] or not cfg["password"]:
            log.info("[email] SMTP credentials missing — falling back to console")
            return _send_console(to=to, subject=subject, body_html=body_html)
        return _send_smtp(to=to, subject=subject, body_html=body_html, cfg=cfg)

    # "console" or unknown
    return _send_console(to=to, subject=subject, body_html=body_html)


def test_connection() -> dict:
    """
    Validate email configuration without sending a real email.
    Returns {"ok": True/False, "provider": ..., "detail": "..."}.
    """
    provider = _resolve_provider()

    if provider == "console":
        return {"ok": True, "provider": "console", "detail": "Console mode — no email will be sent"}

    if provider == "microsoft_graph":
        cfg = _graph_config()
        missing = [k for k in ("tenant_id", "client_id", "client_secret", "from_address") if not cfg.get(k)]
        if missing:
            return {"ok": False, "provider": "microsoft_graph",
                    "detail": f"Missing Graph config: {', '.join(missing)}"}
        # Attempt token acquisition only
        tenant_id = cfg["tenant_id"]
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        token_body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id":  cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "scope": "https://graph.microsoft.com/.default",
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                token_url, data=token_body, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                data = json.loads(resp.read())
            if data.get("access_token"):
                return {"ok": True, "provider": "microsoft_graph",
                        "detail": "Token acquired — Graph API reachable"}
            return {"ok": False, "provider": "microsoft_graph",
                    "detail": f"Token response: {list(data.keys())}"}
        except Exception as exc:
            return {"ok": False, "provider": "microsoft_graph", "detail": str(exc)}

    # SMTP providers
    cfg = _smtp_config()
    missing = [k for k in ("host", "user", "password") if not cfg.get(k)]
    if missing:
        return {"ok": False, "provider": provider,
                "detail": f"Missing SMTP config: {', '.join(missing)}"}
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=TIMEOUT_S) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(cfg["user"], cfg["password"].replace(" ", ""))
        return {"ok": True, "provider": provider,
                "detail": f"SMTP login successful ({cfg['host']}:{cfg['port']})"}
    except Exception as exc:
        return {"ok": False, "provider": provider, "detail": str(exc)}
