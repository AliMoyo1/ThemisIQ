"""Append-only audit log.

Mirrors ThemisIQ's own immutable audit-log expectation: every bridge action is
written as a JSON line with who/what/when/tenant. Never edited or deleted by
the application (retention handled out-of-band per the 7-year policy).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings

_lock = threading.Lock()


def log_event(*, actor: str, tenant_id: str | None, action: str,
              target: str | None = None, detail: str | None = None,
              ok: bool = True) -> None:
    """Append one audit record. Thread-safe; never raises."""
    settings = get_settings()
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor,            # wa_user_id
        "tenant_id": tenant_id,
        "action": action,
        "target": target,
        "detail": detail,
        "ok": ok,
    }
    line = json.dumps(record, ensure_ascii=False)
    try:
        with _lock:
            Path(settings.audit_log_path).open("a", encoding="utf-8").write(line + "\n")
    except Exception as exc:  # pragma: no cover - logging must never break flow
        # Fall back to stderr so failures are visible without crashing the bridge.
        print(f"[AUDIT FAIL] {line} :: {exc}")
