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

from database import get_db, get_db_background, insert_returning_id, IntegrityError

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
         entity_id: int = 0, payload: dict = None, user_id: int = None,
         org_id: int = None, dedup_key: str = None) -> int:
    """Emit an event: store it and run all registered handlers.

    org_id scopes outbound webhook delivery (see the dispatch block below).
    Pass it explicitly when the caller has no live request context but does
    know the tenant (e.g. a scheduler looping per-org); otherwise it is
    resolved automatically from the current request's tenant context.

    dedup_key (PLAN-35 T09, section 10.3): pass a stable, globally-unique
    key (e.g. a publication_key) when the caller might retry/replay the
    same logical event after a crash -- a job that committed its own
    durable side effects but died before recording completion, and gets
    reprocessed by a fresh claim. Without this, a replay re-runs every
    handler (duplicate tasks, cross-module links, notifications) and
    re-dispatches to every webhook subscriber a second time, none of which
    are idempotent on their own. With it, a second emit() for the same key
    returns the first call's event id without running handlers or
    dispatching webhooks again -- backed by a real unique index
    (uq_events_dedup_key), not just a check-then-insert race.

    Returns the event's row id (a publication job persists this id after a
    successful emit; also how a dedup_key caller finds the original
    event's handler-failure status later via events.status). Existing
    callers that ignore the return value, or never pass dedup_key, are
    unaffected.
    """
    db = get_db()
    try:
        if dedup_key:
            existing = db.execute(
                "SELECT id FROM events WHERE dedup_key=%s", (dedup_key,)
            ).fetchone()
            if existing:
                return existing[0]
        try:
            event_id = insert_returning_id(db,
                "INSERT INTO events (event_type, source_module, source_entity_type, "
                "source_entity_id, payload, created_by, dedup_key) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    event_type,
                    source_module,
                    entity_type,
                    entity_id,
                    json.dumps(payload) if payload else "{}",
                    user_id,
                    dedup_key,
                ),
            )
            db.commit()
        except IntegrityError:
            if not dedup_key:
                raise
            # Lost a race with a concurrent emit() for the same dedup_key --
            # its row is authoritative; this call must not run handlers too.
            db.rollback()
            existing = db.execute(
                "SELECT id FROM events WHERE dedup_key=%s", (dedup_key,)
            ).fetchone()
            if not existing:
                raise
            return existing[0]
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
    # Runs on a background thread (see core.webhooks._delivery_pool) so
    # retry backoff sleeps never add latency to the request/job that
    # triggered the event.
    try:
        from core.webhooks import dispatch_event_background
        from database import get_current_org
        # Explicit org_id wins; otherwise fall back to the request-scoped
        # tenant context set by auth middleware. A caller with neither (e.g.
        # a scheduler querying a table with no org column to key off) gets
        # None here, which dispatch_event() treats as "match no webhook" --
        # fail closed rather than fan out to every tenant. Resolved here
        # (on the calling thread) rather than inside the background thread,
        # since get_current_org() reads a request-scoped ContextVar that is
        # only meaningfully "current" before the handoff.
        effective_org_id = org_id if org_id is not None else get_current_org()
        dispatch_event_background(
            event_type=event_type,
            source_module=source_module,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
            user_id=user_id,
            org_id=effective_org_id,
        )
    except Exception as exc:
        # Webhook delivery must never break the source operation.
        log.warning("webhook dispatch failed for %s: %s", event_type, exc)

    return event_id


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
ERM_RISK_UPDATED      = "erm.risk.updated"
ERM_RISK_ESCALATED    = "erm.risk.escalated"
ERM_RISK_MITIGATED    = "erm.risk.mitigated"
ERM_RISK_CLOSED       = "erm.risk.closed"
ERM_APPETITE_BREACHED = "erm.appetite.breached"

# ORM
ORM_EVENT_LOGGED      = "orm.event.logged"
ORM_EVENT_ELEVATED    = "orm.event.elevated"
ORM_EVENT_RESOLVED    = "orm.event.resolved"
