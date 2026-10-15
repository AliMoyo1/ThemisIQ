"""
One For All — cross-module event bus.

Modules emit events when state changes.  Event handlers in other modules
pick them up and create corresponding records (e.g. ARIA policy published
→ GRID audit finding flagged for review).

Events are stored in the `events` table and processed synchronously on emit.
Failed handlers log the error but don't block the source operation.

Delivery survives a crash and a failing handler (AI governance G1b):

* each handler's outcome is a row in `event_deliveries`, so a retry runs only the handlers that have not
  succeeded and a handler that did its work is never run a second time for the same event;
* `enqueue(db, ...)` writes the event on the CALLER's connection, so it commits or rolls back with the source
  change and a crash between the two cannot lose it; `deliver_pending()` (the sweeper) delivers what is due;
* a failed event is retried with growing waits up to MAX_ATTEMPTS, then marked `dead` for an administrator
  (`list_dead`, `retry_dead`); nothing is silently dropped, and a stale view is retried, never shown as done.

Handlers are still called at least once per event, so one whose side effect is not already idempotent keys on
the `event_id` it is passed.
"""
import json
import logging
from datetime import datetime, timedelta
from core.timeutils import utcnow
from typing import Callable, Optional

from database import (
    get_db, get_db_background, get_current_org, insert_returning_id, IntegrityError, list_active_tenants,
    tenant_context,
)
from core.best_effort import swallowed

MAX_ATTEMPTS = 5                       # failed deliveries of one handler before the event is dead
_BACKOFF_MINUTES = (1, 5, 15, 60, 360)  # wait after the 1st, 2nd, ... failed attempt
_LEASE_SECONDS = 120                   # an event being delivered is not picked up by the sweeper for this long
_GRACE_SECONDS = 30                    # an enqueued event is left to its own caller to deliver for this long

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
    reprocessed by a fresh claim.

    A second emit() for the same key never inserts a second row (backed by
    a real unique index, uq_events_dedup_key, not just a check-then-insert
    race) and never re-runs handlers/webhooks once the first call's row
    reaches status='processed'. Until then -- status is still 'pending'
    (this call is racing an in-flight first attempt) or 'failed' (a
    handler or the webhook handoff raised) -- a replay DOES re-run
    handlers/webhooks against the existing event id, rather than returning
    it untouched. This is a deliberate change from treating "a row exists"
    as "it was delivered": the row is committed before handlers run
    (committing only after would hold this connection's write lock for as
    long as arbitrary handler code takes to run, risking a self-deadlock
    against a handler's own, separate write connection), so a crash in
    that window used to produce a permanently un-processed event that
    every future replay would silently treat as already handled. The
    tradeoff this accepts is the ordinary at-least-once one: a handler
    invoked for the same logical event more than once, on the rare replay
    that lands after a crash or failure. Every handler registered for a
    dedup_key-using event type must tolerate that -- event_id (passed to
    every handler call below) is how a handler makes its own side effect
    idempotent against it; policy_published_handler and
    _auto_trigger_workflows (core/event_handlers.py) both do.

    A genuinely concurrent race between two emit() calls for the same
    dedup_key (not a later, sequential replay -- see claim_next_job's own
    lease guard, which is what actually prevents this in the one caller
    that uses dedup_key today) still has one residual gap: the losing call
    returns the winner's row id without confirming delivery actually
    happened, so if the winner's process dies before its own handler loop
    runs, nobody has run handlers for this event yet. Not separately
    guarded here -- the caller in that position (policy_publication.py's
    process_job) checks this event's actual status before deciding whether
    its own job may be marked complete, so a stuck 'pending'/'failed'
    status correctly keeps that job retryable rather than silently
    forgotten, even though no NEW handler run was forced at this exact
    moment.

    Returns the event's row id (a publication job persists this id after a
    successful emit; also how a dedup_key caller finds the original
    event's handler-failure status later via events.status). Existing
    callers that ignore the return value, or never pass dedup_key, are
    unaffected.
    """
    effective_org_id = org_id if org_id is not None else get_current_org()
    db = get_db()
    event_id = None
    try:
        if dedup_key:
            existing = db.execute(
                "SELECT id, status FROM events WHERE dedup_key=%s", (dedup_key,)
            ).fetchone()
            if existing:
                if existing["status"] == "processed":
                    return existing["id"]
                event_id = existing["id"]  # replay: skip the insert, rerun delivery below

        if event_id is None:
            try:
                event_id = insert_returning_id(db,
                    "INSERT INTO events (event_type, source_module, source_entity_type, "
                    "source_entity_id, payload, created_by, dedup_key, org_id, next_attempt_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        event_type,
                        source_module,
                        entity_type,
                        entity_id,
                        json.dumps(payload) if payload else "{}",
                        user_id,
                        dedup_key,
                        effective_org_id,
                        _now(_LEASE_SECONDS),  # this call delivers it; the sweeper waits out the lease
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

    try:
        deliver(event_id)
    except Exception:
        # The source operation must not fail because delivery could not start; the event is stored and the
        # sweeper delivers it once its lease runs out.
        swallowed("emit delivery (events)")
    return event_id


def enqueue(db, event_type: str, source_module: str, entity_type: str = "",
            entity_id: int = 0, payload: dict = None, user_id: int = None,
            org_id: int = None, dedup_key: str = None) -> int:
    """Store an event on the CALLER's connection and do not commit it.

    The event then commits or rolls back together with the change that caused it, so a crash between the source
    commit and the emit cannot lose it. Nothing is delivered yet: call `deliver(event_id)` after the caller's
    commit, or leave it to the sweeper (`deliver_pending`), which delivers it once a short grace has passed. A
    repeated dedup_key returns the existing event's id."""
    if dedup_key:
        existing = db.execute("SELECT id FROM events WHERE dedup_key=%s", (dedup_key,)).fetchone()
        if existing:
            return existing[0]
    return insert_returning_id(db,
        "INSERT INTO events (event_type, source_module, source_entity_type, source_entity_id, payload, "
        "created_by, dedup_key, org_id, next_attempt_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (event_type, source_module, entity_type, entity_id, json.dumps(payload) if payload else "{}", user_id,
         dedup_key, org_id if org_id is not None else get_current_org(), _now(_GRACE_SECONDS)),
    )


def deliver_committed(event_ids) -> None:
    """Deliver events a caller wrote with `enqueue` and has now committed. A failure to start delivery is logged and
    left to the sweeper: the change those events belong to is already safe."""
    for event_id in event_ids or ():
        try:
            deliver(event_id)
        except Exception:
            swallowed("deliver_committed (events)")


def _now(offset_seconds: int = 0) -> str:
    return (utcnow() + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%d %H:%M:%S")


def _handler_keys(event_type: str) -> list:
    """[(key, handler)] for an event type. A key names the handler stably across restarts and is unique within
    the type (two lambdas registered for one type become name and name#2)."""
    seen: dict = {}
    keyed = []
    for handler in _handlers.get(event_type, []):
        base = f"{getattr(handler, '__module__', '')}.{getattr(handler, '__qualname__', type(handler).__name__)}"
        seen[base] = seen.get(base, 0) + 1
        keyed.append((base if seen[base] == 1 else f"{base}#{seen[base]}", handler))
    return keyed


def _record_delivery(event_id: int, handler: str, status: str, error: str = None) -> None:
    """One handler's outcome. Bookkeeping uses its own short connection so it never holds a write lock while a
    handler runs."""
    db = get_db_background()
    try:
        db.execute(
            "INSERT INTO event_deliveries (event_id, handler, status, attempts, last_error) "
            "VALUES (%s, %s, %s, 1, %s) "
            "ON CONFLICT (event_id, handler) DO UPDATE SET status = excluded.status, "
            "attempts = event_deliveries.attempts + 1, last_error = excluded.last_error, "
            "updated_at = CURRENT_TIMESTAMP",
            (event_id, handler, status, (error or "")[:500] or None),
        )
        db.commit()
    except Exception:
        swallowed("_record_delivery (events)")
    finally:
        db.close()


def deliver(event_id: int) -> str:
    """Run the handlers of one stored event that have not succeeded yet and record each outcome.

    Returns the event's status afterwards: "processed", "failed" (a retry is scheduled), "dead" (the attempt cap
    was reached) or "missing". A handler that already succeeded for this event is skipped."""
    db = get_db_background()
    try:
        event = db.execute("SELECT * FROM events WHERE id=%s", (event_id,)).fetchone()
        done = {r["handler"] for r in db.execute(
            "SELECT handler FROM event_deliveries WHERE event_id=%s AND status='ok'", (event_id,)).fetchall()}
    finally:
        db.close()
    if event is None:
        return "missing"
    if event["status"] in ("processed", "dead"):
        return event["status"]
    try:
        payload = json.loads(event["payload"] or "{}")
    except (TypeError, ValueError):
        payload = {}
    org_id = event["org_id"] if event["org_id"] is not None else get_current_org()
    entity_type, entity_id = event["source_entity_type"] or "", event["source_entity_id"] or 0

    # Status is decided once, from the whole loop's outcome (_finish): a later handler's success never hides an
    # earlier handler's failure, and an event type with no handler still reaches "processed".
    for key, handler in _handler_keys(event["event_type"]):
        if key in done:
            continue
        try:
            handler(event_type=event["event_type"], source_module=event["source_module"],
                    entity_type=entity_type, entity_id=entity_id, payload=payload,
                    user_id=event["created_by"], event_id=event_id, org_id=org_id)
        except Exception as exc:
            log.exception("Event handler %s failed for %s: %s", key, event["event_type"], exc)
            _record_delivery(event_id, key, "failed", f"{type(exc).__name__}: {exc}")
        else:
            _record_delivery(event_id, key, "ok")

    # Outbound webhooks: a background thread does the HTTP delivery with its own backoff, so this only hands off.
    # A failed HANDOFF counts like a failed handler (a retry hands off again); a successful one is not repeated.
    if "webhook" not in done:
        try:
            from core.webhooks import dispatch_event_background
            dispatch_event_background(
                event_type=event["event_type"], source_module=event["source_module"],
                entity_type=entity_type, entity_id=entity_id, payload=payload,
                user_id=event["created_by"], org_id=org_id,
            )
        except Exception as exc:
            log.warning("webhook dispatch failed for %s: %s", event["event_type"], exc)
            _record_delivery(event_id, "webhook", "failed", f"{type(exc).__name__}: {exc}")
        else:
            _record_delivery(event_id, "webhook", "ok")
    return _finish(event_id)


def _finish(event_id: int) -> str:
    """Set the event's status from its deliveries: processed, or failed with the next try, or dead."""
    db = get_db_background()
    try:
        failed = db.execute(
            "SELECT attempts, last_error FROM event_deliveries WHERE event_id=%s AND status='failed' "
            "ORDER BY attempts DESC", (event_id,)).fetchall()
        if not failed:
            status, sets = "processed", ("status=%s, processed_at=%s, last_error=NULL, next_attempt_at=NULL",
                                         ("processed", utcnow().isoformat()))
        else:
            attempts = max(r["attempts"] for r in failed)
            error = failed[0]["last_error"]
            if attempts >= MAX_ATTEMPTS:
                status = "dead"
                sets = ("status=%s, attempts=%s, last_error=%s, dead_lettered_at=%s, next_attempt_at=NULL",
                        ("dead", attempts, error, _now()))
            else:
                wait = _BACKOFF_MINUTES[min(attempts, len(_BACKOFF_MINUTES)) - 1]
                status = "failed"
                sets = ("status=%s, attempts=%s, last_error=%s, next_attempt_at=%s",
                        ("failed", attempts, error, _now(wait * 60)))
        db.execute(f"UPDATE events SET {sets[0]} WHERE id=%s", (*sets[1], event_id))
        db.commit()
        return status
    except Exception:
        swallowed("_finish (events)")  # bookkeeping failure is non-critical: the sweeper will look again
        return "failed"
    finally:
        db.close()


def _claim(event_id: int) -> bool:
    """Take a lease on a due event so two sweepers (or a sweeper and a slow emit) never deliver it together."""
    db = get_db_background()
    try:
        taken = db.execute(
            "UPDATE events SET next_attempt_at=%s WHERE id=%s AND status IN ('pending', 'failed') "
            "AND next_attempt_at IS NOT NULL AND next_attempt_at <= %s",
            (_now(_LEASE_SECONDS), event_id, _now()),
        ).rowcount
        db.commit()
        return taken == 1
    except Exception:
        swallowed("_claim (events)")
        return False
    finally:
        db.close()


def deliver_pending(limit: int = 50) -> dict:
    """Deliver the stored events that are due: pending ones (written with a source change, or whose emit() died)
    and failed ones whose retry time has come. Each runs inside its own tenant. Safe from several processes.

    Only events with a scheduled attempt are touched: rows stored before this delivery design existed have none,
    keep the status they had, and are never replayed behind anyone's back."""
    counts = {"delivered": 0, "failed": 0, "dead": 0, "skipped": 0}
    db = get_db_background()
    try:
        due = db.execute(
            "SELECT id, org_id FROM events WHERE status IN ('pending', 'failed') AND dead_lettered_at IS NULL "
            "AND next_attempt_at IS NOT NULL AND next_attempt_at <= %s ORDER BY next_attempt_at, id LIMIT %s",
            (_now(), int(limit)),
        ).fetchall()
    finally:
        db.close()
    slugs = dict(list_active_tenants()) if due else {}
    for row in due:
        if not _claim(row["id"]):
            counts["skipped"] += 1
            continue
        try:
            if row["org_id"] is not None and slugs.get(row["org_id"]):
                with tenant_context(row["org_id"], slugs[row["org_id"]], is_super_admin=False):
                    status = deliver(row["id"])
            else:
                status = deliver(row["id"])
        except Exception:
            log.exception("Event %s could not be delivered", row["id"])
            counts["skipped"] += 1
            continue
        counts[{"processed": "delivered", "failed": "failed", "dead": "dead"}.get(status, "skipped")] += 1
    return counts


def list_dead(limit: int = 100) -> list:
    """Events that used up their attempts, newest first, for an administrator."""
    db = get_db()
    try:
        return [dict(r) for r in db.execute(
            "SELECT id, event_type, source_module, source_entity_type, source_entity_id, org_id, attempts, "
            "last_error, created_at, dead_lettered_at FROM events WHERE status = 'dead' "
            "ORDER BY id DESC LIMIT %s", (max(1, min(int(limit), 500)),)).fetchall()]
    finally:
        db.close()


def retry_dead(event_id: int) -> bool:
    """Give a dead event a fresh set of attempts. The handlers that already succeeded still do not run again."""
    db = get_db()
    try:
        changed = db.execute(
            "UPDATE events SET status='pending', attempts=0, dead_lettered_at=NULL, next_attempt_at=%s "
            "WHERE id=%s AND status='dead'", (_now(), event_id)).rowcount
        db.execute("UPDATE event_deliveries SET attempts=0 WHERE event_id=%s AND status='failed'", (event_id,))
        db.commit()
        return changed == 1
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

# AI governance (plans/ai-governance)
AI_USE_SUBMITTED        = "ai_use.submitted"
AI_USE_APPROVED         = "ai_use.approved"
AI_USE_REJECTED         = "ai_use.rejected"
AI_USE_RETURNED         = "ai_use.returned"
AI_USE_MATERIAL_CHANGE  = "ai_use.material_change"
AI_USE_RETIRED          = "ai_use.retired"
AI_ASSESSMENT_COMPLETED = "ai_assessment.completed"
AI_DECISION_REQUESTED   = "ai_use.decision_requested"
AI_REVIEWER_ASSIGNED    = "ai_use.reviewer_assigned"
AI_DECIDER_ASSIGNED     = "ai_use.decider_assigned"
AI_DECISION_MADE        = "ai_use.decision_made"
AI_DECISION_REVOKED     = "ai_use.decision_revoked"
AI_REGULATORY_CONFIRMED = "ai_use.regulatory_confirmed"
AI_PACK_ISSUED          = "ai_use.pack_issued"
AI_LITERACY_PUBLISHED   = "ai_literacy.published"
AI_CONTROL_FAILED       = "ai_control.failed"
EVIDENCE_EXPIRED        = "evidence.expired"
EVALUATION_FAILED       = "evaluation.failed"
VENDOR_INCIDENT         = "vendor.incident"
REGULATION_REVIEWED     = "regulation.reviewed"

# ORM
ORM_EVENT_LOGGED      = "orm.event.logged"
ORM_EVENT_ELEVATED    = "orm.event.elevated"
ORM_EVENT_RESOLVED    = "orm.event.resolved"
