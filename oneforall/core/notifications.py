"""
ThemisIQ outbound notifications: Slack and Microsoft Teams.

Webhook URLs are read from the settings table (Admin > Connectors) with
fallback to SLACK_WEBHOOK_URL / TEAMS_WEBHOOK_URL env vars.

All send functions return True on success, False on failure or when the
connector is not configured. They never raise.
"""
import logging

import httpx

from config import settings

log = logging.getLogger(__name__)


def _get_setting(key: str, default: str = "") -> str:
    try:
        from database import get_db
        db = get_db()
        try:
            row = db.execute(
                "SELECT value FROM settings WHERE key=%s", (key,)
            ).fetchone()
            return (row[0] if row else None) or default
        finally:
            db.close()
    except Exception:
        return default


def _slack_url() -> str:
    return _get_setting("slack_webhook_url") or getattr(settings, "SLACK_WEBHOOK_URL", "")


def _teams_url() -> str:
    return _get_setting("teams_webhook_url") or getattr(settings, "TEAMS_WEBHOOK_URL", "")


def _whatsapp_url() -> str:
    return _get_setting("whatsapp_webhook_url") or getattr(settings, "WHATSAPP_WEBHOOK_URL", "")


def send_slack(text: str) -> bool:
    url = _slack_url()
    if not url:
        return False
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(url, json={"text": text})
            r.raise_for_status()
        log.info("[slack] Sent: %.60s", text)
        return True
    except Exception as exc:
        log.warning("[slack] Failed: %s", exc)
        return False


def send_teams(text: str) -> bool:
    url = _teams_url()
    if not url:
        return False
    try:
        payload = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": text[:100],
            "themeColor": "1e3a8a",
            "text": text,
        }
        with httpx.Client(timeout=10) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
        log.info("[teams] Sent: %.60s", text)
        return True
    except Exception as exc:
        log.warning("[teams] Failed: %s", exc)
        return False


def send_whatsapp(text: str) -> bool:
    """Send an alert via the configured WhatsApp bridge webhook URL.

    The URL should point to the themisiq_wa_bridge webhook receiver or any
    WhatsApp Business API endpoint that accepts JSON POST with a 'text' field.
    Falls back to WHATSAPP_WEBHOOK_URL env var.
    """
    url = _whatsapp_url()
    if not url:
        return False
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(url, json={"text": text})
            r.raise_for_status()
        log.info("[whatsapp] Sent: %.60s", text)
        return True
    except Exception as exc:
        log.warning("[whatsapp] Failed: %s", exc)
        return False


def notify_connectors(text: str) -> None:
    """Fire all configured connectors (Slack, Teams, WhatsApp). Swallows all errors."""
    try:
        send_slack(text)
    except Exception as exc:
        log.warning("[notify] Slack error: %s", exc)
    try:
        send_teams(text)
    except Exception as exc:
        log.warning("[notify] Teams error: %s", exc)
    try:
        send_whatsapp(text)
    except Exception as exc:
        log.warning("[notify] WhatsApp error: %s", exc)


def connectors_status() -> dict:
    """Return which connectors are currently configured (for admin UI)."""
    return {
        "slack_configured": bool(_slack_url()),
        "teams_configured": bool(_teams_url()),
        "whatsapp_configured": bool(_whatsapp_url()),
    }
