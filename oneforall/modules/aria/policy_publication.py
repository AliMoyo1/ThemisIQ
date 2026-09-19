"""
PLAN-35 T09 (section 10.3): processes aria_policy_publication_jobs rows.

decide_approval (policy_workflow_service.py) inserts a 'pending' job row
in the same transaction that approves a policy version -- fast and
transactional. This module does the slower, retryable side-effect work
a scheduled worker picks up afterward:

    - Copy the approved version's branded file into the Evidence Vault,
      keyed by the immutable policy_version_id (never the mutable
      document id), so a later revision's evidence never overwrites an
      earlier approved version's.
    - When the document's framework/control_ref match GRID controls,
      attach the same version as GRID evidence, again keyed by version id,
      and only onto controls whose own business-unit scope is compatible
      with the policy's (grid_audits/grid_controls have no org_id column
      at all in this schema -- business_unit_id is the only scope
      dimension both sides actually share, so that is what is checked;
      see the T09 execution-ledger notes for why a literal "organization"
      comparison as section 10.3 describes is not possible here).
    - Emit ARIA_POLICY_PUBLISHED with publication_key + version_id, and
      persist the returned event id on the job.

Design for at-least-once execution: every side effect is written with an
idempotent insert-or-already-exists check keyed by policy_version_id (or
policy_version_id + control_id for GRID), so replaying a job after a crash
never creates a duplicate. Never reverses the approval itself on failure --
a copy failure only marks this job 'failed' after retries are exhausted;
the approved version and document status are untouched.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from core.timeutils import utcnow
from database import get_db_background, insert_returning_id
from modules.aria import policy_storage

log = logging.getLogger("aria.policy_publication")

DEFAULT_LEASE_SECONDS = 120
_BACKOFF_MINUTES = [1, 5, 30]
MAX_ATTEMPTS = len(_BACKOFF_MINUTES) + 2  # 1,5,30,30,30 then permanently failed


def _is_postgres() -> bool:
    from config import settings
    return settings.is_postgres()


def _is_unique_violation(exc: Exception) -> bool:
    text = str(exc).lower()
    return "unique" in text or "duplicate key" in text


# ─────────────────────────────────────────────────────────────────────────
# Claim (section 10.3: "Claim with a short DB lease and random token")
# ─────────────────────────────────────────────────────────────────────────

def claim_next_job(db, is_postgres: bool, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict | None:
    """Claims and returns one due job (state='pending', or a 'running' job
    whose lease has expired -- a crashed worker's job becomes claimable
    again automatically), or None if nothing is due right now.

    Uses the same locking convention as policy_access.reserve_document_number:
    BEGIN IMMEDIATE on SQLite (whole-database write lock, released at the
    commit below -- held only for this short claim, never across the
    actual copy work that follows), SELECT ... FOR UPDATE SKIP LOCKED on
    PostgreSQL (row-level, safe with multiple app workers).
    """
    import uuid as _uuid
    now = utcnow()
    now_iso = now.isoformat()
    token = _uuid.uuid4().hex
    lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()

    if is_postgres:
        row = db.execute(
            "SELECT id FROM aria_policy_publication_jobs "
            "WHERE (state='pending' OR (state='running' AND lease_until < %s)) "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= %s) "
            "ORDER BY created_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED",
            (now_iso, now_iso),
        ).fetchone()
    else:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT id FROM aria_policy_publication_jobs "
            "WHERE (state='pending' OR (state='running' AND lease_until < %s)) "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= %s) "
            "ORDER BY created_at ASC LIMIT 1",
            (now_iso, now_iso),
        ).fetchone()

    if not row:
        if not is_postgres:
            db.rollback()  # release the BEGIN IMMEDIATE lock; nothing to claim
        return None

    job_id = row[0]
    db.execute(
        "UPDATE aria_policy_publication_jobs SET state='running', lease_until=%s, "
        "lease_token=%s, attempts=attempts+1, updated_at=%s WHERE id=%s",
        (lease_until, token, now_iso, job_id),
    )
    db.commit()

    full = db.execute(
        "SELECT * FROM aria_policy_publication_jobs WHERE id=%s", (job_id,)
    ).fetchone()
    return dict(full) if full else None


# ─────────────────────────────────────────────────────────────────────────
# Side effects (section 10.3)
# ─────────────────────────────────────────────────────────────────────────

def _copy_to_evidence_vault(db, version: dict, doc: dict) -> int:
    """Idempotent: a unique index on evidence_items(aria_policy_version_id)
    (WHERE NOT NULL) means a replayed job that already succeeded here
    raises a unique violation, which is treated as 'already done', not
    an error."""
    existing = db.execute(
        "SELECT id FROM evidence_items WHERE aria_policy_version_id=%s",
        (version["id"],),
    ).fetchone()
    if existing:
        return existing[0]

    branded_rel = version.get("branded_path")
    file_name = ""
    file_size = 0
    mime_type = ""
    if branded_rel:
        abs_path = policy_storage.resolve_stored_path(branded_rel)
        file_name = f"{doc.get('doc_id') or 'policy'}_{version.get('version') or '1.0'}.docx"
        if abs_path.exists():
            file_size = abs_path.stat().st_size
        mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    title = doc.get("title") or f"Policy #{doc.get('id')}"
    tag = f"aria_doc_id={doc.get('id')}"
    try:
        vault_id = insert_returning_id(db,
            "INSERT INTO evidence_items "
            "(title, description, file_path, file_name, file_size, file_hash, "
            " mime_type, category, tags, status, business_unit_id, "
            " uploaded_by, aria_policy_version_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'current',%s,%s,%s)",
            (
                title,
                f"ARIA policy document (framework: {doc.get('framework', '')}, "
                f"control: {doc.get('control_ref', '')}, version: {version.get('version')}). "
                f"Approved {version.get('approved_at') or ''}.",
                # Version-keyed evidence stores a virtual pointer, like the
                # legacy handler's aria://documents/{id} scheme, so download
                # always re-authorizes through ARIA rather than serving a
                # raw path directly (section 10.3: "authorize both the GRID
                # record and the ARIA version before serving the file" --
                # the same principle applies to the vault copy).
                f"aria://policy-versions/{version['id']}",
                file_name, file_size,
                version.get("branded_sha256") or "",
                mime_type, "policy",
                f"aria,policy,approved,{doc.get('framework', '')},{doc.get('control_ref', '')},{tag}",
                doc.get("business_unit_id"),
                version.get("approved_by"),
                version["id"],
            ),
        )
    except Exception as exc:
        if not _is_unique_violation(exc):
            raise
        db.rollback()
        existing = db.execute(
            "SELECT id FROM evidence_items WHERE aria_policy_version_id=%s",
            (version["id"],),
        ).fetchone()
        if not existing:
            raise
        return existing[0]

    db.execute(
        "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) "
        "VALUES (%s,'aria','document',%s,%s)",
        (vault_id, doc["id"], version.get("approved_by")),
    )
    return vault_id


def _compatible_business_unit(policy_bu_id, audit_bu_id) -> bool:
    """grid_audits has no org_id column at all in this schema (confirmed
    directly), so a literal organization comparison as section 10.3
    describes is not possible. business_unit_id is the one scope
    dimension both ARIA policies and GRID audits actually carry.

    The compatible direction is "the audit's audience must not be broader
    than the policy's": an org-wide (NULL BU) policy is visible to anyone,
    so it may attach to any audit, org-wide or BU-specific. A BU-private
    policy may only attach to an audit scoped to that exact same BU --
    never to a NULL/org-wide audit, whose audience (every BU in the org)
    is broader than the policy's own. GRID's evidence listing does not
    itself re-check ARIA scope before showing attached evidence metadata
    (title, notes, document/version ids), so attaching a BU-private policy
    to an org-wide audit would leak that metadata to every BU in the org,
    not just the policy's own -- this function is the only thing standing
    between the two, and the previous version had this backwards (treated
    a NULL audit as compatible with everything, which is exactly the leak)."""
    if policy_bu_id is None:
        return True
    return audit_bu_id is not None and int(policy_bu_id) == int(audit_bu_id)


def _copy_to_grid_evidence(db, version: dict, doc: dict) -> list[int]:
    """Idempotent per (control_id, aria_policy_version_id) via the unique
    index added in T01. Returns the ids of grid_evidence_files rows that
    exist for this version after this call (whether just created or
    already present from a prior attempt)."""
    control_ref = (doc.get("control_ref") or "").strip()
    framework = (doc.get("framework") or "").strip()
    if not control_ref or not framework:
        return []

    refs = [r.strip() for r in control_ref.split(",") if r.strip()]
    fw_rows = db.execute(
        "SELECT id FROM grid_frameworks WHERE LOWER(name) LIKE %s",
        (f"%{framework.lower()[:20]}%",),
    ).fetchall()
    fw_ids = [r[0] for r in fw_rows] or [None]
    placeholders = ",".join(["%s"] * len(fw_ids))

    attached_ids: list[int] = []
    for ref in refs:
        controls = db.execute(
            f"SELECT c.id, a.business_unit_id AS audit_bu_id "
            f"FROM grid_controls c JOIN grid_audits a ON a.id = c.audit_id "
            f"WHERE a.status NOT IN ('Archived','Completed') "
            f"AND c.control_id = %s "
            f"AND (c.framework_id IS NULL OR c.framework_id IN ({placeholders}))",
            [ref] + fw_ids,
        ).fetchall()

        for ctrl in controls:
            ctrl = dict(ctrl)
            if not _compatible_business_unit(doc.get("business_unit_id"), ctrl.get("audit_bu_id")):
                continue  # never attach a subsidiary-private policy to an unrelated subsidiary's audit
            existing = db.execute(
                "SELECT id FROM grid_evidence_files WHERE control_id=%s AND aria_policy_version_id=%s",
                (ctrl["id"], version["id"]),
            ).fetchone()
            if existing:
                attached_ids.append(existing[0])
                continue
            try:
                new_id = insert_returning_id(db,
                    "INSERT INTO grid_evidence_files "
                    "(control_id, filename, original_name, file_path, file_size, "
                    " mime_type, uploaded_by, notes, status, aria_policy_version_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'Approved',%s)",
                    (
                        ctrl["id"],
                        f"aria-policy-v{version['id']}.ref",
                        doc.get("title") or f"Policy #{doc['id']}",
                        f"aria://policy-versions/{version['id']}",
                        0, "application/x-aria-policy",
                        version.get("approved_by"),
                        f"ARIA policy document (aria_document_id={doc['id']}, "
                        f"policy_version_id={version['id']}, framework={framework}, "
                        f"ref={ref}, version={version.get('version')})",
                        version["id"],
                    ),
                )
            except Exception as exc:
                if not _is_unique_violation(exc):
                    raise
                db.rollback()
                again = db.execute(
                    "SELECT id FROM grid_evidence_files WHERE control_id=%s AND aria_policy_version_id=%s",
                    (ctrl["id"], version["id"]),
                ).fetchone()
                if not again:
                    raise
                new_id = again[0]
            attached_ids.append(new_id)
    return attached_ids


# ─────────────────────────────────────────────────────────────────────────
# Process one claimed job
# ─────────────────────────────────────────────────────────────────────────

def process_job(db, job: dict, is_postgres: bool) -> str:
    """Returns 'complete', 'failed', or 'retry_scheduled'. Never raises for
    an ordinary processing failure -- that path is recorded on the job row
    instead, per section 10.3: 'never reverse an approval because a
    downstream copy failed.'"""
    version = db.execute(
        "SELECT * FROM aria_policy_versions WHERE id=%s", (job["policy_version_id"],)
    ).fetchone()
    doc = db.execute(
        "SELECT * FROM aria_documents WHERE id=%s", (job["document_id"],)
    ).fetchone()

    if not version or not doc:
        # The version/document was removed out from under an already
        # inserted job (should not happen given ON DELETE RESTRICT on both
        # FKs, but fail safely rather than crash the worker loop).
        _mark_failed(db, job, "Referenced version or document no longer exists.")
        return "failed"

    version, doc = dict(version), dict(doc)
    try:
        _copy_to_evidence_vault(db, version, doc)
        _copy_to_grid_evidence(db, version, doc)
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("Publication job %s failed (attempt %d): %s", job["id"], job["attempts"], exc)
        return _schedule_retry_or_fail(db, job, str(exc))

    # Section 10.2/T09: current-version-aware search indexing. Best-effort
    # -- a search-index refresh failure must not turn a successful
    # publication into a retry (the vault/GRID copies above, which matter
    # for compliance evidence, already committed).
    try:
        from modules.aria import ask_service
        ask_service.reindex_document(doc.get("doc_id"))
    except Exception as exc:
        log.warning("Publication job %s: search reindex failed (non-fatal): %s", job["id"], exc)

    from core.events import emit, ARIA_POLICY_PUBLISHED
    event_id = emit(
        ARIA_POLICY_PUBLISHED,
        source_module="aria", entity_type="document", entity_id=doc["id"],
        payload={
            "doc_id": doc.get("doc_id"), "title": doc.get("title", ""),
            "framework": doc.get("framework", ""), "control_ref": doc.get("control_ref", ""),
            "version": version.get("version"),
            "version_id": version["id"],
            "publication_key": job["publication_key"],
        },
        user_id=version.get("approved_by"),
        org_id=job.get("org_id"),
        # Keyed by this job's own unique publication_key so a crash/lease
        # reclaim between here and the "mark complete" write below can
        # never re-run handlers or re-dispatch webhooks on replay -- the
        # vault/GRID copies above are separately idempotent, but emit()'s
        # side effects (tasks, notifications, workflows, webhooks) are not.
        dedup_key=job["publication_key"],
    )

    now_iso = utcnow().isoformat()
    updated = db.execute(
        "UPDATE aria_policy_publication_jobs SET state='complete', event_id=%s, "
        "last_error=NULL, updated_at=%s WHERE id=%s AND lease_token=%s",
        (event_id, now_iso, job["id"], job["lease_token"]),
    )
    if getattr(updated, "rowcount", 1) == 0:
        # Lease was reclaimed by another worker mid-flight (very unlikely
        # given the work above is a few fast local operations, not a slow
        # conversion) -- the side effects are idempotent, so the other
        # worker's own completion write is authoritative; nothing to do.
        log.warning("Publication job %s completed but lease had already been reclaimed.", job["id"])
    db.commit()
    return "complete"


def _schedule_retry_or_fail(db, job: dict, error: str) -> str:
    now = utcnow()
    attempts = job["attempts"]
    if attempts >= MAX_ATTEMPTS:
        _mark_failed(db, job, error)
        return "failed"
    backoff_idx = min(attempts - 1, len(_BACKOFF_MINUTES) - 1)
    next_attempt = (now + timedelta(minutes=_BACKOFF_MINUTES[backoff_idx])).isoformat()
    db.execute(
        "UPDATE aria_policy_publication_jobs SET state='pending', next_attempt_at=%s, "
        "last_error=%s, lease_until=NULL, lease_token=NULL, updated_at=%s "
        "WHERE id=%s AND lease_token=%s",
        (next_attempt, error[:2000], now.isoformat(), job["id"], job["lease_token"]),
    )
    db.commit()
    return "retry_scheduled"


def _mark_failed(db, job: dict, error: str) -> None:
    db.execute(
        "UPDATE aria_policy_publication_jobs SET state='failed', last_error=%s, "
        "lease_until=NULL, lease_token=NULL, updated_at=%s WHERE id=%s",
        (error[:2000], utcnow().isoformat(), job["id"]),
    )
    db.commit()
    doc = db.execute(
        "SELECT doc_id, title, org_id, business_unit_id, policy_workflow_managed "
        "FROM aria_documents WHERE id=%s", (job["document_id"],)
    ).fetchone()
    if doc:
        _notify_scoped_managers_of_failure(db, job, dict(doc))


def _notify_scoped_managers_of_failure(db, job: dict, doc: dict) -> None:
    """Section 10.3: 'Show \"Approved; evidence synchronization needs
    attention\" to scoped managers with a retry action.' A manager for a
    DIFFERENT business unit in the same organization must not learn a
    BU-private policy's title/link just because they also hold
    compliance_manager -- every candidate is re-checked through
    document_read_ok, the same scope rule used everywhere else in this
    workflow, not just filtered by org_id."""
    from modules.aria.policy_access import document_read_ok
    try:
        candidates = db.execute(
            "SELECT DISTINCT u.id, u.org_id, u.business_unit_id, "
            "COALESCE(u.is_super_admin,0) AS is_super_admin "
            "FROM users u JOIN user_roles ur ON ur.user_id = u.id "
            "WHERE u.is_active=1 AND u.org_id=%s "
            "AND ur.role_key IN ('super_admin','compliance_manager')",
            (job.get("org_id"),),
        ).fetchall()
        managers = [m for m in candidates if document_read_ok(dict(m), doc)]
        for m in managers:
            db.execute(
                "INSERT INTO notifications (user_id, module, title, message, link) "
                "VALUES (%s,'aria',%s,%s,%s)",
                (m[0], "Evidence synchronization needs attention",
                 f"'{doc.get('title')}' ({doc.get('doc_id')}) was approved, but publishing it to "
                 f"the Evidence Vault / GRID failed after retries. Approval is not affected; "
                 f"use the retry action once the underlying issue is resolved.",
                 f"/aria/documents?open={doc.get('doc_id')}"),
            )
        db.commit()
    except Exception as exc:
        log.warning("Failed to notify managers of publication failure: %s", exc)


# ─────────────────────────────────────────────────────────────────────────
# Entry points
# ─────────────────────────────────────────────────────────────────────────

def run_due_jobs(limit: int = 10) -> dict:
    """Scheduler entry point: claim and process up to `limit` due jobs.
    Each job gets its own connection/transaction boundary for the claim
    step (see claim_next_job), then reuses that same connection for its
    own work and completion -- never holding the claim's lock across the
    actual copy work."""
    is_pg = _is_postgres()
    counts = {"complete": 0, "retry_scheduled": 0, "failed": 0}
    for _ in range(limit):
        db = get_db_background()
        try:
            job = claim_next_job(db, is_pg)
            if not job:
                break
            outcome = process_job(db, job, is_pg)
            counts[outcome] = counts.get(outcome, 0) + 1
        finally:
            db.close()
    return counts


def retry_now(db, actor: dict, job_id: int) -> dict:
    """Explicit retry action for a scoped manager (section 10.3). Requires
    read access to the underlying document -- the same rule as everywhere
    else in this workflow, not a separate ad hoc check."""
    from modules.aria.policy_access import document_read_ok
    from modules.aria.policy_workflow_service import NotFoundError, ForbiddenError

    job = db.execute("SELECT * FROM aria_policy_publication_jobs WHERE id=%s", (job_id,)).fetchone()
    if not job:
        raise NotFoundError("Publication job not found.")
    job = dict(job)
    doc = db.execute("SELECT * FROM aria_documents WHERE id=%s", (job["document_id"],)).fetchone()
    if not doc or not document_read_ok(actor, dict(doc)):
        raise NotFoundError("Publication job not found.")
    from core.rbac import has_capability
    if not (has_capability(actor, "aria.policy.approve") or has_capability(actor, "aria.policy.edit_any")):
        raise ForbiddenError("You do not have permission to retry publication.")
    if job["state"] != "failed":
        raise NotFoundError("Only a failed publication job can be retried.")

    now = utcnow().isoformat()
    db.execute(
        "UPDATE aria_policy_publication_jobs SET state='pending', next_attempt_at=NULL, "
        "lease_until=NULL, lease_token=NULL, updated_at=%s WHERE id=%s AND state='failed'",
        (now, job_id),
    )
    db.commit()
    return dict(db.execute("SELECT * FROM aria_policy_publication_jobs WHERE id=%s", (job_id,)).fetchone())
