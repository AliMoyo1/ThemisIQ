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


def _is_postgres() -> bool:
    from config import settings
    return settings.is_postgres()


def _is_unique_violation(exc: Exception) -> bool:
    name = type(exc).__name__
    return "IntegrityError" in name or "UniqueViolation" in name
