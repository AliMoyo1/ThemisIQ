"""Environment-driven configuration.

All secrets come from environment / .env — never hardcoded, never committed.
Per-tenant API keys + user->tenant bindings are loaded from a JSON mapping
file (THEMIS_TENANT_MAP) that the operator maintains out-of-band (not in git).
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Bridge itself ---
    bridge_base_url: str = Field(default="http://localhost:8000",
                                 description="Public base URL the bridge listens on")
    log_level: str = "INFO"

    # --- WhatsApp Business Platform (Meta Cloud API or Twilio) ---
    # Meta Cloud API:
    wa_verify_token: str = Field(default="", description="GET webhook verify token")
    wa_token: str = ""                       # Meta permanent/user access token
    wa_phone_number_id: str = ""             # Meta phone number ID
    wa_api_version: str = "v19.0"
    # Twilio fallback (set WA_PROVIDER=twilio to use):
    wa_provider: str = Field(default="meta", description="meta | twilio")
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # --- ThemisIQ ---
    themis_base_url: str = Field(default="https://themisiq.net",
                                 description="Base URL of the ThemisIQ instance")
    themis_tenant_map_path: str = Field(
        default="tenant_map.json",
        description="JSON file mapping wa_user_id -> {tenant_id, api_key, role, modules}")

    # --- WhatsApp App Secret (separate from verify_token) ---
    # Meta uses this to sign POST payloads (X-Hub-Signature-256).
    # Get it from Meta App Dashboard > App Settings > Basic > App Secret.
    wa_app_secret: str = Field(default="", description="Meta App Secret for HMAC payload verification")

    # --- ThemisIQ outbound webhook (proactive alerts) ---
    themis_webhook_secret: str = Field(
        default="", description="HMAC secret for verifying ThemisIQ webhook payloads")

    # --- LLM provider (reuse ThemisIQ's provider set) ---
    ai_provider: str = Field(default="anthropic", description="anthropic|deepseek|openai|gemini|ollama")
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    ollama_host: str = "http://localhost:11434"
    ai_model: str = Field(default="claude-sonnet-4", description="Provider model id")

    # --- Operational ---
    message_log_retention_days: int = 90
    audit_log_path: str = "audit.log.jsonl"
    rate_limit_per_user_per_min: int = 10
    # If true, LLM calls are skipped and stubbed (safe for offline smoke tests).
    offline_mode: bool = Field(default=False, description="Disable outbound LLM/WA/API calls")


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Per-tenant mapping. Kept OUT of git. Example shape:
# {
#   "wa_user_263783047375": {
#     "tenant_id": "org_abc",
#     "api_key": "tq_live_xxx",          # read-only, scoped to modules
#     "role": "compliance_manager",
#     "modules": ["sentinel", "erm", "command_centre"]
#   }
# }
# ---------------------------------------------------------------------------
_TENANT_MAP: Dict[str, Any] = {}


def get_tenant_for_user(wa_user_id: str) -> Optional[Dict[str, Any]]:
    return _TENANT_MAP.get(wa_user_id)


def tenant_modules(wa_user_id: str) -> set[str]:
    t = get_tenant_for_user(wa_user_id)
    return set(t.get("modules", [])) if t else set()


# ---------------------------------------------------------------------------
# Org -> subscribers reverse map.
# ThemisIQ outbound webhooks carry an integer `organisation_id`, but the
# tenant map is keyed by wa_user_id. Build a reverse index so proactive alerts
# can fan out to every linked WhatsApp number for that org.
#
# Each tenant-map entry may carry an `org_id` (int) matching ThemisIQ's
# `organisation_id`. A top-level `org_subscriptions` block can also map an
# org_id directly to a list of wa_user_ids (useful when several numbers watch
# one org). Both sources are merged.
# ---------------------------------------------------------------------------
_ORG_SUBS: Dict[int, list[str]] = {}


def _rebuild_org_subs() -> None:
    global _ORG_SUBS
    merged: Dict[int, list[str]] = {}
    # 1) per-entry org_id
    for wa_id, rec in _TENANT_MAP.items():
        oid = rec.get("org_id")
        if isinstance(oid, int):
            merged.setdefault(oid, [])
            if wa_id not in merged[oid]:
                merged[oid].append(wa_id)
    # 2) explicit org_subscriptions override
    for oid_str, ids in (_TENANT_MAP.get("org_subscriptions") or {}).items():
        try:
            oid = int(oid_str)
        except (TypeError, ValueError):
            continue
        for wid in ids:
            merged.setdefault(oid, [])
            if wid not in merged[oid]:
                merged[oid].append(wid)
    _ORG_SUBS = merged


def get_subscribers_for_org(org_id: Optional[int]) -> list[str]:
    """Return wa_user_ids subscribed to alerts for a given org (empty if none)."""
    if org_id is None:
        return []
    return list(_ORG_SUBS.get(int(org_id), []))


def load_tenant_map(path: Optional[str] = None) -> Dict[str, Any]:
    global _TENANT_MAP
    p = Path(path or get_settings().themis_tenant_map_path)
    if p.exists():
        _TENANT_MAP = json.loads(p.read_text(encoding="utf-8"))
    else:
        _TENANT_MAP = {}
    _rebuild_org_subs()
    return _TENANT_MAP
