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
from database import get_db, insert_returning_id, sql_current_date

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


# ── Row converters ───────────────────────────────────────────────────────────

def _ropa_row(row):
    d = dict(row)
    for f in ("data_categories", "special_categories", "processors", "recipients", "security_measures"):
        d[f] = _parse_json(d.get(f), [])
    return d


def _dpia_row(row):
    d = dict(row)
    d["data_categories"] = _parse_json(d.get("data_categories"), [])
    d["special_cats"] = _parse_json(d.get("special_cats"), [])
    d["risks"] = _parse_json(d.get("risks"), [])
    return d


def _breach_row(row):
    d = dict(row)
    d["data_types"] = _parse_json(d.get("data_types"), [])
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


def create_ropa(data):
    data.setdefault("processing_name", "Untitled Entry")
    data.setdefault("regulation", _primary_jurisdiction_key())
    data.setdefault("status", "active")
    data.setdefault("risk_level", "low")
    return _generic_create("sentinel_ropa", _ROPA_FIELDS, data, ref_prefix="ROPA", json_fields=_ROPA_JSON)


def update_ropa(ropa_id, data):
    _generic_update("sentinel_ropa", set(_ROPA_FIELDS), data, ropa_id, json_fields=_ROPA_JSON)

def get_ropa(ropa_id):
    return _generic_get("sentinel_ropa", ropa_id, _ropa_row)

def delete_ropa(ropa_id):
    _generic_delete("sentinel_ropa", ropa_id)


def list_ropa(search=None, regulation=None, status=None, risk=None, limit=500, bu_scope=None):
    sql = "SELECT * FROM sentinel_ropa WHERE 1=1"
    params = []
    if search:
        sql += " AND (processing_name LIKE %s OR department LIKE %s OR owner LIKE %s)"
        like = f"%{search}%"
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
    return [_ropa_row(r) for r in rows]


# ═════════════════════════════════════════════════════════════════════════════
# DPIA
# ═════════════════════════════════════════════════════════════════════════════

_DPIA_FIELDS = [
    "title", "status", "regulation", "org_name", "department", "controller_name",
    "dpo_name", "dpo_email", "activity_type", "activity_desc", "purpose", "legal_basis",
    "data_categories", "special_cats", "data_subjects", "subject_count", "retention",
    "systems", "processors", "intl_transfer", "transfer_dest", "transfer_mech",
    "necessity", "proportionality", "risks", "overall_risk", "residual_risk",
    "dpo_consulted", "auth_consulted", "subjects_consulted", "consult_notes",
    "ai_research", "ai_full_dpia", "ropa_id",
]
_DPIA_JSON = ["data_categories", "special_cats", "risks"]


def create_dpia(data):
    data.setdefault("title", "Untitled DPIA")
    data.setdefault("status", "draft")
    data.setdefault("regulation", _primary_jurisdiction_key())
    for f in _DPIA_JSON:
        data.setdefault(f, "[]")
    return _generic_create("sentinel_dpias", _DPIA_FIELDS, data, ref_prefix="DPIA", json_fields=_DPIA_JSON)


def update_dpia(dpia_id, data):
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
        sql += " AND (d.title LIKE %s OR d.org_name LIKE %s OR d.activity_type LIKE %s)"
        like = f"%{search}%"
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
# AIIA — AI Impact Assessments (PLAN-20)
# ═════════════════════════════════════════════════════════════════════════════

_AIIA_FIELDS = [
    "title", "ai_system_name", "application_id", "department", "owner",
    "system_description", "business_process", "deployment_env",
    "third_party", "third_party_details", "outputs_decisions",
    "influences_customers", "autonomy_level", "data_categories",
    "sensitive_data", "stakeholders_direct", "stakeholders_indirect",
    "mitigation_measures", "residual_classification",
    "status", "ropa_id", "dpia_id", "business_unit_id", "created_by",
]
_AIIA_BOOL_FIELDS = ("third_party", "influences_customers", "sensitive_data")


def _normalize_aiia_bools(data):
    for f in _AIIA_BOOL_FIELDS:
        if f in data:
            data[f] = 1 if data[f] else 0


def _aiia_row(row):
    d = dict(row)
    d["data_categories"] = _parse_json(d.get("data_categories"), [])
    return d


def _get_aiia_impacts(db, aiia_id):
    """One row per currently-active dimension (an unscored placeholder if it
    has no row yet) plus any existing scored rows for dimensions that are no
    longer active -- history survives a deactivation or a rename-away."""
    active_dims = [r["name"] for r in db.execute(
        "SELECT name FROM sentinel_aiia_dimensions WHERE is_active=1 ORDER BY order_idx, name"
    ).fetchall()]
    existing = {r["dimension_name"]: dict(r) for r in db.execute(
        "SELECT * FROM sentinel_aiia_impacts WHERE aiia_id=%s", (aiia_id,)
    ).fetchall()}
    rows = []
    for name in active_dims:
        if name in existing:
            rows.append(existing.pop(name))
        else:
            rows.append({"aiia_id": aiia_id, "dimension_name": name, "applicable": 1,
                         "description": None, "likelihood": None, "impact": None})
    rows.extend(existing.values())
    return rows


def _save_aiia_impacts(db, aiia_id, impacts):
    """Replace all impact rows. Each entry:
    {dimension_name, applicable, description, likelihood, impact}."""
    db.execute("DELETE FROM sentinel_aiia_impacts WHERE aiia_id=%s", (aiia_id,))
    for imp in (impacts or []):
        name = str(imp.get("dimension_name") or "").strip()
        if not name:
            continue
        lik, impv = imp.get("likelihood"), imp.get("impact")
        db.execute(
            "INSERT INTO sentinel_aiia_impacts "
            "(aiia_id, dimension_name, applicable, description, likelihood, impact) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (aiia_id, name, 1 if imp.get("applicable", True) else 0,
             imp.get("description"),
             max(1, min(5, int(lik))) if lik not in (None, "") else None,
             max(1, min(5, int(impv))) if impv not in (None, "") else None),
        )


def _compute_aiia_classification(db, impacts):
    """Band of the highest L*I product among applicable, scored rows.
    Returns 'unrated' when no ERM framework is active -- never silently
    reuse resolve_band's generic fallback band for a classification the
    user never actually chose. Returns None when nothing is scored yet."""
    from modules.erm.data_service import get_active_framework_matrix, resolve_band
    fw_matrix = get_active_framework_matrix(db)
    if not fw_matrix["matrix"]:
        return "unrated"
    best, best_product = None, -1
    for imp in (impacts or []):
        if not imp.get("applicable", True):
            continue
        L, I = imp.get("likelihood"), imp.get("impact")
        if L is None or I is None:
            continue
        product = int(L) * int(I)
        if product > best_product:
            best_product, best = product, (int(L), int(I))
    if best is None:
        return None
    return resolve_band(fw_matrix, best[0], best[1])


def create_aiia(data):
    data.setdefault("title", "Untitled AI Impact Assessment")
    data.setdefault("status", "draft")
    data.setdefault("autonomy_level", "decision_support")
    _normalize_aiia_bools(data)
    if "data_categories" in data:
        data["data_categories"] = _to_json(data["data_categories"])
    impacts = data.pop("impacts", None)
    now = _now()
    db = get_db()
    try:
        params = {f: data.get(f) for f in _AIIA_FIELDS}
        params["ref_number"] = _gen_ref("AIIA")
        params["created_at"] = now
        params["updated_at"] = now
        cols = ["ref_number"] + _AIIA_FIELDS + ["created_at", "updated_at"]
        new_id = insert_returning_id(
            db,
            f"INSERT INTO sentinel_aiia ({', '.join(cols)}) "
            f"VALUES ({', '.join('%(' + c + ')s' for c in cols)})",
            params,
        )
        if impacts is not None:
            _save_aiia_impacts(db, new_id, impacts)
            classification = _compute_aiia_classification(db, _get_aiia_impacts(db, new_id))
            db.execute(
                "UPDATE sentinel_aiia SET overall_classification=%s, updated_at=%s WHERE id=%s",
                (classification, now, new_id),
            )
        db.commit()
        return new_id
    finally:
        db.close()


def update_aiia(aiia_id, data):
    _normalize_aiia_bools(data)
    if "data_categories" in data:
        data["data_categories"] = _to_json(data["data_categories"])
    impacts = data.pop("impacts", None)
    now = _now()
    db = get_db()
    try:
        sets, params = [], {}
        for k, v in data.items():
            if k in _AIIA_FIELDS:
                sets.append(f"{k}=%({k})s")
                params[k] = v
        if impacts is not None:
            _save_aiia_impacts(db, aiia_id, impacts)
            classification = _compute_aiia_classification(db, _get_aiia_impacts(db, aiia_id))
            sets.append("overall_classification=%(overall_classification)s")
            params["overall_classification"] = classification
        if sets:
            params["updated_at"] = now
            params["id"] = aiia_id
            db.execute(
                f"UPDATE sentinel_aiia SET {','.join(sets)}, updated_at=%(updated_at)s WHERE id=%(id)s",
                params,
            )
        db.commit()
    finally:
        db.close()


def get_aiia(aiia_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT a.*, r.ref_number AS ropa_ref, r.processing_name AS ropa_name, "
            "d.ref_number AS dpia_ref, d.title AS dpia_title "
            "FROM sentinel_aiia a "
            "LEFT JOIN sentinel_ropa r ON r.id = a.ropa_id "
            "LEFT JOIN sentinel_dpias d ON d.id = a.dpia_id "
            "WHERE a.id=%s",
            (aiia_id,),
        ).fetchone()
        if not row:
            return None
        result = _aiia_row(row)
        result["impacts"] = _get_aiia_impacts(db, aiia_id)
        return result
    finally:
        db.close()


def delete_aiia(aiia_id):
    db = get_db()
    try:
        db.execute("DELETE FROM sentinel_aiia_impacts WHERE aiia_id=%s", (aiia_id,))
        db.execute("DELETE FROM sentinel_aiia WHERE id=%s", (aiia_id,))
        db.commit()
    finally:
        db.close()


def list_aiias(search=None, status=None, limit=500, bu_scope=None):
    sql = (
        "SELECT a.*, r.ref_number AS ropa_ref, d.ref_number AS dpia_ref "
        "FROM sentinel_aiia a "
        "LEFT JOIN sentinel_ropa r ON r.id = a.ropa_id "
        "LEFT JOIN sentinel_dpias d ON d.id = a.dpia_id "
        "WHERE 1=1"
    )
    params = []
    if search:
        sql += " AND (a.title LIKE %s OR a.ai_system_name LIKE %s)"
        like = f"%{search}%"
        params += [like, like]
    if status:
        sql += " AND a.status=%s"
        params.append(status)
    if bu_scope is not None:
        ph = ",".join(["%s"] * len(bu_scope))
        sql += f" AND (a.business_unit_id IN ({ph}) OR a.business_unit_id IS NULL)"
        params.extend(bu_scope)
    sql += " ORDER BY a.updated_at DESC LIMIT %s"
    params.append(limit)
    db = get_db()
    try:
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()
    return [_aiia_row(r) for r in rows]


def list_aiia_dimensions(include_inactive=True):
    db = get_db()
    try:
        sql = "SELECT * FROM sentinel_aiia_dimensions"
        if not include_inactive:
            sql += " WHERE is_active=1"
        sql += " ORDER BY order_idx, name"
        rows = db.execute(sql).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]


def save_aiia_dimensions(dimensions):
    """Upsert the dimension list. Each entry: {id?, name, order_idx?,
    is_active?}. Renaming an existing dimension propagates the new name
    onto every historical sentinel_aiia_impacts row so scored history
    follows it, instead of orphaning it under the old name. Dimensions
    not mentioned in the payload are left untouched (this is an upsert,
    not a destructive full-sync)."""
    db = get_db()
    try:
        existing = {r["id"]: dict(r) for r in db.execute(
            "SELECT * FROM sentinel_aiia_dimensions"
        ).fetchall()}
        existing_names = {r["name"].strip().lower(): r["id"] for r in existing.values()}
        for dim in (dimensions or []):
            dim_id = dim.get("id")
            name = str(dim.get("name") or "").strip()
            if not name:
                raise ValueError("Dimension name is required")
            order_idx = dim.get("order_idx", 0)
            is_active = 1 if dim.get("is_active", True) else 0
            collision_id = existing_names.get(name.lower())
            if collision_id is not None and collision_id != dim_id:
                raise ValueError(f"A dimension named '{name}' already exists")
            if dim_id and dim_id in existing:
                old_name = existing[dim_id]["name"]
                db.execute(
                    "UPDATE sentinel_aiia_dimensions SET name=%s, order_idx=%s, is_active=%s WHERE id=%s",
                    (name, order_idx, is_active, dim_id),
                )
                if old_name != name:
                    db.execute(
                        "UPDATE sentinel_aiia_impacts SET dimension_name=%s WHERE dimension_name=%s",
                        (name, old_name),
                    )
            else:
                new_id = insert_returning_id(
                    db,
                    "INSERT INTO sentinel_aiia_dimensions (name, order_idx, is_active) VALUES (%s,%s,%s)",
                    (name, order_idx, is_active),
                )
                existing_names[name.lower()] = new_id
        db.commit()
    finally:
        db.close()


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


def create_breach(data):
    data.setdefault("title", "Untitled Incident")
    data.setdefault("regulation", _primary_jurisdiction_key())
    data.setdefault("severity", "medium")
    data.setdefault("status", "open")
    if data.get("discovery_date"):
        try:
            from modules.sentinel.jurisdictions import get_breach_deadline_hours
            hours = get_breach_deadline_hours(data.get("regulation", "GDPR"))
            disc = to_dt(data["discovery_date"][:10])
            data["notify_deadline"] = (disc + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return _generic_create("sentinel_breaches", _BREACH_FIELDS, data, ref_prefix="BRE", json_fields=["data_types"])


def update_breach(bid, data):
    _generic_update("sentinel_breaches", set(_BREACH_FIELDS), data, bid, json_fields=["data_types"])

def get_breach(bid):
    return _generic_get("sentinel_breaches", bid, _breach_row)

def delete_breach(bid):
    _generic_delete("sentinel_breaches", bid)


def list_breaches(search=None, status=None, severity=None, limit=500, bu_scope=None):
    sql = "SELECT * FROM sentinel_breaches WHERE 1=1"
    params = []
    if search:
        sql += " AND (title LIKE %s OR description LIKE %s)"
        like = f"%{search}%"
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


def update_dsr(dsr_id, data):
    _generic_update("sentinel_dsr", set(_DSR_FIELDS), data, dsr_id)


def get_dsr(dsr_id):
    return _generic_get("sentinel_dsr", dsr_id)


def delete_dsr(dsr_id):
    _generic_delete("sentinel_dsr", dsr_id)


def list_dsrs(search=None, status=None, request_type=None, limit=500):
    sql = "SELECT * FROM sentinel_dsr WHERE 1=1"
    params = []
    if search:
        sql += " AND (requester_name LIKE %s OR requester_email LIKE %s OR description LIKE %s)"
        like = f"%{search}%"
        params += [like, like, like]
    if status:
        sql += " AND status=%s"
        params.append(status)
    if request_type:
        sql += " AND request_type=%s"
        params.append(request_type)
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
        sql += " AND (name LIKE %s OR services LIKE %s OR country LIKE %s)"
        like = f"%{search}%"
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

_NOTICE_FIELDS = ["title", "regulation", "audience", "version", "content", "status", "review_date", "published_date"]

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

def list_consent(search=None, status=None, limit=500):
    sql = "SELECT * FROM sentinel_consent WHERE 1=1"
    params = []
    if search:
        sql += " AND (subject_name LIKE %s OR subject_email LIKE %s OR purpose LIKE %s)"
        like = f"%{search}%"
        params += [like, like, like]
    if status:
        sql += " AND status=%s"
        params.append(status)
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
    "org_name", "registration_number", "country", "address", "sector",
    "controller_name", "controller_email", "controller_phone",
    "dpo_name", "dpo_email", "dpo_phone",
    "regulator_name", "regulator_ref", "regulation", "is_primary", "notes",
]

def create_controller(data):
    data.setdefault("org_name", "Unnamed Organisation")
    return _generic_create("sentinel_controllers", _CTRL_FIELDS, data)

def update_controller(cid, data):
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
    "ropa_id", "destination", "recipient", "transfer_type", "safeguards",
    "safeguard_detail", "regulation", "adequacy_decision", "data_types",
    "frequency", "volume", "status", "review_date", "notes",
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
    "trigger_event", "deletion_method", "responsible", "review_date", "notes",
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
    "implementation_date", "review_date", "responsible", "evidence", "regulation", "notes",
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
    "title", "type", "version", "status", "owner", "department",
    "regulation", "content", "file_path", "file_name", "review_date",
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
        sql += " AND (title LIKE %s OR owner LIKE %s OR department LIKE %s)"
        like = f"%{search}%"
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
        sql += " AND (staff_name LIKE %s OR training_name LIKE %s OR department LIKE %s)"
        like = f"%{search}%"
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

def list_dataflows(limit=500):
    return _generic_list("sentinel_data_flows", order="created_at DESC", limit=limit)


# ═════════════════════════════════════════════════════════════════════════════
# Settings (uses shared settings table)
# ═════════════════════════════════════════════════════════════════════════════

def get_setting(key, default=None):
    db = get_db()
    try:
        row = db.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
    finally:
        db.close()
    return row["value"] if row else default


def set_setting(key, value):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO settings(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        db.commit()
    finally:
        db.close()


def get_all_settings():
    db = get_db()
    try:
        rows = db.execute("SELECT key, value FROM settings").fetchall()
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

def get_stats():
    db = get_db()
    try:
        ropa_total = db.execute("SELECT COUNT(*) FROM sentinel_ropa").fetchone()[0]
        dpia_total = db.execute("SELECT COUNT(*) FROM sentinel_dpias").fetchone()[0]
        dpia_draft = db.execute("SELECT COUNT(*) FROM sentinel_dpias WHERE status='draft'").fetchone()[0]
        dpia_approved = db.execute("SELECT COUNT(*) FROM sentinel_dpias WHERE status='approved'").fetchone()[0]
        breach_open = db.execute("SELECT COUNT(*) FROM sentinel_breaches WHERE status='open'").fetchone()[0]
        breach_critical = db.execute("SELECT COUNT(*) FROM sentinel_breaches WHERE severity='critical'").fetchone()[0]
        dsr_open = db.execute("SELECT COUNT(*) FROM sentinel_dsr WHERE status='open'").fetchone()[0]
        dsr_overdue = db.execute(
            f"SELECT COUNT(*) FROM sentinel_dsr WHERE status='open' AND deadline_date < {sql_current_date()}"
        ).fetchone()[0]
        vendor_total = db.execute("SELECT COUNT(*) FROM sentinel_vendors").fetchone()[0]
        high_risk_ropa = db.execute(
            "SELECT COUNT(*) FROM sentinel_ropa WHERE risk_level IN ('high','critical')"
        ).fetchone()[0]
        dpia_required = db.execute(
            "SELECT COUNT(*) FROM sentinel_ropa WHERE dpia_required=1"
        ).fetchone()[0]
        consent_active = db.execute(
            "SELECT COUNT(*) FROM sentinel_consent WHERE status='active'"
        ).fetchone()[0]
        notices_total = db.execute("SELECT COUNT(*) FROM sentinel_privacy_notices").fetchone()[0]
        policy_total = db.execute("SELECT COUNT(*) FROM sentinel_policies").fetchone()[0]
        training_total = db.execute("SELECT COUNT(*) FROM sentinel_training").fetchone()[0]
        by_reg = db.execute(
            "SELECT regulation, COUNT(*) c FROM sentinel_ropa GROUP BY regulation"
        ).fetchall()
        risk_dist = db.execute(
            "SELECT risk_level, COUNT(*) c FROM sentinel_ropa GROUP BY risk_level"
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


def list_lia(ropa_id=None, result=None, limit=200):
    sql = "SELECT l.*, r.processing_name AS ropa_name FROM sentinel_lia l " \
          "LEFT JOIN sentinel_ropa r ON r.id=l.ropa_id WHERE 1=1"
    params = []
    if ropa_id:
        sql += " AND l.ropa_id=%s"
        params.append(ropa_id)
    if result:
        sql += " AND l.overall_result=%s"
        params.append(result)
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


def get_jurisdiction_stats() -> list[dict]:
    """Per-jurisdiction record counts across ropa / breaches / dsrs / dpias."""
    db = get_db()
    try:
        ropa_map   = {r[0]: r[1] for r in db.execute("SELECT regulation,COUNT(*) FROM sentinel_ropa GROUP BY regulation").fetchall() if r[0]}
        breach_map = {r[0]: r[1] for r in db.execute("SELECT regulation,COUNT(*) FROM sentinel_breaches GROUP BY regulation").fetchall() if r[0]}
        dsr_map    = {r[0]: r[1] for r in db.execute("SELECT regulation,COUNT(*) FROM sentinel_dsr GROUP BY regulation").fetchall() if r[0]}
        dpia_map   = {r[0]: r[1] for r in db.execute("SELECT regulation,COUNT(*) FROM sentinel_dpias GROUP BY regulation").fetchall() if r[0]}
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


def get_compliance_score():
    db = get_db()
    try:
        scores = {}
        ropa_total = db.execute("SELECT COUNT(*) FROM sentinel_ropa").fetchone()[0]
        ropa_complete = db.execute(
            "SELECT COUNT(*) FROM sentinel_ropa WHERE purpose IS NOT NULL AND legal_basis IS NOT NULL "
            "AND data_categories IS NOT NULL AND purpose!='' AND legal_basis!='' AND data_categories!=''"
        ).fetchone()[0]
        scores["ropa_completeness"] = {
            "score": round(ropa_complete / ropa_total * 100) if ropa_total else 0,
            "label": "RoPA Completeness", "total": ropa_total, "done": ropa_complete,
        }

        hr_ropa = db.execute(
            "SELECT COUNT(*) FROM sentinel_ropa WHERE risk_level IN ('high','critical') OR dpia_required=1"
        ).fetchone()[0]
        hr_with_dpia = db.execute(
            "SELECT COUNT(*) FROM sentinel_ropa WHERE (risk_level IN ('high','critical') OR dpia_required=1) AND dpia_id IS NOT NULL"
        ).fetchone()[0]
        scores["dpia_coverage"] = {
            "score": round(hr_with_dpia / hr_ropa * 100) if hr_ropa else 100,
            "label": "DPIA Coverage", "total": hr_ropa, "done": hr_with_dpia,
        }

        breach_total = db.execute("SELECT COUNT(*) FROM sentinel_breaches").fetchone()[0]
        breach_resolved = db.execute(
            "SELECT COUNT(*) FROM sentinel_breaches WHERE status IN ('resolved','closed','contained')"
        ).fetchone()[0]
        scores["breach_response"] = {
            "score": round(breach_resolved / breach_total * 100) if breach_total else 100,
            "label": "Breach Resolution", "total": breach_total, "done": breach_resolved,
        }

        dsr_total = db.execute("SELECT COUNT(*) FROM sentinel_dsr").fetchone()[0]
        dsr_closed = db.execute(
            "SELECT COUNT(*) FROM sentinel_dsr WHERE status IN ('closed','completed')"
        ).fetchone()[0]
        scores["dsr_closure"] = {
            "score": round(dsr_closed / dsr_total * 100) if dsr_total else 100,
            "label": "DSR Closure", "total": dsr_total, "done": dsr_closed,
        }

        vendor_total = db.execute("SELECT COUNT(*) FROM sentinel_vendors").fetchone()[0]
        vendor_dpa = db.execute(
            "SELECT COUNT(*) FROM sentinel_vendors WHERE dpa_status IN ('Active','Signed','Executed','Compliant')"
        ).fetchone()[0]
        scores["vendor_compliance"] = {
            "score": round(vendor_dpa / vendor_total * 100) if vendor_total else 100,
            "label": "Vendor DPA", "total": vendor_total, "done": vendor_dpa,
        }
    finally:
        db.close()

    weights = {
        "ropa_completeness": 25, "dpia_coverage": 25,
        "breach_response": 20, "dsr_closure": 15, "vendor_compliance": 15,
    }
    weighted = sum(scores.get(k, {}).get("score", 0) * w for k, w in weights.items())
    total_w = sum(weights.values())
    overall = round(weighted / total_w) if total_w else 0
    grade = "A" if overall >= 90 else "B" if overall >= 75 else "C" if overall >= 60 else "D" if overall >= 40 else "F"
    return {"overall": overall, "breakdown": scores, "grade": grade}
