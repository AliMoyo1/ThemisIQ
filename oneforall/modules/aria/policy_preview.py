"""
PLAN-35 T05: app-side spool client for the ARIA policy conversion worker.

Protocol (section 7.4): the app writes a job to inbox/<job_id>/, a separate
worker process (potentially a separate container -- section 7.6) claims,
converts with LibreOffice, and writes a result. This module owns only the
app's half of that exchange: it never invokes a converter itself, never
receives a caller-supplied path or executable argument, and never reads
the worker's own private work/profile directories, only its own spool
inbox/outbox.

Blocking I/O note: submit/poll use blocking file I/O and time.sleep, by
design matching the plan's "do not hold a DB transaction or block an async
event loop while converting" instruction -- route handlers must call these
via asyncio.to_thread(...), never directly from an async def body.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from config import settings


class ConversionTimeoutError(Exception):
    pass


class ConversionFailedError(Exception):
    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(message)


def _spool_dir() -> Path:
    return Path(settings.ARIA_POLICY_PREVIEW_SPOOL_DIR)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write-then-rename within the same directory: atomic on both NTFS
    and POSIX filesystems, so a reader never observes a partially written
    file."""
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_bytes(data)
    os.rename(str(tmp), str(path))


def submit_conversion_job(branded_docx_bytes: bytes, timeout_seconds: int | None = None) -> str:
    """Write a conversion job to the spool inbox. Returns the job id.
    Accepts only already-validated bytes -- no path, no filter, no
    converter argument crosses this boundary."""
    timeout_seconds = timeout_seconds or settings.ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS
    job_id = uuid.uuid4().hex
    job_dir = _spool_dir() / "inbox" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"job_id": job_id, "deadline": time.time() + timeout_seconds}
    _atomic_write_bytes(job_dir / "input.docx", branded_docx_bytes)
    _atomic_write_bytes(job_dir / "manifest.json", json.dumps(manifest).encode("utf-8"))
    return job_id


def poll_conversion_result(job_id: str, timeout_seconds: int | None = None, poll_interval: float = 0.5) -> bytes:
    """Block (see module docstring) until the worker's result appears in
    the outbox, or the deadline passes. Returns the PDF bytes on success.
    """
    timeout_seconds = timeout_seconds or settings.ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS
    deadline = time.time() + timeout_seconds
    result_path = _spool_dir() / "outbox" / job_id / "result.json"

    while time.time() < deadline:
        if result_path.exists():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                # result.json rename may still be mid-flight; retry rather
                # than fail on a transient partial read.
                time.sleep(poll_interval)
                continue
            if result.get("ok"):
                return (result_path.parent / "output.pdf").read_bytes()
            raise ConversionFailedError(
                result.get("error_code", "PREVIEW_UNAVAILABLE"),
                result.get("error_message", "Conversion failed."),
            )
        time.sleep(poll_interval)

    raise ConversionTimeoutError(f"No result for job {job_id} within {timeout_seconds}s.")


def cleanup_job(job_id: str) -> None:
    """Remove a job's own spool directories once the app has consumed (or
    given up on) its result. Only ever touches paths under its own job id,
    never enumerates or removes a sibling job's directory."""
    for base in ("inbox", "outbox"):
        job_dir = _spool_dir() / base / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
