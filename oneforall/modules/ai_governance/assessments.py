"""
AI governance G3b: the AI impact assessment (AIIA), moved here from Sentinel.

Same tables (`sentinel_aiia`, `sentinel_aiia_impacts`, `sentinel_aiia_dimensions`), same reference numbers and same link
identity as before: those are keys inside saved links and audit rows, so they stay. What moved is the owner of the screens
and of this service (plans/ai-governance/06-aiia-in-ai-governance.md), and what it now guarantees:

* a new assessment is filed in a unit (the system's, else the author's), never silently organization wide;
* the system, the business unit and the privacy records it names are ones its writer may open, and a privacy record the
  reader may not open is not named;
* an update carries the version it was based on and a stale one is refused;
* every change is audited, completing one raises one event, and an approved one is not deleted.

Like the rest of the service layer, every function takes the caller's connection and user, checks the capability and the
unit scope itself, never commits, and returns the audit entries and events the route handles once it has committed.
"""
import json
import re
import secrets
import string

from core import events
from core.rbac import has_capability
from core.sql_like import ci_like, like_pattern
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance import service
from modules.ai_governance.service import APP, ServiceError
from modules.governance.entity_scope import describe_record, entity_scope_sql, record_unit
from modules.sentinel.record_profiles import get_profile

KIND = ("sentinel", "aiia")
_ROPA, _DPIA = ("sentinel", "ropa"), ("sentinel", "dpia")

STATUSES = ("draft", "in_progress", "completed", "approved")
DONE = ("completed", "approved")
AUTONOMY = ("decision_support", "human_in_loop", "automated")
DEPLOYMENT_ENV = ("on_prem", "cloud", "hybrid")
RESIDUAL = ("very_low", "low", "moderate", "high", "critical")
PAGE_MAX = 100
DIMENSIONS_MAX = 50

_SHORT, _LONG = 200, 4000
_TEXT_LIMITS = {"title": _SHORT, "ai_system_name": _SHORT, "department": _SHORT, "owner": _SHORT, "business_process": 500,
                "system_description": _LONG, "third_party_details": 2000, "outputs_decisions": 2000,
                "stakeholders_direct": 2000, "stakeholders_indirect": 2000, "mitigation_measures": _LONG}
_CHOICES = {"deployment_env": DEPLOYMENT_ENV, "autonomy_level": AUTONOMY, "residual_classification": RESIDUAL,
            "status": STATUSES}
_BOOLS = ("third_party", "influences_customers", "sensitive_data")
_REFS = ("application_id", "ropa_id", "dpia_id", "business_unit_id")
_FIELDS = (*_TEXT_LIMITS, *_CHOICES, *_BOOLS, "data_categories", *_REFS)
_LABELS = {"ai_system_name": "AI system name", "outputs_decisions": "outputs and decisions",
           "third_party": "third-party AI", "influences_customers": "customer influence", "sensitive_data": "sensitive data",
           "data_categories": "data categories", "deployment_env": "deployment environment", "autonomy_level": "autonomy level",
           "residual_classification": "residual classification", "system_description": "system description",
           "business_process": "business process", "third_party_details": "third-party details",
           "stakeholders_direct": "direct stakeholders", "stakeholders_indirect": "indirect stakeholders",
           "mitigation_measures": "mitigation measures", "application_id": "AI system", "ropa_id": "RoPA",
           "dpia_id": "DPIA", "business_unit_id": "business unit"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_CLASSIFICATION = re.compile(r"[A-Za-z0-9_ -]{1,40}")
_PRIVACY = {"ropa": (_ROPA, "sentinel_ropa", "processing_name"), "dpia": (_DPIA, "sentinel_dpias", "title")}


def _label(field) -> str:
    return _LABELS.get(field, field.replace("_", " "))


def _now() -> str:
    return service._now()


def _int(value):
    """An integer given as a number or as digits (a form sends numbers as text); None for anything else, booleans included."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit() and len(value.strip()) <= 9:
        return int(value.strip())
    return None


def _can(user) -> dict:
    return {"manage": has_capability(user, "ai_assessment.manage"), "configure": has_capability(user, "ai_assessment.configure")}


# ── Cleaning what a form sends ──────────────────────────────────────────────

def _clean_impacts(db, raw, allowed_extra=()):
    """([normalized rows], error sentence or None). A dimension must exist (or already be on this assessment)."""
    if not isinstance(raw, list):
        return [], "Send the impacts as a list."
    known = {r["name"] for r in db.execute("SELECT name FROM sentinel_aiia_dimensions").fetchall()} | set(allowed_extra)
    rows, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            return [], "Each impact must be an object."
        name = _CONTROL.sub("", item.get("dimension_name") if isinstance(item.get("dimension_name"), str) else "").strip()
        if not name:
            continue
        if name not in known:
            return [], f"Unknown impact dimension: {name[:60]}."
        if name in seen:
            return [], f"The dimension {name[:60]} is given twice."
        seen.add(name)
        scores = []
        for field in ("likelihood", "impact"):
            value = item.get(field)
            if value in (None, ""):
                scores.append(None)
                continue
            number = _int(value)
            if number is None or not 1 <= number <= 5:
                return [], f"The {field} of {name[:60]} must be a whole number from 1 to 5."
            scores.append(number)
        description = item.get("description")
        description = _CONTROL.sub("", description).strip()[:1000] if isinstance(description, str) else None
        rows.append({"dimension_name": name, "applicable": 0 if item.get("applicable") in (False, 0, "0") else 1,
                     "description": description or None, "likelihood": scores[0], "impact": scores[1]})
    return rows, None


def _clean(db, raw, *, creating, existing_impacts=()):
    """(fields, impacts or None, errors). `fields` holds only fields that were sent, normalized."""
    if not isinstance(raw, dict):
        raise ServiceError(422, "Send the assessment as an object.", errors={"_": "Send the assessment as an object."})
    fields, errors, impacts = {}, {}, None
    for field in _FIELDS:
        if field not in raw:
            continue
        value = raw[field]
        if field in _TEXT_LIMITS:
            if value is None:
                fields[field] = None
            elif not isinstance(value, str):
                errors[field] = f"The {_label(field)} must be text."
            else:
                value = _CONTROL.sub("", value).strip()
                if len(value) > _TEXT_LIMITS[field]:
                    errors[field] = f"The {_label(field)} is too long (at most {_TEXT_LIMITS[field]} characters)."
                else:
                    fields[field] = value or None
        elif field in _CHOICES:
            if value in (None, "") and field != "status":
                fields[field] = None
            elif value not in _CHOICES[field]:
                errors[field] = f"Unknown choice for the {_label(field)}."
            else:
                fields[field] = value
        elif field in _BOOLS:
            if value in (True, 1):
                fields[field] = 1
            elif value in (False, 0, None):
                fields[field] = 0
            else:
                errors[field] = f"The {_label(field)} must be yes or no."
        elif field == "data_categories":
            if value is None:
                fields[field] = []
            elif (not isinstance(value, list) or len(value) > 20
                  or not all(isinstance(v, str) and 0 < len(v.strip()) <= 50 for v in value)):
                errors[field] = f"The {_label(field)} must be a short list of choices."
            else:
                fields[field] = list(dict.fromkeys(v.strip() for v in value))
        else:  # a reference: checked against what the writer may open by the caller
            if value in (None, ""):
                fields[field] = None
            else:
                number = _int(value)
                if number is None:
                    errors[field] = f"Choose the {_label(field)} from the list."
                else:
                    fields[field] = number
    if creating and not fields.get("title"):
        errors["title"] = "Give the assessment a title."
    if "impacts" in raw and raw["impacts"] is not None:
        impacts, problem = _clean_impacts(db, raw["impacts"], existing_impacts)
        if problem:
            errors["impacts"] = problem
    if errors:
        raise ServiceError(422, "Some answers need fixing.", errors=errors)
    return fields, impacts


def _check_references(db, user, fields) -> None:
    """Everything the assessment points at is something the writer may open, or the change is refused."""
    for field, key in (("application_id", APP), ("ropa_id", _ROPA), ("dpia_id", _DPIA)):
        if fields.get(field) is not None and not describe_record(db, key, fields[field], user):
            what = "an AI system" if field == "application_id" else "a privacy record"
            raise ServiceError(400, f"Choose {what} you can open.")
    unit = fields.get("business_unit_id")
    if unit is not None:
        service._check_unit(db, user, unit)


# ── Reading ─────────────────────────────────────────────────────────────────

def _classification(db, rows):
    """The band of the highest likelihood x impact among applicable, scored rows. "unrated" when no rating framework is
    active (never a band the person did not choose); None when nothing is scored yet."""
    from modules.erm.data_service import get_active_framework_matrix, resolve_band
    matrix = get_active_framework_matrix(db)
    if not matrix["matrix"]:
        return "unrated"
    best, best_product = None, -1
    for row in rows:
        if not row["applicable"] or row["likelihood"] is None or row["impact"] is None:
            continue
        product = int(row["likelihood"]) * int(row["impact"])
        if product > best_product:
            best, best_product = (int(row["likelihood"]), int(row["impact"])), product
    return None if best is None else resolve_band(matrix, best[0], best[1])


def _impact(row, active) -> dict:
    return {"dimension_name": row["dimension_name"], "applicable": bool(row["applicable"]), "description": row["description"],
            "likelihood": row["likelihood"], "impact": row["impact"], "active": active}


def _impacts(db, assessment_id) -> list:
    """One row per active dimension (an unscored placeholder when it has none), then scored rows of dimensions that are no
    longer active: history survives a deactivation or a rename."""
    dims = db.execute("SELECT name, is_active FROM sentinel_aiia_dimensions ORDER BY order_idx, name").fetchall()
    existing = {r["dimension_name"]: r for r in db.execute(
        "SELECT dimension_name, applicable, description, likelihood, impact FROM sentinel_aiia_impacts WHERE aiia_id = %s ORDER BY id",
        (assessment_id,)).fetchall()}
    rows = []
    for dim in dims:
        if not dim["is_active"]:
            continue
        if dim["name"] in existing:
            rows.append(_impact(existing.pop(dim["name"]), True))
        else:
            rows.append({"dimension_name": dim["name"], "applicable": True, "description": None, "likelihood": None,
                         "impact": None, "active": True})
    rows.extend(_impact(r, False) for r in existing.values())
    return rows


def _json_list(raw) -> list:
    return [v for v in service._json_list(raw) if isinstance(v, str)]


def _privacy_record(db, user, kind, record_id):
    """None when nothing is linked; {"restricted": True} when it is linked to something the reader may not open."""
    if record_id is None:
        return None
    key, table, _ = _PRIVACY[kind]
    shown = describe_record(db, key, record_id, user)
    if not shown:
        return {"restricted": True}
    ref = db.execute(f"SELECT ref_number FROM {table} WHERE id = %s", (record_id,)).fetchone()
    return {"id": record_id, "ref": ref[0] if ref else None, "title": shown["title"], "url": shown["url"]}


def _system(db, user, application_id):
    if application_id is None:
        return None
    shown = describe_record(db, APP, application_id, user)
    if not shown:
        return {"restricted": True}
    return {"id": application_id, "name": shown["title"], "url": shown["url"]}


def _full(db, user, row) -> dict:
    out = {k: row[k] for k in ("id", "ref_number", "title", "ai_system_name", "application_id", "department", "owner",
                               "system_description", "business_process", "deployment_env", "third_party_details",
                               "outputs_decisions", "autonomy_level", "stakeholders_direct", "stakeholders_indirect",
                               "overall_classification", "mitigation_measures", "residual_classification", "status",
                               "ropa_id", "dpia_id", "business_unit_id", "created_by", "version")}
    for flag in _BOOLS:
        out[flag] = bool(row[flag])
    expanded = get_profile("aiia").expand(dict(row))
    for key in get_profile("aiia").detail_keys():
        out[key] = expanded.get(key)
    made, needed = get_profile("aiia").completeness({**dict(row), **expanded})
    out["readiness"] = {"made": made, "needed": needed,
                        "gaps": [gap.label for gap in get_profile("aiia").gaps({**dict(row), **expanded})]}
    out["data_categories"] = _json_list(row["data_categories"])
    out["created_at"], out["updated_at"] = service._text(row["created_at"]), service._text(row["updated_at"])
    unit = db.execute("SELECT name FROM business_units WHERE id = %s", (row["business_unit_id"],)).fetchone() \
        if row["business_unit_id"] is not None else None
    out["business_unit"] = unit[0] if unit else None
    out["impacts"] = _impacts(db, row["id"])
    out["application"] = _system(db, user, row["application_id"])
    out["ropa"] = _privacy_record(db, user, "ropa", row["ropa_id"])
    out["dpia"] = _privacy_record(db, user, "dpia", row["dpia_id"])
    for field, record in (("application_id", "application"), ("ropa_id", "ropa"), ("dpia_id", "dpia")):
        if out[record] and out[record].get("restricted"):
            out[field] = None
    out["can"] = _can(user)
    return out


def _row(db, user, assessment_id):
    """The assessment row when the reader may open it, else None (hidden is the same as missing)."""
    scope, params = entity_scope_sql(KIND, user, "t")
    return db.execute(f"SELECT t.* FROM sentinel_aiia t WHERE t.id = %s AND {scope}", [assessment_id, *params]).fetchone()


def get_assessment(db, user, assessment_id: int) -> "dict | None":
    service._require(user, "ai_assessment.view")
    row = _row(db, user, assessment_id)
    return _full(db, user, row) if row else None


def list_assessments(db, user, *, q=None, status=None, application_id=None, linked=None, classification=None,
                     page=1, page_size=25) -> dict:
    service._require(user, "ai_assessment.view")
    if status not in (None, "") and status not in STATUSES:
        raise ServiceError(400, "Unknown status filter.")
    if linked not in (None, "", "any", "none"):
        raise ServiceError(400, "Unknown linked filter.")
    if classification not in (None, "") and not _CLASSIFICATION.fullmatch(str(classification)):
        raise ServiceError(400, "Unknown classification filter.")
    page = _int(page)
    if page is None or page < 1:
        page = 1
    size = 25 if page_size is None else _int(page_size)
    if size is None or not 1 <= size <= PAGE_MAX:
        raise ServiceError(400, f"The page size must be 1 to {PAGE_MAX}.")

    app_scope, app_params = entity_scope_sql(APP, user, "ap")
    scope, scope_params = entity_scope_sql(KIND, user, "t")
    where, params = [scope], list(scope_params)
    if q:
        where.append(f"({ci_like('t.title')} OR {ci_like('t.ai_system_name')} OR {ci_like('t.ref_number')})")
        params += [like_pattern(q)] * 3
    if status:
        where.append("t.status = %s")
        params.append(status)
    if application_id not in (None, ""):
        number = _int(application_id)
        if number is None:
            raise ServiceError(400, "Unknown system filter.")
        where.append("t.application_id = %s")
        params.append(number)
    if linked == "any":
        where.append("t.application_id IS NOT NULL")
    elif linked == "none":
        where.append("t.application_id IS NULL")
    if classification:
        where.append("t.overall_classification = %s")
        params.append(classification)
    clause = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) FROM sentinel_aiia t WHERE {clause}", params).fetchone()[0]
    rows = db.execute(
        "SELECT t.id, t.ref_number, t.title, t.ai_system_name, t.application_id, t.status, t.overall_classification, "
        "t.residual_classification, t.autonomy_level, t.business_unit_id, t.updated_at, t.version, "
        "bu.name AS bu_name, ap.name AS app_name FROM sentinel_aiia t "
        "LEFT JOIN business_units bu ON bu.id = t.business_unit_id "
        f"LEFT JOIN applications ap ON ap.id = t.application_id AND {app_scope} "
        f"WHERE {clause} ORDER BY t.updated_at DESC, t.id DESC LIMIT %s OFFSET %s",
        [*app_params, *params, size, (page - 1) * size]).fetchall()
    items = []
    for r in rows:
        if r["application_id"] is None:
            system = None
        elif r["app_name"] is None:
            system = {"restricted": True}
        else:
            system = {"id": r["application_id"], "name": r["app_name"], "url": f"/ai-governance/systems/{r['application_id']}"}
        items.append({
            "id": r["id"], "ref_number": r["ref_number"], "title": r["title"], "ai_system_name": r["ai_system_name"],
            "application_id": None if system and system.get("restricted") else r["application_id"],
            "application": system, "status": r["status"],
            "overall_classification": r["overall_classification"], "residual_classification": r["residual_classification"],
            "autonomy_level": r["autonomy_level"], "business_unit": r["bu_name"], "version": r["version"],
            "updated_at": service._text(r["updated_at"]), "url": f"/ai-governance/assessments/{r['id']}"})
    return {"items": items, "total": total, "page": page, "page_size": size, "pages": max(1, -(-total // size)),
            "can": _can(user)}


# ── Writing ─────────────────────────────────────────────────────────────────

def _new_ref(db) -> str:
    day = utcnow().strftime("%Y%m%d")
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(8):
        ref = f"AIIA-{day}-" + "".join(secrets.choice(alphabet) for _ in range(5))
        if not db.execute("SELECT 1 FROM sentinel_aiia WHERE ref_number = %s", (ref,)).fetchone():
            return ref
    raise ServiceError(503, "Could not make a reference number. Try again.")


def _store_impacts(db, assessment_id, rows) -> None:
    db.execute("DELETE FROM sentinel_aiia_impacts WHERE aiia_id = %s", (assessment_id,))
    for r in rows:
        db.execute(
            "INSERT INTO sentinel_aiia_impacts (aiia_id, dimension_name, applicable, description, likelihood, impact) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (assessment_id, r["dimension_name"], r["applicable"], r["description"], r["likelihood"], r["impact"]))


def _completed_event(db, user, assessment_id, application_id, status, version):
    return events.enqueue(
        db, events.AI_ASSESSMENT_COMPLETED, "ai_governance", "ai_assessment", assessment_id,
        {"assessment_id": assessment_id, "application_id": application_id, "status": status},
        user_id=user["id"], org_id=user.get("org_id"), dedup_key=f"ai_assessment.completed:{assessment_id}:{version}")


def create_assessment(db, user, raw) -> dict:
    service._require(user, "ai_assessment.manage")
    fields, impacts = _clean(db, raw, creating=True)
    _, details, errors = get_profile("aiia").prepare(
        {key: raw[key] for key in get_profile("aiia").detail_keys() if key in raw})
    if errors:
        raise ServiceError(422, "Some answers need fixing.", errors=errors)
    _check_references(db, user, fields)
    unit = fields.get("business_unit_id")
    if unit is None and fields.get("application_id") is not None:
        known, app_unit = record_unit(db, "governance", "application", fields["application_id"], user)
        unit = app_unit if known else None
    if unit is None:
        unit = user.get("business_unit_id") or None
    fields["business_unit_id"] = unit
    fields.setdefault("status", "draft")
    fields.setdefault("autonomy_level", None)
    fields["autonomy_level"] = fields["autonomy_level"] or "decision_support"

    now = _now()
    values = {f: fields.get(f) for f in _FIELDS}
    values["data_categories"] = json.dumps(fields.get("data_categories") or [])
    values["details"] = json.dumps(details or {})
    for flag in _BOOLS:
        values[flag] = fields.get(flag, 0)
    values.update(ref_number=_new_ref(db), created_by=user["id"], created_at=now, updated_at=now, version=1,
                  overall_classification=_classification(db, impacts) if impacts is not None else None)
    columns = list(values)
    new_id = insert_returning_id(
        db, f"INSERT INTO sentinel_aiia ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
        [values[c] for c in columns])
    if impacts is not None:
        _store_impacts(db, new_id, impacts)
    out_events = []
    if values["status"] in DONE:
        out_events.append(_completed_event(db, user, new_id, values["application_id"], values["status"], 1))
    row = _row(db, user, new_id)
    return {"assessment": _full(db, user, row), "events": out_events,
            "audit": [("ai_assessment_created", "ai_assessment", new_id, f"{values['ref_number']} {values['title'][:80]}")]}


def _stale(db, assessment_id) -> ServiceError:
    row = db.execute("SELECT version, status FROM sentinel_aiia WHERE id = %s", (assessment_id,)).fetchone()
    return ServiceError(409, "This assessment was changed by someone else. Reload it and try again.",
                        current_version=row["version"] if row else None, status_now=row["status"] if row else None)


def update_assessment(db, user, assessment_id: int, raw, expected_version) -> dict:
    service._require(user, "ai_assessment.manage")
    row = _row(db, user, assessment_id)
    if not row:
        raise ServiceError(404, "Assessment not found.")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version you were editing.")
    existing_names = [r["dimension_name"] for r in db.execute(
        "SELECT dimension_name FROM sentinel_aiia_impacts WHERE aiia_id = %s", (assessment_id,)).fetchall()]
    fields, impacts = _clean(db, raw, creating=False, existing_impacts=existing_names)
    try:
        old_details = json.loads(row["details"] or "{}")
    except (TypeError, ValueError):
        old_details = {}
    if not isinstance(old_details, dict):
        old_details = {}
    _, details, errors = get_profile("aiia").prepare(
        {key: raw[key] for key in get_profile("aiia").detail_keys() if key in raw}, old_details)
    if errors:
        raise ServiceError(422, "Some answers need fixing.", errors=errors)
    if fields.get("title", row["title"]) is None:
        raise ServiceError(422, "Some answers need fixing.", errors={"title": "Give the assessment a title."})
    for field in ("application_id", "ropa_id", "dpia_id"):  # a link already there stays even if the writer can no longer open it
        if field in fields and fields[field] == row[field]:
            fields.pop(field)
    if fields.get("business_unit_id") is None:
        fields.pop("business_unit_id", None)  # the unit can move to another unit in scope, never be cleared
    elif fields["business_unit_id"] == row["business_unit_id"]:
        fields.pop("business_unit_id")
    _check_references(db, user, fields)
    if "autonomy_level" in fields and fields["autonomy_level"] is None:
        fields["autonomy_level"] = "decision_support"

    def stored(field):
        if field == "data_categories":
            return _json_list(row[field])
        return bool(row[field]) if field in _BOOLS else row[field]

    changed = {f: v for f, v in fields.items() if (bool(v) if f in _BOOLS else v) != stored(f)}
    if details is not None and details != old_details:
        changed["details"] = json.dumps(details)
    impacts_changed = False
    if impacts is not None:
        current = {r["dimension_name"]: (bool(r["applicable"]), r["description"], r["likelihood"], r["impact"]) for r in db.execute(
            "SELECT dimension_name, applicable, description, likelihood, impact FROM sentinel_aiia_impacts WHERE aiia_id = %s",
            (assessment_id,)).fetchall()}
        wanted = {r["dimension_name"]: (bool(r["applicable"]), r["description"], r["likelihood"], r["impact"]) for r in impacts}
        impacts_changed = current != wanted
    if not changed and not impacts_changed:
        if row["version"] != expected_version:
            raise _stale(db, assessment_id)
        return {"assessment": _full(db, user, row), "events": [], "audit": []}

    sets, params = [], []
    for field, value in changed.items():
        sets.append(f"{field} = %s")
        params.append(json.dumps(value) if field == "data_categories" else value)
    if impacts_changed:
        sets.append("overall_classification = %s")
        params.append(_classification(db, impacts))
    now = _now()
    new_version = row["version"] + 1
    moved = db.execute(
        f"UPDATE sentinel_aiia SET {', '.join(sets)}, updated_at = %s, version = %s WHERE id = %s AND version = %s",
        [*params, now, new_version, assessment_id, expected_version]).rowcount
    if moved != 1:
        raise _stale(db, assessment_id)
    if impacts_changed:
        _store_impacts(db, assessment_id, impacts)

    names = sorted(set(changed) | ({"impacts"} if impacts_changed else set()))
    audit = [("ai_assessment_updated", "ai_assessment", assessment_id, "changed: " + ", ".join(names))]
    out_events = []
    if "status" in changed:
        audit.append(("ai_assessment_status_changed", "ai_assessment", assessment_id, f"{row['status']} -> {changed['status']}"))
        if changed["status"] in DONE and row["status"] not in DONE:
            out_events.append(_completed_event(db, user, assessment_id, changed.get("application_id", row["application_id"]),
                                               changed["status"], new_version))
    if "application_id" in changed:
        audit.append(("ai_assessment_linked", "ai_assessment", assessment_id,
                      f"system {changed['application_id']}" if changed["application_id"] is not None else "system link removed"))
    return {"assessment": _full(db, user, _row(db, user, assessment_id)), "events": out_events, "audit": audit}


def delete_assessment(db, user, assessment_id: int) -> dict:
    service._require(user, "ai_assessment.manage")
    row = _row(db, user, assessment_id)
    if not row:
        raise ServiceError(404, "Assessment not found.")
    if row["status"] == "approved":
        raise ServiceError(409, "An approved assessment cannot be deleted. Set it back to in progress first.")
    db.execute("DELETE FROM sentinel_aiia_impacts WHERE aiia_id = %s", (assessment_id,))
    db.execute("DELETE FROM sentinel_aiia WHERE id = %s", (assessment_id,))
    return {"events": [], "audit": [("ai_assessment_deleted", "ai_assessment", assessment_id, f"{row['ref_number']} {row['title'][:80]}")]}


# ── Impact dimensions ───────────────────────────────────────────────────────

def list_dimensions(db, user, include_inactive=True) -> list:
    service._require(user, "ai_assessment.view")
    sql = "SELECT id, name, order_idx, is_active FROM sentinel_aiia_dimensions"
    if not include_inactive:
        sql += " WHERE is_active = 1"
    rows = db.execute(sql + " ORDER BY order_idx, name").fetchall()
    return [{"id": r["id"], "name": r["name"], "order_idx": r["order_idx"], "is_active": bool(r["is_active"])} for r in rows]


def save_dimensions(db, user, dimensions) -> dict:
    """Upsert the dimension list. Renaming one carries its scored history; one not mentioned is left alone. Everything
    is checked before anything is written, so a refused list changes nothing."""
    service._require(user, "ai_assessment.configure")
    if not isinstance(dimensions, list):
        raise ServiceError(422, "Send the dimensions as a list.")
    if len(dimensions) > DIMENSIONS_MAX:
        raise ServiceError(422, f"At most {DIMENSIONS_MAX} dimensions can be saved at once.")
    existing = {r["id"]: r for r in db.execute("SELECT id, name, order_idx, is_active FROM sentinel_aiia_dimensions").fetchall()}
    taken = {r["name"].strip().lower(): r["id"] for r in existing.values()}
    plan, seen = [], set()
    for dim in dimensions:
        if not isinstance(dim, dict):
            raise ServiceError(422, "Each dimension must be an object.")
        name = _CONTROL.sub("", dim.get("name") if isinstance(dim.get("name"), str) else "").strip()
        if not name:
            raise ServiceError(422, "Every dimension needs a name.")
        if len(name) > 100:
            raise ServiceError(422, "A dimension name is too long (at most 100 characters).")
        dim_id = _int(dim.get("id"))
        dim_id = dim_id if dim_id in existing else None
        order = _int(dim.get("order_idx"))
        collision = taken.get(name.lower())
        if (collision is not None and collision != dim_id) or name.lower() in seen:
            raise ServiceError(409, f"A dimension named '{name}' already exists.")
        seen.add(name.lower())
        plan.append((dim_id, name, order if order is not None else 0, 0 if dim.get("is_active") in (False, 0, "0") else 1))
    for dim_id, name, order, active in plan:
        if dim_id is not None:
            old = existing[dim_id]["name"]
            db.execute("UPDATE sentinel_aiia_dimensions SET name = %s, order_idx = %s, is_active = %s WHERE id = %s",
                       (name, order, active, dim_id))
            if old != name:
                db.execute("UPDATE sentinel_aiia_impacts SET dimension_name = %s WHERE dimension_name = %s", (name, old))
        else:
            insert_returning_id(db, "INSERT INTO sentinel_aiia_dimensions (name, order_idx, is_active) VALUES (%s, %s, %s)",
                                (name, order, active))
    return {"dimensions": list_dimensions(db, user), "events": [],
            "audit": [("ai_dimensions_changed", "ai_assessment_dimensions", 0, f"{len(plan)} dimensions saved")]}


# ── Pickers ─────────────────────────────────────────────────────────────────

def link_options(db, user, kind, q=None, limit=20) -> list:
    """RoPAs or DPIAs (kind "ropa" or "dpia") the writer may open, found by typing, for the review section of the form."""
    service._require(user, "ai_assessment.manage")
    if kind not in _PRIVACY:
        raise ServiceError(400, "Choose RoPA or DPIA.")
    key, table, title = _PRIVACY[kind]
    scope, params = entity_scope_sql(key, user, "t")
    where, args = [scope], list(params)
    if q and q.strip():
        where.append(f"({ci_like('t.ref_number')} OR {ci_like('t.' + title)})")
        args += [like_pattern(q)] * 2
    rows = db.execute(f"SELECT t.id, t.ref_number, t.{title} AS title FROM {table} t WHERE {' AND '.join(where)} "
                      "ORDER BY t.updated_at DESC, t.id DESC LIMIT %s", [*args, max(1, min(int(limit), 50))]).fetchall()
    return [{"id": r["id"], "ref": r["ref_number"], "title": r["title"] or "(untitled)"} for r in rows]
