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

from database import get_db_background as get_db, list_active_tenants, tenant_context
from core.timeutils import utcnow

log = logging.getLogger("oneforall.workflow_scheduler")
_scheduler: BackgroundScheduler | None = None


def _run_sla_checks() -> None:
    """Process SLA breaches and warnings independently inside each tenant."""
    try:
        tenants = list_active_tenants()
    except Exception as exc:
        log.error("SLA tenant list failed: %s", exc)
        return
    for org_id, slug in tenants:
        try:
            with tenant_context(org_id, slug, is_super_admin=False):
                _run_sla_checks_tenant(org_id)
        except Exception as exc:
            log.error("SLA checks failed for org %s: %s", org_id, exc)


def _run_sla_checks_tenant(org_id: int) -> None:
    db = get_db()
    try:
        now = utcnow()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        warn_cutoff = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        dedup_cutoff = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")

        resp_breached = db.execute(
            "UPDATE sla_instances SET breached = 1, breach_type = COALESCE(breach_type, 'response') "
            "WHERE org_id=%s AND status = 'active' AND breached = 0 AND response_due IS NOT NULL "
            "AND responded_at IS NULL AND response_due < %s", (org_id, now_str)
        ).rowcount
        res_breached = db.execute(
            "UPDATE sla_instances SET breached = 1, breach_type = COALESCE(breach_type, 'resolution') "
            "WHERE org_id=%s AND status = 'active' AND breached = 0 AND resolution_due IS NOT NULL "
            "AND resolved_at IS NULL AND resolution_due < %s", (org_id, now_str)
        ).rowcount
        db.commit()
        if resp_breached or res_breached:
            log.info("SLA breaches flagged for org %s: response=%d resolution=%d",
                     org_id, resp_breached, res_breached)

        at_risk = db.execute(
            "SELECT si.id, si.entity_type, si.entity_id, sd.name as sla_name "
            "FROM sla_instances si "
            "JOIN sla_definitions sd ON si.definition_id = sd.id "
            "WHERE si.org_id=%s AND si.status = 'active' AND si.breached = 0 AND ("
            "  (si.response_due IS NOT NULL AND si.responded_at IS NULL "
            "   AND si.response_due > %s AND si.response_due <= %s) OR "
            "  (si.resolution_due IS NOT NULL AND si.resolved_at IS NULL "
            "   AND si.resolution_due > %s AND si.resolution_due <= %s))",
            (org_id, now_str, warn_cutoff, now_str, warn_cutoff)
        ).fetchall()
        if at_risk:
            admins = db.execute(
                "SELECT DISTINCT u.id FROM users u "
                "JOIN user_roles ur ON u.id = ur.user_id "
                "WHERE u.org_id=%s AND ur.role_key='compliance_mgr' AND u.is_active = 1",
                (org_id,),
            ).fetchall()
            for sla in at_risk:
                link = f"/workflows?tab=sla&instance={sla['id']}"
                for admin in admins:
                    existing = db.execute(
                        "SELECT id FROM notifications WHERE user_id = %s "
                        "AND module = 'sla_warning' AND link = %s AND created_at > %s",
                        (admin["id"], link, dedup_cutoff)
                    ).fetchone()
                    if not existing:
                        db.execute(
                            "INSERT INTO notifications (user_id, title, message, link, module) "
                            "VALUES (%s, %s, %s, %s, 'sla_warning')",
                            (admin["id"],
                             f"SLA At Risk: {sla['sla_name']}",
                             f"SLA for {sla['entity_type']} #{sla['entity_id']} is due within 2 hours.",
                             link)
                        )
            db.commit()
            log.info("Pre-breach warnings sent for %d at-risk SLAs in org %s",
                     len(at_risk), org_id)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _run_workflow_step_reminders() -> None:
    """Check each tenant independently and reject legacy foreign assignments."""
    try:
        tenants = list_active_tenants()
    except Exception as exc:
        log.error("Workflow reminder tenant list failed: %s", exc)
        return
    for org_id, slug in tenants:
        try:
            with tenant_context(org_id, slug, is_super_admin=False):
                _run_workflow_step_reminders_tenant(org_id)
        except Exception as exc:
            log.error("Workflow reminders failed for org %s: %s", org_id, exc)


def _run_workflow_step_reminders_tenant(org_id: int) -> None:
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
            "LEFT JOIN users starter ON starter.id = wi.started_by "
            "JOIN users assignee ON assignee.id = wa.assigned_to "
            "WHERE wa.status = 'pending' AND wa.due_at IS NOT NULL "
            "AND wa.due_at < %s AND wi.status = 'active' "
            "AND COALESCE(wi.org_id, starter.org_id) = %s "
            "AND assignee.org_id = %s AND assignee.is_active = 1",
            (now_str, org_id, org_id),
        ).fetchall()
        notified = 0
        for action in overdue:
            link = f"/workflows?instance={action['instance_id']}"
            existing = db.execute(
                "SELECT id FROM notifications WHERE user_id = %s "
                "AND module = 'workflow' AND link = %s "
                "AND title LIKE 'Overdue%%' AND created_at > %s",
                (action["assigned_to"], link, reminder_cutoff),
            ).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO notifications (user_id, title, message, link, module) "
                    "VALUES (%s, %s, %s, %s, 'workflow')",
                    (
                        action["assigned_to"],
                        f"Overdue Workflow Step: {action['workflow_name']}",
                        f"Step {action['step_index'] + 1} was due at {action['due_at']} and is still pending.",
                        link,
                    ),
                )
                notified += 1
        if notified:
            db.commit()
            log.info("Workflow step reminders sent for %d overdue actions in org %s", notified, org_id)
    except Exception:
        db.rollback()
        raise
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
