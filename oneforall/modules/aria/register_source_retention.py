"""Retention and legal holds for confirmed document register source workbooks.

A confirmed workbook is kept in the Evidence Vault as the exact bytes its register claims came from. Each customer
chooses how long it keeps them; until it does, nothing is deleted. No legal period is assumed. A workbook can also carry
its own deletion date and a legal hold, and a hold always wins over a date.

When a date passes without a hold, the daily pass removes the file only. The Vault record, its hash and the claims stay,
so a claim can still say which workbook it came from and that the file was removed under retention.
"""
import logging
import os
from datetime import date, timedelta
from pathlib import Path

from config import settings
from core.timeutils import utcnow
from database import get_db_background

log = logging.getLogger("oneforall.register_source_retention")

POLICY_KEY = "registers.source_retention_days"
MIN_DAYS, MAX_DAYS = 30, 3650
MANAGE_CAPABILITY = "platform.report.retention.manage"  # the people who already own the tenant's retention choices


def policy_days(db) -> "int | None":
    """The tenant's chosen period, or None when it has not chosen one (workbooks are then kept)."""
    row = db.execute("SELECT value FROM settings WHERE key=%s", (POLICY_KEY,)).fetchone()
    if row is None or row["value"] in (None, ""):
        return None
    days = int(row["value"])
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise ValueError("The tenant source workbook retention policy is outside its allowed range")
    return days


def save_policy(db, days: "int | None") -> None:
    if days is None:
        db.execute("DELETE FROM settings WHERE key=%s", (POLICY_KEY,))
    else:
        db.execute("INSERT INTO settings (key,value) VALUES (%s,%s) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",
                   (POLICY_KEY, str(days)))


def is_source(db, evidence_id: int) -> bool:
    return db.execute("SELECT 1 FROM aria_document_register_batches WHERE source_evidence_id=%s LIMIT 1",
                      (evidence_id,)).fetchone() is not None


def on_filed(db, evidence_id: int, user_id: int) -> None:
    """Start the retention record for a newly filed workbook, from the tenant's period if it has one."""
    if db.execute("SELECT 1 FROM register_source_retention WHERE evidence_id=%s", (evidence_id,)).fetchone():
        return
    days = policy_days(db)
    delete_after = (utcnow().date() + timedelta(days=days)).isoformat() if days else None
    db.execute("INSERT INTO register_source_retention (evidence_id,delete_after,set_by) VALUES (%s,%s,%s)",
               (evidence_id, delete_after, user_id))


def get(db, evidence_id: int) -> dict:
    row = db.execute("SELECT delete_after,hold_reason,set_by,set_at,purged_at,purged_hash "
                     "FROM register_source_retention WHERE evidence_id=%s", (evidence_id,)).fetchone()
    if not row:
        return {"delete_after": None, "hold_reason": None, "purged_at": None, "purged_hash": None}
    found = dict(row)
    found["delete_after"] = str(found["delete_after"])[:10] if found["delete_after"] else None
    found["purged_at"] = str(found["purged_at"]) if found["purged_at"] else None
    found["set_at"] = str(found["set_at"]) if found["set_at"] else None
    return found


def parse_change(body) -> tuple:
    """(delete_after or None, hold_reason or None, reason). Raises ValueError with a sentence that can be shown."""
    if not isinstance(body, dict):
        raise ValueError("Send the retention change as an object.")
    raw_date = body.get("delete_after")
    delete_after = None
    if raw_date not in (None, ""):
        if not isinstance(raw_date, str):
            raise ValueError("The deletion date must be a date in YYYY-MM-DD format.")
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError:
            raise ValueError("The deletion date must be a real date in YYYY-MM-DD format.") from None
        if parsed <= utcnow().date():
            raise ValueError("Choose a deletion date after today.")
        delete_after = parsed.isoformat()
    hold = body.get("hold_reason")
    if hold is not None and not isinstance(hold, str):
        raise ValueError("The hold reason must be text.")
    hold = (hold or "").strip() or None
    if hold is not None and not 10 <= len(hold) <= 500:
        raise ValueError("A hold reason must be 10 to 500 characters.")
    reason = body.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not 10 <= len(reason) <= 500:
        raise ValueError("Record why the retention changed, in 10 to 500 characters.")
    return delete_after, hold, reason


def set_retention(db, evidence_id: int, user_id: int, delete_after, hold_reason) -> dict:
    """Replace the workbook's date and hold. The row is locked so a purge already under way cannot ignore a new hold."""
    lock = " FOR UPDATE" if settings.is_postgres() else ""
    row = db.execute("SELECT purged_at FROM register_source_retention WHERE evidence_id=%s" + lock,
                     (evidence_id,)).fetchone()
    if row and row["purged_at"]:
        raise ValueError("This workbook's file was already removed under retention.")
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if row:
        db.execute("UPDATE register_source_retention SET delete_after=%s,hold_reason=%s,set_by=%s,set_at=%s "
                   "WHERE evidence_id=%s AND purged_at IS NULL", (delete_after, hold_reason, user_id, now, evidence_id))
    else:
        db.execute("INSERT INTO register_source_retention (evidence_id,delete_after,hold_reason,set_by,set_at) "
                   "VALUES (%s,%s,%s,%s,%s)", (evidence_id, delete_after, hold_reason, user_id, now))
    return get(db, evidence_id)


def purge_due(org_id: int) -> int:
    """Remove the files of due, unheld workbooks in this tenant, at most 100 per pass. Keep record, hash and claims."""
    root = Path(os.getenv("EVIDENCE_DIR", "data/evidence")).resolve()
    db = get_db_background()
    done = 0
    try:
        today = utcnow().date().isoformat()
        due = db.execute(
            "SELECT r.evidence_id FROM register_source_retention r JOIN evidence_items e ON e.id=r.evidence_id "
            "WHERE r.delete_after IS NOT NULL AND r.delete_after<=%s AND r.hold_reason IS NULL "
            "AND r.purged_at IS NULL AND e.org_id=%s ORDER BY r.delete_after,r.evidence_id LIMIT 100",
            (today, org_id)).fetchall()
        for row in due:
            evidence_id = row["evidence_id"]
            # Serialize with a hold being set: on PostgreSQL the row lock makes a hold set during the scan win.
            locked = db.execute(
                "SELECT delete_after,hold_reason,purged_at FROM register_source_retention WHERE evidence_id=%s"
                + (" FOR UPDATE" if settings.is_postgres() else ""), (evidence_id,)).fetchone()
            if (not locked or locked["hold_reason"] or locked["purged_at"] or not locked["delete_after"]
                    or str(locked["delete_after"])[:10] > today):
                db.rollback()
                continue
            item = db.execute("SELECT file_path,file_hash FROM evidence_items WHERE id=%s AND org_id=%s",
                              (evidence_id, org_id)).fetchone()
            if not item:
                db.rollback()
                continue
            db.execute("UPDATE evidence_items SET file_path=NULL,status='archived',updated_at=CURRENT_TIMESTAMP "
                       "WHERE id=%s", (evidence_id,))
            db.execute("UPDATE register_source_retention SET purged_at=CURRENT_TIMESTAMP,purged_hash=%s "
                       "WHERE evidence_id=%s", (item["file_hash"], evidence_id))
            db.commit()
            if item["file_path"]:
                path = (root / item["file_path"]).resolve()
                if path.is_relative_to(root):
                    path.unlink(missing_ok=True)
            done += 1
        if done:
            log.info("Removed %s expired source workbook files in organization %s", done, org_id)
        return done
    except Exception:
        db.rollback()
        log.exception("Source workbook retention pass failed for organization %s", org_id)
        return done
    finally:
        db.close()
