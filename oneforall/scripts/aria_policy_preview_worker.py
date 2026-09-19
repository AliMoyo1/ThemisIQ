#!/usr/bin/env python3
"""
PLAN-35 T05: ARIA policy preview conversion worker.

Runs as a separate process from the web app (in production, inside a
dedicated container per section 7.6). Watches the shared spool directory
for conversion jobs written by policy_preview.py, invokes LibreOffice
headless to convert a branded DOCX to PDF, and writes the result back to
the spool. Deliberately does NOT import the application's config, database,
or any application module: this process must not have access to
application secrets, the .env file, or the upload root beyond the shared
spool -- it is a separate trust boundary, not a library the app calls into.

Configuration is read from this process's own environment only:
  ARIA_POLICY_PREVIEW_SPOOL_DIR   shared spool root (default /spool)
  ARIA_POLICY_PREVIEW_EXECUTABLE  LibreOffice binary (default "soffice")
  ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS  per-conversion timeout (default 60)

Usage: python aria_policy_preview_worker.py [--once] [--poll-interval SECONDS]
--once processes every currently queued job and exits (used by tests and
by a one-shot readiness check); without it, the worker polls forever.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

SPOOL_DIR = Path(os.environ.get("ARIA_POLICY_PREVIEW_SPOOL_DIR", "/spool"))
EXECUTABLE = os.environ.get("ARIA_POLICY_PREVIEW_EXECUTABLE", "soffice")
CONVERT_TIMEOUT_SECONDS = int(os.environ.get("ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS", "60"))
LOCK_PATH = SPOOL_DIR / ".worker.lock"


class WorkerAlreadyRunningError(Exception):
    pass


def _acquire_singleton_lock() -> None:
    """Exclusive-create a lock file: atomic and portable (POSIX and
    Windows both honor O_CREAT|O_EXCL via Python's 'x' open mode). Guards
    against a second worker instance being started by mistake on the same
    host; it is not a distributed lock across hosts, which this
    single-worker deployment (section 7.6, "start with one worker") does
    not need."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        raise WorkerAlreadyRunningError(
            f"Lock file {LOCK_PATH} already exists; another worker instance may be running."
        )


def _release_singleton_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def _claim_job(job_dir: Path, claimed_root: Path) -> Path | None:
    """Atomically claim a queued job by renaming it out of inbox/. Returns
    None if another process claimed it first (the loser's rename raises)."""
    target = claimed_root / job_dir.name
    try:
        os.rename(str(job_dir), str(target))
        return target
    except OSError:
        return None


def convert(input_docx: Path, output_dir: Path, executable: str = EXECUTABLE,
            timeout_seconds: int = CONVERT_TIMEOUT_SECONDS) -> Path:
    """Invoke LibreOffice headless with a unique per-conversion profile
    directory so no state leaks between jobs. Isolated into its own
    function specifically so tests can monkeypatch this single call site
    rather than mocking subprocess globally."""
    profile_dir = output_dir / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_uri = profile_dir.resolve().as_uri()

    args = [
        executable,
        "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nofirststartwizard",
        f"-env:UserInstallation={profile_uri}",
        "--convert-to", "pdf:writer_pdf_Export",
        "--outdir", str(output_dir),
        str(input_docx),
    ]
    # Minimal environment: no application secrets, no inherited PATH
    # beyond what the converter itself needs to run.
    minimal_env = {"HOME": str(profile_dir), "PATH": os.environ.get("PATH", "")}
    subprocess.run(
        args, shell=False, timeout=timeout_seconds, check=True,
        capture_output=True, env=minimal_env,
    )
    produced = output_dir / (input_docx.stem + ".pdf")
    if not produced.exists():
        raise RuntimeError("Converter exited 0 but produced no output file.")
    return produced


def _write_result(job_dir: Path, ok: bool, error_code: str = "", error_message: str = "") -> None:
    result = {"ok": ok}
    if not ok:
        result.update(error_code=error_code, error_message=error_message)
    tmp = job_dir / f"result.json.tmp{os.getpid()}"
    tmp.write_text(json.dumps(result), encoding="utf-8")
    os.rename(str(tmp), str(job_dir / "result.json"))  # atomic terminal write


def process_one_job(job_dir: Path) -> None:
    """Convert a single already-claimed job directory. Never raises --
    every failure path ends in a written result.json so the app-side
    poller doesn't hang past its own deadline waiting on a job the worker
    has actually already given up on."""
    input_docx = job_dir / "input.docx"
    manifest_path = job_dir / "manifest.json"

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _write_result(job_dir, False, "PREVIEW_UNAVAILABLE", "Invalid or missing job manifest.")
        return

    if time.time() > manifest.get("deadline", float("inf")):
        _write_result(job_dir, False, "PREVIEW_TIMEOUT", "Job expired before being claimed.")
        return
    if not input_docx.exists():
        _write_result(job_dir, False, "PREVIEW_UNAVAILABLE", "No input document in job directory.")
        return

    try:
        produced = convert(input_docx, job_dir)
        shutil.move(str(produced), str(job_dir / "output.pdf"))
        _write_result(job_dir, True)
    except subprocess.TimeoutExpired:
        _write_result(job_dir, False, "PREVIEW_TIMEOUT", "Conversion exceeded the configured timeout.")
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"")[:500].decode("utf-8", "replace")
        _write_result(job_dir, False, "PREVIEW_UNAVAILABLE", f"Converter exited {exc.returncode}: {stderr}")
    except Exception as exc:
        _write_result(job_dir, False, "PREVIEW_UNAVAILABLE", str(exc))


def run_once() -> int:
    """Claim and process every job currently queued in inbox/, one at a
    time (sequential loop; the singleton lock in main() prevents a second
    worker instance from also converting concurrently). Returns the count
    processed."""
    inbox = SPOOL_DIR / "inbox"
    outbox = SPOOL_DIR / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    if not inbox.exists():
        return 0

    processed = 0
    for job_dir in sorted(p for p in inbox.iterdir() if p.is_dir()):
        claimed = _claim_job(job_dir, outbox)
        if claimed is None:
            continue
        process_one_job(claimed)
        processed += 1
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process queued jobs once and exit.")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    args = parser.parse_args()

    _acquire_singleton_lock()
    try:
        if args.once:
            n = run_once()
            print(f"Processed {n} job(s).")
            return
        while True:
            run_once()
            time.sleep(args.poll_interval)
    finally:
        _release_singleton_lock()


if __name__ == "__main__":
    main()
