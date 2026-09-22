"""Persistent background jobs for ERM emerging-risk horizon scans.

The public ERM endpoint only enqueues work and returns a job id.  APScheduler
claims and executes jobs outside the ASGI event loop, so a slow AI provider
cannot block the single Uvicorn worker or outlive Cloudflare's request timeout.

Every caller must already be inside the correct ``tenant_context``.  The job
row also carries ``org_id`` and every read/write repeats that predicate as a
defence-in-depth boundary (and for SQLite tests, where schemas are shared).
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from config import settings
from core.timeutils import utcnow
from database import IntegrityError, get_db, get_db_background, insert_returning_id


log = logging.getLogger("erm.scan_jobs")

LEASE_SECONDS = 15 * 60
MAX_ATTEMPTS = 2
_PUBLIC_FAILURE = "The emerging-risk scan could not be completed. Please retry later."
_PUBLIC_ERROR_CODES = {
    "ai_unavailable",
    "context_unavailable",
    "invalid_result",
    "scan_failed",
    "worker_abandoned",
}


def _dict(row) -> dict | None:
    return dict(row) if row is not None else None


def _time_text(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def public_job(job: dict, *, reused: bool | None = None) -> dict:
    """Return the stable, non-sensitive polling contract exposed to the UI."""
    state = str(job.get("state") or "failed")
    result = {
        "job_id": int(job["id"]),
        "state": state,
        "created_at": _time_text(job.get("created_at")),
        "started_at": _time_text(job.get("started_at")),
        "completed_at": _time_text(job.get("completed_at")),
    }
    if reused is not None:
        result["reused"] = bool(reused)
    if state == "completed":
        result["created"] = int(job.get("result_created") or 0)
        result["grounded"] = bool(job.get("result_grounded"))
    elif state == "failed":
        error_code = str(job.get("error_code") or "scan_failed")
        result["error_code"] = (
            error_code if error_code in _PUBLIC_ERROR_CODES else "scan_failed"
        )
        # Never echo a stored provider or exception message to the browser.
        result["error"] = _PUBLIC_FAILURE
    return result


def enqueue_scan(org_id: int, requested_by: int | None) -> tuple[dict, bool]:
    """Create a pending job or return the org's existing active job.

    The ``(org_id, active_slot)`` unique index closes the check/insert race
    across multiple Uvicorn processes.  Terminal jobs set active_slot NULL,
    allowing history to remain while a later scan is queued.
    """
    org_id = int(org_id)
    if org_id <= 0:
        raise ValueError("A valid organization is required for an ERM scan")

    db = get_db()
    try:
        existing = db.execute(
            "SELECT * FROM erm_emerging_scan_jobs "
            "WHERE org_id=%s AND active_slot=1 "
            "ORDER BY id DESC LIMIT 1",
            (org_id,),
        ).fetchone()
        if existing:
            return dict(existing), False

        now_iso = utcnow().isoformat()
        try:
            job_id = insert_returning_id(
                db,
                "INSERT INTO erm_emerging_scan_jobs "
                "(org_id, requested_by, state, active_slot, created_at, updated_at) "
                "VALUES (%s,%s,'pending',1,%s,%s)",
                (org_id, requested_by, now_iso, now_iso),
            )
            db.commit()
        except IntegrityError:
            # Another process won the unique active-slot race.  PostgreSQL's
            # wrapper has already rolled back the failed transaction.
            existing = db.execute(
                "SELECT * FROM erm_emerging_scan_jobs "
                "WHERE org_id=%s AND active_slot=1 "
                "ORDER BY id DESC LIMIT 1",
                (org_id,),
            ).fetchone()
            if not existing:
                raise
            return dict(existing), False

        row = db.execute(
            "SELECT * FROM erm_emerging_scan_jobs WHERE id=%s AND org_id=%s",
            (job_id, org_id),
        ).fetchone()
        if not row:
            raise RuntimeError("Queued ERM scan job could not be read back")
        return dict(row), True
    finally:
        db.close()


def get_job(job_id: int, org_id: int) -> dict | None:
    """Fetch one job inside the current tenant, scoped again by org id."""
    db = get_db()
    try:
        return _dict(db.execute(
            "SELECT * FROM erm_emerging_scan_jobs WHERE id=%s AND org_id=%s",
            (int(job_id), int(org_id)),
        ).fetchone())
    finally:
        db.close()


def claim_next_job(org_id: int) -> dict | None:
    """Atomically claim one pending or abandoned job in the current tenant."""
    org_id = int(org_id)
    now = utcnow()
    now_iso = now.isoformat()
    lease_until = (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
    token = uuid.uuid4().hex

    db = get_db_background()
    try:
        if not settings.is_postgres():
            db.execute("BEGIN IMMEDIATE")

        # A worker that crashes twice must not retain the org's active slot
        # forever.  Only expired leases are terminalised here.
        db.execute(
            "UPDATE erm_emerging_scan_jobs SET state='failed', active_slot=NULL, "
            "lease_token=NULL, lease_until=NULL, error_code='worker_abandoned', "
            "error_message=%s, completed_at=%s, updated_at=%s "
            "WHERE org_id=%s AND state='running' AND active_slot=1 "
            "AND lease_until IS NOT NULL AND lease_until < %s AND attempts >= %s",
            (_PUBLIC_FAILURE, now_iso, now_iso, org_id, now_iso, MAX_ATTEMPTS),
        )

        select_sql = (
            "SELECT * FROM erm_emerging_scan_jobs "
            "WHERE org_id=%s AND active_slot=1 AND attempts < %s "
            "AND (state='pending' OR (state='running' AND lease_until < %s)) "
            "ORDER BY created_at ASC, id ASC LIMIT 1"
        )
        if settings.is_postgres():
            select_sql += " FOR UPDATE SKIP LOCKED"
        row = db.execute(select_sql, (org_id, MAX_ATTEMPTS, now_iso)).fetchone()
        if not row:
            db.commit()
            return None

        job_id = row["id"]
        db.execute(
            "UPDATE erm_emerging_scan_jobs SET state='running', lease_token=%s, "
            "lease_until=%s, attempts=attempts+1, "
            "started_at=COALESCE(started_at,%s), updated_at=%s "
            "WHERE id=%s AND org_id=%s AND active_slot=1",
            (token, lease_until, now_iso, now_iso, job_id, org_id),
        )
        db.commit()
        claimed = db.execute(
            "SELECT * FROM erm_emerging_scan_jobs WHERE id=%s AND org_id=%s",
            (job_id, org_id),
        ).fetchone()
        return _dict(claimed)
    finally:
        db.close()


def _complete(job: dict, result: dict) -> bool:
    now_iso = utcnow().isoformat()
    db = get_db_background()
    try:
        cur = db.execute(
            "UPDATE erm_emerging_scan_jobs SET state='completed', active_slot=NULL, "
            "lease_token=NULL, lease_until=NULL, result_created=%s, "
            "result_grounded=%s, error_code=NULL, error_message=NULL, "
            "completed_at=%s, updated_at=%s "
            "WHERE id=%s AND org_id=%s AND state='running' AND lease_token=%s",
            (
                max(0, int(result.get("created") or 0)),
                1 if result.get("grounded") else 0,
                now_iso,
                now_iso,
                job["id"],
                job["org_id"],
                job["lease_token"],
            ),
        )
        db.commit()
        return getattr(cur, "rowcount", 1) == 1
    finally:
        db.close()


def _fail(job: dict, code: str = "scan_failed") -> bool:
    now_iso = utcnow().isoformat()
    code = str(code or "scan_failed")
    if code not in _PUBLIC_ERROR_CODES:
        code = "scan_failed"
    db = get_db_background()
    try:
        cur = db.execute(
            "UPDATE erm_emerging_scan_jobs SET state='failed', active_slot=NULL, "
            "lease_token=NULL, lease_until=NULL, error_code=%s, error_message=%s, "
            "completed_at=%s, updated_at=%s "
            "WHERE id=%s AND org_id=%s AND state='running' AND lease_token=%s",
            (
                code,
                _PUBLIC_FAILURE,
                now_iso,
                now_iso,
                job["id"],
                job["org_id"],
                job["lease_token"],
            ),
        )
        db.commit()
        return getattr(cur, "rowcount", 1) == 1
    finally:
        db.close()


def process_next_job(org_id: int) -> dict | None:
    """Claim and execute one job; caller must bind the tenant context."""
    job = claim_next_job(org_id)
    if not job:
        return None

    try:
        from modules.erm import ai_service

        result = ai_service.run_emerging_scan()
        if not isinstance(result, dict) or result.get("error"):
            code = result.get("error") if isinstance(result, dict) else "invalid_result"
            _fail(job, str(code or "scan_failed"))
            return {"job_id": job["id"], "state": "failed"}
        if not _complete(job, result):
            log.warning("ERM scan job %s completed after its lease was reclaimed", job["id"])
            return {"job_id": job["id"], "state": "lease_lost"}
        return {
            "job_id": job["id"],
            "state": "completed",
            "created": int(result.get("created") or 0),
            "grounded": bool(result.get("grounded")),
        }
    except Exception as exc:
        log.exception("ERM scan job %s failed (%s)", job["id"], type(exc).__name__)
        _fail(job, "scan_failed")
        return {"job_id": job["id"], "state": "failed"}
