"""
ThemisIQ — Reminder auto-scheduler.

Automatically processes the email_reminders table every 5 minutes,
sending any reminders whose remind_at has passed.

This replaces the need for an admin to manually call POST /api/reminders/send-due.
Reminder creation still happens via the /api/reminders endpoint.
"""
from __future__ import annotations

import logging
from datetime import timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import get_db_background as get_db  # scheduler: fail-fast, never block UI
from core.email import send_email
from core.timeutils import utcnow

log = logging.getLogger("aegis.reminders")

_scheduler: BackgroundScheduler | None = None

# ─────────────────────────────────────────────────────────────────────────────
# Email template for reminders
# ─────────────────────────────────────────────────────────────────────────────

def _reminder_html(title: str, message: str, module: str, remind_at: str) -> str:
    mod_label = (module or "platform").upper()
    body = (message or "This is your scheduled ThemisIQ reminder.").replace("\n", "<br>")
    return f"""
    <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:24px">
      <div style="background:#1e3a8a;color:white;padding:16px 20px;border-radius:8px 8px 0 0">
        <div style="font-size:11px;font-weight:700;letter-spacing:1px;opacity:.7;text-transform:uppercase">ThemisIQ · {mod_label}</div>
        <div style="font-size:18px;font-weight:700;margin-top:4px">⏰ {title}</div>
      </div>
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 8px 8px;padding:20px">
        <p style="color:#1e293b;font-size:14px;line-height:1.6">{body}</p>
        <p style="color:#94a3b8;font-size:11px;margin-top:16px;border-top:1px solid #e2e8f0;padding-top:12px">
          Scheduled for: {remind_at}<br>
          This reminder was set up in ThemisIQ. You can manage your reminders in the platform.
        </p>
      </div>
    </div>
    """


# ─────────────────────────────────────────────────────────────────────────────
# Job
# ─────────────────────────────────────────────────────────────────────────────

def _process_due_reminders() -> None:
    """Send all email reminders whose remind_at has passed and reschedule recurring ones."""
    db = get_db()
    try:
        _now_str = utcnow().strftime("%Y-%m-%d %H:%M:%S")
        due = db.execute(
            "SELECT * FROM email_reminders "
            "WHERE is_sent = 0 AND remind_at <= %s "
            "ORDER BY remind_at ASC LIMIT 50",
            (_now_str,)
        ).fetchall()

        if not due:
            return

        log.info("Reminder scheduler: %d due reminder(s)", len(due))

        for r in due:
            rid    = r["id"]
            title  = r["title"] or "Reminder"
            msg    = r["message"] or ""
            module = r["module"] or "platform"
            to     = r["recipient_email"] or ""

            if not to:
                # No email address — just mark sent
                db.execute("UPDATE email_reminders SET is_sent=1, sent_at=CURRENT_TIMESTAMP WHERE id=%s", (rid,))
                continue

            result = send_email(
                to=to,
                subject=f"[ThemisIQ] {title}",
                body_html=_reminder_html(title, msg, module, r["remind_at"] or ""),
            )

            if result.get("ok"):
                db.execute(
                    "UPDATE email_reminders SET is_sent=1, sent_at=CURRENT_TIMESTAMP WHERE id=%s",
                    (rid,),
                )
                log.info("Reminder sent → %s | %s (provider: %s)", to, title, result.get("provider"))

                # Reschedule recurring reminders
                interval = (r["repeat_interval"] or "none").lower()
                if interval in ("daily", "weekly", "monthly"):
                    offset = {"daily": "+1 day", "weekly": "+7 days", "monthly": "+1 month"}[interval]
                    try:
                        db.execute(
                            "INSERT INTO email_reminders "
                            "(module, entity_type, entity_id, title, message, "
                            " recipient_id, recipient_email, remind_at, repeat_interval, created_by) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,datetime(%s,%s),%s,%s)",
                            (
                                r["module"], r["entity_type"], r["entity_id"],
                                r["title"], r["message"],
                                r["recipient_id"], r["recipient_email"],
                                r["remind_at"], offset,
                                r["repeat_interval"], r["created_by"],
                            ),
                        )
                    except Exception as exc:
                        log.warning("Failed to reschedule reminder %d: %s", rid, exc)
            else:
                log.warning("Reminder email failed for id=%d: %s", rid, result.get("error", "unknown"))

        db.commit()

    except Exception as exc:
        log.error("Reminder scheduler job failed: %s", exc)
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _process_due_reminders,
        IntervalTrigger(minutes=5),
        id="reminder_processor",
        replace_existing=True,
        misfire_grace_time=60,
    )
    _scheduler.start()
    log.info("Reminder scheduler started — processing every 5 minutes")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Reminder scheduler stopped")
