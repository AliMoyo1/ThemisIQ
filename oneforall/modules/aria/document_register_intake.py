"""Review-only intake for an existing document-control workbook.

Workbook assertions are not controlled documents or accepted control links.
The source XLSX is filed as unverified reference material only after confirmation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import timedelta
from pathlib import Path

from config import settings
from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance.register_imports import _cell, _workbook
from modules.ai_governance.service import ServiceError
from modules.aria.policy_access import document_read_ok, resolve_create_bu
from modules.governance.data_service import bu_scope_ids


class RegisterError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


HEADINGS = ("#", "Document Code", "Document Title", "Document Type", "Version", "Effective Date",
            "Last Reviewed", "Next Review", "Review Status", "Owner", "ISO Control Reference",
            "Notes/Filename", "Approval Status")
FIELDS = ("number", "code", "title", "type", "version", "effective_date", "last_reviewed",
          "next_review", "review_status", "owner", "control_reference", "notes", "approval_claim")


def _gate(user):
    if not user.get("org_id") or not has_capability(user, "aria.policy.create"):
        raise RegisterError(403, "Policy author permission required.")


def _unit(user, business_unit_id=None, org_wide=False):
    try:
        requested = int(business_unit_id) if business_unit_id not in (None, "") else None
        unit, error = resolve_create_bu(user, requested, org_wide)
    except (TypeError, ValueError):
        raise RegisterError(400, "Choose an accessible business unit.") from None
    if error or (unit is None and not org_wide and user.get("business_unit_id") is None):
        raise RegisterError(400, error or "Choose an accessible business unit.")
    return unit


def _visible(user, row):
    if row["org_id"] != user.get("org_id"):
        return False
    scope = bu_scope_ids(user)
    return scope is None or row["business_unit_id"] is None or row["business_unit_id"] in scope


def _version(text):
    found = re.search(r"\b(?:version|v)\s*([0-9]+(?:\.[0-9]+)*)\b", str(text or ""), re.I)
    return found.group(1) if found else None


def _match(db, user, code, version, unit):
    candidates = db.execute("SELECT id,doc_id,version,org_id,business_unit_id,policy_workflow_managed "
                            "FROM aria_documents WHERE org_id=%s AND lower(doc_id)=lower(%s) AND version=%s",
                            (user["org_id"], code, version)).fetchall()
    visible = [r for r in candidates if document_read_ok(user, dict(r)) and r["business_unit_id"] == unit]
    return visible[0]["id"] if len(visible) == 1 else None


def _retain_source(db, user, batch, data):
    """File exactly the confirmed workbook bytes; return (Vault id, new path)."""
    if settings.is_postgres():
        key = int.from_bytes(hashlib.sha256(
            f"register:{batch['org_id']}:{batch['business_unit_id']}:{batch['file_sha256']}".encode()
        ).digest()[:8], "big", signed=True)
        db.execute("SELECT pg_advisory_xact_lock(%s)", (key,)).fetchone()
    scope = "b.business_unit_id IS NULL" if batch["business_unit_id"] is None else "b.business_unit_id=%s"
    params = [batch["org_id"], batch["file_sha256"]]
    if batch["business_unit_id"] is not None:
        params.append(batch["business_unit_id"])
    existing = db.execute(
        "SELECT b.source_evidence_id,e.file_path FROM aria_document_register_batches b "
        "JOIN evidence_items e ON e.id=b.source_evidence_id "
        f"WHERE b.org_id=%s AND b.file_sha256=%s AND {scope} "
        "AND b.status='confirmed' AND e.status='current' ORDER BY b.id DESC LIMIT 1", params,
    ).fetchone()
    root = Path(os.getenv("EVIDENCE_DIR", "data/evidence"))
    if existing:
        path = (root / existing["file_path"]).resolve()
        if path.is_relative_to(root.resolve()) and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == batch["file_sha256"]:
            return existing["source_evidence_id"], None
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.xlsx"
    path = root / stored
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
        stream.write(data)
    try:
        evidence_id = insert_returning_id(
            db, "INSERT INTO evidence_items "
            "(title,description,file_path,file_name,file_size,file_hash,mime_type,category,tags,status,"
            "uploaded_by,owner_user_id,org_id,business_unit_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (f"Document register: {batch['file_name']}",
             "Confirmed source workbook; its entries and approval claims are unverified.",
             stored, batch["file_name"], len(data), batch["file_sha256"],
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "report", "aria,document-register,source-workbook", "current",
             user["id"], user["id"], batch["org_id"], batch["business_unit_id"]),
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return evidence_id, path


def preview(db, user, data, filename, business_unit_id=None, org_wide=False):
    _gate(user)
    unit = _unit(user, business_unit_id, org_wide)
    if not filename.lower().endswith(".xlsx"):
        raise RegisterError(422, "Upload an XLSX document register.")
    try:
        wb = _workbook(data)
    except ServiceError as exc:
        raise RegisterError(exc.status, exc.message) from None
    try:
        if "Document Register" not in wb.sheetnames:
            raise RegisterError(422, "The workbook needs a Document Register sheet.")
        sheet = wb["Document Register"]
        headings = tuple(_cell(c.value) for c in sheet[3][:len(HEADINGS)])
        if headings != HEADINGS:
            raise RegisterError(422, "The document register headings differ from this template; review the mapping.")
        rows, warnings, seen = [], [], set()
        for line, values in enumerate(sheet.iter_rows(min_row=4, values_only=True), start=4):
            if not values or not str(values[0] or "").strip().isdigit():
                continue  # section heading, not a register entry
            row = {field: _cell(values[i] if i < len(values) else None) for i, field in enumerate(FIELDS)}
            row["line"] = line
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", row["code"]) or not row["title"] or not row["version"]:
                raise RegisterError(422, f"Row {line} needs a safe code, title and version.")
            key = (row["code"].casefold(), row["version"].casefold())
            if key in seen:
                raise RegisterError(422, f"Duplicate document code and version on row {line}.")
            seen.add(key)
            row["outcome"] = "matched" if _match(db, user, row["code"], row["version"], unit) else "needs_source_file"
            if row["review_status"].casefold() in ("superseded", "withdrawn", "retired"):
                warnings.append({"code": "not_current", "ref": row["code"], "line": line})
            rows.append(row)
        if not rows or len(rows) > 1000:
            raise RegisterError(422, "The workbook needs 1 to 1000 detailed document rows.")
        versions = {"filename": _version(filename), "banner": _version(sheet["A2"].value)}
        if "Document Control" in wb.sheetnames:
            history = [_version(r[0]) for r in wb["Document Control"].iter_rows(values_only=True) if r]
            versions["revision_history"] = next((v for v in reversed(history) if v), None)
        distinct = {v for v in versions.values() if v}
        if len(distinct) > 1:
            warnings.append({"code": "version_conflict", "ref": "", "versions": versions})
        now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
        digest = hashlib.sha256(data).hexdigest()
        batch_id = insert_returning_id(db,
            "INSERT INTO aria_document_register_batches "
            "(org_id,business_unit_id,file_name,file_sha256,source_bytes,rows,warnings,created_by,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (user["org_id"], unit, filename.replace("\\", "/").split("/")[-1][:200], digest, data,
             json.dumps(rows, ensure_ascii=False),
             json.dumps(warnings, ensure_ascii=False), user["id"], now))
        return {"batch_id": batch_id, "version": 1, "rows": rows, "warnings": warnings,
                "source_versions": versions, "file_sha256": digest}
    finally:
        wb.close()


def confirm(db, user, batch_id, version, acknowledged):
    _gate(user)
    if type(batch_id) is not int or type(version) is not int:
        raise RegisterError(422, "Choose a preview and version.")
    lock = " FOR UPDATE" if settings.is_postgres() else ""
    batch = db.execute("SELECT * FROM aria_document_register_batches WHERE id=%s AND org_id=%s" + lock,
                       (batch_id, user["org_id"])).fetchone()
    if not batch or batch["created_by"] != user["id"] or not _visible(user, batch):
        raise RegisterError(404, "Preview not found.")
    if batch["version"] != version or batch["status"] != "previewed":
        raise RegisterError(409, "The preview is no longer current.")
    if utcnow() - __import__("datetime").datetime.strptime(str(batch["created_at"])[:19], "%Y-%m-%d %H:%M:%S") > timedelta(days=7):
        raise RegisterError(409, "The preview expired.")
    # A user losing their unit or organization-wide authoring permission cannot confirm later.
    if batch["business_unit_id"] is None:
        if not has_capability(user, "aria.policy.edit_any"):
            raise RegisterError(403, "Organization-wide scope is no longer available.")
    elif _unit(user, batch["business_unit_id"]) != batch["business_unit_id"]:
        raise RegisterError(403, "The preview scope is no longer available.")
    warnings = json.loads(batch["warnings"])
    required = {f"{w['code']}:{w.get('ref','')}" for w in warnings}
    if not isinstance(acknowledged, list) or set(acknowledged) != required:
        raise RegisterError(422, "Review and acknowledge every workbook discrepancy.")
    data = bytes(batch["source_bytes"] or b"")
    if not data or hashlib.sha256(data).hexdigest() != batch["file_sha256"]:
        raise RegisterError(409, "The preview source is missing or changed. Upload the workbook again.")
    source_id, new_path = _retain_source(db, user, batch, data)
    rows = json.loads(batch["rows"])
    try:
        for row in rows:
            match_id = _match(db, user, row["code"], row["version"], batch["business_unit_id"])
            db.execute("INSERT INTO aria_document_register_claims "
                       "(batch_id,org_id,business_unit_id,document_code,document_version,title,source_json,matched_document_id) "
                       "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                       (batch_id, user["org_id"], batch["business_unit_id"], row["code"], row["version"],
                        row["title"], json.dumps(row, ensure_ascii=False), match_id))
        changed = db.execute("UPDATE aria_document_register_batches SET status='confirmed',version=version+1,"
                             "source_evidence_id=%s,source_bytes=NULL,confirmed_at=%s "
                             "WHERE id=%s AND status='previewed' AND version=%s",
                             (source_id, utcnow().strftime("%Y-%m-%d %H:%M:%S"), batch_id, version)).rowcount
        if changed != 1:
            raise RegisterError(409, "The preview was already confirmed.")
        return {"claims": len(rows), "matched": sum(bool(_match(db, user, r["code"], r["version"], batch["business_unit_id"])) for r in rows),
                "source_evidence_id": source_id, "_created_source_path": new_path}
    except Exception:
        if new_path is not None:
            new_path.unlink(missing_ok=True)
        raise


def claims(db, user, limit=200):
    if not user.get("org_id") or not (has_capability(user, "aria.policy.create") or has_capability(user, "aria.policy.approve")):
        raise RegisterError(403, "Policy review permission required.")
    scope = bu_scope_ids(user)
    where, params = "c.org_id=%s", [user["org_id"]]
    if scope is not None:
        where += " AND (c.business_unit_id IS NULL"
        if scope:
            where += f" OR c.business_unit_id IN ({','.join(['%s'] * len(scope))})"
            params.extend(scope)
        where += ")"
    return [dict(r) for r in db.execute("SELECT c.id,c.document_code,c.document_version,c.title,c.matched_document_id,"
                                      "c.state,c.version,b.created_by,b.source_evidence_id FROM aria_document_register_claims c "
                                      "JOIN aria_document_register_batches b ON b.id=c.batch_id "
                                      f"WHERE {where} "
                                      "ORDER BY c.id DESC LIMIT %s", [*params, min(max(int(limit), 1), 1000)]).fetchall()]


def expire_previews(org_id, *, db=None):
    """Discard unconfirmed workbook bytes after the seven-day review window."""
    from database import get_db_background

    owned = db is None
    db = db or get_db_background()
    try:
        cutoff = (utcnow() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        result = db.execute(
            "UPDATE aria_document_register_batches SET status='expired',source_bytes=NULL,version=version+1 "
            "WHERE org_id=%s AND status='previewed' AND created_at<%s", (org_id, cutoff))
        db.commit()
        return result.rowcount
    except Exception:
        db.rollback()
        raise
    finally:
        if owned:
            db.close()


def review_claim(db, user, claim_id, version, decision):
    if not has_capability(user, "aria.policy.approve"):
        raise RegisterError(403, "Policy reviewer permission required.")
    if type(claim_id) is not int or type(version) is not int or decision not in ("exact_match", "needs_source_file"):
        raise RegisterError(422, "Choose a claim, version and review outcome.")
    claim = db.execute("SELECT c.*,b.created_by FROM aria_document_register_claims c "
                       "JOIN aria_document_register_batches b ON b.id=c.batch_id "
                       "WHERE c.id=%s AND c.org_id=%s", (claim_id, user.get("org_id"))).fetchone()
    if not claim or not _visible(user, claim):
        raise RegisterError(404, "Claim not found.")
    if claim["created_by"] == user.get("id"):
        raise RegisterError(403, "A different reviewer must reconcile this claim.")
    if claim["state"] != "pending_review" or claim["version"] != version:
        raise RegisterError(409, "The claim was already reviewed.")
    match_id = _match(db, user, claim["document_code"], claim["document_version"], claim["business_unit_id"])
    if decision == "exact_match" and match_id is None:
        raise RegisterError(409, "The exact scoped document version is no longer available.")
    state = "matched_for_review" if decision == "exact_match" else "needs_source_file"
    changed = db.execute("UPDATE aria_document_register_claims SET state=%s,matched_document_id=%s,"
                         "version=version+1,reviewed_by=%s,reviewed_at=%s "
                         "WHERE id=%s AND state='pending_review' AND version=%s",
                         (state, match_id if decision == "exact_match" else None, user["id"],
                          utcnow().strftime("%Y-%m-%d %H:%M:%S"), claim_id, version)).rowcount
    if changed != 1:
        raise RegisterError(409, "The claim was already reviewed.")
    return {"state": state, "document_id": match_id if decision == "exact_match" else None}
