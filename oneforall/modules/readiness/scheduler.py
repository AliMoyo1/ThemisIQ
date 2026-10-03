"""
PLAN-36 P04: data-readiness and integrity centre -- background scan.

One job, daily, same cross-process lease pattern as
modules/aria/scheduler.py's retention sweep (database.try_acquire_scheduler_lock):
APScheduler's own max_instances=1 only protects one process's scheduler
against itself, not a second Uvicorn worker's separate scheduler instance
(scripts/deploy.py: --workers 2) running the same sweep at the same tick.

run_scan_now(org_id) is also called directly from the on-demand "Scan now"
route -- it does not touch the lease (an explicit, authenticated,
rate-limited user action is not the thing the lease protects against;
task_plan.md's "run on demand and through a bounded scheduler lease" names
these as two separate entry points, not one gating the other).
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db_background as get_db, list_active_tenants, tenant_context, try_acquire_scheduler_lock
from modules.readiness.data_service import run_rules_for_org

log = logging.getLogger("readiness.scheduler")
TZ = "UTC"

_scheduler: BackgroundScheduler | None = None
_LOCK_NAME = "readiness_scan_sweep"
_LOCK_LEASE_SECONDS = 3600


def run_scan_now(org_id: int) -> dict:
    """Runs every registered rule for exactly one org, inside its own
    tenant context. Safe to call from a live request (on-demand scan) or
    from the scheduled sweep below."""
    from database import get_db_background
    db = get_db_background()
    try:
        return run_rules_for_org(db, org_id)
    finally:
        db.close()


def _scan_sweep() -> None:
    lock_db = get_db()
    try:
        acquired = try_acquire_scheduler_lock(lock_db, _LOCK_NAME, _LOCK_LEASE_SECONDS)
    except Exception as exc:
        log.warning("Readiness scan: could not acquire scheduler lock, skipping this run: %s", exc)
        return
    finally:
        lock_db.close()
    if not acquired:
        log.info("Readiness scan: another worker already holds the lock, skipping this run.")
        return

    try:
        tenants = list_active_tenants()
    except Exception as exc:
        log.warning("Readiness scan: could not list tenants: %s", exc)
        return

    totals = {"new": 0, "updated": 0, "resolved": 0}
    for org_id, slug in tenants:
        try:
            with tenant_context(org_id, slug):
                counts = run_scan_now(org_id)
            for k, v in counts.items():
                if isinstance(v, int):
                    totals[k] = totals.get(k, 0) + v
        except Exception as exc:
            log.warning("Readiness scan failed for org %s: %s", org_id, exc)
    if sum(totals.values()):
        log.info("Readiness scan: %s", totals)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone=TZ)
    _scheduler.add_job(
        _scan_sweep,
        CronTrigger(hour=3, minute=30, timezone=TZ),
        id="readiness_scan_sweep",
        replace_existing=True,
        misfire_grace_time=300,
        max_instances=1,
    )
    _scheduler.start()
    log.info("Readiness scheduler started (daily scan at 03:30 UTC).")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def get_scheduler_status() -> dict:
    if _scheduler is None or not _scheduler.running:
        return {"running": False, "jobs": []}
    jobs = [
        {"id": job.id, "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None}
        for job in _scheduler.get_jobs()
    ]
    return {"running": True, "jobs": jobs}
