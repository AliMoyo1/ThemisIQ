"""
Evidence Vault — Background scheduler.

Jobs:
  Job 1  Evidence expiry monitor  (daily 09:00 UTC)
         - Alerts 30 days, 7 days, and 1 day before evidence expiry_date
         - Creates task_board items for evidence owners
         - Sends admin notifications
         - Idempotent: checks for existing open tasks before creating duplicates
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db_background as get_db, sql_date_offset  # scheduler: fail-fast, never block UI
from core.email import send_email as _core_send_email

log = logging.getLogger("evidence.scheduler")
TZ = "UTC"

_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _send(*, to: str, subject: str, body_html: str) -> bool:
    """Thin wrapper around core.email.send_email for backward compatibility."""
    result = _core_send_email(to=to, subject=subject, body_html=body_html)
    return result.get("ok", False)


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
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Job — Evidence Expiry Check
# ─────────────────────────────────────────────────────────────────────────────

def _expiry_check() -> None:
    """
    Daily: create tasks and notifications for evidence expiring in 30, 7, and 1 days.
    Idempotent — won't duplicate if task already exists for that item + threshold.
    """
    log.info("Evidence: running expiry check")
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
                "SELECT e.id, e.title, e.category, e.expiry_date, "
                "       u.email AS owner_email, u.full_name AS owner_name "
                "FROM evidence_items e "
                "LEFT JOIN users u ON e.uploaded_by = u.id "
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

                # Email owner if available
                if ev.get("owner_email"):
                    _send(
                        to=ev["owner_email"],
                        subject=f"[ThemisIQ] Evidence expiring {label}: {title}",
                        body_html=(
                            f"<p>Hello {ev.get('owner_name', 'there')},</p>"
                            f"<p>The following evidence item in the ThemisIQ Evidence Vault "
                            f"is expiring <strong>{label}</strong> (on {exp}):</p>"
                            f"<p><strong>{title}</strong></p>"
                            f"<p>Please review and renew this evidence or archive it if no longer required.</p>"
                            f"<p><a href='/evidence/'>Open Evidence Vault</a></p>"
                        ),
                    )

        if total_created > 0:
            _notify_admins(
                db,
                f"Evidence Vault: {total_created} item(s) expiring soon",
                f"{total_created} evidence items are approaching their expiry date. "
                f"Check the Task Board for details.",
            )

        db.commit()
        log.info("Evidence expiry check: %d task(s) created", total_created)
    except Exception as e:
        log.warning("Evidence expiry check failed: %s", e)
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

    _scheduler.start()
    log.info("Evidence scheduler started — expiry check daily at 09:00 UTC")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Evidence scheduler stopped")
