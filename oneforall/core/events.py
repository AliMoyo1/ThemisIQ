"""
One For All — cross-module event bus.

Modules emit events when state changes.  Event handlers in other modules
pick them up and create corresponding records (e.g. ARIA policy published
→ GRID audit finding flagged for review).

Events are stored in the `events` table and processed synchronously on emit.
Failed handlers log the error but don't block the source operation.
"""
import json
import logging
from datetime import datetime
from core.timeutils import utcnow
from typing import Callable, Optional

from database import get_db, get_db_background, insert_returning_id

log = logging.getLogger("oneforall.events")

# Registry: event_type → list of handler functions
_handlers: dict[str, list[Callable]] = {}


def on(event_type: str):
    """Decorator to register an event handler."""
    def decorator(func: Callable):
        _handlers.setdefault(event_type, []).append(func)
        return func
    return decorator


def emit(event_type: str, source_module: str, entity_type: str = "",
         entity_id: int = 0, payload: dict = None, user_id: int = None):
    """Emit an event: store it and run all registered handlers."""
    db = get_db()
    try:
        event_id = insert_returning_id(db,
            "INSERT INTO events (event_type, source_module, source_entity_type, "
            "source_entity_id, payload, created_by) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                event_type,
                source_module,
                entity_type,
                entity_id,
                json.dumps(payload) if payload else "{}",
                user_id,
            ),
        )
        db.commit()
    finally:
        db.close()

    # Run handlers
    handlers = _handlers.get(event_type, [])
    for handler in handlers:
        try:
            handler(event_type=event_type, source_module=source_module,
                    entity_type=entity_type, entity_id=entity_id,
                    payload=payload or {}, user_id=user_id)
            _mark_processed(event_id)
        except Exception as exc:
            log.exception("Event handler %s failed for %s: %s", handler.__name__, event_type, exc)
            _mark_failed(event_id, str(exc))

    # Fan out to registered outbound webhooks (best-effort; never blocks).
    try:
        from core.webhooks import dispatch_event
        dispatch_event(
            event_type=event_type,
            source_module=source_module,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
            user_id=user_id,
            org_id=None,  # emit() has no org context; webhook keeps its own org_id
        )
    except Exception as exc:
        # Webhook delivery must never break the source operation.
        log.warning("webhook dispatch failed for %s: %s", event_type, exc)


def _mark_processed(event_id: int):
    # Low-priority bookkeeping — use background connection (fail-fast, don't block UI)
    db = get_db_background()
    try:
        db.execute(
            "UPDATE events SET status='processed', processed_at=%s WHERE id=%s",
            (utcnow().isoformat(), event_id),
        )
        db.commit()
    except Exception:
        pass  # Bookkeeping failure is non-critical
    finally:
        db.close()


def _mark_failed(event_id: int, error: str):
    db = get_db_background()
    try:
        db.execute(
            "UPDATE events SET status='failed', processed_at=%s WHERE id=%s",
            (utcnow().isoformat(), event_id),
        )
        db.commit()
    except Exception:
        pass  # Bookkeeping failure is non-critical
    finally:
        db.close()


# ── Event type constants ─────────────────────────────────────────────────────
# ARIA
ARIA_POLICY_PUBLISHED   = "aria.policy.published"
ARIA_POLICY_UPDATED     = "aria.policy.updated"
ARIA_RISK_CREATED       = "aria.risk.created"
ARIA_RISK_ESCALATED     = "aria.risk.escalated"
ARIA_CONTROL_UPDATED    = "aria.control.updated"

# GRID
GRID_AUDIT_COMPLETED    = "grid.audit.completed"
GRID_FINDING_CREATED    = "grid.finding.created"
GRID_NC_RAISED          = "grid.non_conformance.raised"
GRID_POLICY_REQUESTED   = "grid.policy.requested"

# BCM
BCM_INCIDENT_DECLARED   = "bcm.incident.declared"
BCM_INCIDENT_RESOLVED   = "bcm.incident.resolved"
BCM_RISK_ESCALATED      = "bcm.risk.escalated"
BCM_PLAN_APPROVED       = "bcm.plan.approved"
BCM_PLAN_ACTIVATED      = "bcm.plan.activated"
BCM_PLAN_DEACTIVATED    = "bcm.plan.deactivated"

# Sentinel
SENTINEL_BREACH_CONFIRMED  = "sentinel.breach.confirmed"
SENTINEL_BREACH_RESOLVED   = "sentinel.breach.resolved"   # fired when status → closed/resolved/contained
SENTINEL_DPIA_COMPLETED    = "sentinel.dpia.completed"
SENTINEL_DSR_OVERDUE       = "sentinel.dsr.overdue"

# ERM
ERM_RISK_IDENTIFIED   = "erm.risk.identified"
ERM_RISK_ESCALATED    = "erm.risk.escalated"
ERM_RISK_MITIGATED    = "erm.risk.mitigated"
ERM_RISK_CLOSED       = "erm.risk.closed"
ERM_APPETITE_BREACHED = "erm.appetite.breached"

# ORM
ORM_EVENT_LOGGED      = "orm.event.logged"
ORM_EVENT_ELEVATED    = "orm.event.elevated"
ORM_EVENT_RESOLVED    = "orm.event.resolved"
