"""
Data Protection Sentinel — SQLite database layer.
Unified schema covering RoPA, DPIA, Breaches, DSR, Vendors,
Privacy Notices, Consent, Controllers, Audit Log, and Users.
"""
import sqlite3
import json
import os
import random
import string
import hashlib
import secrets
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_PATH = os.getenv("DATABASE_PATH", "sentinel.db")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


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
    ts = datetime.utcnow().strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"{prefix}-{ts}-{suffix}"


def _hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def _verify_password(password, stored):
    try:
        salt, hashed = stored.split(":", 1)
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == hashed
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA INIT
# ═══════════════════════════════════════════════════════════════════════════════

def init_db():
    with get_db() as conn:
        conn.executescript("""

        -- ── Users ────────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT UNIQUE NOT NULL,
            email           TEXT UNIQUE NOT NULL,
            full_name       TEXT NOT NULL,
            password_hash   TEXT NOT NULL,
            role            TEXT NOT NULL DEFAULT 'viewer',
            is_active       INTEGER DEFAULT 1,
            last_login      TEXT,
            avatar_initials TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── RoPA Entries ────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS ropa_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_number      TEXT UNIQUE NOT NULL,
            processing_name TEXT NOT NULL,
            department      TEXT,
            owner           TEXT,
            regulation      TEXT DEFAULT 'GDPR',
            purpose         TEXT,
            legal_basis     TEXT,
            data_categories TEXT,   -- JSON array
            special_categories TEXT, -- JSON array
            data_subjects   TEXT,
            subject_count   TEXT,
            retention_period TEXT,
            systems         TEXT,
            processors      TEXT,   -- JSON array
            recipients      TEXT,   -- JSON array
            intl_transfers  TEXT,
            transfer_dest   TEXT,
            transfer_safeguard TEXT,
            security_measures  TEXT, -- JSON array
            dpia_required   INTEGER DEFAULT 0,
            dpia_id         INTEGER REFERENCES dpias(id),
            risk_score      TEXT DEFAULT 'low',
            ai_risk_notes   TEXT,
            status          TEXT DEFAULT 'active',
            review_date     TEXT,
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── DPIAs ────────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS dpias (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_number      TEXT UNIQUE NOT NULL,
            title           TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'draft',
            regulation      TEXT NOT NULL,
            org_name        TEXT,
            department      TEXT,
            controller_name TEXT,
            dpo_name        TEXT,
            dpo_email       TEXT,
            activity_type   TEXT,
            activity_desc   TEXT,
            purpose         TEXT,
            legal_basis     TEXT,
            data_categories TEXT,
            special_cats    TEXT,
            data_subjects   TEXT,
            subject_count   TEXT,
            retention       TEXT,
            systems         TEXT,
            processors      TEXT,
            intl_transfer   TEXT,
            transfer_dest   TEXT,
            transfer_mech   TEXT,
            necessity       TEXT,
            proportionality TEXT,
            risks           TEXT,
            overall_risk    TEXT,
            residual_risk   TEXT,
            dpo_consulted   TEXT,
            auth_consulted  TEXT,
            subjects_consulted TEXT,
            consult_notes   TEXT,
            ai_research     TEXT,
            ai_full_dpia    TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Breach & Incident Register ───────────────────────────────────────
        CREATE TABLE IF NOT EXISTS breaches (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_number      TEXT UNIQUE NOT NULL,
            title           TEXT NOT NULL,
            regulation      TEXT DEFAULT 'GDPR',
            discovery_date  TEXT,
            incident_date   TEXT,
            breach_type     TEXT,
            description     TEXT,
            data_types      TEXT,   -- JSON array
            affected_count  TEXT,
            severity        TEXT DEFAULT 'medium',
            root_cause      TEXT,
            containment     TEXT,
            remediation     TEXT,
            notification_required INTEGER DEFAULT 0,
            authority_notified    INTEGER DEFAULT 0,
            authority_notify_date TEXT,
            authority_ref   TEXT,
            subjects_notified     INTEGER DEFAULT 0,
            subjects_notify_date  TEXT,
            notify_deadline TEXT,
            status          TEXT DEFAULT 'open',
            ai_assessment   TEXT,
            lessons_learned TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── DSR / SAR Tracker ────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS dsr_requests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_number      TEXT UNIQUE NOT NULL,
            requester_name  TEXT,
            requester_email TEXT,
            request_type    TEXT,
            regulation      TEXT DEFAULT 'GDPR',
            description     TEXT,
            received_date   TEXT,
            deadline_date   TEXT,
            status          TEXT DEFAULT 'open',
            response_notes  TEXT,
            ai_draft        TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Vendor / Processor Register ──────────────────────────────────────
        CREATE TABLE IF NOT EXISTS vendors (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            type            TEXT DEFAULT 'processor',
            country         TEXT,
            services        TEXT,
            data_types      TEXT,   -- JSON array
            data_subjects   TEXT,
            dpa_status      TEXT DEFAULT 'pending',
            dpa_date        TEXT,
            dpa_expiry      TEXT,
            risk_level      TEXT DEFAULT 'medium',
            ai_assessment   TEXT,
            contact_name    TEXT,
            contact_email   TEXT,
            website         TEXT,
            regulation      TEXT DEFAULT 'GDPR',
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Privacy Notices ──────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS privacy_notices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT NOT NULL,
            regulation      TEXT DEFAULT 'GDPR',
            audience        TEXT,
            version         TEXT DEFAULT '1.0',
            content         TEXT,
            status          TEXT DEFAULT 'draft',
            review_date     TEXT,
            published_date  TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Consent Records ──────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS consent_records (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id      TEXT,
            subject_name    TEXT,
            subject_email   TEXT,
            purpose         TEXT NOT NULL,
            regulation      TEXT DEFAULT 'GDPR',
            legal_basis     TEXT DEFAULT 'Consent',
            consent_date    TEXT,
            expiry_date     TEXT,
            withdrawal_date TEXT,
            status          TEXT DEFAULT 'active',
            evidence        TEXT,
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Controllers & DPO ────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS controllers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            org_name        TEXT NOT NULL,
            registration_number TEXT,
            country         TEXT,
            address         TEXT,
            sector          TEXT,
            controller_name TEXT,
            controller_email TEXT,
            controller_phone TEXT,
            dpo_name        TEXT,
            dpo_email       TEXT,
            dpo_phone       TEXT,
            regulator_name  TEXT,
            regulator_ref   TEXT,
            regulation      TEXT,
            is_primary      INTEGER DEFAULT 0,
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Cross-Border Transfers ───────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS transfers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_number      TEXT UNIQUE NOT NULL,
            ropa_id         INTEGER REFERENCES ropa_entries(id),
            destination     TEXT NOT NULL,
            recipient_name  TEXT,
            transfer_type   TEXT,
            safeguard       TEXT,
            safeguard_detail TEXT,
            regulation      TEXT DEFAULT 'GDPR',
            adequacy_decision INTEGER DEFAULT 0,
            data_types      TEXT,   -- JSON
            frequency       TEXT,
            volume          TEXT,
            status          TEXT DEFAULT 'active',
            review_date     TEXT,
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Retention Schedules ──────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS retention_schedules (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            category        TEXT NOT NULL,
            data_type       TEXT,
            retention_period TEXT,
            legal_basis     TEXT,
            regulation      TEXT DEFAULT 'GDPR',
            trigger_event   TEXT,
            disposal_method TEXT,
            owner           TEXT,
            review_date     TEXT,
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Security Measures ────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS security_measures (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            measure_name    TEXT NOT NULL,
            category        TEXT,
            description     TEXT,
            status          TEXT DEFAULT 'implemented',
            implementation_date TEXT,
            review_date     TEXT,
            owner           TEXT,
            evidence        TEXT,
            regulation      TEXT DEFAULT 'GDPR',
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Audit Log ────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            action          TEXT NOT NULL,
            entity_type     TEXT,
            entity_id       INTEGER,
            entity_name     TEXT,
            user_name       TEXT DEFAULT 'System',
            details         TEXT,
            ip_address      TEXT,
            created_at      TEXT NOT NULL
        );

        -- ── Settings ─────────────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS settings (
            key     TEXT PRIMARY KEY,
            value   TEXT
        );

        -- ── Policy & Document Library ────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS policies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_number      TEXT UNIQUE NOT NULL,
            title           TEXT NOT NULL,
            policy_type     TEXT DEFAULT 'Privacy Policy',
            version         TEXT DEFAULT '1.0',
            status          TEXT DEFAULT 'draft',
            owner           TEXT,
            department      TEXT,
            regulation      TEXT,
            description     TEXT,
            file_path       TEXT,
            file_name       TEXT,
            review_date     TEXT,
            expiry_date     TEXT,
            approved_by     TEXT,
            approved_date   TEXT,
            next_review     TEXT,
            tags            TEXT,
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Training & Awareness Register ────────────────────────────────────
        CREATE TABLE IF NOT EXISTS training_records (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_number      TEXT UNIQUE NOT NULL,
            training_name   TEXT NOT NULL,
            training_type   TEXT DEFAULT 'Online',
            staff_name      TEXT NOT NULL,
            staff_email     TEXT,
            department      TEXT,
            completion_date TEXT,
            expiry_date     TEXT,
            score           INTEGER,
            passed          INTEGER DEFAULT 0,
            certificate_no  TEXT,
            trainer         TEXT,
            regulation      TEXT,
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        -- ── Data Flow Entries ───────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS data_flows (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_number      TEXT UNIQUE NOT NULL,
            flow_name       TEXT NOT NULL,
            source_system   TEXT,
            destination     TEXT,
            data_types      TEXT,
            frequency       TEXT DEFAULT 'Continuous',
            safeguards      TEXT,
            ropa_id         INTEGER REFERENCES ropa_entries(id),
            regulation      TEXT,
            notes           TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );
        """)


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════════════════════════

def log_action(action, entity_type=None, entity_id=None, entity_name=None,
               user="System", details=None):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO audit_log (action,entity_type,entity_id,entity_name,
               user_name,details,created_at) VALUES (?,?,?,?,?,?,?)""",
            (action, entity_type, entity_id, entity_name, user, details, _now())
        )


def list_audit(limit=200):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

def get_setting(key, default=None):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )


def get_all_settings():
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ═══════════════════════════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════════════════════════

def get_stats():
    with get_db() as conn:
        ropa_total   = conn.execute("SELECT COUNT(*) FROM ropa_entries").fetchone()[0]
        dpia_total   = conn.execute("SELECT COUNT(*) FROM dpias").fetchone()[0]
        dpia_draft   = conn.execute("SELECT COUNT(*) FROM dpias WHERE status='draft'").fetchone()[0]
        dpia_approved= conn.execute("SELECT COUNT(*) FROM dpias WHERE status='approved'").fetchone()[0]
        breach_open  = conn.execute("SELECT COUNT(*) FROM breaches WHERE status='open'").fetchone()[0]
        breach_critical = conn.execute("SELECT COUNT(*) FROM breaches WHERE severity='critical'").fetchone()[0]
        dsr_open     = conn.execute("SELECT COUNT(*) FROM dsr_requests WHERE status='open'").fetchone()[0]
        dsr_overdue  = conn.execute(
            "SELECT COUNT(*) FROM dsr_requests WHERE status='open' AND deadline_date < ?", (_now()[:10],)
        ).fetchone()[0]
        vendor_total = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
        high_risk_ropa = conn.execute(
            "SELECT COUNT(*) FROM ropa_entries WHERE risk_score IN ('high','critical')"
        ).fetchone()[0]
        dpia_required = conn.execute(
            "SELECT COUNT(*) FROM ropa_entries WHERE dpia_required=1"
        ).fetchone()[0]
        special_cat  = conn.execute(
            "SELECT COUNT(*) FROM ropa_entries WHERE special_categories IS NOT NULL AND special_categories != '[]'"
        ).fetchone()[0]
        intl_transfers = conn.execute(
            "SELECT COUNT(*) FROM ropa_entries WHERE intl_transfers='Yes'"
        ).fetchone()[0]
        consent_active = conn.execute(
            "SELECT COUNT(*) FROM consent_records WHERE status='active'"
        ).fetchone()[0]
        notices_total= conn.execute("SELECT COUNT(*) FROM privacy_notices").fetchone()[0]
        # Recent activity
        recent_audit = conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
        # By regulation
        by_reg = conn.execute(
            "SELECT regulation, COUNT(*) c FROM ropa_entries GROUP BY regulation"
        ).fetchall()
        dpia_by_reg = conn.execute(
            "SELECT regulation, COUNT(*) c FROM dpias GROUP BY regulation"
        ).fetchall()
        risk_dist = conn.execute(
            "SELECT risk_score, COUNT(*) c FROM ropa_entries GROUP BY risk_score"
        ).fetchall()
        policy_total = conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
        policy_expiring = conn.execute(
            "SELECT COUNT(*) FROM policies WHERE next_review IS NOT NULL AND next_review <= date('now', '+30 days') AND next_review >= date('now')"
        ).fetchone()[0]
        training_total = conn.execute("SELECT COUNT(*) FROM training_records").fetchone()[0]
        training_expiring = conn.execute(
            "SELECT COUNT(*) FROM training_records WHERE expiry_date IS NOT NULL AND expiry_date <= date('now', '+30 days') AND expiry_date >= date('now')"
        ).fetchone()[0]
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
        "special_cat": special_cat,
        "intl_transfers": intl_transfers,
        "consent_active": consent_active,
        "notices_total": notices_total,
        "policies": policy_total,
        "policies_expiring": policy_expiring,
        "training": training_total,
        "training_expiring": training_expiring,
        "recent_audit": [dict(r) for r in recent_audit],
        "by_regulation": {r["regulation"]: r["c"] for r in by_reg},
        "dpia_by_regulation": {r["regulation"]: r["c"] for r in dpia_by_reg},
        "risk_distribution": {r["risk_score"]: r["c"] for r in risk_dist},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ROPA
# ═══════════════════════════════════════════════════════════════════════════════

def _ropa_row(row):
    if not row:
        return None
    d = dict(row)
    for f in ("data_categories", "special_categories", "processors", "recipients", "security_measures"):
        d[f] = _parse_json(d.get(f), [])
    return d


def create_ropa(data):
    now = _now()
    ref = _gen_ref("ROPA")
    for f in ("data_categories", "special_categories", "processors", "recipients", "security_measures"):
        if f in data and isinstance(data[f], list):
            data[f] = json.dumps(data[f])
    fields = [
        "processing_name", "department", "owner", "regulation", "purpose", "legal_basis",
        "data_categories", "special_categories", "data_subjects", "subject_count",
        "retention_period", "systems", "processors", "recipients", "intl_transfers",
        "transfer_dest", "transfer_safeguard", "security_measures", "dpia_required",
        "dpia_id", "risk_score", "ai_risk_notes", "status", "review_date", "notes"
    ]
    params = {f: data.get(f) for f in fields}
    params.update({"ref_number": ref, "created_at": now, "updated_at": now})
    if not params.get("processing_name"): params["processing_name"] = "Untitled Entry"
    if not params.get("regulation"): params["regulation"] = "GDPR"
    if not params.get("status"): params["status"] = "active"
    if not params.get("risk_score"): params["risk_score"] = "low"
    cols = ", ".join(["ref_number"] + fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in ["ref_number"] + fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO ropa_entries ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "ropa", new_id, data.get("processing_name", ref))
    return new_id


def update_ropa(ropa_id, data):
    now = _now()
    for f in ("data_categories", "special_categories", "processors", "recipients", "security_measures"):
        if f in data and isinstance(data[f], list):
            data[f] = json.dumps(data[f])
    allowed = {
        "processing_name", "department", "owner", "regulation", "purpose", "legal_basis",
        "data_categories", "special_categories", "data_subjects", "subject_count",
        "retention_period", "systems", "processors", "recipients", "intl_transfers",
        "transfer_dest", "transfer_safeguard", "security_measures", "dpia_required",
        "dpia_id", "risk_score", "ai_risk_notes", "status", "review_date", "notes"
    }
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": ropa_id})
    with get_db() as conn:
        conn.execute(f"UPDATE ropa_entries SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "ropa", ropa_id, data.get("processing_name"))


def get_ropa(ropa_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM ropa_entries WHERE id=?", (ropa_id,)).fetchone()
    return _ropa_row(row)


def list_ropa(search=None, regulation=None, status=None, risk=None, limit=500):
    sql = "SELECT * FROM ropa_entries WHERE 1=1"
    params = []
    if search:
        sql += " AND (processing_name LIKE ? OR department LIKE ? OR owner LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    if regulation:
        sql += " AND regulation=?"
        params.append(regulation)
    if status:
        sql += " AND status=?"
        params.append(status)
    if risk:
        sql += " AND risk_score=?"
        params.append(risk)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_ropa_row(r) for r in rows]


def delete_ropa(ropa_id):
    with get_db() as conn:
        conn.execute("DELETE FROM ropa_entries WHERE id=?", (ropa_id,))
    log_action("DELETE", "ropa", ropa_id)


# ═══════════════════════════════════════════════════════════════════════════════
# DPIA
# ═══════════════════════════════════════════════════════════════════════════════

def _dpia_row(row):
    if not row:
        return None
    d = dict(row)
    d["data_categories"] = _parse_json(d.get("data_categories"), [])
    d["special_cats"]    = _parse_json(d.get("special_cats"), [])
    d["risks"]           = _parse_json(d.get("risks"), [])
    return d


def create_dpia(data):
    now = _now()
    ref = _gen_ref("DPIA")
    for f in ("data_categories", "special_cats", "risks"):
        if f in data and isinstance(data[f], list):
            data[f] = json.dumps(data[f])
        elif f not in data:
            data[f] = "[]"
    fields = [
        "title", "status", "regulation", "org_name", "department", "controller_name",
        "dpo_name", "dpo_email", "activity_type", "activity_desc", "purpose", "legal_basis",
        "data_categories", "special_cats", "data_subjects", "subject_count", "retention",
        "systems", "processors", "intl_transfer", "transfer_dest", "transfer_mech",
        "necessity", "proportionality", "risks", "overall_risk", "residual_risk",
        "dpo_consulted", "auth_consulted", "subjects_consulted", "consult_notes",
        "ai_research", "ai_full_dpia"
    ]
    params = {f: data.get(f) for f in fields}
    params.update({"ref_number": ref, "created_at": now, "updated_at": now})
    if not params.get("title"):
        params["title"] = "Untitled DPIA"
    if not params.get("status"):
        params["status"] = "draft"
    if not params.get("regulation"):
        params["regulation"] = "GDPR"
    cols = ", ".join(["ref_number"] + fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in ["ref_number"] + fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO dpias ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "dpia", new_id, data.get("title", ref))
    return new_id


def update_dpia(dpia_id, data):
    now = _now()
    for f in ("data_categories", "special_cats", "risks"):
        if f in data and isinstance(data[f], list):
            data[f] = json.dumps(data[f])
    allowed = {
        "title", "status", "regulation", "org_name", "department", "controller_name",
        "dpo_name", "dpo_email", "activity_type", "activity_desc", "purpose", "legal_basis",
        "data_categories", "special_cats", "data_subjects", "subject_count", "retention",
        "systems", "processors", "intl_transfer", "transfer_dest", "transfer_mech",
        "necessity", "proportionality", "risks", "overall_risk", "residual_risk",
        "dpo_consulted", "auth_consulted", "subjects_consulted", "consult_notes",
        "ai_research", "ai_full_dpia"
    }
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": dpia_id})
    with get_db() as conn:
        conn.execute(f"UPDATE dpias SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "dpia", dpia_id, data.get("title"))


def get_dpia(dpia_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM dpias WHERE id=?", (dpia_id,)).fetchone()
    return _dpia_row(row)


def list_dpias(search=None, regulation=None, status=None, limit=500):
    sql = "SELECT * FROM dpias WHERE 1=1"
    params = []
    if search:
        sql += " AND (title LIKE ? OR org_name LIKE ? OR activity_type LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    if regulation:
        sql += " AND regulation=?"
        params.append(regulation)
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_dpia_row(r) for r in rows]


def delete_dpia(dpia_id):
    with get_db() as conn:
        conn.execute("DELETE FROM dpias WHERE id=?", (dpia_id,))
    log_action("DELETE", "dpia", dpia_id)


# ═══════════════════════════════════════════════════════════════════════════════
# BREACHES
# ═══════════════════════════════════════════════════════════════════════════════

def _breach_row(row):
    if not row:
        return None
    d = dict(row)
    d["data_types"] = _parse_json(d.get("data_types"), [])
    return d


def create_breach(data):
    now = _now()
    ref = _gen_ref("BRE")
    if "data_types" in data and isinstance(data["data_types"], list):
        data["data_types"] = json.dumps(data["data_types"])
    # Auto-compute 72h notify deadline for GDPR
    if data.get("discovery_date") and data.get("regulation") in ("GDPR", "UK GDPR"):
        try:
            disc = datetime.strptime(data["discovery_date"], "%Y-%m-%d")
            data["notify_deadline"] = (disc + timedelta(hours=72)).strftime("%Y-%m-%d")
        except Exception:
            pass
    fields = [
        "title", "regulation", "discovery_date", "incident_date", "breach_type",
        "description", "data_types", "affected_count", "severity", "root_cause",
        "containment", "remediation", "notification_required", "authority_notified",
        "authority_notify_date", "authority_ref", "subjects_notified",
        "subjects_notify_date", "notify_deadline", "status", "ai_assessment", "lessons_learned"
    ]
    params = {f: data.get(f) for f in fields}
    params.update({"ref_number": ref, "created_at": now, "updated_at": now})
    if not params.get("title"): params["title"] = "Untitled Incident"
    if not params.get("regulation"): params["regulation"] = "GDPR"
    if not params.get("severity"): params["severity"] = "medium"
    if not params.get("status"): params["status"] = "open"
    cols = ", ".join(["ref_number"] + fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in ["ref_number"] + fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO breaches ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "breach", new_id, data.get("title", ref))
    return new_id


def update_breach(breach_id, data):
    now = _now()
    if "data_types" in data and isinstance(data["data_types"], list):
        data["data_types"] = json.dumps(data["data_types"])
    allowed = {
        "title", "regulation", "discovery_date", "incident_date", "breach_type",
        "description", "data_types", "affected_count", "severity", "root_cause",
        "containment", "remediation", "notification_required", "authority_notified",
        "authority_notify_date", "authority_ref", "subjects_notified",
        "subjects_notify_date", "notify_deadline", "status", "ai_assessment", "lessons_learned"
    }
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": breach_id})
    with get_db() as conn:
        conn.execute(f"UPDATE breaches SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "breach", breach_id, data.get("title"))


def get_breach(breach_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM breaches WHERE id=?", (breach_id,)).fetchone()
    return _breach_row(row)


def list_breaches(search=None, status=None, severity=None, limit=500):
    sql = "SELECT * FROM breaches WHERE 1=1"
    params = []
    if search:
        sql += " AND (title LIKE ? OR description LIKE ?)"
        like = f"%{search}%"
        params += [like, like]
    if status:
        sql += " AND status=?"
        params.append(status)
    if severity:
        sql += " AND severity=?"
        params.append(severity)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_breach_row(r) for r in rows]


def delete_breach(breach_id):
    with get_db() as conn:
        conn.execute("DELETE FROM breaches WHERE id=?", (breach_id,))
    log_action("DELETE", "breach", breach_id)


# ═══════════════════════════════════════════════════════════════════════════════
# DSR
# ═══════════════════════════════════════════════════════════════════════════════

def create_dsr(data):
    now = _now()
    ref = _gen_ref("DSR")
    # Auto-compute deadline (30 days by default, 1 month for GDPR)
    if data.get("received_date") and not data.get("deadline_date"):
        try:
            rec = datetime.strptime(data["received_date"], "%Y-%m-%d")
            data["deadline_date"] = (rec + timedelta(days=30)).strftime("%Y-%m-%d")
        except Exception:
            pass
    fields = [
        "requester_name", "requester_email", "request_type", "regulation",
        "description", "received_date", "deadline_date", "status",
        "response_notes", "ai_draft"
    ]
    params = {f: data.get(f) for f in fields}
    params.update({"ref_number": ref, "created_at": now, "updated_at": now})
    if not params.get("regulation"): params["regulation"] = "GDPR"
    if not params.get("status"): params["status"] = "open"
    cols = ", ".join(["ref_number"] + fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in ["ref_number"] + fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO dsr_requests ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "dsr", new_id, f"{data.get('request_type','DSR')} from {data.get('requester_name','Unknown')}")
    return new_id


def update_dsr(dsr_id, data):
    now = _now()
    allowed = {
        "requester_name", "requester_email", "request_type", "regulation",
        "description", "received_date", "deadline_date", "status",
        "response_notes", "ai_draft"
    }
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": dsr_id})
    with get_db() as conn:
        conn.execute(f"UPDATE dsr_requests SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "dsr", dsr_id)


def list_dsrs(search=None, status=None, request_type=None, limit=500):
    sql = "SELECT * FROM dsr_requests WHERE 1=1"
    params = []
    if search:
        sql += " AND (requester_name LIKE ? OR requester_email LIKE ? OR description LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    if status:
        sql += " AND status=?"
        params.append(status)
    if request_type:
        sql += " AND request_type=?"
        params.append(request_type)
    sql += " ORDER BY deadline_date ASC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def delete_dsr(dsr_id):
    with get_db() as conn:
        conn.execute("DELETE FROM dsr_requests WHERE id=?", (dsr_id,))
    log_action("DELETE", "dsr", dsr_id)


# ═══════════════════════════════════════════════════════════════════════════════
# VENDORS
# ═══════════════════════════════════════════════════════════════════════════════

def _vendor_row(row):
    if not row:
        return None
    d = dict(row)
    d["data_types"] = _parse_json(d.get("data_types"), [])
    return d


def create_vendor(data):
    now = _now()
    if "data_types" in data and isinstance(data["data_types"], list):
        data["data_types"] = json.dumps(data["data_types"])
    fields = [
        "name", "type", "country", "services", "data_types", "data_subjects",
        "dpa_status", "dpa_date", "dpa_expiry", "risk_level", "ai_assessment",
        "contact_name", "contact_email", "website", "regulation", "notes"
    ]
    params = {f: data.get(f) for f in fields}
    params.update({"created_at": now, "updated_at": now})
    if not params.get("name"): params["name"] = "Unnamed Vendor"
    if not params.get("type"): params["type"] = "processor"
    if not params.get("risk_level"): params["risk_level"] = "medium"
    if not params.get("dpa_status"): params["dpa_status"] = "pending"
    if not params.get("regulation"): params["regulation"] = "GDPR"
    cols = ", ".join(fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO vendors ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "vendor", new_id, data.get("name"))
    return new_id


def update_vendor(vendor_id, data):
    now = _now()
    if "data_types" in data and isinstance(data["data_types"], list):
        data["data_types"] = json.dumps(data["data_types"])
    allowed = {
        "name", "type", "country", "services", "data_types", "data_subjects",
        "dpa_status", "dpa_date", "dpa_expiry", "risk_level", "ai_assessment",
        "contact_name", "contact_email", "website", "regulation", "notes"
    }
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": vendor_id})
    with get_db() as conn:
        conn.execute(f"UPDATE vendors SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "vendor", vendor_id, data.get("name"))


def list_vendors(search=None, risk=None, dpa_status=None, limit=500):
    sql = "SELECT * FROM vendors WHERE 1=1"
    params = []
    if search:
        sql += " AND (name LIKE ? OR services LIKE ? OR country LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    if risk:
        sql += " AND risk_level=?"
        params.append(risk)
    if dpa_status:
        sql += " AND dpa_status=?"
        params.append(dpa_status)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_vendor_row(r) for r in rows]


def get_vendor(vendor_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM vendors WHERE id=?", (vendor_id,)).fetchone()
    return _vendor_row(row)


def delete_vendor(vendor_id):
    with get_db() as conn:
        conn.execute("DELETE FROM vendors WHERE id=?", (vendor_id,))
    log_action("DELETE", "vendor", vendor_id)


# ═══════════════════════════════════════════════════════════════════════════════
# PRIVACY NOTICES
# ═══════════════════════════════════════════════════════════════════════════════

def create_notice(data):
    now = _now()
    fields = ["title", "regulation", "audience", "version", "content", "status", "review_date", "published_date"]
    params = {f: data.get(f) for f in fields}
    params.update({"created_at": now, "updated_at": now})
    if not params.get("title"): params["title"] = "Untitled Notice"
    if not params.get("regulation"): params["regulation"] = "GDPR"
    if not params.get("status"): params["status"] = "draft"
    if not params.get("version"): params["version"] = "1.0"
    cols = ", ".join(fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO privacy_notices ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "notice", new_id, data.get("title"))
    return new_id


def update_notice(notice_id, data):
    now = _now()
    allowed = {"title", "regulation", "audience", "version", "content", "status", "review_date", "published_date"}
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": notice_id})
    with get_db() as conn:
        conn.execute(f"UPDATE privacy_notices SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "notice", notice_id, data.get("title"))


def list_notices(limit=200):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM privacy_notices ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_notice(notice_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM privacy_notices WHERE id=?", (notice_id,)).fetchone()
    return dict(row) if row else None


def delete_notice(notice_id):
    with get_db() as conn:
        conn.execute("DELETE FROM privacy_notices WHERE id=?", (notice_id,))
    log_action("DELETE", "notice", notice_id)


# ═══════════════════════════════════════════════════════════════════════════════
# CONSENT RECORDS
# ═══════════════════════════════════════════════════════════════════════════════

def create_consent(data):
    now = _now()
    fields = [
        "subject_id", "subject_name", "subject_email", "purpose", "regulation",
        "legal_basis", "consent_date", "expiry_date", "withdrawal_date", "status", "evidence", "notes"
    ]
    params = {f: data.get(f) for f in fields}
    params.update({"created_at": now, "updated_at": now})
    if not params.get("regulation"): params["regulation"] = "GDPR"
    if not params.get("status"): params["status"] = "active"
    if not params.get("legal_basis"): params["legal_basis"] = "Consent"
    cols = ", ".join(fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO consent_records ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "consent", new_id, data.get("purpose"))
    return new_id


def update_consent(consent_id, data):
    now = _now()
    allowed = {
        "subject_id", "subject_name", "subject_email", "purpose", "regulation",
        "legal_basis", "consent_date", "expiry_date", "withdrawal_date", "status", "evidence", "notes"
    }
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": consent_id})
    with get_db() as conn:
        conn.execute(f"UPDATE consent_records SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "consent", consent_id)


def list_consent(search=None, status=None, limit=500):
    sql = "SELECT * FROM consent_records WHERE 1=1"
    params = []
    if search:
        sql += " AND (subject_name LIKE ? OR subject_email LIKE ? OR purpose LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def delete_consent(consent_id):
    with get_db() as conn:
        conn.execute("DELETE FROM consent_records WHERE id=?", (consent_id,))
    log_action("DELETE", "consent", consent_id)


# ═══════════════════════════════════════════════════════════════════════════════
# CONTROLLERS
# ═══════════════════════════════════════════════════════════════════════════════

def create_controller(data):
    now = _now()
    fields = [
        "org_name", "registration_number", "country", "address", "sector",
        "controller_name", "controller_email", "controller_phone",
        "dpo_name", "dpo_email", "dpo_phone",
        "regulator_name", "regulator_ref", "regulation", "is_primary", "notes"
    ]
    params = {f: data.get(f) for f in fields}
    params.update({"created_at": now, "updated_at": now})
    if not params.get("org_name"): params["org_name"] = "Unnamed Organisation"
    cols = ", ".join(fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO controllers ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "controller", new_id, data.get("org_name"))
    return new_id


def update_controller(ctrl_id, data):
    now = _now()
    allowed = {
        "org_name", "registration_number", "country", "address", "sector",
        "controller_name", "controller_email", "controller_phone",
        "dpo_name", "dpo_email", "dpo_phone",
        "regulator_name", "regulator_ref", "regulation", "is_primary", "notes"
    }
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": ctrl_id})
    with get_db() as conn:
        conn.execute(f"UPDATE controllers SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "controller", ctrl_id, data.get("org_name"))


def list_controllers(limit=200):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM controllers ORDER BY is_primary DESC, org_name ASC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_controller(ctrl_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM controllers WHERE id=?", (ctrl_id,)).fetchone()
    return dict(row) if row else None


def delete_controller(ctrl_id):
    with get_db() as conn:
        conn.execute("DELETE FROM controllers WHERE id=?", (ctrl_id,))
    log_action("DELETE", "controller", ctrl_id)


# ═══════════════════════════════════════════════════════════════════════════════
# TRANSFERS
# ═══════════════════════════════════════════════════════════════════════════════

def create_transfer(data):
    now = _now()
    ref = _gen_ref("TRF")
    if "data_types" in data and isinstance(data["data_types"], list):
        data["data_types"] = json.dumps(data["data_types"])
    fields = [
        "ropa_id", "destination", "recipient_name", "transfer_type", "safeguard",
        "safeguard_detail", "regulation", "adequacy_decision", "data_types",
        "frequency", "volume", "status", "review_date", "notes"
    ]
    params = {f: data.get(f) for f in fields}
    params.update({"ref_number": ref, "created_at": now, "updated_at": now})
    if not params.get("regulation"): params["regulation"] = "GDPR"
    if not params.get("status"): params["status"] = "active"
    cols = ", ".join(["ref_number"] + fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in ["ref_number"] + fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO transfers ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "transfer", new_id, data.get("destination"))
    return new_id


def update_transfer(transfer_id, data):
    now = _now()
    if "data_types" in data and isinstance(data["data_types"], list):
        data["data_types"] = json.dumps(data["data_types"])
    allowed = {
        "ropa_id", "destination", "recipient_name", "transfer_type", "safeguard",
        "safeguard_detail", "regulation", "adequacy_decision", "data_types",
        "frequency", "volume", "status", "review_date", "notes"
    }
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": transfer_id})
    with get_db() as conn:
        conn.execute(f"UPDATE transfers SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "transfer", transfer_id, data.get("destination"))


def list_transfers(limit=500):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM transfers ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete_transfer(transfer_id):
    with get_db() as conn:
        conn.execute("DELETE FROM transfers WHERE id=?", (transfer_id,))
    log_action("DELETE", "transfer", transfer_id)


# ═══════════════════════════════════════════════════════════════════════════════
# RETENTION SCHEDULES
# ═══════════════════════════════════════════════════════════════════════════════

def create_retention(data):
    now = _now()
    fields = [
        "category", "data_type", "retention_period", "legal_basis", "regulation",
        "trigger_event", "disposal_method", "owner", "review_date", "notes"
    ]
    params = {f: data.get(f) for f in fields}
    params.update({"created_at": now, "updated_at": now})
    if not params.get("regulation"): params["regulation"] = "GDPR"
    cols = ", ".join(fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO retention_schedules ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "retention", new_id, data.get("category"))
    return new_id


def update_retention(ret_id, data):
    now = _now()
    allowed = {
        "category", "data_type", "retention_period", "legal_basis", "regulation",
        "trigger_event", "disposal_method", "owner", "review_date", "notes"
    }
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": ret_id})
    with get_db() as conn:
        conn.execute(f"UPDATE retention_schedules SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "retention", ret_id, data.get("category"))


def list_retention(limit=500):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM retention_schedules ORDER BY category ASC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete_retention(ret_id):
    with get_db() as conn:
        conn.execute("DELETE FROM retention_schedules WHERE id=?", (ret_id,))
    log_action("DELETE", "retention", ret_id)


# ═══════════════════════════════════════════════════════════════════════════════
# SECURITY MEASURES
# ═══════════════════════════════════════════════════════════════════════════════

def create_security(data):
    now = _now()
    fields = [
        "measure_name", "category", "description", "status",
        "implementation_date", "review_date", "owner", "evidence", "regulation", "notes"
    ]
    params = {f: data.get(f) for f in fields}
    params.update({"created_at": now, "updated_at": now})
    if not params.get("status"): params["status"] = "implemented"
    if not params.get("regulation"): params["regulation"] = "GDPR"
    cols = ", ".join(fields + ["created_at", "updated_at"])
    vals = ", ".join([":" + k for k in fields + ["created_at", "updated_at"]])
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO security_measures ({cols}) VALUES ({vals})", params)
        new_id = cur.lastrowid
    log_action("CREATE", "security", new_id, data.get("measure_name"))
    return new_id


def update_security(sec_id, data):
    now = _now()
    allowed = {
        "measure_name", "category", "description", "status",
        "implementation_date", "review_date", "owner", "evidence", "regulation", "notes"
    }
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if not sets:
        return
    params.update({"updated_at": now, "id": sec_id})
    with get_db() as conn:
        conn.execute(f"UPDATE security_measures SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE", "security", sec_id, data.get("measure_name"))


def list_security(limit=500):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM security_measures ORDER BY category ASC, measure_name ASC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete_security(sec_id):
    with get_db() as conn:
        conn.execute("DELETE FROM security_measures WHERE id=?", (sec_id,))
    log_action("DELETE", "security", sec_id)


# ═══════════════════════════════════════════════════════════════════════════════
# USERS
# ═══════════════════════════════════════════════════════════════════════════════

ROLES = ["admin", "dpo", "auditor", "analyst", "viewer"]

def _initials(name):
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper() if name else "??"


def create_user(data):
    now = _now()
    password = data.get("password", "changeme123")
    full_name = data.get("full_name", data.get("username", "User"))
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO users (username, email, full_name, password_hash, role,
               is_active, avatar_initials, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                data["username"], data["email"], full_name,
                _hash_password(password),
                data.get("role", "viewer"),
                1,
                _initials(full_name),
                now, now
            )
        )
        new_id = cur.lastrowid
    log_action("CREATE_USER", "user", new_id, data["username"])
    return new_id


def authenticate_user(username, password):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE (username=? OR email=?) AND is_active=1",
            (username, username)
        ).fetchone()
    if not row:
        return None
    user = dict(row)
    if not _verify_password(password, user["password_hash"]):
        return None
    # Update last login
    with get_db() as conn:
        conn.execute("UPDATE users SET last_login=? WHERE id=?", (_now(), user["id"]))
    log_action("LOGIN", "user", user["id"], user["username"])
    return user


def get_user(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(username):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? OR email=?", (username, username)
        ).fetchone()
    return dict(row) if row else None


def list_users():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, email, full_name, role, is_active, last_login, avatar_initials, created_at FROM users ORDER BY role, full_name"
        ).fetchall()
    return [dict(r) for r in rows]


def update_user(user_id, data):
    now = _now()
    allowed = {"email", "full_name", "role", "is_active"}
    sets, params = [], {}
    for k, v in data.items():
        if k in allowed:
            sets.append(f"{k}=:{k}")
            params[k] = v
    if "password" in data and data["password"]:
        sets.append("password_hash=:password_hash")
        params["password_hash"] = _hash_password(data["password"])
    if "full_name" in data:
        sets.append("avatar_initials=:avatar_initials")
        params["avatar_initials"] = _initials(data["full_name"])
    if not sets:
        return
    params.update({"updated_at": now, "id": user_id})
    with get_db() as conn:
        conn.execute(f"UPDATE users SET {','.join(sets)},updated_at=:updated_at WHERE id=:id", params)
    log_action("UPDATE_USER", "user", user_id)


def delete_user(user_id):
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    log_action("DELETE_USER", "user", user_id)


def ensure_default_admin():
    """Create default admin user if no users exist."""
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        create_user({
            "username": "admin",
            "email": "admin@sentinel.local",
            "full_name": "Administrator",
            "password": "sentinel2024",
            "role": "admin"
        })
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# POLICIES
# ═══════════════════════════════════════════════════════════════════════════════

def _next_policy_ref():
    with get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0] + 1
        return f"POL-{datetime.utcnow().strftime('%Y%m')}-{n:04d}"

def create_policy(data):
    data = dict(data)
    now = datetime.utcnow().isoformat()
    data.setdefault("ref_number", _next_policy_ref())
    data["created_at"] = now
    data["updated_at"] = now
    allowed = {
        "ref_number","title","policy_type","version","status","owner","department",
        "regulation","description","file_path","file_name","review_date","expiry_date",
        "approved_by","approved_date","next_review","tags","notes","created_at","updated_at"
    }
    params = {k: v for k, v in data.items() if k in allowed}
    cols = ",".join(params.keys())
    vals = ",".join(f":{k}" for k in params.keys())
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO policies ({cols}) VALUES ({vals})", params)
        return cur.lastrowid

def update_policy(policy_id, data):
    data = dict(data)
    data["updated_at"] = datetime.utcnow().isoformat()
    allowed = {
        "title","policy_type","version","status","owner","department","regulation",
        "description","file_path","file_name","review_date","expiry_date",
        "approved_by","approved_date","next_review","tags","notes","updated_at"
    }
    params = {k: v for k, v in data.items() if k in allowed}
    if not params:
        return
    params["id"] = policy_id
    sets = ",".join(f"{k}=:{k}" for k in params if k != "id")
    with get_db() as conn:
        conn.execute(f"UPDATE policies SET {sets} WHERE id=:id", params)

def get_policy(policy_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM policies WHERE id=?", (policy_id,)).fetchone()
        return dict(row) if row else None

def list_policies(search=None, status=None, policy_type=None, limit=500):
    sql = "SELECT * FROM policies WHERE 1=1"
    params = []
    if search:
        sql += " AND (title LIKE ? OR owner LIKE ? OR department LIKE ?)"
        params.extend([f"%{search}%"]*3)
    if status:
        sql += " AND status=?"
        params.append(status)
    if policy_type:
        sql += " AND policy_type=?"
        params.append(policy_type)
    sql += " ORDER BY next_review ASC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

def delete_policy(policy_id):
    with get_db() as conn:
        conn.execute("DELETE FROM policies WHERE id=?", (policy_id,))


# ═══════════════════════════════════════════════════════════════════════════════
# TRAINING RECORDS
# ═══════════════════════════════════════════════════════════════════════════════

def _next_training_ref():
    with get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM training_records").fetchone()[0] + 1
        return f"TRN-{datetime.utcnow().strftime('%Y%m')}-{n:04d}"

def create_training(data):
    data = dict(data)
    now = datetime.utcnow().isoformat()
    data.setdefault("ref_number", _next_training_ref())
    data["created_at"] = now
    data["updated_at"] = now
    allowed = {
        "ref_number","training_name","training_type","staff_name","staff_email",
        "department","completion_date","expiry_date","score","passed","certificate_no",
        "trainer","regulation","notes","created_at","updated_at"
    }
    params = {k: v for k, v in data.items() if k in allowed}
    cols = ",".join(params.keys())
    vals = ",".join(f":{k}" for k in params.keys())
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO training_records ({cols}) VALUES ({vals})", params)
        return cur.lastrowid

def update_training(training_id, data):
    data = dict(data)
    data["updated_at"] = datetime.utcnow().isoformat()
    allowed = {
        "training_name","training_type","staff_name","staff_email","department",
        "completion_date","expiry_date","score","passed","certificate_no",
        "trainer","regulation","notes","updated_at"
    }
    params = {k: v for k, v in data.items() if k in allowed}
    if not params:
        return
    params["id"] = training_id
    sets = ",".join(f"{k}=:{k}" for k in params if k != "id")
    with get_db() as conn:
        conn.execute(f"UPDATE training_records SET {sets} WHERE id=:id", params)

def get_training(training_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM training_records WHERE id=?", (training_id,)).fetchone()
        return dict(row) if row else None

def list_training(search=None, department=None, passed=None, limit=500):
    sql = "SELECT * FROM training_records WHERE 1=1"
    params = []
    if search:
        sql += " AND (staff_name LIKE ? OR training_name LIKE ? OR department LIKE ?)"
        params.extend([f"%{search}%"]*3)
    if department:
        sql += " AND department=?"
        params.append(department)
    if passed is not None:
        sql += " AND passed=?"
        params.append(int(passed))
    sql += " ORDER BY expiry_date ASC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

def delete_training(training_id):
    with get_db() as conn:
        conn.execute("DELETE FROM training_records WHERE id=?", (training_id,))


# ═══════════════════════════════════════════════════════════════════════════════
# DATA FLOWS
# ═══════════════════════════════════════════════════════════════════════════════

def _next_flow_ref():
    with get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM data_flows").fetchone()[0] + 1
        return f"FLOW-{datetime.utcnow().strftime('%Y%m')}-{n:04d}"

def create_dataflow(data):
    data = dict(data)
    now = datetime.utcnow().isoformat()
    data.setdefault("ref_number", _next_flow_ref())
    data["created_at"] = now
    data["updated_at"] = now
    allowed = {
        "ref_number","flow_name","source_system","destination","data_types",
        "frequency","safeguards","ropa_id","regulation","notes","created_at","updated_at"
    }
    params = {k: v for k, v in data.items() if k in allowed}
    cols = ",".join(params.keys())
    vals = ",".join(f":{k}" for k in params.keys())
    with get_db() as conn:
        cur = conn.execute(f"INSERT INTO data_flows ({cols}) VALUES ({vals})", params)
        return cur.lastrowid

def list_dataflows(limit=500):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM data_flows ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

def update_dataflow(flow_id, data):
    data = dict(data)
    data["updated_at"] = datetime.utcnow().isoformat()
    allowed = {
        "flow_name","source_system","destination","data_types","frequency",
        "safeguards","ropa_id","regulation","notes","updated_at"
    }
    params = {k: v for k, v in data.items() if k in allowed}
    if not params:
        return
    params["id"] = flow_id
    sets = ",".join(f"{k}=:{k}" for k in params if k != "id")
    with get_db() as conn:
        conn.execute(f"UPDATE data_flows SET {sets} WHERE id=:id", params)

def delete_dataflow(flow_id):
    with get_db() as conn:
        conn.execute("DELETE FROM data_flows WHERE id=?", (flow_id,))


# ═══════════════════════════════════════════════════════════════════════════════
# COMPLIANCE CALENDAR (computed from all modules)
# ═══════════════════════════════════════════════════════════════════════════════

def get_calendar_events(days_ahead=90):
    """Return upcoming compliance events from all modules."""
    events = []
    with get_db() as conn:
        # DPIA reviews
        rows = conn.execute(
            "SELECT id, ref_number, title, updated_at, status FROM dpias WHERE status NOT IN ('approved') ORDER BY updated_at"
        ).fetchall()
        for r in rows:
            events.append({
                "id": f"dpia-{r['id']}", "module": "DPIA", "title": r["title"] or r["ref_number"],
                "event_type": "DPIA Review Due", "date": r["updated_at"][:10] if r["updated_at"] else None,
                "status": r["status"], "color": "purple", "link_id": r["id"], "urgent": r["status"] == "in_review"
            })

        # DSR deadlines (30-day clock)
        rows = conn.execute(
            "SELECT id, ref_number, request_type, requester_name, received_date, status FROM dsr_requests WHERE status NOT IN ('closed','completed') ORDER BY received_date"
        ).fetchall()
        for r in rows:
            if r["received_date"]:
                try:
                    rcvd = datetime.strptime(r["received_date"][:10], "%Y-%m-%d")
                    deadline = rcvd + timedelta(days=30)
                    days_left = (deadline - datetime.utcnow()).days
                    events.append({
                        "id": f"dsr-{r['id']}", "module": "DSR", "title": f"{r['request_type']} — {r['requester_name'] or 'Unknown'}",
                        "event_type": "DSR Deadline", "date": deadline.strftime("%Y-%m-%d"),
                        "status": r["status"], "color": "red" if days_left < 7 else "amber", "link_id": r["id"],
                        "urgent": days_left < 7, "days_remaining": days_left
                    })
                except Exception:
                    pass

        # Breach notification (72h window for unnotified)
        rows = conn.execute(
            "SELECT id, ref_number, title, discovery_date, authority_notified FROM breaches WHERE authority_notified=0 OR authority_notified IS NULL ORDER BY discovery_date"
        ).fetchall()
        for r in rows:
            if r["discovery_date"]:
                try:
                    disc = datetime.strptime(r["discovery_date"][:10], "%Y-%m-%d")
                    deadline = disc + timedelta(hours=72)
                    hours_left = int((deadline - datetime.utcnow()).total_seconds() / 3600)
                    events.append({
                        "id": f"breach-{r['id']}", "module": "Breach", "title": r["title"] or r["ref_number"],
                        "event_type": "72h Notification Window", "date": deadline.strftime("%Y-%m-%d"),
                        "status": "urgent" if hours_left < 24 else "open", "color": "red", "link_id": r["id"],
                        "urgent": True, "hours_remaining": max(0, hours_left)
                    })
                except Exception:
                    pass

        # RoPA review dates
        rows = conn.execute(
            "SELECT id, ref_number, processing_name, review_date FROM ropa_entries WHERE review_date IS NOT NULL AND review_date != '' ORDER BY review_date"
        ).fetchall()
        for r in rows:
            events.append({
                "id": f"ropa-{r['id']}", "module": "RoPA", "title": r["processing_name"] or r["ref_number"],
                "event_type": "RoPA Annual Review", "date": r["review_date"],
                "status": "upcoming", "color": "blue", "link_id": r["id"], "urgent": False
            })

        # Policy renewals
        rows = conn.execute(
            "SELECT id, ref_number, title, next_review FROM policies WHERE next_review IS NOT NULL ORDER BY next_review"
        ).fetchall()
        for r in rows:
            events.append({
                "id": f"policy-{r['id']}", "module": "Policy", "title": r["title"] or r["ref_number"],
                "event_type": "Policy Review Due", "date": r["next_review"],
                "status": "upcoming", "color": "green", "link_id": r["id"], "urgent": False
            })

        # Vendor DPA renewals
        rows = conn.execute(
            "SELECT id, name, dpa_expiry FROM vendors WHERE dpa_expiry IS NOT NULL AND dpa_expiry != '' ORDER BY dpa_expiry"
        ).fetchall()
        for r in rows:
            events.append({
                "id": f"vendor-{r['id']}", "module": "Vendor", "title": r["name"],
                "event_type": "DPA Renewal", "date": r["dpa_expiry"],
                "status": "upcoming", "color": "orange", "link_id": r["id"], "urgent": False
            })

        # Training expiries
        rows = conn.execute(
            "SELECT id, ref_number, training_name, staff_name, expiry_date FROM training_records WHERE expiry_date IS NOT NULL ORDER BY expiry_date"
        ).fetchall()
        for r in rows:
            events.append({
                "id": f"training-{r['id']}", "module": "Training", "title": f"{r['training_name']} — {r['staff_name']}",
                "event_type": "Training Renewal", "date": r["expiry_date"],
                "status": "upcoming", "color": "teal", "link_id": r["id"], "urgent": False
            })

    # Sort by date, put None dates last
    events.sort(key=lambda e: (e.get("date") is None, e.get("date") or "9999"))
    return events


# ═══════════════════════════════════════════════════════════════════════════════
# COMPLIANCE SCORECARD
# ═══════════════════════════════════════════════════════════════════════════════

def get_compliance_score():
    """Compute an overall compliance health score (0-100) across all modules."""
    scores = {}
    with get_db() as conn:
        # RoPA completeness: entries with purpose + legal_basis + data_categories filled
        ropa_total = conn.execute("SELECT COUNT(*) FROM ropa_entries").fetchone()[0]
        ropa_complete = conn.execute(
            "SELECT COUNT(*) FROM ropa_entries WHERE purpose IS NOT NULL AND legal_basis IS NOT NULL AND data_categories IS NOT NULL AND purpose!='' AND legal_basis!='' AND data_categories!=''"
        ).fetchone()[0]
        scores["ropa_completeness"] = {"score": round(ropa_complete/ropa_total*100) if ropa_total else 0, "label": "RoPA Completeness", "total": ropa_total, "done": ropa_complete}

        # DPIA coverage: high-risk RoPAs that have a DPIA
        hr_ropa = conn.execute("SELECT COUNT(*) FROM ropa_entries WHERE risk_score IN ('high','critical') OR dpia_required=1").fetchone()[0]
        hr_with_dpia = conn.execute("SELECT COUNT(*) FROM ropa_entries WHERE (risk_score IN ('high','critical') OR dpia_required=1) AND dpia_id IS NOT NULL").fetchone()[0]
        scores["dpia_coverage"] = {"score": round(hr_with_dpia/hr_ropa*100) if hr_ropa else 100, "label": "DPIA Coverage (High-Risk RoPAs)", "total": hr_ropa, "done": hr_with_dpia}

        # Breach response: breaches with regulator notification or marked resolved
        breach_total = conn.execute("SELECT COUNT(*) FROM breaches").fetchone()[0]
        breach_resolved = conn.execute("SELECT COUNT(*) FROM breaches WHERE status IN ('resolved','closed','contained')").fetchone()[0]
        scores["breach_response"] = {"score": round(breach_resolved/breach_total*100) if breach_total else 100, "label": "Breach Resolution Rate", "total": breach_total, "done": breach_resolved}

        # DSR closure rate
        dsr_total = conn.execute("SELECT COUNT(*) FROM dsr_requests").fetchone()[0]
        dsr_closed = conn.execute("SELECT COUNT(*) FROM dsr_requests WHERE status IN ('closed','completed')").fetchone()[0]
        scores["dsr_closure"] = {"score": round(dsr_closed/dsr_total*100) if dsr_total else 100, "label": "DSR Closure Rate", "total": dsr_total, "done": dsr_closed}

        # Vendor DPA status: vendors with active DPA
        vendor_total = conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
        vendor_dpa = conn.execute("SELECT COUNT(*) FROM vendors WHERE dpa_status IN ('Active','Signed','Executed','Compliant')").fetchone()[0]
        scores["vendor_compliance"] = {"score": round(vendor_dpa/vendor_total*100) if vendor_total else 100, "label": "Vendor DPA Coverage", "total": vendor_total, "done": vendor_dpa}

        # Policy freshness: policies with next_review in future
        policy_total = conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
        policy_current = conn.execute("SELECT COUNT(*) FROM policies WHERE status='approved' AND (next_review IS NULL OR next_review >= date('now'))").fetchone()[0]
        scores["policy_health"] = {"score": round(policy_current/policy_total*100) if policy_total else 0, "label": "Policy Freshness", "total": policy_total, "done": policy_current}

        # Training: staff with current (non-expired) training
        training_total = conn.execute("SELECT COUNT(DISTINCT staff_email) FROM training_records WHERE staff_email IS NOT NULL AND staff_email != ''").fetchone()[0]
        training_current = conn.execute("SELECT COUNT(DISTINCT staff_email) FROM training_records WHERE passed=1 AND (expiry_date IS NULL OR expiry_date >= date('now'))").fetchone()[0]
        scores["training_coverage"] = {"score": round(training_current/training_total*100) if training_total else 0, "label": "Staff Training Coverage", "total": training_total, "done": training_current}

    # Overall weighted average
    weights = {"ropa_completeness": 20, "dpia_coverage": 20, "breach_response": 15, "dsr_closure": 15, "vendor_compliance": 10, "policy_health": 10, "training_coverage": 10}
    weighted_sum = sum(scores.get(k, {}).get("score", 0) * w for k, w in weights.items())
    total_weight = sum(weights.values())
    overall = round(weighted_sum / total_weight) if total_weight else 0

    return {"overall": overall, "breakdown": scores, "grade": "A" if overall >= 90 else "B" if overall >= 75 else "C" if overall >= 60 else "D" if overall >= 40 else "F"}
