"""
Sentinel module — Background scheduler.

Jobs:
  Job 1  Breach deadline monitor  (every hour)
         - Sends email alert when 72h notify window has < 48h, < 24h, < 6h remaining
         - Marks notification sent to avoid spamming

  Job 2  DSR deadline monitor  (daily 08:00)
         - Sends email when 7 days, 3 days, 1 day remaining
         - Emits SENTINEL_DSR_OVERDUE event when past deadline

  Job 3  Retention schedule review  (weekly, Monday 07:00)
         - Creates notifications for retention records due for review
         - Creates tasks for data owners to confirm deletion / renewal

All jobs are safe to run repeatedly (idempotent where possible).
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from core.timeutils import utcnow, to_dt

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db_background as get_db, sql_date_offset  # scheduler: fail-fast, never block UI
from core.email import send_email as _core_send_email

log = logging.getLogger("sentinel.scheduler")
TZ = "Africa/Harare"

_scheduler: BackgroundScheduler | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _esc(t) -> str:
    return html.escape(str(t)) if t else ""


def _send(*, to: str, subject: str, body_html: str) -> bool:
    """Thin wrapper around core.email.send_email for backward compatibility."""
    result = _core_send_email(to=to, subject=subject, body_html=body_html)
    return result.get("ok", False)


def _get_dpo_email() -> str:
    db = get_db()
    try:
        row = db.execute("SELECT value FROM settings WHERE key='sentinel_dpo_email'").fetchone()
        if row:
            return row["value"]
        row = db.execute("SELECT value FROM settings WHERE key='dpo_email'").fetchone()
        if row:
            return row["value"]
        row = db.execute("SELECT email FROM users WHERE is_active=1 ORDER BY id LIMIT 1").fetchone()
        return row["email"] if row else ""
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
        pass
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
        pass
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Job 1 — Breach 72-hour deadline monitor  (hourly)
# ─────────────────────────────────────────────────────────────────────────────

def _breach_deadline_check() -> None:
    log.info("Sentinel: running breach deadline check")
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
    dpo = _get_dpo_email()

    for b in open_breaches:
        bid = b["id"]
        ref = b["ref_number"] or f"BRE-{bid}"
        title = b["title"] or "Data Breach Incident"
        severity = b["severity"] or "unknown"
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

        # 24h alert (send once)
        if hours_left <= 24 and hours_left > 0 and not b["breach_notified_24h"]:
            _send_breach_alert(dpo, ref, title, severity, hours_left, "24h",
                               regulation=regulation, authority=authority, window=window_label)
            _notify_admins("sentinel",
                f"⚠️ Breach Notification Due in {hours_left:.0f}h: {title}",
                f"Ref {ref} — {regulation} requires notification to {authority}. "
                f"{hours_left:.0f} hours remaining.",
                "/sentinel/breaches")
            _mark_breach_notified(bid, "24h")

        # 6h alert (send once)
        elif hours_left <= 6 and hours_left > 0 and not b["breach_notified_6h"]:
            _send_breach_alert(dpo, ref, title, severity, hours_left, "6h",
                               regulation=regulation, authority=authority, window=window_label)
            _notify_admins("sentinel",
                f"🚨 URGENT: Breach Notification Due in {hours_left:.0f}h: {title}",
                f"Ref {ref} — Only {hours_left:.0f} hours until the {regulation} "
                f"{window_label} notification deadline ({authority}).",
                "/sentinel/breaches")
            _mark_breach_notified(bid, "6h")

        # Overdue
        elif hours_left <= 0:
            hours_overdue = abs(hours_left)
            if hours_overdue < 2:  # only notify once when it first tips over
                _notify_admins("sentinel",
                    f"🔴 OVERDUE: Breach Notification Deadline Passed — {title}",
                    f"Ref {ref} — The {regulation} {window_label} notification deadline "
                    f"({authority}) has passed. Immediate action required.",
                    "/sentinel/breaches")

    log.info("Sentinel: breach deadline check complete (%d open breaches checked)", len(open_breaches))


def _send_breach_alert(to: str, ref: str, title: str, severity: str,
                       hours_left: float, alert_level: str,
                       regulation: str = "GDPR", authority: str = "DPA",
                       window: str = "72h") -> None:
    if not to:
        return
    urgency = "URGENT" if alert_level == "6h" else "Important"
    body = f"""
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
  <div style="background:#dc2626;color:white;padding:20px 24px;border-radius:8px 8px 0 0">
    <h2 style="margin:0;font-size:18px">⚠️ {_esc(urgency)}: Breach Notification Deadline</h2>
    <p style="margin:8px 0 0;opacity:.85;font-size:13px">
      {_esc(regulation)} — {_esc(window)} notification deadline to {_esc(authority)}
    </p>
  </div>
  <div style="border:1px solid #e5e7eb;border-top:none;padding:24px;border-radius:0 0 8px 8px">
    <p style="font-size:15px;color:#111">
      The breach notification window is closing. Action required.
    </p>
    <table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0">
      <tr><td style="padding:8px 0;color:#6b7280;width:40%">Reference</td>
          <td style="font-weight:700">{_esc(ref)}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Title</td>
          <td style="font-weight:700">{_esc(title)}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Regulation</td>
          <td style="font-weight:700">{_esc(regulation)}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Authority</td>
          <td style="font-weight:700">{_esc(authority)}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Severity</td>
          <td style="font-weight:700;color:#dc2626">{_esc(severity.upper())}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Time remaining</td>
          <td style="font-weight:700;color:#dc2626">{hours_left:.1f} hours</td></tr>
    </table>
    <p style="font-size:13px;color:#6b7280">
      Where notification to the supervisory authority is required, it must be completed
      within the deadline set by {_esc(regulation)}.
    </p>
    <a href="#" style="display:inline-block;background:#dc2626;color:white;padding:10px 20px;
       border-radius:6px;text-decoration:none;font-size:14px;font-weight:700;margin-top:8px">
      Open Breach Record
    </a>
  </div>
</div>"""
    _send(to=to,
          subject=f"[{alert_level} ALERT] {regulation} Breach Notification Due — {ref}",
          body_html=body)


def _mark_breach_notified(bid: int, level: str) -> None:
    col = "breach_notified_24h" if level == "24h" else "breach_notified_6h"
    db = get_db()
    try:
        db.execute(f"UPDATE sentinel_breaches SET {col}=1 WHERE id=?", (bid,))
        db.commit()
    except Exception:
        pass
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Job 2 — DSR 30-day deadline monitor  (daily 08:00)
# ─────────────────────────────────────────────────────────────────────────────

def _dsr_deadline_check() -> None:
    log.info("Sentinel: running DSR deadline check")
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
    dpo = _get_dpo_email()

    for d in open_dsrs:
        did = d["id"]
        ref = d["ref_number"] or f"DSR-{did}"
        name = d["requester_name"] or "Data Subject"
        req_type = d["request_type"] or "Request"
        regulation = d["regulation"] or "GDPR"

        try:
            from modules.sentinel.jurisdictions import get_dsr_deadline_days, get_authority_short
            dsr_window = get_dsr_deadline_days(regulation)
            authority = get_authority_short(regulation)
        except Exception:
            dsr_window = 30
            authority = "DPA"

        try:
            deadline = datetime.strptime(d["deadline_date"][:10], "%Y-%m-%d").date()
        except Exception:
            continue

        days_left = (deadline - now).days

        if days_left < 0:
            # Overdue — emit event + notify
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
            # Alert approaching deadline
            if dpo:
                _send_dsr_alert(dpo, ref, name, req_type, days_left, str(deadline),
                                regulation=regulation, authority=authority, dsr_window=dsr_window)
            _notify_admins("sentinel",
                f"DSR Deadline: {days_left} day{'s' if days_left > 1 else ''} remaining — {ref}",
                f"{regulation}: {req_type} from {name} is due in {days_left} day(s) "
                f"({deadline}). Notify {authority} if unable to respond.",
                "/sentinel/dsr")

    log.info("Sentinel: DSR deadline check complete (%d open DSRs checked)", len(open_dsrs))


def _send_dsr_alert(to: str, ref: str, name: str, req_type: str,
                    days_left: int, deadline: str,
                    regulation: str = "GDPR", authority: str = "DPA",
                    dsr_window: int = 30) -> None:
    urgency_color = "#dc2626" if days_left == 1 else "#f59e0b" if days_left == 3 else "#2563eb"
    body = f"""
<div style="font-family:sans-serif;max-width:600px;margin:0 auto">
  <div style="background:{urgency_color};color:white;padding:20px 24px;border-radius:8px 8px 0 0">
    <h2 style="margin:0;font-size:18px">DSR Deadline: {days_left} Day{'s' if days_left > 1 else ''} Remaining</h2>
    <p style="margin:8px 0 0;opacity:.85;font-size:13px">
      {_esc(regulation)} — {dsr_window}-day data subject request response requirement
    </p>
  </div>
  <div style="border:1px solid #e5e7eb;border-top:none;padding:24px;border-radius:0 0 8px 8px">
    <table style="width:100%;border-collapse:collapse;font-size:14px;margin:16px 0">
      <tr><td style="padding:8px 0;color:#6b7280;width:40%">Reference</td>
          <td style="font-weight:700">{_esc(ref)}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Requester</td>
          <td>{_esc(name)}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Request type</td>
          <td>{_esc(req_type)}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Regulation</td>
          <td>{_esc(regulation)}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Authority</td>
          <td>{_esc(authority)}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Deadline</td>
          <td style="font-weight:700;color:{urgency_color}">{_esc(deadline)}</td></tr>
      <tr><td style="padding:8px 0;color:#6b7280">Days remaining</td>
          <td style="font-weight:700;color:{urgency_color}">{days_left}</td></tr>
    </table>
    <p style="font-size:13px;color:#6b7280">
      Data subject requests must be responded to within the timeframe required by
      {_esc(regulation)}. Extensions must be communicated to the data subject.
    </p>
  </div>
</div>"""
    _send(to=to,
          subject=f"[DSR Alert — {days_left}d] {regulation}: {req_type} due {deadline} — {ref}",
          body_html=body)


# ─────────────────────────────────────────────────────────────────────────────
# Job 3 — Retention review monitor  (weekly Monday 07:00)
# ─────────────────────────────────────────────────────────────────────────────

def _retention_review_check() -> None:
    log.info("Sentinel: running retention review check")
    db = get_db()
    try:
        due = db.execute(
            "SELECT id, category, data_type, retention_period, owner, review_date "
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
