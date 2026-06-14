#!/usr/bin/env python3
"""
verify_latest_backup.py — Daily structural backup verification.

Run daily at 03:00 CAT (wired into grid/scheduler.py APScheduler job).
Verifies the most recent backup zip is structurally sound.
Does NOT restore data (that is the weekly restore drill).

Exit codes:
    0 — PASS (all checks passed)
    1 — FAIL (backup missing, corrupt, or R2 copy absent)

Alerting: on FAIL, the caller (APScheduler) should invoke _notify_admins.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

BACKUP_DIR = Path(os.getenv("BACKUP_PATH", "data/backups"))
MAX_AGE_HOURS = int(os.getenv("BACKUP_MAX_AGE_HOURS", "26"))  # allow 2h drift above 24h schedule


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    # 1. Find the most recent backup zip
    candidates = sorted(BACKUP_DIR.glob("themisiq-*.zip"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        _fail(f"No backup zips found in {BACKUP_DIR}")

    latest = candidates[-1]
    age_hours = (time.time() - latest.stat().st_mtime) / 3600
    if age_hours > MAX_AGE_HOURS:
        _fail(f"Most recent backup is {age_hours:.1f}h old (> {MAX_AGE_HOURS}h): {latest.name}")

    # 2. Zip structural integrity
    with zipfile.ZipFile(latest, "r") as zf:
        bad = zf.testzip()
        if bad:
            _fail(f"Corrupt entry in zip: {bad}")
        if "themisiq.dump" not in zf.namelist():
            _fail(f"themisiq.dump missing from {latest.name} — not a PG backup?")
        dump_data = zf.read("themisiq.dump")

    # 3. pg_restore structural check (no DB connection needed)
    with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tmp:
        tmp.write(dump_data)
        tmp_path = tmp.name

    try:
        res = subprocess.run(
            ["pg_restore", "--list", tmp_path],
            capture_output=True, timeout=60,
        )
        if res.returncode != 0 or b"TABLE DATA" not in res.stdout:
            _fail(
                f"pg_restore --list rejected {latest.name}:\n"
                f"{res.stderr.decode()[:500]}"
            )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # 4. Offsite R2 presence (optional — skip if rclone not configured)
    r2_remote = os.getenv("BACKUP_OFFSITE_RCLONE_REMOTE", "")
    if r2_remote:
        res = subprocess.run(
            ["rclone", "lsf", f"{r2_remote}/{latest.name}"],
            capture_output=True, timeout=30,
        )
        if res.returncode != 0 or latest.name.encode() not in res.stdout:
            _fail(f"{latest.name} not found on R2 remote {r2_remote}")

    size_kb = latest.stat().st_size // 1024
    print(f"PASS: {latest.name} ({size_kb} KB, {age_hours:.1f}h old)")
    sys.exit(0)


if __name__ == "__main__":
    main()
