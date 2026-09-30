"""
P02: read-only backup freshness metadata.

File existence/age/size only -- never opens the zip, never runs
`pg_restore`, never contacts the offsite remote (those are
scripts/verify_latest_backup.py's job, a scheduled 03:00 check, not an
on-demand one). Matches task_plan.md P02's own "backup freshness is
metadata-only and never downloads a dump" acceptance line.

Mirrors the exact same BACKUP_PATH/BACKUP_MAX_AGE_HOURS/filename-pattern
conventions scripts/verify_latest_backup.py and modules/grid/scheduler.py's
perform_backup() already use, read directly from those files rather than
guessed, so this reports on the real thing, not a second, drifting copy of
it.
"""
import os
import time
from pathlib import Path

from core.capability_state import CapabilityState, AVAILABLE, DEGRADED, NOT_CONFIGURED

def _max_age_hours() -> int:
    return int(os.getenv("BACKUP_MAX_AGE_HOURS", "26"))


def _backup_jobs_enabled() -> bool:
    """Same flag modules/grid/scheduler.py's start_scheduler() already reads
    -- when the application's own backup jobs are disabled, a host-level
    backup service is authoritative and this process has no visibility into
    its freshness at all (not even "no file found", since there may
    genuinely be none in this app's own BACKUP_PATH by design)."""
    return os.getenv("GRID_BACKUP_JOBS_ENABLED", "true").lower() in ("1", "true", "yes", "on")


def get_backup_freshness() -> CapabilityState:
    if not _backup_jobs_enabled():
        return CapabilityState(
            state=NOT_CONFIGURED,
            reason_code="backup_host_managed",
            message="Backups are managed by the host, not this application -- freshness is not visible here.",
        )

    backup_dir = Path(os.getenv("BACKUP_PATH", "data/backups"))
    candidates = (
        sorted(backup_dir.glob("themisiq-*.zip"), key=lambda p: p.stat().st_mtime)
        if backup_dir.is_dir() else []
    )
    if not candidates:
        return CapabilityState(
            state=NOT_CONFIGURED,
            reason_code="no_backup_found",
            message="No backup file found yet.",
        )

    latest = candidates[-1]
    age_hours = (time.time() - latest.stat().st_mtime) / 3600
    size_kb = latest.stat().st_size // 1024

    max_age = _max_age_hours()
    if age_hours > max_age:
        return CapabilityState(
            state=DEGRADED,
            reason_code="backup_stale",
            message=f"Most recent backup is {age_hours:.1f}h old (expected within {max_age}h).",
            retryable=True,
        )

    return CapabilityState(
        state=AVAILABLE,
        reason_code="backup_fresh",
        message=f"Latest backup: {latest.name} ({size_kb} KB, {age_hours:.1f}h old).",
    )
