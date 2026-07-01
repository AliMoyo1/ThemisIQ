"""
ThemisIQ - Workflow and SLA background scheduler.

Runs every 5 minutes:
- Scans active SLA instances, flags breaches (response and resolution)
- Sends pre-breach notifications to compliance managers for SLAs due within 2 hours
- Sends overdue step reminders to workflow action assignees (throttled to 4h)
"""
from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import get_db_background as get_db
from core.timeutils import utcnow

log = logging.getLogger("oneforall.workflow_scheduler")
_scheduler: BackgroundScheduler | None = None


def _run_sla_checks() -> None:
    """Flag breaches and send pre-breach warnings for at-risk SLAs."""
    db = get_db()
    try:
        now = utcnow()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        warn_cutoff = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        dedup_cutoff = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

        resp_breached = db.execute(
            "UPDATE sla_instances SET breached = 1, breach_type = COALESCE(breach_type, 'response') "
            "WHERE status = 'active' AND breached = 0 AND response_due IS NOT NULL "
            "AND responded_at IS NULL AND response_due < %s", (now_str,)
        ).rowcount

        res_breached = db.execute(
            "UPDATE sla_instances SET breached = 1, breach_type = COALESCE(breach_type, 'resolution') "
            "WHERE status = 'active' AND breached = 0 AND resolution_due IS NOT NULL "
            "AND resolved_at IS NULL AND resolution_due < %s", (now_str,)
        ).rowcount

        db.commit()

        if resp_breached or res_breached:
            log.info("SLA breaches flagged: response=%d resolution=%d", resp_breached, res_breached)

        at_risk = db.execute(
            "SELECT si.id, si.entity_type, si.entity_id, sd.name as sla_name "
            "FROM sla_instances si "
            "JOIN sla_definitions sd ON si.definition_id = sd.id "
            "WHERE si.status = 'active' AND si.breached = 0 AND ("
            "  (si.response_due IS NOT NULL AND si.responded_at IS NULL "
            "   AND si.response_due > %s AND si.response_due <= %s) OR "
            "  (si.resolution_due IS NOT NULL AND si.resolved_at IS NULL "
            "   AND si.resolution_due > %s AND si.resolution_due <= %s))",
            (now_str, warn_cutoff, now_str, warn_cutoff)
        ).fetchall()

        if at_risk:
            admins = db.execute(
                "SELECT DISTINCT u.id FROM users u "
                "JOIN user_roles ur ON u.id = ur.user_id "
                "WHERE ur.role_key IN ('super_admin', 'compliance_mgr') AND u.is_active = 1"
            ).fetchall()
            for sla in at_risk:
                link = f"/workflows?tab=sla&instance={sla['id']}"
                for admin in admins:
                    existing = db.execute(
                        "SELECT id FROM notifications WHERE user_id = %s "
                        "AND category = 'sla_warning' AND link = %s AND created_at > %s",
                        (admin["id"], link, dedup_cutoff)
                    ).fetchone()
                    if not existing:
                        db.execute(
                            "INSERT INTO notifications (user_id, title, message, link, category) "
                            "VALUES (%s, %s, %s, %s, 'sla_warning')",
                            (admin["id"],
                             f"SLA At Risk: {sla['sla_name']}",
                             f"SLA for {sla['entity_type']} #{sla['entity_id']} is due within 2 hours.")
                        )
            db.commit()
            log.info("Pre-breach warnings sent for %d at-risk SLAs", len(at_risk))

    except Exception as exc:
        log.error("SLA check job failed: %s", exc)
    finally:
        db.close()


def _run_workflow_step_reminders() -> None:
    """Notify assignees of pending workflow steps that have passed their due_at."""
    db = get_db()
    try:
        now = utcnow()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        reminder_cutoff = (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")

        overdue = db.execute(
            "SELECT wa.id, wa.instance_id, wa.step_index, wa.assigned_to, wa.due_at, "
            "wd.name as workflow_name "
            "FROM workflow_actions wa "
            "JOIN workflow_instances wi ON wa.instance_id = wi.id "
            "JOIN workflow_definitions wd ON wi.definition_id = wd.id "
            "WHERE wa.status = 'pending' AND wa.due_at IS NOT NULL "
            "AND wa.due_at < %s AND wi.status = 'active'",
            (now_str,)
        ).fetchall()

        notified = 0
        for action in overdue:
            if not action["assigned_to"]:
                continue
            link = f"/workflows?instance={action['instance_id']}"
            existing = db.execute(
                "SELECT id FROM notifications WHERE user_id = %s "
                "AND category = 'workflow' AND link = %s "
                "AND title LIKE 'Overdue%%' AND created_at > %s",
                (action["assigned_to"], link, reminder_cutoff)
            ).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO notifications (user_id, title, message, link, category) "
                    "VALUES (%s, %s, %s, %s, 'workflow')",
                    (action["assigned_to"],
                     f"Overdue Workflow Step: {action['workflow_name']}",
                     f"Step {action['step_index'] + 1} was due at {action['due_at']} and is still pending.")
                )
                notified += 1

        if notified:
            db.commit()
            log.info("Workflow step reminders sent for %d overdue actions", notified)

    except Exception as exc:
        log.error("Workflow step reminder job failed: %s", exc)
    finally:
        db.close()


def _run_all() -> None:
    _run_sla_checks()
    _run_workflow_step_reminders()


def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_all,
        IntervalTrigger(minutes=5),
        id="workflow_sla_processor",
        replace_existing=True,
        misfire_grace_time=60,
    )
    _scheduler.start()
    log.info("Workflow/SLA scheduler started — checking every 5 minutes")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Workflow/SLA scheduler stopped")
