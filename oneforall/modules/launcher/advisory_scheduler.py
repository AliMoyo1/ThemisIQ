"""
Advisory Composer — Background scheduler.

Jobs:
  Job 1  Daily governance briefing composition  (daily 05:30 UTC)
         - Collects signals from platform data
         - Ranks by severity
         - Inserts top 3 into governance_advisories
         - Idempotent: checks for existing briefing before composing
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db_background as get_db  # scheduler: fail-fast, never block UI

log = logging.getLogger("advisory.scheduler")
TZ = "UTC"

_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Job — Daily Briefing Composition
# ─────────────────────────────────────────────────────────────────────────────

def _compose_advisories() -> None:
    """Daily: collect signals and compose governance briefing."""
    log.info("Advisory: running daily briefing composition")
    db = get_db()
    try:
        from core.advisor import compose_briefing
        from core.timeutils import utcnow

        today = utcnow().strftime("%Y-%m-%d")
        count = compose_briefing(db, today)
        log.info("Advisory compose: %d signal(s) inserted for %s", count, today)
    except Exception:
        log.exception("Advisory compose failed")
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler start / stop
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone=TZ)

    _scheduler.add_job(
        _compose_advisories,
        CronTrigger(hour=5, minute=30, timezone=TZ),
        id="advisory_composer",
        replace_existing=True,
        misfire_grace_time=300,
    )

    _scheduler.start()
    log.info("Advisory scheduler started — daily briefing at 05:30 UTC")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Advisory scheduler stopped")
