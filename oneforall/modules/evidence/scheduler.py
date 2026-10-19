"""
Evidence Vault: background scheduler.

Jobs:
  Job 1  Evidence expiry monitor  (daily 09:00 UTC)
         - Alerts 30 days, 7 days, and 1 day before evidence expiry_date
         - Creates task_board items for evidence owners
         - Sends admin notifications
         - Asks the email outbox to tell the uploader of each item that is about to expire
         - Idempotent: checks for existing open tasks before creating duplicates

The job visits every organization in turn. A message carries the item reference, the date and a link, never the title of
the item, and is sent by the outbox (core/email_outbox.py), which checks at that moment that the uploader is active, may
open the item and that it is still current.
"""
from __future__ import annotations

import logging
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from database import get_db_background as get_db, sql_date_offset, sql_current_date, try_acquire_scheduler_lock, list_active_tenants  # scheduler: fail-fast, never block UI
from config import settings
from core import email_outbox as outbox
from core import email_templates as templates
from core.best_effort import swallowed
from core.timeutils import utcnow

log = logging.getLogger("evidence.scheduler")
TZ = "UTC"

_scheduler: BackgroundScheduler | None = None


def _index_due() -> None:
    """One small cross-worker batch, with a short lease and per-tenant context."""
    lock_db = get_db()
    try:
        acquired = try_acquire_scheduler_lock(lock_db, "evidence_text_index", 290)
    finally:
        lock_db.close()
    if not acquired:
        return
    from modules.evidence.indexer import index_batch

    remaining = 12
    tenants = sorted(list_active_tenants())
    if not settings.is_postgres():
        tenants = tenants[:1]
    if not tenants:
        tenants = [(None, None)]
    pivot = int(utcnow().timestamp() // 300) % len(tenants)
    tenants = tenants[pivot:] + tenants[:pivot]

    def visit(org_id):
        nonlocal remaining
        if remaining <= 0:
            return 0
        count = index_batch(org_id if settings.is_postgres() else None,
                            limit=min(remaining, 3 if settings.is_postgres() else 12))
        remaining -= count
        return count

    outbox.for_each_tenant(visit, "Evidence text indexing", tenants=tenants)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _notify_admins(db, title: str, message: str) -> None:
    try:
        rows = db.execute(
            "SELECT DISTINCT u.id FROM users u "
            "JOIN user_roles ur ON u.id = ur.user_id "
            "WHERE ur.role_key IN ('super_admin', 'admin', 'compliance_mgr') "
            "AND u.is_active = 1"
        ).fetchall()
        for r in rows:
            db.execute(
                "INSERT INTO notifications (user_id, module, title, message, link) "
                "VALUES (%s, 'evidence', %s, %s, '/evidence/')",
                (r[0], title, message),
            )
    except Exception as e:
        log.warning("_notify_admins failed: %s", e)


def _task_exists(db, evidence_id: int, days_label: str) -> bool:
    try:
        row = db.execute(
            "SELECT id FROM task_board WHERE module='evidence' AND entity_type='evidence_item' "
            "AND entity_id=%s AND status!='done' AND title LIKE %s",
            (evidence_id, f"%EXPIRY%{days_label}%"),
        ).fetchone()
        return row is not None
    except Exception:
        swallowed("_task_exists (task_board)")
        return False


def enqueue_expiry_messages(db, org_id, today=None) -> int:
    """Ask the outbox to tell the owner of every current item that expires within 30 days (the uploader when a file
    has no owner).

    One message per item, owner, expiry date and bucket (30, 7 or 1 days left): a day the job did not run never loses a
    threshold, a repeated run asks for the message that exists, and a renewed expiry date is a new reminder. The GRID job
    that used to mail the same people asks through this function, so a person reached by both is told once."""
    today = today or utcnow().date()
    rows = db.execute(
        "SELECT e.id, e.expiry_date, COALESCE(e.owner_user_id, e.uploaded_by) AS owner_id FROM evidence_items e "
        "WHERE e.status = 'current' AND e.expiry_date IS NOT NULL "
        "AND COALESCE(e.owner_user_id, e.uploaded_by) IS NOT NULL "
        f"AND e.expiry_date >= {sql_current_date()} AND e.expiry_date <= {sql_date_offset('+30 days')}"
    ).fetchall()
    asked = 0
    for ev in rows:
        due = templates.iso_or_none(ev["expiry_date"])
        if not due:
            continue
        days_left = (date.fromisoformat(due) - today).days
        bucket = 1 if days_left <= 1 else (7 if days_left <= 7 else 30)
        if outbox.enqueue_safely(
                db, "evidence.renew", recipient_user_id=ev["owner_id"], org_id=org_id,
                route=f"/evidence/?open=item:{ev['id']}", fields={"reference": f"EV-{ev['id']}", "due": due},
                source=("evidence", "item", ev["id"]), purpose="expiry", threshold=f"d{bucket}:{due}"):
            asked += 1
    return asked


# ─────────────────────────────────────────────────────────────────────────────
# Job: Evidence Expiry Check
# ─────────────────────────────────────────────────────────────────────────────

def _expiry_check() -> None:
    """
    Daily: create tasks and notifications for evidence expiring in 30, 7, and 1 days.
    Idempotent: won't duplicate if task already exists for that item + threshold.
    """
    log.info("Evidence: running expiry check")
    outbox.for_each_tenant(_expiry_check_in, "Evidence expiry check")


def _expiry_check_in(org_id: int) -> None:
    db = get_db()
    try:
        thresholds = [
            (1,  "TOMORROW",  "critical"),
            (7,  "7 days",    "high"),
            (30, "30 days",   "medium"),
        ]
        total_created = 0

        for days, label, priority in thresholds:
            rows = db.execute(
                "SELECT e.id, e.title, e.category, e.expiry_date "
                "FROM evidence_items e "
                "WHERE e.status = 'current' "
                f"  AND e.expiry_date = {sql_date_offset(f'+{days} days')} "
                "ORDER BY e.title",
            ).fetchall()

            for ev in rows:
                eid   = ev["id"]
                title = ev["title"] or f"Evidence #{eid}"
                exp   = ev["expiry_date"]

                if _task_exists(db, eid, label):
                    continue  # Already notified at this threshold

                # Create task
                db.execute(
                    "INSERT INTO task_board "
                    "(title, description, module, entity_type, entity_id, priority, status) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        f"EVIDENCE EXPIRY ({label}): {title}",
                        f"Evidence item '{title}' (id={eid}, category={ev['category']}) "
                        f"expires on {exp}. Review and renew or archive this evidence "
                        f"to maintain compliance record integrity.",
                        "evidence", "evidence_item", eid, priority, "todo",
                    ),
                )
                total_created += 1

        # The uploader is told by email through the outbox, once per item, expiry date and bucket
        mails = enqueue_expiry_messages(db, org_id)

        if total_created > 0:
            _notify_admins(
                db,
                f"Evidence Vault: {total_created} item(s) expiring soon",
                f"{total_created} evidence items are approaching their expiry date. "
                f"Check the Task Board for details.",
            )

        db.commit()
        log.info("Evidence expiry check: %d task(s) created, %d message(s) asked for", total_created, mails)

        # T1.3: recompute effectiveness for controls that have expiring evidence
        try:
            from modules.governance.effectiveness import recompute_controls_by_ids
            ctrl_rows = db.execute(
                "SELECT DISTINCT el.entity_id FROM evidence_links el "
                "JOIN evidence_items ei ON ei.id = el.evidence_id "
                "WHERE el.entity_type = 'canonical_control' "
                "AND ei.status = 'current' "
                f"AND ei.expiry_date <= {sql_date_offset('+30 days')}"
            ).fetchall()
            if ctrl_rows:
                cids = [r[0] for r in ctrl_rows]
                count = recompute_controls_by_ids(db, cids)
                db.commit()
                log.info("Evidence scheduler: recomputed %d control score(s) after expiry check", count)
        except Exception as eff_exc:
            log.warning("Evidence scheduler: effectiveness recompute failed: %s", eff_exc)

        # PLAN-13: nightly compliance drift detection
        try:
            from modules.governance.data_service import run_drift_check
            res = run_drift_check(db)
            log.info("Drift check: %s updates, %s tasks", res["updates"], res["tasks"])
        except Exception as drift_exc:
            log.warning("Drift check failed: %s", drift_exc)
    except Exception as e:
        log.warning("Evidence expiry check failed in organization %s: %s", org_id, e)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler start / stop
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone=TZ)

    _scheduler.add_job(
        _expiry_check,
        CronTrigger(hour=9, minute=0, timezone=TZ),
        id="evidence_expiry",
        replace_existing=True,
        misfire_grace_time=300,
    )
    from modules.evidence.indexer import indexing_enabled
    if indexing_enabled():
        _scheduler.add_job(
            _index_due, IntervalTrigger(minutes=5), id="evidence_text_index",
            replace_existing=True, max_instances=1, misfire_grace_time=30,
        )

    _scheduler.start()
    log.info("Evidence scheduler started: expiry check daily; text indexing %s",
             "enabled every five minutes" if indexing_enabled() else "disabled")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Evidence scheduler stopped")
