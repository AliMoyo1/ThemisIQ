"""FastAPI application — the ThemisIQ WhatsApp Bridge.

Endpoints:
  GET  /webhook/whatsapp        Meta/Twilio webhook verification handshake
  POST /webhook/whatsapp        inbound WhatsApp message -> process -> reply
  POST /webhook/themisiq        ThemisIQ outbound webhook (proactive alerts)
  GET  /health                  liveness

All flows: HMAC-verify -> rate-limit -> RBAC/intent -> act (read-only) ->
audit -> reply. No writes to ThemisIQ in MVP scope.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import PlainTextResponse

from . import audit, intent, llm
from .auth import (verify_themis_signature, verify_wa_challenge,
                   verify_meta_signature)
from .config import (Settings, get_settings, get_tenant_for_user, tenant_modules,
                     load_tenant_map, get_subscribers_for_org)
from .ratelimit import RateLimiter
from .themis_client import ThemisClient

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bridge")

PRIVACY_NOTICE = (
    "You're using the ThemisIQ assistant (read-only). Messages are processed "
    "under GDPR/CDPA and logged for audit; logs are retained 90 days. "
    "AI answers are generated and should be verified. Reply 'help' for options."
)

app = FastAPI(title="ThemisIQ WhatsApp Bridge", version="0.1.0")
settings: Settings = get_settings()
load_tenant_map()
_limiter = RateLimiter(limit_per_window=settings.rate_limit_per_user_per_min)
_SEEN_INTRO: set[str] = set()


# ---------------------------------------------------------------------------
# WhatsApp webhook: verification handshake
# ---------------------------------------------------------------------------
@app.get("/webhook/whatsapp")
async def wa_verify(mode: str | None = None, token: str | None = None,
                    challenge: str | None = None):
    chal = verify_wa_challenge(mode, token, challenge, settings)
    if chal is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    return PlainTextResponse(chal)


# ---------------------------------------------------------------------------
# WhatsApp webhook: inbound message
# ---------------------------------------------------------------------------
@app.post("/webhook/whatsapp")
async def wa_inbound(request: Request):
    raw = await request.body()
    # Meta signs payloads with X-Hub-Signature-256 using the app secret.
    sig = request.headers.get("X-Hub-Signature-256")
    if settings.wa_verify_token and not verify_meta_signature(
            raw, sig, settings.wa_verify_token):
        audit.log_event(actor="unknown", tenant_id=None, action="wa_verify", ok=False)
        raise HTTPException(status_code=401, detail="Bad signature")

    payload = json.loads(raw or b"{}")
    wa_user_id, text = _extract_wa_message(payload)
    if not wa_user_id or not text:
        return Response(status_code=200)  # ack, nothing to do

    return await _handle_user_message(wa_user_id, text)


# ---------------------------------------------------------------------------
# ThemisIQ outbound webhook: proactive alerts
# ---------------------------------------------------------------------------
@app.post("/webhook/themisiq")
async def themis_inbound(request: Request):
    raw = await request.body()
    sig = request.headers.get("X-ThemisIQ-Signature")
    if settings.themis_webhook_secret and not verify_themis_signature(
            raw, sig, settings.themis_webhook_secret):
        audit.log_event(actor="themisiq", tenant_id=None, action="themis_verify", ok=False)
        raise HTTPException(status_code=401, detail="Bad signature")
    payload = json.loads(raw or b"{}")
    org_id = payload.get("organisation_id")
    event_type = payload.get("event_type", "event")

    if not settings.themis_webhook_secret:
        # No secret configured -> accept but don't deliver (safe default).
        log.warning("ThemisIQ webhook received but THEMIS_WEBHOOK_SECRET unset; not delivering.")
        return Response(status_code=200)

    subscribers = get_subscribers_for_org(org_id)
    if not subscribers:
        log.info("ThemisIQ event %s for org %s: no subscribers", event_type, org_id)
        audit.log_event(actor="themisiq", tenant_id=str(org_id),
                        action="themis_no_subscribers", target=event_type, ok=True)
        return Response(status_code=200)

    # Fan out to every subscribed number, respecting each user's module scope.
    text = _format_alert(event_type, payload)
    delivered = 0
    for wa_user_id in subscribers:
        tenant = get_tenant_for_user(wa_user_id)
        if not tenant:
            continue
        # RBAC-style scope: only alert users whose modules cover this event.
        if not _event_allowed_for_user(event_type, tenant.get("modules", [])):
            continue
        await _send_reply(wa_user_id, text)
        audit.log_event(actor="themisiq", tenant_id=tenant.get("tenant_id"),
                        action="themis_alert_sent", target=event_type, ok=True)
        delivered += 1

    log.info("ThemisIQ event %s for org %s -> delivered to %d/%d subscribers",
             event_type, org_id, delivered, len(subscribers))
    return Response(status_code=200)


def _event_allowed_for_user(event_type: str, modules: list[str]) -> bool:
    """Map an event_type to the module a user must have to receive it.

    Keeps proactive alerts within each subscriber's read scope (mirrors the
    inbound RBAC model — a user only gets pings for modules they can see).
    """
    module_for_event = {
        "breach.created": "sentinel",
        "breach.updated": "sentinel",
        "dsar.created": "sentinel",
        "dpia.created": "aria",
        "dpia.submitted": "aria",
        "risk.threshold_breached": "erm",
        "kri.status_changed": "erm",
        "audit.logged": "command_centre",
        "control.effectiveness_changed": "governance",
    }
    needed = module_for_event.get(event_type)
    if needed is None:
        return True  # unknown events: deliver to all subscribers by default
    return needed in (modules or [])


def _format_alert(event_type: str, payload: dict) -> str:
    """Render a concise, human-readable WhatsApp alert from an event payload."""
    data = payload.get("data") or {}
    when = payload.get("timestamp", "")
    header = {"breach.created": "🚨 BREACH NOTIFICATION",
              "breach.updated": "🔄 BREACH UPDATE",
              "dsar.created": "📥 NEW DSAR",
              "dpia.created": "📝 NEW DPIA",
              "dpia.submitted": "✅ DPIA SUBMITTED",
              "risk.threshold_breached": "⚠️ RISK THRESHOLD BREACHED",
              "kri.status_changed": "📊 KRI STATUS CHANGE",
              "audit.logged": "🧾 AUDIT EVENT",
              "control.effectiveness_changed": "🛡️ CONTROL CHANGE"}.get(
                  event_type, f"🔔 ThemisIQ alert: {event_type}")
    parts = [header]
    if data:
        for key in ("title", "name", "id", "entity", "summary", "status", "score"):
            if key in data and data[key] not in (None, ""):
                parts.append(f"{key.replace('_', ' ').title()}: {data[key]}")
    if when:
        parts.append(f"Time: {when}")
    parts.append("— ThemisIQ (automated alert)")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# ---------------------------------------------------------------------------
# Core handler
# ---------------------------------------------------------------------------
async def _handle_user_message(wa_user_id: str, text: str) -> Response:
    # Rate limit
    if not _limiter.allow(wa_user_id):
        await _send_reply(wa_user_id, "Rate limit reached. Please slow down.")
        return Response(status_code=200)

    tenant = get_tenant_for_user(wa_user_id)
    if not tenant:
        audit.log_event(actor=wa_user_id, tenant_id=None, action="unbound_user", ok=False)
        await _send_reply(wa_user_id,
                          "This number is not linked to a ThemisIQ account. "
                          "Contact your administrator.")
        return Response(status_code=200)

    modules = tenant_modules(wa_user_id)
    intent_obj = intent.parse(wa_user_id, text, modules)

    # First-time privacy notice
    if wa_user_id not in _SEEN_INTRO:
        _SEEN_INTRO.add(wa_user_id)
        await _send_reply(wa_user_id, PRIVACY_NOTICE)

    if intent_obj.action == "help":
        await _send_reply(wa_user_id, intent.HELP_TEXT)
        audit.log_event(actor=wa_user_id, tenant_id=tenant["tenant_id"],
                        action="help", ok=True)
        return Response(status_code=200)

    if intent_obj.action == "denied":
        msg = (f"Access denied: your role does not permit '{intent_obj.params['needed']}' "
               f"data. Contact your administrator.")
        await _send_reply(wa_user_id, msg)
        audit.log_event(actor=wa_user_id, tenant_id=tenant["tenant_id"],
                        action="rbac_denied", target=intent_obj.params["needed"], ok=False)
        return Response(status_code=200)

    # Execute read-only action
    try:
        reply = _execute(tenant, intent_obj)
    except Exception as exc:  # pragma: no cover
        log.exception("action failed")
        reply = "Sorry, I couldn't complete that. Please try later or contact support."
        audit.log_event(actor=wa_user_id, tenant_id=tenant["tenant_id"],
                        action=intent_obj.action, ok=False, detail=str(exc)[:200])

    await _send_reply(wa_user_id, reply)
    audit.log_event(actor=wa_user_id, tenant_id=tenant["tenant_id"],
                    action=intent_obj.action, ok=True)
    return Response(status_code=200)


def _execute(tenant: dict, i: intent.Intent) -> str:
    client = ThemisClient(tenant["tenant_id"], tenant["api_key"])
    if i.action == "open_dpias":
        data = client.open_dpias()
        return _summarise(data, "Open DPIAs")
    if i.action == "open_dsars":
        data = client.open_dsars()
        return _summarise(data, "Open DSRs")
    if i.action == "open_breaches":
        data = client.open_breaches()
        return _summarise(data, "Open Breaches")
    if i.action == "risk_score":
        data = client.risk_score()
        return f"Current risk score: {_pretty(data)}"
    if i.action == "kri_status":
        data = client.kri_status()
        return f"KRI status:\n{_pretty(data)}"
    if i.action == "document":
        data = client.document(i.params.get("doc_id", ""))
        # LLM summarise (read-only; don't send full body to LLM if sensitive)
        return llm.complete(
            "You are a compliance assistant. Summarise this document record briefly.",
            f"Document: {json.dumps(data, ensure_ascii=False)[:1500]}")
    if i.action == "command_centre":
        data = client.command_centre()
        return f"Command Centre overview:\n{_pretty(data)}"
    if i.action == "draft_breach_text":
        # LLM drafts notification text from incident id (no live write)
        return llm.complete(
            "You are a DPO assistant. Draft a draft breach-notification text "
            "under GDPR Art. 33 / CDPA. Mark it DRAFT.",
            f"Incident id: {i.params.get('incident_id')}")
    if i.action == "qa":
        return llm.complete(
            "You are a data-protection and compliance expert (GDPR, CDPA, "
            "ISO 27001/42001). Answer concisely. Note you are AI-generated.",
            i.params["question"])
    return "Unsupported action."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _summarise(data: Any, title: str) -> str:
    if isinstance(data, dict):
        items = data.get("items") or data.get("data") or data.get("results")
    else:
        items = data
    if isinstance(items, list):
        if not items:
            return f"{title}: none open."
        lines = [f"{title} ({len(items)}):"]
        for it in items[:10]:
            if isinstance(it, dict):
                label = (it.get("title") or it.get("name") or it.get("id")
                         or "item")
                lines.append(f"• {label}")
            else:
                lines.append(f"• {it}")
        return "\n".join(lines)
    return f"{title}:\n{_pretty(data)}"


def _pretty(data: Any) -> str:
    try:
        s = json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        s = str(data)
    return s[:1500]


def _extract_wa_message(payload: dict) -> tuple[str, str]:
    """Extract (wa_user_id, text) from Meta Cloud API payload shape."""
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        wa_user_id = change.get("contacts", [{}])[0].get("wa_id", "")
        msg = change["messages"][0]
        return wa_user_id, msg.get("text", {}).get("body", "")
    except Exception:
        return "", ""


async def _send_reply(wa_user_id: str, text: str) -> None:
    """Send a WhatsApp text reply. Meta Cloud API shape shown; Twilio similar."""
    if settings.offline_mode:
        log.info("[offline] would send to %s: %s", wa_user_id, text[:80])
        return
    import httpx
    if settings.wa_provider == "twilio":
        # Twilio WhatsApp: POST to Twilio API with From/To/Body
        url = (f"https://api.twilio.com/2010-04-01/Accounts/"
               f"{settings.twilio_account_sid}/Messages.json")
        data = {"From": f"whatsapp:{settings.twilio_from_number}",
                "To": f"whatsapp:{wa_user_id}", "Body": text}
        httpx.post(url, data=data, auth=(settings.twilio_account_sid,
                                          settings.twilio_auth_token), timeout=10)
    else:
        url = (f"https://graph.facebook.com/{settings.wa_api_version}/"
               f"{settings.wa_phone_number_id}/messages")
        body = {"messaging_product": "whatsapp", "to": wa_user_id,
                "type": "text", "text": {"body": text[:4096]}}
        httpx.post(url, json=body,
                   headers={"Authorization": f"Bearer {settings.wa_token}"}, timeout=10)
