"""
AI governance: importing the responses of an external form (plans/2026-10-governance-rework/01 section 4).

A specialist brings in the export of the customer's own Google or Microsoft Form. Nothing becomes a request until a person
has looked at a preview and confirmed it:

* preview reads the file (see `import_rules`), keeps the processed rows in a batch, and says for every response what would
  happen: a new request, the same response again (nothing happens), a correction of an earlier response (a new revision
  with its differences), or an error. It also lists the people the owner might be and the applications it might already be.
* confirm creates one draft request per response in the existing intake lifecycle. The importing specialist is the author
  of record; the requester's name, contact and organization are facts of their own. An owner is a person the specialist
  confirmed, or an explicit gap; the import never invents one.
* the same response imported twice creates nothing the second time, and a correction never edits an earlier request: it is a
  new revision, and an earlier request that nobody has decided on is marked superseded.

Like the rest of the service layer, every function takes the caller's connection and user, checks capability and unit
scope itself, never commits, and returns the audit entries the route handles once it has committed.
"""
import hashlib
import json
import logging
from datetime import timedelta

from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance import import_rules as ir
from modules.ai_governance import service
from modules.ai_governance.service import ServiceError
from modules.governance.data_service import bu_scope_ids

log = logging.getLogger("oneforall.ai_governance")

SOURCE_SYSTEMS = {"google_forms": "Google Forms", "microsoft_forms": "Microsoft Forms", "other": "Another form tool"}
PREVIEW_KEEP_DAYS = 7
OUTCOMES = ("new", "duplicate", "revision", "error", "replaced_in_file")
CREATES = ("new", "revision")
_UNDECIDED = ("draft", "returned", "submitted")


def guide() -> dict:
    return {"version": ir.GUIDE_VERSION, "questions": list(ir.FIELD_GUIDE), "required": list(ir.REQUIRED_TARGETS),
            "limits": {"file_bytes": ir.MAX_FILE_BYTES, "rows": ir.MAX_ROWS, "columns": ir.MAX_COLUMNS, "cell": ir.MAX_CELL},
            "source_systems": SOURCE_SYSTEMS, "date_orders": list(ir.DATE_ORDERS)}


def _load(db, user, batch_id):
    service._require(user, "ai_use.review")
    row = db.execute("SELECT * FROM ai_import_batches WHERE id = %s", (batch_id,)).fetchone()
    if row is None or not service._same_org(user, row["org_id"]) or not service._in_scope(user, row["business_unit_id"]):
        raise ServiceError(404, "Import not found.")
    return row


def _present(row, *, with_rows=True) -> dict:
    rows = json.loads(row["rows"] or "[]") if with_rows else []
    counts = json.loads(row["counts"] or "{}")
    return {"id": row["id"], "status": row["status"], "version": row["version"], "source_system": row["source_system"],
            "source_label": SOURCE_SYSTEMS.get(row["source_system"], row["source_system"]), "form_name": row["form_name"],
            "export_date": row["export_date"], "date_order": row["date_order"], "file_name": row["file_name"],
            "file_kind": row["file_kind"], "file_sha256": row["file_sha256"], "row_count": row["row_count"],
            "business_unit_id": row["business_unit_id"], "mapping": json.loads(row["mapping"] or "{}"),
            "mapping_version": row["mapping_version"], "counts": counts, "rows": rows,
            "imported_by": row["imported_by"], "created_at": service._text(row["created_at"]),
            "confirmed_at": service._text(row["confirmed_at"])}


def _headers(batch) -> list:
    return json.loads(batch["headers"] or "[]")


# ── People and applications a response might refer to ───────────────────────

def owner_candidates(db, user, hint) -> list:
    """People of the organization a response's "owner" answer might mean: an exact email, else an exact name. They are
    candidates for a person to confirm, never an assignment."""
    hint = (hint or "").strip()
    if not hint:
        return []
    sql = ("SELECT id, full_name, email FROM users WHERE is_active = 1 AND deleted_at IS NULL "
           "AND (LOWER(email) = LOWER(%s) OR LOWER(full_name) = LOWER(%s))")
    params = [hint, hint]
    if user.get("org_id") is not None:
        sql, params = sql + " AND org_id = %s", [*params, user["org_id"]]
    rows = db.execute(sql + " ORDER BY full_name LIMIT 5", params).fetchall()
    return [{"id": r["id"], "name": r["full_name"], "email": r["email"],
             "by": "email" if (r["email"] or "").lower() == hint.lower() else "name"} for r in rows]


def _existing_by_key(db, user, key):
    if not key:
        return None
    sql = "SELECT * FROM ai_use_intake_requests WHERE source_key = %s"
    params = [key]
    if user.get("org_id") is not None:
        sql, params = sql + " AND org_id = %s", [*params, user["org_id"]]
    return db.execute(sql + " ORDER BY revision DESC, id DESC LIMIT 1", params).fetchone()


# ── Preview ─────────────────────────────────────────────────────────────────

def _text_field(value, what, limit, required=True) -> "str | None":
    value = (value or "").strip() if isinstance(value, str) or value is None else None
    if value is None:
        raise ServiceError(422, "Some details need fixing.", errors={what: f"The {what.replace('_', ' ')} must be text."})
    if required and not value:
        raise ServiceError(422, "Some details need fixing.", errors={what: f"Say the {what.replace('_', ' ')}."})
    if len(value) > limit:
        raise ServiceError(422, "Some details need fixing.", errors={what: f"Keep it to {limit} characters or fewer."})
    return value or None


def preview(db, user, *, data, filename, source_system, form_name, export_date=None, mapping=None, date_order="iso",
            business_unit_id=None) -> dict:
    """Read an export and keep the processed rows as a batch awaiting confirmation. Nothing becomes a request."""
    service._require(user, "ai_use.review")
    if source_system not in SOURCE_SYSTEMS:
        raise ServiceError(422, "Some details need fixing.", errors={"source_system": "Choose where the form was made."})
    form_name = _text_field(form_name, "form_name", 120)
    export_date = _text_field(export_date, "export_date", 10, required=False)
    if export_date and ir.norm_date(export_date, "iso") != (export_date, True):
        raise ServiceError(422, "Some details need fixing.", errors={"export_date": "Write the export date as YYYY-MM-DD."})
    if date_order not in ir.DATE_ORDERS:
        raise ServiceError(422, "Some details need fixing.", errors={"date_order": "Choose how dates are written in the export."})
    unit = service._check_unit(db, user, business_unit_id)
    try:
        table = ir.read_table(data, filename or "")
    except ir.ImportRuleError as exc:
        raise ServiceError(422, str(exc), errors={"file": str(exc)})
    headers = table["headers"]
    chosen = mapping if mapping is not None else ir.suggest_mapping(headers)
    problems = ir.validate_mapping(chosen, headers)
    if problems:
        raise ServiceError(422, "The columns need to be matched to the questions.", errors={"mapping": " ".join(problems)},
                           mapping=chosen, headers=headers)
    chosen = {h: (chosen.get(h) or "") for h in headers}

    processed = [ir.process_row(headers, r, chosen, date_order=date_order) for r in table["rows"]]
    last_with_key, keys = {}, []
    for index, r in enumerate(processed):
        key = ir.correlation_key(user.get("org_id"), form_name, r["response_id"], r["requester"].get("email"), r["answers"].get("name"))
        keys.append(key)
        if key and r["importable"]:
            last_with_key[key] = index
    out_rows, counts = [], {k: 0 for k in OUTCOMES}
    for index, r in enumerate(processed):
        key = keys[index]
        outcome, existing_id, diff, prior = "new", None, [], None
        if not r["importable"]:
            outcome = "error"
        elif key and last_with_key.get(key) != index:
            outcome = "replaced_in_file"
        else:
            existing = _existing_by_key(db, user, key)
            if existing is not None:
                old_answers = json.loads(existing["payload"] or "{}")
                old_requester = json.loads(existing["requester"] or "{}")
                existing_id, prior = existing["id"], existing["status"]
                if existing["source_fingerprint"] == r["fingerprint"]:
                    outcome = "duplicate"
                else:
                    outcome = "revision"
                    diff = ir.diff_answers(old_answers, r["answers"]) + ir.diff_requester(old_requester, r["requester"])
        counts[outcome] += 1
        candidates = owner_candidates(db, user, r["owner_hint"]) if outcome in CREATES else []
        matches = []
        if outcome in CREATES and r["answers"].get("name"):
            try:
                matches = service.find_duplicates(db, user, r["answers"]["name"], r["answers"].get("provider_name"))
            except Exception:
                log.warning("AI governance import: similar applications could not be read", exc_info=True)
        out_rows.append({
            "row_number": r["row_number"], "outcome": outcome, "answers": r["answers"], "requester": r["requester"],
            "owner_hint": r["owner_hint"], "owner_candidates": candidates, "matches": matches, "issues": r["issues"],
            "missing": r["missing"], "unmapped": r["unmapped"], "fingerprint": r["fingerprint"], "source_key": key,
            "existing_id": existing_id, "prior_status": prior, "diff": diff})

    cutoff = (utcnow() - timedelta(days=PREVIEW_KEEP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("DELETE FROM ai_import_batches WHERE status = 'previewed' AND created_at < %s", (cutoff,))
    sha = hashlib.sha256(bytes(data)).hexdigest()
    db.execute("UPDATE ai_import_batches SET status = 'discarded', rows = '[]', version = version + 1 "
               "WHERE status = 'previewed' AND imported_by = %s AND file_sha256 = %s", (user["id"], sha))
    now = service._now()
    batch_id = insert_returning_id(
        db,
        "INSERT INTO ai_import_batches (org_id, business_unit_id, source_system, form_name, export_date, mapping, "
        "mapping_version, date_order, file_name, file_sha256, file_kind, row_count, headers, status, rows, counts, "
        "imported_by, version, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'previewed', %s, %s, %s, 1, %s)",
        (user.get("org_id"), unit, source_system, form_name, export_date, json.dumps(chosen), ir.GUIDE_VERSION, date_order,
         (filename or "")[:200] or None, sha, table["kind"], len(processed), json.dumps(headers), json.dumps(out_rows),
         json.dumps(counts), user["id"], now))
    return {"batch": _present(db.execute("SELECT * FROM ai_import_batches WHERE id = %s", (batch_id,)).fetchone()),
            "headers": headers, "encoding": table.get("encoding"),
            "audit": [("ai_import_previewed", "ai_import", batch_id, f"{len(processed)} responses read from {table['kind']}")],
            "events": []}


def get_batch(db, user, batch_id: int) -> dict:
    row = _load(db, user, batch_id)
    return {"batch": _present(row), "headers": _headers(row)}


def list_batches(db, user, limit=50) -> dict:
    service._require(user, "ai_use.review")
    sql, params = "SELECT * FROM ai_import_batches WHERE 1 = 1", []
    if user.get("org_id") is not None:
        sql, params = sql + " AND org_id = %s", [user["org_id"]]
    scope = bu_scope_ids(user)
    if scope is not None:
        sql += f" AND (business_unit_id IS NULL OR business_unit_id IN ({','.join(['%s'] * len(scope))}))"
        params += list(scope)
    rows = db.execute(sql + " ORDER BY id DESC LIMIT %s", [*params, max(1, min(int(limit), 100))]).fetchall()
    return {"batches": [_present(r, with_rows=False) for r in rows]}


# ── Confirm and discard ─────────────────────────────────────────────────────

def discard(db, user, batch_id: int, expected_version) -> dict:
    row = _load(db, user, batch_id)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the import you are discarding.")
    if row["status"] != "previewed":
        raise ServiceError(409, "Only an import waiting for confirmation can be discarded.", status_now=row["status"])
    moved = db.execute("UPDATE ai_import_batches SET status = 'discarded', rows = '[]', version = version + 1 "
                       "WHERE id = %s AND status = 'previewed' AND version = %s", (batch_id, expected_version)).rowcount
    if moved != 1:
        raise ServiceError(409, "This import was changed by someone else. Reload it and try again.")
    return {"batch": _present(db.execute("SELECT * FROM ai_import_batches WHERE id = %s", (batch_id,)).fetchone(), with_rows=False),
            "audit": [("ai_import_discarded", "ai_import", batch_id, "discarded before confirmation")], "events": []}


def confirm(db, user, batch_id: int, expected_version, rows=None) -> dict:
    """Create the requests of a previewed batch. `rows` maps a row number to {"include": bool, "owner_user_id": int|None}; a
    response not mentioned is included with its owner left open. Responses that were duplicates or errors create nothing."""
    row = _load(db, user, batch_id)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the import you are confirming.")
    if row["status"] == "confirmed":
        return {"batch": _present(row, with_rows=False), "created": [], "already": True, "audit": [], "events": []}
    if row["status"] != "previewed":
        raise ServiceError(409, "Only an import waiting for confirmation can be confirmed.", status_now=row["status"])
    if rows is not None and not isinstance(rows, dict):
        raise ServiceError(400, "Send the choices per response as an object.")
    claimed = db.execute("UPDATE ai_import_batches SET status = 'confirming', version = version + 1 "
                         "WHERE id = %s AND status = 'previewed' AND version = %s", (batch_id, expected_version)).rowcount
    if claimed != 1:
        current = db.execute("SELECT * FROM ai_import_batches WHERE id = %s", (batch_id,)).fetchone()
        if current and current["status"] == "confirmed":
            return {"batch": _present(current, with_rows=False), "created": [], "already": True, "audit": [], "events": []}
        raise ServiceError(409, "This import was changed by someone else. Reload it and try again.")

    unit = row["business_unit_id"]
    stored = json.loads(row["rows"] or "[]")
    choices = rows or {}
    created, audit, kept = [], [], []
    summary = {"created": 0, "revised": 0, "skipped": 0, "duplicates": 0}
    for item in stored:
        pick = choices.get(str(item["row_number"])) or {}
        if item["outcome"] not in CREATES:
            summary["duplicates" if item["outcome"] == "duplicate" else "skipped"] += 1
            kept.append({**item, "result": None, "unmapped": {}})
            continue
        if pick.get("include") is False:
            summary["skipped"] += 1
            kept.append({**item, "result": "left out", "unmapped": {}})
            continue
        owner_id = pick.get("owner_user_id")
        if owner_id is not None:
            if isinstance(owner_id, bool) or not isinstance(owner_id, int):
                raise ServiceError(422, "Choose the owner from the people offered.", errors={f"row_{item['row_number']}": "Choose an owner or leave it open."})
            service._check_owner(db, user, owner_id)
        # The response may have been imported by someone else since the preview: never create the same thing twice.
        latest = _existing_by_key(db, user, item["source_key"])
        if latest is not None and latest["source_fingerprint"] == item["fingerprint"]:
            summary["duplicates"] += 1
            kept.append({**item, "outcome": "duplicate", "existing_id": latest["id"], "result": None, "unmapped": {}})
            continue
        revision = (latest["revision"] + 1) if latest is not None else 1
        answers = dict(item["answers"])
        answers["owner_user_id"] = owner_id
        answers["business_unit_id"] = unit
        requester = dict(item["requester"])
        requester["source_form"] = row["form_name"]
        requester["source_system"] = row["source_system"]
        if item.get("owner_hint"):
            requester["owner_named_in_form"] = item["owner_hint"]
        intake_id = service.create_imported_draft(
            db, user, answers, requester=requester, batch_id=batch_id, source_key=item["source_key"],
            fingerprint=item["fingerprint"], revision=revision, supersedes_id=latest["id"] if latest is not None else None,
            unit=unit)
        if intake_id is None:  # the same response was imported at the same moment: the first one stands, this creates nothing
            winner = _existing_by_key(db, user, item["source_key"])
            summary["duplicates"] += 1
            kept.append({**item, "outcome": "duplicate", "existing_id": winner["id"] if winner else None, "result": None, "unmapped": {}})
            continue
        detail = f"imported from {row['form_name']} (row {item['row_number']}"
        detail += f", revision {revision})" if revision > 1 else ")"
        audit.append(("ai_use_draft_created", "ai_use_intake", intake_id, detail))
        summary["revised" if latest is not None else "created"] += 1
        if latest is not None and latest["status"] in _UNDECIDED:
            done = db.execute(
                "UPDATE ai_use_intake_requests SET status = 'superseded', review_note = %s, version = version + 1, updated_at = %s "
                "WHERE id = %s AND status IN ('draft', 'returned', 'submitted')",
                (f"Replaced by revision {revision} from an import.", service._now(), latest["id"])).rowcount
            if done:
                audit.append(("ai_use_superseded", "ai_use_intake", latest["id"], f"replaced by request {intake_id}"))
        created.append({"row_number": item["row_number"], "intake_id": intake_id, "revision": revision,
                        "supersedes_id": latest["id"] if latest is not None else None, "owner_user_id": owner_id,
                        "name": answers.get("name")})
        kept.append({**item, "result": "created", "intake_id": intake_id, "revision": revision, "unmapped": {}})
    counts = json.loads(row["counts"] or "{}")
    counts.update(summary)
    now = service._now()
    db.execute("UPDATE ai_import_batches SET status = 'confirmed', rows = %s, counts = %s, confirmed_at = %s WHERE id = %s",
               (json.dumps(kept), json.dumps(counts), now, batch_id))
    audit.append(("ai_import_confirmed", "ai_import", batch_id,
                  f"{summary['created']} created, {summary['revised']} revised, {summary['duplicates']} already imported, "
                  f"{summary['skipped']} left out"))
    final = db.execute("SELECT * FROM ai_import_batches WHERE id = %s", (batch_id,)).fetchone()
    return {"batch": _present(final, with_rows=False), "created": created, "summary": summary, "audit": audit, "events": []}
