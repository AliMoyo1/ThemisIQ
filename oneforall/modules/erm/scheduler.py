"""
ERM module — Background scheduler.

Jobs:
  Job 1  Scan queue drain  (every 2 seconds)
         - Claims at most one durable job per tick and executes it outside
           the ASGI event loop, with explicit tenant context.
  Job 2  Weekly horizon scan enqueue  (Monday 06:00 CAT)
         - Enqueues one job per active organization.  The same queue is used
           by the External Context button, so scheduled and interactive scans
           share deduplication, crash recovery, and status semantics.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from database import list_active_tenants, tenant_context
from modules.erm import scan_jobs

log = logging.getLogger("erm.scheduler")
TZ = "Africa/Harare"

_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Job 1 — Durable queue drain
# ─────────────────────────────────────────────────────────────────────────────

def _drain_scan_queue() -> None:
    """Process at most one queued job per tick, preserving backpressure.

    APScheduler runs this function in its own worker thread.  Each Uvicorn
    process may have a scheduler, so ``scan_jobs.claim_next_job`` uses a
    database row lock/lease to make cross-process claims safe.
    """
    try:
        tenants = list_active_tenants()
    except Exception as exc:
        log.warning("ERM scan queue: could not list tenants (%s)", type(exc).__name__)
        return

    for org_id, slug in tenants:
        try:
            with tenant_context(org_id, slug):
                result = scan_jobs.process_next_job(org_id)
        except Exception as exc:
            log.warning(
                "ERM scan queue processing failed for org %s (%s)",
                org_id,
                type(exc).__name__,
            )
            continue
        if result:
            log.info(
                "ERM scan job %s finished state=%s created=%s grounded=%s",
                result.get("job_id"),
                result.get("state"),
                result.get("created", 0),
                result.get("grounded", False),
            )
            return


# ─────────────────────────────────────────────────────────────────────────────
# Job 2 — Weekly enqueue for every active tenant
# ─────────────────────────────────────────────────────────────────────────────

def _enqueue_weekly_scans() -> None:
    try:
        tenants = list_active_tenants()
    except Exception as exc:
        log.warning("ERM weekly scan: could not list tenants (%s)", type(exc).__name__)
        return

    queued = reused = 0
    for org_id, slug in tenants:
        try:
            with tenant_context(org_id, slug):
                _, created = scan_jobs.enqueue_scan(org_id, requested_by=None)
            if created:
                queued += 1
            else:
                reused += 1
        except Exception as exc:
            log.warning(
                "ERM weekly scan enqueue failed for org %s (%s)",
                org_id,
                type(exc).__name__,
            )
    log.info("ERM weekly scan enqueue: queued=%d already_active=%d", queued, reused)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler start / stop
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone=TZ)

    _scheduler.add_job(
        _drain_scan_queue,
        IntervalTrigger(seconds=2),
        id="erm_emerging_scan_queue",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=10,
    )

    # Emerging risk scan: weekly Monday 06:00 CAT (ahead of BCM's Monday
    # 07:00/08:00 jobs).  This only queues work; the drain job executes it.
    _scheduler.add_job(
        _enqueue_weekly_scans,
        CronTrigger(day_of_week="mon", hour=6, minute=0, timezone=TZ),
        id="erm_emerging_scan_weekly",
        replace_existing=True,
        misfire_grace_time=300,
    )

    _scheduler.start()
    log.info("ERM scheduler started — queue drain every 2s; weekly enqueue Mon 06:00 CAT")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("ERM scheduler stopped")
