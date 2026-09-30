"""
PLAN-36 P05: evidence collection campaigns -- background sweep.

One daily job, same cross-process lease pattern as modules/aria/scheduler.py's
retention sweep and modules/readiness/scheduler.py's scan sweep
(database.try_acquire_scheduler_lock): mark overdue requests, schedule T-3
reminders (into the existing email_reminders table/engine -- no new send
mechanism), and generate the next cycle for any closed recurring campaign.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db_background as get_db, list_active_tenants, tenant_context, try_acquire_scheduler_lock
from modules.evidence_campaigns import data_service as svc

log = logging.getLogger("evidence_campaigns.scheduler")
TZ = "UTC"

_scheduler: BackgroundScheduler | None = None
_LOCK_NAME = "evidence_campaigns_sweep"
_LOCK_LEASE_SECONDS = 3600


def _sweep() -> None:
    lock_db = get_db()
    try:
        acquired = try_acquire_scheduler_lock(lock_db, _LOCK_NAME, _LOCK_LEASE_SECONDS)
    except Exception as exc:
        log.warning("Evidence campaigns sweep: could not acquire scheduler lock, skipping: %s", exc)
        return
    finally:
        lock_db.close()
    if not acquired:
        log.info("Evidence campaigns sweep: another worker already holds the lock, skipping.")
        return

    try:
        tenants = list_active_tenants()
    except Exception as exc:
        log.warning("Evidence campaigns sweep: could not list tenants: %s", exc)
        return

    totals = {"overdue": 0, "reminders": 0, "recurring": 0}
    for org_id, slug in tenants:
        try:
            with tenant_context(org_id, slug):
                db = get_db()
                try:
                    totals["overdue"] += svc.mark_overdue_requests(db, org_id)
                    totals["reminders"] += svc.schedule_reminders(db, org_id)
                    totals["recurring"] += svc.generate_recurring_campaigns(db, org_id)
                finally:
                    db.close()
        except Exception as exc:
            log.warning("Evidence campaigns sweep failed for org %s: %s", org_id, exc)
    if sum(totals.values()):
        log.info("Evidence campaigns sweep: %s", totals)


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone=TZ)
    _scheduler.add_job(
        _sweep,
        CronTrigger(hour=4, minute=0, timezone=TZ),
        id="evidence_campaigns_sweep",
        replace_existing=True,
        misfire_grace_time=300,
        max_instances=1,
    )
    _scheduler.start()
    log.info("Evidence campaigns scheduler started (daily sweep at 04:00 UTC).")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
