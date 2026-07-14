"""Authentication & signature verification.

- WhatsApp webhook GET verification (Meta challenge).
- HMAC-SHA256 verification of inbound payloads, both directions:
    * Meta WhatsApp payloads (X-Hub-Signature-256)
    * ThemisIQ outbound webhooks (X-ThemisIQ-Signature)
"""
from __future__ import annotations

import hashlib
import hmac
import json

from .config import Settings, get_settings


def verify_meta_signature(raw_body: bytes, signature_header: str | None,
                          app_secret: str) -> bool:
    """Verify Meta's X-Hub-Signature-256: 'sha256=<hmac>'.

    NOTE: Meta signs with the *app secret*. If you use a different secret for
    webhook verification, pass it here. Returns False on any mismatch.
    """
    if not app_secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, provided)


def verify_themis_signature(raw_body: bytes, signature_header: str | None,
                            secret: str) -> bool:
    """Verify ThemisIQ's X-ThemisIQ-Signature: 'sha256=<hmac of raw body>'."""
    if not secret or not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, provided)


def verify_wa_challenge(mode: str | None, token: str | None,
                        challenge: str | None, settings: Settings) -> str | None:
    """Meta webhook subscription handshake.

    Returns the challenge string to echo back, or None to reject.
    """
    if mode == "subscribe" and token == settings.wa_verify_token:
        return challenge
    return None
