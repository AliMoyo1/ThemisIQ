"""
ThemisIQ - Central email utility.

Single source of truth for all outbound email across the platform.

Supported providers (selected automatically from config):
  google          - Gmail SMTP  (smtp.gmail.com:587, STARTTLS + app password)
  microsoft_smtp  - Office 365  (smtp.office365.com:587, STARTTLS + app password)
  microsoft_graph - Entra ID service account via Microsoft Graph REST API
                    (requires MS_TENANT_ID + MS_CLIENT_ID + MS_CLIENT_SECRET)
  sendgrid        - SendGrid REST API
  smtp            - Any generic SMTP server
  console         - Log-only fallback (no credentials required): nothing leaves the platform

Provider resolution order:
  1. `settings` table key "email_provider"   (set via Admin > Email Settings)
  2. EMAIL_PROVIDER env var                  (set in .env)
  3. Auto-detect from SMTP_HOST              (backward-compat with existing .env)
  4. Console fallback                        (always safe)

What a result says (plans/2026-10-governance-rework/06 sections 6 and 9). `send_email` never raises and returns:

  {"status": ..., "ok": bool, "provider": ..., ...}

  provider_accepted  the provider took the message. Not: it arrived, not: it was read. The only status where ok is True.
  logged_only        no provider is configured, or its credentials are missing: nothing left the platform.
  suppressed         deliberately not sent (no usable recipient address).
  failed             the provider refused it or could not be reached; `permanent` says whether to stop trying.

A caller that records a message as sent, clears a due alert or sets a "notified" flag does so only on provider_accepted.

Secrets: a new password or key is a deployment secret (SMTP_PASS, MS_CLIENT_SECRET, SENDGRID_API_KEY in the environment
of the service). A value stored in the settings table by an earlier version is still read, so a running installation does
not stop, and is reported by `health()` as obscured, not encrypted.

Security: callers pass structured, escaped HTML (core.email_templates). This module does NOT re-escape content, and it
removes line breaks from the recipient and subject so that neither can add a header.
"""
from __future__ import annotations

import base64
import html as _html
import json
import logging
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlsplit

from config import settings
from core.best_effort import swallowed

log = logging.getLogger("aegis.email")

TIMEOUT_S = 15  # seconds for SMTP and HTTP connections

STATUS_ACCEPTED = "provider_accepted"
STATUS_LOGGED = "logged_only"
STATUS_SUPPRESSED = "suppressed"
STATUS_FAILED = "failed"

# SMTP replies that will not succeed on a retry: an address the server refuses, or credentials it rejects.
_PERMANENT_SMTP = (smtplib.SMTPRecipientsRefused, smtplib.SMTPAuthenticationError, smtplib.SMTPSenderRefused)

_PLACEHOLDER_DOMAINS = ("example.com", "example.org", "example.net")

_ADDRESS = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                      r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


# ─────────────────────────────────────────────────────────────────────────────
# Settings helpers (read from DB at call time: supports live reconfiguration)
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
        swallowed("_get_setting (settings)")
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Obscuring of the passwords that an earlier version stored in the settings table.
# XOR with the first 32 bytes of SHA-256(SECRET_KEY). This is obfuscation, not encryption: it is kept only so that a value
# already stored can still be read. New secrets are deployment secrets (see the module docstring).
# ─────────────────────────────────────────────────────────────────────────────

def _derive_key() -> bytes:
    import hashlib
    return hashlib.sha256(settings.SECRET_KEY.encode()).digest()  # 32 bytes


def encrypt_setting(plaintext: str) -> str:
    """Return base64-encoded XOR-obscured string, or empty string for empty input."""
    if not plaintext:
        return ""
    key = _derive_key()
    data = plaintext.encode("utf-8")
    enc = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.b64encode(enc).decode("ascii")


def decrypt_setting(ciphertext: str) -> str:
    """Reverse encrypt_setting. Returns plaintext, or empty string on failure."""
    if not ciphertext:
        return ""
    try:
        key = _derive_key()
        data = base64.b64decode(ciphertext.encode("ascii"))
        dec = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return dec.decode("utf-8")
    except Exception:
        return ""


def db_secrets_allowed() -> bool:
    """A new secret may be saved in the settings table only when the operator says so on purpose. The default is no:
    the value is obscured, not encrypted, so it should live in the service's environment."""
    return os.getenv("EMAIL_ALLOW_DB_SECRETS", "").strip().lower() in ("1", "true", "yes")


# ─────────────────────────────────────────────────────────────────────────────
# Addresses, headers and links
# ─────────────────────────────────────────────────────────────────────────────

def _clean_header(value: str) -> str:
    """One line, no control characters: a header value that cannot start another header."""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()


def valid_address(value: str) -> bool:
    """A plain `local@domain` address, not a list and not a display name with an address inside it."""
    text = str(value or "").strip()
    return bool(text) and len(text) <= 254 and bool(_ADDRESS.match(text))


def app_origin() -> str:
    """The origin that links in mail point to (`APP_URL`), or "" when none is configured. It must be https; http is
    accepted only for localhost, so a mail never carries a link to a plain-text host or to a relative path."""
    configured = (os.getenv("APP_URL") or getattr(settings, "APP_URL", "") or "").strip()
    try:
        parsed = urlsplit(configured)
        hostname = parsed.hostname
        parsed.port  # reject malformed port syntax
        scheme = parsed.scheme.lower()
    except ValueError:
        return ""
    if (not hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment
            or (parsed.path not in ("", "/"))
            or (scheme != "https" and not (scheme == "http" and hostname in ("localhost", "127.0.0.1")))):
        return ""
    return f"{scheme}://{parsed.netloc}"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "table"):
            self.parts.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            self._href = href if href.startswith(("https://", "http://")) else ""

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("p", "div", "tr", "li", "h1", "h2", "h3", "table"):
            self.parts.append("\n")
        elif tag == "a" and self._href:
            self.parts.append(f" ({self._href})")
            self._href = ""

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(body_html: str) -> str:
    """A plain text part for a message that was written as HTML only."""
    parser = _Text()
    try:
        parser.feed(body_html or "")
    except Exception:
        return _html.unescape(re.sub(r"<[^>]+>", " ", body_html or ""))
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Provider resolution
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_provider() -> str:
    """
    Determine which provider to use, in priority order:
      settings table -> EMAIL_PROVIDER env -> auto-detect from SMTP_HOST -> console
    """
    db_provider = _get_setting("email_provider", "").strip().lower()
    if db_provider:
        return db_provider

    env_provider = os.getenv("EMAIL_PROVIDER", "").strip().lower()
    if env_provider:
        return env_provider

    host = (_get_setting("smtp_host") or settings.SMTP_HOST or "").lower()
    if "gmail" in host or "google" in host:
        return "google"
    if "office365" in host or "outlook" in host or "microsoft" in host:
        return "microsoft_smtp"
    if host:
        return "smtp"

    if settings.MS_TENANT_ID and settings.MS_CLIENT_ID and settings.MS_CLIENT_SECRET:
        return "microsoft_graph"

    return "console"


# ─────────────────────────────────────────────────────────────────────────────
# SMTP config (Google or Microsoft SMTP or custom)
# ─────────────────────────────────────────────────────────────────────────────

def _smtp_config() -> dict:
    """SMTP connection parameters. A deployment secret in the environment wins over a value an earlier version stored in
    the settings table."""
    host = _get_setting("smtp_host") or settings.SMTP_HOST
    port = int(_get_setting("smtp_port") or settings.SMTP_PORT or 587)
    user = _get_setting("smtp_user") or settings.SMTP_USER
    raw_pass = _get_setting("smtp_pass_enc")
    pw = settings.SMTP_PASS or (decrypt_setting(raw_pass) if raw_pass else "")
    frm = _get_setting("smtp_from") or settings.SMTP_FROM
    return {"host": host, "port": port, "user": user, "password": pw, "from": frm}


def credential_source() -> str:
    """Where the SMTP password comes from, without revealing it: environment, stored (obscured) or none."""
    if settings.SMTP_PASS:
        return "environment"
    if _get_setting("smtp_pass_enc"):
        return "stored_obscured"
    return "none"


def _sender_header(cfg: dict, provider: str) -> str:
    """The From header. A Gmail account sends as itself, so the mailbox is the address and a configured name is kept;
    for other providers the configured value is used when it is a plain address, else the authenticated user."""
    name, address = parseaddr(_clean_header(cfg.get("from") or ""))
    user = _clean_header(cfg.get("user") or "")
    if address.lower().rsplit("@", 1)[-1] in _PLACEHOLDER_DOMAINS:
        address = ""  # the shipped default is a placeholder, not an address the account may send as
    if provider == "google" and valid_address(user):
        address = user
    elif not valid_address(address):
        address = user if valid_address(user) else ""
    if not address:
        return ""
    return f'"{name}" <{address}>' if name else address


# ─────────────────────────────────────────────────────────────────────────────
# Microsoft Graph config
# ─────────────────────────────────────────────────────────────────────────────

def _graph_config() -> dict:
    """Microsoft Graph API parameters. A deployment secret in the environment wins over a stored value."""
    raw_secret = _get_setting("ms_client_secret_enc")
    secret = settings.MS_CLIENT_SECRET or (decrypt_setting(raw_secret) if raw_secret else "")
    return {
        "tenant_id": _get_setting("ms_tenant_id") or settings.MS_TENANT_ID,
        "client_id": _get_setting("ms_client_id") or settings.MS_CLIENT_ID,
        "client_secret": secret,
        "from_address": _get_setting("smtp_from") or settings.SMTP_FROM,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Results
# ─────────────────────────────────────────────────────────────────────────────

def _result(status: str, provider: str, **extra) -> dict:
    return {"status": status, "ok": status == STATUS_ACCEPTED, "provider": provider, **extra}


# ─────────────────────────────────────────────────────────────────────────────
# Transport implementations
# ─────────────────────────────────────────────────────────────────────────────

def _send_smtp(*, to: str, subject: str, body_html: str, body_text: str, cfg: dict, provider: str = "smtp") -> dict:
    """Send via STARTTLS SMTP (Google, Microsoft SMTP, or custom) with a verified certificate."""
    sender = _sender_header(cfg, provider)
    if not sender:
        return _result(STATUS_FAILED, provider, error="No sender address is configured", permanent=True)
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    domain = parseaddr(sender)[1].rsplit("@", 1)[-1] or None
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Auto-Submitted"] = "auto-generated"
    reply_to = _clean_header(os.getenv("SMTP_REPLY_TO", ""))
    if valid_address(reply_to):
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=TIMEOUT_S) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(cfg["user"], cfg["password"].replace(" ", ""))
            server.send_message(msg)
        log.info("[email-smtp] Accepted by %s for %s", cfg["host"], to)
        return _result(STATUS_ACCEPTED, provider, host=cfg["host"])
    except Exception as exc:
        code = getattr(exc, "smtp_code", None)
        label = type(exc).__name__ + (f" {code}" if code else "")
        log.warning("[email-smtp] Failed for %s: %s", to, label)
        return _result(STATUS_FAILED, provider, error=label, permanent=isinstance(exc, _PERMANENT_SMTP))


def _send_graph(*, to: str, subject: str, body_html: str, body_text: str, cfg: dict) -> dict:
    """
    Send via Microsoft Graph API using the client-credentials OAuth2 flow.

    Requires an Azure AD App Registration with Mail.Send application permission, admin consent granted in the tenant and
    a mailbox matching cfg["from_address"]. Uses the stdlib urllib only.
    """
    tenant_id = cfg["tenant_id"]
    client_id = cfg["client_id"]
    secret = cfg["client_secret"]
    from_addr = cfg["from_address"]

    # Strip display name if present ("ThemisIQ <user@domain.com>" -> "user@domain.com")
    if "<" in from_addr and ">" in from_addr:
        from_addr = from_addr.split("<")[1].rstrip(">").strip()

    if not all([tenant_id, client_id, secret, from_addr]):
        log.warning("[email-graph] Incomplete Graph config: nothing was sent")
        return _result(STATUS_LOGGED, "microsoft_graph", reason="not_configured")

    token_url = f"https://login.microsoftonline.com/{urllib.parse.quote(tenant_id, safe='')}/oauth2/v2.0/token"
    token_body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": secret,
        "scope": "https://graph.microsoft.com/.default",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(token_url, data=token_body, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
        access_token = token_data.get("access_token", "")
        if not access_token:
            raise ValueError("No access token in the response")
    except Exception as exc:
        log.warning("[email-graph] Token acquisition failed: %s", type(exc).__name__)
        return _result(STATUS_FAILED, "microsoft_graph", error=f"Token: {type(exc).__name__}")

    send_url = f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(from_addr, safe='@')}/sendMail"
    mail_body = json.dumps({
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": "false",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(send_url, data=mail_body, method="POST", headers={
            "Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            status = resp.status
        if status not in (200, 202):
            raise ValueError(f"Unexpected status {status}")
        log.info("[email-graph] Accepted for %s", to)
        return _result(STATUS_ACCEPTED, "microsoft_graph")
    except urllib.error.HTTPError as exc:
        log.warning("[email-graph] Send failed for %s: HTTP %s", to, exc.code)
        return _result(STATUS_FAILED, "microsoft_graph", error=f"HTTP {exc.code}", permanent=exc.code in (400, 401, 403))
    except Exception as exc:
        log.warning("[email-graph] Send failed for %s: %s", to, type(exc).__name__)
        return _result(STATUS_FAILED, "microsoft_graph", error=type(exc).__name__)


# ─────────────────────────────────────────────────────────────────────────────
# SendGrid REST API
# ─────────────────────────────────────────────────────────────────────────────

def _sendgrid_config() -> dict:
    raw_key = _get_setting("sendgrid_api_key_enc")
    api_key = (os.getenv("SENDGRID_API_KEY") or getattr(settings, "SENDGRID_API_KEY", "")
               or (decrypt_setting(raw_key) if raw_key else ""))
    from_addr = (
        _get_setting("smtp_from")
        or getattr(settings, "SMTP_FROM", "")
        or os.getenv("SMTP_FROM", "")
    )
    return {"api_key": api_key, "from": from_addr}


def _send_sendgrid(*, to: str, subject: str, body_html: str, body_text: str) -> dict:
    cfg = _sendgrid_config()
    if not cfg["api_key"]:
        log.info("[email-sendgrid] API key not configured: nothing was sent")
        return _result(STATUS_LOGGED, "sendgrid", reason="not_configured")

    name, from_email = parseaddr(_clean_header(cfg["from"]))
    if not valid_address(from_email):
        return _result(STATUS_FAILED, "sendgrid", error="No valid sender address is configured", permanent=True)

    payload = json.dumps({
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": from_email, "name": name or "ThemisIQ"},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body_text}, {"type": "text/html", "value": body_html}],
    }).encode("utf-8")

    try:
        req = urllib.request.Request("https://api.sendgrid.com/v3/mail/send", data=payload, method="POST", headers={
            "Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            status = resp.status
        if status not in (200, 202):
            raise ValueError(f"Unexpected status {status}")
        log.info("[email-sendgrid] Accepted for %s", to)
        return _result(STATUS_ACCEPTED, "sendgrid")
    except urllib.error.HTTPError as exc:
        log.warning("[email-sendgrid] Failed for %s: HTTP %s", to, exc.code)
        return _result(STATUS_FAILED, "sendgrid", error=f"HTTP {exc.code}", permanent=exc.code in (400, 401, 403))
    except Exception as exc:
        log.warning("[email-sendgrid] Failed for %s: %s", to, type(exc).__name__)
        return _result(STATUS_FAILED, "sendgrid", error=type(exc).__name__)


def _send_console(*, to: str, subject: str) -> dict:
    """Log-only fallback. No credentials required. Nothing leaves the platform, so this is NOT a delivery."""
    log.info("[email-console] Not sent (no provider is configured). Subject: %s", subject)
    return _result(STATUS_LOGGED, "console", reason="no_provider")


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def send_email(*, to: str, subject: str, body_html: str, body_text: Optional[str] = None) -> dict:
    """
    Send an email via the configured provider.

    Returns {"status": provider_accepted | logged_only | suppressed | failed, "ok": status == provider_accepted,
    "provider": ..., ...}. Never raises. A caller that marks a message sent, clears a due alert or sets a notified flag
    does so only when `ok` is True.
    """
    to = _clean_header(to)
    subject = _clean_header(subject)
    if not valid_address(to):
        return _result(STATUS_SUPPRESSED, "none", reason="invalid_recipient", error="No valid recipient address")
    if not subject:
        return _result(STATUS_SUPPRESSED, "none", reason="missing_subject", error="Missing subject")
    text = body_text if body_text is not None else html_to_text(body_html)

    provider = _resolve_provider()
    log.debug("[email] Using provider: %s", provider)

    if provider == "microsoft_graph":
        return _send_graph(to=to, subject=subject, body_html=body_html, body_text=text, cfg=_graph_config())

    if provider == "sendgrid":
        return _send_sendgrid(to=to, subject=subject, body_html=body_html, body_text=text)

    if provider in ("google", "microsoft_smtp", "smtp"):
        cfg = _smtp_config()
        if not cfg["host"] or not cfg["user"] or not cfg["password"]:
            log.info("[email] SMTP configuration is incomplete: nothing was sent")
            return _result(STATUS_LOGGED, provider, reason="not_configured")
        return _send_smtp(to=to, subject=subject, body_html=body_html, body_text=text, cfg=cfg, provider=provider)

    return _send_console(to=to, subject=subject)


def health() -> dict:
    """What an administrator needs to know about the sender, with no secret in it."""
    provider = _resolve_provider()
    cfg = _smtp_config()
    warnings: list[str] = []
    configured = provider != "console"
    if provider in ("google", "microsoft_smtp", "smtp"):
        configured = bool(cfg["host"] and cfg["user"] and cfg["password"])
        configured_from = parseaddr(cfg["from"])[1]
        if provider == "google" and configured_from and configured_from.lower() != str(cfg["user"]).lower():
            warnings.append("The configured From address is not the Gmail mailbox. Mail is sent as the mailbox; use an "
                            "alias the account is authorized to send as, or set From to the mailbox.")
    source = credential_source()
    if source == "stored_obscured":
        warnings.append("The password is stored in the database, obscured but not encrypted. Move it to the service's "
                        "environment (SMTP_PASS), rotate it, and clear the stored copy.")
    origin = app_origin()
    if not origin:
        warnings.append("APP_URL is not a valid HTTPS origin, so messages carry no link.")
    if not os.getenv("SMTP_REPLY_TO") and configured:
        warnings.append("No monitored reply address is configured (SMTP_REPLY_TO). Messages say not to reply.")
    return {"provider": provider, "configured": configured, "credential_source": source, "app_origin": origin or None,
            "from": cfg["from"] if provider in ("google", "microsoft_smtp", "smtp") else None, "warnings": warnings}


def test_connection() -> dict:
    """
    Validate email configuration without sending a real email.
    Returns {"ok": True/False, "status": ..., "provider": ..., "detail": "..."}. `ok` is True only when a real provider
    answered: console mode and missing configuration are not a working connection.
    """
    provider = _resolve_provider()

    if provider == "console":
        return {"ok": False, "status": STATUS_LOGGED, "provider": "console",
                "detail": "No provider is configured: nothing is sent, messages are only logged"}

    if provider == "sendgrid":
        cfg = _sendgrid_config()
        if not cfg["api_key"]:
            return {"ok": False, "status": STATUS_LOGGED, "provider": "sendgrid", "detail": "SENDGRID_API_KEY is not configured"}
        return {"ok": True, "status": "configured", "provider": "sendgrid",
                "detail": f"An API key is present. From: {cfg['from']}. It is not checked until a message is sent."}

    if provider == "microsoft_graph":
        cfg = _graph_config()
        missing = [k for k in ("tenant_id", "client_id", "client_secret", "from_address") if not cfg.get(k)]
        if missing:
            return {"ok": False, "status": STATUS_LOGGED, "provider": "microsoft_graph",
                    "detail": f"Missing Graph configuration: {', '.join(missing)}"}
        token_url = f"https://login.microsoftonline.com/{urllib.parse.quote(cfg['tenant_id'], safe='')}/oauth2/v2.0/token"
        token_body = urllib.parse.urlencode({
            "grant_type": "client_credentials", "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
            "scope": "https://graph.microsoft.com/.default",
        }).encode("utf-8")
        try:
            req = urllib.request.Request(token_url, data=token_body, method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                data = json.loads(resp.read())
            if data.get("access_token"):
                return {"ok": True, "status": "configured", "provider": "microsoft_graph",
                        "detail": "A token was issued: the Graph API is reachable"}
            return {"ok": False, "status": STATUS_FAILED, "provider": "microsoft_graph", "detail": "No token was issued"}
        except Exception as exc:
            return {"ok": False, "status": STATUS_FAILED, "provider": "microsoft_graph", "detail": type(exc).__name__}

    cfg = _smtp_config()
    missing = [k for k in ("host", "user", "password") if not cfg.get(k)]
    if missing:
        return {"ok": False, "status": STATUS_LOGGED, "provider": provider,
                "detail": f"Missing SMTP configuration: {', '.join(missing)}"}
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=TIMEOUT_S) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(cfg["user"], cfg["password"].replace(" ", ""))
        return {"ok": True, "status": "configured", "provider": provider,
                "detail": f"SMTP login succeeded ({cfg['host']}:{cfg['port']}). Nothing was sent."}
    except Exception as exc:
        return {"ok": False, "status": STATUS_FAILED, "provider": provider, "detail": f"{type(exc).__name__}"}
