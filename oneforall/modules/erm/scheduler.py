"""
ERM module — Background scheduler.

Jobs:
  Job 1  Emerging risk horizon scan  (weekly, Monday 06:00 CAT)
         - Runs the same grounded (live web search) / knowledge-only scan
           as the "Scan for emerging risks" button on the External Context
           page, via ai_service.run_emerging_scan()
         - Idempotent: emerging_title_exists() skips candidates that
           already exist as a non-dismissed inbox item
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from modules.erm import ai_service

log = logging.getLogger("erm.scheduler")
TZ = "Africa/Harare"

_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Job 1 — Emerging Risk Horizon Scan
# ─────────────────────────────────────────────────────────────────────────────

def _emerging_scan_job() -> None:
    log.info("ERM: running weekly emerging-risk horizon scan")
    try:
        result = ai_service.run_emerging_scan()
        log.info(
            "ERM emerging-risk scan done: %d candidate(s) created (grounded=%s)",
            result["created"], result["grounded"],
        )
    except Exception as exc:
        log.warning("ERM emerging-risk scan failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler start / stop
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone=TZ)

    # Emerging risk scan: weekly Monday 06:00 CAT (ahead of BCM's Monday
    # 07:00/08:00 jobs, ready before the week's first risk review)
    _scheduler.add_job(
        _emerging_scan_job,
        CronTrigger(day_of_week="mon", hour=6, minute=0, timezone=TZ),
        id="erm_emerging_scan",
        replace_existing=True,
        misfire_grace_time=300,
    )

    _scheduler.start()
    log.info("ERM scheduler started — jobs: emerging_scan (Mon 06:00 CAT)")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("ERM scheduler stopped")
