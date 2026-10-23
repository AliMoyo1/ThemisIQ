"""
Sentinel module — data service layer.

CRUD operations for all 14 Sentinel entity types.
All table names are sentinel_-prefixed.
Uses the unified get_db() pattern (caller closes connection).
"""
import json
import random
import string
from datetime import datetime, timedelta
from core.timeutils import utcnow, to_dt
from core.change_watch import watched
from database import get_db, insert_returning_id, sql_current_date
from core.sql_like import ci_like, like_pattern
from modules.sentinel.record_profiles import RecordError, get_profile
from core.report_kit.identity import pct

# ── Helpers ──────────────────────────────────────────────────────────────────

def _now():
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _parse_json(val, default=None):
    if default is None:
        default = []
    if not val:
        return default
    try:
        return json.loads(val)
    except Exception:
        return default


def _to_json(val):
    if isinstance(val, (list, dict)):
        return json.dumps(val)
    return val


def _gen_ref(prefix="REF"):
    ts = utcnow().strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"{prefix}-{ts}-{suffix}"


def _primary_jurisdiction_key() -> str:
    """Return the primary active jurisdiction key, falling back to 'GDPR'."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT jurisdiction_key FROM sentinel_jurisdiction_config "
            "WHERE is_active=1 AND is_primary=1 LIMIT 1"
        ).fetchone()
        return row["jurisdiction_key"] if row else "GDPR"
    finally:
        db.close()


def _generic_create(table, fields, data, ref_prefix=None, json_fields=None):
    """Generic CREATE helper. Returns new row ID."""
    now = _now()
    if json_fields:
        for f in json_fields:
            if f in data and isinstance(data[f], list):
                data[f] = json.dumps(data[f])
    params = {f: data.get(f) for f in fields}
    params["created_at"] = now
    params["updated_at"] = now
    if ref_prefix:
        params["ref_number"] = _gen_ref(ref_prefix)
    all_cols = list(params.keys())
    cols = ", ".join(all_cols)
    vals = ", ".join("%(" + k + ")s" for k in all_cols)
    db = get_db()
    try:
        cur = insert_returning_id(db,f"INSERT INTO {table} ({cols}) VALUES ({vals})", params)
        db.commit()
        return cur
    finally:
        db.close()


def _generic_update(table, allowed, data, row_id, json_fields=None):
    """Generic UPDATE helper."""
    now = _now()
    if json_fields:
        for f in json_fields:
            if f in data and isinstance(data[f], list):
                data[f] = json.dumps(data[f])
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=%({k})s")
            params[k] = v
    if not sets:
        return
    params["updated_at"] = now
    params["id"] = row_id
    db = get_db()
    try:
        db.execute(
            f"UPDATE {table} SET {','.join(sets)},updated_at=%(updated_at)s WHERE id=%(id)s",
            params,
        )
        db.commit()
    finally:
        db.close()


def _generic_get(table, row_id, row_fn=None):
    db = get_db()
    try:
        row = db.execute(f"SELECT * FROM {table} WHERE id=%s", (row_id,)).fetchone()
    finally:
        db.close()
    if not row:
        return None
    return row_fn(row) if row_fn else dict(row)


def _generic_delete(table, row_id):
    db = get_db()
    try:
        db.execute(f"DELETE FROM {table} WHERE id=%s", (row_id,))
        db.commit()
    finally:
        db.close()


def _generic_list(table, filters=None, order="updated_at DESC", limit=500, row_fn=None):
    """Generic list with optional filters dict {column: value}."""
    sql = f"SELECT * FROM {table} WHERE 1=1"
    params = []
    if filters:
        for col, val in filters.items():
            if val is not None and val != "":
                if col == "q":
                    continue  # handled separately
                sql += f" AND {col}=%s"
                params.append(val)
    sql += f" ORDER BY {order} LIMIT %s"
    params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    fn = row_fn or dict
    return [fn(r) for r in rows]


def unit_scope_sql(bu_scope, column="business_unit_id"):
    """(" AND (<column> IS NULL OR <column> IN (...))", params) for a caller confined to `bu_scope` (bu_scope_ids):
    the rule the lists below apply, in one place for the code that counts. ("", []) for None, a super administrator."""
    if bu_scope is None:
        return "", []
    marks = ",".join(["%s"] * len(bu_scope))
    return f" AND ({column} IS NULL OR {column} IN ({marks}))", list(bu_scope)


# The Sentinel tables that carry a business unit. Everything else here is organization wide.
_UNIT_TABLES = ("sentinel_ropa", "sentinel_dpias", "sentinel_breaches", "sentinel_dsr", "sentinel_consent")


def _unit_counter(db, bu_scope):
    """count(table, where) -> int, with the tables that sit in a unit limited to `bu_scope`."""
    unit, unit_params = unit_scope_sql(bu_scope)

    def count(table, where="1=1"):
        scoped = table in _UNIT_TABLES
        return db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE ({where}){unit if scoped else ''}",
            unit_params if scoped else [],
        ).fetchone()[0]
    return count


# ── Row converters ───────────────────────────────────────────────────────────

def _json_or_text(val):
    """Keep older free-text recipients and measures instead of reading them as empty lists."""
    if val is None or val == "":
        return []
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
        except ValueError:
            return val
        return parsed if isinstance(parsed, list) else val
    return val


def _ropa_row(row):
    d = dict(row)
    for f in ("data_categories", "special_categories"):
        d[f] = _parse_json(d.get(f), [])
    for f in ("processors", "recipients", "security_measures"):
        d[f] = _json_or_text(d.get(f))
    profile = get_profile("ropa", d.get("regulation"))
    d = profile.expand(d)
    made, needed = profile.completeness(d)
    d["readiness"] = {"made": made, "needed": needed, "gaps": [gap.label for gap in profile.gaps(d)]}
    return d


def _dpia_row(row):
    d = dict(row)
    d["data_categories"] = _parse_json(d.get("data_categories"), [])
    d["special_cats"] = _parse_json(d.get("special_cats"), [])
    d["risks"] = _parse_json(d.get("risks"), [])
    # The historical column default was medium even when nobody rated the DPIA.
    # The assessor's overall rating is the only reliable source for this alias.
    d["risk_level"] = d.get("overall_risk") or None
    profile = get_profile("dpia", d.get("regulation"))
    d = profile.expand(d)
    made, needed = profile.completeness(d)
    d["readiness"] = {"made": made, "needed": needed, "gaps": [gap.label for gap in profile.gaps(d)]}
    return d


def _breach_row(row):
    d = dict(row)
    d["data_types"] = _parse_json(d.get("data_types"), [])
    try:
        from modules.sentinel.jurisdictions import breach_clock
        d["clock"] = breach_clock(d.get("regulation"), d.get("discovery_date"))
    except Exception:  # the record is still shown; only the explanation is missing
        d["clock"] = None
    return d


def _vendor_row(row):
    d = dict(row)
    d["data_types"] = _parse_json(d.get("data_types"), [])
    return d


# ═════════════════════════════════════════════════════════════════════════════
# RoPA
# ═════════════════════════════════════════════════════════════════════════════

_ROPA_FIELDS = [
    "processing_name", "department", "owner", "regulation", "purpose", "legal_basis",
    "data_categories", "special_categories", "data_subjects", "subject_count",
    "retention_period", "systems", "processors", "recipients", "intl_transfers",
    "transfer_dest", "transfer_safeguard", "security_measures", "dpia_required",
    "dpia_id", "risk_level", "ai_risk_notes", "status", "review_date", "notes",
]
_ROPA_JSON = ["data_categories", "special_categories", "processors", "recipients", "security_measures"]

_ROPA_SYSTEM = ("regulation", "dpia_id", "ai_risk_notes")


def _record_values(profile, data, existing_details=None, system_fields=()):
    """Validated profile columns and JSON details, plus explicitly permitted system fields."""
    columns, details, errors = profile.prepare(data, existing_details)
    if errors:
        raise RecordError(errors)
    values = {k: data[k] for k in system_fields if k in data}
    values.update(columns)
    if details is not None:
        values["details"] = json.dumps(details)
    return values


def create_ropa(data, business_unit_id=None):
    data.setdefault("processing_name", "Untitled Entry")
    data.setdefault("regulation", _primary_jurisdiction_key())
    data.setdefault("status", "active")
    data.setdefault("risk_level", None)
    values = _record_values(get_profile("ropa", data["regulation"]), data, system_fields=_ROPA_SYSTEM)
    values["business_unit_id"] = business_unit_id
    return _generic_create("sentinel_ropa", _ROPA_FIELDS + ["details", "business_unit_id"], values,
                           ref_prefix="ROPA", json_fields=_ROPA_JSON)


@watched("sentinel", "ropa")
def update_ropa(ropa_id, data):
    db = get_db()
    try:
        row = db.execute("SELECT regulation, details FROM sentinel_ropa WHERE id=%s", (ropa_id,)).fetchone()
    finally:
        db.close()
    stored = _parse_json(row["details"], {}) if row else {}
    values = _record_values(get_profile("ropa", data.get("regulation") or (row["regulation"] if row else None)), data,
                            stored if isinstance(stored, dict) else {}, system_fields=_ROPA_SYSTEM)
    _generic_update("sentinel_ropa", set(_ROPA_FIELDS) | {"details"}, values, ropa_id, json_fields=_ROPA_JSON)

def get_ropa(ropa_id):
    return _generic_get("sentinel_ropa", ropa_id, _ropa_row)

def delete_ropa(ropa_id):
    """Raises ValueError (the route answers 409) while the delete would leave something wrong behind. A data flow that
    names the entry would be left pointing at nothing (the foreign key refuses it anyway, as a 500). An LIA follows
    its entry's unit through ropa_id, so for an entry that sits in a unit ON DELETE SET NULL would show it to every
    unit; an entry that is organization wide changes nothing for its LIAs and is deleted as before."""
    db = get_db()
    try:
        entry = db.execute("SELECT business_unit_id FROM sentinel_ropa WHERE id=%s", (ropa_id,)).fetchone()
        flows = db.execute("SELECT COUNT(*) FROM sentinel_data_flows WHERE ropa_id=%s", (ropa_id,)).fetchone()[0]
        lias = db.execute("SELECT COUNT(*) FROM sentinel_lia WHERE ropa_id=%s", (ropa_id,)).fetchone()[0]
    finally:
        db.close()
    if flows:
        raise ValueError(f"This RoPA entry still has {flows} data flow{'' if flows == 1 else 's'}. "
                         "Delete them or link them to another entry first.")
    if lias and entry and entry["business_unit_id"] is not None:
        raise ValueError(f"This RoPA entry sits in a business unit and still has {lias} legitimate interest "
                         f"assessment{'' if lias == 1 else 's'}. Deleting the entry would show "
                         f"{'it' if lias == 1 else 'them'} to every unit; delete "
                         f"{'it' if lias == 1 else 'them'} first.")
    _generic_delete("sentinel_ropa", ropa_id)


def list_ropa(search=None, regulation=None, status=None, risk=None, limit=500, bu_scope=None):
    sql = "SELECT * FROM sentinel_ropa WHERE 1=1"
    params = []
    if search:
        sql += f" AND ({ci_like('processing_name')} OR {ci_like('department')} OR {ci_like('owner')})"
        like = like_pattern(search)
        params += [like, like, like]
    if regulation:
        sql += " AND regulation=%s"
        params.append(regulation)
    if status:
        sql += " AND status=%s"
        params.append(status)
    if risk:
        sql += " AND risk_level=%s"
        params.append(risk)
    if bu_scope is not None:
        if bu_scope:
            ph = ",".join(["%s"] * len(bu_scope))
            sql += f" AND (business_unit_id IN ({ph}) OR business_unit_id IS NULL)"
            params.extend(bu_scope)
        else:
            sql += " AND business_unit_id IS NULL"
    sql += " ORDER BY updated_at DESC"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [_ropa_row(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# DPIA
# ═════════════════════════════════════════════════════════════════════════════

_DPIA_FIELDS = [
    "title", "status", "regulation", "org_name", "department", "controller_name",
    "dpo_name", "dpo_email", "activity_type", "activity_desc", "purpose", "legal_basis",
    "data_categories", "special_cats", "data_subjects", "subject_count", "retention",
    "systems", "processors", "intl_transfer", "transfer_dest", "transfer_mech",
    "necessity", "proportionality", "risks", "overall_risk", "residual_risk", "risk_level",
    "dpo_consulted", "auth_consulted", "subjects_consulted", "consult_notes",
    "ai_research", "ai_full_dpia", "ropa_id",
    "description", "owner", "due_date", "mitigations", "details",
]
_DPIA_JSON = ["data_categories", "special_cats", "risks"]


def _date_or_none(data, field):
    """Store an empty date as NULL and reject values other than YYYY-MM-DD."""
    if field not in data:
        return
    raw = data[field]
    if raw is not None and not isinstance(raw, str):
        raise ValueError(f"The {field.replace('_', ' ')} must be a date written YYYY-MM-DD.")
    value = (raw or "").strip()
    if value:
        try:
            if len(value) != 10:
                raise ValueError(value)
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"The {field.replace('_', ' ')} must be a date written YYYY-MM-DD.") from None
    data[field] = value or None


def _sync_dpia_risk(data):
    """Persist the chosen overall rating; a client's legacy risk_level is never authoritative."""
    data.pop("risk_level", None)
    for field in ("overall_risk", "residual_risk"):
        if field in data:
            value = str(data[field] or "").strip().lower()
            if value and value not in ("low", "medium", "high"):
                raise ValueError(f"Choose a valid {field.replace('_', ' ')}.")
            data[field] = value or None
    if "overall_risk" in data:
        data["risk_level"] = data["overall_risk"]


def create_dpia(data, business_unit_id=None):
    """`business_unit_id` is the caller's to give, never read from `data` (what a client sent): a DPIA about a unit's
    RoPA entry sits in that unit, so the copy is no wider than the entry it came from."""
    data.setdefault("title", "Untitled DPIA")
    data.setdefault("status", "draft")
    data.setdefault("regulation", _primary_jurisdiction_key())
    for f in _DPIA_JSON:
        data.setdefault(f, "[]")
    _date_or_none(data, "due_date")
    _sync_dpia_risk(data)
    data.setdefault("risk_level", None)
    profile = get_profile("dpia", data["regulation"])
    data.update(_record_values(profile, {k: data[k] for k in profile.detail_keys() if k in data}))
    data["business_unit_id"] = business_unit_id
    return _generic_create("sentinel_dpias", _DPIA_FIELDS + ["business_unit_id"], data, ref_prefix="DPIA",
                           json_fields=_DPIA_JSON)


@watched("sentinel", "dpia")
def update_dpia(dpia_id, data):
    _date_or_none(data, "due_date")
    _sync_dpia_risk(data)
    db = get_db()
    try:
        row = db.execute("SELECT regulation, details FROM sentinel_dpias WHERE id=%s", (dpia_id,)).fetchone()
    finally:
        db.close()
    profile = get_profile("dpia", data.get("regulation") or (row["regulation"] if row else None))
    existing = _parse_json(row["details"], {}) if row else {}
    data.update(_record_values(profile, {k: data[k] for k in profile.detail_keys() if k in data},
                               existing if isinstance(existing, dict) else {}))
    _generic_update("sentinel_dpias", set(_DPIA_FIELDS), data, dpia_id, json_fields=_DPIA_JSON)

def get_dpia(dpia_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT d.*, r.ref_number AS ropa_ref, r.processing_name AS ropa_name, "
            "r.updated_at AS ropa_updated_at "
            "FROM sentinel_dpias d "
            "LEFT JOIN sentinel_ropa r ON r.id = d.ropa_id "
            "WHERE d.id=%s",
            (dpia_id,),
        ).fetchone()
    finally:
        db.close()
    return _dpia_row(row) if row else None

def delete_dpia(dpia_id):
    db = get_db()
    try:
        row = db.execute("SELECT ropa_id FROM sentinel_dpias WHERE id=%s", (dpia_id,)).fetchone()
        if row and row["ropa_id"]:
            db.execute(
                "UPDATE sentinel_ropa SET dpia_id=NULL WHERE id=%s AND dpia_id=%s",
                (row["ropa_id"], dpia_id),
            )
        db.execute("DELETE FROM sentinel_dpias WHERE id=%s", (dpia_id,))
        db.commit()
    finally:
        db.close()


def link_dpia_to_ropa(dpia_id, ropa_id):
    """Link a DPIA to a RoPA and backfill empty DPIA fields. Returns False if refused."""
    db = get_db()
    try:
        dpia = db.execute("SELECT * FROM sentinel_dpias WHERE id=%s", (dpia_id,)).fetchone()
        ropa = db.execute("SELECT * FROM sentinel_ropa WHERE id=%s", (ropa_id,)).fetchone()
        if not dpia or not ropa:
            return False
        if ropa["dpia_id"] and ropa["dpia_id"] != dpia_id:
            return False

        def _empty(val):
            if val is None:
                return True
            if isinstance(val, str) and val.strip() in ("", "[]", "null"):
                return True
            return False

        _RPA_TO_DPIA = [
            ("processing_name", "title", lambda v: f"DPIA: {v}"),
            ("department",       "department",       None),
            ("owner",            "owner",            None),
            ("purpose",          "activity_desc",     None),
            ("legal_basis",      "legal_basis",      None),
            ("data_categories",  "data_categories",  None),
            ("special_categories", "special_cats",   None),
            ("data_subjects",    "data_subjects",    None),
            ("retention_period", "retention",        None),
            ("intl_transfers",   "intl_transfer",    None),
            ("recipients",       "processors",       None),
            ("regulation",       "regulation",       None),
        ]
        now = _now()
        sets, params = [], []
        for ropa_col, dpia_col, transform in _RPA_TO_DPIA:
            ropa_val = ropa[ropa_col] if ropa_col in ropa.keys() else None
            dpia_val = dpia[dpia_col] if dpia_col in dpia.keys() else None
            if ropa_val and not _empty(ropa_val) and _empty(dpia_val):
                val = transform(ropa_val) if transform else ropa_val
                sets.append(f"{dpia_col}=%s")
                params.append(val)
        sets.append("ropa_id=%s")
        params.append(ropa_id)
        sets.append("updated_at=%s")
        params.append(now)
        params.append(dpia_id)
        db.execute(
            f"UPDATE sentinel_dpias SET {','.join(sets)} WHERE id=%s",
            params,
        )
        db.execute(
            "UPDATE sentinel_ropa SET dpia_id=%s, updated_at=%s WHERE id=%s",
            (dpia_id, now, ropa_id),
        )
        db.commit()
        return True
    finally:
        db.close()


def list_dpias(search=None, regulation=None, status=None, limit=500, bu_scope=None):
    sql = (
        "SELECT d.*, r.ref_number AS ropa_ref, r.processing_name AS ropa_name, "
        "r.updated_at AS ropa_updated_at "
        "FROM sentinel_dpias d "
        "LEFT JOIN sentinel_ropa r ON r.id = d.ropa_id "
        "WHERE 1=1"
    )
    params = []
    if search:
        sql += f" AND ({ci_like('d.title')} OR {ci_like('d.org_name')} OR {ci_like('d.activity_type')})"
        like = like_pattern(search)
        params += [like, like, like]
    if regulation:
        sql += " AND d.regulation=%s"
        params.append(regulation)
    if status:
        sql += " AND d.status=%s"
        params.append(status)
    if bu_scope is not None:
        ph = ",".join(["%s"] * len(bu_scope))
        sql += f" AND (d.business_unit_id IN ({ph}) OR d.business_unit_id IS NULL)"
        params.extend(bu_scope)
    sql += " ORDER BY d.updated_at DESC LIMIT %s"
    params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [_dpia_row(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Breaches
# ═════════════════════════════════════════════════════════════════════════════

_BREACH_FIELDS = [
    "title", "regulation", "discovery_date", "incident_date", "breach_type",
    "description", "data_types", "affected_count", "severity", "root_cause",
    "containment", "remediation", "notification_required", "authority_notified",
    "authority_notify_date", "authority_ref", "subjects_notified",
    "subjects_notify_date", "notify_deadline", "status", "ai_assessment", "lessons_learned",
]


def _notify_deadline(regulation, discovery_date):
    """The indicative notification deadline counted from the recorded discovery date by the configured rule, or None when
    there is no trigger (no discovery date) or no rule for the regulation: no clock is invented for either."""
    from modules.sentinel.jurisdictions import breach_clock, get_breach_deadline_hours
    if breach_clock(regulation, discovery_date)["state"] in ("no_trigger", "no_rule"):
        return None
    start = to_dt(str(discovery_date)[:10])
    if start is None:
        return None
    return (start + timedelta(hours=get_breach_deadline_hours(regulation))).strftime("%Y-%m-%d %H:%M:%S")


def create_breach(data, business_unit_id=None):
    data.setdefault("title", "Untitled Incident")
    data.setdefault("regulation", _primary_jurisdiction_key())
    data.setdefault("severity", "medium")
    data.setdefault("status", "open")
    if data.get("discovery_date"):
        try:
            data["notify_deadline"] = _notify_deadline(data.get("regulation", "GDPR"), data["discovery_date"])
        except Exception:
            pass
    data["business_unit_id"] = business_unit_id
    return _generic_create("sentinel_breaches", _BREACH_FIELDS + ["business_unit_id"], data,
                           ref_prefix="BRE", json_fields=["data_types"])


@watched("sentinel", "breach")
def update_breach(bid, data):
    # The deadline follows its trigger and its rule. It used to be set once, at creation, so an edited discovery date or
    # regulation left the old deadline running. An explicit deadline in the update is kept as given.
    if ("discovery_date" in data or "regulation" in data) and "notify_deadline" not in data:
        current = get_breach(bid) or {}
        data = dict(data)
        try:
            data["notify_deadline"] = _notify_deadline(
                data.get("regulation", current.get("regulation")) or "GDPR",
                data.get("discovery_date", current.get("discovery_date")))
        except Exception:
            data.pop("notify_deadline", None)
    _generic_update("sentinel_breaches", set(_BREACH_FIELDS), data, bid, json_fields=["data_types"])

def get_breach(bid):
    return _generic_get("sentinel_breaches", bid, _breach_row)

def delete_breach(bid):
    _generic_delete("sentinel_breaches", bid)


def list_breaches(search=None, status=None, severity=None, limit=500, bu_scope=None):
    sql = "SELECT * FROM sentinel_breaches WHERE 1=1"
    params = []
    if search:
        sql += f" AND ({ci_like('title')} OR {ci_like('description')})"
        like = like_pattern(search)
        params += [like, like]
    if status:
        sql += " AND status=%s"
        params.append(status)
    if severity:
        sql += " AND severity=%s"
        params.append(severity)
    if bu_scope is not None:
        ph = ",".join(["%s"] * len(bu_scope))
        sql += f" AND (business_unit_id IN ({ph}) OR business_unit_id IS NULL)"
        params.extend(bu_scope)
    sql += " ORDER BY updated_at DESC LIMIT %s"
    params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [_breach_row(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# DSR
# ═════════════════════════════════════════════════════════════════════════════

_DSR_FIELDS = [
    "requester_name", "requester_email", "request_type", "regulation",
    "description", "received_date", "deadline_date", "status", "response_notes", "ai_draft",
    "business_unit_id",
]


def create_dsr(data):
    data.setdefault("regulation", _primary_jurisdiction_key())
    data.setdefault("status", "open")
    if data.get("received_date") and not data.get("deadline_date"):
        try:
            from modules.sentinel.jurisdictions import get_dsr_deadline_days
            days = get_dsr_deadline_days(data.get("regulation", "GDPR"))
            rec = to_dt(data["received_date"][:10])
            data["deadline_date"] = (rec + timedelta(days=days)).strftime("%Y-%m-%d")
        except Exception:
            pass
    return _generic_create("sentinel_dsr", _DSR_FIELDS, data, ref_prefix="DSR")


@watched("sentinel", "dsr")
def update_dsr(dsr_id, data, bu_scope=None):
    """No-ops (returns False) if dsr_id is outside bu_scope, mirroring
    get_dsr's fail-closed check -- callers must treat False as
    HTTPException(404), never apply data anyway."""
    if bu_scope is not None and get_dsr(dsr_id, bu_scope=bu_scope) is None:
        return False
    if data.get("received_date") and not data.get("deadline_date"):
        try:
            from modules.sentinel.jurisdictions import get_dsr_deadline_days
            existing = get_dsr(dsr_id)
            regulation = data.get("regulation") or (existing.get("regulation") if existing else None) or "GDPR"
            days = get_dsr_deadline_days(regulation)
            rec = to_dt(data["received_date"][:10])
            data["deadline_date"] = (rec + timedelta(days=days)).strftime("%Y-%m-%d")
        except Exception:
            pass
    _generic_update("sentinel_dsr", set(_DSR_FIELDS), data, dsr_id)
    return True


def get_dsr(dsr_id, bu_scope=None):
    """Returns None both when dsr_id doesn't exist and when it's outside
    bu_scope, so a 404 built from this never confirms another BU's DSR id
    is real (same fail-closed shape as modules/evidence/routes.py's
    _scoped_evidence_item)."""
    row = _generic_get("sentinel_dsr", dsr_id)
    if row is None or bu_scope is None:
        return row
    if row.get("business_unit_id") is None or row["business_unit_id"] in bu_scope:
        return row
    return None


def delete_dsr(dsr_id, bu_scope=None):
    """Returns False (caller 404s) if dsr_id is outside bu_scope."""
    if bu_scope is not None and get_dsr(dsr_id, bu_scope=bu_scope) is None:
        return False
    _generic_delete("sentinel_dsr", dsr_id)
    return True


def list_dsrs(search=None, status=None, request_type=None, limit=500, bu_scope=None):
    sql = "SELECT * FROM sentinel_dsr WHERE 1=1"
    params = []
    if search:
        sql += f" AND ({ci_like('requester_name')} OR {ci_like('requester_email')} OR {ci_like('description')})"
        like = like_pattern(search)
        params += [like, like, like]
    if status:
        sql += " AND status=%s"
        params.append(status)
    if request_type:
        sql += " AND request_type=%s"
        params.append(request_type)
    if bu_scope is not None:
        ph = ",".join(["%s"] * len(bu_scope))
        sql += f" AND (business_unit_id IN ({ph}) OR business_unit_id IS NULL)"
        params.extend(bu_scope)
    sql += " ORDER BY deadline_date ASC LIMIT %s"
    params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Vendors
# ═════════════════════════════════════════════════════════════════════════════

_VENDOR_FIELDS = [
    "name", "type", "country", "services", "data_types", "data_subjects",
    "dpa_status", "dpa_date", "dpa_expiry", "risk_level", "ai_assessment",
    "contact_name", "contact_email", "website", "regulation", "notes", "canonical_id",
    "review_date",
]


def create_vendor(data):
    data.setdefault("name", "Unnamed Vendor")
    data.setdefault("type", "processor")
    data.setdefault("risk_level", "medium")
    data.setdefault("dpa_status", "pending")
    data.setdefault("regulation", _primary_jurisdiction_key())
    # Auto-link canonical vendor identity
    if not data.get("canonical_id"):
        try:
            from core.vendor_link import ensure_canonical
            db = get_db()
            try:
                cid = ensure_canonical(db, data["name"], data.get("contact_email"))
                db.commit()
                data["canonical_id"] = cid
            finally:
                db.close()
        except Exception:
            pass
    return _generic_create("sentinel_vendors", _VENDOR_FIELDS, data, json_fields=["data_types"])


@watched("sentinel", "vendor")
def update_vendor(vid, data):
    _generic_update("sentinel_vendors", set(_VENDOR_FIELDS), data, vid, json_fields=["data_types"])

def get_vendor(vid):
    return _generic_get("sentinel_vendors", vid, _vendor_row)

def delete_vendor(vid):
    _generic_delete("sentinel_vendors", vid)


def list_vendors(search=None, risk=None, dpa_status=None, limit=500):
    sql = "SELECT * FROM sentinel_vendors WHERE 1=1"
    params = []
    if search:
        sql += f" AND ({ci_like('name')} OR {ci_like('services')} OR {ci_like('country')})"
        like = like_pattern(search)
        params += [like, like, like]
    if risk:
        sql += " AND risk_level=%s"
        params.append(risk)
    if dpa_status:
        sql += " AND dpa_status=%s"
        params.append(dpa_status)
    sql += " ORDER BY updated_at DESC LIMIT %s"
    params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [_vendor_row(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Privacy Notices
# ═════════════════════════════════════════════════════════════════════════════

_NOTICE_FIELDS = ["title", "regulation", "audience", "version", "content", "status", "review_date", "published_date", "notice_type", "published_url"]

def create_notice(data):
    data.setdefault("title", "Untitled Notice")
    data.setdefault("regulation", _primary_jurisdiction_key())
    data.setdefault("status", "draft")
    data.setdefault("version", "1.0")
    return _generic_create("sentinel_privacy_notices", _NOTICE_FIELDS, data)

def update_notice(nid, data):
    _generic_update("sentinel_privacy_notices", set(_NOTICE_FIELDS), data, nid)

def get_notice(nid):
    return _generic_get("sentinel_privacy_notices", nid)

def delete_notice(nid):
    _generic_delete("sentinel_privacy_notices", nid)

def list_notices(limit=200):
    return _generic_list("sentinel_privacy_notices", order="updated_at DESC", limit=limit)


# ═════════════════════════════════════════════════════════════════════════════
# Consent
# ═════════════════════════════════════════════════════════════════════════════

_CONSENT_FIELDS = [
    "subject_id", "subject_name", "subject_email", "purpose", "regulation",
    "legal_basis", "consent_date", "expiry_date", "withdrawal_date", "status", "evidence", "notes",
    "collection_method", "business_unit_id",
]

def create_consent(data):
    data.setdefault("regulation", _primary_jurisdiction_key())
    data.setdefault("status", "active")
    data.setdefault("legal_basis", "Consent")
    return _generic_create("sentinel_consent", _CONSENT_FIELDS, data)

def update_consent(cid, data):
    _generic_update("sentinel_consent", set(_CONSENT_FIELDS), data, cid)

def get_consent(cid):
    return _generic_get("sentinel_consent", cid)

def delete_consent(cid):
    _generic_delete("sentinel_consent", cid)

def list_consent(search=None, status=None, limit=500, bu_scope=None):
    sql = "SELECT * FROM sentinel_consent WHERE 1=1"
    params = []
    if search:
        sql += f" AND ({ci_like('subject_name')} OR {ci_like('subject_email')} OR {ci_like('purpose')})"
        like = like_pattern(search)
        params += [like, like, like]
    if status:
        sql += " AND status=%s"
        params.append(status)
    unit, unit_params = unit_scope_sql(bu_scope)
    sql += unit
    params.extend(unit_params)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Controllers
# ═════════════════════════════════════════════════════════════════════════════

_CTRL_FIELDS = [
    "org_name", "registration_number", "country", "address", "sector", "role",
    "controller_name", "controller_email", "controller_phone",
    "dpo_name", "dpo_email", "dpo_phone",
    "regulator_name", "regulator_ref", "regulation", "is_primary", "notes",
    "contact_name", "contact_email", "agreement_date", "agreement_ref", "responsibilities",
    "representative", "representative_contact", "record_owner", "last_full_review",
]

CONTROLLER_ROLES = ("controller", "joint_controller", "processor", "dpo", "regulator")


def _check_controller(data):
    if data.get("role") not in (None, "", *CONTROLLER_ROLES):
        raise ValueError("Choose a role from the list.")

def create_controller(data):
    _check_controller(data)
    data.setdefault("org_name", "Unnamed Organisation")
    if not data.get("role"):
        data["role"] = "controller" if str(data.get("is_primary") or "0").lower() in ("1", "true", "yes") else "joint_controller"
    return _generic_create("sentinel_controllers", _CTRL_FIELDS, data)

def update_controller(cid, data):
    _check_controller(data)
    _generic_update("sentinel_controllers", set(_CTRL_FIELDS), data, cid)

def get_controller(cid):
    return _generic_get("sentinel_controllers", cid)

def delete_controller(cid):
    _generic_delete("sentinel_controllers", cid)

def list_controllers(limit=200):
    return _generic_list("sentinel_controllers", order="is_primary DESC, org_name ASC", limit=limit)


# ═════════════════════════════════════════════════════════════════════════════
# Transfers
# ═════════════════════════════════════════════════════════════════════════════

_TRANSFER_FIELDS = [
    "ropa_id", "destination", "recipient_name", "transfer_type", "safeguard",
    "safeguard_detail", "regulation", "legal_basis", "adequacy_decision", "data_types",
    "frequency", "volume", "risk_level", "status", "review_date", "notes",
]

def create_transfer(data):
    data.setdefault("regulation", _primary_jurisdiction_key())
    data.setdefault("status", "active")
    return _generic_create("sentinel_transfers", _TRANSFER_FIELDS, data, ref_prefix="TRF", json_fields=["data_types"])

def update_transfer(tid, data):
    _generic_update("sentinel_transfers", set(_TRANSFER_FIELDS), data, tid, json_fields=["data_types"])

def get_transfer(tid):
    return _generic_get("sentinel_transfers", tid)

def delete_transfer(tid):
    _generic_delete("sentinel_transfers", tid)

def list_transfers(limit=500):
    return _generic_list("sentinel_transfers", order="updated_at DESC", limit=limit)


# ═════════════════════════════════════════════════════════════════════════════
# Retention
# ═════════════════════════════════════════════════════════════════════════════

_RET_FIELDS = [
    "category", "data_type", "retention_period", "legal_basis", "regulation",
    "trigger_event", "disposal_method", "owner", "review_date", "notes",
]

def create_retention(data):
    data.setdefault("regulation", _primary_jurisdiction_key())
    return _generic_create("sentinel_retention", _RET_FIELDS, data)

def update_retention(rid, data):
    _generic_update("sentinel_retention", set(_RET_FIELDS), data, rid)

def get_retention(rid):
    return _generic_get("sentinel_retention", rid)

def delete_retention(rid):
    _generic_delete("sentinel_retention", rid)

def list_retention(limit=500):
    return _generic_list("sentinel_retention", order="category ASC", limit=limit)


# ═════════════════════════════════════════════════════════════════════════════
# Security Measures
# ═════════════════════════════════════════════════════════════════════════════

_SEC_FIELDS = [
    "measure_name", "category", "description", "status",
    "implementation_date", "review_date", "owner", "evidence", "regulation", "notes",
]

def create_security(data):
    data.setdefault("status", "implemented")
    data.setdefault("regulation", _primary_jurisdiction_key())
    return _generic_create("sentinel_security_measures", _SEC_FIELDS, data)

def update_security(sid, data):
    _generic_update("sentinel_security_measures", set(_SEC_FIELDS), data, sid)

def get_security(sid):
    return _generic_get("sentinel_security_measures", sid)

def delete_security(sid):
    _generic_delete("sentinel_security_measures", sid)

def list_security(limit=500):
    return _generic_list("sentinel_security_measures", order="category ASC, measure_name ASC", limit=limit)


# ═════════════════════════════════════════════════════════════════════════════
# Policies
# ═════════════════════════════════════════════════════════════════════════════

_POLICY_FIELDS = [
    "title", "policy_type", "version", "status", "owner", "department",
    "regulation", "description", "file_path", "file_name", "review_date",
    "expiry_date", "approved_by", "approved_date", "next_review", "tags", "notes",
]

def create_policy(data):
    return _generic_create("sentinel_policies", _POLICY_FIELDS, data, ref_prefix="POL")

def update_policy(pid, data):
    _generic_update("sentinel_policies", set(_POLICY_FIELDS), data, pid)

def get_policy(pid):
    return _generic_get("sentinel_policies", pid)

def delete_policy(pid):
    _generic_delete("sentinel_policies", pid)

def list_policies(search=None, status=None, policy_type=None, limit=500):
    sql = "SELECT * FROM sentinel_policies WHERE 1=1"
    params = []
    if search:
        sql += f" AND ({ci_like('title')} OR {ci_like('owner')} OR {ci_like('department')})"
        like = like_pattern(search)
        params += [like, like, like]
    if status:
        sql += " AND status=%s"
        params.append(status)
    if policy_type:
        sql += " AND type=%s"   # DB column is 'type', not 'policy_type'
        params.append(policy_type)
    sql += " ORDER BY review_date ASC LIMIT %s"
    params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Training
# ═════════════════════════════════════════════════════════════════════════════

_TRAINING_FIELDS = [
    "training_name", "training_type", "staff_name", "staff_email",
    "department", "completion_date", "expiry_date", "score", "passed",
    "certificate_no", "trainer", "regulation", "notes",
]

def create_training(data):
    return _generic_create("sentinel_training", _TRAINING_FIELDS, data, ref_prefix="TRN")

def update_training(tid, data):
    _generic_update("sentinel_training", set(_TRAINING_FIELDS), data, tid)

def get_training(tid):
    return _generic_get("sentinel_training", tid)

def delete_training(tid):
    _generic_delete("sentinel_training", tid)

def list_training(search=None, department=None, limit=500):
    sql = "SELECT * FROM sentinel_training WHERE 1=1"
    params = []
    if search:
        sql += f" AND ({ci_like('staff_name')} OR {ci_like('training_name')} OR {ci_like('department')})"
        like = like_pattern(search)
        params += [like, like, like]
    if department:
        sql += " AND department=%s"
        params.append(department)
    sql += " ORDER BY expiry_date ASC LIMIT %s"
    params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Data Flows
# ═════════════════════════════════════════════════════════════════════════════

_FLOW_FIELDS = [
    "name", "source", "destination", "data_types",
    "purpose", "legal_basis", "safeguards", "ropa_id", "regulation", "notes",
]

def create_dataflow(data):
    return _generic_create("sentinel_data_flows", _FLOW_FIELDS, data, ref_prefix="FLOW")

def update_dataflow(fid, data):
    _generic_update("sentinel_data_flows", set(_FLOW_FIELDS), data, fid)

def get_dataflow(fid):
    return _generic_get("sentinel_data_flows", fid)

def delete_dataflow(fid):
    _generic_delete("sentinel_data_flows", fid)

def list_dataflows(limit=500, bu_scope=None):
    """A data flow sits where its RoPA entry sits (organization wide without one), like an LIA."""
    if bu_scope is None:
        return _generic_list("sentinel_data_flows", order="created_at DESC", limit=limit)
    unit, unit_params = unit_scope_sql(bu_scope, "r.business_unit_id")
    db = get_db()
    try:
        rows = db.execute(
            "SELECT f.* FROM sentinel_data_flows f LEFT JOIN sentinel_ropa r ON r.id=f.ropa_id "
            f"WHERE 1=1{unit} ORDER BY f.created_at DESC LIMIT %s",
            [*unit_params, limit],
        ).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Settings (uses shared settings table)
# ═════════════════════════════════════════════════════════════════════════════

_PRIVACY_SETTING_LIMITS = {
    "org_name": 200,
    "dpo_name": 200,
    "dpo_email": 254,
    "primary_regulation": 200,
    "sentinel_dpo_email": 254,
}


def update_privacy_settings(values):
    """Update only Privacy-owned keys in the shared settings table."""
    if not isinstance(values, dict) or not values:
        raise ValueError("Provide Privacy settings to update")
    for key, value in values.items():
        if key not in _PRIVACY_SETTING_LIMITS:
            raise ValueError("Unknown Privacy setting")
        if not isinstance(value, str) or len(value) > _PRIVACY_SETTING_LIMITS[key]:
            raise ValueError("Invalid Privacy setting value")
    db = get_db()
    try:
        for key, value in values.items():
            db.execute(
                "INSERT INTO settings(key,value) VALUES(%s,%s) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_setting(key, default=None):
    db = get_db()
    try:
        row = db.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
    finally:
        db.close()
    return row["value"] if row else default


def set_setting(key, value):
    update_privacy_settings({key: value})


def get_all_settings():
    db = get_db()
    try:
        rows = db.execute(
            "SELECT key, value FROM settings WHERE key IN (%s,%s,%s,%s,%s)",
            tuple(_PRIVACY_SETTING_LIMITS),
        ).fetchall()
    finally:
        db.close()
    return {r["key"]: r["value"] for r in rows}


# ═════════════════════════════════════════════════════════════════════════════
# Sentinel Audit Log (uses shared audit_log)
# ═════════════════════════════════════════════════════════════════════════════

def list_audit(limit=200, org_id=None):
    db = get_db()
    try:
        if org_id is None:
            rows = db.execute(
                "SELECT * FROM audit_log WHERE module='sentinel' ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM audit_log WHERE module='sentinel' AND org_id=%s ORDER BY created_at DESC LIMIT %s",
                (org_id, limit),
            ).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Stats
# ═════════════════════════════════════════════════════════════════════════════

def get_stats(bu_scope=None):
    """The dashboard counts. With `bu_scope` (bu_scope_ids) only what that caller can open is counted, so the numbers
    agree with the lists; vendors, notices and the other kinds with no unit are counted as they are."""
    db = get_db()
    try:
        count = _unit_counter(db, bu_scope)
        unit, unit_params = unit_scope_sql(bu_scope)
        ropa_total = count("sentinel_ropa")
        dpia_total = count("sentinel_dpias")
        dpia_draft = count("sentinel_dpias", "status='draft'")
        dpia_approved = count("sentinel_dpias", "status='approved'")
        breach_open = count("sentinel_breaches", "status='open'")
        breach_critical = count("sentinel_breaches", "severity='critical'")
        dsr_open = count("sentinel_dsr", "status='open'")
        dsr_overdue = count("sentinel_dsr", f"status='open' AND deadline_date < {sql_current_date()}")
        vendor_total = count("sentinel_vendors")
        high_risk_ropa = count("sentinel_ropa", "risk_level IN ('high','critical')")
        dpia_required = count("sentinel_ropa", "dpia_required=1")
        consent_active = count("sentinel_consent", "status='active'")
        notices_total = count("sentinel_privacy_notices")
        policy_total = count("sentinel_policies")
        training_total = count("sentinel_training")
        by_reg = db.execute(
            f"SELECT regulation, COUNT(*) c FROM sentinel_ropa WHERE 1=1{unit} GROUP BY regulation", unit_params
        ).fetchall()
        risk_dist = db.execute(
            f"SELECT risk_level, COUNT(*) c FROM sentinel_ropa WHERE 1=1{unit} GROUP BY risk_level", unit_params
        ).fetchall()
    finally:
        db.close()
    return {
        "ropa_total": ropa_total,
        "dpia_total": dpia_total,
        "dpia_draft": dpia_draft,
        "dpia_approved": dpia_approved,
        "breach_open": breach_open,
        "breach_critical": breach_critical,
        "dsr_open": dsr_open,
        "dsr_overdue": dsr_overdue,
        "vendor_total": vendor_total,
        "high_risk_ropa": high_risk_ropa,
        "dpia_required": dpia_required,
        "consent_active": consent_active,
        "notices_total": notices_total,
        "policies": policy_total,
        "training": training_total,
        "by_regulation": {r["regulation"]: r["c"] for r in by_reg},
        "risk_distribution": {r["risk_level"]: r["c"] for r in risk_dist},
    }


# ═════════════════════════════════════════════════════════════════════════════
# Legitimate Interest Assessments (SENT-14)
# ═════════════════════════════════════════════════════════════════════════════

_LIA_FIELDS = [
    "ropa_id", "title", "regulation",
    "purpose_desc", "purpose_legit", "purpose_notes",
    "necessity_desc", "necessity_pass", "alternatives", "necessity_notes",
    "subject_impact", "safeguards", "reasonable_exp", "override_ok", "balance_notes",
    "overall_result", "overall_score", "dpo_reviewed", "dpo_notes", "created_by",
]


def create_lia(data):
    data.setdefault("regulation", _primary_jurisdiction_key())
    data.setdefault("overall_result", "pending")
    return _generic_create("sentinel_lia", _LIA_FIELDS, data)


def update_lia(lia_id, data):
    # Auto-calculate overall result from three parts
    p1 = data.get("purpose_legit")
    p2 = data.get("necessity_pass")
    p3 = data.get("override_ok")
    if p1 is not None and p2 is not None and p3 is not None:
        score = int(bool(p1)) + int(bool(p2)) + int(bool(p3))
        data["overall_score"] = score
        data["overall_result"] = (
            "passed" if score == 3 else
            "review_needed" if score == 2 else
            "failed"
        )
    _generic_update("sentinel_lia", set(_LIA_FIELDS), data, lia_id)


def get_lia(lia_id):
    return _generic_get("sentinel_lia", lia_id)


def delete_lia(lia_id):
    _generic_delete("sentinel_lia", lia_id)


def list_lia(ropa_id=None, result=None, limit=200, bu_scope=None):
    """An LIA has no unit of its own: it sits where its RoPA entry sits, and is organization wide without one."""
    sql = "SELECT l.*, r.processing_name AS ropa_name FROM sentinel_lia l " \
          "LEFT JOIN sentinel_ropa r ON r.id=l.ropa_id WHERE 1=1"
    params = []
    if ropa_id:
        sql += " AND l.ropa_id=%s"
        params.append(ropa_id)
    if result:
        sql += " AND l.overall_result=%s"
        params.append(result)
    unit, unit_params = unit_scope_sql(bu_scope, "r.business_unit_id")
    sql += unit
    params.extend(unit_params)
    sql += " ORDER BY l.updated_at DESC LIMIT %s"
    params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# Compliance Score
# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
# Jurisdiction Configuration
# ═════════════════════════════════════════════════════════════════════════════

def get_active_jurisdictions() -> list[dict]:
    """Active jurisdictions merged with registry rules."""
    from modules.sentinel.jurisdictions import JURISDICTION_RULES
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM sentinel_jurisdiction_config "
            "WHERE is_active=1 ORDER BY is_primary DESC, jurisdiction_key ASC"
        ).fetchall()
    finally:
        db.close()
    result = []
    for r in rows:
        entry = dict(r)
        entry.update(JURISDICTION_RULES.get(r["jurisdiction_key"], {}))
        result.append(entry)
    return result


def get_all_jurisdiction_configs() -> list[dict]:
    """All configured jurisdictions (active and inactive) merged with registry."""
    from modules.sentinel.jurisdictions import JURISDICTION_RULES
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM sentinel_jurisdiction_config "
            "ORDER BY is_primary DESC, jurisdiction_key ASC"
        ).fetchall()
    finally:
        db.close()
    result = []
    for r in rows:
        entry = dict(r)
        entry.update(JURISDICTION_RULES.get(r["jurisdiction_key"], {}))
        result.append(entry)
    return result


def activate_jurisdiction(key: str, is_primary: bool = False, **config) -> None:
    """Enable a jurisdiction (upsert). Sets is_primary=True if requested."""
    now = _now()
    db = get_db()
    try:
        if is_primary:
            db.execute("UPDATE sentinel_jurisdiction_config SET is_primary=0")
        db.execute(
            "INSERT INTO sentinel_jurisdiction_config "
            "(jurisdiction_key, is_active, is_primary, regulator_contact, "
            " registration_number, dpo_name, dpo_email, notes, activated_at) "
            "VALUES (%(key)s,1,%(pri)s,%(rc)s,%(rn)s,%(dn)s,%(de)s,%(nt)s,%(now)s) "
            "ON CONFLICT(jurisdiction_key) DO UPDATE SET "
            "is_active=1, is_primary=%(pri)s, activated_at=%(now)s",
            {
                "key": key, "pri": 1 if is_primary else 0,
                "rc": config.get("regulator_contact"),
                "rn": config.get("registration_number"),
                "dn": config.get("dpo_name"),
                "de": config.get("dpo_email"),
                "nt": config.get("notes"),
                "now": now,
            },
        )
        db.commit()
    finally:
        db.close()


def deactivate_jurisdiction(key: str) -> None:
    """Disable a jurisdiction (keeps config row, marks inactive)."""
    db = get_db()
    try:
        db.execute(
            "UPDATE sentinel_jurisdiction_config SET is_active=0 WHERE jurisdiction_key=%s",
            (key,),
        )
        db.commit()
    finally:
        db.close()


def update_jurisdiction_config(key: str, data: dict) -> None:
    """Update org-specific fields for a jurisdiction (DPO, reg number, notes, etc.)."""
    allowed = {"regulator_contact", "registration_number", "dpo_name", "dpo_email",
               "notes", "is_primary"}
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=%({k})s")
            params[k] = v
    if not sets:
        return
    params["key"] = key
    db = get_db()
    try:
        if data.get("is_primary"):
            db.execute("UPDATE sentinel_jurisdiction_config SET is_primary=0")
        db.execute(
            f"UPDATE sentinel_jurisdiction_config SET {','.join(sets)} "
            "WHERE jurisdiction_key=%(key)s",
            params,
        )
        db.commit()
    finally:
        db.close()


def get_jurisdiction_stats(bu_scope=None) -> list[dict]:
    """Per-jurisdiction record counts across ropa / breaches / dsrs / dpias, of what `bu_scope` can open."""
    unit, unit_params = unit_scope_sql(bu_scope)
    db = get_db()
    try:
        def per_regulation(table):
            rows = db.execute(
                f"SELECT regulation,COUNT(*) FROM {table} WHERE 1=1{unit} GROUP BY regulation", unit_params
            ).fetchall()
            return {r[0]: r[1] for r in rows if r[0]}
        ropa_map = per_regulation("sentinel_ropa")
        breach_map = per_regulation("sentinel_breaches")
        dsr_map = per_regulation("sentinel_dsr")
        dpia_map = per_regulation("sentinel_dpias")
    finally:
        db.close()
    all_keys = set(list(ropa_map) + list(breach_map) + list(dsr_map) + list(dpia_map))
    return [
        {
            "regulation": k,
            "ropa":     ropa_map.get(k, 0),
            "breaches": breach_map.get(k, 0),
            "dsrs":     dsr_map.get(k, 0),
            "dpias":    dpia_map.get(k, 0),
            "total":    ropa_map.get(k, 0) + breach_map.get(k, 0) + dsr_map.get(k, 0) + dpia_map.get(k, 0),
        }
        for k in sorted(all_keys)
    ]


# What each part of the compliance score is worth. A part with nothing to measure takes no share of the overall.
SCORE_WEIGHTS = {"ropa_completeness": 25, "dpia_coverage": 25, "breach_response": 20, "dsr_closure": 15, "vendor_compliance": 15}


def get_compliance_score(bu_scope=None):
    """The score of what `bu_scope` (bu_scope_ids) can open; None, a super administrator, scores everything.

    A part with nothing to measure (no breach recorded, no data subject request, no vendor) has no score: `score` is None and
    the part takes no share of the overall, which is worked out over the weights of the parts that were measured. Such a part
    used to score 100, so a module with nothing recorded read as a B. The overall is None, and the grade "N/A", when nothing
    could be measured. Percentages are rounded half up, as the pages and the reports round them."""
    db = get_db()
    try:
        count = _unit_counter(db, bu_scope)
        # data_categories is a JSON list: an entry saved with the list emptied holds '[]', which names no category.
        ropa_complete = count(
            "sentinel_ropa",
            "purpose IS NOT NULL AND legal_basis IS NOT NULL "
            "AND data_categories IS NOT NULL AND purpose!='' AND legal_basis!='' AND data_categories NOT IN ('', '[]')",
        )
        high_risk = "(risk_level IN ('high','critical') OR dpia_required=1)"
        measures = {
            "ropa_completeness": ("RoPA Completeness", count("sentinel_ropa"), ropa_complete),
            "dpia_coverage": ("DPIA Coverage", count("sentinel_ropa", high_risk),
                              count("sentinel_ropa", f"{high_risk} AND dpia_id IS NOT NULL")),
            "breach_response": ("Breach Resolution", count("sentinel_breaches"),
                                count("sentinel_breaches", "status IN ('resolved','closed','contained')")),
            "dsr_closure": ("DSR Closure", count("sentinel_dsr"), count("sentinel_dsr", "status IN ('closed','completed')")),
            "vendor_compliance": ("Vendor DPA", count("sentinel_vendors"),
                                  count("sentinel_vendors", "dpa_status IN ('Active','Signed','Executed','Compliant')")),
        }
    finally:
        db.close()

    scores = {key: {"score": pct(done, total), "label": label, "total": total, "done": done, "weight": SCORE_WEIGHTS[key]}
              for key, (label, total, done) in measures.items()}
    measured = [s for s in scores.values() if s["score"] is not None]
    weight = sum(s["weight"] for s in measured)
    overall = pct(sum(s["score"] * s["weight"] for s in measured), weight * 100) if weight else None
    grade = ("N/A" if overall is None else "A" if overall >= 90 else "B" if overall >= 75 else "C" if overall >= 60
             else "D" if overall >= 40 else "F")
    return {"overall": overall, "breakdown": scores, "grade": grade}
