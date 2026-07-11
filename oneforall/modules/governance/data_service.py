"""
Governance module — Data access layer for the Governance Graph node types
(Tier 1 T1.1): business_units, departments, business_processes, applications,
data_assets.

These are shared, cross-module organisational entities. Every other module's
scoped tables (risks, controls, policies, evidence, audits, plans, etc.)
reference these via optional business_unit_id / department_id / etc. FKs.
"""
from database import get_db, insert_returning_id
from core.timeutils import utcnow


def _dicts(rows):
    return [dict(r) for r in rows]


def _dict(row):
    return dict(row) if row else None


def _now():
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ═════════════════════════════════════════════════════════════════════════════
# BUSINESS UNITS (self-referential SBU hierarchy)
# ═════════════════════════════════════════════════════════════════════════════

def list_business_units(include_inactive: bool = False) -> list[dict]:
    db = get_db()
    try:
        sql = ("SELECT bu.*, "
               "(SELECT full_name FROM users WHERE id=bu.head_user_id) AS head_name, "
               "(SELECT COUNT(*) FROM business_units c WHERE c.parent_id=bu.id) AS child_count "
               "FROM business_units bu")
        if not include_inactive:
            sql += " WHERE bu.is_active=1"
        sql += " ORDER BY bu.parent_id NULLS FIRST, bu.name"
        return _dicts(db.execute(sql).fetchall())
    finally:
        db.close()


def get_business_unit(bu_id: int) -> dict | None:
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM business_units WHERE id=%s", (bu_id,)).fetchone())
    finally:
        db.close()


def get_business_unit_tree() -> list[dict]:
    """Return active business_units as a nested tree by parent_id.

    Root nodes (parent_id IS NULL) hold `children: [...]` lists. Depth is
    bounded by the DB — a caller with 100 SBUs still gets a fast one-pass tree.
    """
    flat = list_business_units(include_inactive=False)
    by_id = {b["id"]: {**b, "children": []} for b in flat}
    roots = []
    for b in flat:
        node = by_id[b["id"]]
        pid = b.get("parent_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(node)
        else:
            roots.append(node)
    return roots


def create_business_unit(data: dict) -> int:
    db = get_db()
    try:
        new_id = insert_returning_id(db,
            "INSERT INTO business_units "
            "(name, code, description, parent_id, head_user_id, is_active) "
            "VALUES (%s, %s, %s, %s, %s, 1)",
            (data.get("name", "").strip(),
             (data.get("code") or "").strip() or None,
             data.get("description") or None,
             data.get("parent_id"),
             data.get("head_user_id")),
        )
        db.commit()
        return new_id
    finally:
        db.close()


def update_business_unit(bu_id: int, data: dict) -> bool:
    db = get_db()
    try:
        # Guard: a BU cannot be its own ancestor (prevents cycles).
        new_parent = data.get("parent_id")
        if new_parent and int(new_parent) == int(bu_id):
            return False
        if new_parent and _is_descendant(db, int(new_parent), int(bu_id)):
            return False
        db.execute(
            "UPDATE business_units SET "
            "name=%s, code=%s, description=%s, parent_id=%s, head_user_id=%s, "
            "is_active=%s, updated_at=%s WHERE id=%s",
            (data.get("name", "").strip(),
             (data.get("code") or "").strip() or None,
             data.get("description") or None,
             new_parent,
             data.get("head_user_id"),
             1 if data.get("is_active", 1) else 0,
             _now(), bu_id),
        )
        db.commit()
        return True
    finally:
        db.close()


def delete_business_unit(bu_id: int) -> bool:
    """Delete a BU only if no children and no scoped entities reference it.

    Safer than a CASCADE — governance data should be preserved. Callers can
    reassign entities to the parent BU first if they really want to delete.
    """
    db = get_db()
    try:
        children = db.execute(
            "SELECT COUNT(*) FROM business_units WHERE parent_id=%s", (bu_id,)
        ).fetchone()[0]
        if children:
            return False
        # Check references — if any scoped entity uses this BU, refuse.
        for tbl in ("erm_enterprise_risks", "orm_events", "orm_rcsa_assessments",
                    "aria_documents", "aria_controls", "grid_audits",
                    "sentinel_ropa", "sentinel_breaches", "sentinel_dpias",
                    "bcm_plans", "bcm_bia_records", "bcm_incidents",
                    "evidence_items", "task_board", "departments",
                    "business_processes", "applications", "data_assets"):
            try:
                cnt = db.execute(
                    f"SELECT COUNT(*) FROM {tbl} WHERE business_unit_id=%s", (bu_id,)
                ).fetchone()[0]
                if cnt:
                    return False
            except Exception:
                # Table or column may not exist yet in older migrations — skip.
                continue
        db.execute("DELETE FROM business_units WHERE id=%s", (bu_id,))
        db.commit()
        return True
    finally:
        db.close()


def _is_descendant(db, candidate_id: int, ancestor_id: int) -> bool:
    """True if candidate_id is anywhere below ancestor_id in the tree."""
    current = candidate_id
    depth = 0
    while current and depth < 50:
        row = db.execute("SELECT parent_id FROM business_units WHERE id=%s", (current,)).fetchone()
        if not row:
            return False
        pid = row[0]
        if pid == ancestor_id:
            return True
        current = pid
        depth += 1
    return False


# ═════════════════════════════════════════════════════════════════════════════
# DEPARTMENTS
# ═════════════════════════════════════════════════════════════════════════════

def list_departments(bu_id: int | None = None, include_inactive: bool = False) -> list[dict]:
    db = get_db()
    try:
        sql = ("SELECT d.*, bu.name AS bu_name, "
               "(SELECT full_name FROM users WHERE id=d.head_user_id) AS head_name "
               "FROM departments d LEFT JOIN business_units bu ON bu.id=d.business_unit_id")
        clauses, params = [], []
        if not include_inactive:
            clauses.append("d.is_active=1")
        if bu_id:
            clauses.append("d.business_unit_id=%s")
            params.append(bu_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY d.name"
        return _dicts(db.execute(sql, tuple(params)).fetchall())
    finally:
        db.close()


def create_department(data: dict) -> int:
    db = get_db()
    try:
        new_id = insert_returning_id(db,
            "INSERT INTO departments "
            "(name, code, description, business_unit_id, head_user_id, is_active) "
            "VALUES (%s, %s, %s, %s, %s, 1)",
            (data.get("name", "").strip(),
             (data.get("code") or "").strip() or None,
             data.get("description") or None,
             data.get("business_unit_id"),
             data.get("head_user_id")),
        )
        db.commit()
        return new_id
    finally:
        db.close()


def update_department(dept_id: int, data: dict) -> bool:
    db = get_db()
    try:
        db.execute(
            "UPDATE departments SET name=%s, code=%s, description=%s, "
            "business_unit_id=%s, head_user_id=%s, is_active=%s, updated_at=%s "
            "WHERE id=%s",
            (data.get("name", "").strip(),
             (data.get("code") or "").strip() or None,
             data.get("description") or None,
             data.get("business_unit_id"),
             data.get("head_user_id"),
             1 if data.get("is_active", 1) else 0,
             _now(), dept_id),
        )
        db.commit()
        return True
    finally:
        db.close()


def delete_department(dept_id: int) -> bool:
    db = get_db()
    try:
        for tbl in ("business_processes", "applications"):
            try:
                cnt = db.execute(
                    f"SELECT COUNT(*) FROM {tbl} WHERE department_id=%s", (dept_id,)
                ).fetchone()[0]
                if cnt:
                    return False
            except Exception:
                continue
        db.execute("DELETE FROM departments WHERE id=%s", (dept_id,))
        db.commit()
        return True
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# BUSINESS PROCESSES
# ═════════════════════════════════════════════════════════════════════════════

def list_business_processes(bu_id: int | None = None, dept_id: int | None = None,
                             include_inactive: bool = False) -> list[dict]:
    db = get_db()
    try:
        sql = ("SELECT bp.*, bu.name AS bu_name, d.name AS dept_name, "
               "(SELECT full_name FROM users WHERE id=bp.owner_user_id) AS owner_name "
               "FROM business_processes bp "
               "LEFT JOIN business_units bu ON bu.id=bp.business_unit_id "
               "LEFT JOIN departments d ON d.id=bp.department_id")
        clauses, params = [], []
        if not include_inactive:
            clauses.append("bp.is_active=1")
        if bu_id:
            clauses.append("bp.business_unit_id=%s")
            params.append(bu_id)
        if dept_id:
            clauses.append("bp.department_id=%s")
            params.append(dept_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY bp.name"
        return _dicts(db.execute(sql, tuple(params)).fetchall())
    finally:
        db.close()


def create_business_process(data: dict) -> int:
    db = get_db()
    try:
        new_id = insert_returning_id(db,
            "INSERT INTO business_processes "
            "(name, code, description, business_unit_id, department_id, owner_user_id, "
            "criticality, rto_hours, rpo_hours, revenue_impact_per_hour, is_active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
            (data.get("name", "").strip(),
             (data.get("code") or "").strip() or None,
             data.get("description") or None,
             data.get("business_unit_id"),
             data.get("department_id"),
             data.get("owner_user_id"),
             data.get("criticality", "medium"),
             data.get("rto_hours"),
             data.get("rpo_hours"),
             data.get("revenue_impact_per_hour")),
        )
        db.commit()
        return new_id
    finally:
        db.close()


def update_business_process(bp_id: int, data: dict) -> bool:
    db = get_db()
    try:
        db.execute(
            "UPDATE business_processes SET name=%s, code=%s, description=%s, "
            "business_unit_id=%s, department_id=%s, owner_user_id=%s, "
            "criticality=%s, rto_hours=%s, rpo_hours=%s, revenue_impact_per_hour=%s, "
            "is_active=%s, updated_at=%s WHERE id=%s",
            (data.get("name", "").strip(),
             (data.get("code") or "").strip() or None,
             data.get("description") or None,
             data.get("business_unit_id"),
             data.get("department_id"),
             data.get("owner_user_id"),
             data.get("criticality", "medium"),
             data.get("rto_hours"),
             data.get("rpo_hours"),
             data.get("revenue_impact_per_hour"),
             1 if data.get("is_active", 1) else 0,
             _now(), bp_id),
        )
        db.commit()
        return True
    finally:
        db.close()


def delete_business_process(bp_id: int) -> bool:
    db = get_db()
    try:
        db.execute("DELETE FROM business_processes WHERE id=%s", (bp_id,))
        db.commit()
        return True
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# APPLICATIONS
# ═════════════════════════════════════════════════════════════════════════════

def list_applications(bu_id: int | None = None, include_inactive: bool = False) -> list[dict]:
    db = get_db()
    try:
        sql = ("SELECT a.*, bu.name AS bu_name, d.name AS dept_name, "
               "cv.name AS vendor_name, "
               "(SELECT full_name FROM users WHERE id=a.owner_user_id) AS owner_name "
               "FROM applications a "
               "LEFT JOIN business_units bu ON bu.id=a.business_unit_id "
               "LEFT JOIN departments d ON d.id=a.department_id "
               "LEFT JOIN canonical_vendors cv ON cv.id=a.vendor_id")
        clauses, params = [], []
        if not include_inactive:
            clauses.append("a.is_active=1")
        if bu_id:
            clauses.append("a.business_unit_id=%s")
            params.append(bu_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY a.name"
        return _dicts(db.execute(sql, tuple(params)).fetchall())
    finally:
        db.close()


def create_application(data: dict) -> int:
    db = get_db()
    try:
        new_id = insert_returning_id(db,
            "INSERT INTO applications "
            "(name, description, application_type, hosting, vendor_id, "
            "business_unit_id, department_id, owner_user_id, criticality, is_active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
            (data.get("name", "").strip(),
             data.get("description") or None,
             data.get("application_type") or None,
             data.get("hosting") or None,
             data.get("vendor_id"),
             data.get("business_unit_id"),
             data.get("department_id"),
             data.get("owner_user_id"),
             data.get("criticality", "medium")),
        )
        db.commit()
        return new_id
    finally:
        db.close()


def update_application(app_id: int, data: dict) -> bool:
    db = get_db()
    try:
        db.execute(
            "UPDATE applications SET name=%s, description=%s, application_type=%s, "
            "hosting=%s, vendor_id=%s, business_unit_id=%s, department_id=%s, "
            "owner_user_id=%s, criticality=%s, is_active=%s, updated_at=%s WHERE id=%s",
            (data.get("name", "").strip(),
             data.get("description") or None,
             data.get("application_type") or None,
             data.get("hosting") or None,
             data.get("vendor_id"),
             data.get("business_unit_id"),
             data.get("department_id"),
             data.get("owner_user_id"),
             data.get("criticality", "medium"),
             1 if data.get("is_active", 1) else 0,
             _now(), app_id),
        )
        db.commit()
        return True
    finally:
        db.close()


def delete_application(app_id: int) -> bool:
    db = get_db()
    try:
        cnt = db.execute(
            "SELECT COUNT(*) FROM data_assets WHERE application_id=%s", (app_id,)
        ).fetchone()[0]
        if cnt:
            return False
        db.execute("DELETE FROM applications WHERE id=%s", (app_id,))
        db.commit()
        return True
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# DATA ASSETS
# ═════════════════════════════════════════════════════════════════════════════

def list_data_assets(bu_id: int | None = None, classification: str | None = None,
                      include_inactive: bool = False) -> list[dict]:
    db = get_db()
    try:
        sql = ("SELECT da.*, bu.name AS bu_name, a.name AS application_name, "
               "(SELECT full_name FROM users WHERE id=da.owner_user_id) AS owner_name "
               "FROM data_assets da "
               "LEFT JOIN business_units bu ON bu.id=da.business_unit_id "
               "LEFT JOIN applications a ON a.id=da.application_id")
        clauses, params = [], []
        if not include_inactive:
            clauses.append("da.is_active=1")
        if bu_id:
            clauses.append("da.business_unit_id=%s")
            params.append(bu_id)
        if classification:
            clauses.append("da.classification=%s")
            params.append(classification)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY da.name"
        return _dicts(db.execute(sql, tuple(params)).fetchall())
    finally:
        db.close()


def create_data_asset(data: dict) -> int:
    db = get_db()
    try:
        new_id = insert_returning_id(db,
            "INSERT INTO data_assets "
            "(name, description, category, classification, business_unit_id, "
            "application_id, owner_user_id, location, contains_pii, contains_phi, "
            "contains_financial, contains_ip, is_active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
            (data.get("name", "").strip(),
             data.get("description") or None,
             data.get("category") or None,
             data.get("classification", "internal"),
             data.get("business_unit_id"),
             data.get("application_id"),
             data.get("owner_user_id"),
             data.get("location") or None,
             1 if data.get("contains_pii") else 0,
             1 if data.get("contains_phi") else 0,
             1 if data.get("contains_financial") else 0,
             1 if data.get("contains_ip") else 0),
        )
        db.commit()
        return new_id
    finally:
        db.close()


def update_data_asset(asset_id: int, data: dict) -> bool:
    db = get_db()
    try:
        db.execute(
            "UPDATE data_assets SET name=%s, description=%s, category=%s, "
            "classification=%s, business_unit_id=%s, application_id=%s, "
            "owner_user_id=%s, location=%s, contains_pii=%s, contains_phi=%s, "
            "contains_financial=%s, contains_ip=%s, is_active=%s, updated_at=%s "
            "WHERE id=%s",
            (data.get("name", "").strip(),
             data.get("description") or None,
             data.get("category") or None,
             data.get("classification", "internal"),
             data.get("business_unit_id"),
             data.get("application_id"),
             data.get("owner_user_id"),
             data.get("location") or None,
             1 if data.get("contains_pii") else 0,
             1 if data.get("contains_phi") else 0,
             1 if data.get("contains_financial") else 0,
             1 if data.get("contains_ip") else 0,
             1 if data.get("is_active", 1) else 0,
             _now(), asset_id),
        )
        db.commit()
        return True
    finally:
        db.close()


def delete_data_asset(asset_id: int) -> bool:
    db = get_db()
    try:
        db.execute("DELETE FROM data_assets WHERE id=%s", (asset_id,))
        db.commit()
        return True
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# CANONICAL CONTROLS
# ═════════════════════════════════════════════════════════════════════════════

def list_canonical_controls(bu_id: int | None = None, include_inactive: bool = False) -> list[dict]:
    db = get_db()
    try:
        sql = ("SELECT cc.*, bu.name AS bu_name, "
               "(SELECT full_name FROM users WHERE id=cc.owner_user_id) AS owner_name "
               "FROM canonical_controls cc "
               "LEFT JOIN business_units bu ON bu.id=cc.business_unit_id")
        clauses, params = [], []
        if not include_inactive:
            clauses.append("cc.is_active=1")
        if bu_id:
            clauses.append("cc.business_unit_id=%s")
            params.append(bu_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY cc.title"
        return _dicts(db.execute(sql, tuple(params)).fetchall())
    finally:
        db.close()


def create_canonical_control(data: dict) -> int:
    db = get_db()
    try:
        new_id = insert_returning_id(db,
            "INSERT INTO canonical_controls "
            "(ref, title, description, owner_user_id, automation, "
            "test_frequency_days, last_tested_at, business_unit_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (data.get("ref", "").strip(),
             data.get("title", "").strip(),
             data.get("description") or None,
             data.get("owner_user_id"),
             data.get("automation") or None,
             data.get("test_frequency_days"),
             data.get("last_tested_at") or None,
             data.get("business_unit_id")),
        )
        db.commit()
        return new_id
    finally:
        db.close()


def update_canonical_control(cid: int, data: dict) -> bool:
    db = get_db()
    try:
        db.execute(
            "UPDATE canonical_controls SET ref=%s, title=%s, description=%s, "
            "owner_user_id=%s, automation=%s, test_frequency_days=%s, "
            "last_tested_at=%s, business_unit_id=%s, is_active=%s, updated_at=%s "
            "WHERE id=%s",
            (data.get("ref", "").strip(),
             data.get("title", "").strip(),
             data.get("description") or None,
             data.get("owner_user_id"),
             data.get("automation") or None,
             data.get("test_frequency_days"),
             data.get("last_tested_at") or None,
             data.get("business_unit_id"),
             1 if data.get("is_active", 1) else 0,
             _now(), cid),
        )
        db.commit()
        return True
    finally:
        db.close()


def delete_canonical_control(cid: int) -> bool:
    """Delete a canonical control only if no risk_controls reference it."""
    db = get_db()
    try:
        refs = db.execute(
            "SELECT COUNT(*) FROM risk_controls WHERE control_id=%s", (cid,)
        ).fetchone()[0]
        if refs:
            return False
        db.execute("DELETE FROM canonical_controls WHERE id=%s", (cid,))
        db.commit()
        return True
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# Governance summary — feeds the T3 heatmap and the Command Centre BU rollup
# ═════════════════════════════════════════════════════════════════════════════

def get_governance_summary() -> dict:
    """Return counts across all 5 node types plus totals per BU.

    Cheap: one query per table. Runs on the Command Centre; keeps fast even
    with thousands of nodes.
    """
    db = get_db()
    try:
        counts = {}
        for label, table in (("business_units", "business_units"),
                              ("departments", "departments"),
                              ("business_processes", "business_processes"),
                              ("applications", "applications"),
                              ("canonical_controls", "canonical_controls"),
                              ("data_assets", "data_assets")):
            try:
                counts[label] = db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE is_active=1"
                ).fetchone()[0]
            except Exception:
                counts[label] = 0
        return counts
    finally:
        db.close()
