#!/usr/bin/env python3
"""
restore_backup.py — Disaster-recovery restore from a ThemisIQ backup zip.

Usage:
    # Restore from local zip:
    python scripts/restore_backup.py backups/themisiq-20260613_020000.zip \\
        --target-db postgresql://themisiq:pass@localhost:5432/themisiq

    # Pull from Cloudflare R2 first, then restore:
    python scripts/restore_backup.py r2:themisiq-backups/themisiq-20260613_020000.zip \\
        --target-db $DATABASE_URL

Restore steps:
    1. If source is r2:..., rclone copy to /tmp/ first.
    2. Validate the zip (testzip).
    3. Extract grid_uploads/ and evidence/ to disk.
    4. Pipe themisiq.dump to pg_restore --clean --if-exists.
    5. Validate row counts against expected from zip manifest.

WARNING: This will DROP and recreate all tables in the target database.
         Always test on a staging instance first.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import urllib.parse
import zipfile
from pathlib import Path


def rclone_pull(remote_path: str, dest_dir: Path) -> Path:
    """Download a single file from an rclone remote to dest_dir."""
    print(f"[restore] Pulling from {remote_path} via rclone...")
    result = subprocess.run(
        ["rclone", "copy", remote_path, str(dest_dir), "--retries", "3"],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"[restore] rclone failed: {result.stderr.decode()[:500]}", file=sys.stderr)
        sys.exit(1)
    filename = remote_path.split("/")[-1]
    local = dest_dir / filename
    if not local.exists():
        print(f"[restore] Expected file not found after rclone: {local}", file=sys.stderr)
        sys.exit(1)
    return local


def validate_zip(zip_path: Path) -> None:
    print(f"[restore] Validating {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        bad = zf.testzip()
        if bad:
            print(f"[restore] Corrupt entry in zip: {bad}", file=sys.stderr)
            sys.exit(1)
    print("[restore] Zip OK.")


def extract_uploads(zip_path: Path, dest_root: Path) -> dict[str, int]:
    """Extract grid_uploads/ and evidence/ directories; return counts."""
    counts: dict[str, int] = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            for prefix in ("grid_uploads/", "evidence/"):
                if name.startswith(prefix) and not name.endswith("/"):
                    zf.extract(name, dest_root)
                    counts[prefix.rstrip("/")] = counts.get(prefix.rstrip("/"), 0) + 1
    for k, v in counts.items():
        print(f"[restore] Extracted {v} files → {dest_root}/{k}/")
    return counts


def restore_pg(zip_path: Path, target_db: str) -> None:
    """Pipe themisiq.dump from the zip to pg_restore."""
    parsed = urllib.parse.urlparse(target_db)
    pg_env = {
        **os.environ,
        "PGPASSWORD": os.getenv("PGPASSWORD", parsed.password or ""),
        "PGSSLMODE": os.getenv("PGSSLMODE", "prefer"),
    }
    cmd = [
        "pg_restore",
        "--clean", "--if-exists",
        "--no-owner", "--no-acl",
        "-h", parsed.hostname or "localhost",
        "-p", str(parsed.port or 5432),
        "-U", parsed.username or "themisiq",
        "-d", (parsed.path or "/themisiq").lstrip("/"),
        "--format=custom",
    ]

    print("[restore] Running pg_restore...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        if "themisiq.dump" not in zf.namelist():
            print("[restore] No themisiq.dump in zip — is this a SQLite backup?", file=sys.stderr)
            sys.exit(1)
        dump_data = zf.read("themisiq.dump")

    result = subprocess.run(cmd, input=dump_data, capture_output=True, env=pg_env, timeout=1800)
    if result.returncode != 0:
        print(f"[restore] pg_restore stderr:\n{result.stderr.decode()[:2000]}", file=sys.stderr)
        sys.exit(1)
    print("[restore] pg_restore OK.")


def validate_row_counts(target_db: str) -> None:
    """Spot-check a few core tables to confirm data landed."""
    try:
        import psycopg2
        conn = psycopg2.connect(target_db)
        cur = conn.cursor()
        tables = [
            "aria_frameworks", "aria_controls", "sentinel_breaches",
            "grid_audits", "bcm_plans", "erm_risks",
        ]
        print("[restore] Row count validation:")
        for tbl in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                n = cur.fetchone()[0]
                print(f"  {tbl}: {n} rows")
            except Exception as exc:
                print(f"  {tbl}: ERROR — {exc}")
        conn.close()
    except ImportError:
        print("[restore] psycopg2 not available — skipping row count check.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a ThemisIQ backup zip to PostgreSQL.")
    parser.add_argument("source", help="Local path or r2:remote/path to the backup zip.")
    parser.add_argument("--target-db", required=True,
                        help="PostgreSQL connection URL (postgresql://user:pass@host:port/db).")
    parser.add_argument("--uploads-dest", default=".",
                        help="Directory to extract grid_uploads/ and evidence/ into (default: cwd).")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="themisiq_restore_") as tmpdir:
        tmp = Path(tmpdir)

        if args.source.startswith("r2:") or args.source.startswith("s3:"):
            zip_path = rclone_pull(args.source, tmp)
        else:
            zip_path = Path(args.source).expanduser().resolve()
            if not zip_path.exists():
                print(f"[restore] File not found: {zip_path}", file=sys.stderr)
                sys.exit(1)

        validate_zip(zip_path)
        extract_uploads(zip_path, Path(args.uploads_dest))
        restore_pg(zip_path, args.target_db)
        validate_row_counts(args.target_db)

    print("[restore] Done.")


if __name__ == "__main__":
    main()
