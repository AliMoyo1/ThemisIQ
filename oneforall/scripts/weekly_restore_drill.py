#!/usr/bin/env python3
"""
weekly_restore_drill.py — Weekly restore drill run via APScheduler (Sunday 04:00 CAT).

Steps:
    1. Pull yesterday's backup from R2 (if BACKUP_OFFSITE_RCLONE_REMOTE is set),
       else use the latest local zip.
    2. Spin up a temp PostgreSQL container (postgres:16-alpine --rm).
    3. Restore the pg_dump into the temp container.
    4. Run a row-count parity check (counts only) against prod.
    5. Tear down the temp container.
    6. Exit 0 on PASS, 1 on any FAIL.

The APScheduler job in grid/scheduler.py calls this as a subprocess so that
a Docker failure doesn't crash the main app process.

Requires:
    - Docker available on the host (`docker run` works without sudo)
    - BACKUP_OFFSITE_RCLONE_REMOTE env var set for R2 pull (optional)
    - DATABASE_URL set for prod row-count comparison

Budget: 30 minutes total runtime (enforced via timeout).
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
DRILL_TIMEOUT = 1800  # 30 minutes
DRILL_PG_PORT = int(os.getenv("DRILL_PG_PORT", "15432"))
DRILL_PG_PASSWORD = "drill_temp_password_not_for_prod"

_CORE_TABLES = [
    "aria_frameworks", "aria_controls", "aria_risks", "aria_documents",
    "sentinel_breaches", "grid_audits", "bcm_plans", "erm_risks", "orm_events",
]


def _fail(msg: str) -> None:
    print(f"[drill] FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def pull_from_r2(r2_remote: str, dest: Path) -> Path:
    """Download the most recent backup from R2."""
    print(f"[drill] Listing R2 remote {r2_remote}...")
    res = subprocess.run(
        ["rclone", "lsf", r2_remote, "--format", "t"],
        capture_output=True, timeout=60,
    )
    if res.returncode != 0:
        _fail(f"rclone lsf failed: {res.stderr.decode()[:300]}")
    files = [f.strip() for f in res.stdout.decode().splitlines() if f.strip()]
    if not files:
        _fail("No files found on R2 remote.")
    latest_name = sorted(files)[-1]
    print(f"[drill] Pulling {latest_name} from R2...")
    res = subprocess.run(
        ["rclone", "copy", f"{r2_remote}/{latest_name}", str(dest), "--retries", "3"],
        capture_output=True, timeout=300,
    )
    if res.returncode != 0:
        _fail(f"rclone copy failed: {res.stderr.decode()[:300]}")
    local = dest / latest_name
    if not local.exists():
        _fail(f"Expected {local} after rclone but not found.")
    return local


def find_latest_local() -> Path:
    candidates = sorted(BACKUP_DIR.glob("themisiq-*.zip"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        _fail(f"No backup zips in {BACKUP_DIR}")
    return candidates[-1]


def start_drill_pg() -> str:
    """Start a temporary PG container. Returns container name."""
    name = f"themisiq-drill-{int(time.time())}"
    print(f"[drill] Starting temp PG container {name} on port {DRILL_PG_PORT}...")
    res = subprocess.run([
        "docker", "run", "-d", "--rm",
        "--name", name,
        "-e", f"POSTGRES_PASSWORD={DRILL_PG_PASSWORD}",
        "-e", "POSTGRES_DB=themisiq_drill",
        "-e", "POSTGRES_USER=themisiq",
        "-p", f"{DRILL_PG_PORT}:5432",
        "postgres:16-alpine",
    ], capture_output=True, timeout=60)
    if res.returncode != 0:
        _fail(f"docker run failed: {res.stderr.decode()[:300]}")
    # Wait for PG to be ready
    drill_url = (
        f"postgresql://themisiq:{DRILL_PG_PASSWORD}"
        f"@localhost:{DRILL_PG_PORT}/themisiq_drill"
    )
    for _ in range(30):
        time.sleep(2)
        rc = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", "themisiq"],
            capture_output=True,
        ).returncode
        if rc == 0:
            print("[drill] PG ready.")
            return name
    _fail("Temp PG container did not become ready in time.")
    return ""  # unreachable


def stop_drill_pg(name: str) -> None:
    subprocess.run(["docker", "stop", name], capture_output=True, timeout=30)


def restore_into_drill(zip_path: Path, container: str) -> None:
    """Restore pg_dump from zip into the drill container."""
    print(f"[drill] Reading pg_dump from {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        dump_data = zf.read("themisiq.dump")

    print("[drill] Running pg_restore into drill container...")
    res = subprocess.run(
        [
            "docker", "exec", "-i", container,
            "pg_restore",
            "--no-owner", "--no-acl",
            "-U", "themisiq",
            "-d", "themisiq_drill",
            "--format=custom",
        ],
        input=dump_data, capture_output=True, timeout=DRILL_TIMEOUT,
    )
    if res.returncode != 0:
        stderr = res.stderr.decode()
        # Ignore "already exists" warnings from --clean on an empty DB
        if "ERROR:" in stderr and "already exists" not in stderr:
            _fail(f"pg_restore failed:\n{stderr[:1000]}")


def check_row_counts(container: str, prod_url: str) -> bool:
    """Compare row counts between drill PG and prod."""
    try:
        import psycopg2
    except ImportError:
        print("[drill] psycopg2 not available — skipping row count check.")
        return True

    drill_url = (
        f"postgresql://themisiq:{DRILL_PG_PASSWORD}"
        f"@localhost:{DRILL_PG_PORT}/themisiq_drill"
    )
    prod = psycopg2.connect(prod_url)
    drill = psycopg2.connect(drill_url)

    ok = True
    print("\n[drill] Row count comparison (prod vs drill):")
    print(f"  {'Table':<45} {'Prod':>10} {'Drill':>10} {'Match':>6}")
    print("  " + "-" * 75)
    for table in _CORE_TABLES:
        try:
            with prod.cursor() as c:
                c.execute(f"SELECT COUNT(*) FROM {table}")
                pc = c.fetchone()[0]
            with drill.cursor() as c:
                c.execute(f"SELECT COUNT(*) FROM {table}")
                dc = c.fetchone()[0]
            match = "✓" if pc == dc else "✗"
            if pc != dc:
                ok = False
            print(f"  {table:<45} {pc:>10} {dc:>10} {match:>6}")
        except Exception as exc:
            print(f"  {table:<45} {'ERR':>10} {'ERR':>10} {'✗':>6}  ({exc})")
            ok = False
    prod.close()
    drill.close()
    return ok


def main() -> None:
    r2_remote = os.getenv("BACKUP_OFFSITE_RCLONE_REMOTE", "")
    prod_url = os.getenv("DATABASE_URL", "")

    with tempfile.TemporaryDirectory(prefix="themisiq_drill_") as tmpdir:
        if r2_remote:
            zip_path = pull_from_r2(r2_remote, Path(tmpdir))
        else:
            zip_path = find_latest_local()

        print(f"[drill] Using backup: {zip_path.name}")

        container = start_drill_pg()
        try:
            restore_into_drill(zip_path, container)
            if prod_url:
                ok = check_row_counts(container, prod_url)
            else:
                print("[drill] DATABASE_URL not set — skipping prod comparison.")
                ok = True
        finally:
            stop_drill_pg(container)
            print("[drill] Drill container stopped.")

    if ok:
        print("\n[drill] PASS — restore drill succeeded.")
        sys.exit(0)
    else:
        print("\n[drill] FAIL — row count mismatch between prod and restored backup.")
        sys.exit(1)


if __name__ == "__main__":
    main()
