"""Reviewable intake of existing policies. Suggestions never constitute approval or proof.

The original bytes are private and immutable. Registration records a legacy-origin
version so that later revisions can use PLAN-35's named approval workflow. External
approval is a separate, independently verified attestation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

from core.rbac import has_capability
from core.sql_like import ci_like, like_pattern
from core.timeutils import utcnow
from database import insert_returning_id
from modules.aria.policy_access import document_edit_ok, document_read_ok, reserve_document_number, resolve_create_bu
from modules.aria.policy_storage import DocxValidationError, validate_docx
from modules.aria.policy_parser import MAX_PAGES
from modules.governance.data_service import bu_scope_ids

MAX_FILE = 25 * 1024 * 1024
MAX_CANDIDATES = 80
EXTRACT_TIMEOUT = 40
MIME = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf"}
TYPES = {"Policy", "Procedure", "Standard", "Guideline", "Template", "Record", "Plan"}


class IntakeError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def _root() -> Path:
    from modules.aria.routes import ARIA_UPLOAD_DIR
    return ARIA_UPLOAD_DIR.resolve() / "policy_imports"


def _source_path(row: dict) -> Path:
    path = (_root() / row["stored_path"]).resolve()
    if not path.is_relative_to(_root()):
        raise IntakeError(500, "Stored import path is invalid.")
    return path


def _can_read(actor: dict, row: dict) -> bool:
    if row["org_id"] != actor.get("org_id"):
        return False
    scope = bu_scope_ids(actor)
    return scope is None or row["business_unit_id"] is None or row["business_unit_id"] in scope


def get_import(db, actor: dict, import_id: str) -> dict:
    if not (has_capability(actor, "aria.policy.create") or has_capability(actor, "aria.policy.approve")):
        raise IntakeError(404, "Import not found.")
    row = db.execute("SELECT * FROM aria_policy_imports WHERE id=%s AND org_id=%s",
                     (import_id, actor.get("org_id"))).fetchone()
    if not row or not _can_read(actor, row):
        raise IntakeError(404, "Import not found.")
    return dict(row)


def list_imports(db, actor: dict, limit: int = 100) -> list[dict]:
    scope = bu_scope_ids(actor)
    where = "org_id=%s"
    params: list = [actor.get("org_id")]
    if scope is not None:
        where += " AND (business_unit_id IS NULL"
        if scope:
            where += f" OR business_unit_id IN ({','.join(['%s'] * len(scope))})"
            params.extend(scope)
        where += ")"
    rows = db.execute(
        "SELECT id,file_name,file_hash,file_size,state,external_status,document_id,created_at,extracted_json "
        f"FROM aria_policy_imports WHERE {where} ORDER BY created_at DESC LIMIT %s",
        [*params, max(1, min(int(limit), 200))],
    ).fetchall()
    return [{**dict(r), "suggested_title": json.loads(r["extracted_json"]).get("metadata", {}).get("title", {}).get("value", "")}
            for r in rows]


def _extract_isolated(path: Path, ext: str, filename: str) -> dict:
    """Run expensive document parsing outside the web process and its secrets."""
    worker = Path(__file__).with_name("policy_extract_worker.py")
    clean_env = {key: value for key, value in os.environ.items()
                 if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}}
    clean_env["PYTHONUTF8"] = "1"

    def limits():
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (25, 25))
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))

    try:
        completed = subprocess.run(
            [sys.executable, "-I", str(worker), str(path), ext, filename],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=clean_env, timeout=EXTRACT_TIMEOUT, check=False,
            preexec_fn=limits if os.name == "posix" else None,
        )
        if completed.returncode != 0 or len(completed.stdout) > 1_500_000:
            raise IntakeError(422, "Local extraction could not finish safely. Review the original manually.")
        parsed = json.loads(completed.stdout)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("spans"), list):
            raise ValueError("Invalid extraction response")
        return parsed
    except (subprocess.TimeoutExpired, OSError, ValueError, json.JSONDecodeError) as exc:
        raise IntakeError(422, "Local extraction timed out or failed. Review the original manually.") from exc


def _candidates(db, spans: list[dict]) -> list[dict]:
    controls = db.execute("SELECT c.id,c.ref,c.name,f.name AS framework FROM controls c "
                          "JOIN frameworks f ON f.id=c.framework_id WHERE f.is_active=1 ORDER BY c.id").fetchall()
    proposals = []
    seen = set()
    stop = {"with", "from", "that", "this", "their", "information", "management", "control", "requirements"}
    for span in spans:
        excerpt = span["text"][:500]
        words = set(re.findall(r"[a-z0-9]{4,}", excerpt.lower())) - stop
        for control in controls:
            ref = control["ref"]
            exact = len(ref) >= 3 and bool(re.search(rf"(?<![\w.]){re.escape(ref)}(?![\w.])", span["text"], re.IGNORECASE))
            tokens = set(re.findall(r"[a-z0-9]{4,}", control["name"].lower())) - stop
            overlap = (len(words & tokens) / len(tokens)) if tokens else 0.0
            if not exact and (len(tokens) < 3 or len(words & tokens) < 2 or overlap < 0.67):
                continue
            if (control["id"], span["anchor"]) in seen:
                continue
            seen.add((control["id"], span["anchor"]))
            proposals.append({"control_id": control["id"], "ref": ref, "name": control["name"],
                              "framework": control["framework"], "anchor": span["anchor"],
                              "excerpt": excerpt, "relationship": "related",
                              "match_method": "exact_reference" if exact else "keyword_overlap",
                              "confidence": 1.0 if exact else round(overlap, 2)})
            if len(proposals) >= MAX_CANDIDATES:
                return proposals
    return proposals


def stage_import(db, actor: dict, content: bytes, filename: str, business_unit_id=None, org_wide=False) -> dict:
    from modules.aria.policy_storage import validate_docx
    if not has_capability(actor, "aria.policy.create"):
        raise IntakeError(403, "Policy author permission required.")
    if not actor.get("org_id"):
        raise IntakeError(403, "Organization required.")
    if not content or len(content) > MAX_FILE:
        raise IntakeError(413, "File must be between 1 byte and 25 MB.")
    safe_name = filename.replace("\\", "/").split("/")[-1][:240]
    ext = Path(safe_name).suffix.lower()
    if ext not in MIME:
        raise IntakeError(422, "Upload a DOCX or PDF. Legacy formats need reviewed conversion first.")
    if ext == ".pdf" and not content.startswith(b"%PDF-"):
        raise IntakeError(422, "This is not a PDF file.")
    try:
        bu_id, error = resolve_create_bu(actor, business_unit_id, org_wide)
    except (TypeError, ValueError):
        raise IntakeError(400, "Invalid business unit.") from None
    if error or (bu_id is None and not org_wide and actor.get("business_unit_id") is None):
        raise IntakeError(400, error or "Choose a business unit or explicitly request organization-wide scope.")
    digest = hashlib.sha256(content).hexdigest()
    existing = db.execute("SELECT * FROM aria_policy_imports WHERE org_id=%s AND file_hash=%s "
                          "AND state IN ('needs_review','registered') ORDER BY created_at DESC LIMIT 30",
                          (actor["org_id"], digest)).fetchall()
    for match in existing:
        # The same bytes may be governed separately by two business units.
        # Reuse an intake only when its ownership is the ownership requested.
        if (match["business_unit_id"] == bu_id and _can_read(actor, match)
                and _source_path(match).is_file()):
            return {"id": match["id"], "state": match["state"], "duplicate_existing": True,
                    "extracted": json.loads(match["extracted_json"])}
    import_id = uuid.uuid4().hex
    relative = f"org_{int(actor['org_id'])}/{import_id}{ext}"
    path = (_root() / relative).resolve()
    if not path.is_relative_to(_root()):
        raise IntakeError(400, "Invalid file path.")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        handle.write(content)
    try:
        if ext == ".docx":
            validate_docx(path)
        extracted = _extract_isolated(path, ext, safe_name)
    except (DocxValidationError, IntakeError) as exc:
        path.unlink(missing_ok=True)
        raise IntakeError(422, str(exc)) from exc
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise IntakeError(422, "The file could not be safely parsed. Use a supported document or request manual review.") from exc
    now = utcnow().isoformat()
    try:
        db.execute("INSERT INTO aria_policy_imports "
                   "(id,org_id,business_unit_id,uploaded_by,file_name,stored_path,file_hash,file_size,mime_type,extracted_json,created_at,updated_at) "
                   "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                   (import_id, actor["org_id"], bu_id, actor["id"], safe_name, relative,
                    digest, len(content), MIME[ext], json.dumps(extracted), now, now))
        for item in _candidates(db, extracted["spans"]):
            db.execute("INSERT INTO aria_policy_clause_links "
                       "(import_id,org_id,control_id,anchor,excerpt,relationship,match_method,confidence) "
                       "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                       (import_id, actor["org_id"], item["control_id"], item["anchor"], item["excerpt"],
                        item["relationship"], item["match_method"], item["confidence"]))
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise
    return {"id": import_id, "state": "needs_review", "extracted": extracted}


def detail(db, actor: dict, import_id: str) -> dict:
    row = get_import(db, actor, import_id)
    links = [dict(r) for r in db.execute(
        "SELECT l.id,l.anchor,l.excerpt,l.relationship,l.state,l.match_method,l.confidence,c.ref,c.name,f.name AS framework "
        "FROM aria_policy_clause_links l JOIN controls c ON c.id=l.control_id "
        "JOIN frameworks f ON f.id=c.framework_id WHERE l.import_id=%s AND l.org_id=%s ORDER BY l.id",
        (import_id, row["org_id"])).fetchall()]
    draft = None
    doc_id = None
    pending_replacement = False
    if row["document_id"]:
        version = db.execute("SELECT base_version_id FROM aria_policy_versions WHERE id=%s AND document_id=%s",
                             (row["policy_version_id"], row["document_id"])).fetchone()
        pending_replacement = bool(version and version["base_version_id"] and row["external_status"] != "verified")
        doc = db.execute("SELECT doc_id FROM aria_documents WHERE id=%s AND org_id=%s",
                         (row["document_id"], row["org_id"])).fetchone()
        doc_id = doc["doc_id"] if doc else None
        candidate = db.execute("SELECT id,state,lock_version,build_id,owner_user_id FROM aria_policy_drafts "
                               "WHERE source_document_id=%s AND org_id=%s AND content_kind='uploaded_docx' "
                               "AND state IN ('editing','ready') ORDER BY created_at DESC LIMIT 1",
                               (row["document_id"], row["org_id"])).fetchone()
        if candidate and (candidate["owner_user_id"] == actor.get("id") or has_capability(actor, "aria.policy.edit_any")):
            draft = {key: candidate[key] for key in ("id", "state", "lock_version", "build_id")}
    return {"id": row["id"], "file_name": row["file_name"], "file_hash": row["file_hash"],
            "state": row["state"], "external_status": row["external_status"],
            "document_id": row["document_id"], "evidence_id": row["evidence_id"],
            "doc_id": doc_id, "composition_draft": draft,
            "pending_replacement": pending_replacement,
            "extracted": json.loads(row["extracted_json"]),
            "reviewed": json.loads(row["reviewed_json"] or "{}"), "links": links}


def refresh_suggestions(db, actor: dict, import_id: str) -> dict:
    """Re-extract an immutable staged source without changing its review decisions."""
    if not has_capability(actor, "aria.policy.create"):
        raise IntakeError(403, "Policy author permission required.")
    row = get_import(db, actor, import_id)
    if row["state"] != "needs_review":
        raise IntakeError(409, "Only a staged import can refresh suggestions.")
    path = _source_path(row)
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            raise IntakeError(409, "The submitted file changed or is missing.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["file_hash"]:
            raise IntakeError(409, "The submitted file changed or is missing.")
    except OSError as exc:
        raise IntakeError(409, "The submitted file changed or is missing.") from exc
    ext = Path(row["file_name"]).suffix.lower()
    if ext not in MIME:
        raise IntakeError(422, "Unsupported source format.")
    extracted = _extract_isolated(path, ext, row["file_name"])
    db.execute("UPDATE aria_policy_imports SET extracted_json=%s,updated_at=%s "
               "WHERE id=%s AND org_id=%s AND state='needs_review'",
               (json.dumps(extracted), utcnow().isoformat(), import_id, actor["org_id"]))
    db.commit()
    return detail(db, actor, import_id)


def search_controls(db, actor: dict, query: str) -> list[dict]:
    if not has_capability(actor, "aria.policy.create"):
        raise IntakeError(403, "Policy author permission required.")
    query = query.strip()[:100]
    if len(query) < 2:
        return []
    where = f"({ci_like('c.ref')} OR {ci_like('c.name')} OR {ci_like('f.name')})"
    return [dict(r) for r in db.execute(
        "SELECT c.id,c.ref,c.name,f.name AS framework FROM controls c "
        f"JOIN frameworks f ON f.id=c.framework_id WHERE f.is_active=1 AND {where} "
        "ORDER BY f.name,c.ref LIMIT 30", [like_pattern(query)] * 3).fetchall()]


def version_candidates(db, actor: dict, import_id: str, query: str) -> list[dict]:
    row = get_import(db, actor, import_id)
    if row["state"] != "needs_review" or not has_capability(actor, "aria.policy.create"):
        return []
    query = query.strip()[:100]
    if len(query) < 2:
        return []
    where_bu = "business_unit_id IS NULL" if row["business_unit_id"] is None else "business_unit_id=%s"
    params = [row["org_id"]]
    if row["business_unit_id"] is not None:
        params.append(row["business_unit_id"])
    params.append(like_pattern(query))
    found = db.execute("SELECT * FROM aria_documents WHERE org_id=%s AND " + where_bu +
                       f" AND {ci_like('title')} AND status='Approved' AND current_policy_version_id IS NOT NULL "
                       "ORDER BY updated_at DESC LIMIT 30", params).fetchall()
    return [{"id": d["id"], "doc_id": d["doc_id"], "title": d["title"], "version": d["version"]}
            for d in found if document_edit_ok(actor, dict(d))]


def add_manual_link(db, actor: dict, import_id: str, control_id: int, anchor: str,
                    relationship: str = "related") -> dict:
    if not has_capability(actor, "aria.policy.create"):
        raise IntakeError(403, "Policy author permission required.")
    row = get_import(db, actor, import_id)
    if row["state"] != "needs_review":
        raise IntakeError(409, "This review is already registered. Start a version review for further changes.")
    if relationship not in ("related", "addresses", "partially_addresses"):
        raise IntakeError(422, "Invalid relationship.")
    if not isinstance(control_id, int) or isinstance(control_id, bool) or control_id < 1:
        raise IntakeError(422, "Invalid control.")
    control = db.execute("SELECT c.id FROM controls c JOIN frameworks f ON f.id=c.framework_id "
                         "WHERE c.id=%s AND f.is_active=1", (control_id,)).fetchone()
    if not control:
        raise IntakeError(404, "Control not found.")
    spans = json.loads(row["extracted_json"]).get("spans", [])
    span = next((s for s in spans if s["anchor"] == anchor), None)
    if not span:
        raise IntakeError(422, "Choose a source block or page from this document.")
    db.execute("INSERT INTO aria_policy_clause_links "
               "(import_id,org_id,control_id,anchor,excerpt,relationship,match_method,confidence) "
               "VALUES (%s,%s,%s,%s,%s,%s,'manual',1.0) ON CONFLICT DO NOTHING",
               (import_id, row["org_id"], control_id, anchor, span["text"][:500], relationship))
    db.commit()
    return detail(db, actor, import_id)


def _metadata(value: dict, fallback: dict) -> dict:
    proposed = fallback.get("metadata", {})
    result = {}
    for key in ("title", "version", "doc_type", "owner", "approver", "effective_date", "review_date"):
        raw = value.get(key, proposed.get(key, {}).get("value", ""))
        if not isinstance(raw, str):
            raise IntakeError(422, f"Invalid {key}.")
        result[key] = raw.strip()[:180]
    if not result["title"]:
        raise IntakeError(422, "Enter a document title.")
    if result["doc_type"] not in TYPES:
        raise IntakeError(422, "Choose the document type after reviewing the source.")
    for key in ("effective_date", "review_date"):
        if result[key]:
            try:
                date.fromisoformat(result[key])
            except ValueError:
                raise IntakeError(422, f"Use YYYY-MM-DD for {key}.") from None
    if not re.fullmatch(r"\d{1,3}\.\d{1,3}", result["version"]):
        raise IntakeError(422, "Confirm the source version as major.minor, for example 2.1. Do not guess an unknown version.")
    return result


def _register_import_inner(db, actor: dict, import_id: str, reviewed: dict,
                           accepted_link_ids: list[int], created_paths: list[Path],
                           existing_document_id: int | None = None) -> dict:
    from config import settings
    from modules.aria.routes import ARIA_UPLOAD_DIR
    from modules.evidence.routes import EVIDENCE_DIR
    if not has_capability(actor, "aria.policy.create"):
        raise IntakeError(403, "Policy author permission required.")
    row = get_import(db, actor, import_id)
    if row["state"] == "registered":
        return {"document_id": row["document_id"], "evidence_id": row["evidence_id"], "created": False}
    if row["state"] != "needs_review":
        raise IntakeError(409, "Import is not ready for review.")
    source = _source_path(row)
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != row["file_hash"]:
        raise IntakeError(409, "The submitted file changed or is missing.")
    metadata = _metadata(reviewed, json.loads(row["extracted_json"]))
    if not isinstance(accepted_link_ids, list) or len(accepted_link_ids) > MAX_CANDIDATES or any(
            not isinstance(n, int) or isinstance(n, bool) for n in accepted_link_ids):
        raise IntakeError(422, "Invalid control selection.")
    accepted = set(accepted_link_ids)
    candidates = [dict(r) for r in db.execute(
        "SELECT l.id,l.control_id,f.name AS framework,c.ref FROM aria_policy_clause_links l "
        "JOIN controls c ON c.id=l.control_id JOIN frameworks f ON f.id=c.framework_id "
        "WHERE l.import_id=%s AND l.org_id=%s", (import_id, row["org_id"])).fetchall()]
    if not accepted.issubset({c["id"] for c in candidates}):
        raise IntakeError(422, "Invalid control selection.")
    framework_names = sorted({c["framework"] for c in candidates if c["id"] in accepted})
    refs = sorted({c["ref"] for c in candidates if c["id"] in accepted})
    now = utcnow().isoformat()
    existing = None
    if existing_document_id is not None:
        if not isinstance(existing_document_id, int) or isinstance(existing_document_id, bool):
            raise IntakeError(422, "Choose a valid existing policy.")
        existing = db.execute("SELECT * FROM aria_documents WHERE id=%s AND org_id=%s",
                              (existing_document_id, row["org_id"])).fetchone()
        if (not existing or existing["business_unit_id"] != row["business_unit_id"]
                or not existing["current_policy_version_id"]
                or not document_edit_ok(actor, dict(existing))):
            raise IntakeError(404, "Existing policy not found.")
        if existing["status"] != "Approved":
            raise IntakeError(409, "The existing policy needs an approved current version before replacement.")
        try:
            old_version = tuple(int(part) for part in existing["version"].split("."))
            new_version = tuple(int(part) for part in metadata["version"].split("."))
        except (ValueError, AttributeError):
            raise IntakeError(409, "The existing version cannot be compared safely; review it first.") from None
        if new_version <= old_version:
            raise IntakeError(409, "The replacement version must be newer than the current version.")
        if db.execute("SELECT 1 FROM aria_policy_versions WHERE document_id=%s AND version=%s",
                      (existing_document_id, metadata["version"])).fetchone():
            raise IntakeError(409, "That policy already has this version. Review the existing version instead.")
        doc_id = existing_document_id
    else:
        doc_number = reserve_document_number(db, is_postgres=settings.is_postgres())
        doc_id = insert_returning_id(db, "INSERT INTO aria_documents "
        "(doc_id,framework,control_ref,title,doc_type,version,status,owner,approver,effective_date,review_date,"
        "file_path,file_name,file_size,comments,org_id,business_unit_id,owner_user_id,policy_workflow_managed,created_at,updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,'Draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s)",
        (doc_number, ", ".join(framework_names) or "Unmapped", ", ".join(refs), metadata["title"],
         metadata["doc_type"], metadata["version"], metadata["owner"], metadata["approver"],
         metadata["effective_date"] or None, metadata["review_date"] or None,
         str(source.relative_to(ARIA_UPLOAD_DIR.resolve())).replace("\\", "/"), row["file_name"], row["file_size"],
         "[Imported; approval unverified]", row["org_id"], row["business_unit_id"], actor["id"], now, now))
    major, minor = (int(n) for n in metadata["version"].split("."))
    version_id = insert_returning_id(db, "INSERT INTO aria_policy_versions "
        "(org_id,business_unit_id,document_id,base_version_id,version_major,version_minor,version,state,origin,metadata_json,"
        "input_sha256,source_sha256,source_path,created_by,created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,'legacy','uploaded',%s,%s,%s,%s,%s,%s)",
        (row["org_id"], row["business_unit_id"], doc_id,
         existing["current_policy_version_id"] if existing else None,
         major, minor, metadata["version"], json.dumps(metadata),
         row["file_hash"], row["file_hash"], str(source.relative_to(ARIA_UPLOAD_DIR.resolve())).replace("\\", "/"),
         actor["id"], now))
    if not existing:
        db.execute("UPDATE aria_documents SET current_policy_version_id=%s WHERE id=%s", (version_id, doc_id))
    EVIDENCE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    target_name = f"{uuid.uuid4().hex}{source.suffix}"
    target = EVIDENCE_DIR / target_name
    created_paths.append(target)
    with source.open("rb") as source_file, os.fdopen(
            os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as target_file:
        shutil.copyfileobj(source_file, target_file)
    parent = db.execute("SELECT id,version FROM evidence_items WHERE org_id=%s AND aria_policy_version_id=%s "
                        "ORDER BY id DESC LIMIT 1", (row["org_id"], existing["current_policy_version_id"])).fetchone() if existing else None
    vault_id = insert_returning_id(db, "INSERT INTO evidence_items "
        "(title,description,file_path,file_name,file_size,file_hash,mime_type,category,tags,status,uploaded_by,"
        "org_id,business_unit_id,aria_policy_version_id,parent_id,version) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,'policy',%s,%s,%s,%s,%s,%s,%s,%s)",
        (metadata["title"], "Imported original; approval unverified", target_name, row["file_name"],
         row["file_size"], row["file_hash"], row["mime_type"], f"aria,policy,aria_doc_id={doc_id}",
         "draft" if existing else "current", actor["id"], row["org_id"], row["business_unit_id"], version_id,
         parent["id"] if parent else None, (parent["version"] or 1) + 1 if parent else 1))
    db.execute("INSERT INTO evidence_links (evidence_id,module,entity_type,entity_id,linked_by) "
               "VALUES (%s,'aria','document',%s,%s)", (vault_id, doc_id, actor["id"]))
    for link in candidates:
        db.execute("UPDATE aria_policy_clause_links SET state=%s,decided_by=%s,decided_at=%s WHERE id=%s AND import_id=%s",
                   ("confirmed" if link["id"] in accepted else "rejected", actor["id"], now, link["id"], import_id))
    changed = db.execute("UPDATE aria_policy_imports SET state='registered',reviewed_json=%s,document_id=%s,"
                         "policy_version_id=%s,evidence_id=%s,updated_at=%s WHERE id=%s AND state='needs_review'",
                         (json.dumps(metadata), doc_id, version_id, vault_id, now, import_id))
    if getattr(changed, "rowcount", 1) != 1:
        raise IntakeError(409, "This import was registered by another reviewer. Reload the review queue.")
    db.commit()
    return {"document_id": doc_id, "evidence_id": vault_id, "created": True,
            "pending_replacement": bool(existing)}


def register_import(db, actor: dict, import_id: str, reviewed: dict, accepted_link_ids: list[int],
                    existing_document_id: int | None = None) -> dict:
    created_paths: list[Path] = []
    try:
        return _register_import_inner(db, actor, import_id, reviewed, accepted_link_ids, created_paths,
                                      existing_document_id)
    except Exception:
        db.rollback()
        for path in created_paths:
            path.unlink(missing_ok=True)
        raise


def verify_external(db, actor: dict, import_id: str, *, approver: str, approved_at: str, proof: str) -> dict:
    row = get_import(db, actor, import_id)
    if row["state"] != "registered":
        raise IntakeError(409, "Register this document first.")
    if not has_capability(actor, "aria.policy.approve") or actor["id"] == row["uploaded_by"]:
        raise IntakeError(403, "An independent policy approver must verify the external approval.")
    if row["external_status"] == "verified":
        raise IntakeError(409, "External approval is already verified.")
    if not (approver.strip() and proof.strip() and approved_at.strip()):
        raise IntakeError(422, "Approver, date and evidence location are required.")
    try:
        approval_day = date.fromisoformat(approved_at)
    except ValueError:
        raise IntakeError(422, "Use YYYY-MM-DD for the approval date.") from None
    if approval_day > date.today():
        raise IntakeError(422, "External approval cannot be dated in the future.")
    doc = db.execute("SELECT * FROM aria_documents WHERE id=%s AND org_id=%s",
                     (row["document_id"], row["org_id"])).fetchone()
    if not doc or not document_read_ok(actor, dict(doc)):
        raise IntakeError(404, "Import not found.")
    if not _source_path(row).is_file() or hashlib.sha256(_source_path(row).read_bytes()).hexdigest() != row["file_hash"]:
        raise IntakeError(409, "The original changed or is missing; approval cannot be verified.")
    version = db.execute("SELECT base_version_id FROM aria_policy_versions WHERE id=%s AND document_id=%s",
                         (row["policy_version_id"], row["document_id"])).fetchone()
    if not version:
        raise IntakeError(409, "The imported policy version is missing.")
    if version["base_version_id"] is not None and doc["current_policy_version_id"] != version["base_version_id"]:
        raise IntakeError(409, "The current policy changed during review. Reassess this replacement.")
    if version["base_version_id"] is None and doc["current_policy_version_id"] != row["policy_version_id"]:
        raise IntakeError(409, "The current policy changed during review. Reassess this import.")
    if version["base_version_id"] is not None and db.execute(
            "SELECT 1 FROM aria_policy_versions WHERE document_id=%s AND state IN ('draft','pending') LIMIT 1",
            (row["document_id"],)).fetchone():
        raise IntakeError(409, "Resolve the open internal revision before adopting this external update.")
    now = utcnow().isoformat()
    changed_attestation = db.execute("UPDATE aria_policy_imports SET external_status='verified',external_approver=%s,"
                                    "external_approved_at=%s,external_proof=%s,external_source_sha256=%s,"
                                    "external_verified_by=%s,external_verified_at=%s,updated_at=%s "
                                    "WHERE id=%s AND external_status='unverified'",
                                    (approver.strip()[:180], approved_at, proof.strip()[:500], row["file_hash"],
                                     actor["id"], now, now, import_id))
    if getattr(changed_attestation, "rowcount", 1) != 1:
        raise IntakeError(409, "External approval was already verified. Reload this import.")
    metadata = json.loads(row["reviewed_json"] or "{}")
    if version["base_version_id"] is not None:
        from modules.aria.routes import ARIA_UPLOAD_DIR
        mapped = db.execute("SELECT DISTINCT f.name AS framework,c.ref FROM aria_policy_clause_links l "
                            "JOIN controls c ON c.id=l.control_id JOIN frameworks f ON f.id=c.framework_id "
                            "WHERE l.import_id=%s AND l.org_id=%s AND l.state='confirmed'",
                            (import_id, row["org_id"])).fetchall()
        frameworks = ", ".join(sorted({m["framework"] for m in mapped})) or "Unmapped"
        control_refs = ", ".join(sorted({m["ref"] for m in mapped}))
        previous = db.execute("SELECT id FROM evidence_items WHERE org_id=%s AND aria_policy_version_id=%s "
                              "AND status='current'", (row["org_id"], version["base_version_id"])).fetchall()
        for prior in previous:
            db.execute("UPDATE evidence_items SET status='superseded',updated_at=%s WHERE id=%s",
                       (now, prior["id"]))
        changed = db.execute("UPDATE aria_documents SET current_policy_version_id=%s,title=%s,doc_type=%s,version=%s,"
                   "framework=%s,control_ref=%s,"
                   "owner=%s,approver=%s,effective_date=%s,review_date=%s,file_path=%s,file_name=%s,file_size=%s,"
                   "status='Approved',comments='[Externally approved; verified in ThemisIQ]',"
                   "reviewed_by=%s,reviewed_at=%s,updated_at=%s WHERE id=%s AND current_policy_version_id=%s",
                   (row["policy_version_id"], metadata["title"], metadata["doc_type"], metadata["version"],
                    frameworks, control_refs,
                    metadata["owner"], metadata["approver"], metadata["effective_date"] or None,
                    metadata["review_date"] or None,
                    str(_source_path(row).relative_to(ARIA_UPLOAD_DIR.resolve())).replace("\\", "/"),
                    row["file_name"], row["file_size"], actor["id"], now, now, row["document_id"],
                    version["base_version_id"]))
        if getattr(changed, "rowcount", 1) != 1:
            raise IntakeError(409, "The current policy changed during review. Reassess this replacement.")
    else:
        changed = db.execute("UPDATE aria_documents SET status='Approved',"
                   "comments='[Externally approved; verified in ThemisIQ]',"
                   "reviewed_by=%s,reviewed_at=%s,updated_at=%s "
                   "WHERE id=%s AND current_policy_version_id=%s",
                   (actor["id"], now, now, row["document_id"], row["policy_version_id"]))
        if getattr(changed, "rowcount", 1) != 1:
            raise IntakeError(409, "The current policy changed during review. Reassess this import.")
    db.execute("UPDATE evidence_items SET status='current',"
               "description='Imported original; external approval verified',updated_at=%s "
               "WHERE id=%s AND org_id=%s", (now, row["evidence_id"], row["org_id"]))
    db.commit()
    return {"document_id": row["document_id"], "external_status": "verified",
            "replacement_adopted": version["base_version_id"] is not None}
