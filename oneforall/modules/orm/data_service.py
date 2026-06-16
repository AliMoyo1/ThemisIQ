"""
ORM module — Operational Risk Management data layer.
Covers orm_events, orm_kris, dashboard stats, chat, KRI history,
event workflow, SLA tracking, and RCSA.
"""
from datetime import datetime, timedelta
from core.timeutils import utcnow
from database import get_db, insert_returning_id


def _dict(row):
    return dict(row) if row else None


def _dicts(rows):
    return [dict(r) for r in rows]


def _now():
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ═════════════════════════════════════════════════════════════════════════════
# EVENTS
# ═════════════════════════════════════════════════════════════════════════════

def list_events(event_type=None, severity=None, status=None, department=None,
                date_from=None, date_to=None, limit=500):
    db = get_db()
    try:
        where, params = [], []
        if event_type:
            where.append("event_type=%s"); params.append(event_type)
        if severity:
            where.append("severity=%s"); params.append(severity)
        if status:
            where.append("status=%s"); params.append(status)
        if department:
            where.append("department=%s"); params.append(department)
        if date_from:
            where.append("created_at >= %s"); params.append(date_from)
        if date_to:
            where.append("created_at <= %s"); params.append(date_to + " 23:59:59")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        return _dicts(db.execute(
            f"SELECT e.*, u.full_name AS reporter_name, o.full_name AS owner_name "
            f"FROM orm_events e "
            f"LEFT JOIN users u ON u.id=e.reported_by "
            f"LEFT JOIN users o ON o.id=e.owner_id "
            f"{clause} ORDER BY e.created_at DESC LIMIT %s",
            params + [limit],
        ).fetchall())
    finally:
        db.close()


def get_event(event_id):
    db = get_db()
    try:
        return _dict(db.execute(
            "SELECT e.*, u.full_name AS reporter_name, o.full_name AS owner_name "
            "FROM orm_events e "
            "LEFT JOIN users u ON u.id=e.reported_by "
            "LEFT JOIN users o ON o.id=e.owner_id "
            "WHERE e.id=%s", (event_id,)
        ).fetchone())
    finally:
        db.close()


def create_event(data):
    db = get_db()
    try:
        sev = data.get("severity", "medium")
        resp_due, res_due = _compute_sla_deadlines(sev)
        eid = insert_returning_id(db,
            """INSERT INTO orm_events
               (title, description, event_type, severity, status, department,
                process_affected, root_cause, root_cause_category, financial_impact,
                customers_affected, downtime_minutes, detected_at, resolved_at,
                reported_by, owner_id, corrective_action, preventive_action, is_recurring,
                workflow_step, response_due_at, resolution_due_at, basel_category)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("title"), data.get("description"),
             data.get("event_type", "process_failure"),
             sev, data.get("status", "open"),
             data.get("department"), data.get("process_affected"),
             data.get("root_cause"), data.get("root_cause_category"),
             data.get("financial_impact", 0), data.get("customers_affected", 0),
             data.get("downtime_minutes", 0), data.get("detected_at"),
             data.get("resolved_at"), data.get("reported_by"), data.get("owner_id"),
             data.get("corrective_action"), data.get("preventive_action"),
             data.get("is_recurring", 0),
             data.get("workflow_step", "identified"),
             resp_due, res_due,
             data.get("basel_category")),
        )
        # Record initial workflow step in history
        db.execute(
            "INSERT INTO orm_event_workflow_history (event_id, from_step, to_step, changed_by, notes) "
            "VALUES (%s,%s,%s,%s,%s)",
            (eid, None, "identified", data.get("reported_by"), "Event created")
        )
        db.commit()
        return eid
    finally:
        db.close()


def update_event(event_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "description", "event_type", "severity", "status", "department",
                  "process_affected", "root_cause", "root_cause_category", "financial_impact",
                  "customers_affected", "downtime_minutes", "detected_at", "resolved_at",
                  "owner_id", "corrective_action", "preventive_action", "is_recurring",
                  "erm_risk_id", "workflow_step", "response_due_at", "resolution_due_at",
                  "basel_category"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        if data.get("status") == "resolved" and "resolved_at" not in data:
            fields.append("resolved_at=%s"); vals.append(_now())
        if fields:
            fields.append("updated_at=%s"); vals.append(_now()); vals.append(event_id)
            db.execute(f"UPDATE orm_events SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_event(event_id):
    db = get_db()
    try:
        db.execute("DELETE FROM orm_events WHERE id=%s", (event_id,))
        db.commit()
    finally:
        db.close()


def link_to_erm(event_id, erm_risk_id):
    db = get_db()
    try:
        db.execute("UPDATE orm_events SET erm_risk_id=%s, updated_at=%s WHERE id=%s",
                   (erm_risk_id, _now(), event_id))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# KEY RISK INDICATORS
# ═════════════════════════════════════════════════════════════════════════════

def list_kris(limit=200):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT k.*, u.full_name AS owner_name "
            "FROM orm_kris k LEFT JOIN users u ON u.id=k.owner_id "
            "WHERE k.status='active' ORDER BY k.name LIMIT %s", (limit,)
        ).fetchall())
    finally:
        db.close()


def get_kri(kri_id):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM orm_kris WHERE id=%s", (kri_id,)).fetchone())
    finally:
        db.close()


def create_kri(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO orm_kris (name, description, metric_type, threshold_warn, threshold_crit, "
            "current_value, unit, frequency, owner_id, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("name"), data.get("description"), data.get("metric_type", "count"),
             data.get("threshold_warn"), data.get("threshold_crit"),
             data.get("current_value", 0), data.get("unit", "events"),
             data.get("frequency", "monthly"), data.get("owner_id"),
             data.get("status", "active")),
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_kri(kri_id, data, user_id=None):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("name", "description", "metric_type", "threshold_warn", "threshold_crit",
                  "current_value", "unit", "frequency", "owner_id", "status", "trend"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        value_changed = "current_value" in data
        if value_changed:
            fields.append("last_updated=%s"); vals.append(_now())
        if fields:
            fields.append("updated_at=%s"); vals.append(_now()); vals.append(kri_id)
            db.execute(f"UPDATE orm_kris SET {','.join(fields)} WHERE id=%s", vals)
        if value_changed:
            # Record history row for sparkline / trend analysis
            db.execute(
                "INSERT INTO orm_kri_history (kri_id, value, recorded_by) VALUES (%s,%s,%s)",
                (kri_id, data["current_value"], user_id)
            )
            # Auto-compute trend from last 3 history values
            hist = db.execute(
                "SELECT value FROM orm_kri_history WHERE kri_id=%s ORDER BY recorded_at DESC LIMIT 3",
                (kri_id,)
            ).fetchall()
            if len(hist) >= 2:
                latest = hist[0][0]; prior = hist[-1][0]
                trend = "improving" if latest < prior else ("worsening" if latest > prior else "stable")
                db.execute("UPDATE orm_kris SET trend=%s WHERE id=%s", (trend, kri_id))
        db.commit()
    finally:
        db.close()


def delete_kri(kri_id):
    db = get_db()
    try:
        db.execute("DELETE FROM orm_kris WHERE id=%s", (kri_id,))
        db.commit()
    finally:
        db.close()


def list_event_templates(category=None, is_active=True):
    db = get_db()
    try:
        where, params = [], []
        if is_active is not None:
            where.append("is_active=%s"); params.append(1 if is_active else 0)
        if category:
            where.append("category=%s"); params.append(category)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        return _dicts(db.execute(
            f"SELECT * FROM orm_event_templates {clause} "
            "ORDER BY category, severity DESC, usage_count DESC",
            params
        ).fetchall())
    finally:
        db.close()


def get_event_template(template_id):
    db = get_db()
    try:
        return _dict(db.execute(
            "SELECT * FROM orm_event_templates WHERE id=%s", (template_id,)
        ).fetchone())
    finally:
        db.close()


def create_event_template(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO orm_event_templates "
            "(title, description, category, event_type, severity, department, "
            "process_affected, root_cause_category, corrective_action, preventive_action, "
            "basel_category, tags, is_active) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("title"), data.get("description"),
             data.get("category", "Process & Operations"),
             data.get("event_type", "process_failure"),
             data.get("severity", "medium"),
             data.get("department"), data.get("process_affected"),
             data.get("root_cause_category"), data.get("corrective_action"),
             data.get("preventive_action"), data.get("basel_category"),
             data.get("tags"), data.get("is_active", 1))
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_event_template(template_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "description", "category", "event_type", "severity", "department",
                  "process_affected", "root_cause_category", "corrective_action",
                  "preventive_action", "basel_category", "tags", "is_active"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        if fields:
            vals.append(template_id)
            db.execute(f"UPDATE orm_event_templates SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_event_template(template_id):
    db = get_db()
    try:
        db.execute("DELETE FROM orm_event_templates WHERE id=%s", (template_id,))
        db.commit()
    finally:
        db.close()


def increment_template_usage(template_id):
    db = get_db()
    try:
        db.execute(
            "UPDATE orm_event_templates SET usage_count = usage_count + 1 WHERE id=%s",
            (template_id,)
        )
        db.commit()
    finally:
        db.close()


def get_kri_history(kri_id, limit=12):
    """Return last N history rows for sparkline / trend display."""
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT h.*, u.full_name AS recorded_by_name "
            "FROM orm_kri_history h LEFT JOIN users u ON u.id=h.recorded_by "
            "WHERE h.kri_id=%s ORDER BY h.recorded_at DESC LIMIT %s",
            (kri_id, limit)
        ).fetchall())
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# EVENT WORKFLOW
# ═════════════════════════════════════════════════════════════════════════════

_WORKFLOW_STEPS = ["identified", "under_investigation", "root_cause_confirmed",
                   "remediation", "closed"]

# When advancing workflow, auto-update the event status field too
_STEP_STATUS_MAP = {
    "identified":           "open",
    "under_investigation":  "investigating",
    "root_cause_confirmed": "investigating",
    "remediation":          "investigating",
    "closed":               "closed",
}


def transition_event_workflow(event_id, to_step, user_id=None, notes=None):
    """Advance an event to the given workflow step, recording history."""
    db = get_db()
    try:
        ev = db.execute("SELECT workflow_step, status FROM orm_events WHERE id=%s", (event_id,)).fetchone()
        if not ev:
            return None
        from_step = ev["workflow_step"] if ev else None
        new_status = _STEP_STATUS_MAP.get(to_step)
        update_fields = ["workflow_step=%s", "updated_at=%s"]
        update_vals = [to_step, _now()]
        if new_status:
            update_fields.append("status=%s")
            update_vals.append(new_status)
        if to_step == "closed":
            update_fields.append("resolved_at=%s")
            update_vals.append(_now())
        update_vals.append(event_id)
        db.execute(f"UPDATE orm_events SET {','.join(update_fields)} WHERE id=%s", update_vals)
        db.execute(
            "INSERT INTO orm_event_workflow_history (event_id, from_step, to_step, changed_by, notes) "
            "VALUES (%s,%s,%s,%s,%s)",
            (event_id, from_step, to_step, user_id, notes)
        )
        db.commit()
        return {"ok": True, "from_step": from_step, "to_step": to_step}
    finally:
        db.close()


def get_event_workflow_history(event_id):
    """Return full workflow history for an event."""
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT h.*, u.full_name AS changed_by_name "
            "FROM orm_event_workflow_history h LEFT JOIN users u ON u.id=h.changed_by "
            "WHERE h.event_id=%s ORDER BY h.changed_at ASC",
            (event_id,)
        ).fetchall())
    finally:
        db.close()


def get_sla_overdue_count():
    """Count events where response_due_at or resolution_due_at has passed."""
    db = get_db()
    try:
        now = _now()
        row = db.execute(
            "SELECT COUNT(*) FROM orm_events "
            "WHERE status NOT IN ('closed','resolved') "
            "AND (response_due_at < %s OR resolution_due_at < %s)",
            (now, now)
        ).fetchone()
        return row[0] if row else 0
    except Exception:
        return 0
    finally:
        db.close()


def _compute_sla_deadlines(severity):
    """Return (response_due, resolution_due) datetimes based on severity."""
    now = utcnow()
    sla = {
        "critical": (24, 5 * 24),
        "high":     (48, 10 * 24),
        "medium":   (72, 30 * 24),
        "low":      (96, 60 * 24),
    }
    resp_h, res_h = sla.get(severity, (72, 30 * 24))
    resp_due = (now + timedelta(hours=resp_h)).strftime("%Y-%m-%d %H:%M:%S")
    res_due = (now + timedelta(hours=res_h)).strftime("%Y-%m-%d %H:%M:%S")
    return resp_due, res_due


# ═════════════════════════════════════════════════════════════════════════════
# RCSA — Risk & Control Self-Assessment
# ═════════════════════════════════════════════════════════════════════════════

def list_rcsa_assessments():
    db = get_db()
    try:
        rows = _dicts(db.execute(
            "SELECT a.*, u.full_name AS owner_name, "
            "(SELECT COUNT(*) FROM orm_rcsa_risks r WHERE r.assessment_id=a.id) AS risk_count, "
            "(SELECT COUNT(*) FROM orm_rcsa_actions ac "
            " JOIN orm_rcsa_controls c ON c.id=ac.control_id "
            " JOIN orm_rcsa_risks r2 ON r2.id=c.risk_id "
            " WHERE r2.assessment_id=a.id AND ac.status='open') AS open_actions "
            "FROM orm_rcsa_assessments a LEFT JOIN users u ON u.id=a.owner_id "
            "ORDER BY a.created_at DESC"
        ).fetchall())
        return rows
    finally:
        db.close()


def get_rcsa_assessment(assessment_id):
    db = get_db()
    try:
        return _dict(db.execute(
            "SELECT a.*, u.full_name AS owner_name "
            "FROM orm_rcsa_assessments a LEFT JOIN users u ON u.id=a.owner_id "
            "WHERE a.id=%s", (assessment_id,)
        ).fetchone())
    finally:
        db.close()


def create_rcsa_assessment(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO orm_rcsa_assessments (title, scope, period_start, period_end, "
            "status, owner_id, due_date, notes, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("title"), data.get("scope"), data.get("period_start"),
             data.get("period_end"), data.get("status", "draft"),
             data.get("owner_id"), data.get("due_date"), data.get("notes"),
             data.get("created_by"))
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_rcsa_assessment(assessment_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "scope", "period_start", "period_end", "status",
                  "owner_id", "due_date", "notes"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        if fields:
            fields.append("updated_at=%s"); vals.append(_now()); vals.append(assessment_id)
            db.execute(f"UPDATE orm_rcsa_assessments SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_rcsa_assessment(assessment_id):
    db = get_db()
    try:
        db.execute("DELETE FROM orm_rcsa_assessments WHERE id=%s", (assessment_id,))
        db.commit()
    finally:
        db.close()


def list_rcsa_risks(assessment_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT r.*, u.full_name AS owner_name, "
            "(SELECT COUNT(*) FROM orm_rcsa_controls c WHERE c.risk_id=r.id) AS control_count "
            "FROM orm_rcsa_risks r LEFT JOIN users u ON u.id=r.owner_id "
            "WHERE r.assessment_id=%s ORDER BY r.inherent_likelihood*r.inherent_impact DESC",
            (assessment_id,)
        ).fetchall())
    finally:
        db.close()


def create_rcsa_risk(data):
    db = get_db()
    try:
        il = data.get("inherent_likelihood", 3)
        ii = data.get("inherent_impact", 3)
        ce = data.get("control_effectiveness", 3)
        residual = round(il * ii * (1 - ce / 5), 2)
        cur = insert_returning_id(db,
            "INSERT INTO orm_rcsa_risks (assessment_id, title, category, inherent_likelihood, "
            "inherent_impact, control_effectiveness, residual_score, owner_id, notes) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("assessment_id"), data.get("title"), data.get("category", "operational"),
             il, ii, ce, residual, data.get("owner_id"), data.get("notes"))
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_rcsa_risk(risk_id, data):
    db = get_db()
    try:
        # Recompute residual if scores change
        if any(k in data for k in ("inherent_likelihood", "inherent_impact", "control_effectiveness")):
            cur = db.execute("SELECT inherent_likelihood, inherent_impact, control_effectiveness "
                             "FROM orm_rcsa_risks WHERE id=%s", (risk_id,)).fetchone()
            if cur:
                il = data.get("inherent_likelihood", cur["inherent_likelihood"])
                ii = data.get("inherent_impact", cur["inherent_impact"])
                ce = data.get("control_effectiveness", cur["control_effectiveness"])
                data["residual_score"] = round(il * ii * (1 - ce / 5), 2)
        fields, vals = [], []
        for k in ("title", "category", "inherent_likelihood", "inherent_impact",
                  "control_effectiveness", "residual_score", "owner_id", "notes"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        if fields:
            vals.append(risk_id)
            db.execute(f"UPDATE orm_rcsa_risks SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_rcsa_risk(risk_id):
    db = get_db()
    try:
        db.execute("DELETE FROM orm_rcsa_risks WHERE id=%s", (risk_id,))
        db.commit()
    finally:
        db.close()


def list_rcsa_controls(risk_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT c.*, u.full_name AS tested_by_name "
            "FROM orm_rcsa_controls c LEFT JOIN users u ON u.id=c.tested_by "
            "WHERE c.risk_id=%s ORDER BY c.created_at",
            (risk_id,)
        ).fetchall())
    finally:
        db.close()


def create_rcsa_control(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO orm_rcsa_controls (risk_id, name, aria_control_id, "
            "design_effectiveness, operating_effectiveness, test_date, tested_by, "
            "evidence_notes, gap_description) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("risk_id"), data.get("name"), data.get("aria_control_id"),
             data.get("design_effectiveness", "adequate"),
             data.get("operating_effectiveness", "effective"),
             data.get("test_date"), data.get("tested_by"),
             data.get("evidence_notes"), data.get("gap_description"))
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_rcsa_control(control_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("name", "aria_control_id", "design_effectiveness", "operating_effectiveness",
                  "test_date", "tested_by", "evidence_notes", "gap_description"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        if fields:
            vals.append(control_id)
            db.execute(f"UPDATE orm_rcsa_controls SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_rcsa_control(control_id):
    db = get_db()
    try:
        db.execute("DELETE FROM orm_rcsa_controls WHERE id=%s", (control_id,))
        db.commit()
    finally:
        db.close()


def list_rcsa_actions(control_id=None, assessment_id=None):
    db = get_db()
    try:
        if assessment_id:
            return _dicts(db.execute(
                "SELECT a.*, u.full_name AS owner_name, c.name AS control_name, "
                "r.title AS risk_title "
                "FROM orm_rcsa_actions a "
                "LEFT JOIN users u ON u.id=a.owner_id "
                "JOIN orm_rcsa_controls c ON c.id=a.control_id "
                "JOIN orm_rcsa_risks r ON r.id=c.risk_id "
                "WHERE r.assessment_id=%s ORDER BY a.due_date",
                (assessment_id,)
            ).fetchall())
        return _dicts(db.execute(
            "SELECT a.*, u.full_name AS owner_name "
            "FROM orm_rcsa_actions a LEFT JOIN users u ON u.id=a.owner_id "
            "WHERE a.control_id=%s ORDER BY a.due_date",
            (control_id,)
        ).fetchall())
    finally:
        db.close()


def create_rcsa_action(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO orm_rcsa_actions (control_id, title, description, owner_id, due_date, status, notes) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (data.get("control_id"), data.get("title"), data.get("description"),
             data.get("owner_id"), data.get("due_date"), data.get("status", "open"),
             data.get("notes"))
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_rcsa_action(action_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "description", "owner_id", "due_date", "status", "notes"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        if fields:
            fields.append("updated_at=%s"); vals.append(_now()); vals.append(action_id)
            db.execute(f"UPDATE orm_rcsa_actions SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_rcsa_action(action_id):
    db = get_db()
    try:
        db.execute("DELETE FROM orm_rcsa_actions WHERE id=%s", (action_id,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═════════════════════════════════════════════════════════════════════════════

def get_dashboard_stats(days=30):
    """Stats for the ORM dashboard over the last N days."""
    db = get_db()
    try:
        since = (utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        prev_since = (utcnow() - timedelta(days=days*2)).strftime("%Y-%m-%d")
        prev_to = since

        def count_period(where_extra="", params=()):
            return db.execute(
                f"SELECT COUNT(*) FROM orm_events WHERE created_at >= %s {where_extra}",
                (since,) + params,
            ).fetchone()[0]

        total = count_period()
        prev_total = db.execute(
            "SELECT COUNT(*) FROM orm_events WHERE created_at >= %s AND created_at < %s",
            (prev_since, prev_to)
        ).fetchone()[0]

        fin_loss = db.execute(
            "SELECT COALESCE(SUM(financial_impact),0) FROM orm_events WHERE created_at >= %s",
            (since,)
        ).fetchone()[0]
        prev_fin = db.execute(
            "SELECT COALESCE(SUM(financial_impact),0) FROM orm_events WHERE created_at >= %s AND created_at < %s",
            (prev_since, prev_to)
        ).fetchone()[0]

        customers = db.execute(
            "SELECT COALESCE(SUM(customers_affected),0) FROM orm_events WHERE created_at >= %s",
            (since,)
        ).fetchone()[0]
        prev_customers = db.execute(
            "SELECT COALESCE(SUM(customers_affected),0) FROM orm_events WHERE created_at >= %s AND created_at < %s",
            (prev_since, prev_to)
        ).fetchone()[0]

        downtime_mins = db.execute(
            "SELECT COALESCE(SUM(downtime_minutes),0) FROM orm_events WHERE created_at >= %s",
            (since,)
        ).fetchone()[0]
        prev_downtime = db.execute(
            "SELECT COALESCE(SUM(downtime_minutes),0) FROM orm_events WHERE created_at >= %s AND created_at < %s",
            (prev_since, prev_to)
        ).fetchone()[0]

        # By type
        type_rows = _dicts(db.execute(
            "SELECT event_type, COUNT(*) AS cnt FROM orm_events WHERE created_at >= %s GROUP BY event_type ORDER BY cnt DESC",
            (since,)
        ).fetchall())

        # Top 5 by financial impact
        top5 = _dicts(db.execute(
            "SELECT id, title, event_type, financial_impact, severity FROM orm_events "
            "WHERE created_at >= %s AND financial_impact > 0 ORDER BY financial_impact DESC LIMIT 5",
            (since,)
        ).fetchall())

        # Recent events
        recent = _dicts(db.execute(
            "SELECT id, title, event_type, severity, status, financial_impact, created_at "
            "FROM orm_events ORDER BY created_at DESC LIMIT 10"
        ).fetchall())

        # SLA overdue count
        now_str = utcnow().strftime("%Y-%m-%d %H:%M:%S")
        sla_overdue = db.execute(
            "SELECT COUNT(*) FROM orm_events "
            "WHERE status NOT IN ('closed','resolved') "
            "AND (response_due_at < %s OR resolution_due_at < %s)",
            (now_str, now_str)
        ).fetchone()[0]

        return {
            "period_days": days,
            "total_events": total,
            "total_events_delta": total - prev_total,
            "financial_loss": fin_loss,
            "financial_loss_delta": fin_loss - prev_fin,
            "customers_affected": customers,
            "customers_delta": customers - prev_customers,
            "downtime_hours": round(downtime_mins / 60, 1),
            "downtime_delta": round((downtime_mins - prev_downtime) / 60, 1),
            "by_type": type_rows,
            "top5_by_impact": top5,
            "recent_events": recent,
            "sla_overdue": sla_overdue,
        }
    finally:
        db.close()


def get_distinct_departments():
    db = get_db()
    try:
        rows = db.execute(
            "SELECT DISTINCT department FROM orm_events WHERE department IS NOT NULL AND department != '' ORDER BY department"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        db.close()


def has_active_bcm_incident():
    db = get_db()
    try:
        row = db.execute(
            "SELECT id FROM bcm_incidents WHERE status NOT IN ('resolved','closed') LIMIT 1"
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        db.close()


def has_active_sentinel_breach():
    """Check if Sentinel has any active/open incidents or breaches."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT id FROM sentinel_incidents WHERE status NOT IN ('resolved','closed') LIMIT 1"
        ).fetchone()
        return row is not None
    except Exception:
        try:
            row = db.execute(
                "SELECT id FROM data_breaches WHERE status NOT IN ('resolved','closed') LIMIT 1"
            ).fetchone()
            return row is not None
        except Exception:
            return False
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# CHAT
# ═════════════════════════════════════════════════════════════════════════════

def list_chat(user_id, limit=50):
    db = get_db()
    try:
        rows = _dicts(db.execute(
            "SELECT * FROM orm_chat_messages WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit)
        ).fetchall())
        rows.reverse()
        return rows
    finally:
        db.close()


def save_chat(user_id, role, content, provider=None):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO orm_chat_messages (user_id, role, content, provider) VALUES (%s,%s,%s,%s)",
            (user_id, role, content, provider)
        )
        db.commit()
    finally:
        db.close()


def clear_chat(user_id):
    db = get_db()
    try:
        db.execute("DELETE FROM orm_chat_messages WHERE user_id=%s", (user_id,))
        db.commit()
    finally:
        db.close()
