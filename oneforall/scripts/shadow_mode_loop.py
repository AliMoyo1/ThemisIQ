#!/usr/bin/env python3
"""
shadow_mode_loop.py — Phase M: 48-hour shadow mode orchestration.

Keeps the shadow PostgreSQL instance in sync with the production SQLite database
and continuously verifies parity. Production SQLite is NEVER written to.

Usage:
    # Full 48-hour shadow mode (recommended):
    python scripts/shadow_mode_loop.py \\
        --sqlite data/oneforall.db \\
        --postgres postgresql://themisiq:shadow_pass@localhost:5433/themisiq_shadow \\
        --hours 48 --interval-hours 6

    # Quick smoke test (2 cycles, 30 minutes apart):
    python scripts/shadow_mode_loop.py ... --hours 1 --interval-hours 0.5

    # Verify-only mode (no re-sync, parity checks only):
    python scripts/shadow_mode_loop.py ... --verify-only

Log output is written to shadow_mode_YYYYMMDD_HHMMSS.log in the current directory.

Exit codes:
    0 — All parity checks passed throughout the shadow period.
    1 — One or more parity failures detected.
    2 — Shadow mode aborted (DB connection error, initial migration failed).
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

_SCRIPTS = Path(__file__).parent


def _run_script(script: str, args: list[str], log: logging.Logger, timeout: int = 3600) -> bool:
    """Run a Python script via subprocess. Returns True on success (exit 0)."""
    cmd = [sys.executable, str(_SCRIPTS / script)] + args
    log.info("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                log.info("  [%s] %s", script, line)
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                log.warning("  [%s] STDERR: %s", script, line)
        if result.returncode != 0:
            log.error("%s exited %d", script, result.returncode)
            return False
        return True
    except subprocess.TimeoutExpired:
        log.error("%s timed out after %ds", script, timeout)
        return False
    except Exception as exc:
        log.error("%s failed: %s", script, exc)
        return False


def _check_pg_reachable(postgres_url: str, log: logging.Logger) -> bool:
    try:
        import psycopg2
        conn = psycopg2.connect(postgres_url, connect_timeout=5)
        conn.close()
        return True
    except Exception as exc:
        log.error("Cannot connect to shadow PG: %s", exc)
        return False


def _check_sqlite_readable(sqlite_path: str, log: logging.Logger) -> bool:
    import sqlite3
    try:
        conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        conn.execute("SELECT COUNT(*) FROM sqlite_master")
        conn.close()
        return True
    except Exception as exc:
        log.error("Cannot open SQLite: %s", exc)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase M shadow mode orchestration.")
    parser.add_argument("--sqlite", required=True, help="Path to SQLite .db file.")
    parser.add_argument("--postgres", required=True, help="Shadow PG connection URL.")
    parser.add_argument("--hours", type=float, default=48.0,
                        help="Total shadow mode duration in hours (default: 48).")
    parser.add_argument("--interval-hours", type=float, default=6.0,
                        help="Re-sync interval in hours (default: 6).")
    parser.add_argument("--verify-only", action="store_true",
                        help="Skip re-sync, run parity + warm-replay only.")
    args = parser.parse_args()

    # Configure logging to both stdout and a log file
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = Path(f"shadow_mode_{ts}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file),
        ],
    )
    log = logging.getLogger("shadow")

    log.info("=" * 70)
    log.info("Phase M — Shadow Mode")
    log.info("  SQLite:   %s", args.sqlite)
    log.info("  Shadow PG: %s", args.postgres.replace("//", "//***:***@").split("@")[-1])
    log.info("  Duration: %.1fh  Interval: %.1fh", args.hours, args.interval_hours)
    log.info("  Log:      %s", log_file)
    log.info("=" * 70)

    # Pre-flight
    if not _check_sqlite_readable(args.sqlite, log):
        sys.exit(2)
    if not _check_pg_reachable(args.postgres, log):
        log.error("Shadow PG not reachable. Start it first:")
        log.error("  docker compose -f docker-compose.shadow.yml up -d")
        sys.exit(2)

    # Initial schema creation + data migration
    if not args.verify_only:
        log.info("")
        log.info("── Initial migration ──────────────────────────────────────────────")
        ok = _run_script("sqlite_to_postgres.py", [
            "--sqlite", args.sqlite,
            "--postgres", args.postgres,
            "--apply",
        ], log, timeout=7200)
        if not ok:
            log.error("Initial migration failed — shadow mode aborted.")
            sys.exit(2)

    # Shadow loop
    end_time = datetime.now() + timedelta(hours=args.hours)
    cycle = 0
    failures: list[str] = []

    while True:
        cycle += 1
        now = datetime.now()
        remaining = (end_time - now).total_seconds() / 3600
        log.info("")
        log.info("── Cycle %d  (%.1fh remaining) ────────────────────────────────────",
                 cycle, remaining)

        # 1. Re-sync (delta — idempotent ON CONFLICT DO NOTHING)
        if not args.verify_only:
            log.info("  [1/3] Re-sync SQLite → Shadow PG...")
            ok = _run_script("sqlite_to_postgres.py", [
                "--sqlite", args.sqlite,
                "--postgres", args.postgres,
                "--apply",
            ], log, timeout=3600)
            if not ok:
                msg = f"Cycle {cycle}: re-sync failed"
                failures.append(msg)
                log.error(msg)

        # 2. Parity check
        log.info("  [2/3] Parity check...")
        ok = _run_script("verify_pg_parity.py", [
            "--sqlite", args.sqlite,
            "--postgres", args.postgres,
        ], log, timeout=600)
        if not ok:
            msg = f"Cycle {cycle}: parity FAIL"
            failures.append(msg)
            log.error(msg)

        # 3. Warm replay
        log.info("  [3/3] Warm replay...")
        ok = _run_script("warm_replay.py", [
            "--sqlite", args.sqlite,
            "--postgres", args.postgres,
        ], log, timeout=300)
        if not ok:
            msg = f"Cycle {cycle}: warm replay FAIL"
            failures.append(msg)
            log.error(msg)

        log.info("  Cycle %d done. Failures so far: %d", cycle, len(failures))

        # Check if done
        now = datetime.now()
        if now >= end_time:
            break

        # Sleep until next cycle (or end time, whichever is sooner)
        next_wake = now + timedelta(hours=args.interval_hours)
        sleep_until = min(next_wake, end_time)
        sleep_secs = max(0, (sleep_until - datetime.now()).total_seconds())
        log.info("  Next cycle in %.1f min at %s",
                 sleep_secs / 60, sleep_until.strftime("%H:%M:%S"))
        time.sleep(sleep_secs)

    # Summary
    log.info("")
    log.info("=" * 70)
    log.info("Shadow mode complete — %d cycles, %d failure(s)", cycle, len(failures))
    if failures:
        log.error("FAIL — the following checks did not pass:")
        for f in failures:
            log.error("  • %s", f)
        log.error("Investigate before proceeding to Phase N cutover.")
        sys.exit(1)
    else:
        log.info("PASS — all parity and warm-replay checks passed.")
        log.info("Shadow mode complete. Ready for Phase N-pre (rollback plan) → Phase N (cutover).")
        sys.exit(0)


if __name__ == "__main__":
    main()
