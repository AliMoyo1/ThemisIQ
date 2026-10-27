"""Review-only intake for an existing document-control workbook.

Workbook assertions are not controlled documents or accepted control links.
The original XLSX is identified by hash; actual files enter through policy intake.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta

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
            "(org_id,business_unit_id,file_name,file_sha256,rows,warnings,created_by,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (user["org_id"], unit, filename[:200], digest, json.dumps(rows, ensure_ascii=False),
             json.dumps(warnings, ensure_ascii=False), user["id"], now))
        return {"batch_id": batch_id, "version": 1, "rows": rows, "warnings": warnings,
                "source_versions": versions, "file_sha256": digest}
    finally:
        wb.close()


def confirm(db, user, batch_id, version, acknowledged):
    _gate(user)
    if type(batch_id) is not int or type(version) is not int:
        raise RegisterError(422, "Choose a preview and version.")
    batch = db.execute("SELECT * FROM aria_document_register_batches WHERE id=%s AND org_id=%s",
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
    rows = json.loads(batch["rows"])
    for row in rows:
        match_id = _match(db, user, row["code"], row["version"], batch["business_unit_id"])
        db.execute("INSERT INTO aria_document_register_claims "
                   "(batch_id,org_id,business_unit_id,document_code,document_version,title,source_json,matched_document_id) "
                   "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                   (batch_id, user["org_id"], batch["business_unit_id"], row["code"], row["version"],
                    row["title"], json.dumps(row, ensure_ascii=False), match_id))
    changed = db.execute("UPDATE aria_document_register_batches SET status='confirmed',version=version+1,confirmed_at=%s "
                         "WHERE id=%s AND status='previewed' AND version=%s",
                         (utcnow().strftime("%Y-%m-%d %H:%M:%S"), batch_id, version)).rowcount
    if changed != 1:
        raise RegisterError(409, "The preview was already confirmed.")
    return {"claims": len(rows), "matched": sum(bool(_match(db, user, r["code"], r["version"], batch["business_unit_id"])) for r in rows)}


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
                                      "c.state,c.version,b.created_by FROM aria_document_register_claims c "
                                      "JOIN aria_document_register_batches b ON b.id=c.batch_id "
                                      f"WHERE {where} "
                                      "ORDER BY c.id DESC LIMIT %s", [*params, min(max(int(limit), 1), 1000)]).fetchall()]


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
