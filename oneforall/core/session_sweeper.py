"""
ThemisIQ - expired session sweeper.

Deletes the sessions rows whose expires_at has passed, once at startup and then every hour. Without it a row is only
removed when that exact token is presented again after expiry (core.auth.get_session_user), so the rows of browsers
that never come back would stay forever. The systemd service runs one process, but the Docker entrypoint starts several
workers (WORKERS, default 2), each with its own scheduler, so a run first takes the cross-process lease
(database.try_acquire_scheduler_lock) and skips when another worker holds it.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.auth import cleanup_expired_sessions
from core.timeutils import utcnow_aware
from database import get_db_background, try_acquire_scheduler_lock

log = logging.getLogger("oneforall.session_sweeper")
_scheduler: BackgroundScheduler | None = None
_LOCK_NAME = "expired_session_purge"
# Long enough to cover the start skew between the workers' ticks, far below the one hour interval so a worker that
# died holding the lease never blocks the next run.
_LOCK_LEASE_SECONDS = 300


def run_once() -> int:
    """One purge. Returns how many sessions were removed, 0 when another worker holds the lease. A failure is logged
    and the next tick tries again; it never reaches the scheduler."""
    try:
        lock_db = get_db_background()
        try:
            acquired = try_acquire_scheduler_lock(lock_db, _LOCK_NAME, _LOCK_LEASE_SECONDS)
        finally:
            lock_db.close()
        if not acquired:
            log.info("Session purge: another worker already holds the lock, skipping this run.")
            return 0
        removed = cleanup_expired_sessions()
    except Exception as exc:
        log.error("Session purge failed: %s", exc)
        return 0
    if removed:
        log.info("Session purge: removed %d expired session(s)", removed)
    return removed


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_once,
        IntervalTrigger(hours=1),
        id="expired_session_purge",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
        next_run_time=utcnow_aware(),  # the startup run: the scheduler thread fires it at once, startup never waits
    )
    _scheduler.start()
    log.info("Session sweeper started, purging expired sessions now and every hour")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Session sweeper stopped")
