"""
Whether AI Governance is switched on for an organization.

A rollout switch, not a security control. The pages and calls behind it are protected by capability and business-unit
scope whether it is on or off; off only hides the entry points (the navigation link, the "Uses AI?" fields, the Vault
target), so an organization meets the feature when someone decides it should. The AI impact assessment is not behind
it: that is existing functionality that moved from Sentinel and stays reachable for the people who held it.

The default for an organization with no stored choice comes from `AI_GOVERNANCE_DEFAULT_ENABLED` (off unless set), so a
deployment never shows the feature to an organization by accident. A value that cannot be read falls back to that
default and says so in the log. The answer is cached for a short while per process, because every page asks.
"""
import logging
import time

from config import settings
from database import get_db_background

log = logging.getLogger("oneforall.ai_governance")

_SETTING = "ai_governance.enabled.org{}"
_TTL_SECONDS = 30.0
_cache: dict = {}


def default_enabled() -> bool:
    return bool(settings.AI_GOVERNANCE_DEFAULT_ENABLED)


def _read(org_id: int) -> bool:
    try:
        db = get_db_background()
        try:
            row = db.execute("SELECT value FROM settings WHERE key = %s", (_SETTING.format(org_id),)).fetchone()
        finally:
            db.close()
    except Exception:
        log.warning("AI Governance switch for organization %s could not be read; using the default", org_id, exc_info=True)
        return default_enabled()
    if row is None or row["value"] is None:
        return default_enabled()
    return str(row["value"]).strip() == "1"


def is_enabled(org_id, fresh: bool = False) -> bool:
    """True when AI Governance is shown to this organization. A platform administrator (no organization) always sees it."""
    if org_id is None:
        return True
    now = time.monotonic()
    hit = _cache.get(org_id)
    if hit and not fresh and now - hit[0] < _TTL_SECONDS:
        return hit[1]
    value = _read(org_id)
    _cache[org_id] = (now, value)
    return value


def is_set(org_id: int) -> bool:
    """True when the organization has a stored choice (otherwise it follows the platform default)."""
    db = get_db_background()
    try:
        row = db.execute("SELECT 1 FROM settings WHERE key = %s", (_SETTING.format(org_id),)).fetchone()
    finally:
        db.close()
    return row is not None


def set_enabled(org_id: int, enabled: bool) -> None:
    db = get_db_background()
    try:
        db.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (_SETTING.format(org_id), "1" if enabled else "0"))
        db.commit()
    finally:
        db.close()
    _cache[org_id] = (time.monotonic(), bool(enabled))


# Separation of duties on decisions: the person who decides is neither the one who asked nor the system's owner. On
# unless an organization turns it off (a single person may be the whole function); the choice is audited and recorded
# on every decision made while it is off.
_SEPARATION = "ai_governance.separation.org{}"


def separation_required(org_id) -> bool:
    if org_id is None:
        return True
    try:
        db = get_db_background()
        try:
            row = db.execute("SELECT value FROM settings WHERE key = %s", (_SEPARATION.format(org_id),)).fetchone()
        finally:
            db.close()
    except Exception:
        log.warning("Separation setting for organization %s could not be read; keeping it on", org_id, exc_info=True)
        return True
    return True if row is None or row["value"] is None else str(row["value"]).strip() != "0"


def set_separation(org_id: int, required: bool) -> None:
    db = get_db_background()
    try:
        db.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (_SEPARATION.format(org_id), "1" if required else "0"))
        db.commit()
    finally:
        db.close()


def clear_cache() -> None:
    _cache.clear()
