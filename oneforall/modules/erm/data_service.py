"""
ERM module — Data access layer.
Covers erm_enterprise_risks, erm_risk_appetite, erm_risk_library,
erm_regulatory_obligations, erm_assessments, and the shared risk_register view.
"""
from datetime import datetime
from core.timeutils import utcnow
from database import get_db, insert_returning_id, sql_now_offset, sql_now_ts, sql_days_between, sql_date_offset, sql_date_ts, sql_current_date


def _dict(row):
    return dict(row) if row else None


def _dicts(rows):
    return [dict(r) for r in rows]


def _now():
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ═════════════════════════════════════════════════════════════════════════════
# ENTERPRISE RISKS
# ═════════════════════════════════════════════════════════════════════════════

def list_enterprise_risks(category=None, status=None, source_module=None, board_only=False, limit=500):
    db = get_db()
    try:
        where, params = [], []
        if category:
            where.append("category=%s"); params.append(category)
        if status:
            where.append("status=%s"); params.append(status)
        if source_module:
            where.append("source_module=%s"); params.append(source_module)
        if board_only:
            where.append("board_visibility=1")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        rows = db.execute(
            f"SELECT e.*, u.full_name AS owner_name "
            f"FROM erm_enterprise_risks e "
            f"LEFT JOIN users u ON u.id = e.owner_id "
            f"{clause} ORDER BY "
            f"CASE status WHEN 'open' THEN 0 WHEN 'under_review' THEN 1 ELSE 2 END, "
            f"(likelihood*impact) DESC LIMIT %s",
            params + [limit],
        ).fetchall()
        return _dicts(rows)
    finally:
        db.close()


def get_enterprise_risk(risk_id):
    db = get_db()
    try:
        return _dict(db.execute(
            "SELECT e.*, u.full_name AS owner_name, 'erm' AS register_source "
            "FROM erm_enterprise_risks e LEFT JOIN users u ON u.id=e.owner_id "
            "WHERE e.id=%s", (risk_id,)
        ).fetchone())
    finally:
        db.close()


def create_enterprise_risk(data):
    db = get_db()
    try:
        inh, res, qual = _compute_scores(data)
        cur = insert_returning_id(db,
            """INSERT INTO erm_enterprise_risks
               (title, description, category, sub_category, likelihood, impact, velocity,
                strategic_objective, owner_id, reviewer_id, treatment, treatment_plan,
                residual_likelihood, residual_impact, status, board_visibility,
                regulation_links, review_date, source_module, source_risk_id, created_by,
                inherent_score, residual_score, qualitative_score,
                risk_statement, workflow_step, response_deadline)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (data.get("title"), data.get("description"), data.get("category", "strategic"),
             data.get("sub_category"), data.get("likelihood", 3), data.get("impact", 3),
             data.get("velocity", 3), data.get("strategic_objective"),
             data.get("owner_id"), data.get("reviewer_id"),
             data.get("treatment", "mitigate"), data.get("treatment_plan"),
             data.get("residual_likelihood"), data.get("residual_impact"),
             data.get("status", "open"), data.get("board_visibility", 0),
             data.get("regulation_links"), data.get("review_date"),
             data.get("source_module", "erm"), data.get("source_risk_id"),
             data.get("created_by"),
             inh, res, qual,
             data.get("risk_statement"), data.get("workflow_step", "draft"),
             data.get("response_deadline")),
        )
        db.commit()
        return cur
    finally:
        db.close()


def _compute_scores(data, existing=None):
    """Auto-derive inherent_score, residual_score, qualitative_score from L/I values."""
    L = data.get("likelihood") or (existing.get("likelihood") if existing else 3) or 3
    I = data.get("impact")     or (existing.get("impact")     if existing else 3) or 3
    RL = data.get("residual_likelihood") or (existing.get("residual_likelihood") if existing else None)
    RI = data.get("residual_impact")     or (existing.get("residual_impact")     if existing else None)
    inherent  = int(L) * int(I)
    residual  = int(RL) * int(RI) if RL and RI else None
    qual = "critical" if inherent >= 20 else "high" if inherent >= 12 else "medium" if inherent >= 6 else "low"
    return inherent, residual, qual


def update_enterprise_risk(risk_id, data):
    db = get_db()
    try:
        existing = _dict(db.execute(
            "SELECT likelihood, impact, residual_likelihood, residual_impact "
            "FROM erm_enterprise_risks WHERE id=%s", (risk_id,)
        ).fetchone())
        fields, vals = [], []
        for k in ("title", "description", "category", "sub_category", "likelihood", "impact",
                  "velocity", "strategic_objective", "owner_id", "reviewer_id", "treatment",
                  "treatment_plan", "residual_likelihood", "residual_impact", "status",
                  "board_visibility", "regulation_links", "review_date",
                  "risk_statement", "workflow_step", "response_deadline", "effectiveness_rating",
                  "last_reviewed"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        # Auto-compute scores whenever likelihood/impact touched
        if any(k in data for k in ("likelihood", "impact", "residual_likelihood", "residual_impact")):
            inh, res, qual = _compute_scores(data, existing)
            fields += ["inherent_score=%s", "qualitative_score=%s"]
            vals   += [inh, qual]
            if res is not None:
                fields.append("residual_score=%s"); vals.append(res)
        if fields:
            fields.append("updated_at=%s"); vals.append(_now()); vals.append(risk_id)
            db.execute(f"UPDATE erm_enterprise_risks SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_enterprise_risk(risk_id):
    db = get_db()
    try:
        db.execute("UPDATE erm_kris SET linked_risk_id=NULL WHERE linked_risk_id=%s", (risk_id,))
        db.execute("DELETE FROM erm_risk_workflow_history WHERE risk_id=%s", (risk_id,))
        db.execute("DELETE FROM erm_enterprise_risks WHERE id=%s", (risk_id,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# RISK APPETITE
# ═════════════════════════════════════════════════════════════════════════════

def list_appetite():
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT a.*, u.full_name AS approver_name "
            "FROM erm_risk_appetite a LEFT JOIN users u ON u.id=a.approved_by "
            "ORDER BY category"
        ).fetchall())
    finally:
        db.close()


def get_appetite(appetite_id):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM erm_risk_appetite WHERE id=%s", (appetite_id,)).fetchone())
    finally:
        db.close()


def upsert_appetite(data):
    """Create or update appetite for a category."""
    db = get_db()
    try:
        existing = db.execute(
            "SELECT id FROM erm_risk_appetite WHERE category=%s", (data.get("category"),)
        ).fetchone()
        if existing:
            fields, vals = [], []
            for k in ("appetite_level", "max_score", "description", "tolerance_notes",
                      "approved_by", "effective_date", "review_date"):
                if k in data:
                    fields.append(f"{k}=%s"); vals.append(data[k])
            if fields:
                fields.append("updated_at=%s"); vals.append(_now())
                vals.append(existing[0])
                db.execute(f"UPDATE erm_risk_appetite SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
            return existing[0]
        else:
            cur = insert_returning_id(db,
                "INSERT INTO erm_risk_appetite (category, appetite_level, max_score, description, "
                "tolerance_notes, approved_by, effective_date, review_date) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (data.get("category"), data.get("appetite_level", "medium"),
                 data.get("max_score", 12), data.get("description"),
                 data.get("tolerance_notes"), data.get("approved_by"),
                 data.get("effective_date"), data.get("review_date")),
            )
            db.commit()
            return cur
    finally:
        db.close()


def delete_appetite(appetite_id):
    db = get_db()
    try:
        db.execute("DELETE FROM erm_risk_appetite WHERE id=%s", (appetite_id,))
        db.commit()
    finally:
        db.close()


def get_appetite_status():
    """For each category: current max score in erm_enterprise_risks vs appetite threshold."""
    db = get_db()
    try:
        appetites = _dicts(db.execute("SELECT * FROM erm_risk_appetite").fetchall())
        result = []
        for a in appetites:
            cat = a["category"]
            max_risk = db.execute(
                "SELECT MAX(likelihood*impact) FROM erm_enterprise_risks "
                "WHERE category=%s AND status NOT IN ('closed','accepted')", (cat,)
            ).fetchone()[0] or 0
            count_open = db.execute(
                "SELECT COUNT(*) FROM erm_enterprise_risks "
                "WHERE category=%s AND status NOT IN ('closed','accepted')", (cat,)
            ).fetchone()[0]
            a["current_max_score"] = max_risk
            a["open_count"] = count_open
            a["breached"] = max_risk > a["max_score"]
            # Top risk in this category
            top = db.execute(
                "SELECT id, title, (likelihood*impact) AS score FROM erm_enterprise_risks "
                "WHERE category=%s AND status NOT IN ('closed','accepted') "
                "ORDER BY (likelihood*impact) DESC LIMIT 1", (cat,)
            ).fetchone()
            a["top_risk"] = _dict(top)
            result.append(a)
        return result
    finally:
        db.close()


def mark_appetite_notified(appetite_id, is_breached: bool):
    """Set or clear last_breach_notified_at for a risk appetite row.

    Call with is_breached=True after emitting a breach event.
    Call with is_breached=False when the breach clears, so the next breach fires again.
    """
    db = get_db()
    try:
        value = _now() if is_breached else None
        db.execute(
            "UPDATE erm_risk_appetite SET last_breach_notified_at=%s WHERE id=%s",
            (value, appetite_id),
        )
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# RISK LIBRARY
# ═════════════════════════════════════════════════════════════════════════════

def list_library(category=None, industry=None, limit=200):
    db = get_db()
    try:
        where, params = ["is_active=1"], []
        if category:
            where.append("category=%s"); params.append(category)
        if industry:
            where.append("(applicable_industries LIKE %s OR applicable_industries='all')")
            params.append(f"%{industry}%")
        clause = "WHERE " + " AND ".join(where)
        return _dicts(db.execute(
            f"SELECT * FROM erm_risk_library {clause} ORDER BY category, title LIMIT %s",
            params + [limit],
        ).fetchall())
    finally:
        db.close()


def get_library_item(item_id):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM erm_risk_library WHERE id=%s", (item_id,)).fetchone())
    finally:
        db.close()


def update_library_item(item_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "description", "category", "default_likelihood", "default_impact",
                  "typical_treatment", "suggested_controls", "applicable_industries",
                  "regulatory_references", "tags", "is_active"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        if fields:
            vals.append(item_id)
            db.execute(f"UPDATE erm_risk_library SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_library_item(item_id):
    db = get_db()
    try:
        db.execute("UPDATE erm_risk_library SET is_active=0 WHERE id=%s", (item_id,))
        db.commit()
    finally:
        db.close()


def create_library_item(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO erm_risk_library (title, description, category, default_likelihood, "
            "default_impact, typical_treatment, suggested_controls, applicable_industries, "
            "regulatory_references, tags) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("title"), data.get("description"), data.get("category"),
             data.get("default_likelihood", 3), data.get("default_impact", 3),
             data.get("typical_treatment", "mitigate"), data.get("suggested_controls"),
             data.get("applicable_industries"), data.get("regulatory_references"),
             data.get("tags")),
        )
        db.commit()
        return cur
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# REGULATORY OBLIGATIONS
# ═════════════════════════════════════════════════════════════════════════════

def list_obligations(status=None, regulator=None, limit=500):
    db = get_db()
    try:
        where, params = [], []
        if status:
            where.append("o.status=%s"); params.append(status)
        if regulator:
            where.append("o.regulator=%s"); params.append(regulator)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        return _dicts(db.execute(
            f"SELECT o.*, u.full_name AS owner_name "
            f"FROM erm_regulatory_obligations o LEFT JOIN users u ON u.id=o.owner_id "
            f"{clause} ORDER BY o.due_date ASC NULLS LAST, o.regulator LIMIT %s",
            params + [limit],
        ).fetchall())
    finally:
        db.close()


def get_obligation(obl_id):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM erm_regulatory_obligations WHERE id=%s", (obl_id,)).fetchone())
    finally:
        db.close()


def create_obligation(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO erm_regulatory_obligations "
            "(regulator, regulation_name, obligation, applicable_departments, evidence_required, "
            "owner_id, due_date, status, linked_controls, linked_erm_risk_id, notes, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("regulator"), data.get("regulation_name"), data.get("obligation"),
             data.get("applicable_departments"), data.get("evidence_required"),
             data.get("owner_id"), data.get("due_date"), data.get("status", "pending"),
             data.get("linked_controls"), data.get("linked_erm_risk_id"),
             data.get("notes"), data.get("created_by")),
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_obligation(obl_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("regulator", "regulation_name", "obligation", "applicable_departments",
                  "evidence_required", "owner_id", "due_date", "status",
                  "linked_controls", "linked_erm_risk_id", "notes"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        if fields:
            fields.append("updated_at=%s"); vals.append(_now()); vals.append(obl_id)
            db.execute(f"UPDATE erm_regulatory_obligations SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_obligation(obl_id):
    db = get_db()
    try:
        db.execute("DELETE FROM erm_regulatory_obligations WHERE id=%s", (obl_id,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# SELF-ASSESSMENTS
# ═════════════════════════════════════════════════════════════════════════════

def list_assessments(limit=200):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT a.*, u.full_name AS creator_name, "
            "(SELECT COUNT(*) FROM erm_assessment_questions WHERE assessment_id=a.id) AS question_count "
            "FROM erm_assessments a LEFT JOIN users u ON u.id=a.created_by "
            "ORDER BY a.created_at DESC LIMIT %s", (limit,)
        ).fetchall())
    finally:
        db.close()


def get_assessment(assessment_id):
    db = get_db()
    try:
        a = _dict(db.execute("SELECT * FROM erm_assessments WHERE id=%s", (assessment_id,)).fetchone())
        if a:
            a["questions"] = _dicts(db.execute(
                "SELECT * FROM erm_assessment_questions WHERE assessment_id=%s ORDER BY order_idx",
                (assessment_id,)
            ).fetchall())
        return a
    finally:
        db.close()


def create_assessment(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO erm_assessments (title, type, description, target_audience, status, due_date, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (data.get("title"), data.get("type", "risk"), data.get("description"),
             data.get("target_audience"), data.get("status", "draft"),
             data.get("due_date"), data.get("created_by")),
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_assessment(assessment_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("title", "type", "description", "target_audience", "status", "due_date"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        if fields:
            fields.append("updated_at=%s"); vals.append(_now()); vals.append(assessment_id)
            db.execute(f"UPDATE erm_assessments SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_assessment(assessment_id):
    db = get_db()
    try:
        db.execute("DELETE FROM erm_assessment_responses WHERE assessment_id=%s", (assessment_id,))
        db.execute("DELETE FROM erm_assessment_questions WHERE assessment_id=%s", (assessment_id,))
        db.execute("DELETE FROM erm_assessments WHERE id=%s", (assessment_id,))
        db.commit()
    finally:
        db.close()


def add_question(assessment_id, data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO erm_assessment_questions "
            "(assessment_id, question, question_type, options, weight, order_idx, required) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (assessment_id, data.get("question"), data.get("question_type", "scale"),
             data.get("options"), data.get("weight", 1.0),
             data.get("order_idx", 0), data.get("required", 1)),
        )
        db.commit()
        return cur
    finally:
        db.close()


def delete_question(question_id):
    db = get_db()
    try:
        db.execute("DELETE FROM erm_assessment_questions WHERE id=%s", (question_id,))
        db.commit()
    finally:
        db.close()


def save_response(data):
    db = get_db()
    try:
        # Upsert: delete existing response for this question+respondent then insert
        db.execute(
            "DELETE FROM erm_assessment_responses WHERE assessment_id=%s AND question_id=%s AND respondent_id=%s",
            (data.get("assessment_id"), data.get("question_id"), data.get("respondent_id")),
        )
        cur = insert_returning_id(db,
            "INSERT INTO erm_assessment_responses "
            "(assessment_id, question_id, respondent_id, response, score, notes) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (data.get("assessment_id"), data.get("question_id"), data.get("respondent_id"),
             data.get("response"), data.get("score"), data.get("notes")),
        )
        db.commit()
        return cur
    finally:
        db.close()


def list_responses(assessment_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT r.*, q.question, q.weight, u.full_name AS respondent_name "
            "FROM erm_assessment_responses r "
            "JOIN erm_assessment_questions q ON q.id=r.question_id "
            "LEFT JOIN users u ON u.id=r.respondent_id "
            "WHERE r.assessment_id=%s ORDER BY r.question_id, r.submitted_at",
            (assessment_id,)
        ).fetchall())
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# UNIFIED RISK REGISTER VIEW (erm_enterprise_risks UNION risk_register)
# ═════════════════════════════════════════════════════════════════════════════

def get_unified_register(filters=None, limit=1000):
    """Return all ERM enterprise risks + risk_register entries as a unified list."""
    filters = filters or {}
    cat    = filters.get("category")
    status = filters.get("status")
    db = get_db()
    try:
        # ── ERM enterprise risks ──────────────────────────────────────────
        erm_where, erm_params = [], []
        if cat:    erm_where.append("category=%s");  erm_params.append(cat)
        if status: erm_where.append("status=%s");    erm_params.append(status)
        else:      erm_where.append("status != 'closed'")
        ew = ("WHERE " + " AND ".join(erm_where)) if erm_where else ""
        erm_rows = _dicts(db.execute(
            f"SELECT e.id, e.title, e.description, e.category, e.likelihood, e.impact, "
            f"(e.likelihood*e.impact) AS risk_score, e.status, e.treatment, e.owner_id, "
            f"e.board_visibility, "
            f"'erm' AS register_source, e.source_module, e.created_at, "
            f"u.full_name AS owner_name "
            f"FROM erm_enterprise_risks e "
            f"LEFT JOIN users u ON u.id=e.owner_id "
            f"{ew} ORDER BY (e.likelihood*e.impact) DESC LIMIT %s",
            erm_params + [limit]
        ).fetchall())

        # ── Platform risk_register ────────────────────────────────────────
        rr_where, rr_params = [], []
        if cat:    rr_where.append("r.category=%s");  rr_params.append(cat)
        if status: rr_where.append("r.status=%s");    rr_params.append(status)
        else:      rr_where.append("r.status != 'closed'")
        rw = ("WHERE " + " AND ".join(rr_where)) if rr_where else ""
        rr_rows = _dicts(db.execute(
            f"SELECT r.id, r.title, r.description, r.category, r.likelihood, r.impact, "
            f"r.risk_score, r.status, r.treatment, r.owner_id, "
            f"0 AS board_visibility, "
            f"'risk_register' AS register_source, r.source_module, r.created_at, "
            f"u.full_name AS owner_name "
            f"FROM risk_register r "
            f"LEFT JOIN users u ON u.id=r.owner_id "
            f"{rw} ORDER BY r.risk_score DESC LIMIT %s",
            rr_params + [limit]
        ).fetchall())

        all_risks = erm_rows + rr_rows
        all_risks.sort(key=lambda x: x.get("risk_score") or 0, reverse=True)
        return all_risks[:limit]
    finally:
        db.close()


def get_register_stats():
    """Stats for ERM dashboard: by_level, by_module, by_category, heat_map."""
    db = get_db()
    try:
        def score_to_level(s):
            s = s or 0
            if s >= 20: return "critical"
            if s >= 12: return "high"
            if s >= 6:  return "medium"
            return "low"

        # All open risks from both tables
        erm = _dicts(db.execute(
            "SELECT likelihood, impact, (likelihood*impact) AS score, category, source_module "
            "FROM erm_enterprise_risks WHERE status NOT IN ('closed','accepted')"
        ).fetchall())
        rr = _dicts(db.execute(
            "SELECT likelihood, impact, risk_score AS score, category, source_module "
            "FROM risk_register WHERE status NOT IN ('closed')"
        ).fetchall())
        all_risks = erm + rr

        by_level = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        by_module = {}
        by_category = {}
        heat_map = [[0]*5 for _ in range(5)]

        for r in all_risks:
            lvl = score_to_level(r.get("score"))
            by_level[lvl] = by_level.get(lvl, 0) + 1
            mod = r.get("source_module") or "erm"
            by_module[mod] = by_module.get(mod, 0) + 1
            cat = r.get("category") or "operational"
            by_category[cat] = by_category.get(cat, 0) + 1
            l = min(max((r.get("likelihood") or 1) - 1, 0), 4)
            i = min(max((r.get("impact") or 1) - 1, 0), 4)
            heat_map[l][i] += 1

        return {
            "total": len(all_risks),
            "by_level": by_level,
            "by_module": by_module,
            "by_category": by_category,
            "heat_map": heat_map,
        }
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# RISK FEED (recent events from all modules)
# ═════════════════════════════════════════════════════════════════════════════

def get_risk_feed(limit=20):
    """Recent risk-related events from the platform events table."""
    db = get_db()
    try:
        rows = _dicts(db.execute(
            "SELECT event_type, source_module, source_entity_type, source_entity_id, "
            "payload, created_at FROM events "
            "WHERE event_type LIKE '%%.risk%%' OR event_type LIKE '%%breach%%' "
            "OR event_type LIKE '%%incident%%' OR event_type LIKE '%%escalat%%' "
            "OR event_type LIKE 'erm.%%' OR event_type LIKE 'orm.%%' "
            "ORDER BY created_at DESC LIMIT %s",
            (limit,)
        ).fetchall())
        return rows
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═════════════════════════════════════════════════════════════════════════════

def get_dashboard_stats():
    db = get_db()
    try:
        total_erm = db.execute("SELECT COUNT(*) FROM erm_enterprise_risks WHERE status!='closed'").fetchone()[0]
        critical = db.execute(
            "SELECT COUNT(*) FROM erm_enterprise_risks WHERE (likelihood*impact)>=20 AND status!='closed'"
        ).fetchone()[0]
        high = db.execute(
            "SELECT COUNT(*) FROM erm_enterprise_risks WHERE (likelihood*impact)>=12 AND status!='closed'"
        ).fetchone()[0]
        total_rr = db.execute("SELECT COUNT(*) FROM risk_register WHERE status!='closed'").fetchone()[0]
        appetite_breaches = db.execute(
            "SELECT COUNT(*) FROM erm_enterprise_risks e "
            "JOIN erm_risk_appetite a ON a.category=e.category "
            "WHERE (e.likelihood*e.impact) > a.max_score AND e.status!='closed'"
        ).fetchone()[0]
        overdue_obligations = db.execute(
            "SELECT COUNT(*) FROM erm_regulatory_obligations "
            f"WHERE status NOT IN ('compliant') AND due_date < {sql_current_date()}"
        ).fetchone()[0]
        open_assessments = db.execute(
            "SELECT COUNT(*) FROM erm_assessments WHERE status='active'"
        ).fetchone()[0]
        board_visible = db.execute(
            "SELECT COUNT(*) FROM erm_enterprise_risks WHERE board_visibility=1 AND status!='closed'"
        ).fetchone()[0]

        # Trend: compare current open count to 30 days ago
        erm_30d = db.execute(
            "SELECT COUNT(*) FROM erm_enterprise_risks WHERE status!='closed' "
            f"AND created_at < {sql_now_ts('-30 days')}"
        ).fetchone()[0]
        rr_30d = db.execute(
            "SELECT COUNT(*) FROM risk_register WHERE status!='closed' "
            f"AND created_at < {sql_now_ts('-30 days')}"
        ).fetchone()[0]
        total_30d = erm_30d + rr_30d
        trend_total = (total_erm + total_rr) - total_30d

        crit_30d = db.execute(
            "SELECT COUNT(*) FROM erm_enterprise_risks "
            "WHERE (likelihood*impact)>=20 AND status!='closed' "
            f"AND created_at < {sql_now_ts('-30 days')}"
        ).fetchone()[0]
        trend_critical = critical - crit_30d

        # Top 5 critical risks
        top_critical = _dicts(db.execute(
            "SELECT e.id, e.title, e.category, e.likelihood, e.impact, "
            "(e.likelihood*e.impact) AS score, e.source_module, e.status, "
            "'erm' AS register_source "
            "FROM erm_enterprise_risks e "
            "WHERE e.status IN ('open','under_review') "
            "ORDER BY (e.likelihood*e.impact) DESC LIMIT 5"
        ).fetchall())

        # Actions required: unowned + past-review-date + overdue obligations
        actions = []
        # Unowned ERM risks (no owner_id)
        unowned = _dicts(db.execute(
            "SELECT id, title, 'unowned_risk' AS action_type FROM erm_enterprise_risks "
            "WHERE owner_id IS NULL AND status IN ('open','under_review') LIMIT 5"
        ).fetchall())
        for r in unowned:
            actions.append({"type": "unowned_risk", "id": r["id"],
                            "text": f"Unowned risk: {r['title']}", "link": "/erm/register"})

        # Past review date
        overdue_review = _dicts(db.execute(
            "SELECT id, title FROM erm_enterprise_risks "
            f"WHERE review_date < {sql_current_date()} AND status IN ('open','under_review') "
            "AND review_date IS NOT NULL LIMIT 5"
        ).fetchall())
        for r in overdue_review:
            actions.append({"type": "overdue_review", "id": r["id"],
                            "text": f"Review overdue: {r['title']}", "link": "/erm/register"})

        # Overdue obligations
        overdue_obls = _dicts(db.execute(
            "SELECT id, regulation_name FROM erm_regulatory_obligations "
            f"WHERE status NOT IN ('compliant') AND due_date < {sql_current_date()} LIMIT 5"
        ).fetchall())
        for o in overdue_obls:
            actions.append({"type": "overdue_obligation", "id": o["id"],
                            "text": f"Overdue obligation: {o['regulation_name']}",
                            "link": "/erm/obligations"})

        return {
            "total_enterprise_risks": total_erm,
            "total_register_risks": total_rr,
            "total_risks": total_erm + total_rr,
            "critical": critical,
            "high": high,
            "appetite_breaches": appetite_breaches,
            "overdue_obligations": overdue_obligations,
            "open_assessments": open_assessments,
            "board_visible": board_visible,
            "trend_total": trend_total,
            "trend_critical": trend_critical,
            "top_critical_risks": top_critical,
            "actions_required": actions[:8],
        }
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# CHAT
# ═════════════════════════════════════════════════════════════════════════════

def list_chat(user_id, limit=50):
    db = get_db()
    try:
        rows = _dicts(db.execute(
            "SELECT * FROM erm_chat_messages WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
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
            "INSERT INTO erm_chat_messages (user_id, role, content, provider) VALUES (%s,%s,%s,%s)",
            (user_id, role, content, provider)
        )
        db.commit()
    finally:
        db.close()


def clear_chat(user_id):
    db = get_db()
    try:
        db.execute("DELETE FROM erm_chat_messages WHERE user_id=%s", (user_id,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# KEY RISK INDICATORS (KRIs)
# ═════════════════════════════════════════════════════════════════════════════

def list_kris(linked_risk_id=None):
    db = get_db()
    try:
        where, params = [], []
        if linked_risk_id:
            where.append("k.linked_risk_id=%s"); params.append(linked_risk_id)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        rows = db.execute(
            f"SELECT k.*, u.full_name AS owner_name, r.title AS risk_title "
            f"FROM erm_kris k "
            f"LEFT JOIN users u ON u.id=k.owner_id "
            f"LEFT JOIN erm_enterprise_risks r ON r.id=k.linked_risk_id "
            f"{clause} ORDER BY k.name",
            params
        ).fetchall()
        return _dicts(rows)
    finally:
        db.close()


def get_kri(kri_id):
    db = get_db()
    try:
        return _dict(db.execute(
            "SELECT k.*, u.full_name AS owner_name, r.title AS risk_title "
            "FROM erm_kris k "
            "LEFT JOIN users u ON u.id=k.owner_id "
            "LEFT JOIN erm_enterprise_risks r ON r.id=k.linked_risk_id "
            "WHERE k.id=%s", (kri_id,)
        ).fetchone())
    finally:
        db.close()


def create_kri(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO erm_kris (name, description, linked_risk_id, metric_type, "
            "threshold_warn, threshold_crit, current_value, unit, frequency, owner_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("name"), data.get("description"), data.get("linked_risk_id"),
             data.get("metric_type", "count"), data.get("threshold_warn"),
             data.get("threshold_crit"), data.get("current_value", 0),
             data.get("unit"), data.get("frequency", "monthly"), data.get("owner_id"))
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_kri(kri_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("name", "description", "linked_risk_id", "metric_type",
                  "threshold_warn", "threshold_crit", "unit", "frequency",
                  "owner_id", "status", "trend"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        # Handle value update: also record history
        if "current_value" in data:
            fields.append("current_value=%s"); vals.append(data["current_value"])
            fields.append("last_updated=%s"); vals.append(_now())
            db.execute(
                "INSERT INTO erm_kri_history (kri_id, value) VALUES (%s,%s)",
                (kri_id, data["current_value"])
            )
        if fields:
            fields.append("updated_at=%s"); vals.append(_now()); vals.append(kri_id)
            db.execute(f"UPDATE erm_kris SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_kri(kri_id):
    db = get_db()
    try:
        db.execute("DELETE FROM erm_kris WHERE id=%s", (kri_id,))
        db.commit()
    finally:
        db.close()


def get_kri_history(kri_id, limit=12):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM erm_kri_history WHERE kri_id=%s ORDER BY recorded_at DESC LIMIT %s",
            (kri_id, limit)
        ).fetchall())
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# WORKFLOW HISTORY
# ═════════════════════════════════════════════════════════════════════════════

_WORKFLOW_STEPS = ["draft", "identified", "assessed", "treated", "monitored", "closed"]


def transition_workflow(risk_id, to_step, user_id, notes=None):
    """Advance a risk to the next workflow step. Returns the new step or raises ValueError."""
    db = get_db()
    try:
        risk = db.execute(
            "SELECT workflow_step FROM erm_enterprise_risks WHERE id=%s", (risk_id,)
        ).fetchone()
        if not risk:
            raise ValueError("Risk not found")
        from_step = risk["workflow_step"] or "draft"
        if to_step not in _WORKFLOW_STEPS:
            raise ValueError(f"Invalid step: {to_step}")
        db.execute(
            "INSERT INTO erm_risk_workflow_history (risk_id, from_step, to_step, changed_by, notes) "
            "VALUES (%s,%s,%s,%s,%s)", (risk_id, from_step, to_step, user_id, notes)
        )
        # Keep status field in sync with meaningful workflow steps:
        #   closed   → status = 'closed'    (excluded from appetite calculation)
        #   treated  → status = 'mitigated' (risk action taken)
        #   assessed → status = 'under_review'
        #   any other step → leave status unchanged
        step_status_map = {
            "closed":   "closed",
            "treated":  "mitigated",
            "assessed": "under_review",
        }
        new_status = step_status_map.get(to_step)
        if new_status:
            db.execute(
                "UPDATE erm_enterprise_risks SET workflow_step=%s, status=%s, updated_at=%s WHERE id=%s",
                (to_step, new_status, _now(), risk_id)
            )
        else:
            db.execute(
                "UPDATE erm_enterprise_risks SET workflow_step=%s, updated_at=%s WHERE id=%s",
                (to_step, _now(), risk_id)
            )
        db.commit()
        return to_step
    finally:
        db.close()


def get_workflow_history(risk_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT h.*, u.full_name AS changed_by_name "
            "FROM erm_risk_workflow_history h "
            "LEFT JOIN users u ON u.id=h.changed_by "
            "WHERE h.risk_id=%s ORDER BY h.changed_at ASC",
            (risk_id,)
        ).fetchall())
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# RISK STATEMENT LIBRARY
# ═════════════════════════════════════════════════════════════════════════════

def list_statements(category=None, tags=None, limit=200):
    db = get_db()
    try:
        where, params = [], []
        if category:
            where.append("category=%s"); params.append(category)
        if tags:
            where.append("tags LIKE %s"); params.append(f"%{tags}%")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        return _dicts(db.execute(
            f"SELECT * FROM erm_risk_statements {clause} "
            f"ORDER BY usage_count DESC, created_at DESC LIMIT %s",
            params + [limit]
        ).fetchall())
    finally:
        db.close()


def create_statement(data):
    db = get_db()
    try:
        full = data.get("full_statement") or (
            f"Due to {data.get('cause', '')}, there is a risk that "
            f"{data.get('event', '')}, resulting in {data.get('consequence', '')}."
        )
        cur = insert_returning_id(db,
            "INSERT INTO erm_risk_statements (category, cause, event, consequence, "
            "full_statement, tags, industry) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (data.get("category"), data.get("cause"), data.get("event"),
             data.get("consequence"), full, data.get("tags"), data.get("industry"))
        )
        db.commit()
        return cur
    finally:
        db.close()


def update_statement(stmt_id, data):
    db = get_db()
    try:
        fields, vals = [], []
        for k in ("category", "cause", "event", "consequence", "full_statement", "tags", "industry"):
            if k in data:
                fields.append(f"{k}=%s"); vals.append(data[k])
        if fields:
            vals.append(stmt_id)
            db.execute(f"UPDATE erm_risk_statements SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def delete_statement(stmt_id):
    db = get_db()
    try:
        db.execute("DELETE FROM erm_risk_statements WHERE id=%s", (stmt_id,))
        db.commit()
    finally:
        db.close()


def use_statement(stmt_id):
    """Increment usage count and return the statement."""
    db = get_db()
    try:
        db.execute(
            "UPDATE erm_risk_statements SET usage_count=usage_count+1 WHERE id=%s", (stmt_id,)
        )
        db.commit()
        return _dict(db.execute("SELECT * FROM erm_risk_statements WHERE id=%s", (stmt_id,)).fetchone())
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# REPORTING DATA
# ═════════════════════════════════════════════════════════════════════════════

def get_trend_data(period_days=30):
    """Return weekly risk count snapshots over the given period."""
    db = get_db()
    try:
        rows = db.execute(
            f"SELECT date(created_at) AS day, COUNT(*) AS new_risks "
            f"FROM erm_enterprise_risks "
            f"WHERE created_at >= {sql_date_ts(f'-{int(period_days)} days')} "
            f"GROUP BY day ORDER BY day ASC"
        ).fetchall()
        # Also get total open per day using current status snapshot
        total_open = db.execute(
            "SELECT COUNT(*) FROM erm_enterprise_risks WHERE status NOT IN ('closed','accepted')"
        ).fetchone()[0]
        critical_open = db.execute(
            "SELECT COUNT(*) FROM erm_enterprise_risks "
            "WHERE status NOT IN ('closed','accepted') AND (inherent_score>=20 OR likelihood*impact>=20)"
        ).fetchone()[0]
        return {
            "daily": _dicts(rows),
            "total_open": total_open,
            "critical_open": critical_open,
            "period_days": period_days
        }
    finally:
        db.close()


def get_risk_aging():
    """Bucket open risks by how long they have been open."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, title, category, qualitative_score, "
            f"""CAST({sql_days_between("'now'", "created_at")} AS INTEGER) AS days_open """
            "FROM erm_enterprise_risks "
            "WHERE status NOT IN ('closed','accepted') ORDER BY days_open DESC"
        ).fetchall()
        buckets = {"lt30": [], "d30_90": [], "d90_180": [], "gt180": []}
        for r in rows:
            d = r["days_open"] or 0
            key = "lt30" if d < 30 else "d30_90" if d < 90 else "d90_180" if d < 180 else "gt180"
            buckets[key].append(dict(r))
        return {k: {"count": len(v), "risks": v[:5]} for k, v in buckets.items()}
    finally:
        db.close()


def get_executive_dashboard():
    """Board-level view: board_visibility=1 risks + appetite status + top 3 actions."""
    db = get_db()
    try:
        board_risks = _dicts(db.execute(
            "SELECT e.*, u.full_name AS owner_name "
            "FROM erm_enterprise_risks e "
            "LEFT JOIN users u ON u.id=e.owner_id "
            "WHERE e.board_visibility=1 AND e.status NOT IN ('closed','accepted') "
            "ORDER BY (e.likelihood*e.impact) DESC LIMIT 10"
        ).fetchall())
        appetite = _dicts(db.execute(
            "SELECT a.*, "
            "(SELECT MAX(likelihood*impact) FROM erm_enterprise_risks "
            " WHERE category=a.category AND status NOT IN ('closed','accepted')) AS current_score "
            "FROM erm_risk_appetite a ORDER BY category"
        ).fetchall())
        for a in appetite:
            a["breached"] = bool(a.get("current_score") and a["current_score"] > a["max_score"])
        actions = _dicts(db.execute(
            "SELECT id, title, category, qualitative_score, owner_id "
            "FROM erm_enterprise_risks "
            f"WHERE (owner_id IS NULL OR review_date < {sql_current_date()}) "
            "AND status NOT IN ('closed','accepted') LIMIT 3"
        ).fetchall())
        total = db.execute(
            "SELECT COUNT(*) FROM erm_enterprise_risks WHERE status NOT IN ('closed','accepted')"
        ).fetchone()[0]
        critical = db.execute(
            "SELECT COUNT(*) FROM erm_enterprise_risks "
            "WHERE status NOT IN ('closed','accepted') AND (inherent_score>=20 OR likelihood*impact>=20)"
        ).fetchone()[0]
        return {
            "board_risks": board_risks, "appetite": appetite,
            "actions": actions, "total_open": total, "critical": critical
        }
    finally:
        db.close()
