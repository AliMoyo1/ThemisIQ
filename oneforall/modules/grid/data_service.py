"""
GRID module — Data access layer.

All database operations for audit management: frameworks, audits, controls,
evidence, non-conformances, vendors, approvals, cross-mappings, share links,
reminders, comments, compliance scores, and activity logging.
"""
import json
import secrets
from datetime import datetime, timedelta
from core.timeutils import utcnow, to_dt

from database import get_db, insert_returning_id


import re as _re

# helpers
def _dict(row):
    return dict(row) if row else None

def _dicts(rows):
    return [dict(r) for r in rows]

def _find_unified_framework(db, grid_fw_name):
    """Find the unified frameworks.id for a grid_framework name.

    Tries exact match first, then normalized (strip version suffixes,
    collapse spaces/punctuation) so 'ISO27001' matches 'ISO 27001:2022'.
    """
    row = db.execute(
        "SELECT id FROM frameworks WHERE name=%s", (grid_fw_name,)
    ).fetchone()
    if row:
        return row[0]
    # Normalize: lowercase, remove colons, version suffixes, extra spaces
    def _norm(s):
        s = _re.sub(r'[:\-]', ' ', s.lower())
        s = _re.sub(r'\s*v?\d+(\.\d+)*\s*$', '', s)
        return _re.sub(r'\s+', '', s)
    target = _norm(grid_fw_name)
    all_fw = db.execute("SELECT id, name FROM frameworks").fetchall()
    for fid, fname in all_fw:
        if _norm(fname) == target:
            return fid
    return None

def _parse_json(val, default=None):
    if val is None:
        return default if default is not None else []
    if isinstance(val, (list, dict)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


_DEFAULT_FRAMEWORKS = [
    ("ISO 27001:2022", "Information Security Management System", "#4f8ef7", "Security"),
    ("ISO 42001:2023", "AI Management System Standard", "#b06ef5", "AI Governance"),
    ("SOC 2 Type II", "Service Organization Controls", "#3ecf84", "Security"),
    ("PCI DSS v4.0", "Payment Card Industry Data Security Standard", "#f5a623", "Financial"),
    ("GDPR", "General Data Protection Regulation", "#2dcdc8", "Privacy"),
    ("Zimbabwe CDPA", "Cyber and Data Protection Act", "#3ecf84", "Privacy"),
    ("HIPAA", "Health Insurance Portability Act", "#f25c5c", "Healthcare"),
]

def seed_frameworks():
    """Seed GRID frameworks from defaults, then sync with unified frameworks table."""
    db = get_db()
    try:
        cnt = db.execute("SELECT COUNT(*) FROM grid_frameworks").fetchone()[0]
        if cnt == 0:
            for name, desc, color, ftype in _DEFAULT_FRAMEWORKS:
                db.execute(
                    "INSERT INTO grid_frameworks (name, description, color, type) "
                    "VALUES (%s,%s,%s,%s)", (name, desc, color, ftype),
                )
            db.commit()

        # Sync: import any active unified frameworks that have 'grid' in
        # relevant_modules but are missing from grid_frameworks.
        try:
            unified = db.execute(
                "SELECT name, description, color, type FROM frameworks "
                "WHERE is_active = 1 AND relevant_modules LIKE '%grid%'"
            ).fetchall()
            existing = {
                r[0] for r in db.execute(
                    "SELECT name FROM grid_frameworks"
                ).fetchall()
            }
            added = 0
            for row in unified:
                if row[0] not in existing:
                    db.execute(
                        "INSERT INTO grid_frameworks (name, description, color, type) "
                        "VALUES (%s,%s,%s,%s)",
                        (row[0], row[1], row[2] or "#4f8ef7", row[3] or "Security"),
                    )
                    added += 1
            if added:
                db.commit()
        except Exception:
            pass  # unified frameworks table may not exist yet
    finally:
        db.close()

def list_frameworks():
    db = get_db()
    try:
        return _dicts(db.execute("SELECT * FROM grid_frameworks WHERE active=1 ORDER BY name").fetchall())
    finally:
        db.close()

def create_framework(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,"INSERT INTO grid_frameworks (name, description, color, type) VALUES (%s,%s,%s,%s)",
            (data.get("name", "Unnamed"), data.get("description", ""), data.get("color", "#4f8ef7"), data.get("type", "Security")))
        db.commit()
        return cur
    finally:
        db.close()

def delete_framework(fid):
    db = get_db()
    try:
        db.execute("UPDATE grid_frameworks SET active=0 WHERE id=%s", (fid,))
        db.commit()
    finally:
        db.close()


def list_audits():
    db = get_db()
    try:
        return _dicts(db.execute("""
            SELECT a.*, f.name AS framework_name, f.color AS framework_color,
                   u.full_name AS lead_name,
                   (SELECT COUNT(*) FROM grid_controls WHERE audit_id=a.id) AS total_controls,
                   (SELECT COUNT(*) FROM grid_controls WHERE audit_id=a.id AND status='Complete') AS complete_controls
            FROM grid_audits a
            LEFT JOIN grid_frameworks f ON a.framework_id=f.id
            LEFT JOIN users u ON a.lead_id=u.id
            ORDER BY a.created_at DESC
        """).fetchall())
    finally:
        db.close()

def get_audit(aid):
    db = get_db()
    try:
        audit = _dict(db.execute("""
            SELECT a.*, f.name AS framework_name, f.color AS framework_color
            FROM grid_audits a LEFT JOIN grid_frameworks f ON a.framework_id=f.id
            WHERE a.id=%s""", (aid,)).fetchone())
        if not audit:
            return None
        controls = _dicts(db.execute("""
            SELECT c.*, u.full_name AS assignee_name,
                   (SELECT COUNT(*) FROM grid_evidence_items WHERE control_id=c.id) AS evidence_total,
                   (SELECT COUNT(*) FROM grid_evidence_files WHERE control_id=c.id) AS evidence_uploaded
            FROM grid_controls c LEFT JOIN users u ON c.assignee_id=u.id
            WHERE c.audit_id=%s ORDER BY c.control_id""", (aid,)).fetchall())
        timeline = _dicts(db.execute("SELECT * FROM grid_timeline WHERE audit_id=%s ORDER BY date", (aid,)).fetchall())
        audit["controls"] = controls
        audit["timeline"] = timeline
        return audit
    finally:
        db.close()

def create_audit(data):
    import json as _json
    db = get_db()
    try:
        is_integrated = 1 if data.get("is_integrated") else 0
        framework_ids_json = None
        if is_integrated and data.get("framework_ids"):
            fw_ids = data["framework_ids"]
            if isinstance(fw_ids, list):
                framework_ids_json = _json.dumps(fw_ids)
            else:
                framework_ids_json = str(fw_ids)

        aid = insert_returning_id(db,
            "INSERT INTO grid_audits (name, framework_id, audit_type, auditor, lead_id, start_date, end_date, audit_date,"
            " scope, objective, criteria, methodology, is_integrated, framework_ids) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("name", "Untitled Audit"), data.get("framework_id"), data.get("audit_type", "External"),
             data.get("auditor"), data.get("lead_id"), data.get("start_date"), data.get("end_date"),
             data.get("audit_date"), data.get("scope", ""), data.get("objective", ""),
             data.get("criteria", ""), data.get("methodology", ""),
             is_integrated, framework_ids_json))
        grid_fw_id = data.get("framework_id")

        # ── Auto-populate controls ───────────────────────────────────────────
        # Helper: insert controls from one grid_framework into this audit
        def _insert_controls_for_grid_fw(gfid):
            gf = db.execute("SELECT name FROM grid_frameworks WHERE id=%s", (gfid,)).fetchone()
            if not gf:
                return []
            uf_id = _find_unified_framework(db, gf[0])
            if not uf_id:
                return []
            unified_ctrls = db.execute(
                "SELECT ref, name, description, priority "
                "FROM controls WHERE framework_id=%s ORDER BY ref",
                (uf_id,),
            ).fetchall()
            inserted_ids = {}
            for c in unified_ctrls:
                new_id = insert_returning_id(db,
                    "INSERT INTO grid_controls "
                    "(audit_id, framework_id, control_id, name, description, risk_level) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (aid, gfid, c[0], c[1], c[2], c[3] or "Medium"),
                )
                # Map unified control ref → new grid_controls.id
                inserted_ids[(uf_id, c[0])] = (new_id, uf_id)
            return inserted_ids

        if is_integrated and framework_ids_json:
            # IMS mode: insert controls for ALL selected frameworks
            all_fw_ids = _json.loads(framework_ids_json)
            all_inserted = {}  # (unified_fw_id, ref) → (grid_control_id, unified_fw_id)
            for fid in all_fw_ids:
                inserted = _insert_controls_for_grid_fw(int(fid))
                all_inserted.update(inserted)

            # Auto-create grid_control_mappings from aria_control_mappings for mapped pairs
            for (uf_id_a, ref_a), (gc_id_a, _) in all_inserted.items():
                for (uf_id_b, ref_b), (gc_id_b, _) in all_inserted.items():
                    if uf_id_a >= uf_id_b:
                        continue  # avoid duplicates / self-links
                    # Check if these two unified controls are mapped
                    ctrl_a = db.execute(
                        "SELECT id FROM controls WHERE framework_id=%s AND ref=%s",
                        (uf_id_a, ref_a)
                    ).fetchone()
                    ctrl_b = db.execute(
                        "SELECT id FROM controls WHERE framework_id=%s AND ref=%s",
                        (uf_id_b, ref_b)
                    ).fetchone()
                    if not ctrl_a or not ctrl_b:
                        continue
                    is_mapped = db.execute(
                        "SELECT 1 FROM aria_control_mappings "
                        "WHERE (source_control_id=%s AND target_control_id=%s) "
                        "   OR (source_control_id=%s AND target_control_id=%s) LIMIT 1",
                        (ctrl_a[0], ctrl_b[0], ctrl_b[0], ctrl_a[0])
                    ).fetchone()
                    if is_mapped:
                        db.execute(
                            "INSERT INTO grid_control_mappings "
                            "(source_control_id, target_control_id, mapping_type, confidence) "
                            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                            (gc_id_a, gc_id_b, "ims_equivalent", 1.0),
                        )
        elif grid_fw_id:
            # Standard single-framework mode
            _insert_controls_for_grid_fw(grid_fw_id)

        sd, ad = data.get("start_date"), data.get("audit_date")
        if sd and ad:
            try:
                start = to_dt(sd)
                end = to_dt(ad)
                mid = start + (end - start) / 2
                for title, dt in [("Kick-off meeting", start), ("Evidence collection opens", start + timedelta(days=7)),
                                  ("Internal review deadline", mid), ("Auditor evidence submission", end - timedelta(days=14)),
                                  ("External audit date", end)]:
                    db.execute("INSERT INTO grid_timeline (audit_id, title, date, status) VALUES (%s,%s,%s,%s)",
                               (aid, title, dt.strftime("%Y-%m-%d"), "Pending"))
            except ValueError:
                pass
        db.commit()
        return aid
    finally:
        db.close()

def is_audit_locked(audit_id, db=None):
    """Check if an audit is locked. Accepts optional db connection to avoid nesting."""
    own_db = db is None
    if own_db:
        db = get_db()
    try:
        row = db.execute("SELECT is_locked FROM grid_audits WHERE id=%s", (audit_id,)).fetchone()
        return bool(row and row[0])
    finally:
        if own_db:
            db.close()


def _assert_not_locked(audit_id, db=None):
    """Raise ValueError if audit is locked."""
    if is_audit_locked(audit_id, db):
        raise ValueError("Audit is locked and cannot be modified")


def update_audit(aid, data):
    db = get_db()
    try:
        _assert_not_locked(aid, db)
        fields, vals = [], []
        for col in ("name", "status", "auditor", "audit_date", "start_date", "end_date",
                    "audit_type", "lead_id", "framework_id",
                    "scope", "objective", "criteria", "methodology", "conclusion",
                    "parent_audit_id"):
            if col in data:
                fields.append(f"{col}=%s"); vals.append(data[col])
        if fields:
            vals.append(aid)
            db.execute(f"UPDATE grid_audits SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()

def delete_audit(aid):
    db = get_db()
    try:
        cids = [r[0] for r in db.execute("SELECT id FROM grid_controls WHERE audit_id=%s", (aid,)).fetchall()]
        for cid in cids:
            eids = [r[0] for r in db.execute("SELECT id FROM grid_evidence_files WHERE control_id=%s", (cid,)).fetchall()]
            for eid in eids:
                db.execute("DELETE FROM grid_approvals WHERE evidence_id=%s", (eid,))
            db.execute("DELETE FROM grid_evidence_files WHERE control_id=%s", (cid,))
            db.execute("DELETE FROM grid_evidence_items WHERE control_id=%s", (cid,))
            db.execute("DELETE FROM grid_control_comments WHERE control_id=%s", (cid,))
            db.execute("DELETE FROM grid_reminders WHERE control_id=%s", (cid,))
            db.execute("DELETE FROM grid_control_mappings WHERE source_control_id=%s OR target_control_id=%s", (cid, cid))
        db.execute("DELETE FROM grid_controls WHERE audit_id=%s", (aid,))
        db.execute("DELETE FROM grid_timeline WHERE audit_id=%s", (aid,))
        db.execute("DELETE FROM grid_non_conformances WHERE audit_id=%s", (aid,))
        db.execute("DELETE FROM grid_reminders WHERE audit_id=%s", (aid,))
        db.execute("DELETE FROM grid_share_links WHERE audit_id=%s", (aid,))
        db.execute("DELETE FROM grid_compliance_scores WHERE audit_id=%s", (aid,))
        db.execute("DELETE FROM grid_audits WHERE id=%s", (aid,))
        db.commit()
    finally:
        db.close()


def list_controls(audit_id=None, status=None, risk_level=None):
    db = get_db()
    try:
        q = """SELECT c.*, u.full_name AS assignee_name,
               (SELECT COUNT(*) FROM grid_evidence_items WHERE control_id=c.id) AS evidence_total,
               (SELECT COUNT(*) FROM grid_evidence_files WHERE control_id=c.id) AS evidence_uploaded
               FROM grid_controls c LEFT JOIN users u ON c.assignee_id=u.id WHERE 1=1"""
        params = []
        if audit_id:
            q += " AND c.audit_id=%s"; params.append(audit_id)
        if status:
            q += " AND c.status=%s"; params.append(status)
        if risk_level:
            q += " AND c.risk_level=%s"; params.append(risk_level)
        q += " ORDER BY c.control_id"
        return _dicts(db.execute(q, params).fetchall())
    finally:
        db.close()

def get_control(cid):
    db = get_db()
    try:
        ctrl = _dict(db.execute("""
            SELECT c.*, u.full_name AS assignee_name,
                   (SELECT COUNT(*) FROM grid_evidence_items WHERE control_id=c.id) AS evidence_total,
                   (SELECT COUNT(*) FROM grid_evidence_files WHERE control_id=c.id) AS evidence_uploaded
            FROM grid_controls c LEFT JOIN users u ON c.assignee_id=u.id WHERE c.id=%s""", (cid,)).fetchone())
        if not ctrl:
            return None
        ctrl["evidence_items"] = _dicts(db.execute("SELECT * FROM grid_evidence_items WHERE control_id=%s", (cid,)).fetchall())
        ctrl["evidence_files"] = _dicts(db.execute(
            "SELECT ef.*, u.full_name AS uploader_name FROM grid_evidence_files ef "
            "LEFT JOIN users u ON ef.uploaded_by=u.id WHERE ef.control_id=%s ORDER BY ef.created_at DESC", (cid,)).fetchall())
        ctrl["comments"] = _dicts(db.execute(
            "SELECT cc.*, u.full_name AS user_name FROM grid_control_comments cc "
            "LEFT JOIN users u ON cc.user_id=u.id WHERE cc.control_id=%s ORDER BY cc.created_at DESC", (cid,)).fetchall())
        ctrl["reminders"] = _dicts(db.execute("SELECT * FROM grid_reminders WHERE control_id=%s", (cid,)).fetchall())
        return ctrl
    finally:
        db.close()

def create_control(data):
    db = get_db()
    try:
        cid = insert_returning_id(db,
            "INSERT INTO grid_controls (audit_id, framework_id, control_id, name, description, risk_level, assignee_id, due_date) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("audit_id"), data.get("framework_id"), data.get("control_id", ""),
             data.get("name", "Untitled Control"), data.get("description", ""),
             data.get("risk_level", "Medium"), data.get("assignee_id"), data.get("due_date")))
        ev_req = data.get("evidence_required", [])
        if isinstance(ev_req, str):
            ev_req = _parse_json(ev_req, [])
        for ev_name in ev_req:
            if ev_name:
                db.execute("INSERT INTO grid_evidence_items (control_id, name) VALUES (%s,%s)", (cid, ev_name))
        db.commit()
        return cid
    finally:
        db.close()

def create_controls_bulk(audit_id, framework_id, controls):
    db = get_db()
    try:
        created = []
        for c in controls:
            cid = insert_returning_id(db,
                "INSERT INTO grid_controls (audit_id, framework_id, control_id, name, description, risk_level) VALUES (%s,%s,%s,%s,%s,%s)",
                (audit_id, framework_id, c.get("control_id", ""), c.get("name", ""), c.get("description", ""), c.get("risk_level", "Medium")))
            for ev in c.get("evidence_required", []):
                if ev:
                    db.execute("INSERT INTO grid_evidence_items (control_id, name) VALUES (%s,%s)", (cid, ev))
            created.append(cid)
        db.commit()
        return created
    finally:
        db.close()

def update_control(cid, data):
    db = get_db()
    try:
        # Check if parent audit is locked
        row = db.execute("SELECT audit_id FROM grid_controls WHERE id=%s", (cid,)).fetchone()
        if row:
            _assert_not_locked(row[0], db)
        fields, vals = [], []
        for col in ("status", "assignee_id", "due_date", "notes", "name", "description", "risk_level", "control_id"):
            if col in data:
                fields.append(f"{col}=%s"); vals.append(data[col])
        if fields:
            vals.append(cid)
            db.execute(f"UPDATE grid_controls SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
        _auto_status_control(db, cid, data.get("status"))
    finally:
        db.close()

def _auto_status_control(db, cid, explicit_status=None):
    """Auto-progress a control's status based on evidence state.

    Completion logic:
      - If evidence_items exist: Complete when every item has an approved file.
      - If no evidence_items: Complete when *all* uploaded files are approved.
      - In Progress when at least one file is uploaded but not yet fully approved.
      - Stays unchanged when the caller passes an explicit_status override.
    """
    if explicit_status:
        return

    items_required = db.execute(
        "SELECT COUNT(*) FROM grid_evidence_items WHERE control_id=%s", (cid,)
    ).fetchone()[0]
    files_total = db.execute(
        "SELECT COUNT(*) FROM grid_evidence_files WHERE control_id=%s", (cid,)
    ).fetchone()[0]
    files_approved = db.execute(
        "SELECT COUNT(*) FROM grid_evidence_files "
        "WHERE control_id=%s AND status IN ('approved', 'Approved')", (cid,)
    ).fetchone()[0]

    if items_required > 0:
        # Each evidence_item needs at least one approved file
        items_with_approval = db.execute(
            "SELECT COUNT(DISTINCT ei.id) FROM grid_evidence_items ei "
            "JOIN grid_evidence_files ef ON ef.evidence_item_id = ei.id "
            "WHERE ei.control_id = %s AND ef.status IN ('approved', 'Approved')",
            (cid,),
        ).fetchone()[0]
        if items_with_approval >= items_required:
            db.execute("UPDATE grid_controls SET status='Complete' WHERE id=%s AND status != 'Complete'", (cid,))
            db.commit()
        elif files_total > 0:
            db.execute("UPDATE grid_controls SET status='In Progress' WHERE id=%s AND status NOT IN ('Complete','In Progress')", (cid,))
            db.commit()
    else:
        # No explicit items — all files must be approved
        if files_total > 0 and files_approved >= files_total:
            db.execute("UPDATE grid_controls SET status='Complete' WHERE id=%s AND status != 'Complete'", (cid,))
            db.commit()
        elif files_total > 0:
            db.execute("UPDATE grid_controls SET status='In Progress' WHERE id=%s AND status NOT IN ('Complete','In Progress')", (cid,))
            db.commit()

def delete_control(cid):
    db = get_db()
    try:
        eids = [r[0] for r in db.execute("SELECT id FROM grid_evidence_files WHERE control_id=%s", (cid,)).fetchall()]
        for eid in eids:
            db.execute("DELETE FROM grid_approvals WHERE evidence_id=%s", (eid,))
        db.execute("DELETE FROM grid_evidence_files WHERE control_id=%s", (cid,))
        db.execute("DELETE FROM grid_evidence_items WHERE control_id=%s", (cid,))
        db.execute("DELETE FROM grid_control_comments WHERE control_id=%s", (cid,))
        db.execute("DELETE FROM grid_reminders WHERE control_id=%s", (cid,))
        db.execute("DELETE FROM grid_control_mappings WHERE source_control_id=%s OR target_control_id=%s", (cid, cid))
        db.execute("DELETE FROM grid_controls WHERE id=%s", (cid,))
        db.commit()
    finally:
        db.close()


def get_evidence(control_id):
    db = get_db()
    try:
        items = _dicts(db.execute("SELECT * FROM grid_evidence_items WHERE control_id=%s", (control_id,)).fetchall())
        files = _dicts(db.execute(
            "SELECT ef.*, u.full_name AS uploader_name FROM grid_evidence_files ef "
            "LEFT JOIN users u ON ef.uploaded_by=u.id WHERE ef.control_id=%s ORDER BY ef.created_at DESC", (control_id,)).fetchall())
        # Annotate items with their file counts and approval status
        for item in items:
            mapped = [f for f in files if f.get("evidence_item_id") == item["id"]]
            item["file_count"] = len(mapped)
            item["has_approved"] = any(
                (f.get("status") or "").lower() in ("approved",) for f in mapped
            )
        return {"items": items, "files": files}
    finally:
        db.close()


def get_evidence_items(control_id):
    """Return evidence checklist items for a control with mapped file info.
    Uses a single JOIN query instead of N+1 per-item queries.
    """
    db = get_db()
    try:
        # Fetch items
        items = _dicts(db.execute(
            "SELECT * FROM grid_evidence_items WHERE control_id=%s ORDER BY id", (control_id,)
        ).fetchall())
        if not items:
            return items

        # Fetch ALL related files in one query (fix N+1)
        item_ids = [i["id"] for i in items]
        placeholders = ",".join(["%s"] * len(item_ids))
        all_files = _dicts(db.execute(
            f"SELECT ef.id, ef.evidence_item_id, ef.original_name, ef.status, ef.file_size "
            f"FROM grid_evidence_files ef "
            f"WHERE ef.evidence_item_id IN ({placeholders}) ORDER BY ef.created_at DESC",
            item_ids,
        ).fetchall())

        # Group files by item_id in Python
        files_by_item: dict = {}
        for f in all_files:
            files_by_item.setdefault(f["evidence_item_id"], []).append(f)

        for item in items:
            mapped = files_by_item.get(item["id"], [])
            item["files"] = mapped
            item["file_count"] = len(mapped)
            item["has_approved"] = any(
                (f.get("status") or "").lower() == "approved" for f in mapped
            )
        return items
    finally:
        db.close()


def create_evidence_item(control_id, name, description="", required=1):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO grid_evidence_items (control_id, name, description, required) VALUES (%s,%s,%s,%s)",
            (control_id, name, description, required),
        )
        db.commit()
        return cur
    finally:
        db.close()


def delete_evidence_item(item_id):
    db = get_db()
    try:
        # Un-map any files that were linked to this item (don't delete the files)
        db.execute(
            "UPDATE grid_evidence_files SET evidence_item_id=NULL WHERE evidence_item_id=%s",
            (item_id,),
        )
        db.execute("DELETE FROM grid_evidence_items WHERE id=%s", (item_id,))
        db.commit()
    finally:
        db.close()

def create_evidence_file(data):
    """Create a new evidence file, or version-up an existing one if replace_id is set."""
    db = get_db()
    try:
        replace_id = data.get("replace_id")
        if replace_id:
            # ── Version-up: archive the current row, then update in-place ───
            existing = _dict(db.execute(
                "SELECT * FROM grid_evidence_files WHERE id=%s", (replace_id,)
            ).fetchone())
            if existing:
                db.execute(
                    "INSERT INTO grid_evidence_versions "
                    "(evidence_id, version, filename, original_name, file_path, "
                    "file_size, mime_type, uploaded_by, notes, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (replace_id, existing["version"], existing["filename"],
                     existing["original_name"], existing["file_path"],
                     existing["file_size"], existing["mime_type"],
                     existing["uploaded_by"], existing["notes"],
                     existing["created_at"]),
                )
                new_version = (existing["version"] or 1) + 1
                db.execute(
                    "UPDATE grid_evidence_files SET "
                    "filename=%s, original_name=%s, file_path=%s, file_size=%s, "
                    "mime_type=%s, uploaded_by=%s, notes=%s, version=%s, "
                    "status='Uploaded', approved_by=NULL, approved_at=NULL, "
                    "expiry_notified=0, expires_at=%s, created_at=CURRENT_TIMESTAMP "
                    "WHERE id=%s",
                    (data["filename"], data["original_name"], data["file_path"],
                     data.get("file_size", 0), data.get("mime_type", ""),
                     data.get("uploaded_by"), data.get("notes"),
                     new_version, data.get("expires_at"), replace_id),
                )
                db.commit()
                _auto_status_control(db, existing["control_id"])
                return replace_id

        # ── Fresh upload ────────────────────────────────────────────────────
        fid = insert_returning_id(db,
            "INSERT INTO grid_evidence_files (control_id, evidence_item_id, filename, original_name, "
            "file_path, file_size, mime_type, uploaded_by, notes, expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data["control_id"], data.get("evidence_item_id"), data["filename"],
             data["original_name"], data["file_path"], data.get("file_size", 0),
             data.get("mime_type", ""), data.get("uploaded_by"), data.get("notes"), data.get("expires_at")))
        db.commit()
        _auto_status_control(db, data["control_id"])
        # Sync to central vault (best-effort)
        try:
            sync_grid_evidence_to_vault(fid)
        except Exception:
            pass
        return fid
    finally:
        db.close()


def get_evidence_versions(evidence_id):
    """Return version history (oldest first) for an evidence file."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT ev.*, u.full_name AS uploader_name "
            "FROM grid_evidence_versions ev "
            "LEFT JOIN users u ON ev.uploaded_by = u.id "
            "WHERE ev.evidence_id = %s ORDER BY ev.version ASC",
            (evidence_id,),
        ).fetchall()
        return _dicts(rows)
    finally:
        db.close()

def get_evidence_file(eid):
    db = get_db()
    try:
        return _dict(db.execute("SELECT * FROM grid_evidence_files WHERE id=%s", (eid,)).fetchone())
    finally:
        db.close()

def approve_evidence(eid, status, approved_by):
    db = get_db()
    try:
        db.execute("UPDATE grid_evidence_files SET status=%s, approved_by=%s, approved_at=CURRENT_TIMESTAMP WHERE id=%s", (status, approved_by, eid))
        db.commit()
        ef = _dict(db.execute("SELECT control_id FROM grid_evidence_files WHERE id=%s", (eid,)).fetchone())
        if ef:
            _auto_status_control(db, ef["control_id"])
    finally:
        db.close()

def delete_evidence_file(eid):
    db = get_db()
    try:
        db.execute("DELETE FROM grid_approvals WHERE evidence_id=%s", (eid,))
        db.execute("DELETE FROM grid_evidence_files WHERE id=%s", (eid,))
        db.commit()
    finally:
        db.close()


def add_comment(control_id, user_id, content):
    db = get_db()
    try:
        cur = insert_returning_id(db,"INSERT INTO grid_control_comments (control_id, user_id, content) VALUES (%s,%s,%s)", (control_id, user_id, content))
        db.commit()
        return cur
    finally:
        db.close()


def create_reminder(data):
    db = get_db()
    try:
        cur = insert_returning_id(db,"INSERT INTO grid_reminders (control_id, audit_id, user_id, frequency) VALUES (%s,%s,%s,%s)",
            (data.get("control_id"), data.get("audit_id"), data["user_id"], data.get("frequency", "weekly")))
        db.commit()
        return cur
    finally:
        db.close()

def get_pending_reminders(audit_id):
    db = get_db()
    try:
        return _dicts(db.execute("""
            SELECT c.*, u.full_name AS assignee_name, u.email AS assignee_email
            FROM grid_controls c LEFT JOIN users u ON c.assignee_id=u.id
            WHERE c.audit_id=%s AND c.status!='Complete' AND u.email IS NOT NULL
        """, (audit_id,)).fetchall())
    finally:
        db.close()


# CAP lifecycle steps (ordered)
_CAP_STATUSES = [
    "Open", "RCA", "CAP Submitted", "Approved",
    "Implementation", "Verification", "Closed",
]


def list_ncs(audit_id=None, status=None, cap_status=None):
    db = get_db()
    try:
        q = (
            "SELECT nc.*, u.full_name AS assigned_name, "
            "v.full_name AS verified_by_name, "
            "m.full_name AS mgmt_response_by_name, "
            "c.control_id AS ctrl_ref, c.name AS control_name, "
            "a.name AS audit_name "
            "FROM grid_non_conformances nc "
            "LEFT JOIN users u ON nc.assigned_to=u.id "
            "LEFT JOIN users v ON nc.verified_by=v.id "
            "LEFT JOIN users m ON nc.mgmt_response_by=m.id "
            "LEFT JOIN grid_controls c ON nc.control_id=c.id "
            "LEFT JOIN grid_audits a ON nc.audit_id=a.id "
            "WHERE 1=1"
        )
        params = []
        if audit_id:
            q += " AND nc.audit_id=%s"
            params.append(audit_id)
        if status:
            q += " AND nc.status=%s"
            params.append(status)
        if cap_status:
            q += " AND nc.cap_status=%s"
            params.append(cap_status)
        q += " ORDER BY nc.created_at DESC"
        return _dicts(db.execute(q, params).fetchall())
    finally:
        db.close()

def get_nc(ncid):
    db = get_db()
    try:
        nc = _dict(db.execute(
            "SELECT nc.*, u.full_name AS assigned_name, "
            "v.full_name AS verified_by_name, "
            "m.full_name AS mgmt_response_by_name, "
            "c.control_id AS ctrl_ref, c.name AS control_name, "
            "a.name AS audit_name "
            "FROM grid_non_conformances nc "
            "LEFT JOIN users u ON nc.assigned_to=u.id "
            "LEFT JOIN users v ON nc.verified_by=v.id "
            "LEFT JOIN users m ON nc.mgmt_response_by=m.id "
            "LEFT JOIN grid_controls c ON nc.control_id=c.id "
            "LEFT JOIN grid_audits a ON nc.audit_id=a.id "
            "WHERE nc.id=%s", (ncid,)).fetchone())
        return nc
    finally:
        db.close()

def create_nc(data):
    db = get_db()
    try:
        _assert_not_locked(data["audit_id"], db)
        cur = insert_returning_id(db,
            "INSERT INTO grid_non_conformances "
            "(audit_id, control_id, title, description, severity, assigned_to, due_date, cap_status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (data["audit_id"], data.get("control_id"),
             data.get("title", "Untitled NC"), data.get("description", ""),
             data.get("severity", "minor"), data.get("assigned_to"),
             data.get("due_date"), "Open"))
        db.commit()
        return cur
    finally:
        db.close()

def update_nc(ncid, data):
    db = get_db()
    try:
        # Check if parent audit is locked
        row = db.execute("SELECT audit_id FROM grid_non_conformances WHERE id=%s", (ncid,)).fetchone()
        if row:
            _assert_not_locked(row[0], db)
        fields, vals = [], []
        for col in ("title", "description", "severity", "status", "assigned_to",
                     "root_cause", "corrective_action", "preventive_action",
                     "due_date", "target_date", "cap_status",
                     "verification_notes", "verified_by",
                     "response_deadline", "effectiveness_review"):
            if col in data:
                fields.append(f"{col}=%s")
                vals.append(data[col])
        # Auto-set timestamps based on cap_status transitions
        cap = data.get("cap_status")
        if cap == "Closed" and "closed_at" not in data:
            fields.append("closed_at=CURRENT_TIMESTAMP")
        if cap == "Verification" and data.get("verified_by"):
            fields.append("verified_at=CURRENT_TIMESTAMP")
        # Legacy: also close if status=closed
        if data.get("status") == "closed" and "closed_at" not in data:
            fields.append("closed_at=CURRENT_TIMESTAMP")
        if fields:
            vals.append(ncid)
            db.execute(
                f"UPDATE grid_non_conformances SET {','.join(fields)} WHERE id=%s",
                vals,
            )
            db.commit()
    finally:
        db.close()

def advance_cap_status(ncid, user_id=None):
    """Advance a NC to the next CAP lifecycle step. Returns new status or None."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT cap_status FROM grid_non_conformances WHERE id=%s", (ncid,)
        ).fetchone()
        if not row:
            return None
        current = row[0] or "Open"
        try:
            idx = _CAP_STATUSES.index(current)
        except ValueError:
            idx = 0
        if idx >= len(_CAP_STATUSES) - 1:
            return current  # already at Closed
        next_status = _CAP_STATUSES[idx + 1]
        sets = "cap_status=%s"
        params = [next_status]
        if next_status == "Verification" and user_id:
            sets += ", verified_by=%s, verified_at=CURRENT_TIMESTAMP"
            params.append(user_id)
        if next_status == "Closed":
            sets += ", closed_at=CURRENT_TIMESTAMP, status='closed'"
        params.append(ncid)
        db.execute(
            f"UPDATE grid_non_conformances SET {sets} WHERE id=%s", params
        )
        db.commit()
        return next_status
    finally:
        db.close()

def revert_cap_status(ncid):
    """Move a NC back one CAP lifecycle step. Returns new status or None."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT cap_status FROM grid_non_conformances WHERE id=%s", (ncid,)
        ).fetchone()
        if not row:
            return None
        current = row[0] or "Open"
        try:
            idx = _CAP_STATUSES.index(current)
        except ValueError:
            idx = 0
        if idx <= 0:
            return current  # already at Open
        prev_status = _CAP_STATUSES[idx - 1]
        # If reverting from Closed, re-open
        sets = "cap_status=%s"
        params = [prev_status]
        if current == "Closed":
            sets += ", closed_at=NULL, status='open'"
        params.append(ncid)
        db.execute(
            f"UPDATE grid_non_conformances SET {sets} WHERE id=%s", params
        )
        db.commit()
        return prev_status
    finally:
        db.close()

def submit_mgmt_response(ncid, user_id, status, response_text=None, response_deadline=None):
    """
    Manager approves or rejects a CAP.
    status: 'Approved' or 'Rejected'
    On approval: auto-advances cap_status from 'CAP Submitted' to 'Approved'.
    On rejection: reverts cap_status back to 'RCA' so the assignee can rework.
    """
    if status not in ("Approved", "Rejected"):
        return None
    db = get_db()
    try:
        row = db.execute(
            "SELECT cap_status FROM grid_non_conformances WHERE id=%s", (ncid,)
        ).fetchone()
        if not row:
            return None
        sets = (
            "mgmt_response_status=%s, mgmt_response_by=%s, "
            "mgmt_response_at=CURRENT_TIMESTAMP"
        )
        params = [status, user_id]
        if response_text is not None:
            sets += ", mgmt_response=%s"
            params.append(response_text)
        if response_deadline is not None:
            sets += ", response_deadline=%s"
            params.append(response_deadline)
        # On approval, advance to 'Approved' stage
        if status == "Approved":
            sets += ", cap_status='Approved'"
        # On rejection, revert to 'RCA' for rework
        elif status == "Rejected":
            sets += ", cap_status='RCA'"
        params.append(ncid)
        db.execute(
            f"UPDATE grid_non_conformances SET {sets} WHERE id=%s", params
        )
        db.commit()
        # Return the new cap_status
        new = db.execute(
            "SELECT cap_status FROM grid_non_conformances WHERE id=%s", (ncid,)
        ).fetchone()
        return new[0] if new else None
    finally:
        db.close()


def delete_nc(ncid):
    db = get_db()
    try:
        db.execute("DELETE FROM grid_non_conformances WHERE id=%s", (ncid,))
        db.commit()
    finally:
        db.close()


# ── NC-Evidence Links ──────────────────────────────────────────────────────

def list_nc_evidence(ncid):
    """Return all evidence files linked to a non-conformance."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT lnk.id AS link_id, lnk.notes AS link_notes, lnk.linked_at, "
            "ef.id AS evidence_id, ef.original_name, ef.filename, ef.file_size, "
            "ef.mime_type, ef.status AS evidence_status, ef.created_at AS uploaded_at, "
            "u.full_name AS linked_by_name, "
            "up.full_name AS uploader_name "
            "FROM grid_nc_evidence lnk "
            "JOIN grid_evidence_files ef ON lnk.evidence_file_id = ef.id "
            "LEFT JOIN users u ON lnk.linked_by = u.id "
            "LEFT JOIN users up ON ef.uploaded_by = up.id "
            "WHERE lnk.nc_id=%s "
            "ORDER BY lnk.linked_at DESC",
            (ncid,)
        ).fetchall()
        return _dicts(rows)
    finally:
        db.close()


def link_evidence_to_nc(ncid, evidence_file_id, linked_by=None, notes=None):
    """Link an evidence file to a non-conformance. Returns link id or None on duplicate."""
    db = get_db()
    try:
        row_id = insert_returning_id(db,
            "INSERT INTO grid_nc_evidence (nc_id, evidence_file_id, linked_by, notes) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (ncid, evidence_file_id, linked_by, notes),
        )
        db.commit()
        return row_id
    finally:
        db.close()


def unlink_evidence_from_nc(link_id):
    """Remove an NC-evidence link by its id."""
    db = get_db()
    try:
        db.execute("DELETE FROM grid_nc_evidence WHERE id=%s", (link_id,))
        db.commit()
    finally:
        db.close()


def get_available_evidence_for_nc(ncid):
    """Return evidence files from the same audit as the NC, not yet linked."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT ef.id, ef.original_name, ef.file_size, ef.mime_type, "
            "ef.status, c.control_id AS ctrl_ref, c.name AS control_name "
            "FROM grid_evidence_files ef "
            "JOIN grid_controls c ON ef.control_id = c.id "
            "JOIN grid_non_conformances nc ON nc.audit_id = c.audit_id "
            "WHERE nc.id=%s "
            "AND ef.id NOT IN (SELECT evidence_file_id FROM grid_nc_evidence WHERE nc_id=%s) "
            "ORDER BY ef.original_name",
            (ncid, ncid)
        ).fetchall()
        return _dicts(rows)
    finally:
        db.close()


def list_vendors(status=None, risk_level=None):
    db = get_db()
    try:
        q = "SELECT * FROM grid_vendors WHERE 1=1"
        params = []
        if status:
            q += " AND status=%s"; params.append(status)
        if risk_level:
            q += " AND risk_level=%s"; params.append(risk_level)
        q += " ORDER BY name"
        vendors = _dicts(db.execute(q, params).fetchall())
        for v in vendors:
            latest = _dict(db.execute("SELECT * FROM grid_vendor_assessments WHERE vendor_id=%s ORDER BY assessment_date DESC LIMIT 1", (v["id"],)).fetchone())
            v["latest_assessment"] = latest
        return vendors
    finally:
        db.close()

def get_vendor(vid):
    db = get_db()
    try:
        v = _dict(db.execute("SELECT * FROM grid_vendors WHERE id=%s", (vid,)).fetchone())
        if v:
            v["assessments"] = _dicts(db.execute("SELECT * FROM grid_vendor_assessments WHERE vendor_id=%s ORDER BY assessment_date DESC", (vid,)).fetchall())
        return v
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
            "INSERT INTO grid_vendors (name, contact_name, contact_email, services, risk_level, status, frameworks, contract_expiry, notes, canonical_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (data.get("name", "Unnamed"), data.get("contact_name"), data.get("contact_email"),
             data.get("services"), data.get("risk_level", "medium"), data.get("status", "active"),
             data.get("frameworks"), data.get("contract_expiry"), data.get("notes"), canonical_id))
        db.commit()
        return cur
    finally:
        db.close()

def update_vendor(vid, data):
    db = get_db()
    try:
        fields, vals = [], []
        for col in ("name", "contact_name", "contact_email", "services", "risk_level", "status", "frameworks", "contract_expiry", "notes"):
            if col in data:
                fields.append(f"{col}=%s"); vals.append(data[col])
        if fields:
            vals.append(vid)
            db.execute(f"UPDATE grid_vendors SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()

def delete_vendor(vid):
    db = get_db()
    try:
        db.execute("DELETE FROM grid_vendor_assessments WHERE vendor_id=%s", (vid,))
        db.execute("DELETE FROM grid_vendors WHERE id=%s", (vid,))
        db.commit()
    finally:
        db.close()

def create_vendor_assessment(vid, data):
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO grid_vendor_assessments (vendor_id, score, findings, action_required, assessed_by) VALUES (%s,%s,%s,%s,%s)",
            (vid, data.get("score"), data.get("findings"), data.get("action_required"), data.get("assessed_by")))
        db.commit()
        return cur
    finally:
        db.close()


def bulk_approve_evidence(eids, status, approved_by):
    """Approve or reject multiple evidence files at once."""
    db = get_db()
    try:
        control_ids = set()
        for eid in eids:
            db.execute(
                "UPDATE grid_evidence_files SET status=%s, approved_by=%s, approved_at=CURRENT_TIMESTAMP WHERE id=%s",
                (status, approved_by, eid),
            )
            ef = db.execute("SELECT control_id FROM grid_evidence_files WHERE id=%s", (eid,)).fetchone()
            if ef:
                control_ids.add(ef[0])
        db.commit()
        for cid in control_ids:
            _auto_status_control(db, cid)
        return len(eids)
    finally:
        db.close()


def get_all_evidence(audit_id=None, status=None, mime_type=None):
    """Return all evidence files across audits, with control/audit context."""
    db = get_db()
    try:
        q = (
            "SELECT ef.*, u.full_name AS uploader_name, "
            "c.control_id AS ctrl_ref, c.name AS control_name, c.audit_id, "
            "a.name AS audit_name, a.status AS audit_status "
            "FROM grid_evidence_files ef "
            "LEFT JOIN users u ON ef.uploaded_by=u.id "
            "LEFT JOIN grid_controls c ON ef.control_id=c.id "
            "LEFT JOIN grid_audits a ON c.audit_id=a.id "
            "WHERE 1=1"
        )
        params = []
        if audit_id:
            q += " AND c.audit_id=%s"
            params.append(audit_id)
        if status:
            q += " AND ef.status=%s"
            params.append(status)
        if mime_type:
            q += " AND ef.mime_type LIKE %s"
            params.append(f"%{mime_type}%")
        q += " ORDER BY ef.created_at DESC"
        return _dicts(db.execute(q, params).fetchall())
    finally:
        db.close()


def get_evidence_completeness(audit_id):
    """Return evidence completeness stats for an audit."""
    db = get_db()
    try:
        controls = _dicts(db.execute(
            "SELECT c.id, c.control_id AS ctrl_ref, c.name, c.status "
            "FROM grid_controls c WHERE c.audit_id=%s ORDER BY c.control_id",
            (audit_id,),
        ).fetchall())

        total_items = 0
        items_with_evidence = 0
        items_approved = 0
        total_files = 0
        approved_files = 0
        pending_files = 0
        rejected_files = 0
        controls_complete = 0
        controls_with_evidence = []
        controls_without_evidence = []

        for ctrl in controls:
            cid = ctrl["id"]
            items = db.execute(
                "SELECT COUNT(*) FROM grid_evidence_items WHERE control_id=%s", (cid,)
            ).fetchone()[0]
            files = db.execute(
                "SELECT COUNT(*) FROM grid_evidence_files WHERE control_id=%s", (cid,)
            ).fetchone()[0]
            approved = db.execute(
                "SELECT COUNT(*) FROM grid_evidence_files WHERE control_id=%s AND status IN ('approved','Approved')",
                (cid,),
            ).fetchone()[0]
            pending = db.execute(
                "SELECT COUNT(*) FROM grid_evidence_files WHERE control_id=%s AND (status IS NULL OR status IN ('Uploaded','pending',''))",
                (cid,),
            ).fetchone()[0]
            rejected = db.execute(
                "SELECT COUNT(*) FROM grid_evidence_files WHERE control_id=%s AND status IN ('rejected','Rejected')",
                (cid,),
            ).fetchone()[0]

            total_items += items
            total_files += files
            approved_files += approved
            pending_files += pending
            rejected_files += rejected

            if items > 0:
                items_w = db.execute(
                    "SELECT COUNT(DISTINCT ei.id) FROM grid_evidence_items ei "
                    "JOIN grid_evidence_files ef ON ef.evidence_item_id=ei.id "
                    "WHERE ei.control_id=%s", (cid,),
                ).fetchone()[0]
                items_a = db.execute(
                    "SELECT COUNT(DISTINCT ei.id) FROM grid_evidence_items ei "
                    "JOIN grid_evidence_files ef ON ef.evidence_item_id=ei.id "
                    "WHERE ei.control_id=%s AND ef.status IN ('approved','Approved')", (cid,),
                ).fetchone()[0]
                items_with_evidence += items_w
                items_approved += items_a

            if ctrl.get("status") == "Complete":
                controls_complete += 1

            if files > 0:
                controls_with_evidence.append({
                    "id": cid,
                    "ctrl_ref": ctrl["ctrl_ref"],
                    "name": ctrl["name"],
                    "files": files,
                    "approved": approved,
                    "pending": pending,
                    "rejected": rejected,
                })
            else:
                controls_without_evidence.append({
                    "id": cid,
                    "ctrl_ref": ctrl["ctrl_ref"],
                    "name": ctrl["name"],
                })

        total_controls = len(controls)
        return {
            "totalControls": total_controls,
            "controlsComplete": controls_complete,
            "controlsWithEvidence": len(controls_with_evidence),
            "controlsWithoutEvidence": len(controls_without_evidence),
            "totalItems": total_items,
            "itemsWithEvidence": items_with_evidence,
            "itemsApproved": items_approved,
            "totalFiles": total_files,
            "approvedFiles": approved_files,
            "pendingFiles": pending_files,
            "rejectedFiles": rejected_files,
            "completionPct": round(controls_complete / total_controls * 100) if total_controls else 0,
            "evidencePct": round(len(controls_with_evidence) / total_controls * 100) if total_controls else 0,
            "approvalPct": round(approved_files / total_files * 100) if total_files else 0,
            "controlsMissing": controls_without_evidence,
            "controlsDetail": controls_with_evidence,
        }
    finally:
        db.close()


def get_approvals(evidence_id):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT a.*, u.full_name AS approver_name FROM grid_approvals a "
            "LEFT JOIN users u ON a.approver_id=u.id WHERE a.evidence_id=%s ORDER BY a.stage", (evidence_id,)).fetchall())
    finally:
        db.close()

def request_approval(evidence_id, approver_id):
    db = get_db()
    try:
        max_stage = db.execute("SELECT COALESCE(MAX(stage),0) FROM grid_approvals WHERE evidence_id=%s", (evidence_id,)).fetchone()[0]
        cur = insert_returning_id(db,"INSERT INTO grid_approvals (evidence_id, stage, approver_id) VALUES (%s,%s,%s)", (evidence_id, max_stage + 1, approver_id))
        db.commit()
        return cur
    finally:
        db.close()

def decide_approval(approval_id, status, comments=None):
    db = get_db()
    try:
        db.execute("UPDATE grid_approvals SET status=%s, comments=%s, decided_at=CURRENT_TIMESTAMP WHERE id=%s", (status, comments, approval_id))
        db.commit()
        row = _dict(db.execute("SELECT evidence_id FROM grid_approvals WHERE id=%s", (approval_id,)).fetchone())
        if row and status == "approved":
            approve_evidence(row["evidence_id"], "Approved", None)
    finally:
        db.close()


def list_mappings(audit_id):
    db = get_db()
    try:
        return _dicts(db.execute("""
            SELECT m.*, s.name AS source_name, s.control_id AS source_ctrl_id,
                   t.name AS target_name, t.control_id AS target_ctrl_id
            FROM grid_control_mappings m
            JOIN grid_controls s ON m.source_control_id=s.id
            JOIN grid_controls t ON m.target_control_id=t.id
            WHERE s.audit_id=%s OR t.audit_id=%s
        """, (audit_id, audit_id)).fetchall())
    finally:
        db.close()

def create_mapping(source_id, target_id, mapping_type="equivalent", confidence=None):
    db = get_db()
    try:
        cur = insert_returning_id(db,"INSERT INTO grid_control_mappings (source_control_id, target_control_id, mapping_type, confidence) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (source_id, target_id, mapping_type, confidence))
        db.commit()
        return cur
    finally:
        db.close()

def save_mappings_bulk(mappings):
    db = get_db()
    try:
        for m in mappings:
            db.execute("INSERT INTO grid_control_mappings (source_control_id, target_control_id, mapping_type, confidence) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (m["source_control_id"], m["target_control_id"], m.get("mapping_type", "equivalent"), m.get("confidence")))
        db.commit()
    finally:
        db.close()

def delete_mapping(mid):
    db = get_db()
    try:
        db.execute("DELETE FROM grid_control_mappings WHERE id=%s", (mid,))
        db.commit()
    finally:
        db.close()


def create_share_link(audit_id, created_by, auditor_email=None, expires_days=30):
    db = get_db()
    try:
        token = secrets.token_urlsafe(32)
        expires = (utcnow() + timedelta(days=expires_days)).strftime("%Y-%m-%d %H:%M:%S")
        cur = insert_returning_id(db,"INSERT INTO grid_share_links (audit_id, token, created_by, auditor_email, expires_at) VALUES (%s,%s,%s,%s,%s)",
            (audit_id, token, created_by, auditor_email, expires))
        db.commit()
        return {"id": cur, "token": token, "expires_at": expires}
    finally:
        db.close()

def list_share_links(audit_id):
    db = get_db()
    try:
        return _dicts(db.execute("SELECT * FROM grid_share_links WHERE audit_id=%s AND active=1 ORDER BY created_at DESC", (audit_id,)).fetchall())
    finally:
        db.close()

def validate_share_link(token):
    db = get_db()
    try:
        link = _dict(db.execute("SELECT * FROM grid_share_links WHERE token=%s AND active=1", (token,)).fetchone())
        if not link:
            return None
        if link.get("expires_at") and to_dt(link["expires_at"]) < utcnow():
            return None
        db.execute("UPDATE grid_share_links SET access_count=access_count+1 WHERE id=%s", (link["id"],))
        db.commit()
        return link
    finally:
        db.close()

def revoke_share_link(sid):
    db = get_db()
    try:
        db.execute("UPDATE grid_share_links SET active=0 WHERE id=%s", (sid,))
        db.commit()
    finally:
        db.close()


def get_audit_stats(audit_id):
    db = get_db()
    try:
        total = db.execute("SELECT COUNT(*) FROM grid_controls WHERE audit_id=%s", (audit_id,)).fetchone()[0]
        complete = db.execute("SELECT COUNT(*) FROM grid_controls WHERE audit_id=%s AND status='Complete'", (audit_id,)).fetchone()[0]
        in_progress = db.execute("SELECT COUNT(*) FROM grid_controls WHERE audit_id=%s AND status='In Progress'", (audit_id,)).fetchone()[0]
        overdue = db.execute("SELECT COUNT(*) FROM grid_controls WHERE audit_id=%s AND due_date < CURRENT_DATE AND status!='Complete'", (audit_id,)).fetchone()[0]
        ev_total = db.execute("SELECT COUNT(*) FROM grid_evidence_items ei JOIN grid_controls c ON ei.control_id=c.id WHERE c.audit_id=%s", (audit_id,)).fetchone()[0]
        ev_uploaded = db.execute("SELECT COUNT(*) FROM grid_evidence_files ef JOIN grid_controls c ON ef.control_id=c.id WHERE c.audit_id=%s", (audit_id,)).fetchone()[0]
        audit = _dict(db.execute("SELECT audit_date FROM grid_audits WHERE id=%s", (audit_id,)).fetchone())
        days = None
        if audit and audit.get("audit_date"):
            try:
                days = (datetime.strptime(audit["audit_date"], "%Y-%m-%d") - utcnow()).days
            except ValueError:
                pass
        return {
            "total": total, "complete": complete, "inProgress": in_progress,
            "notStarted": total - complete - in_progress, "overdue": overdue,
            "evidenceTotal": ev_total, "evidenceUploaded": ev_uploaded,
            "daysToAudit": days,
            "completionPct": round(complete / total * 100) if total else 0,
        }
    finally:
        db.close()


def log_activity(user_id, action, entity_type, entity_id, details=None):
    db = get_db()
    try:
        db.execute("INSERT INTO audit_log (user_id, action, module, entity_type, entity_id, details) VALUES (%s,%s,%s,%s,%s,%s)",
            (user_id, action, "grid", entity_type, entity_id, json.dumps(details) if details else None))
        db.commit()
    finally:
        db.close()

def list_activity(limit=50):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT a.*, u.full_name AS user_name FROM audit_log a "
            "LEFT JOIN users u ON a.user_id=u.id WHERE a.module='grid' "
            "ORDER BY a.created_at DESC LIMIT %s", (limit,)).fetchall())
    finally:
        db.close()


def update_timeline(tid, data):
    db = get_db()
    try:
        fields, vals = [], []
        for col in ("title", "date", "status"):
            if col in data:
                fields.append(f"{col}=%s"); vals.append(data[col])
        if fields:
            vals.append(tid)
            db.execute(f"UPDATE grid_timeline SET {','.join(fields)} WHERE id=%s", vals)
            db.commit()
    finally:
        db.close()


def record_score(audit_id, score, details=None):
    db = get_db()
    try:
        cur = insert_returning_id(db,"INSERT INTO grid_compliance_scores (audit_id, score, details) VALUES (%s,%s,%s)",
            (audit_id, score, json.dumps(details) if details else None))
        db.commit()
        return cur
    finally:
        db.close()

def list_scores(audit_id, limit=60):
    db = get_db()
    try:
        return _dicts(db.execute(
            "SELECT * FROM grid_compliance_scores WHERE audit_id=%s ORDER BY created_at DESC LIMIT %s",
            (audit_id, limit)).fetchall())
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# Report persistence
# ═════════════════════════════════════════════════════════════════════════════

def create_report(data):
    """Save a generated report record."""
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO grid_reports "
            "(audit_id, report_type, title, filename, file_path, file_size, notes, generated_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                data["audit_id"],
                data.get("report_type", "pdf"),
                data.get("title", "Untitled Report"),
                data["filename"],
                data["file_path"],
                data.get("file_size", 0),
                data.get("notes"),
                data.get("generated_by"),
            ),
        )
        db.commit()
        return cur
    finally:
        db.close()


def list_reports(audit_id=None, limit=50):
    """List saved reports, optionally filtered by audit."""
    db = get_db()
    try:
        q = (
            "SELECT r.*, a.name AS audit_name, "
            "u.full_name AS generated_by_name "
            "FROM grid_reports r "
            "LEFT JOIN grid_audits a ON r.audit_id=a.id "
            "LEFT JOIN users u ON r.generated_by=u.id "
            "WHERE 1=1"
        )
        params = []
        if audit_id is not None:
            q += " AND r.audit_id=%s"
            params.append(audit_id)
        q += " ORDER BY r.generated_at DESC LIMIT %s"
        params.append(limit)
        return _dicts(db.execute(q, params).fetchall())
    finally:
        db.close()


def get_report(rid):
    """Get a single report record."""
    db = get_db()
    try:
        return _dict(db.execute(
            "SELECT r.*, a.name AS audit_name, "
            "u.full_name AS generated_by_name "
            "FROM grid_reports r "
            "LEFT JOIN grid_audits a ON r.audit_id=a.id "
            "LEFT JOIN users u ON r.generated_by=u.id "
            "WHERE r.id=%s", (rid,)
        ).fetchone())
    finally:
        db.close()


def delete_report(rid):
    """Delete a report record (caller should also remove the physical file)."""
    db = get_db()
    try:
        db.execute("DELETE FROM grid_reports WHERE id=%s", (rid,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# Follow-up audit linking
# ═════════════════════════════════════════════════════════════════════════════

def create_followup_audit(parent_audit_id, data):
    """
    Create a follow-up audit linked to a parent.
    Copies framework, audit_type, and lead from parent if not overridden.
    Returns the new audit ID.
    """
    db = get_db()
    try:
        parent = _dict(db.execute(
            "SELECT * FROM grid_audits WHERE id=%s", (parent_audit_id,)
        ).fetchone())
        if not parent:
            return None

        name = data.get("name") or f"{parent['name']} — Follow-up"
        fw_id = data.get("framework_id") or parent.get("framework_id")
        audit_type = data.get("audit_type") or parent.get("audit_type", "External")
        lead_id = data.get("lead_id") or parent.get("lead_id")

        new_aid = insert_returning_id(db,
            "INSERT INTO grid_audits "
            "(name, framework_id, audit_type, auditor, lead_id, start_date, "
            " end_date, audit_date, scope, objective, criteria, methodology, "
            " parent_audit_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                name, fw_id, audit_type,
                data.get("auditor") or parent.get("auditor"),
                lead_id,
                data.get("start_date"), data.get("end_date"),
                data.get("audit_date"),
                data.get("scope", parent.get("scope", "")),
                data.get("objective", parent.get("objective", "")),
                data.get("criteria", parent.get("criteria", "")),
                data.get("methodology", parent.get("methodology", "")),
                parent_audit_id,
            ),
        )

        # Auto-populate controls from framework (same as create_audit)
        if fw_id:
            gf = db.execute(
                "SELECT name FROM grid_frameworks WHERE id=%s", (fw_id,)
            ).fetchone()
            if gf:
                uf_id = _find_unified_framework(db, gf[0])
                if uf_id:
                    rows = db.execute(
                        "SELECT ref, name, description, priority "
                        "FROM controls WHERE framework_id=%s ORDER BY ref",
                        (uf_id,),
                    ).fetchall()
                    for c in rows:
                        db.execute(
                            "INSERT INTO grid_controls "
                            "(audit_id, framework_id, control_id, name, description, risk_level) "
                            "VALUES (%s,%s,%s,%s,%s,%s)",
                            (new_aid, fw_id, c[0], c[1], c[2], c[3] or "Medium"),
                        )

        db.commit()
        return new_aid
    finally:
        db.close()


def carry_forward_ncs(parent_audit_id, new_audit_id):
    """
    Copy open/in-progress NCs from parent audit into the follow-up audit.
    Resets CAP status to 'Open' and links via source_nc_id for traceability.
    Returns count of carried-forward NCs.
    """
    db = get_db()
    try:
        # Fetch open NCs from parent (not closed, not in Verification/Closed stage)
        ncs = db.execute(
            "SELECT id, control_id, title, description, severity, assigned_to, "
            "root_cause, corrective_action, preventive_action, due_date, "
            "cap_status "
            "FROM grid_non_conformances "
            "WHERE audit_id=%s AND status != 'closed' "
            "AND cap_status NOT IN ('Closed', 'Verification')",
            (parent_audit_id,),
        ).fetchall()

        count = 0
        for nc in ncs:
            # Try to match control by control_id (ref) in the new audit
            new_ctrl_id = None
            if nc["control_id"]:
                old_ctrl = db.execute(
                    "SELECT control_id FROM grid_controls WHERE id=%s",
                    (nc["control_id"],),
                ).fetchone()
                if old_ctrl and old_ctrl[0]:
                    match = db.execute(
                        "SELECT id FROM grid_controls "
                        "WHERE audit_id=%s AND control_id=%s",
                        (new_audit_id, old_ctrl[0]),
                    ).fetchone()
                    if match:
                        new_ctrl_id = match[0]

            db.execute(
                "INSERT INTO grid_non_conformances "
                "(audit_id, control_id, title, description, severity, "
                " assigned_to, root_cause, corrective_action, "
                " preventive_action, due_date, cap_status, source_nc_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    new_audit_id,
                    new_ctrl_id,
                    nc["title"],
                    nc["description"],
                    nc["severity"],
                    nc["assigned_to"],
                    nc["root_cause"],
                    nc["corrective_action"],
                    nc["preventive_action"],
                    nc["due_date"],
                    "Open",  # Reset CAP status in follow-up
                    nc["id"],  # Link back to source NC
                ),
            )
            count += 1

        db.commit()
        return count
    finally:
        db.close()


def get_audit_lineage(audit_id):
    """
    Return the full chain of audits: ancestors up to root, plus children.
    Returns {"ancestors": [...], "current": {...}, "children": [...]}.
    """
    db = get_db()
    try:
        # Walk up ancestors
        ancestors = []
        current = None
        current_id = audit_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            row = db.execute(
                "SELECT a.id, a.name, a.status, a.audit_date, a.parent_audit_id, "
                "f.name AS framework_name "
                "FROM grid_audits a "
                "LEFT JOIN grid_frameworks f ON a.framework_id=f.id "
                "WHERE a.id=%s",
                (current_id,),
            ).fetchone()
            if not row:
                break
            rec = dict(row)
            if current_id == audit_id:
                current = rec
                current_id = rec.get("parent_audit_id")
                continue
            ancestors.insert(0, rec)
            current_id = rec.get("parent_audit_id")

        # Get direct children
        children = _dicts(db.execute(
            "SELECT a.id, a.name, a.status, a.audit_date, "
            "f.name AS framework_name "
            "FROM grid_audits a "
            "LEFT JOIN grid_frameworks f ON a.framework_id=f.id "
            "WHERE a.parent_audit_id=%s "
            "ORDER BY a.created_at DESC",
            (audit_id,),
        ).fetchall())

        return {
            "ancestors": ancestors,
            "current": current,
            "children": children or [],
        }
    finally:
        db.close()


def get_cross_cycle_comparison(audit_id):
    """
    Compare NC status between this audit and its parent.
    Returns a list of NC pairs: source (parent) NC + current (child) NC state.
    Also lists NCs that are new in this cycle (no source_nc_id).
    """
    db = get_db()
    try:
        audit = db.execute(
            "SELECT parent_audit_id FROM grid_audits WHERE id=%s",
            (audit_id,),
        ).fetchone()
        if not audit or not audit["parent_audit_id"]:
            # No parent — return just this audit's NCs as "new"
            ncs = _dicts(db.execute(
                "SELECT nc.*, u.full_name AS assigned_name, "
                "c.control_id AS ctrl_ref, c.name AS control_name "
                "FROM grid_non_conformances nc "
                "LEFT JOIN users u ON nc.assigned_to=u.id "
                "LEFT JOIN grid_controls c ON nc.control_id=c.id "
                "WHERE nc.audit_id=%s ORDER BY nc.created_at",
                (audit_id,),
            ).fetchall())
            return {
                "parent_audit_id": None,
                "carried_forward": [],
                "new_in_cycle": ncs,
                "resolved_in_parent": [],
            }

        parent_id = audit["parent_audit_id"]

        # NCs in this audit that were carried forward (have source_nc_id)
        carried = _dicts(db.execute(
            "SELECT cur.id, cur.title, cur.severity, cur.status, "
            "cur.cap_status, cur.assigned_to, cur.source_nc_id, "
            "u.full_name AS assigned_name, "
            "c.control_id AS ctrl_ref, c.name AS control_name, "
            "src.status AS source_status, src.cap_status AS source_cap_status, "
            "src.closed_at AS source_closed_at "
            "FROM grid_non_conformances cur "
            "LEFT JOIN users u ON cur.assigned_to=u.id "
            "LEFT JOIN grid_controls c ON cur.control_id=c.id "
            "LEFT JOIN grid_non_conformances src ON cur.source_nc_id=src.id "
            "WHERE cur.audit_id=%s AND cur.source_nc_id IS NOT NULL "
            "ORDER BY cur.created_at",
            (audit_id,),
        ).fetchall())

        # NCs new in this cycle (no source)
        new_ncs = _dicts(db.execute(
            "SELECT nc.*, u.full_name AS assigned_name, "
            "c.control_id AS ctrl_ref, c.name AS control_name "
            "FROM grid_non_conformances nc "
            "LEFT JOIN users u ON nc.assigned_to=u.id "
            "LEFT JOIN grid_controls c ON nc.control_id=c.id "
            "WHERE nc.audit_id=%s AND nc.source_nc_id IS NULL "
            "ORDER BY nc.created_at",
            (audit_id,),
        ).fetchall())

        # NCs from parent that were closed (not carried forward)
        carried_ids = {c["source_nc_id"] for c in carried if c.get("source_nc_id")}
        resolved = _dicts(db.execute(
            "SELECT nc.id, nc.title, nc.severity, nc.status, "
            "nc.cap_status, nc.closed_at, "
            "u.full_name AS assigned_name, "
            "c.control_id AS ctrl_ref, c.name AS control_name "
            "FROM grid_non_conformances nc "
            "LEFT JOIN users u ON nc.assigned_to=u.id "
            "LEFT JOIN grid_controls c ON nc.control_id=c.id "
            "WHERE nc.audit_id=%s AND (nc.status='closed' OR nc.cap_status='Closed') "
            "ORDER BY nc.closed_at DESC",
            (parent_id,),
        ).fetchall())

        return {
            "parent_audit_id": parent_id,
            "carried_forward": carried,
            "new_in_cycle": new_ncs,
            "resolved_in_parent": resolved,
        }
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# Audit sign-off & locking
# ═════════════════════════════════════════════════════════════════════════════

_SIGNOFF_ROLES = ["lead", "reviewer"]


def get_signoffs(audit_id):
    """Return all sign-offs for an audit."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT s.*, u.full_name AS user_name "
            "FROM grid_audit_signoffs s "
            "LEFT JOIN users u ON s.user_id=u.id "
            "WHERE s.audit_id=%s ORDER BY s.signed_at",
            (audit_id,),
        ).fetchall()
        return _dicts(rows)
    finally:
        db.close()


def sign_off_audit(audit_id, user_id, role, comment=None):
    """
    Record a sign-off for the given role.
    role must be 'lead' or 'reviewer'.
    Lead must sign before reviewer can sign.
    Returns the sign-off id, or None if role invalid / prerequisite missing.
    """
    if role not in _SIGNOFF_ROLES:
        return None
    db = get_db()
    try:
        # Reviewer cannot sign until lead has signed
        if role == "reviewer":
            lead = db.execute(
                "SELECT id FROM grid_audit_signoffs WHERE audit_id=%s AND role='lead'",
                (audit_id,),
            ).fetchone()
            if not lead:
                return None  # Lead hasn't signed yet

        cur = insert_returning_id(db,
            "INSERT INTO grid_audit_signoffs "
            "(audit_id, role, user_id, comment, signed_at) "
            "VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP) "
            "ON CONFLICT (audit_id, role) DO UPDATE SET "
            "user_id=excluded.user_id, comment=excluded.comment, signed_at=CURRENT_TIMESTAMP",
            (audit_id, role, user_id, comment),
        )
        db.commit()
        return cur
    finally:
        db.close()


def revoke_signoff(audit_id, role):
    """Remove a sign-off. Also removes downstream sign-offs (revoking lead removes reviewer)."""
    db = get_db()
    try:
        if role == "lead":
            # Revoking lead also revokes reviewer
            db.execute(
                "DELETE FROM grid_audit_signoffs WHERE audit_id=%s AND role IN ('lead','reviewer')",
                (audit_id,),
            )
        else:
            db.execute(
                "DELETE FROM grid_audit_signoffs WHERE audit_id=%s AND role=%s",
                (audit_id, role),
            )
        # Also unlock if revoking sign-offs
        db.execute(
            "UPDATE grid_audits SET is_locked=0, locked_at=NULL, locked_by=NULL WHERE id=%s",
            (audit_id,),
        )
        db.commit()
    finally:
        db.close()


def lock_audit(audit_id, user_id):
    """
    Lock the audit (requires both lead and reviewer sign-offs).
    Returns True on success, None if prerequisites not met.
    """
    db = get_db()
    try:
        signoffs = db.execute(
            "SELECT role FROM grid_audit_signoffs WHERE audit_id=%s",
            (audit_id,),
        ).fetchall()
        roles = {r[0] for r in signoffs}
        if "lead" not in roles or "reviewer" not in roles:
            return None  # Both must sign before locking

        db.execute(
            "UPDATE grid_audits SET is_locked=1, locked_at=CURRENT_TIMESTAMP, "
            "locked_by=%s, status='Completed' WHERE id=%s",
            (user_id, audit_id),
        )
        db.commit()
        return True
    finally:
        db.close()


def unlock_audit(audit_id):
    """Unlock an audit (admin action). Also clears all sign-offs."""
    db = get_db()
    try:
        db.execute(
            "UPDATE grid_audits SET is_locked=0, locked_at=NULL, locked_by=NULL WHERE id=%s",
            (audit_id,),
        )
        db.execute("DELETE FROM grid_audit_signoffs WHERE audit_id=%s", (audit_id,))
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# Audit program dashboard data
# ═════════════════════════════════════════════════════════════════════════════

def get_program_dashboard():
    """
    Multi-audit program overview: overall compliance posture,
    per-audit stats, NC summary, trend data.
    """
    db = get_db()
    try:
        # Per-audit stats
        audits = _dicts(db.execute("""
            SELECT a.id, a.name, a.status, a.audit_date, a.is_locked,
                   a.parent_audit_id,
                   f.name AS framework_name, f.color AS framework_color,
                   u.full_name AS lead_name,
                   COUNT(c.id) AS total_controls,
                   SUM(CASE WHEN c.status='Complete' THEN 1 ELSE 0 END) AS complete_controls,
                   SUM(CASE WHEN c.due_date < CURRENT_DATE AND c.status!='Complete'
                       THEN 1 ELSE 0 END) AS overdue_controls
            FROM grid_audits a
            LEFT JOIN grid_frameworks f ON a.framework_id=f.id
            LEFT JOIN users u ON a.lead_id=u.id
            LEFT JOIN grid_controls c ON c.audit_id=a.id
            GROUP BY a.id ORDER BY a.created_at DESC
        """).fetchall())

        for a in audits:
            t = a.get("total_controls") or 0
            c = a.get("complete_controls") or 0
            a["completion_pct"] = round(c / t * 100) if t > 0 else 0

        # Aggregate totals
        total_controls = sum(a.get("total_controls", 0) for a in audits)
        complete_controls = sum(a.get("complete_controls", 0) for a in audits)
        overdue_controls = sum(a.get("overdue_controls", 0) for a in audits)
        overall_pct = round(complete_controls / total_controls * 100) if total_controls else 0

        # NC summary across all audits
        nc_stats = _dict(db.execute("""
            SELECT COUNT(*) AS total_ncs,
                   SUM(CASE WHEN status='closed' OR cap_status='Closed' THEN 1 ELSE 0 END) AS closed_ncs,
                   SUM(CASE WHEN severity IN ('critical','major') AND status!='closed'
                       AND cap_status NOT IN ('Closed','Verification') THEN 1 ELSE 0 END) AS critical_open
            FROM grid_non_conformances
        """).fetchone()) or {}

        # Compliance score trend (last 30 snapshots per audit)
        trends = _dicts(db.execute("""
            SELECT cs.audit_id, a.name AS audit_name, cs.score, cs.created_at
            FROM grid_compliance_scores cs
            JOIN grid_audits a ON cs.audit_id=a.id
            ORDER BY cs.created_at DESC LIMIT 180
        """).fetchall())

        return {
            "total_audits": len(audits),
            "total_controls": total_controls,
            "complete_controls": complete_controls,
            "overdue_controls": overdue_controls,
            "overall_pct": overall_pct,
            "nc_total": nc_stats.get("total_ncs", 0),
            "nc_closed": nc_stats.get("closed_ncs", 0),
            "nc_critical_open": nc_stats.get("critical_open", 0),
            "audits": audits,
            "score_trends": trends,
        }
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# ARIA policy integration
# ═════════════════════════════════════════════════════════════════════════════

def list_aria_policies(framework_name=None, control_ref=None, status="Approved"):
    """
    Fetch approved ARIA documents available for linking as GRID evidence.
    Optionally filter by framework name and control ref.
    """
    db = get_db()
    try:
        q = (
            "SELECT id, doc_id, framework, control_ref, title, doc_type, "
            "version, status, owner, effective_date, created_at "
            "FROM aria_documents WHERE 1=1"
        )
        params = []
        if status:
            q += " AND status=%s"
            params.append(status)
        if framework_name:
            q += " AND framework=%s"
            params.append(framework_name)
        if control_ref:
            q += " AND control_ref=%s"
            params.append(control_ref)
        q += " ORDER BY framework, control_ref, title"
        return _dicts(db.execute(q, params).fetchall())
    finally:
        db.close()


def attach_aria_policy_as_evidence(control_id, aria_doc_id, user_id):
    """
    Create a grid_evidence_file record pointing to an ARIA policy document.
    Returns the evidence file id, or None if the ARIA doc doesn't exist.
    """
    db = get_db()
    try:
        doc = db.execute(
            "SELECT id, title, doc_id, framework, control_ref, version "
            "FROM aria_documents WHERE id=%s",
            (aria_doc_id,),
        ).fetchone()
        if not doc:
            return None

        # Check for duplicate — don't attach same policy twice to same control
        existing = db.execute(
            "SELECT id FROM grid_evidence_files "
            "WHERE control_id=%s AND original_name=%s AND notes LIKE '%aria_doc_id=%'",
            (control_id, doc["title"]),
        ).fetchone()
        if existing:
            return existing[0]  # Already attached

        cur = insert_returning_id(db,
            "INSERT INTO grid_evidence_files "
            "(control_id, filename, original_name, file_path, file_size, "
            " mime_type, uploaded_by, notes, status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                control_id,
                f"aria-policy-{doc['doc_id']}.ref",
                doc["title"],
                f"aria://documents/{aria_doc_id}",  # Virtual path — ARIA reference
                0,
                "application/x-aria-policy",
                user_id,
                f"ARIA policy document (aria_doc_id={aria_doc_id}, "
                f"framework={doc['framework']}, ref={doc['control_ref']}, "
                f"version={doc['version']})",
                "Approved",  # Pre-approved since ARIA already approved it
            ),
        )
        db.commit()
        return cur
    finally:
        db.close()


# ── Policy requests ──────────────────────────────────────────────────────

def create_policy_request(data):
    """Create a policy request from GRID to ARIA."""
    db = get_db()
    try:
        cur = insert_returning_id(db,
            "INSERT INTO grid_policy_requests "
            "(audit_id, control_id, framework_name, control_ref, "
            " title, description, requested_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                data["audit_id"],
                data.get("control_id"),
                data.get("framework_name", ""),
                data.get("control_ref", ""),
                data.get("title", "Policy needed"),
                data.get("description", ""),
                data["requested_by"],
            ),
        )
        db.commit()
        return cur
    finally:
        db.close()


def list_policy_requests(audit_id=None, status=None):
    """List policy requests, optionally by audit and status."""
    db = get_db()
    try:
        q = (
            "SELECT pr.*, u.full_name AS requested_by_name, "
            "a.name AS audit_name, c.control_id AS ctrl_ref, c.name AS control_name "
            "FROM grid_policy_requests pr "
            "LEFT JOIN users u ON pr.requested_by=u.id "
            "LEFT JOIN grid_audits a ON pr.audit_id=a.id "
            "LEFT JOIN grid_controls c ON pr.control_id=c.id "
            "WHERE 1=1"
        )
        params = []
        if audit_id is not None:
            q += " AND pr.audit_id=%s"
            params.append(audit_id)
        if status:
            q += " AND pr.status=%s"
            params.append(status)
        q += " ORDER BY pr.created_at DESC"
        return _dicts(db.execute(q, params).fetchall())
    finally:
        db.close()


def resolve_policy_request(request_id, aria_document_id):
    """Mark a policy request as fulfilled when ARIA publishes the policy."""
    db = get_db()
    try:
        db.execute(
            "UPDATE grid_policy_requests "
            "SET status='fulfilled', aria_document_id=%s, resolved_at=CURRENT_TIMESTAMP "
            "WHERE id=%s",
            (aria_document_id, request_id),
        )
        db.commit()
    finally:
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# Evidence Vault sync — bridge GRID ↔ central vault
# ═════════════════════════════════════════════════════════════════════════════

import hashlib as _hashlib
import logging as _logging
_vault_log = _logging.getLogger("grid.vault_sync")


def sync_grid_evidence_to_vault(grid_evidence_id, db=None):
    """
    Create or update a central evidence_items record for a GRID evidence file.
    Links it to the GRID control via evidence_links.
    Idempotent — skips if already synced (detected via tag).
    """
    own_db = db is None
    if own_db:
        db = get_db()
    try:
        ef = db.execute(
            "SELECT ef.*, c.audit_id, c.control_id AS ctrl_ref, c.name AS control_name, "
            "a.name AS audit_name "
            "FROM grid_evidence_files ef "
            "JOIN grid_controls c ON ef.control_id=c.id "
            "JOIN grid_audits a ON c.audit_id=a.id "
            "WHERE ef.id=%s",
            (grid_evidence_id,),
        ).fetchone()
        if not ef:
            return None

        # Check if already synced
        tag = f"grid_evidence_id={grid_evidence_id}"
        existing = db.execute(
            "SELECT id FROM evidence_items WHERE tags LIKE %s",
            (f"%{tag}%",),
        ).fetchone()
        if existing:
            return existing[0]

        # Compute file hash if file exists on disk
        file_hash = None
        file_path = ef["file_path"] or ""
        if file_path and not file_path.startswith("aria://"):
            from pathlib import Path
            fp = Path(file_path)
            if fp.exists():
                h = _hashlib.sha256()
                with open(fp, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        h.update(chunk)
                file_hash = h.hexdigest()

        # Determine category from mime type
        mime = (ef["mime_type"] or "").lower()
        if "aria-policy" in mime:
            category = "policy"
        elif "pdf" in mime:
            category = "report"
        elif "image" in mime:
            category = "screenshot"
        else:
            category = "general"

        # Build descriptive tags
        tags = f"grid,audit,{tag}"
        if ef.get("ctrl_ref"):
            tags += f",{ef['ctrl_ref']}"

        vault_id = insert_returning_id(db,
            "INSERT INTO evidence_items "
            "(title, description, file_path, file_name, file_size, file_hash, "
            " mime_type, category, tags, status, expiry_date, uploaded_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                ef["original_name"] or ef["filename"],
                f"Uploaded to GRID audit '{ef['audit_name']}', "
                f"control {ef.get('ctrl_ref', '')} ({ef.get('control_name', '')})",
                file_path,
                ef["original_name"] or ef["filename"],
                ef["file_size"] or 0,
                file_hash,
                ef["mime_type"] or "",
                category,
                tags,
                "current",
                ef.get("expires_at"),
                ef.get("uploaded_by"),
            ),
        )

        # Link to the GRID control
        db.execute(
            "INSERT INTO evidence_links "
            "(evidence_id, module, entity_type, entity_id, linked_by) "
            "VALUES (%s,%s,%s,%s,%s)",
            (vault_id, "grid", "control", ef["control_id"], ef.get("uploaded_by")),
        )

        # Also link to the GRID audit
        db.execute(
            "INSERT INTO evidence_links "
            "(evidence_id, module, entity_type, entity_id, linked_by) "
            "VALUES (%s,%s,%s,%s,%s)",
            (vault_id, "grid", "audit", ef["audit_id"], ef.get("uploaded_by")),
        )

        if own_db:
            db.commit()
        _vault_log.info("Synced GRID evidence #%d → vault #%d", grid_evidence_id, vault_id)
        return vault_id
    except Exception as exc:
        _vault_log.warning("sync_grid_evidence_to_vault failed for #%d: %s",
                           grid_evidence_id, exc)
        return None
    finally:
        if own_db:
            db.close()


def list_vault_evidence(category=None, module=None, search=None, limit=100):
    """Browse the central evidence vault with filters — used by GRID's vault picker."""
    db = get_db()
    try:
        q = (
            "SELECT e.*, u.full_name AS uploaded_by_name, "
            "(SELECT COUNT(*) FROM evidence_links el WHERE el.evidence_id=e.id) AS link_count "
            "FROM evidence_items e "
            "LEFT JOIN users u ON e.uploaded_by=u.id "
            "WHERE e.status != 'archived'"
        )
        params = []
        if category:
            q += " AND e.category=%s"
            params.append(category)
        if module:
            q += " AND e.id IN (SELECT evidence_id FROM evidence_links WHERE module=%s)"
            params.append(module)
        if search:
            q += " AND (e.title LIKE %s OR e.tags LIKE %s OR e.description LIKE %s)"
            params.extend([f"%{search}%"] * 3)
        q += " ORDER BY e.updated_at DESC LIMIT %s"
        params.append(limit)
        return _dicts(db.execute(q, params).fetchall())
    finally:
        db.close()


def attach_vault_item_to_grid_control(control_id, vault_evidence_id, user_id):
    """
    Link a central vault evidence item to a GRID control.
    Creates a grid_evidence_files record referencing the vault item,
    and adds an evidence_links entry if not already linked.
    Returns the grid evidence file id.
    """
    db = get_db()
    try:
        # Get vault item
        item = db.execute(
            "SELECT * FROM evidence_items WHERE id=%s AND status != 'archived'",
            (vault_evidence_id,),
        ).fetchone()
        if not item:
            return None

        # Check if already attached to this control
        existing = db.execute(
            "SELECT id FROM grid_evidence_files "
            "WHERE control_id=%s AND notes LIKE %s",
            (control_id, f"%vault_evidence_id={vault_evidence_id}%"),
        ).fetchone()
        if existing:
            return existing[0]

        # Create GRID evidence file pointing to vault item
        grid_eid = insert_returning_id(db,
            "INSERT INTO grid_evidence_files "
            "(control_id, filename, original_name, file_path, file_size, "
            " mime_type, uploaded_by, notes, status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                control_id,
                item["file_name"] or item["file_path"] or "vault-item",
                item["title"],
                item["file_path"] or f"vault://{vault_evidence_id}",
                item["file_size"] or 0,
                item["mime_type"] or "",
                user_id,
                f"From Evidence Vault (vault_evidence_id={vault_evidence_id}, "
                f"category={item['category'] or 'general'})",
                "Approved",  # Vault items are pre-vetted
            ),
        )

        # Ensure vault link exists to this control
        existing_link = db.execute(
            "SELECT id FROM evidence_links "
            "WHERE evidence_id=%s AND module='grid' AND entity_type='control' AND entity_id=%s",
            (vault_evidence_id, control_id),
        ).fetchone()
        if not existing_link:
            db.execute(
                "INSERT INTO evidence_links "
                "(evidence_id, module, entity_type, entity_id, linked_by) "
                "VALUES (%s,%s,%s,%s,%s)",
                (vault_evidence_id, "grid", "control", control_id, user_id),
            )

        db.commit()
        _auto_status_control(db, control_id)
        return grid_eid
    finally:
        db.close()
