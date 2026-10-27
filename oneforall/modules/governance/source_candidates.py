"""Specialist-gated promotion of a captured source change into the inbox.

The candidate is a human interpretation of a verified source capture. Neither
the watcher nor an AI draft can insert a regulatory update or a drift task.
"""
from __future__ import annotations

from core.source_registry import SOURCES
from core.timeutils import utcnow
from database import get_db, insert_returning_id
from modules.sentinel.living_law import capture_detail


def _text(value, limit: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected text")
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise ValueError("Required text is empty or too long")
    return value


def propose(org_id: int, capture_id: int, author_id: int, data: dict) -> int:
    detail = capture_detail(org_id, capture_id)
    if not detail["hash_verified"] or not detail["is_latest"] or detail["review_state"] != "approved":
        raise ValueError("The latest capture must be approved and intact")
    if not detail["previous_capture_id"] or not detail.get("change_excerpt"):
        raise ValueError("A baseline cannot establish a source change")
    source = SOURCES[detail["source_key"]]
    framework = _text(data.get("framework_name"), 120, True)
    if framework not in source.frameworks:
        raise ValueError("This framework is not mapped to the captured source")
    title = _text(data.get("title"), 240, True)
    summary = _text(data.get("summary", ""), 3000)
    refs = _text(data.get("affected_refs", ""), 1000)
    db = get_db()
    try:
        found = db.execute("SELECT id FROM regulatory_source_candidates "
                           "WHERE org_id=%s AND capture_id=%s AND framework_name=%s",
                           (org_id, capture_id, framework)).fetchone()
        if found:
            return found["id"]
        new_id = insert_returning_id(db,
            "INSERT INTO regulatory_source_candidates "
            "(org_id,capture_id,source_key,source_text_sha256,framework_name,title,summary,affected_refs,created_by,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (org_id, capture_id, source.key, detail["text_sha256"], framework,
             title, summary or None, refs or None, author_id, utcnow().isoformat()))
        db.commit()
        return new_id
    finally:
        db.close()


def list_pending(org_id: int) -> list[dict]:
    db = get_db()
    try:
        return [dict(r) for r in db.execute("SELECT id,capture_id,source_key,framework_name,title,summary,"
            "affected_refs,created_by,created_at FROM regulatory_source_candidates "
            "WHERE org_id=%s AND review_state='pending' ORDER BY id DESC", (org_id,)).fetchall()]
    finally:
        db.close()


def decide(org_id: int, candidate_id: int, reviewer_id: int, decision: str, note: str) -> dict:
    if decision not in {"approved", "rejected"}:
        raise ValueError("Choose approve or reject")
    note = _text(note, 2000, True)
    db = get_db()
    try:
        row = db.execute("SELECT * FROM regulatory_source_candidates "
                         "WHERE id=%s AND org_id=%s AND review_state='pending'",
                         (candidate_id, org_id)).fetchone()
        if not row:
            raise LookupError("Candidate not found")
        if row["created_by"] == reviewer_id:
            raise ValueError("An independent specialist must decide")
        detail = capture_detail(org_id, row["capture_id"])
        if (not detail["hash_verified"] or not detail["is_latest"] or
                detail["review_state"] != "approved" or
                detail["text_sha256"] != row["source_text_sha256"]):
            raise ValueError("The source capture changed or cannot be verified")
        now = utcnow().isoformat()
        update_id = None
        if decision == "approved":
            update_id = insert_returning_id(db,
                "INSERT INTO regulatory_updates "
                "(framework_name,title,summary,source_url,affected_refs,severity,status,created_by,created_at,updated_at,"
                "source_capture_id,source_text_sha256) VALUES (%s,%s,%s,%s,%s,'info','open',%s,%s,%s,%s,%s)",
                (row["framework_name"], row["title"], row["summary"], detail["source_url"],
                 row["affected_refs"], reviewer_id, now, now, detail["id"], detail["text_sha256"]))
        changed = db.execute("UPDATE regulatory_source_candidates SET review_state=%s,reviewed_by=%s,"
            "reviewed_at=%s,review_note=%s,update_id=%s WHERE id=%s AND org_id=%s AND review_state='pending'",
            (decision, reviewer_id, now, note, update_id, candidate_id, org_id)).rowcount
        if changed != 1:
            raise LookupError("Candidate not found")
        drift = {"updates": 0, "tasks": 0}
        if update_id is not None:
            from modules.governance.data_service import run_drift_check
            drift = run_drift_check(db, update_id)
        else:
            db.commit()
        return {"decision": decision, "update_id": update_id, "drift": drift}
    finally:
        db.close()
