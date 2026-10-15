"""
Sentinel module: Background scheduler.

Jobs:
  Job 1  Breach deadline monitor  (every hour)
         - Tells the administrators in the app when the notification deadline is less than 24 and less than 6 hours away
           and when it has passed, once per threshold
         - Asks the email outbox to tell the named privacy officers, once per person and threshold

  Job 2  DSR deadline monitor  (daily 08:00)
         - Asks the email outbox to tell the named privacy officers at 7, 3 and 1 days
         - Emits SENTINEL_DSR_OVERDUE when past the deadline

  Job 3  Retention schedule review  (weekly, Monday 07:00)
         - Creates notifications for retention records due for review
         - Creates tasks for data owners to confirm deletion / renewal

All jobs are safe to run repeatedly (idempotent where possible), and each visits every organization in turn.

Who is told by email (plans/2026-10-governance-rework/06 sections 3 and 4): the active users who hold the DPO role, and
the active user whose address is set as the DPO address in the settings. Never the first user of the table. When nobody is
named, the administrators are told in the app, and the notice says that no email was sent. A message carries the case
reference, the deadline and a link, never the title of a breach or the name of a data subject. Whether a recipient may
open the case, and whether it is still open, are checked by the outbox at the moment of sending.
"""
from __future__ import annotations

import logging
from datetime import datetime
from core.timeutils import utcnow, to_dt

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db_background as get_db, sql_date_offset  # scheduler: fail-fast, never block UI
from core import email_outbox as outbox
from core import email_templates as templates
from core.best_effort import swallowed

log = logging.getLogger("sentinel.scheduler")
TZ = "Africa/Harare"

_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dpo_user_ids(org_id) -> list:
    """The people privacy deadlines are addressed to, in one organization: the active users who hold the DPO role, and
    the active user whose address is set as the DPO address. Never the first user of the table, and never a platform
    operator."""
    db = get_db()
    try:
        ids = outbox.organization_people(db, org_id, ("dpo",))
        for key in ("sentinel_dpo_email", "dpo_email"):
            row = db.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
            address = str((row["value"] if row else "") or "").strip()
            if not address:
                continue
            user = db.execute(
                "SELECT id FROM users WHERE LOWER(email) = LOWER(%s) AND is_active = 1 "
                "AND COALESCE(is_super_admin, 0) = 0 AND (org_id = %s OR org_id IS NULL)", (address, org_id)).fetchone()
            if user and user["id"] not in ids:
                ids.append(user["id"])
            break
        return ids
    finally:
        db.close()


def _ask_officers(org_id, template, recipients, *, route, fields, source, purpose, threshold, priority) -> int:
    """Ask the outbox for one message to each named person. The outbox is the record of what was sent."""
    db = get_db()
    try:
        asked = 0
        for uid in recipients:
            if outbox.enqueue_safely(
                    db, template, recipient_user_id=uid, org_id=org_id, route=route, fields=fields, source=source,
                    purpose=purpose, threshold=threshold, priority=priority):
                asked += 1
        db.commit()
        return asked
    finally:
        db.close()


def _notify_user(user_id: int, module: str, title: str, message: str, link: str = ""):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO notifications (user_id, module, title, message, link) VALUES (%s,%s,%s,%s,%s)",
            (user_id, module, title, message, link),
        )
        db.commit()
    except Exception:
        swallowed("_notify_user (notifications)")
    finally:
        db.close()


def _notify_admins(module: str, title: str, message: str, link: str = ""):
    db = get_db()
    try:
        rows = db.execute(
            "SELECT DISTINCT u.id FROM users u "
            "JOIN user_roles ur ON u.id=ur.user_id "
            "WHERE ur.role_key IN ('super_admin','admin','dpo') AND u.is_active=1"
        ).fetchall()
        for r in rows:
            db.execute(
                "INSERT INTO notifications (user_id, module, title, message, link) VALUES (%s,%s,%s,%s,%s)",
                (r[0], module, title, message, link),
            )
        db.commit()
    except Exception:
        swallowed("_notify_admins (users)")
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Job 1: Breach 72-hour deadline monitor  (hourly)
# ─────────────────────────────────────────────────────────────────────────────

def _breach_deadline_check() -> None:
    log.info("Sentinel: running breach deadline check")
    outbox.for_each_tenant(_breach_deadline_check_in, "Sentinel breach deadline check")


def _breach_deadline_check_in(org_id: int) -> None:
    db = get_db()
    try:
        open_breaches = db.execute(
            "SELECT id, title, ref_number, notify_deadline, severity, regulation, "
            "       breach_notified_24h, breach_notified_6h "
            "FROM sentinel_breaches "
            "WHERE status NOT IN ('resolved','closed','contained') "
            "AND notify_deadline IS NOT NULL"
        ).fetchall()
    finally:
        db.close()

    now = utcnow()
    recipients = _dpo_user_ids(org_id)
    unnamed = "" if recipients else " No privacy officer is named, so no email was sent: name a user with the DPO role."

    for b in open_breaches:
        bid = b["id"]
        ref = b["ref_number"] or f"BRE-{bid}"
        title = b["title"] or "Data Breach Incident"
        regulation = b["regulation"] or "GDPR"

        try:
            from modules.sentinel.jurisdictions import (
                get_authority_short, get_breach_deadline_hours, is_asap_jurisdiction
            )
            authority = get_authority_short(regulation)
            deadline_h = get_breach_deadline_hours(regulation)
            is_asap = is_asap_jurisdiction(regulation)
        except Exception:
            authority = "DPA"
            deadline_h = 72
            is_asap = False

        try:
            deadline = to_dt(b["notify_deadline"])
        except Exception:
            continue

        hours_left = (deadline - now).total_seconds() / 3600
        window_label = "ASAP" if is_asap else f"{deadline_h}h"
        level = "6h" if 0 < hours_left <= 6 else ("24h" if 0 < hours_left <= 24 else None)

        if level:
            _ask_officers(
                org_id, "privacy.deadline", recipients, route=f"/sentinel/?open=breach:{bid}",
                fields={"reference": templates.reference_or(ref, f"BRE-{bid}"),
                        "due": deadline.strftime("%Y-%m-%d %H:%M"), "hours": int(hours_left)},
                source=("sentinel", "breach", bid), purpose="deadline", threshold=level, priority="critical")
            already = b["breach_notified_6h"] if level == "6h" else b["breach_notified_24h"]
            if already:
                continue
            if level == "24h":
                _notify_admins(
                    "sentinel", f"Breach Notification Due in {hours_left:.0f}h: {title}",
                    f"Ref {ref}: {regulation} requires notification to {authority}. "
                    f"{hours_left:.0f} hours remaining.{unnamed}", "/sentinel/breaches")
            else:
                _notify_admins(
                    "sentinel", f"URGENT: Breach Notification Due in {hours_left:.0f}h: {title}",
                    f"Ref {ref}: Only {hours_left:.0f} hours until the {regulation} "
                    f"{window_label} notification deadline ({authority}).{unnamed}", "/sentinel/breaches")
            _mark_breach_notified(bid, level)

        # Overdue
        elif hours_left <= 0:
            hours_overdue = abs(hours_left)
            if hours_overdue < 2:  # only notify once when it first tips over
                _notify_admins(
                    "sentinel", f"OVERDUE: Breach Notification Deadline Passed: {title}",
                    f"Ref {ref}: The {regulation} {window_label} notification deadline "
                    f"({authority}) has passed. Immediate action required.", "/sentinel/breaches")

    log.info("Sentinel: breach deadline check complete in organization %s (%d open breaches checked)",
             org_id, len(open_breaches))


def _mark_breach_notified(bid: int, level: str) -> None:
    """Records that the administrators were told in the app. It says nothing about email: the outbox does."""
    col = "breach_notified_24h" if level == "24h" else "breach_notified_6h"
    db = get_db()
    try:
        db.execute(f"UPDATE sentinel_breaches SET {col}=1 WHERE id=%s", (bid,))
        db.commit()
    except Exception:
        swallowed("_mark_breach_notified (sentinel_breaches)")
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Job 2: DSR 30-day deadline monitor  (daily 08:00)
# ─────────────────────────────────────────────────────────────────────────────

def _dsr_deadline_check() -> None:
    log.info("Sentinel: running DSR deadline check")
    outbox.for_each_tenant(_dsr_deadline_check_in, "Sentinel DSR deadline check")


def _dsr_deadline_check_in(org_id: int) -> None:
    db = get_db()
    try:
        open_dsrs = db.execute(
            "SELECT id, ref_number, requester_name, request_type, regulation, "
            "       deadline_date, requester_email "
            "FROM sentinel_dsr "
            "WHERE status NOT IN ('completed','closed') "
            "AND deadline_date IS NOT NULL"
        ).fetchall()
    finally:
        db.close()

    now = utcnow().date()
    recipients = _dpo_user_ids(org_id)
    unnamed = "" if recipients else " No privacy officer is named, so no email was sent."

    for d in open_dsrs:
        did = d["id"]
        ref = d["ref_number"] or f"DSR-{did}"
        name = d["requester_name"] or "Data Subject"
        req_type = d["request_type"] or "Request"
        regulation = d["regulation"] or "GDPR"

        try:
            from modules.sentinel.jurisdictions import get_authority_short
            authority = get_authority_short(regulation)
        except Exception:
            authority = "DPA"

        try:
            deadline = datetime.strptime(d["deadline_date"][:10], "%Y-%m-%d").date()
        except Exception:
            continue

        days_left = (deadline - now).days

        if days_left < 0:
            # Overdue: emit event + notify
            from core.events import emit, SENTINEL_DSR_OVERDUE
            emit(
                SENTINEL_DSR_OVERDUE,
                source_module="sentinel",
                entity_type="dsr",
                entity_id=did,
                payload={
                    "subject_name": name,
                    "request_type": req_type,
                    "deadline": str(deadline),
                    "days_overdue": abs(days_left),
                    "regulation": regulation,
                },
                user_id=None,
            )
        elif days_left in (7, 3, 1):
            _ask_officers(
                org_id, "privacy.dsr", recipients, route=f"/sentinel/?open=dsr:{did}",
                fields={"reference": templates.reference_or(ref, f"DSR-{did}"), "due": str(deadline)},
                source=("sentinel", "dsr", did), purpose="deadline", threshold=f"d{days_left}", priority=None)
            _notify_admins(
                "sentinel",
                f"DSR Deadline: {days_left} day{'s' if days_left > 1 else ''} remaining: {ref}",
                f"{regulation}: {req_type} from {name} is due in {days_left} day(s) "
                f"({deadline}). Notify {authority} if unable to respond.{unnamed}",
                "/sentinel/dsr")

    log.info("Sentinel: DSR deadline check complete in organization %s (%d open DSRs checked)", org_id, len(open_dsrs))


# ─────────────────────────────────────────────────────────────────────────────
# Job 3: Retention review monitor  (weekly Monday 07:00)
# ─────────────────────────────────────────────────────────────────────────────

def _retention_review_check() -> None:
    log.info("Sentinel: running retention review check")
    outbox.for_each_tenant(lambda _org: _retention_review_check_in(), "Sentinel retention review check")


def _retention_review_check_in() -> None:
    db = get_db()
    try:
        due = db.execute(
            "SELECT id, category, data_type, retention_period, responsible, review_date "
            "FROM sentinel_retention "
            "WHERE review_date IS NOT NULL "
            f"AND review_date <= {sql_date_offset('+30 days')}"
        ).fetchall()
    finally:
        db.close()

    if not due:
        log.info("Sentinel: no retention reviews due within 30 days")
        return

    _notify_admins("sentinel",
        f"Retention Review Due: {len(due)} schedule(s) require attention",
        f"{len(due)} retention schedule(s) have review dates within the next 30 days. "
        "Review and confirm retention periods remain appropriate.",
        "/sentinel/retention")

    # Create task board item
    db2 = get_db()
    try:
        items = ", ".join(f"{r['category']}/{r['data_type']}" for r in due[:5])
        if len(due) > 5:
            items += f" (+{len(due)-5} more)"
        db2.execute(
            "INSERT INTO task_board (title, description, module, priority, status) "
            "VALUES (%s,%s,%s,%s,%s)",
            (f"Retention Review: {len(due)} schedule(s) due",
             f"Review retention periods for: {items}. "
             "Confirm schedules are still accurate and legally compliant.",
             "sentinel", "high", "todo"),
        )
        db2.commit()
    except Exception as exc:
        log.warning("Could not create retention task: %s", exc)
    finally:
        db2.close()

    log.info("Sentinel: retention review check complete (%d schedules flagged)", len(due))


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone=TZ)

    # Breach deadline: every hour
    _scheduler.add_job(
        _breach_deadline_check,
        CronTrigger(minute=0, timezone=TZ),
        id="sentinel_breach_deadline",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # DSR deadline: daily 08:00
    _scheduler.add_job(
        _dsr_deadline_check,
        CronTrigger(hour=8, minute=0, timezone=TZ),
        id="sentinel_dsr_deadline",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Retention review: every Monday 07:00
    _scheduler.add_job(
        _retention_review_check,
        CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=TZ),
        id="sentinel_retention_review",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    log.info("Sentinel scheduler started (breach/DSR/retention jobs)")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
