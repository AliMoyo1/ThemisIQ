"""
ThemisIQ - event delivery sweeper.

Runs every minute and delivers the stored events that are due: events written together with a source change
(core.events.enqueue) whose caller never delivered them, and events with a failed handler whose retry time has
come. See core/events.py for what the bus guarantees. Safe in every process: each event is leased before it is
delivered, so two sweepers never deliver one event together.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger("oneforall.event_sweeper")
_scheduler: BackgroundScheduler | None = None


def run_once() -> dict:
    """One sweep. A failure is logged and the next minute tries again; it never reaches the scheduler."""
    from core.events import deliver_pending
    try:
        counts = deliver_pending()
    except Exception as exc:
        log.error("Event sweep failed: %s", exc)
        return {}
    if counts["failed"] or counts["dead"]:
        log.warning("Event sweep: %s", counts)
    elif counts["delivered"]:
        log.info("Event sweep: %s", counts)
    return counts


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_once,
        IntervalTrigger(minutes=1),
        id="event_delivery_sweeper",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    _scheduler.start()
    log.info("Event delivery sweeper started, checking every minute")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Event delivery sweeper stopped")
