"""Capture-bound, review-only interpretation of a detected source change.

The model may select a short exact passage for a specialist. It cannot create
the change signal, invent a citation, or approve a regulatory effect.
"""
from __future__ import annotations

import hashlib
import json

from core.source_registry import SOURCES

MAX_QUOTE = 320


def verified_quote(capture: dict, quote: str) -> dict:
    source = SOURCES.get(capture.get("source_key"))
    body = capture.get("captured_text", "")
    if not source or source.rights not in {"link_and_short_excerpt", "public_reuse"}:
        raise ValueError("Source excerpt rights have not been reviewed")
    if capture.get("source_url") != source.url or not capture.get("hash_verified"):
        raise ValueError("Capture provenance could not be verified")
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != capture.get("text_sha256"):
        raise ValueError("Captured text hash does not match")
    if not isinstance(quote, str) or not quote.strip() or len(quote) > MAX_QUOTE or quote not in body:
        raise ValueError("Draft passage is not an exact short excerpt of the capture")
    return {"capture_id": capture["id"], "source_key": source.key,
            "source_url": source.url, "raw_sha256": capture["raw_sha256"],
            "text_sha256": capture["text_sha256"],
            "captured_at": capture["captured_at"], "quote": quote,
            "review_state": "draft", "legal_effect": "not_determined"}


def draft_change(capture: dict) -> dict:
    """Select one quote from the stored diff; return an abstention on any failure.

    The bounded prompt sends only public authority text, subject to the
    organization's existing AI policy. It never auto-creates an update/task.
    """
    if not capture.get("hash_verified"):
        return {"verified": False, "reason": "Capture integrity could not be verified"}
    if not capture.get("previous_capture_id"):
        return {"verified": False, "reason": "First baseline; no earlier capture to compare"}
    excerpt = capture.get("change_excerpt") or ""
    added = [line[1:].strip() for line in excerpt.splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    passages = [line for line in added if 12 <= len(line) <= MAX_QUOTE and
                line in capture.get("captured_text", "")]
    if not passages:
        return {"verified": False, "reason": "No exact reviewable changed passage was extracted"}
    try:
        from core.ai_client import create_message, is_configured
        if not is_configured():
            return {"verified": False, "reason": "AI provider unavailable; inspect the stored diff"}
        chosen = create_message([{"role": "user", "content":
            "Select one exact passage from this list that a specialist should review. "
            "Return only a JSON object with a quote property. Do not infer legal effect.\n" +
            json.dumps(passages[:20], ensure_ascii=False)}],
            max_tokens=180, feature="governance.run_drift_check",
            sources=[f"sentinel/law_capture/{capture['id']}"])
        payload = json.loads(chosen)
        quote = payload.get("quote") if isinstance(payload, dict) else None
        if quote not in passages:
            raise ValueError("The suggested quote was not in the captured diff")
        claim = verified_quote(capture, quote)
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        return {"verified": False, "reason": "Cannot verify a source-bound draft; inspect the stored diff"}
    return {"verified": True, "claim": claim,
            "instruction": "Review applicability, effective text and affected controls before recording an impact."}
