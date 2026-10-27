"""Bounded, deterministic workbook intake for AI systems and AIMS risks.

An upload is only a preview. Confirmation is a specialist's recorded act; no
spreadsheet value grants approval, creates a user, or resolves a risk score.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import timedelta

from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance.service import ServiceError, _check_unit
from modules.governance.entity_scope import describe_record, entity_scope_sql

MAX_BYTES = 4 * 1024 * 1024
MAX_EXPANDED = 24 * 1024 * 1024
MAX_ROWS = 1000
PROFILE_VERSION = "register-xlsx-v1"
SYSTEM_FIELDS = ("external_ref", "name", "version", "category", "system_type", "vendor", "purpose",
                 "data_processed", "pii", "accountability", "risk_label", "scope", "claimed_status", "notes")
RISK_FIELDS = ("ref", "system_ref", "system_name", "category", "subcategory", "description", "impact_text",
               "assets", "framework_ref", "likelihood", "impact", "inherent_score", "inherent_level",
               "controls", "effectiveness", "residual_l", "residual_i", "residual_score", "residual_level",
               "treatment", "owner", "target_date", "next_review")


def _require(user, kind):
    if not has_capability(user, "ai_use.review") or (kind == "ai_risks" and not has_capability(user, "orm.event.manage")):
        raise ServiceError(403, "Access denied.")


def _norm(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _cell(value):
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > 2000:
        raise ServiceError(422, "A workbook cell is too long. Shorten it before importing.")
    return text


def _workbook(data):
    if not data or len(data) > MAX_BYTES or not data.startswith(b"PK"):
        raise ServiceError(422, "Upload a valid XLSX workbook of at most 4 MB.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        members = archive.infolist()
        if (len(members) > 180 or sum(m.file_size for m in members) > MAX_EXPANDED or
                any("externalLink" in m.filename or "vbaProject" in m.filename or
                    m.filename.endswith((".rels/", ".bin")) for m in members)):
            raise ServiceError(422, "External links, macros or oversized workbook content are not accepted.")
        if archive.testzip() is not None:
            raise ServiceError(422, "The workbook is damaged.")
        from openpyxl import load_workbook
        # Read-only mode preserves cells in some legacy workbooks whose merge
        # metadata incorrectly covers their header row. We still reject
        # formulas by inspecting cell types before any values are staged.
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except (zipfile.BadZipFile, KeyError, ValueError, OSError):
        raise ServiceError(422, "The XLSX workbook could not be read.") from None
    if len(wb.worksheets) > 8 or any(s.sheet_state != "visible" for s in wb.worksheets):
        raise ServiceError(422, "Remove hidden sheets or extra sheets before importing.")
    for sheet in wb.worksheets:
        if sheet.max_row > MAX_ROWS + 45 or sheet.max_column > 80:
            raise ServiceError(422, "The workbook exceeds the row or column limit.")
        for row in sheet.iter_rows():
            for cell in row:
                if cell.data_type == "f" or (isinstance(cell.value, str) and cell.value.startswith(("=", "+", "@"))):
                    raise ServiceError(422, "Remove workbook formulas before importing.")
    return wb


def _sheet(wb, name, fields, mapping):
    if name not in wb.sheetnames:
        raise ServiceError(422, f"The workbook needs a visible '{name}' sheet.")
    sheet = wb[name]
    headers = [_cell(c.value) for c in sheet[2]]
    if not any(headers):
        raise ServiceError(422, f"The '{name}' sheet needs headings on row 2.")
    if mapping:
        if not isinstance(mapping, dict) or any(k not in fields or v not in headers for k,v in mapping.items()):
            raise ServiceError(422, "The column mapping is invalid.")
        columns = {field: headers.index(header) for field, header in mapping.items()}
    else:
        # The audited workbook profile has stable column order; any unexpected
        # heading requires an explicit mapping rather than a guessed position.
        expected = {"AI Systems Inventory": ("System ID", "AI System Name", "Version"),
                    "Risk Register": ("Risk ID", "System ID", "AI System")}[name]
        if tuple(headers[:3]) != expected or len(headers) < len(fields):
            raise ServiceError(422, "The headings differ from the known template. Send an explicit column mapping.")
        columns = {field: index for index, field in enumerate(fields)}
    required = {"AI Systems Inventory": {"external_ref", "name", "purpose"},
                "Risk Register": {"ref", "description", "likelihood", "impact"}}[name]
    if not required.issubset(columns):
        raise ServiceError(422, "Map the reference, description and other required columns before previewing.")
    rows = []
    for number, values in enumerate(sheet.iter_rows(min_row=3, values_only=True), start=3):
        if not any(v is not None and str(v).strip() for v in values):
            continue
        rows.append({"line": number, **{field: _cell(values[idx] if idx < len(values) else None)
                                        for field, idx in columns.items()}})
    return rows


def _cover_version(wb):
    if "Cover" not in wb.sheetnames:
        return None
    for row in wb["Cover"].iter_rows(values_only=True):
        if row and _norm(row[0]) == "version":
            return _cell(row[1]) if len(row) > 1 else None
    return None


def _header_version(wb, sheet):
    first = _cell(wb[sheet]["A1"].value)
    match = re.search(r"\bVersion\s+([0-9]+(?:\.[0-9]+)*)", first, re.I)
    return match.group(1) if match else None


def _positive_int(raw, label, line):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ServiceError(422, f"Row {line}: {label} must be 1 to 5.") from None
    if not 1 <= value <= 5:
        raise ServiceError(422, f"Row {line}: {label} must be 1 to 5.")
    return value


def _existing_ref(db, ref):
    return db.execute("SELECT a.id,a.business_unit_id,p.version,p.external_ref FROM ai_use_profiles p "
                      "JOIN applications a ON a.id=p.application_id WHERE lower(p.external_ref)=lower(%s)",
                      (ref,)).fetchone()


def preview(db, user, *, kind, data, filename, business_unit_id=None, assessment_id=None, mapping=None):
    if kind not in ("ai_systems", "ai_risks"):
        raise ServiceError(422, "Choose an AI systems or AI risk register.")
    _require(user, kind)
    if not user.get("org_id"):
        raise ServiceError(403, "Choose an organization.")
    unit = _check_unit(db, user, business_unit_id)
    if kind == "ai_risks":
        if type(assessment_id) is not int or not describe_record(db, ("orm", "aims"), assessment_id, user):
            raise ServiceError(404, "Assessment not found.")
        assessment = db.execute("SELECT business_unit_id FROM aims_assessments WHERE id=%s", (assessment_id,)).fetchone()
        if assessment["business_unit_id"] != unit:
            raise ServiceError(422, "The register unit must match the assessment unit.")
    elif assessment_id is not None:
        raise ServiceError(422, "An assessment applies only to the AI risk register.")
    wb = _workbook(data)
    try:
        sheet = "AI Systems Inventory" if kind == "ai_systems" else "Risk Register"
        fields = SYSTEM_FIELDS if kind == "ai_systems" else RISK_FIELDS
        rows = _sheet(wb, sheet, fields, mapping)
        if not rows or len(rows) > MAX_ROWS:
            raise ServiceError(422, "The register must contain 1 to 1000 detailed rows.")
        warnings = []
        cv, sv = _cover_version(wb), _header_version(wb, sheet)
        if cv and sv and cv != sv:
            warnings.append({"code": "version_conflict", "detail": "Cover and inventory versions differ.",
                             "cover": cv, "detail_version": sv})
        seen = set()
        treatments = {}
        if kind == "ai_risks" and "Risk Treatment" in wb.sheetnames:
            ts = wb["Risk Treatment"]
            if [_cell(c.value) for c in ts[2]][:2] != ["Risk ID", "AI System"]:
                raise ServiceError(422, "The treatment sheet headings need review.")
            for row in ts.iter_rows(min_row=3, values_only=True):
                if row and row[0]:
                    key = _cell(row[0])
                    if key in treatments:
                        warnings.append({"code": "duplicate_treatment", "ref": key})
                    treatments[key] = {"level": _cell(row[2]), "treatment": _cell(row[3]),
                                       "action": _cell(row[4]), "owner": _cell(row[5]), "target": _cell(row[9])}
        for row in rows:
            ref = row["external_ref" if kind == "ai_systems" else "ref"].strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", ref):
                raise ServiceError(422, f"Row {row['line']}: enter a stable reference with at most 80 safe characters.")
            if ref.casefold() in seen:
                raise ServiceError(422, f"Duplicate reference {ref} in the workbook.")
            seen.add(ref.casefold())
            if kind == "ai_systems":
                if not row.get("name") or not row.get("purpose"):
                    raise ServiceError(422, f"Row {row['line']}: name and purpose are required.")
                existing = _existing_ref(db, ref)
                visible_existing = existing and describe_record(db, ("governance", "application"), existing["id"], user)
                row["outcome"] = "conflict" if visible_existing else "create"
                if visible_existing:
                    row["existing_id"] = existing["id"]
                    warnings.append({"code": "existing_reference", "ref": ref})
            else:
                l = _positive_int(row.get("likelihood"), "Likelihood", row["line"])
                i = _positive_int(row.get("impact"), "Impact", row["line"])
                row["computed_score"] = l * i
                if row.get("inherent_score") and str(l*i) != row["inherent_score"]:
                    warnings.append({"code": "score_conflict", "ref": ref})
                if row.get("inherent_level", "").upper() == "CRITICAL" and l*i < 20:
                    warnings.append({"code": "rubric_conflict", "ref": ref})
                treatment = treatments.get(ref)
                if treatment is None:
                    warnings.append({"code": "missing_treatment", "ref": ref})
                elif treatment["level"] and row.get("inherent_level") and treatment["level"].upper() != row["inherent_level"].upper():
                    warnings.append({"code": "treatment_level_conflict", "ref": ref})
                row["treatment_row"] = treatment
                existing = db.execute("SELECT id FROM aims_risks WHERE assessment_id=%s AND lower(ref)=lower(%s)",
                                      (assessment_id, ref)).fetchone()
                if existing:
                    warnings.append({"code": "existing_risk", "ref": ref})
                    row["existing_id"] = existing["id"]
                row["outcome"] = "conflict" if existing else "create"
                row["system_id"] = None
                if row.get("system_ref"):
                    app = _existing_ref(db, row["system_ref"])
                    if app and describe_record(db, ("governance", "application"), app["id"], user):
                        row["system_id"] = app["id"]
                    else:
                        warnings.append({"code": "unknown_system", "ref": ref})
        now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
        batch_id = insert_returning_id(db,
            "INSERT INTO register_import_batches (org_id,business_unit_id,kind,assessment_id,file_name,file_sha256,"
            "profile_version,rows,warnings,created_by,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (user["org_id"], unit, kind, assessment_id, filename[:200], hashlib.sha256(data).hexdigest(),
             PROFILE_VERSION, json.dumps(rows), json.dumps(warnings), user["id"], now))
        return {"batch_id": batch_id, "version": 1, "kind": kind, "rows": rows, "warnings": warnings,
                "file_sha256": hashlib.sha256(data).hexdigest(), "created_at": now, "audit": []}
    finally:
        wb.close()


def confirm(db, user, batch_id, *, version, acknowledged, selected=None):
    if type(batch_id) is not int or type(version) is not int:
        raise ServiceError(422, "Choose a preview and its current version.")
    batch = db.execute("SELECT * FROM register_import_batches WHERE id=%s", (batch_id,)).fetchone()
    if not batch or batch["org_id"] != user.get("org_id") or batch["created_by"] != user.get("id"):
        raise ServiceError(404, "Preview not found.")
    _require(user, batch["kind"])
    if batch["status"] != "previewed" or batch["version"] != version:
        raise ServiceError(409, "The preview is no longer current.")
    if utcnow() - __import__("datetime").datetime.strptime(str(batch["created_at"])[:19], "%Y-%m-%d %H:%M:%S") > timedelta(days=7):
        raise ServiceError(409, "The preview expired. Upload the workbook again.")
    current_unit = _check_unit(db, user, batch["business_unit_id"])
    if current_unit != batch["business_unit_id"]:
        raise ServiceError(403, "The preview's business-unit scope is no longer available.")
    if batch["kind"] == "ai_risks" and not describe_record(db, ("orm", "aims"), batch["assessment_id"], user):
        raise ServiceError(404, "Assessment not found.")
    warnings = json.loads(batch["warnings"])
    keys = {f"{w['code']}:{w.get('ref','')}" for w in warnings}
    if not isinstance(acknowledged, list) or set(acknowledged) != keys:
        raise ServiceError(422, "Review and acknowledge every workbook discrepancy before confirming.")
    rows = json.loads(batch["rows"])
    if selected is not None and (not isinstance(selected, list) or
                                 any(not isinstance(value, str) for value in selected)):
        raise ServiceError(422, "Choose a list of workbook references.")
    selection = set(selected if selected is not None else
                    [r["external_ref" if batch["kind"] == "ai_systems" else "ref"] for r in rows])
    if not selection.issubset({r["external_ref" if batch["kind"] == "ai_systems" else "ref"] for r in rows}):
        raise ServiceError(422, "A selected reference is not in the preview.")
    created = []
    for row in rows:
        ref = row["external_ref" if batch["kind"] == "ai_systems" else "ref"]
        if ref not in selection:
            continue
        if row["outcome"] != "create":
            raise ServiceError(409, "Existing records need explicit matching in their owning module.")
        if batch["kind"] == "ai_systems":
            if _existing_ref(db, ref):
                raise ServiceError(409, "This reference cannot be imported. Review your register mapping.")
            app_id = insert_returning_id(db,
                "INSERT INTO applications (name,description,application_type,business_unit_id,is_active) "
                "VALUES (%s,%s,'AI system',%s,1)", (row["name"], row["purpose"], batch["business_unit_id"]))
            db.execute("INSERT INTO ai_use_profiles (application_id,purpose,capability_type,provider_note,intended_users,"
                       "data_categories,external_ref,import_review_state,import_claimed_status,import_batch_id,"
                       "source_claims_json,created_by,updated_by) "
                       "VALUES (%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s,%s)",
                       (app_id, row["purpose"], row.get("category"), row.get("vendor"), row.get("scope"),
                        json.dumps([]), ref, row.get("claimed_status"), batch_id,
                        json.dumps({k: row.get(k) for k in SYSTEM_FIELDS}, ensure_ascii=False),
                        user["id"], user["id"]))
            created.append({"ref": ref, "id": app_id})
        else:
            existing = db.execute("SELECT id FROM aims_risks WHERE assessment_id=%s AND lower(ref)=lower(%s)",
                                  (batch["assessment_id"], ref)).fetchone()
            if existing:
                raise ServiceError(409, "A risk reference was added after this preview. Upload again.")
            risk_id = insert_returning_id(db,
                "INSERT INTO aims_risks (assessment_id,ref,risk_description,likelihood,impact,risk_owner,"
                "contributing_factors,status,import_batch_id,source_claims_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s)",
                (batch["assessment_id"], ref, row["description"], int(row["likelihood"]), int(row["impact"]),
                 row.get("owner"), row.get("subcategory"), batch_id,
                 json.dumps({k: row.get(k) for k in RISK_FIELDS}, ensure_ascii=False)))
            if row.get("system_id"):
                if not describe_record(db, ("governance", "application"), row["system_id"], user):
                    raise ServiceError(409, "A linked AI system is no longer accessible.")
                db.execute("INSERT INTO aims_risk_applications (risk_id,application_id,linked_by,linked_at) "
                           "VALUES (%s,%s,%s,%s)", (risk_id, row["system_id"], user["id"], utcnow().isoformat()))
            treatment = row.get("treatment_row")
            if treatment and treatment.get("action"):
                db.execute("INSERT INTO aims_risk_controls (risk_id,treatment,action_steps,responsible,due_date,status) "
                           "VALUES (%s,%s,%s,%s,%s,'open')", (risk_id, (treatment.get("treatment") or "mitigate").lower(),
                           treatment["action"], treatment.get("owner"), treatment.get("target")))
            created.append({"ref": ref, "id": risk_id})
    changed = db.execute("UPDATE register_import_batches SET status='confirmed',version=version+1,confirmed_at=%s "
                         "WHERE id=%s AND version=%s AND status='previewed'",
                         (utcnow().strftime("%Y-%m-%d %H:%M:%S"), batch_id, version)).rowcount
    if changed != 1:
        raise ServiceError(409, "The preview was already confirmed.")
    return {"created": created, "skipped": len(rows)-len(created),
            "audit": [("register_import_confirmed", "register_import", batch_id,
                       f"{batch['kind']}: {len(created)} draft records; {len(warnings)} discrepancies acknowledged")],
            "events": []}
