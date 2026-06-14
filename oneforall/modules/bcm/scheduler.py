"""
BCM module — Background scheduler.

Jobs:
  Job 1  Plan review monitor  (weekly, Monday 07:00)
         - Checks bcm_plans for review_date within 30 days
         - Creates task_board reminder + admin notifications

  Job 2  Exercise alert monitor  (weekly, Monday 08:00)
         - Checks bcm_exercises with planned_date within 14 days and status='planned'
         - Creates notifications for exercise owners

  Job 3  Training due monitor  (daily 08:00)
         - Checks bcm_training_modules with next_due within 7 days
         - Creates notifications + tasks for training owners

All jobs are safe to run repeatedly (idempotent: checks existing tasks before creating).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db_background as get_db, sql_date_offset  # scheduler: fail-fast, never block UI
from core.email import send_email as _core_send_email

log = logging.getLogger("bcm.scheduler")
TZ = "UTC"

_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _send(*, to: str, subject: str, body_html: str) -> bool:
    """Thin wrapper around core.email.send_email for backward compatibility."""
    result = _core_send_email(to=to, subject=subject, body_html=body_html)
    return result.get("ok", False)


def _notify_admins(db, title: str, message: str, link: str = "/bcm/") -> None:
    """Insert a notification for every admin/super_admin user."""
    try:
        rows = db.execute(
            "SELECT DISTINCT u.id FROM users u "
            "JOIN user_roles ur ON u.id = ur.user_id "
            "WHERE ur.role_key IN ('super_admin', 'admin', 'bcm_manager') AND u.is_active = 1"
        ).fetchall()
        for r in rows:
            db.execute(
                "INSERT INTO notifications (user_id, module, title, message, link) "
                "VALUES (%s, %s, %s, %s, %s)",
                (r[0], "bcm", title, message, link),
            )
    except Exception as e:
        log.warning("_notify_admins failed: %s", e)


def _task_exists(db, title_fragment: str, entity_type: str, entity_id: int) -> bool:
    """Check if an open task already exists to avoid duplicates."""
    try:
        row = db.execute(
            "SELECT id FROM task_board WHERE module='bcm' AND entity_type=%s "
            "AND entity_id=%s AND status!='done' AND title LIKE %s",
            (entity_type, entity_id, f"%{title_fragment}%"),
        ).fetchone()
        return row is not None
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Job 1 — Plan Review Check
# ─────────────────────────────────────────────────────────────────────────────

def _plan_review_check() -> None:
    """
    Alert BCM team when a continuity plan's review date falls within 30 days.
    Creates a task_board entry and admin notification (idempotent — won't
    duplicate if task already exists).
    """
    log.info("BCM: running plan review check")
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, title, review_frequency, next_review, owner "
            "FROM bcm_plans "
            "WHERE status = 'approved' "
            "  AND next_review IS NOT NULL "
            f"  AND next_review <= {sql_date_offset('+30 days')} "
            "  AND next_review >= CURRENT_DATE "
            "ORDER BY next_review ASC"
        ).fetchall()

        created = 0
        for p in rows:
            pid  = p["id"]
            name = p["title"] or f"Plan #{pid}"
            due  = p["next_review"]
            owner = p["owner"] or "BCM Team"

            if _task_exists(db, "REVIEW DUE:", "plan", pid):
                continue

            db.execute(
                "INSERT INTO task_board "
                "(title, description, module, entity_type, entity_id, priority, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    f"REVIEW DUE: {name}",
                    f"Continuity plan '{name}' (owner: {owner}) is due for review "
                    f"on {due}. Review and update the plan, then reset the next review date.",
                    "bcm", "plan", pid, "high", "todo",
                ),
            )
            created += 1

        if created:
            _notify_admins(
                db,
                f"BCM: {created} plan(s) due for review",
                f"{created} continuity plan(s) are due for review within 30 days. "
                f"Check the Task Board for details.",
                "/bcm/#plans",
            )

        db.commit()
        log.info("BCM plan review check: %d task(s) created", created)
    except Exception as e:
        log.warning("BCM plan review check failed: %s", e)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Job 2 — Exercise Alert Check
# ─────────────────────────────────────────────────────────────────────────────

def _exercise_alert_check() -> None:
    """
    Alert when a planned exercise is within 14 days of its scheduled date.
    """
    log.info("BCM: running exercise alert check")
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, title, exercise_type, scheduled_date "
            "FROM bcm_exercises "
            "WHERE status = 'planned' "
            "  AND scheduled_date IS NOT NULL "
            f"  AND scheduled_date <= {sql_date_offset('+14 days')} "
            "  AND scheduled_date >= CURRENT_DATE "
            "ORDER BY scheduled_date ASC"
        ).fetchall()

        alerted = 0
        for ex in rows:
            eid  = ex["id"]
            name = ex["title"] or f"Exercise #{eid}"
            date = ex["scheduled_date"]
            etype = ex["exercise_type"] or "Exercise"

            if _task_exists(db, "EXERCISE UPCOMING:", "exercise", eid):
                continue

            db.execute(
                "INSERT INTO task_board "
                "(title, description, module, entity_type, entity_id, priority, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    f"EXERCISE UPCOMING: {name}",
                    f"{etype} '{name}' is scheduled for {date} (within 14 days). "
                    f"Ensure participants are briefed and materials are prepared.",
                    "bcm", "exercise", eid, "medium", "todo",
                ),
            )
            alerted += 1

        if alerted:
            _notify_admins(
                db,
                f"BCM: {alerted} exercise(s) within 14 days",
                f"{alerted} BCM exercise(s) are coming up within 14 days. "
                f"Check the Task Board for preparation reminders.",
                "/bcm/#exercises",
            )

        db.commit()
        log.info("BCM exercise alert check: %d task(s) created", alerted)
    except Exception as e:
        log.warning("BCM exercise alert check failed: %s", e)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Job 3 — Training Due Check
# ─────────────────────────────────────────────────────────────────────────────

def _training_due_check() -> None:
    """
    Alert when a BCM training module's next_due date is within 7 days.
    """
    log.info("BCM: running training due check")
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, title, category, next_due "
            "FROM bcm_training_modules "
            "WHERE status = 'active' "
            "  AND next_due IS NOT NULL "
            f"  AND next_due <= {sql_date_offset('+7 days')} "
            "  AND next_due >= CURRENT_DATE "
            "ORDER BY next_due ASC"
        ).fetchall()

        created = 0
        for t in rows:
            tid  = t["id"]
            name = t["title"] or f"Training #{tid}"
            due  = t["next_due"]
            cat  = t["category"] or "General"

            if _task_exists(db, "TRAINING DUE:", "training_module", tid):
                continue

            db.execute(
                "INSERT INTO task_board "
                "(title, description, module, entity_type, entity_id, priority, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    f"TRAINING DUE: {name}",
                    f"BCM {cat} training module '{name}' is due by {due}. "
                    f"Ensure all required staff have completed and attested this module.",
                    "bcm", "training_module", tid, "medium", "todo",
                ),
            )
            created += 1

        if created:
            _notify_admins(
                db,
                f"BCM: {created} training module(s) due within 7 days",
                f"{created} BCM training module(s) are due within 7 days. "
                f"Check the Task Board for details.",
                "/bcm/#training",
            )

        db.commit()
        log.info("BCM training due check: %d task(s) created", created)
    except Exception as e:
        log.warning("BCM training due check failed: %s", e)
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

    # Plan review: weekly Monday 07:00 UTC
    _scheduler.add_job(
        _plan_review_check,
        CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=TZ),
        id="bcm_plan_review",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Exercise alert: weekly Monday 08:00 UTC
    _scheduler.add_job(
        _exercise_alert_check,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=TZ),
        id="bcm_exercise_alert",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Training due: daily 08:30 UTC
    _scheduler.add_job(
        _training_due_check,
        CronTrigger(hour=8, minute=30, timezone=TZ),
        id="bcm_training_due",
        replace_existing=True,
        misfire_grace_time=300,
    )

    _scheduler.start()
    log.info(
        "BCM scheduler started — jobs: plan_review (Mon 07:00), "
        "exercise_alert (Mon 08:00), training_due (daily 08:30)"
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("BCM scheduler stopped")
