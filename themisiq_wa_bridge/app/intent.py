"""Intent parsing + RBAC gate.

Maps a free-text WhatsApp message to a safe, read-only action the user's role
permits. Returns (action, params) or a clarification question. If the user's
modules don't include the action's required module, the action is rejected
before any ThemisIQ call is made.

Available actions (backed by ThemisIQ API v1):
  list_risks    - /api/v1/risks (module: erm)
  list_breaches - /api/v1/breaches (module: sentinel)
  list_audits   - /api/v1/audits (module: grid)
  qa            - LLM Q&A only (no module required)
  draft_breach  - LLM drafting, no live API call (module: sentinel)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# module each action requires (must be in the user's allowed modules set)
ACTION_MODULE = {
    "list_risks":     "erm",
    "list_breaches":  "sentinel",
    "list_audits":    "grid",
    "draft_breach":   "sentinel",
    "qa":             "none",
}

HELP_TEXT = (
    "ThemisIQ assistant (read-only). Try:\n"
    "- list open risks\n"
    "- list open breaches\n"
    "- list audits\n"
    "- draft breach notification for incident <id>\n"
    "- <any compliance question>\n"
    "Reply 'help' for this menu."
)


@dataclass
class Intent:
    action: str
    params: dict
    requires_module: Optional[str]


def parse(wa_user_id: str, text: str, allowed_modules: set[str]) -> Intent:
    t = text.strip().lower()

    if t in ("help", "menu", "?"):
        return Intent("help", {}, "none")

    if "breach" in t and ("open" in t or "list" in t or "all" in t):
        return _gate("list_breaches", {"status": "open"}, allowed_modules)

    if "risk" in t and ("open" in t or "list" in t or "all" in t or "status" in t or "score" in t):
        category = _extract_after(t, ("category",)) or None
        return _gate("list_risks", {"status": "open", "category": category}, allowed_modules)

    if "audit" in t and ("open" in t or "list" in t or "all" in t or "status" in t or "progress" in t):
        status = "In Progress" if "progress" in t or "open" in t else None
        return _gate("list_audits", {"status": status}, allowed_modules)

    if "draft breach" in t or "draft notification" in t:
        inc = _extract_after(t, ("incident", "for incident", "id")) or ""
        return _gate("draft_breach", {"incident_id": inc}, allowed_modules)

    # Default: treat as a compliance Q&A (no module required).
    return Intent("qa", {"question": text.strip()}, "none")


def _gate(action: str, params: dict, allowed_modules: set[str]) -> Intent:
    mod = ACTION_MODULE.get(action, "none")
    if mod != "none" and mod not in allowed_modules:
        return Intent("denied", {"needed": mod}, "none")
    return Intent(action, params, mod)


def _extract_after(text: str, keys: tuple[str, ...]) -> str:
    for k in keys:
        if k in text:
            return text.split(k, 1)[1].strip().strip(":").strip()
    return ""
