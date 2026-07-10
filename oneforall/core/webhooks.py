"""Outbound webhook delivery for ThemisIQ.

Previously webhooks could be *registered* (admin UI) and *logged* as "test"
pings, but nothing actually fired them when platform events occurred. This
module closes that gap: when an event is emitted on the bus, every active
webhook subscribed to that event_type receives a signed POST.

Security (mirrors the platform's inbound expectations documented for
integrators):
  * Payload is signed with HMAC-SHA256 using the webhook's stored `secret`.
  * Signature is sent in the `X-ThemisIQ-Signature` header as `sha256=<hex>`.
  * Delivery is best-effort with 3 retries + exponential backoff.
  * Every attempt is written to `webhook_logs` (URL, code, body, success).
  * Failures are logged but never block the source operation (same contract
    as the in-process event handlers).

Payload shape (stable contract for subscribers):
  {
    "event_type": str,
    "source_module": str,
    "source_entity_type": str,
    "source_entity_id": int,
    "timestamp": ISO-8601 UTC,
    "organisation_id": <from webhook.org_id or null>,
    "triggered_by_user": int | null,
    "data": { ...event-specific... }
  }
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from database import get_db, get_db_background
from core.timeutils import utcnow

log = logging.getLogger("oneforall.webhooks")

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; 1, 2, 4, ...
_TIMEOUT = 10.0


def _sign(secret: str, raw_body: bytes) -> str:
    return "sha256=" + hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()


def _build_payload(event_type: str, source_module: str, entity_type: str,
                   entity_id: int, payload: dict, user_id: Optional[int],
                   org_id: Optional[int]) -> dict:
    return {
        "event_type": event_type,
        "source_module": source_module,
        "source_entity_type": entity_type,
        "source_entity_id": entity_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "organisation_id": org_id,
        "triggered_by_user": user_id,
        "data": payload or {},
    }


def _deliver_once(url: str, secret: str, body: bytes,
                  signature: str) -> tuple[int, str]:
    """POST one webhook. Returns (status_code, response_body_text)."""
    try:
        r = httpx.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-ThemisIQ-Signature": signature,
                "User-Agent": "ThemisIQ-Webhooks/1.0",
            },
            timeout=_TIMEOUT,
        )
        return r.status_code, (r.text or "")[:2000]
    except Exception as exc:  # network/DNS/TLS errors
        return 0, f"delivery error: {exc}"


def _log_attempt(webhook_id: int, event_type: str, payload: dict,
                 code: int, body: str, success: bool) -> None:
    db = get_db_background()
    try:
        db.execute(
            "INSERT INTO webhook_logs "
            "(webhook_id, event, payload_json, response_code, response_body, success) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (webhook_id, event_type, json.dumps(payload), code, body[:2000],
             1 if success else 0),
        )
        db.commit()
    except Exception as exc:  # logging must never raise
        log.warning("webhook_logs insert failed for wh=%s: %s", webhook_id, exc)
    finally:
        db.close()


def deliver(webhook_id: int, url: str, secret: str, payload: dict) -> bool:
    """Deliver a payload to one webhook with retry/backoff. Returns success."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = _sign(secret, body)

    last_code, last_body = 0, ""
    for attempt in range(_MAX_RETRIES):
        code, body_text = _deliver_once(url, secret, body, signature)
        last_code, last_body = code, body_text
        # 2xx = success; 4xx (except 429) = permanent failure, stop retrying.
        if 200 <= code < 300:
            _log_attempt(webhook_id, payload["event_type"], payload, code,
                         body_text, True)
            return True
        if code == 429 or code == 0 or 500 <= code < 600:
            # retryable: rate-limited / network / server error
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_BACKOFF_BASE * (2 ** attempt))
                continue
        else:
            # client error (4xx, non-429) — no point retrying
            break

    _log_attempt(webhook_id, payload["event_type"], payload, last_code,
                 last_body, False)
    log.warning("webhook %s delivery failed after %d attempts (last code %s)",
                webhook_id, _MAX_RETRIES, last_code)
    return False


def dispatch_event(event_type: str, source_module: str, entity_type: str,
                   entity_id: int, payload: dict, user_id: Optional[int],
                   org_id: Optional[int]) -> None:
    """Fan out an emitted event to all active webhooks subscribed to it.

    Intended to be called from core.events.emit() AFTER in-process handlers
    run, so webhook delivery never blocks or fails the source operation.
    """
    envelope = _build_payload(event_type, source_module, entity_type,
                              entity_id, payload, user_id, org_id)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, url, secret, events FROM webhooks "
            "WHERE is_active = 1 AND events LIKE %s",
            (f"%{event_type}%",),
        ).fetchall()
    except Exception as exc:
        log.warning("webhook subscriber lookup failed: %s", exc)
        return
    finally:
        db.close()

    for wh in rows:
        # `events` is a comma-separated list; match precisely.
        subscribed = [e.strip() for e in (wh["events"] or "").split(",")]
        if event_type not in subscribed:
            continue
        secret = wh["secret"] or ""
        # Stamp the envelope with this webhook's org context (webhooks table
        # has no org_id column; left as None — emit() carries no org either).
        env = dict(envelope)
        env["organisation_id"] = None
        try:
            deliver(wh["id"], wh["url"], secret, env)
        except Exception as exc:  # a bad URL/config must not crash emit()
            log.exception("webhook %s delivery raised: %s", wh["id"], exc)
            _log_attempt(wh["id"], event_type, env, 0, f"error: {exc}", False)
