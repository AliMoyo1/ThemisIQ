"""
Sentinel module: Background scheduler.

Jobs:
  Job 1  Breach deadline monitor  (every hour)
         - Tells privacy specialists who may open the case when the notification deadline is less than 24 and less than 6 hours away
           and when it has passed, once per threshold
         - Asks the email outbox to tell the named privacy officers, once per person and threshold

  Job 2  DSR deadline monitor  (daily 08:00)
         - Asks the email outbox to tell the named privacy officers at 7, 3 and 1 days
         - Emits SENTINEL_DSR_OVERDUE when past the deadline

  Job 3  Retention schedule review  (weekly, Monday 07:00)
         - Creates notifications for retention records due for review
         - Creates tasks for data owners to confirm deletion / renewal

All jobs are safe to run repeatedly (idempotent where possible), and each visits every organization in turn.

Who is told by email (plans/2026-10-governance-rework/06 sections 3 and 4): active DPOs, the named DPO contact,
and an optional alternate privacy specialist. Never the first user of the table. Scoped privacy specialists receive in-app
case notices; the named specialists also receive in-app notices. A message carries the case reference, recorded review
target and link, never the title of a breach or the name of a data subject. Case access is checked for in-app notices
and again by the outbox when sending email.
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
                "AND COALESCE(is_super_admin, 0) = 0 AND org_id = %s", (address, org_id)).fetchone()
            if user and user["id"] not in ids:
                ids.append(user["id"])
            break
        backup_row = db.execute("SELECT value FROM settings WHERE key='sentinel_backup_email'").fetchone()
        backup = str((backup_row["value"] if backup_row else "") or "").strip()
        if backup:
            person = db.execute(
                "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id=u.id "
                "WHERE LOWER(u.email)=LOWER(%s) AND u.org_id=%s AND u.is_active=1 "
                "AND COALESCE(u.is_super_admin,0)=0 "
                "AND ur.role_key IN ('dpo','privacy_analyst') LIMIT 1", (backup, org_id),
            ).fetchone()
            if person and person["id"] not in ids:
                ids.append(person["id"])
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


def _notify_privacy_people(org_id: int, recipients: list[int], source_type: str, source_id: int,
                           title: str, message: str, link: str) -> None:
    """Give the named privacy people an in-app alert even when mail is not configured."""
    if not recipients:
        return
    db = get_db()
    try:
        from modules.governance.entity_scope import describe_record
        today = utcnow().date().isoformat()
        for uid in recipients:
            row = db.execute(
                "SELECT id,username,email,full_name,org_id,is_active,is_super_admin,business_unit_id "
                "FROM users WHERE id=%s AND org_id=%s AND is_active=1",
                (uid, org_id),
            ).fetchone()
            if not row or describe_record(db, ("sentinel", source_type), source_id,
                                          outbox.user_for_scope(db, row)) is None:
                continue
            exists = db.execute(
                "SELECT 1 FROM notifications WHERE user_id=%s AND module='sentinel' "
                "AND title=%s AND link=%s AND created_at >= %s LIMIT 1",
                (uid, title, link, today),
            ).fetchone()
            if not exists:
                db.execute(
                    "INSERT INTO notifications (user_id,module,title,message,link) "
                    "VALUES (%s,'sentinel',%s,%s,%s)", (uid, title, message, link),
                )
        db.commit()
    except Exception:
        db.rollback()
        swallowed("_notify_privacy_people (notifications)")
    finally:
        db.close()


def _notify_admins(module: str, title: str, message: str, link: str, org_id: int,
                   source_type: str | None = None, source_id: int | None = None,
                   exclude_ids: list[int] | None = None):
    db = get_db()
    try:
        from modules.governance.entity_scope import describe_record
        rows = db.execute(
            "SELECT DISTINCT u.id,u.username,u.email,u.full_name,u.org_id,u.is_active,"
            "u.is_super_admin,u.business_unit_id FROM users u "
            "JOIN user_roles ur ON u.id=ur.user_id "
            "WHERE ur.role_key IN ('dpo','privacy_analyst','org_admin','super_admin') "
            "AND u.is_active=1 AND u.org_id=%s "
            "AND COALESCE(u.is_super_admin,0)=0", (org_id,)
        ).fetchall()
        for r in rows:
            if r["id"] in (exclude_ids or ()):
                continue
            if source_type and describe_record(db, (module, source_type), source_id,
                                               outbox.user_for_scope(db, r)) is None:
                continue
            db.execute(
                "INSERT INTO notifications (user_id, module, title, message, link) VALUES (%s,%s,%s,%s,%s)",
                (r["id"], module, title, message, link),
            )
        db.commit()
    except Exception:
        db.rollback()
        swallowed("_notify_admins (users)")
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Job 1: Breach review deadline monitor  (hourly)
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
    unnamed = "" if recipients else " No privacy specialist is named, so no email was queued: name a DPO or alternate contact."

    for b in open_breaches:
        bid = b["id"]
        ref = templates.reference_or(b["ref_number"], f"BRE-{bid}")
        regulation = b["regulation"] or "GDPR"
        # Old Bill C-11 rows remain readable for reclassification, but a
        # proposal that never became law must not drive deadline alerts.
        if regulation == "Canada Bill C-11":
            continue

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
            _notify_privacy_people(
                org_id, recipients, "breach", bid, f"Breach review due within {level}: {ref}",
                f"Review recorded deadline for {ref}. Confirm the applicable rule and trigger.",
                f"/sentinel/?open=breach:{bid}",
            )
            already = b["breach_notified_6h"] if level == "6h" else b["breach_notified_24h"]
            if already:
                continue
            if level == "24h":
                _notify_admins(
                    "sentinel", f"Breach review due in {hours_left:.0f}h: {ref}",
                    f"Ref {ref}: {hours_left:.0f} hours remain until the recorded review deadline. "
                    f"A privacy specialist must confirm the applicable rule and trigger.{unnamed}",
                    "/sentinel/breaches", org_id, "breach", bid, recipients)
            else:
                _notify_admins(
                    "sentinel", f"Urgent breach review due in {hours_left:.0f}h: {ref}",
                    f"Ref {ref}: {hours_left:.0f} hours remain until the recorded review deadline. "
                    f"Confirm the obligation and required action.{unnamed}",
                    "/sentinel/breaches", org_id, "breach", bid, recipients)
            _mark_breach_notified(bid, level)

        # Overdue
        elif hours_left <= 0:
            hours_overdue = abs(hours_left)
            if hours_overdue < 2:  # only notify once when it first tips over
                _notify_privacy_people(
                    org_id, recipients, "breach", bid, f"Breach review target passed: {ref}",
                    f"Review the recorded target for {ref} and confirm the applicable obligation.",
                    f"/sentinel/?open=breach:{bid}",
                )
                _notify_admins(
                    "sentinel", f"Breach review target passed: {ref}",
                    f"Ref {ref}: The recorded review deadline has passed. "
                    "A privacy specialist should assess the obligation and act promptly.",
                    "/sentinel/breaches", org_id, "breach", bid, recipients)

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
# Job 2: DSR recorded review deadline monitor  (daily 08:00)
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
        ref = templates.reference_or(d["ref_number"], f"DSR-{did}")
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
            _notify_privacy_people(
                org_id, recipients, "dsr", did, f"DSR review target passed: {ref}",
                f"Review the recorded target for {ref} and confirm the applicable obligation.",
                f"/sentinel/?open=dsr:{did}",
            )
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
            _notify_privacy_people(
                org_id, recipients, "dsr", did, f"DSR review due in {days_left} day(s): {ref}",
                f"Review the recorded date for {ref} and confirm the applicable rule.",
                f"/sentinel/?open=dsr:{did}",
            )
            _notify_admins(
                "sentinel",
                f"DSR review: {days_left} day{'s' if days_left > 1 else ''} remaining: {ref}",
                f"Ref {ref}: the recorded response date is in {days_left} day(s) "
                f"({deadline}). Confirm any legal deadline and required action.{unnamed}",
                "/sentinel/dsr", org_id, "dsr", did, recipients)

    log.info("Sentinel: DSR deadline check complete in organization %s (%d open DSRs checked)", org_id, len(open_dsrs))


# ─────────────────────────────────────────────────────────────────────────────
# Job 3: Retention review monitor  (weekly Monday 07:00)
# ─────────────────────────────────────────────────────────────────────────────

def _retention_review_check() -> None:
    log.info("Sentinel: running retention review check")
    outbox.for_each_tenant(_retention_review_check_in, "Sentinel retention review check")


def _retention_review_check_in(org_id: int) -> None:
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
        "/sentinel/retention", org_id)

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

    # A short hourly dispatcher checks each organization's selected 24-hour,
    # weekly or 30-day cadence. Fetching public sources uses zero AI tokens.
    from modules.sentinel.living_law import scheduled_check
    _scheduler.add_job(
        scheduled_check, CronTrigger(minute=17, timezone=TZ),
        id="sentinel_law_source_monitor", replace_existing=True,
        misfire_grace_time=1800, max_instances=1,
    )

    _scheduler.start()
    log.info("Sentinel scheduler started (breach/DSR/retention/law-source jobs)")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
