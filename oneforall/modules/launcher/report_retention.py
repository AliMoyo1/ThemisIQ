"""Tenant-scoped deletion of saved report content after an explicit retention date."""

import logging

from core.timeutils import utcnow
from database import get_db_background

log = logging.getLogger("oneforall.report_retention")


def purge_due(org_id: int) -> int:
    """Purge at most 100 due runs per tenant pass. Leave metadata and a hash tombstone."""
    db = get_db_background()
    done = 0
    try:
        today = utcnow().date().isoformat()
        rows = db.execute(
            "SELECT r.run_id, rr.snapshot_hash FROM report_run_retention r "
            "JOIN report_runs rr ON rr.id=r.run_id "
            "WHERE r.delete_after IS NOT NULL AND r.delete_after<=%s "
            "AND r.hold_reason IS NULL AND r.purged_at IS NULL "
            "AND rr.status!='purged' AND (rr.file_path IS NULL OR rr.file_path='') "
            "ORDER BY r.delete_after,r.run_id LIMIT 100", (today,),
        ).fetchall()
        for row in rows:
            run_id = row["run_id"]
            changed = db.execute(
                "UPDATE report_runs SET result_json=NULL,snapshot_hash=NULL,file_path=NULL,status='purged' "
                "WHERE id=%s AND status!='purged'", (run_id,),
            ).rowcount
            if changed != 1:
                continue
            db.execute("DELETE FROM report_run_notes WHERE run_id=%s", (run_id,))
            db.execute("DELETE FROM report_run_shares WHERE run_id=%s", (run_id,))
            db.execute("DELETE FROM report_run_signoffs WHERE run_id=%s", (run_id,))
            db.execute(
                "UPDATE report_run_retention SET purged_at=CURRENT_TIMESTAMP,purged_hash=%s WHERE run_id=%s",
                (row["snapshot_hash"], run_id),
            )
            db.commit()
            done += 1
        if done:
            log.info("Purged %s expired saved reports in organization %s", done, org_id)
        return done
    except Exception:
        db.rollback()
        log.exception("Saved report retention pass failed for organization %s", org_id)
        return done
    finally:
        db.close()
