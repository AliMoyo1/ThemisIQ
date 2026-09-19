"""
PLAN-35 T04: draft lifecycle for the ARIA policy authoring workflow.

Scope of this module as of T04: create/read/list/save/discard/recover a
draft, and the generation persistence path that replaces
api_generate_policy's direct aria_documents upsert. Build (T05, needs the
PDF pipeline), confirm (T06), and submit/decide (T07) are later tasks and
are not implemented here.

Internal helpers take the caller's `db` connection and never commit/close
it themselves unless noted -- callers own the transaction boundary, per
the plan's transaction-algorithm rules (section 9).
"""
from __future__ import annotations

import json
import uuid

from core.timeutils import utcnow
from database import insert_returning_id
from modules.aria.policy_access import (
    resolve_create_bu, document_read_ok, reserve_document_number, bu_scope_ids,
)

MAX_BODY_CHARS = 50_000
MAX_TITLE_CHARS = 200


class PolicyWorkflowError(Exception):
    """Base for errors the route layer translates into the plan's error
    envelope. `code` matches section 8's error-code table."""
    def __init__(self, code: str, message: str, http_status: int = 409):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class StaleDraftError(PolicyWorkflowError):
    def __init__(self, message="This draft changed since you loaded it. Reload and retry."):
        super().__init__("STALE_DRAFT", message, 409)


class OpenRevisionExistsError(PolicyWorkflowError):
    def __init__(self, message="A draft or candidate is already open for this document."):
        super().__init__("OPEN_REVISION_EXISTS", message, 409)


class NotFoundError(PolicyWorkflowError):
    def __init__(self, message="Not found."):
        super().__init__("NOT_FOUND", message, 404)


class ForbiddenError(PolicyWorkflowError):
    def __init__(self, message="You do not have access to this draft."):
        super().__init__("ACTION_FORBIDDEN", message, 403)


class InvalidInputError(PolicyWorkflowError):
    def __init__(self, message):
        super().__init__("INVALID_INPUT", message, 422)


class ContentTooLargeError(PolicyWorkflowError):
    def __init__(self, message):
        super().__init__("CONTENT_TOO_LARGE", message, 413)


class InvalidTemplateError(PolicyWorkflowError):
    def __init__(self, message):
        super().__init__("INVALID_TEMPLATE", message, 422)


class PreviewUnavailableError(PolicyWorkflowError):
    def __init__(self, message="The document conversion service is currently unavailable."):
        super().__init__("PREVIEW_UNAVAILABLE", message, 503)


class PreviewTimeoutError(PolicyWorkflowError):
    def __init__(self, message="Conversion timed out. You can retry the build."):
        super().__init__("PREVIEW_TIMEOUT", message, 504)


class StaleBaseError(PolicyWorkflowError):
    def __init__(self, message="This document changed since your draft was based on it. Start a new revision."):
        super().__init__("STALE_BASE", message, 409)


class BuildRequiredError(PolicyWorkflowError):
    def __init__(self, message="Build this draft before confirming it."):
        super().__init__("BUILD_REQUIRED", message, 409)


def _row_to_dict(row):
    return dict(row) if row else None


def _draft_can_read(actor: dict, draft: dict) -> bool:
    if draft.get("owner_user_id") == actor.get("id"):
        return True
    from core.rbac import has_capability
    return has_capability(actor, "aria.policy.edit_any")


def _draft_can_edit(actor: dict, draft: dict) -> bool:
    return _draft_can_read(actor, draft)  # same rule for this module's scope


def _next_preview_version(current_version: str | None) -> tuple[int, int]:
    """Informational only: what version this draft would become if
    confirmed right now. The actual reservation, race-proofed against every
    other reserved draft/candidate number, happens at confirm time (T06),
    which this module does not yet implement."""
    if not current_version:
        return (1, 0)
    try:
        major_s, minor_s = current_version.split(".", 1)
        return (int(major_s), int(minor_s) + 1)
    except (ValueError, IndexError):
        return (1, 0)


def create_draft_from_generation(
    db,
    actor: dict,
    *,
    control: dict,
    generated_content: str,
    org_name: str,
    doc_type: str,
    framework_label: str,
    integrated_controls: list[dict] | None,
    request_id: str | None,
    target_business_unit_id: int | None,
    org_wide: bool = False,
) -> dict:
    """Persist a successful AI generation as an editable draft, replacing
    the old direct aria_documents INSERT/UPDATE. Never raises on a
    duplicate resubmission of the same request_id -- returns the existing
    draft instead (section 8: "a repeated successful generation request_id
    returns the saved draft").
    """
    if len(generated_content) > MAX_BODY_CHARS:
        raise ContentTooLargeError(
            f"Generated content exceeds the {MAX_BODY_CHARS}-character limit."
        )

    org_id = actor.get("org_id")
    if org_id is None:
        raise InvalidInputError("Your account has no organization; cannot create a draft.")

    # Idempotency: a repeated request_id from this same actor returns the
    # draft it already created, rather than raising or duplicating.
    if request_id:
        existing = db.execute(
            "SELECT * FROM aria_policy_drafts WHERE org_id=%s AND created_by=%s "
            "AND generation_request_id=%s",
            (org_id, actor["id"], request_id),
        ).fetchone()
        if existing:
            return _row_to_dict(existing)

    bu_id, bu_error = resolve_create_bu(actor, target_business_unit_id, org_wide)
    if bu_error:
        raise InvalidInputError(bu_error)

    # Match the exact prior lookup (control_ref + framework) to decide
    # whether this generation targets an existing document as a revision,
    # or is a brand-new policy. An existing legacy (unmanaged) match is
    # still recorded as source_document_id -- adoption itself happens at
    # confirm time (T06), not here.
    existing_doc = db.execute(
        "SELECT id, version, business_unit_id, org_id, policy_workflow_managed "
        "FROM aria_documents WHERE control_ref=%s AND framework=%s",
        (control["ref"], control["fw_name"]),
    ).fetchone()

    source_document_id = None
    reserved_doc_id = None
    base_version_id = None
    if existing_doc:
        existing_doc = dict(existing_doc)
        if not document_read_ok(actor, existing_doc):
            raise ForbiddenError("You do not have access to revise this document.")
        source_document_id = existing_doc["id"]
        version_major, version_minor = _next_preview_version(existing_doc.get("version"))
        base_version_id = existing_doc.get("current_policy_version_id")
    else:
        reserved_doc_id = reserve_document_number(db, is_postgres=_is_postgres())
        version_major, version_minor = 1, 0

    metadata = {
        "title": f"{control['name']} -- {doc_type}",
        "doc_type": doc_type,
        "org_name": org_name,
        "control_id": control["id"],
        "control_ref": control["ref"],
        "primary_framework_id": control.get("framework_id"),
        "framework_label": framework_label,
        "integrated_controls": integrated_controls or [],
        "effective_date": None,
        "review_date": None,
    }

    now = utcnow().isoformat()
    draft_id = str(uuid.uuid4())
    try:
        db.execute(
            "INSERT INTO aria_policy_drafts "
            "(id, org_id, business_unit_id, owner_user_id, created_by, last_edited_by, "
            "source_document_id, base_version_id, reserved_doc_id, "
            "version_major, version_minor, content_kind, body, metadata_json, "
            "author_user_ids_json, state, lock_version, generation_request_id, "
            "created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'markdown',%s,%s,%s,'editing',1,%s,%s,%s)",
            (draft_id, org_id, bu_id, actor["id"], actor["id"], actor["id"],
             source_document_id, base_version_id, reserved_doc_id,
             version_major, version_minor, generated_content,
             json.dumps(metadata), json.dumps([actor["id"]]), request_id,
             now, now),
        )
    except Exception as exc:
        if _is_unique_violation(exc):
            # Concurrent duplicate submission of the same request_id raced
            # us; the other request's row is the winner. Read it back on a
            # fresh transaction rather than continuing on the failed one.
            db.rollback()
            if request_id:
                winner = db.execute(
                    "SELECT * FROM aria_policy_drafts WHERE org_id=%s AND created_by=%s "
                    "AND generation_request_id=%s",
                    (org_id, actor["id"], request_id),
                ).fetchone()
                if winner:
                    return _row_to_dict(winner)
            raise OpenRevisionExistsError() from exc
        raise

    db.commit()
    return get_draft(db, actor, draft_id)


def get_draft(db, actor: dict, draft_id: str) -> dict:
    row = db.execute(
        "SELECT * FROM aria_policy_drafts WHERE id=%s", (draft_id,)
    ).fetchone()
    if not row:
        raise NotFoundError("Draft not found.")
    draft = _row_to_dict(row)
    if not _draft_can_read(actor, draft):
        raise NotFoundError("Draft not found.")  # 404, not 403: don't confirm existence
    return draft


def list_my_drafts(db, actor: dict) -> list[dict]:
    """Metadata only -- no body -- per the API contract."""
    rows = db.execute(
        "SELECT id, org_id, business_unit_id, owner_user_id, source_document_id, "
        "reserved_doc_id, version_major, version_minor, content_kind, state, "
        "lock_version, metadata_json, created_at, updated_at, expires_at "
        "FROM aria_policy_drafts WHERE org_id=%s AND owner_user_id=%s "
        "AND state IN ('editing','ready') ORDER BY updated_at DESC",
        (actor.get("org_id"), actor["id"]),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def save_draft_body(
    db, actor: dict, draft_id: str, *,
    body: str | None = None, title: str | None = None, doc_type: str | None = None,
    effective_date: str | None = None, review_date: str | None = None,
    expected_lock_version: int,
) -> dict:
    draft = get_draft(db, actor, draft_id)
    if not _draft_can_edit(actor, draft):
        raise ForbiddenError()
    if draft["state"] not in ("editing", "ready"):
        raise PolicyWorkflowError(
            "INVALID_INPUT", f"Cannot edit a draft in state '{draft['state']}'.", 422,
        )
    if draft["content_kind"] != "markdown" and body is not None:
        raise PolicyWorkflowError(
            "INVALID_INPUT", "This is a file-based draft; body cannot be edited directly.", 409,
        )
    if body is not None and len(body) > MAX_BODY_CHARS:
        raise ContentTooLargeError(f"Content exceeds the {MAX_BODY_CHARS}-character limit.")
    if title is not None and len(title) > MAX_TITLE_CHARS:
        raise InvalidInputError(f"Title exceeds {MAX_TITLE_CHARS} characters.")

    metadata = json.loads(draft.get("metadata_json") or "{}")
    if title is not None:
        metadata["title"] = title
    if doc_type is not None:
        metadata["doc_type"] = doc_type
    if effective_date is not None:
        metadata["effective_date"] = effective_date
    if review_date is not None:
        metadata["review_date"] = review_date

    author_ids = set(json.loads(draft.get("author_user_ids_json") or "[]"))
    author_ids.add(actor["id"])

    now = utcnow().isoformat()
    updated = db.execute(
        "UPDATE aria_policy_drafts SET "
        "body=COALESCE(%s, body), metadata_json=%s, author_user_ids_json=%s, "
        "last_edited_by=%s, state='editing', lock_version=lock_version+1, "
        "updated_at=%s, expires_at=NULL, "
        # Editing invalidates any prior successful build (section 6.1).
        "build_id=NULL, build_input_sha256=NULL, template_sha256=NULL, "
        "source_path=NULL, branded_path=NULL, preview_path=NULL, "
        "template_snapshot_path=NULL, source_sha256=NULL, branded_sha256=NULL, "
        "preview_sha256=NULL, renderer_manifest_json=NULL, renderer_manifest_sha256=NULL "
        "WHERE id=%s AND lock_version=%s",
        (body, json.dumps(metadata), json.dumps(sorted(author_ids)),
         actor["id"], now, draft_id, expected_lock_version),
    )
    if getattr(updated, "rowcount", 1) == 0:
        raise StaleDraftError()
    db.commit()
    return get_draft(db, actor, draft_id)


def discard_draft(db, actor: dict, draft_id: str, expected_lock_version: int) -> None:
    draft = get_draft(db, actor, draft_id)
    if not _draft_can_edit(actor, draft):
        raise ForbiddenError()
    now = utcnow().isoformat()
    updated = db.execute(
        "UPDATE aria_policy_drafts SET state='discarded', discarded_at=%s, "
        "lock_version=lock_version+1, updated_at=%s "
        "WHERE id=%s AND lock_version=%s AND state IN ('editing','ready')",
        (now, now, draft_id, expected_lock_version),
    )
    if getattr(updated, "rowcount", 1) == 0:
        raise StaleDraftError()
    db.commit()


def recover_draft(db, actor: dict, draft_id: str) -> dict:
    """Create a fresh editable draft seeded from a discarded/expired one's
    last saved content. The original record is kept as history, never
    reused or un-discarded in place."""
    source = get_draft(db, actor, draft_id)
    if not _draft_can_edit(actor, source):
        raise ForbiddenError()
    if source["state"] not in ("discarded", "expired"):
        raise PolicyWorkflowError(
            "INVALID_INPUT", "Only a discarded or expired draft can be recovered.", 422,
        )

    new_id = str(uuid.uuid4())
    now = utcnow().isoformat()
    db.execute(
        "INSERT INTO aria_policy_drafts "
        "(id, org_id, business_unit_id, owner_user_id, created_by, last_edited_by, "
        "source_document_id, base_version_id, reserved_doc_id, "
        "version_major, version_minor, content_kind, body, metadata_json, "
        "author_user_ids_json, state, lock_version, created_at, updated_at) "
        "SELECT %s, org_id, business_unit_id, owner_user_id, created_by, %s, "
        "source_document_id, base_version_id, reserved_doc_id, "
        "version_major, version_minor, content_kind, body, metadata_json, "
        "author_user_ids_json, 'editing', 1, %s, %s "
        "FROM aria_policy_drafts WHERE id=%s",
        (new_id, actor["id"], now, now, draft_id),
    )
    db.commit()
    return get_draft(db, actor, new_id)


def start_revision_draft(db, actor: dict, doc_id: str, copied_from_version_id: int | None = None) -> dict:
    """Begin a new draft revising an existing document. Relies on
    aria_policy_drafts' partial unique index (org_id, source_document_id)
    WHERE state IN ('editing','ready') -- PLAN-35 T01 -- to make the
    one-open-revision-per-document rule race-proof at the database level,
    not just checked-then-inserted in application code."""
    doc = db.execute(
        "SELECT id, org_id, business_unit_id, version, body, doc_type, "
        "current_policy_version_id, policy_workflow_managed, owner_user_id "
        "FROM aria_documents WHERE doc_id=%s", (doc_id,)
    ).fetchone()
    if not doc:
        raise NotFoundError("Document not found.")
    doc = dict(doc)
    if not document_read_ok(actor, doc):
        raise NotFoundError("Document not found.")
    if not _draft_can_edit_document(actor, doc):
        raise ForbiddenError()

    seed_body = doc.get("body") or ""
    if copied_from_version_id is not None:
        version_row = db.execute(
            "SELECT body FROM aria_policy_versions WHERE id=%s AND document_id=%s",
            (copied_from_version_id, doc["id"]),
        ).fetchone()
        if not version_row:
            raise NotFoundError("Source version not found for this document.")
        seed_body = version_row["body"] or ""

    version_major, version_minor = _next_preview_version(doc.get("version"))
    metadata = {
        "title": doc.get("doc_type") or "Policy Document", "doc_type": doc.get("doc_type"),
        "org_name": "", "control_id": None, "control_ref": None,
        "primary_framework_id": None, "framework_label": "",
        "integrated_controls": [], "effective_date": None, "review_date": None,
    }

    draft_id = str(uuid.uuid4())
    now = utcnow().isoformat()
    try:
        db.execute(
            "INSERT INTO aria_policy_drafts "
            "(id, org_id, business_unit_id, owner_user_id, created_by, last_edited_by, "
            "source_document_id, base_version_id, copied_from_version_id, "
            "version_major, version_minor, content_kind, body, metadata_json, "
            "author_user_ids_json, state, lock_version, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'markdown',%s,%s,%s,'editing',1,%s,%s)",
            (draft_id, doc["org_id"], doc["business_unit_id"], actor["id"], actor["id"], actor["id"],
             doc["id"], doc.get("current_policy_version_id"), copied_from_version_id,
             version_major, version_minor, seed_body, json.dumps(metadata),
             json.dumps([actor["id"]]), now, now),
        )
    except Exception as exc:
        if _is_unique_violation(exc):
            db.rollback()
            raise OpenRevisionExistsError() from exc
        raise

    db.commit()
    return get_draft(db, actor, draft_id)


def _draft_can_edit_document(actor: dict, document: dict) -> bool:
    from core.rbac import has_capability
    if has_capability(actor, "aria.policy.edit_any"):
        return True
    if not has_capability(actor, "aria.policy.edit_own"):
        return False
    owner_id = document.get("owner_user_id")
    return owner_id is not None and int(owner_id) == int(actor["id"])


BUILDER_FORMAT_VERSION = 1  # bump whenever build_policy_docx's output shape changes


def _load_scoped_template(db, actor: dict, template_id: int) -> dict:
    row = db.execute(
        "SELECT * FROM aria_doc_templates WHERE id=%s", (template_id,)
    ).fetchone()
    if not row:
        raise NotFoundError("Template not found.")
    tpl = _row_to_dict(row)
    if not tpl.get("is_active", 1):
        raise InvalidTemplateError("This template has been retired. Choose an active template.")
    tpl_org_id = tpl.get("org_id")
    if tpl_org_id is not None:
        if tpl_org_id != actor.get("org_id"):
            raise NotFoundError("Template not found.")
        scope = bu_scope_ids(actor)
        bu_id = tpl.get("business_unit_id")
        if scope is not None and bu_id is not None and int(bu_id) not in scope:
            raise NotFoundError("Template not found.")
    return tpl


def _input_fingerprint(draft: dict, template_sha256: str) -> str:
    """Canonical fingerprint of everything that determines a build's output
    (section 7.3 step 1): unchanged inputs make a retry return the existing
    build instead of reconverting."""
    import hashlib
    parts = [
        draft.get("body") or "",
        draft.get("metadata_json") or "",
        draft.get("reserved_doc_id") or "",
        str(draft.get("version_major")), str(draft.get("version_minor")),
        str(draft.get("org_id")), str(draft.get("business_unit_id")),
        template_sha256,
        str(BUILDER_FORMAT_VERSION),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def build_draft(db, actor: dict, draft_id: str, template_id: int, expected_lock_version: int) -> dict:
    """Build sequence (section 7.3): generate source DOCX, brand it, convert
    to PDF, hash everything, atomically attach, then reauthorize and attach
    inside a short transaction. Blocking (file I/O, and poll_conversion_result
    sleeps) -- callers in an async context MUST run this via
    asyncio.to_thread(), never call it directly from an async def body.

    Idempotent: if the draft is already 'ready' with a build whose
    fingerprint matches what these exact inputs would produce, returns
    that existing build rather than reconverting (cheap retries).
    """
    from modules.aria import policy_storage as storage
    from modules.aria import policy_preview as preview
    from modules.aria.branding_engine import build_policy_docx, apply_template

    draft = get_draft(db, actor, draft_id)
    if not _draft_can_edit(actor, draft):
        raise ForbiddenError()
    if draft["state"] not in ("editing", "ready"):
        raise PolicyWorkflowError("INVALID_INPUT", f"Cannot build a draft in state '{draft['state']}'.", 422)
    if not (draft.get("body") or "").strip():
        raise PolicyWorkflowError("INVALID_INPUT", "Cannot build an empty draft.", 422)
    if draft["lock_version"] != expected_lock_version:
        raise StaleDraftError()

    template = _load_scoped_template(db, actor, template_id)
    # Templates are stored relative to ARIA_TEMPLATE_DIR (routes.py's
    # existing convention for aria_doc_templates.file_path), a different
    # root than the policy_workflow tree policy_storage manages, so this
    # resolves directly against that root rather than through
    # policy_storage's workflow-only path helper.
    from modules.aria.routes import ARIA_TEMPLATE_DIR
    template_abs_path = ARIA_TEMPLATE_DIR / template["file_path"]
    if not template_abs_path.exists():
        raise InvalidTemplateError("Template file is missing on disk.")
    template_sha256 = storage.sha256_file(template_abs_path)

    fingerprint = _input_fingerprint(draft, template_sha256)
    if draft["state"] == "ready" and draft.get("build_input_sha256") == fingerprint:
        try:
            existing_source = storage.resolve_stored_path(draft["source_path"])
            existing_branded = storage.resolve_stored_path(draft["branded_path"])
            existing_preview = storage.resolve_stored_path(draft["preview_path"])
            if existing_source.exists() and existing_branded.exists() and existing_preview.exists():
                return draft  # identical inputs, still-valid build: cheap retry
        except (PolicyWorkflowError, storage.PathContainmentError, KeyError, TypeError):
            pass  # fall through and rebuild

    build_id, staging = storage.new_staging_dir(draft["org_id"])

    reserved_doc_id = draft.get("reserved_doc_id")
    if not reserved_doc_id and draft.get("source_document_id"):
        existing_doc = db.execute(
            "SELECT doc_id FROM aria_documents WHERE id=%s", (draft["source_document_id"],)
        ).fetchone()
        reserved_doc_id = existing_doc["doc_id"] if existing_doc else ""
    version_str = f"{draft['version_major']}.{draft['version_minor']}"
    metadata = json.loads(draft.get("metadata_json") or "{}")

    try:
        source_doc = build_policy_docx(draft["body"], include_preamble=False)
    except Exception as exc:
        raise PolicyWorkflowError("INVALID_INPUT", f"Could not build source document: {exc}", 422)
    source_path = staging / "source.docx"
    source_doc.save(str(source_path))
    storage.validate_docx(source_path)

    branded_path = staging / "branded.docx"
    try:
        apply_template(
            source_path=str(source_path), template_path=str(template_abs_path),
            output_path=str(branded_path), logo_path=template.get("logo_path"),
            doc_title=metadata.get("title", ""), doc_id=reserved_doc_id or "",
            version=version_str, framework=metadata.get("framework_label", ""),
            author_name=actor.get("full_name", ""), generated_body=True,
        )
    except Exception as exc:
        raise PolicyWorkflowError("INVALID_INPUT", f"Branding failed: {exc}", 422)
    storage.validate_docx(branded_path)

    job_id = preview.submit_conversion_job(branded_path.read_bytes())
    try:
        pdf_bytes = preview.poll_conversion_result(job_id)
    except preview.ConversionTimeoutError as exc:
        raise PreviewTimeoutError(str(exc))
    except preview.ConversionFailedError as exc:
        raise PreviewUnavailableError(exc.message)
    finally:
        preview.cleanup_job(job_id)

    preview_path = staging / "preview.pdf"
    preview_path.write_bytes(pdf_bytes)

    source_sha256 = storage.sha256_file(source_path)
    branded_sha256 = storage.sha256_file(branded_path)
    preview_sha256 = storage.sha256_file(preview_path)

    artifacts = storage.attach_build(draft["org_id"], build_id)
    source_rel = storage.relative_path(artifacts / "source.docx")
    branded_rel = storage.relative_path(artifacts / "branded.docx")
    preview_rel = storage.relative_path(artifacts / "preview.pdf")

    now = utcnow().isoformat()
    updated = db.execute(
        "UPDATE aria_policy_drafts SET state='ready', lock_version=lock_version+1, "
        "template_id=%s, build_id=%s, build_input_sha256=%s, template_sha256=%s, "
        "source_path=%s, branded_path=%s, preview_path=%s, "
        "source_sha256=%s, branded_sha256=%s, preview_sha256=%s, updated_at=%s "
        "WHERE id=%s AND lock_version=%s",
        (template_id, build_id, fingerprint, template_sha256,
         source_rel, branded_rel, preview_rel,
         source_sha256, branded_sha256, preview_sha256, now,
         draft_id, expected_lock_version),
    )
    if getattr(updated, "rowcount", 1) == 0:
        # Someone edited/discarded concurrently: leave the orphaned
        # artifacts for the cleanup job rather than attach them to a draft
        # state that no longer matches what we authorized against.
        raise StaleDraftError()
    db.commit()
    return get_draft(db, actor, draft_id)


_VERSION_PUBLIC_FIELDS = (
    "id", "document_id", "draft_id", "base_version_id", "version_major",
    "version_minor", "version", "state", "origin", "template_id",
    "created_by", "created_at", "approved_by", "approved_at", "lock_version",
)


def _version_to_public_dict(row: dict) -> dict:
    """Strips filesystem paths and the raw body from a version row for API
    responses (section 8: 'no file paths or bodies by default'). Hashes are
    kept -- they're integrity/audit identifiers, not paths, and section 11
    explicitly wants them visible in a details panel."""
    hash_fields = ("input_sha256", "source_sha256", "branded_sha256",
                   "preview_sha256", "template_sha256", "renderer_manifest_sha256")
    out = {k: row.get(k) for k in _VERSION_PUBLIC_FIELDS}
    out.update({k: row.get(k) for k in hash_fields})
    return out


def confirm_draft(db, actor: dict, draft_id: str, build_id: str, expected_lock_version: int) -> dict:
    """Section 9.1. One commit boundary; no files are regenerated or
    renamed here -- what was previewed (the exact build_id's artifacts) is
    exactly what becomes the immutable version. No Vault/GRID publish
    happens here (that is T07/T09's job, triggered by approval)."""
    draft = get_draft(db, actor, draft_id)
    if not _draft_can_edit(actor, draft):
        raise ForbiddenError()

    # Retry of an already-committed draft: reauthorize (done above) and
    # return the original result. Do not demand the stale pre-confirm
    # token just to hand back what already exists (section 9.1 item 8).
    if draft["state"] == "committed":
        version = db.execute(
            "SELECT * FROM aria_policy_versions WHERE id=%s", (draft["committed_version_id"],)
        ).fetchone()
        if not version:
            raise PolicyWorkflowError("INVALID_INPUT", "Committed draft has no matching version record.", 500)
        version = dict(version)
        doc = db.execute("SELECT doc_id FROM aria_documents WHERE id=%s", (version["document_id"],)).fetchone()
        return {
            "document_id": version["document_id"], "doc_id": doc["doc_id"] if doc else None,
            "version_id": version["id"], "version": version["version"],
        }

    if draft["state"] != "ready":
        raise BuildRequiredError()
    if draft.get("build_id") != build_id:
        raise PolicyWorkflowError(
            "STALE_DRAFT", "That build is no longer current for this draft; rebuild first.", 409,
        )
    if draft["lock_version"] != expected_lock_version:
        raise StaleDraftError()

    # Re-hash every attached file: proves what is about to be committed is
    # byte-identical to what the build recorded, not silently tampered with
    # or replaced on disk since the build completed.
    from modules.aria import policy_storage as storage
    for path_field, hash_field in (
        ("source_path", "source_sha256"), ("branded_path", "branded_sha256"),
        ("preview_path", "preview_sha256"),
    ):
        rel = draft.get(path_field)
        expected_hash = draft.get(hash_field)
        if not rel or not expected_hash:
            raise BuildRequiredError()
        try:
            actual_path = storage.resolve_stored_path(rel)
        except storage.PathContainmentError:
            raise PolicyWorkflowError("INVALID_INPUT", f"Recorded {path_field} is invalid.", 500)
        if not actual_path.exists() or storage.sha256_file(actual_path) != expected_hash:
            raise PolicyWorkflowError(
                "INVALID_INPUT", f"{path_field} has changed or is missing since the build completed.", 409,
            )

    metadata = draft.get("metadata_json") or "{}"
    identity = json.dumps({
        "created_by_id": actor["id"], "created_by_name": actor.get("full_name", ""),
    })
    version_str = f"{draft['version_major']}.{draft['version_minor']}"
    now = utcnow().isoformat()

    if draft.get("source_document_id") is None:
        # New policy: create the document under its reserved number.
        doc_id_str = draft.get("reserved_doc_id")
        if not doc_id_str:
            raise PolicyWorkflowError("INVALID_INPUT", "Draft has no reserved document number.", 500)
        new_doc_pk = insert_returning_id(
            db,
            "INSERT INTO aria_documents "
            "(doc_id, framework, title, doc_type, version, status, body, "
            "org_id, business_unit_id, owner_user_id, policy_workflow_managed, "
            "created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,'Draft',%s,%s,%s,%s,1,%s,%s)",
            (doc_id_str, json.loads(metadata).get("framework_label", ""),
             json.loads(metadata).get("title", doc_id_str),
             json.loads(metadata).get("doc_type", "Policy"), version_str, draft["body"],
             draft["org_id"], draft["business_unit_id"], actor["id"], now, now),
        )
        document_id = new_doc_pk
        promote_to_current = True
    else:
        document_id = draft["source_document_id"]
        lock_sql = "SELECT * FROM aria_documents WHERE id=%s"
        if _is_postgres():
            lock_sql += " FOR UPDATE"
        doc = db.execute(lock_sql, (document_id,)).fetchone()
        if not doc:
            raise NotFoundError("Document not found.")
        doc = dict(doc)
        if doc.get("current_policy_version_id") != draft.get("base_version_id"):
            raise StaleBaseError()
        existing_candidate = db.execute(
            "SELECT id FROM aria_policy_versions WHERE document_id=%s AND state IN ('draft','pending') "
            "AND id != COALESCE(%s, -1)",
            (document_id, draft.get("committed_version_id")),
        ).fetchone()
        if existing_candidate:
            raise OpenRevisionExistsError("Another candidate version already exists for this document.")
        promote_to_current = doc.get("current_policy_version_id") is None
        doc_id_str = doc["doc_id"]

    version_pk = insert_returning_id(
        db,
        "INSERT INTO aria_policy_versions "
        "(org_id, business_unit_id, document_id, draft_id, base_version_id, "
        "version_major, version_minor, version, state, origin, body, metadata_json, "
        "identity_json, author_user_ids_json, input_sha256, source_sha256, branded_sha256, "
        "preview_sha256, template_sha256, build_id, source_path, branded_path, preview_path, "
        "template_id, renderer_manifest_json, renderer_manifest_sha256, created_by, created_at, lock_version) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'draft','authored',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)",
        (draft["org_id"], draft["business_unit_id"], document_id, draft["id"], draft.get("base_version_id"),
         draft["version_major"], draft["version_minor"], version_str, draft["body"], metadata,
         identity, draft.get("author_user_ids_json"), draft.get("input_sha256"),
         draft.get("source_sha256"), draft.get("branded_sha256"), draft.get("preview_sha256"),
         draft.get("template_sha256"), draft.get("build_id"), draft.get("source_path"),
         draft.get("branded_path"), draft.get("preview_path"), draft.get("template_id"),
         draft.get("renderer_manifest_json"), draft.get("renderer_manifest_sha256"),
         actor["id"], now),
    )

    if promote_to_current:
        db.execute(
            "UPDATE aria_documents SET current_policy_version_id=%s, version=%s, "
            "body=%s, status='Draft', updated_at=%s WHERE id=%s",
            (version_pk, version_str, draft["body"], now, document_id),
        )
    else:
        db.execute("UPDATE aria_documents SET updated_at=%s WHERE id=%s", (now, document_id))

    db.execute(
        "UPDATE aria_policy_drafts SET state='committed', committed_version_id=%s, "
        "lock_version=lock_version+1, updated_at=%s WHERE id=%s AND lock_version=%s",
        (version_pk, now, draft_id, expected_lock_version),
    )

    # Deliberately NOT core.middleware.log_audit(): it opens its own
    # connection and commits immediately, which would let an audit row
    # exist for a confirmation whose main transaction later failed to
    # commit. Section 9.1 item 7 requires the audit row on the SAME
    # connection, committed once together with everything else above.
    db.execute(
        "INSERT INTO audit_log (user_id, username, module, action, entity_type, "
        "entity_id, details, org_id) VALUES (%s,%s,'aria','confirm','document',%s,%s,%s)",
        (actor["id"], actor.get("username", ""), document_id,
         f"Confirmed policy version {version_str} for {doc_id_str}", draft["org_id"]),
    )

    db.commit()
    return {"document_id": document_id, "doc_id": doc_id_str, "version_id": version_pk, "version": version_str}


def get_version(db, actor: dict, version_id: int) -> dict:
    row = db.execute("SELECT * FROM aria_policy_versions WHERE id=%s", (version_id,)).fetchone()
    if not row:
        raise NotFoundError("Version not found.")
    version = _row_to_dict(row)
    doc = db.execute(
        "SELECT org_id, business_unit_id, policy_workflow_managed FROM aria_documents WHERE id=%s",
        (version["document_id"],),
    ).fetchone()
    if not doc or not document_read_ok(actor, dict(doc)):
        raise NotFoundError("Version not found.")
    return version


def list_document_versions(db, actor: dict, doc_id: str) -> list[dict]:
    doc = db.execute(
        "SELECT id, org_id, business_unit_id, policy_workflow_managed FROM aria_documents WHERE doc_id=%s",
        (doc_id,),
    ).fetchone()
    if not doc or not document_read_ok(actor, dict(doc)):
        raise NotFoundError("Document not found.")
    rows = db.execute(
        "SELECT * FROM aria_policy_versions WHERE document_id=%s ORDER BY created_at DESC",
        (doc["id"],),
    ).fetchall()
    return [_version_to_public_dict(_row_to_dict(r)) for r in rows]


def get_version_file_path(db, actor: dict, version_id: int, kind: str):
    """kind is 'preview' or 'branded'. Returns a resolved, contained
    filesystem Path -- never a raw stored string -- or raises NotFoundError/
    PolicyWorkflowError. This is the only function version download/preview
    routes should call; it is what keeps 'no filesystem paths' true at the
    API layer while still letting the route serve the actual file."""
    version = get_version(db, actor, version_id)
    field = "preview_path" if kind == "preview" else "branded_path"
    rel = version.get(field)
    if not rel:
        raise NotFoundError("No file recorded for this version.")
    from modules.aria import policy_storage as storage
    try:
        path = storage.resolve_stored_path(rel)
    except storage.PathContainmentError:
        raise PolicyWorkflowError("PREVIEW_UNAVAILABLE", "Stored file reference is invalid.", 503)
    if not path.exists():
        raise PolicyWorkflowError("PREVIEW_UNAVAILABLE", "File is missing.", 503)
    return path


def _is_postgres() -> bool:
    from config import settings
    return settings.is_postgres()


def _is_unique_violation(exc: Exception) -> bool:
    name = type(exc).__name__
    return "IntegrityError" in name or "UniqueViolation" in name
