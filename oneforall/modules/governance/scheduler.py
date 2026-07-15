"""
Governance Effectiveness Scheduler (T1.3).

Jobs:
  Job 1  Nightly control effectiveness recompute  (daily 03:00 UTC)
         Scores every active canonical control from its 7 factors.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db_background as get_db

log = logging.getLogger("governance.scheduler")
TZ = "UTC"

_scheduler: BackgroundScheduler | None = None


def _nightly_recompute() -> None:
    """Recompute effectiveness scores for all active canonical controls."""
    log.info("Governance: running nightly control effectiveness recompute")
    db = get_db()
    try:
        from modules.governance.effectiveness import recompute_all_controls
        count = recompute_all_controls(db)
        db.commit()
        log.info("Governance scheduler: scored %d control(s)", count)
    except Exception as exc:
        log.warning("Governance nightly recompute failed: %s", exc)
    finally:
        db.close()


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone=TZ)
    _scheduler.add_job(
        _nightly_recompute,
        CronTrigger(hour=3, minute=0, timezone=TZ),
        id="governance_effectiveness_recompute",
        replace_existing=True,
        misfire_grace_time=300,
    )
    _scheduler.start()
    log.info("Governance scheduler started — nightly recompute at 03:00 UTC")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Governance scheduler stopped")
