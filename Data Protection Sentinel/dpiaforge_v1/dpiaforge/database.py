"""
DPIAforge — SQLite database layer (no ORM needed).
"""
import sqlite3
import json
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.getenv("DATABASE_PATH", "dpiaforge.db")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
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
        """)


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


def row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    d["data_categories"] = _parse_json(d.get("data_categories"), [])
    d["special_cats"]    = _parse_json(d.get("special_cats"), [])
    d["risks"]           = _parse_json(d.get("risks"), [])
    return d


def generate_ref() -> str:
    import random, string
    ts = datetime.utcnow().strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"DPIA-{ts}-{suffix}"


def create_dpia(data: dict) -> int:
    now = _now()
    ref = generate_ref()
    for field in ("data_categories", "special_cats", "risks"):
        if field in data and isinstance(data[field], list):
            data[field] = json.dumps(data[field])
        elif field not in data:
            data[field] = "[]"
    sql = """INSERT INTO dpias (
        ref_number,title,status,regulation,
        org_name,department,controller_name,dpo_name,dpo_email,
        activity_type,activity_desc,purpose,legal_basis,
        data_categories,special_cats,data_subjects,subject_count,retention,
        systems,processors,intl_transfer,transfer_dest,transfer_mech,
        necessity,proportionality,risks,overall_risk,residual_risk,
        dpo_consulted,auth_consulted,subjects_consulted,consult_notes,
        ai_research,ai_full_dpia,created_at,updated_at
    ) VALUES (
        :ref_number,:title,:status,:regulation,
        :org_name,:department,:controller_name,:dpo_name,:dpo_email,
        :activity_type,:activity_desc,:purpose,:legal_basis,
        :data_categories,:special_cats,:data_subjects,:subject_count,:retention,
        :systems,:processors,:intl_transfer,:transfer_dest,:transfer_mech,
        :necessity,:proportionality,:risks,:overall_risk,:residual_risk,
        :dpo_consulted,:auth_consulted,:subjects_consulted,:consult_notes,
        :ai_research,:ai_full_dpia,:created_at,:updated_at
    )"""
    # All DB columns must have a value — supply None for missing ones
    all_keys = [
        "title","status","regulation","org_name","department","controller_name",
        "dpo_name","dpo_email","activity_type","activity_desc","purpose","legal_basis",
        "data_categories","special_cats","data_subjects","subject_count","retention",
        "systems","processors","intl_transfer","transfer_dest","transfer_mech",
        "necessity","proportionality","risks","overall_risk","residual_risk",
        "dpo_consulted","auth_consulted","subjects_consulted","consult_notes",
        "ai_research","ai_full_dpia",
    ]
    params = {k: data.get(k) for k in all_keys}
    params.update({"ref_number": ref, "created_at": now, "updated_at": now})
    params.setdefault("title", "Untitled DPIA")
    params.setdefault("status", "draft")
    params.setdefault("regulation", "GDPR")
    with get_db() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def update_dpia(dpia_id: int, data: dict):
    now = _now()
    for field in ("data_categories", "special_cats", "risks"):
        if field in data and isinstance(data[field], list):
            data[field] = json.dumps(data[field])
    allowed = {
        "title","status","regulation","org_name","department","controller_name",
        "dpo_name","dpo_email","activity_type","activity_desc","purpose","legal_basis",
        "data_categories","special_cats","data_subjects","subject_count","retention",
        "systems","processors","intl_transfer","transfer_dest","transfer_mech",
        "necessity","proportionality","risks","overall_risk","residual_risk",
        "dpo_consulted","auth_consulted","subjects_consulted","consult_notes",
        "ai_research","ai_full_dpia",
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


def get_dpia(dpia_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM dpias WHERE id=?", (dpia_id,)).fetchone()
    return row_to_dict(row)


def list_dpias(search=None, regulation=None, status=None, limit=200) -> list:
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
    return [row_to_dict(r) for r in rows]


def delete_dpia(dpia_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM dpias WHERE id=?", (dpia_id,))


def stats() -> dict:
    with get_db() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM dpias").fetchone()[0]
        drafts   = conn.execute("SELECT COUNT(*) FROM dpias WHERE status='draft'").fetchone()[0]
        review   = conn.execute("SELECT COUNT(*) FROM dpias WHERE status='in_review'").fetchone()[0]
        approved = conn.execute("SELECT COUNT(*) FROM dpias WHERE status='approved'").fetchone()[0]
        rows     = conn.execute("SELECT regulation,COUNT(*) c FROM dpias GROUP BY regulation").fetchall()
    return {
        "total": total, "drafts": drafts,
        "in_review": review, "approved": approved,
        "by_regulation": {r["regulation"]: r["c"] for r in rows},
    }
