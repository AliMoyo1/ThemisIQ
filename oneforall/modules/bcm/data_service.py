"""
BCM module — Data access layer.

All database operations for business continuity management: BIA records,
risks, continuity plans, incidents (with command console), exercises,
vendors, compliance controls, training, documents/RAG, dependency graph,
coverage mapping, plan reviews, chat messages, and reminders.
"""
import json
from datetime import datetime
from core.timeutils import utcnow

from database import get_db, insert_returning_id


# ── helpers ──────────────────────────────────────────────────────────────────

def _dict(row):
    return dict(row) if row else None


def _dicts(rows):
    return [dict(r) for r in rows]


def _now():
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ═════════════════════════════════════════════════════════════════════════════
# BIA RECORDS
# ═════════════════════════════════════════════════════════════════════════════

def list_bia(limit=200, bu_scope=None):
    db = get_db()
    try:
        if bu_scope is not None:
            ph = ",".join(["%s"] * len(bu_scope))
            return _dicts(db.execute(
                f"SELECT * FROM bcm_bia_records WHERE (business_unit_id IN ({ph}) OR business_unit_id IS NULL) "
                "ORDER BY criticality DESC, process_name LIMIT %s",
                list(bu_scope) + [limit]).fetchall())
        return _dicts(db.execute(
            "SELECT * FROM bcm_bia_records ORDER BY criticality DESC, process_name LIMIT %s",
            (limit,)).fetchall())
    finally:
        db.close()


def get_bia(bia_id):
    db = get_db()
    try:
        rec = _dict(db.execute(
            "SELECT b.*, bp.name AS business_process_name "
            "FROM bcm_bia_records b "
            "LEFT JOIN business_processes bp ON bp.id = b.business_process_id "
            "WHERE b.id=%s", (bia_id,)
        ).fetchone())
        if not rec:
            return None
        rec["impact_rows"] = _dicts(db.execute(
            "SELECT * FROM bcm_bia_impact_rows WHERE bia_id=%s ORDER BY order_idx, id", (bia_id,)
        ).fetchall())
        rec["resources"] = _dicts(db.execute(
            "SELECT * FROM bcm_bia_resources WHERE bia_id=%s ORDER BY order_idx, id", (bia_id,)
        ).fetchall())
        rec["bucket_labels"] = _get_bucket_labels(db)
        return rec
    finally:
        db.close()


def create_bia(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_bia_records
               (process_name, department, owner, description, rto_hours, rpo_hours,
                financial_impact_per_day, operational_impact, reputational_impact,
                regulatory_impact, criticality, dependencies, key_tasks, obligations,
                deadlines, peak_periods, peak_workload, min_acceptable_level,
                resume_period, business_process_id, business_unit_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("process_name"), data.get("department"), data.get("owner"),
             data.get("description"), data.get("rto_hours"), data.get("rpo_hours"),
             data.get("financial_impact_per_day"), data.get("operational_impact"),
             data.get("reputational_impact"), data.get("regulatory_impact"),
             data.get("criticality"), data.get("dependencies"), data.get("key_tasks"),
             data.get("obligations"), data.get("deadlines"), data.get("peak_periods"),
             data.get("peak_workload"), data.get("min_acceptable_level"),
             data.get("resume_period"), data.get("business_process_id"),
             data.get("business_unit_id")))
        _seed_default_impact_rows(db, cur)
        db.commit()
        return cur
    finally:
        db.close()


def update_bia(bia_id, data):
    db = get_db()
    try:
        fields = []
        vals = []
        for k in ("process_name", "department", "owner", "description", "rto_hours",
                  "rpo_hours", "financial_impact_per_day", "operational_impact",
                  "reputational_impact", "regulatory_impact", "criticality", "dependencies",
                  "key_tasks", "obligations", "deadlines", "peak_periods", "peak_workload",
                  "min_acceptable_level", "resume_period", "business_process_id",
                  "business_unit_id"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(bia_id)
            db.execute(f"UPDATE bcm_bia_records SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_bia(bia_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_bia_impact_rows WHERE bia_id=%s", (bia_id,))
        db.execute("DELETE FROM bcm_bia_resources WHERE bia_id=%s", (bia_id,))
        db.execute("DELETE FROM bcm_bia_records WHERE id=%s", (bia_id,))
        db.commit()
    finally:
        db.close()


# ── BIA Questionnaire: impact rows, recovery resources, RTO suggestion, bucket labels (PLAN-22) ──

_BIA_GENERAL_ROWS = [
    "Loss of reputation on the market", "Clients' reactions",
    "Impact on other activities", "Health, safety and environmental impacts",
    "Difficulty catching up on backlog",
]
_BIA_FINANCIAL_ROWS = [
    "Legal penalties", "Contractual penalties",
    "Loss of revenue from potential clients", "Loss of revenue from existing clients",
    "Additional expenses (repairs, maintenance, etc.)",
]
_BIA_RESOURCE_CATEGORIES = [
    "People", "Applications / databases", "Electronic data (outside applications)",
    "Paper data", "IT and communications equipment", "Communication channels",
    "Other equipment",
]
_BIA_NEEDED_AFTER = ("immediately", "1h", "4h", "24h", "2d", "1w", "other")
_BIA_BUCKET_HOURS = [2, 4, 24, 48, 168]
_BIA_BUCKET_LABELS_KEY = "bia.bucket_labels"
_BIA_DEFAULT_BUCKET_LABELS = ["2 hours", "4 hours", "24 hours", "48 hours", "1 week"]


def _seed_default_impact_rows(db, bia_id):
    order_idx = 0
    for label in _BIA_GENERAL_ROWS:
        db.execute(
            "INSERT INTO bcm_bia_impact_rows (bia_id, section, label, order_idx) "
            "VALUES (%s,'general',%s,%s)",
            (bia_id, label, order_idx),
        )
        order_idx += 1
    for label in _BIA_FINANCIAL_ROWS:
        db.execute(
            "INSERT INTO bcm_bia_impact_rows (bia_id, section, label, order_idx) "
            "VALUES (%s,'financial',%s,%s)",
            (bia_id, label, order_idx),
        )
        order_idx += 1


def seed_standard_rows_if_empty(bia_id):
    """Idempotent: legacy BIAs created before this plan have zero impact
    rows. Adds the 10 standard rows only if none exist yet."""
    db = get_db()
    try:
        count = db.execute(
            "SELECT COUNT(*) c FROM bcm_bia_impact_rows WHERE bia_id=%s", (bia_id,)
        ).fetchone()["c"]
        if count == 0:
            _seed_default_impact_rows(db, bia_id)
            db.commit()
        return count == 0
    finally:
        db.close()


def list_bia_impact_rows(bia_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_bia_impact_rows WHERE bia_id=%s ORDER BY order_idx, id", (bia_id,)
        ).fetchall())
    finally:
        db.close()


def save_bia_impact_rows(bia_id, rows):
    """Delete-and-reinsert -- these rows carry no history and no FKs point
    at them, unlike resources which are row-CRUD to preserve ids
    mid-edit. Clamps scores to 0-3 ONLY for section='general' rows;
    financial rows hold money amounts and must never be clamped."""
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_bia_impact_rows WHERE bia_id=%s", (bia_id,))
        for idx, row in enumerate(rows):
            section = row.get("section")
            if section not in ("general", "financial"):
                raise ValueError(f"section must be 'general' or 'financial', got {section!r}")
            vals = {}
            for col in ("b1", "b2", "b3", "b4", "b5"):
                v = row.get(col)
                if v in (None, ""):
                    vals[col] = None
                elif section == "general":
                    vals[col] = max(0, min(3, float(v)))
                else:
                    vals[col] = float(v)
            db.execute(
                "INSERT INTO bcm_bia_impact_rows "
                "(bia_id, section, label, description, b1, b2, b3, b4, b5, order_idx) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (bia_id, section, row.get("label") or "Untitled", row.get("description"),
                 vals["b1"], vals["b2"], vals["b3"], vals["b4"], vals["b5"], idx),
            )
        new_rows = _dicts(db.execute(
            "SELECT * FROM bcm_bia_impact_rows WHERE bia_id=%s ORDER BY order_idx, id", (bia_id,)
        ).fetchall())
        suggested = suggest_rto(new_rows)
        db.execute(
            "UPDATE bcm_bia_records SET suggested_rto_hours=%s, updated_at=%s WHERE id=%s",
            (suggested, _now(), bia_id),
        )
        db.commit()
        return {"rows": new_rows, "suggested_rto_hours": suggested}
    finally:
        db.close()


def suggest_rto(rows, bucket_hours=None):
    """First bucket (b1..b5, in order) where ANY general-section row's
    score reaches 3 (high) -> that bucket's hour value. None if no
    general row ever reaches 3. Financial rows are never consulted --
    they hold money amounts, not the 1-3 scale the threshold depends on.
    1 week = 168 hours (not 40, not 120)."""
    bucket_hours = bucket_hours or _BIA_BUCKET_HOURS
    general_rows = [r for r in rows if r.get("section") == "general"]
    for i, hours in enumerate(bucket_hours):
        col = f"b{i + 1}"
        for r in general_rows:
            val = r.get(col)
            if val is not None and float(val) >= 3:
                return hours
    return None


def create_bia_resource(bia_id, data):
    category = data.get("category") or "Other equipment"
    needed_after = data.get("needed_after") or "immediately"
    if needed_after not in _BIA_NEEDED_AFTER:
        raise ValueError(f"needed_after must be one of {_BIA_NEEDED_AFTER}")
    db = get_db()
    try:
        max_idx = db.execute(
            "SELECT COALESCE(MAX(order_idx),-1) m FROM bcm_bia_resources WHERE bia_id=%s", (bia_id,)
        ).fetchone()["m"]
        cur = insert_returning_id(db,
            "INSERT INTO bcm_bia_resources "
            "(bia_id, category, name, specifics, amount, single_point_of_failure, "
            "needed_after, notes, order_idx) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (bia_id, category, data.get("name") or "Untitled resource", data.get("specifics"),
             data.get("amount"), 1 if data.get("single_point_of_failure") else 0,
             needed_after, data.get("notes"), max_idx + 1),
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_bia_resource(resource_id, data):
    if "needed_after" in data and data["needed_after"] not in _BIA_NEEDED_AFTER:
        raise ValueError(f"needed_after must be one of {_BIA_NEEDED_AFTER}")
    if "single_point_of_failure" in data:
        data["single_point_of_failure"] = 1 if data["single_point_of_failure"] else 0
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("category", "name", "specifics", "amount", "single_point_of_failure",
                  "needed_after", "notes", "order_idx"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            vals.append(resource_id)
            db.execute(f"UPDATE bcm_bia_resources SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_bia_resource(resource_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_bia_resources WHERE id=%s", (resource_id,))
        db.commit()
    finally:
        db.close()


def _get_bucket_labels(db):
    row = db.execute("SELECT value FROM settings WHERE key=%s", (_BIA_BUCKET_LABELS_KEY,)).fetchone()
    if row and row["value"]:
        try:
            labels = json.loads(row["value"])
            if isinstance(labels, list) and len(labels) == 5:
                return labels
        except (ValueError, TypeError):
            pass
    return list(_BIA_DEFAULT_BUCKET_LABELS)


def get_bucket_labels():
    db = get_db()
    try:
        return _get_bucket_labels(db)
    finally:
        db.close()


def set_bucket_labels(labels):
    """Applies to every BIA -- this is a per-tenant setting, not per-BIA."""
    if not isinstance(labels, list) or len(labels) != 5 or any(not str(l).strip() for l in labels):
        raise ValueError("Exactly 5 non-empty bucket labels are required")
    db = get_db()
    try:
        db.execute(
            "INSERT INTO settings(key,value) VALUES(%s,%s) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_BIA_BUCKET_LABELS_KEY, json.dumps(labels)),
        )
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# RISKS
# ═════════════════════════════════════════════════════════════════════════════

def list_risks(limit=200):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_risks ORDER BY score DESC, created_at DESC LIMIT %s",
            (limit,)).fetchall())
    finally:
        db.close()


def get_risk(risk_id):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_risks WHERE id=%s", (risk_id,)).fetchone())
    finally:
        db.close()


def create_risk(data):
    db = get_db()
    try:
        likelihood = data.get("likelihood", 1)
        impact = data.get("impact", 1)
        score = data.get("score") or (int(likelihood) * int(impact))
        cur = insert_returning_id(db,
            """INSERT INTO bcm_risks
               (title, category, description, likelihood, impact, score,
                treatment, mitigation, owner, status, due_date)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("title"), data.get("category"), data.get("description"),
             likelihood, impact, score, data.get("treatment"), data.get("mitigation"),
             data.get("owner"), data.get("status", "open"), data.get("due_date")))
        db.commit()
        return cur
    finally:
        db.close()


def update_risk(risk_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "category", "description", "likelihood", "impact",
                  "score", "treatment", "mitigation", "owner", "status", "due_date"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if "likelihood" in data and "impact" in data and "score" not in data:
            fields.append("score=%s")
            vals.append(int(data["likelihood"]) * int(data["impact"]))
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(risk_id)
            db.execute(f"UPDATE bcm_risks SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_risk(risk_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_risks WHERE id=%s", (risk_id,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# BCP PLANS
# ═════════════════════════════════════════════════════════════════════════════

def list_plans(limit=200, bu_scope=None):
    db = get_db()
    try:
        if bu_scope is not None:
            ph = ",".join(["%s"] * len(bu_scope))
            return _dicts(db.execute(
                f"SELECT * FROM bcm_plans WHERE (business_unit_id IN ({ph}) OR business_unit_id IS NULL) "
                "ORDER BY updated_at DESC LIMIT %s",
                list(bu_scope) + [limit]).fetchall())
        return _dicts(db.execute(
            "SELECT * FROM bcm_plans ORDER BY updated_at DESC LIMIT %s", (limit,)).fetchall())
    finally:
        db.close()


def get_plan(plan_id):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_plans WHERE id=%s", (plan_id,)).fetchone())
    finally:
        db.close()


def create_plan(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_plans
               (title, plan_type, department, scope, owner, version, status,
                content, description, review_frequency, last_reviewed, next_review)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("title"), data.get("plan_type"), data.get("department"),
             data.get("scope"), data.get("owner"),
             data.get("version", "1.0"), data.get("status", "draft"),
             data.get("content") or data.get("description"),
             data.get("description"), data.get("review_frequency"),
             data.get("last_reviewed"), data.get("next_review")))
        db.commit()
        return cur
    finally:
        db.close()


def update_plan(plan_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "plan_type", "department", "scope", "owner", "version",
                  "status", "content", "description", "review_frequency",
                  "last_reviewed", "next_review"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(plan_id)
            db.execute(f"UPDATE bcm_plans SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_plan(plan_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_plans WHERE id=%s", (plan_id,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# INCIDENTS + COMMAND CONSOLE
# ═════════════════════════════════════════════════════════════════════════════

def list_incidents(status=None, limit=200):
    db = get_db()
    try:
        if status:
            return _dicts(db.execute(
                "SELECT * FROM bcm_incidents WHERE status=%s ORDER BY created_at DESC LIMIT %s",
                (status, limit)).fetchall())
        return _dicts(db.execute(
            "SELECT * FROM bcm_incidents ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall())
    finally:
        db.close()


def get_incident(inc_id):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_incidents WHERE id=%s", (inc_id,)).fetchone())
    finally:
        db.close()


def create_incident(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_incidents
               (title, description, severity, status, commander, affected_systems,
                impact, assigned_to, declared_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("title"), data.get("description"), data.get("severity", "medium"),
             data.get("status", "open"), data.get("commander"), data.get("affected_systems"),
             data.get("impact"), data.get("assigned_to"), data.get("declared_at")))
        db.commit()
        return cur
    finally:
        db.close()


def update_incident(inc_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "description", "severity", "status", "commander",
                  "affected_systems", "impact", "assigned_to", "declared_at",
                  "resolved_at"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if data.get("status") == "resolved" and "resolved_at" not in data:
            fields.append("resolved_at=%s")
            vals.append(_now())
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(inc_id)
            db.execute(f"UPDATE bcm_incidents SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_incident(inc_id):
    db = get_db()
    try:
        db.execute("DELETE FROM cross_module_links WHERE source_module='bcm' AND source_type='incident' AND source_id=%s", (inc_id,))
        db.execute("DELETE FROM cross_module_links WHERE target_module='bcm' AND target_type='incident' AND target_id=%s", (inc_id,))
        db.execute("DELETE FROM bcm_incidents WHERE id=%s", (inc_id,))
        db.commit()
    finally:
        db.close()


# Incident updates (timeline)
def list_incident_updates(inc_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_incident_updates WHERE incident_id=%s ORDER BY created_at",
            (inc_id,)).fetchall())
    finally:
        db.close()


def create_incident_update(inc_id, author, note):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO bcm_incident_updates (incident_id, author, note) VALUES (%s,%s,%s)",
            (inc_id, author, note))
        db.commit()
        return cur
    finally:
        db.close()


# Incident actions
def list_incident_actions(inc_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_incident_actions WHERE incident_id=%s ORDER BY priority DESC, created_at",
            (inc_id,)).fetchall())
    finally:
        db.close()


def create_incident_action(inc_id, data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_incident_actions
               (incident_id, title, owner, status, priority, due_at, notes, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (inc_id, data.get("title"), data.get("owner"), data.get("status", "open"),
             data.get("priority", "normal"), data.get("due_at"), data.get("notes"),
             data.get("created_by")))
        db.commit()
        return cur
    finally:
        db.close()


def update_incident_action(action_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "owner", "status", "priority", "due_at", "notes", "completed_at"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if data.get("status") == "done" and "completed_at" not in data:
            fields.append("completed_at=%s")
            vals.append(_now())
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(action_id)
            db.execute(f"UPDATE bcm_incident_actions SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_incident_action(action_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_incident_actions WHERE id=%s", (action_id,))
        db.commit()
    finally:
        db.close()


# Incident decisions
def list_incident_decisions(inc_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_incident_decisions WHERE incident_id=%s ORDER BY decided_at",
            (inc_id,)).fetchall())
    finally:
        db.close()


def create_incident_decision(inc_id, data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO bcm_incident_decisions (incident_id, decision, rationale, decided_by) VALUES (%s,%s,%s,%s)",
            (inc_id, data.get("decision"), data.get("rationale"), data.get("decided_by")))
        db.commit()
        return cur
    finally:
        db.close()


# Incident stakeholders
def list_incident_stakeholders(inc_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_incident_stakeholders WHERE incident_id=%s ORDER BY created_at",
            (inc_id,)).fetchall())
    finally:
        db.close()


def create_incident_stakeholder(inc_id, data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_incident_stakeholders
               (incident_id, role, person, channel, notes)
               VALUES (%s,%s,%s,%s,%s)""",
            (inc_id, data.get("role"), data.get("person"), data.get("channel"), data.get("notes")))
        db.commit()
        return cur
    finally:
        db.close()


def update_incident_stakeholder(sh_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("role", "person", "channel", "notified_at", "ack_at", "notes"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            vals.append(sh_id)
            db.execute(f"UPDATE bcm_incident_stakeholders SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_incident_stakeholder(sh_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_incident_stakeholders WHERE id=%s", (sh_id,))
        db.commit()
    finally:
        db.close()


# Incident ↔ Plan links
def list_incident_plan_links(inc_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            """SELECT l.*, p.title AS plan_title FROM bcm_incident_plan_links l
               JOIN bcm_plans p ON p.id = l.plan_id
               WHERE l.incident_id=%s ORDER BY l.created_at""",
            (inc_id,)).fetchall())
    finally:
        db.close()


def link_incident_plan(inc_id, plan_id, linked_by=None):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO bcm_incident_plan_links (incident_id, plan_id, linked_by) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            (inc_id, plan_id, linked_by))
        db.commit()
        return cur
    finally:
        db.close()


def unlink_incident_plan(link_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_incident_plan_links WHERE id=%s", (link_id,))
        db.commit()
    finally:
        db.close()


def search_vault_items(query, limit=20):
    db = get_db()
    try:
        q = '%' + (query or '').strip() + '%'
        return _dicts(db.execute(
            "SELECT id, title, category, tags, status, updated_at "
            "FROM evidence_items WHERE status != 'archived' "
            "AND (title LIKE %s OR tags LIKE %s OR category LIKE %s) "
            "ORDER BY updated_at DESC LIMIT %s",
            (q, q, q, limit)).fetchall())
    finally:
        db.close()


def list_incident_vault_links(inc_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT e.id, e.title, e.category, e.status, e.updated_at, el.id as link_id "
            "FROM evidence_items e JOIN evidence_links el ON e.id = el.evidence_id "
            "WHERE el.module='bcm' AND el.entity_type='incident' AND el.entity_id=%s "
            "AND el.deleted_at IS NULL AND e.status != 'archived' "
            "ORDER BY el.created_at DESC",
            (inc_id,)).fetchall())
    finally:
        db.close()


def link_incident_vault_item(inc_id, evidence_id, linked_by=None):
    db = get_db()
    try:
        existing = db.execute(
            "SELECT id FROM evidence_links WHERE module='bcm' AND entity_type='incident' "
            "AND entity_id=%s AND evidence_id=%s AND deleted_at IS NULL",
            (inc_id, evidence_id)).fetchone()
        if existing:
            return existing['id']
        lid = insert_returning_id(db,
            "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) "
            "VALUES (%s,'bcm','incident',%s,%s)",
            (evidence_id, inc_id, linked_by))
        db.commit()
        return lid
    finally:
        db.close()


def unlink_incident_vault_item(link_id):
    db = get_db()
    try:
        db.execute(
            "UPDATE evidence_links SET deleted_at=CURRENT_TIMESTAMP WHERE id=%s",
            (link_id,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# EXERCISES
# ═════════════════════════════════════════════════════════════════════════════

def list_exercises(limit=200):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_exercises ORDER BY scheduled_date DESC LIMIT %s", (limit,)).fetchall())
    finally:
        db.close()


def get_exercise(ex_id):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_exercises WHERE id=%s", (ex_id,)).fetchone())
    finally:
        db.close()


def create_exercise(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_exercises
               (title, type, scenario, plan_id, scheduled_date, duration_minutes,
                facilitator, participants, objectives, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("title"), data.get("type"), data.get("scenario"),
             data.get("plan_id"), data.get("scheduled_date"), data.get("duration_minutes"),
             data.get("facilitator"), data.get("participants"), data.get("objectives"),
             data.get("status", "planned")))
        db.commit()
        return cur
    finally:
        db.close()


def update_exercise(ex_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "type", "scenario", "plan_id", "scheduled_date", "duration_minutes",
                  "facilitator", "participants", "objectives", "status", "outcome",
                  "aar_summary", "aar_strengths", "aar_improvements", "aar_actions"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(ex_id)
            db.execute(f"UPDATE bcm_exercises SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_exercise(ex_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_exercises WHERE id=%s", (ex_id,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# VENDORS + ASSESSMENTS
# ═════════════════════════════════════════════════════════════════════════════

def list_vendors(limit=200):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_vendors ORDER BY name LIMIT %s", (limit,)).fetchall())
    finally:
        db.close()


def get_vendor(vid):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_vendors WHERE id=%s", (vid,)).fetchone())
    finally:
        db.close()


def create_vendor(data):
    db = get_db()
    try:
        # Ensure canonical vendor identity
        canonical_id = data.get("canonical_id")
        if not canonical_id:
            try:
                from core.vendor_link import ensure_canonical
                canonical_id = ensure_canonical(db, data.get("name", ""), data.get("contact_email"))
            except Exception:
                pass
        cur = insert_returning_id(db,
            """INSERT INTO bcm_vendors
               (name, category, service_provided, owner, contact_name, contact_email,
                contact_phone, criticality, tier, data_sensitivity, sla,
                contract_renewal, risk_score, status, notes, canonical_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("name"), data.get("category"), data.get("service_provided"),
             data.get("owner"), data.get("contact_name"), data.get("contact_email"),
             data.get("contact_phone"), data.get("criticality"), data.get("tier", 3),
             data.get("data_sensitivity"), data.get("sla"), data.get("contract_renewal"),
             data.get("risk_score"), data.get("status", "active"), data.get("notes"), canonical_id))
        db.commit()
        return cur
    finally:
        db.close()


def update_vendor(vid, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("name", "category", "service_provided", "owner", "contact_name",
                  "contact_email", "contact_phone", "criticality", "tier",
                  "data_sensitivity", "sla", "contract_renewal", "risk_score",
                  "status", "notes"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(vid)
            db.execute(f"UPDATE bcm_vendors SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_vendor(vid):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_vendors WHERE id=%s", (vid,))
        db.commit()
    finally:
        db.close()


def list_vendor_assessments(vid):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_vendor_assessments WHERE vendor_id=%s ORDER BY assessed_on DESC",
            (vid,)).fetchall())
    finally:
        db.close()


def create_vendor_assessment(vid, data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_vendor_assessments
               (vendor_id, assessor, score, summary, findings)
               VALUES (%s,%s,%s,%s,%s)""",
            (vid, data.get("assessor"), data.get("score"),
             data.get("summary"), data.get("findings")))
        db.commit()
        return cur
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# COMPLIANCE CONTROLS + EVIDENCE
# ═════════════════════════════════════════════════════════════════════════════

def list_compliance_controls(framework=None, limit=500):
    db = get_db()
    try:
        if framework:
            return _dicts(db.execute(
                "SELECT * FROM bcm_compliance_controls WHERE framework=%s ORDER BY clause LIMIT %s",
                (framework, limit)).fetchall())
        return _dicts(db.execute(
            "SELECT * FROM bcm_compliance_controls ORDER BY framework, clause LIMIT %s",
            (limit,)).fetchall())
    finally:
        db.close()


def get_compliance_control(cid):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_compliance_controls WHERE id=%s", (cid,)).fetchone())
    finally:
        db.close()


def create_compliance_control(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_compliance_controls
               (framework, clause, title, description, status, owner, evidence_notes)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("framework"), data.get("clause"), data.get("title"),
             data.get("description"), data.get("status", "not_started"),
             data.get("owner"), data.get("evidence_notes")))
        db.commit()
        return cur
    finally:
        db.close()


def update_compliance_control(cid, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("framework", "clause", "title", "description", "status",
                  "owner", "evidence_notes", "last_reviewed", "next_review"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(cid)
            db.execute(f"UPDATE bcm_compliance_controls SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_compliance_control(cid):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_compliance_controls WHERE id=%s", (cid,))
        db.commit()
    finally:
        db.close()


def list_compliance_evidence(control_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_compliance_evidence WHERE control_id=%s ORDER BY created_at DESC",
            (control_id,)).fetchall())
    finally:
        db.close()


def create_compliance_evidence(control_id, data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_compliance_evidence
               (control_id, title, file_path, file_type, uploaded_by, notes)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (control_id, data.get("title"), data.get("file_path"),
             data.get("file_type"), data.get("uploaded_by"), data.get("notes")))
        db.commit()
        return cur
    finally:
        db.close()


def delete_compliance_evidence(eid):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_compliance_evidence WHERE id=%s", (eid,))
        db.commit()
    finally:
        db.close()


def sync_bcm_compliance_evidence_to_vault(evidence_id: int, control_id: int, user_id: int):
    """
    Mirror a bcm_compliance_evidence entry into the central evidence_items vault
    and create an evidence_link to the BCM compliance control.
    Follows the pattern of GRID's sync_grid_evidence_to_vault().
    Returns the new evidence_items.id, or None on failure.
    """
    import logging
    log = logging.getLogger("bcm.evidence_sync")
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM bcm_compliance_evidence WHERE id=%s", (evidence_id,)
        ).fetchone()
        if not row:
            return None

        ctrl = db.execute(
            "SELECT framework, clause, title FROM bcm_compliance_controls WHERE id=%s",
            (control_id,)
        ).fetchone()

        framework = ctrl["framework"] if ctrl else "BCM"
        clause    = ctrl["clause"]    if ctrl else ""
        ctrl_title = ctrl["title"]   if ctrl else ""

        vault_id = insert_returning_id(db,
            "INSERT INTO evidence_items "
            "(title, description, file_path, category, tags, status, uploaded_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                row["title"] or f"BCM Evidence #{evidence_id}",
                f"BCM compliance evidence for {framework} clause {clause}: {ctrl_title}",
                row["file_path"] or "",
                row["file_type"] or "general",
                f"bcm,compliance,{framework.lower().replace(' ','-')},bcm_evidence_id={evidence_id}",
                "current",
                user_id,
            )
        )

        db.execute(
            "INSERT INTO evidence_links "
            "(evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s,%s,%s,%s,%s)",
            (vault_id, "bcm", "compliance_control", control_id, user_id)
        )
        db.commit()
        log.info("BCM evidence #%d synced to vault as #%d", evidence_id, vault_id)
        return vault_id
    except Exception as e:
        log.warning("BCM evidence sync failed: %s", e)
        return None
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# TRAINING MODULES + ATTESTATIONS
# ═════════════════════════════════════════════════════════════════════════════

def list_training_modules(limit=200):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_training_modules ORDER BY title LIMIT %s", (limit,)).fetchall())
    finally:
        db.close()


def get_training_module(mid):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_training_modules WHERE id=%s", (mid,)).fetchone())
    finally:
        db.close()


def create_training_module(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_training_modules
               (title, description, category, required_roles, duration_minutes,
                owner, content, passing_score, renewal_months, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("title"), data.get("description"), data.get("category"),
             data.get("required_roles"), data.get("duration_minutes"),
             data.get("owner"), data.get("content"), data.get("passing_score", 80),
             data.get("renewal_months", 12), data.get("status", "active")))
        db.commit()
        return cur
    finally:
        db.close()


def update_training_module(mid, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "description", "category", "required_roles", "duration_minutes",
                  "owner", "content", "passing_score", "renewal_months", "status"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(mid)
            db.execute(f"UPDATE bcm_training_modules SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_training_module(mid):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_training_modules WHERE id=%s", (mid,))
        db.commit()
    finally:
        db.close()


def list_attestations(module_id=None, user_id=None):
    db = get_db()
    try:
        if module_id:
            return _dicts(db.execute(
                "SELECT * FROM bcm_training_attestations WHERE module_id=%s ORDER BY attested_at DESC",
                (module_id,)).fetchall())
        if user_id:
            return _dicts(db.execute(
                "SELECT * FROM bcm_training_attestations WHERE user_id=%s ORDER BY attested_at DESC",
                (user_id,)).fetchall())
        return _dicts(db.execute(
            "SELECT * FROM bcm_training_attestations ORDER BY attested_at DESC LIMIT 500").fetchall())
    finally:
        db.close()


def create_attestation(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_training_attestations
               (module_id, user_id, user_name, user_email, signature, score, ip, user_agent, expires_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("module_id"), data.get("user_id"), data.get("user_name"),
             data.get("user_email"), data.get("signature"), data.get("score"),
             data.get("ip"), data.get("user_agent"), data.get("expires_at")))
        db.commit()
        return cur
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# DOCUMENTS + RAG
# ═════════════════════════════════════════════════════════════════════════════

def list_documents(limit=200):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_documents ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall())
    finally:
        db.close()


def get_document(doc_id):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_documents WHERE id=%s", (doc_id,)).fetchone())
    finally:
        db.close()


def create_document(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_documents
               (title, source_kind, filename, mime, bytes, uploaded_by, tags,
                content, chunk_count, linked_plan_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("title"), data.get("source_kind"), data.get("filename"),
             data.get("mime"), data.get("bytes"), data.get("uploaded_by"),
             data.get("tags"), data.get("content"), data.get("chunk_count", 0),
             data.get("linked_plan_id")))
        db.commit()
        return cur
    finally:
        db.close()


def update_document(doc_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "source_kind", "tags", "content", "chunk_count", "linked_plan_id"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            vals.append(doc_id)
            db.execute(f"UPDATE bcm_documents SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_document(doc_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_document_chunks WHERE document_id=%s", (doc_id,))
        db.execute("DELETE FROM bcm_documents WHERE id=%s", (doc_id,))
        db.commit()
    finally:
        db.close()


def save_chunks(doc_id, chunks):
    """Save document chunks for RAG.

    Accepts either:
      - list of dicts: [{"text": str, "chunk_index": int, ...}, ...]  (from ai_service.chunk_text)
      - list of tuples: [(content_str, token_count), ...]  (legacy format)
    """
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_document_chunks WHERE document_id=%s", (doc_id,))
        for i, c in enumerate(chunks):
            if isinstance(c, dict):
                text = c.get("text", "")
                tokens = c.get("token_count")
            else:
                text, tokens = c
            db.execute(
                "INSERT INTO bcm_document_chunks (document_id, chunk_index, content, token_count) VALUES (%s,%s,%s,%s)",
                (doc_id, i, text, tokens))
        db.execute("UPDATE bcm_documents SET chunk_count=%s WHERE id=%s", (len(chunks), doc_id))
        db.commit()
    finally:
        db.close()


def get_chunks(doc_id=None, chunk_ids=None):
    db = get_db()
    try:
        if chunk_ids:
            placeholders = ",".join("%s" for _ in chunk_ids)
            return _dicts(db.execute(
                f"SELECT * FROM bcm_document_chunks WHERE id IN ({placeholders}) ORDER BY chunk_index",
                chunk_ids).fetchall())
        if doc_id:
            return _dicts(db.execute(
                "SELECT * FROM bcm_document_chunks WHERE document_id=%s ORDER BY chunk_index",
                (doc_id,)).fetchall())
        return []
    finally:
        db.close()


def search_chunks(query_terms, limit=10):
    """Simple keyword search across chunks."""
    db = get_db()
    try:
        like_clauses = " AND ".join("content LIKE %s" for _ in query_terms)
        params = [f"%{t}%" for t in query_terms]
        params.append(limit)
        return _dicts(db.execute(
            f"SELECT * FROM bcm_document_chunks WHERE {like_clauses} LIMIT %s",
            params).fetchall())
    finally:
        db.close()


def save_document_query(user_id, question, answer, cited_ids, provider):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO bcm_document_queries (user_id, question, answer, cited_chunk_ids, provider) VALUES (%s,%s,%s,%s,%s)",
            (user_id, question, answer, cited_ids, provider))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# DEPENDENCY GRAPH
# ═════════════════════════════════════════════════════════════════════════════

def list_dependency_nodes(limit=500):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_dependency_nodes ORDER BY node_type, name LIMIT %s", (limit,)).fetchall())
    finally:
        db.close()


def get_dependency_node(nid):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_dependency_nodes WHERE id=%s", (nid,)).fetchone())
    finally:
        db.close()


def create_dependency_node(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_dependency_nodes
               (node_type, name, description, criticality, ref_table, ref_id)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (data.get("node_type"), data.get("name"), data.get("description"),
             data.get("criticality"), data.get("ref_table"), data.get("ref_id")))
        db.commit()
        return cur
    finally:
        db.close()


def update_dependency_node(nid, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("node_type", "name", "description", "criticality", "ref_table", "ref_id"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(nid)
            db.execute(f"UPDATE bcm_dependency_nodes SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_dependency_node(nid):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_dependency_nodes WHERE id=%s", (nid,))
        db.commit()
    finally:
        db.close()


def list_dependency_edges(source_id=None):
    db = get_db()
    try:
        if source_id:
            return _dicts(db.execute(
                "SELECT * FROM bcm_dependency_edges WHERE source_id=%s", (source_id,)).fetchall())
        return _dicts(db.execute("SELECT * FROM bcm_dependency_edges").fetchall())
    finally:
        db.close()


def create_dependency_edge(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO bcm_dependency_edges (source_id, target_id, label, strength, notes) VALUES (%s,%s,%s,%s,%s)",
            (data.get("source_id"), data.get("target_id"), data.get("label"),
             data.get("strength", 3), data.get("notes")))
        db.commit()
        return cur
    finally:
        db.close()


def delete_dependency_edge(eid):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_dependency_edges WHERE id=%s", (eid,))
        db.commit()
    finally:
        db.close()


def get_dependency_graph():
    """Return full graph as {nodes: [...], edges: [...]}."""
    db = get_db()
    try:
        nodes = _dicts(db.execute("SELECT * FROM bcm_dependency_nodes").fetchall())
        edges = _dicts(db.execute("SELECT * FROM bcm_dependency_edges").fetchall())
        return {"nodes": nodes, "edges": edges}
    finally:
        db.close()


def get_impact_chain(node_id, depth=5):
    """BFS to find all downstream dependents of a node."""
    db = get_db()
    try:
        visited = set()
        queue = [node_id]
        chain = []
        for _ in range(depth):
            if not queue:
                break
            next_queue = []
            for nid in queue:
                if nid in visited:
                    continue
                visited.add(nid)
                rows = db.execute(
                    "SELECT target_id FROM bcm_dependency_edges WHERE source_id=%s", (nid,)).fetchall()
                for r in rows:
                    tid = r[0]
                    if tid not in visited:
                        node = _dict(db.execute(
                            "SELECT * FROM bcm_dependency_nodes WHERE id=%s", (tid,)).fetchone())
                        if node:
                            chain.append(node)
                            next_queue.append(tid)
            queue = next_queue
        return chain
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# BIA ↔ PLAN COVERAGE
# ═════════════════════════════════════════════════════════════════════════════

def list_bia_plan_links(bia_id=None, plan_id=None):
    db = get_db()
    try:
        if bia_id:
            return _dicts(db.execute(
                """SELECT l.*, p.title AS plan_title FROM bcm_bia_plan_links l
                   JOIN bcm_plans p ON p.id=l.plan_id WHERE l.bia_id=%s""",
                (bia_id,)).fetchall())
        if plan_id:
            return _dicts(db.execute(
                """SELECT l.*, b.process_name FROM bcm_bia_plan_links l
                   JOIN bcm_bia_records b ON b.id=l.bia_id WHERE l.plan_id=%s""",
                (plan_id,)).fetchall())
        return _dicts(db.execute("SELECT * FROM bcm_bia_plan_links").fetchall())
    finally:
        db.close()


def create_bia_plan_link(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO bcm_bia_plan_links (bia_id, plan_id, coverage_type, notes, created_by) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (data.get("bia_id"), data.get("plan_id"), data.get("coverage_type", "primary"),
             data.get("notes"), data.get("created_by")))
        db.commit()
        return cur
    finally:
        db.close()


def delete_bia_plan_link(link_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_bia_plan_links WHERE id=%s", (link_id,))
        db.commit()
    finally:
        db.close()


def get_coverage_summary():
    """Return BIA coverage stats: how many BIA records have at least one plan linked."""
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM bcm_bia_records").fetchone()[0]
        covered = db.execute(
            "SELECT COUNT(DISTINCT bia_id) FROM bcm_bia_plan_links").fetchone()[0]
        return {"total_bia": total, "covered": covered, "uncovered": total - covered,
                "pct": round(covered / total * 100) if total else 0}
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# PLAN REVIEWS
# ═════════════════════════════════════════════════════════════════════════════

def list_plan_reviews(plan_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_plan_reviews WHERE plan_id=%s ORDER BY created_at DESC",
            (plan_id,)).fetchall())
    finally:
        db.close()


def create_plan_review(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            """INSERT INTO bcm_plan_reviews
               (plan_id, reviewer_id, reviewer_name, provider, overall_score,
                standards, summary, strengths, gaps, recommendations,
                section_coverage, raw_response)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("plan_id"), data.get("reviewer_id"), data.get("reviewer_name"),
             data.get("provider"), data.get("overall_score"), data.get("standards"),
             data.get("summary"), data.get("strengths"), data.get("gaps"),
             data.get("recommendations"), data.get("section_coverage"),
             data.get("raw_response")))
        db.commit()
        return cur
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# CHAT MESSAGES
# ═════════════════════════════════════════════════════════════════════════════

def list_chat_messages(user_id, limit=50):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_chat_messages WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit)).fetchall())
    finally:
        db.close()


def save_chat_message(user_id, role, content, provider=None):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO bcm_chat_messages (user_id, role, content, provider) VALUES (%s,%s,%s,%s)",
            (user_id, role, content, provider))
        db.commit()
    finally:
        db.close()


def clear_chat_history(user_id):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_chat_messages WHERE user_id=%s", (user_id,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# CRISIS COMMUNICATION TEMPLATES (BCM-14)
# ═════════════════════════════════════════════════════════════════════════════

def list_comm_templates(category=None):
    db = get_db()
    try:
        if category and category != "all":
            return _dicts(db.execute(
                "SELECT * FROM bcm_comm_templates WHERE category=%s AND is_active=1 ORDER BY category, title",
                (category,)).fetchall())
        return _dicts(db.execute(
            "SELECT * FROM bcm_comm_templates WHERE is_active=1 ORDER BY category, title").fetchall())
    finally:
        db.close()


def get_comm_template(tid):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_comm_templates WHERE id=%s", (tid,)).fetchone())
    finally:
        db.close()


def create_comm_template(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO bcm_comm_templates (title, category, incident_types, subject, body, variables, is_active, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("title"), data.get("category", "general"), data.get("incident_types", ""),
             data.get("subject"), data.get("body", ""), data.get("variables", ""),
             data.get("is_active", 1), data.get("created_by")))
        db.commit()
        return cur
    finally:
        db.close()


def update_comm_template(tid, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "category", "incident_types", "subject", "body", "variables", "is_active", "version"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(tid)
            db.execute(f"UPDATE bcm_comm_templates SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_comm_template(tid):
    db = get_db()
    try:
        db.execute("DELETE FROM bcm_comm_templates WHERE id=%s", (tid,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# EMERGENCY CONTACT TREE (BCM-15)
# ═════════════════════════════════════════════════════════════════════════════

def list_contact_nodes():
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_contact_nodes ORDER BY escalation_level, name").fetchall())
    finally:
        db.close()


def get_contact_node(nid):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_contact_nodes WHERE id=%s", (nid,)).fetchone())
    finally:
        db.close()


def get_contact_tree():
    """Return contacts as a hierarchical tree {roots: [...], all: [...]}."""
    db = get_db()
    try:
        all_nodes = _dicts(db.execute(
            "SELECT * FROM bcm_contact_nodes ORDER BY escalation_level, name").fetchall())
        # Build tree: roots are nodes with no parent
        node_map = {n["id"]: dict(n, children=[]) for n in all_nodes}
        roots = []
        for n in node_map.values():
            pid = n.get("parent_id")
            if pid and pid in node_map:
                node_map[pid]["children"].append(n)
            else:
                roots.append(n)
        return {"roots": roots, "all": all_nodes}
    finally:
        db.close()


def create_contact_node(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO bcm_contact_nodes (name, role, team, email, phone, mobile, escalation_level, parent_id, notes) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("name"), data.get("role"), data.get("team"), data.get("email"),
             data.get("phone"), data.get("mobile"), data.get("escalation_level", 1),
             data.get("parent_id"), data.get("notes")))
        db.commit()
        return cur
    finally:
        db.close()


def update_contact_node(nid, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("name", "role", "team", "email", "phone", "mobile", "escalation_level", "parent_id", "notes"):
            if k in data:
                fields.append(f"{k}=%s")
                vals.append(data[k])
        if fields:
            fields.append("updated_at=%s")
            vals.append(_now())
            vals.append(nid)
            db.execute(f"UPDATE bcm_contact_nodes SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_contact_node(nid):
    db = get_db()
    try:
        # Orphan children rather than cascade-delete the whole branch
        db.execute("UPDATE bcm_contact_nodes SET parent_id=NULL WHERE parent_id=%s", (nid,))
        db.execute("DELETE FROM bcm_contact_nodes WHERE id=%s", (nid,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# EXERCISE SCENARIO LIBRARY (BCM-16)
# ═════════════════════════════════════════════════════════════════════════════

def list_scenarios(category=None):
    db = get_db()
    try:
        if category and category != "all":
            return _dicts(db.execute(
                "SELECT * FROM bcm_scenario_library WHERE category=%s ORDER BY title",
                (category,)).fetchall())
        return _dicts(db.execute(
            "SELECT * FROM bcm_scenario_library ORDER BY category, title").fetchall())
    finally:
        db.close()


def get_scenario(sid):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM bcm_scenario_library WHERE id=%s", (sid,)).fetchone())
    finally:
        db.close()


def create_scenario(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO bcm_scenario_library (title, category, description, objectives, injects, "
            "estimated_duration_minutes, difficulty, is_builtin) VALUES (%s,%s,%s,%s,%s,%s,%s,0)",
            (data.get("title"), data.get("category", "general"), data.get("description"),
             data.get("objectives"), data.get("injects"),
             data.get("estimated_duration_minutes", 120), data.get("difficulty", "medium")))
        db.commit()
        return cur
    finally:
        db.close()


def delete_scenario(sid):
    db = get_db()
    try:
        # Only allow deleting custom scenarios (is_builtin=0)
        db.execute("DELETE FROM bcm_scenario_library WHERE id=%s AND is_builtin=0", (sid,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# BIA CALCULATION ENGINE (BCM-12/13)
# ═════════════════════════════════════════════════════════════════════════════

def calculate_bia_metrics(bia_id):
    """
    Calculate recommended criticality, MTPD guidance, and validation notes
    from BIA record data (RTO, RPO, MTPD, financial impact).

    Returns dict: {criticality, mtpd_guidance, validation, notes, score}
    Also persists calc_criticality and calc_notes back to the record.
    """
    db = get_db()
    try:
        bia = _dict(db.execute("SELECT * FROM bcm_bia_records WHERE id=%s", (bia_id,)).fetchone())
        if not bia:
            return None

        rto = bia.get("rto_hours") or 0
        rpo = bia.get("rpo_hours") or 0
        mtpd = bia.get("mtpd_hours") or 0
        fin_impact = bia.get("financial_impact_per_day") or 0
        op_impact = int(bia.get("operational_impact") or 0)
        rep_impact = int(bia.get("reputational_impact") or 0)
        reg_impact = int(bia.get("regulatory_impact") or 0)

        validation = []
        notes = []

        # RTO/RPO validation
        if rto and rpo and rpo > rto:
            validation.append("RPO cannot exceed RTO: data recovery point must be within the recovery time window.")
        if mtpd and rto and mtpd < rto:
            validation.append("MTPD must be greater than or equal to RTO: the maximum tolerable outage must accommodate the recovery time.")

        # Criticality scoring
        # Weight: RTO (40%), financial impact (30%), max impact score (30%)
        rto_score = 5 if rto <= 2 else 4 if rto <= 8 else 3 if rto <= 24 else 2 if rto <= 72 else 1
        impact_scores = [s for s in [op_impact, rep_impact, reg_impact] if s > 0]
        max_impact = max(impact_scores) if impact_scores else 0
        fin_score = 5 if fin_impact >= 100000 else 4 if fin_impact >= 50000 else 3 if fin_impact >= 10000 else 2 if fin_impact >= 1000 else 1

        composite = round((rto_score * 0.4) + (fin_score * 0.3) + (max_impact * 0.3), 1)

        if composite >= 4.0:
            criticality = "critical"
        elif composite >= 3.0:
            criticality = "high"
        elif composite >= 2.0:
            criticality = "medium"
        else:
            criticality = "low"

        # MTPD guidance
        if rto:
            suggested_mtpd = rto * 3
            notes.append(f"Suggested MTPD: {suggested_mtpd}h (3x RTO). Adjust based on contractual and regulatory obligations.")
        if rto <= 4:
            notes.append("Short RTO (<= 4h) indicates mission-critical dependency: ensure hot standby or active-active architecture.")
        if fin_impact > 50000:
            notes.append(f"High financial impact (${fin_impact:,.0f}/day): prioritise investment in automated failover and tested backups.")

        # Persist calculated values
        calc_notes_str = " | ".join(validation + notes)
        db.execute(
            "UPDATE bcm_bia_records SET calc_criticality=%s, calc_notes=%s, updated_at=%s WHERE id=%s",
            (criticality, calc_notes_str, _now(), bia_id))
        db.commit()

        return {
            "criticality": criticality,
            "composite_score": composite,
            "rto_score": rto_score,
            "fin_score": fin_score,
            "max_impact_score": max_impact,
            "mtpd_guidance": f"Suggested minimum MTPD: {rto * 3}h" if rto else "Set RTO first to calculate MTPD guidance.",
            "validation_errors": validation,
            "notes": notes,
        }
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# PLAN ACTIVATION (BCM-17)
# ═════════════════════════════════════════════════════════════════════════════

def list_active_plans():
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_plans WHERE is_active_plan=1 ORDER BY activated_at DESC"
        ).fetchall())
    finally:
        db.close()


def activate_plan(plan_id, activated_by: str, activated_by_id: int,
                  reason: str = "", incident_id: int = None):
    """Mark a plan as actively deployed. Records the activation in the audit table."""
    db = get_db()
    try:
        db.execute(
            "UPDATE bcm_plans SET is_active_plan=1, activated_at=%s, activated_by=%s, "
            "activation_reason=%s, updated_at=%s WHERE id=%s",
            (_now(), activated_by, reason, _now(), plan_id),
        )
        db.execute(
            "INSERT INTO bcm_plan_activations "
            "(plan_id, action, reason, incident_id, activated_by, activated_by_id) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (plan_id, "activated", reason, incident_id, activated_by, activated_by_id),
        )
        db.commit()
    finally:
        db.close()


def deactivate_plan(plan_id, deactivated_by: str, deactivated_by_id: int,
                    reason: str = ""):
    """Stand down a plan from active status."""
    db = get_db()
    try:
        db.execute(
            "UPDATE bcm_plans SET is_active_plan=0, updated_at=%s WHERE id=%s",
            (_now(), plan_id),
        )
        db.execute(
            "INSERT INTO bcm_plan_activations "
            "(plan_id, action, reason, activated_by, activated_by_id) "
            "VALUES (%s,%s,%s,%s,%s)",
            (plan_id, "deactivated", reason, deactivated_by, deactivated_by_id),
        )
        db.commit()
    finally:
        db.close()


def list_plan_activations(plan_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM bcm_plan_activations WHERE plan_id=%s ORDER BY created_at DESC",
            (plan_id,),
        ).fetchall())
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═════════════════════════════════════════════════════════════════════════════

def get_dashboard_stats():
    db = get_db()
    try:
        # ── raw counts ────────────────────────────────────────────────────────────
        bia_count          = db.execute("SELECT COUNT(*) FROM bcm_bia_records").fetchone()[0]
        risk_count         = db.execute("SELECT COUNT(*) FROM bcm_risks").fetchone()[0]
        open_risks         = db.execute("SELECT COUNT(*) FROM bcm_risks WHERE status='open'").fetchone()[0]
        plan_count         = db.execute("SELECT COUNT(*) FROM bcm_plans").fetchone()[0]
        active_plans       = db.execute("SELECT COUNT(*) FROM bcm_plans WHERE is_active_plan=1").fetchone()[0]
        incident_count     = db.execute("SELECT COUNT(*) FROM bcm_incidents").fetchone()[0]
        open_incidents     = db.execute(
            "SELECT COUNT(*) FROM bcm_incidents WHERE status NOT IN ('resolved','closed')"
        ).fetchone()[0]
        exercise_count     = db.execute("SELECT COUNT(*) FROM bcm_exercises").fetchone()[0]
        completed_exercises = db.execute(
            "SELECT COUNT(*) FROM bcm_exercises WHERE status='completed'"
        ).fetchone()[0]
        vendor_count       = db.execute("SELECT COUNT(*) FROM bcm_vendors WHERE status='active'").fetchone()[0]
        training_modules   = db.execute("SELECT COUNT(*) FROM bcm_training_modules WHERE status='active'").fetchone()[0]
        document_count     = db.execute("SELECT COUNT(*) FROM bcm_documents").fetchone()[0]

        # ── coverage (get_coverage_summary opens and closes its own connection) ──
        coverage  = get_coverage_summary()
        bia_pct   = coverage.get("pct", 0)
        ex_pct    = round(completed_exercises / exercise_count * 100) if exercise_count else 0

        # ── plan status list (up to 6 for dashboard panel) ────────────────────────
        plans_list = _dicts(db.execute(
            "SELECT id, title, owner, status, is_active_plan "
            "FROM bcm_plans ORDER BY is_active_plan DESC, updated_at DESC LIMIT 6"
        ).fetchall())
        approved_plans = sum(1 for p in plans_list if (p.get("status") or "") == "approved")
        review_plans   = sum(1 for p in plans_list if (p.get("status") or "") in ("review", "in_review"))

        # ── risk distribution by score (not closed) ───────────────────────────────
        risk_rows = _dicts(db.execute(
            "SELECT score FROM bcm_risks WHERE status != 'closed'"
        ).fetchall())
        risk_dist = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for r in risk_rows:
            s = int(r.get("score") or 0)
            if   s >= 20: risk_dist["critical"] += 1
            elif s >= 12: risk_dist["high"]     += 1
            elif s >=  6: risk_dist["medium"]   += 1
            else:         risk_dist["low"]      += 1

        # ── recent activity (last 5 events across incidents / exercises / plans) ──
        inc_recent  = _dicts(db.execute(
            "SELECT title, 'Incident declared' AS action, created_at "
            "FROM bcm_incidents ORDER BY created_at DESC LIMIT 3"
        ).fetchall())
        ex_recent   = _dicts(db.execute(
            "SELECT title, ('Exercise ' || COALESCE(status,'scheduled')) AS action, "
            "       updated_at AS created_at "
            "FROM bcm_exercises ORDER BY updated_at DESC LIMIT 3"
        ).fetchall())
        plan_recent = _dicts(db.execute(
            "SELECT title, ('Plan ' || COALESCE(status,'updated')) AS action, "
            "       updated_at AS created_at "
            "FROM bcm_plans ORDER BY updated_at DESC LIMIT 3"
        ).fetchall())
        all_recent = inc_recent + ex_recent + plan_recent
        all_recent.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        recent_activity = [
            {"text": r["action"] + ": " + r["title"], "created_at": r["created_at"]}
            for r in all_recent[:5]
        ]

        # ── active incidents list (for dashboard table) ───────────────────────────
        active_inc_rows = _dicts(db.execute(
            "SELECT id, title, severity, status, commander, created_at, affected_systems "
            "FROM bcm_incidents WHERE status NOT IN ('resolved','closed') "
            "ORDER BY created_at DESC LIMIT 5"
        ).fetchall())
        for row in active_inc_rows:
            row["assigned"]     = row.get("commander") or ""
            row["impact"]       = row.get("affected_systems") or ""
            row["declared_at"]  = row.get("created_at")

        # ── trend strings ─────────────────────────────────────────────────────────
        plans_trend     = str(approved_plans) + " approved"
        if review_plans:
            plans_trend += ", " + str(review_plans) + " in review"
        incidents_trend = str(incident_count) + " total"

        return {
            # Raw counts (kept for backward-compat with /api/reports/summary)
            "bia_count":       bia_count,
            "risk_count":      risk_count,
            "open_risks":      open_risks,
            "plan_count":      plan_count,
            "active_plans":    active_plans,
            "incident_count":  incident_count,
            "open_incidents":  open_incidents,
            "exercise_count":  exercise_count,
            "vendor_count":    vendor_count,
            "training_modules": training_modules,
            "document_count":  document_count,
            "coverage":        coverage,
            # Dashboard-display fields (field names the JS populateStats() reads)
            "bia_coverage_pct": bia_pct,
            "bia_trend":        str(coverage.get("covered", 0)) + " of " + str(bia_count) + " processes covered",
            "plans":            plan_count,
            "plans_trend":      plans_trend,
            "incidents_trend":  incidents_trend,
            "exercise_pct":     ex_pct,
            "bia_records":      bia_count,
            "exercises":        exercise_count,
            "plan_status":      plans_list,
            "risk_distribution": risk_dist,
            "recent_activity":  recent_activity,
            "active_incidents": active_inc_rows,
        }
    finally:
        db.close()
