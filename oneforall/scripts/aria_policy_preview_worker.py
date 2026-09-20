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
import sys
import time
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

SPOOL_DIR = Path(os.environ.get("ARIA_POLICY_PREVIEW_SPOOL_DIR", "/spool"))
EXECUTABLE = os.environ.get("ARIA_POLICY_PREVIEW_EXECUTABLE", "soffice")
CONVERT_TIMEOUT_SECONDS = int(os.environ.get("ARIA_POLICY_PREVIEW_TIMEOUT_SECONDS", "60"))
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 200
LOCK_PATH = Path(os.environ.get(
    "ARIA_POLICY_PREVIEW_LOCK_PATH", "/tmp/aria-policy-preview-worker.lock"
))
HEARTBEAT_PATH = SPOOL_DIR / ".worker.heartbeat"
RUNTIME_MANIFEST_PATH = Path(os.environ.get(
    "ARIA_POLICY_PREVIEW_RUNTIME_MANIFEST", str(Path(__file__).with_name("runtime-manifest.json"))
))
HEARTBEAT_MAX_AGE_SECONDS = int(os.environ.get(
    "ARIA_POLICY_PREVIEW_HEARTBEAT_MAX_AGE_SECONDS", "90"
))


class WorkerAlreadyRunningError(Exception):
    pass


class PdfValidationError(Exception):
    """The converter output is not a safe, bounded preview artifact."""


def _write_heartbeat() -> None:
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HEARTBEAT_PATH.with_name(f"{HEARTBEAT_PATH.name}.tmp{os.getpid()}")
    tmp.write_text(str(time.time()), encoding="ascii")
    os.replace(str(tmp), str(HEARTBEAT_PATH))


def _validate_runtime_manifest() -> dict:
    try:
        manifest = json.loads(RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Runtime manifest is missing or invalid.") from exc

    required = (
        "base_image_digest", "libreoffice_version", "font_package_versions",
        "package_versions", "worker_build_id", "pypdf_version", "built_at",
    )
    missing = [key for key in required if not manifest.get(key)]
    serialized = json.dumps(manifest, sort_keys=True).upper()
    if missing or "PIN_ME" in serialized or "FILL_AT_BUILD_TIME" in serialized:
        raise RuntimeError(
            "Runtime manifest is incomplete" + (f" (missing: {', '.join(missing)})" if missing else ".")
        )
    base_image = str(manifest["base_image_digest"])
    if "@sha256:" not in base_image:
        raise RuntimeError("Runtime manifest base image is not digest-pinned.")
    return manifest


def healthcheck() -> None:
    """Cheap liveness/readiness check; never launches LibreOffice."""
    _validate_runtime_manifest()
    if not SPOOL_DIR.is_dir() or not os.access(SPOOL_DIR, os.R_OK | os.W_OK):
        raise RuntimeError("Preview spool is not readable and writable.")
    try:
        heartbeat_age = time.time() - float(HEARTBEAT_PATH.read_text(encoding="ascii"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Worker heartbeat is missing or invalid.") from exc
    if heartbeat_age < 0 or heartbeat_age > HEARTBEAT_MAX_AGE_SECONDS:
        raise RuntimeError(f"Worker heartbeat is stale ({heartbeat_age:.0f}s old).")


def _pdf_object(value):
    """Resolve a pypdf indirect object without accepting resolution errors."""
    return value.get_object() if hasattr(value, "get_object") else value


def _is_static_page_destination(value) -> bool:
    """Return whether *value* is an inert, in-document page destination.

    LibreOffice emits a catalog /OpenAction array that selects the first page
    and zoom level. That array contains no executable action and is safe to
    retain. Named, remote, malformed, and dictionary actions are rejected by
    default rather than being interpreted here.
    """
    destination = _pdf_object(value)
    if not isinstance(destination, list) or len(destination) < 2:
        return False
    target_page = _pdf_object(destination[0])
    if not isinstance(target_page, dict) or str(target_page.get("/Type", "")) != "/Page":
        return False
    return str(destination[1]) in {
        "/XYZ", "/Fit", "/FitH", "/FitV", "/FitR", "/FitB", "/FitBH", "/FitBV"
    }


def _reject_active_pdf_content(reader: PdfReader) -> None:
    """Reject actions, scripts, forms and embedded/interactive content.

    A policy preview only needs static visible pages. LibreOffice should not
    emit these features for the controlled source documents, and accepting
    them would turn a read-only preview into an active-content container.
    """
    root = _pdf_object(reader.trailer.get("/Root"))
    if not isinstance(root, dict):
        raise PdfValidationError("PDF has no valid document catalog.")

    if any(key in root for key in ("/AA", "/AcroForm")):
        raise PdfValidationError("PDF contains active content.")
    if "/OpenAction" in root and not _is_static_page_destination(root["/OpenAction"]):
        raise PdfValidationError("PDF contains active content.")

    names = _pdf_object(root.get("/Names")) if root.get("/Names") is not None else None
    if isinstance(names, dict) and any(
        key in names for key in ("/JavaScript", "/EmbeddedFiles")
    ):
        raise PdfValidationError("PDF contains active content.")

    forbidden_annotation_types = {
        "/FileAttachment", "/Movie", "/RichMedia", "/Screen", "/Sound", "/3D"
    }
    for page in reader.pages:
        page_obj = _pdf_object(page)
        if "/AA" in page_obj:
            raise PdfValidationError("PDF contains active content.")
        annotations = _pdf_object(page_obj.get("/Annots")) if page_obj.get("/Annots") else []
        for annotation_ref in annotations or []:
            annotation = _pdf_object(annotation_ref)
            if not isinstance(annotation, dict):
                raise PdfValidationError("PDF contains an invalid annotation.")
            if "/AA" in annotation:
                raise PdfValidationError("PDF contains active content.")
            if "/A" in annotation:
                action = _pdf_object(annotation["/A"])
                if (
                    not isinstance(action, dict)
                    or str(action.get("/S", "")) != "/GoTo"
                    or not _is_static_page_destination(action.get("/D"))
                ):
                    raise PdfValidationError("PDF contains active content.")
            if str(annotation.get("/Subtype", "")) in forbidden_annotation_types:
                raise PdfValidationError("PDF contains active content.")


def _validate_pdf(path: Path) -> None:
    """Strictly parse and bound a converter-produced PDF before publishing it."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PdfValidationError("Converted PDF is missing or unreadable.") from exc
    if size <= 0:
        raise PdfValidationError("Converted PDF is empty.")
    if size > MAX_PDF_BYTES:
        raise PdfValidationError(
            f"Converted PDF exceeds the {MAX_PDF_BYTES}-byte maximum size."
        )
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise PdfValidationError("Converted output has no valid PDF signature.")
        reader = PdfReader(str(path), strict=True)
        if reader.is_encrypted:
            raise PdfValidationError("Encrypted PDF previews are not allowed.")
        page_count = len(reader.pages)
        if page_count < 1:
            raise PdfValidationError("Converted PDF has no pages.")
        if page_count > MAX_PDF_PAGES:
            raise PdfValidationError(
                f"Converted PDF has {page_count} pages; maximum is {MAX_PDF_PAGES}."
            )
        _reject_active_pdf_content(reader)
    except PdfValidationError:
        raise
    except (PdfReadError, OSError, ValueError, TypeError, KeyError) as exc:
        raise PdfValidationError("Converted output is not a valid strict PDF.") from exc


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
        _validate_pdf(produced)
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
    parser.add_argument("--healthcheck", action="store_true", help="Validate manifest, spool and heartbeat.")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    args = parser.parse_args()

    if args.healthcheck:
        try:
            healthcheck()
        except Exception as exc:
            print(f"Unhealthy: {exc}", file=sys.stderr)
            raise SystemExit(1)
        print("Healthy")
        return

    _acquire_singleton_lock()
    try:
        _write_heartbeat()
        if args.once:
            n = run_once()
            _write_heartbeat()
            print(f"Processed {n} job(s).")
            return
        while True:
            _write_heartbeat()
            run_once()
            _write_heartbeat()
            time.sleep(args.poll_interval)
    finally:
        _release_singleton_lock()


if __name__ == "__main__":
    main()
