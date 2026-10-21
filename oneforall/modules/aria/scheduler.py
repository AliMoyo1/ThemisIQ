"""
ARIA policy workflow — Background scheduler (PLAN-35 T09).

Jobs:
  Job 1  Publication queue drain  (every 60 seconds)
         - Claims and processes due aria_policy_publication_jobs rows:
           copies an approved version into the Evidence Vault / GRID
           evidence, emits ARIA_POLICY_PUBLISHED. See policy_publication.py.
  Job 2  Policy workflow retention  (daily 02:00 UTC)
         - Expires drafts inactive since their own expires_at (section 7.5)
         - Moves orphaned staging/artifacts directories to trash once they
           clear ARIA_POLICY_ORPHAN_GRACE_HOURS
         - Permanently deletes trash entries older than
           ARIA_POLICY_TRASH_RETENTION_DAYS
         Runs per organization with its own referenced-paths snapshot, so
         one organization's live drafts/versions never affect another's
         cleanup pass. Guarded by a real cross-process lease
         (database.try_acquire_scheduler_lock, PLAN-35 T11 review fix) so
         the production multi-worker deployment's several independent
         scheduler instances cannot all run this at once -- APScheduler's
         own max_instances=1 only protects one process against itself.
         Job 1 needs no equivalent guard: it already claims work through a
         real database lock (policy_publication.claim_next_job), not
         APScheduler's.

Both jobs are safe to run even when no organization has policy authoring
enabled yet: an empty queue/no stale drafts is a fast no-op, matching every
other per-module scheduler in this codebase (none gate registration behind
a feature flag; the flag instead gates whether the workflow can be used to
create the rows these jobs act on in the first place).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from database import get_db_background as get_db, list_active_tenants, tenant_context, try_acquire_scheduler_lock
from modules.aria import policy_publication, policy_storage, policy_workflow_service as svc

log = logging.getLogger("aria.scheduler")
TZ = "UTC"

_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Job 1 — Publication queue drain
# ─────────────────────────────────────────────────────────────────────────────

def _drain_publication_queue() -> None:
    """A scheduler tick has no request to inherit tenant context from --
    get_db() silently stays on the public schema/default RLS scope unless
    something binds it first (database.py's get_db(), PostgreSQL branch).
    Bind each active tenant in turn so a claim/process pass (and anything
    it triggers synchronously within that call -- ARIA_POLICY_PUBLISHED's
    handlers, the Ask ARIA reindex) runs against that org's own data, not
    just whichever org happens to be the default/public one."""
    try:
        tenants = list_active_tenants()
    except Exception as exc:
        log.warning("ARIA publication queue: could not list tenants: %s", exc)
        return

    totals = {}
    for org_id, slug in tenants:
        try:
            with tenant_context(org_id, slug):
                counts = policy_publication.run_due_jobs(limit=10)
            for k, v in counts.items():
                totals[k] = totals.get(k, 0) + v
        except Exception as exc:
            log.warning("ARIA publication queue drain failed for org %s: %s", org_id, exc)
    if sum(totals.values()):
        log.info("ARIA publication queue: %s", totals)


# ─────────────────────────────────────────────────────────────────────────────
# Job 2 — Retention (section 7.5)
# ─────────────────────────────────────────────────────────────────────────────

_RETENTION_LOCK_NAME = "aria_retention_sweep"
_RETENTION_LOCK_LEASE_SECONDS = 3600  # generous vs. a once-daily job; see below


def _retention_sweep() -> None:
    """max_instances=1 on this job (see start_scheduler) only prevents a
    slow run from overlapping ITS OWN process's next scheduled tick. The
    production deployment runs multiple Uvicorn workers
    (scripts/deploy.py: --workers 2), each with its own APScheduler
    instance, so that guard alone does nothing to stop a second worker's
    scheduler from starting this exact same sweep at the same 02:00 UTC
    tick (PLAN-35 T11 review finding). Guarded here with a real
    cross-process lease (database.try_acquire_scheduler_lock) instead: the
    losing worker logs and returns immediately rather than duplicating the
    whole sweep. A 1-hour lease is generous for a job that runs once a day
    -- long enough to cover a genuinely slow sweep across many tenants,
    short enough that a worker crashing mid-sweep does not block tomorrow's
    run, which starts nearly 23 hours later.

    Binds each active tenant's context in turn (see _drain_publication_queue's
    docstring) around that org's own slice of the sweep, so drafts/versions
    living in a non-default tenant schema are actually reached, not silently
    skipped."""
    lock_db = get_db()
    try:
        acquired = try_acquire_scheduler_lock(lock_db, _RETENTION_LOCK_NAME, _RETENTION_LOCK_LEASE_SECONDS)
    except Exception as exc:
        log.warning("ARIA retention: could not acquire scheduler lock, skipping this run: %s", exc)
        return
    finally:
        lock_db.close()
    if not acquired:
        log.info("ARIA retention: another worker already holds the lock, skipping this run.")
        return

    try:
        from config import settings
        grace_hours = settings.ARIA_POLICY_ORPHAN_GRACE_HOURS
        trash_days = settings.ARIA_POLICY_TRASH_RETENTION_DAYS

        try:
            tenants = list_active_tenants()
        except Exception as exc:
            log.warning("ARIA retention: could not list tenants: %s", exc)
            return

        total_expired = total_trashed = total_purged = 0
        for org_id, slug in tenants:
            try:
                with tenant_context(org_id, slug):
                    db = get_db()
                    try:
                        total_expired += svc.expire_stale_drafts(db, org_id)
                        referenced = svc.gather_referenced_storage_paths(db, org_id)
                    finally:
                        db.close()
            except Exception as exc:
                log.warning("ARIA retention: draft expiry failed for org %s: %s", org_id, exc)
                continue

            try:
                trashed = policy_storage.move_orphans_to_trash(org_id, referenced, grace_hours)
                total_trashed += len(trashed)
                purged = policy_storage.purge_expired_trash(org_id, trash_days)
                total_purged += len(purged)
            except Exception as exc:
                log.warning("ARIA retention: storage cleanup failed for org %s: %s", org_id, exc)

        if total_expired or total_trashed or total_purged:
            log.info(
                "ARIA retention sweep: %d draft(s) expired, %d dir(s) trashed, %d dir(s) purged",
                total_expired, total_trashed, total_purged,
            )
    except Exception as exc:
        log.warning("ARIA retention sweep failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler start / stop
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone=TZ)

    _scheduler.add_job(
        _drain_publication_queue,
        IntervalTrigger(seconds=60),
        id="aria_publication_drain",
        replace_existing=True,
        misfire_grace_time=30,
        max_instances=1,
    )
    _scheduler.add_job(
        _retention_sweep,
        CronTrigger(hour=2, minute=0, timezone=TZ),
        id="aria_policy_retention",
        replace_existing=True,
        misfire_grace_time=3600,
        max_instances=1,
    )

    _scheduler.start()
    log.info("ARIA policy scheduler started -- publication drain every 60s, retention daily at 02:00 UTC")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("ARIA policy scheduler stopped")
