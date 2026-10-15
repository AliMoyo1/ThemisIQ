"""
ThemisIQ - Reminder auto-scheduler.

Processes the email_reminders table every 5 minutes, sending any reminder whose remind_at has passed, and delivers what
the email outbox holds (core/email_outbox.py).

A reminder is marked sent only when the provider accepted it (plans/2026-10-governance-rework/06, phase E1). One with no
usable address is `suppressed` and stays visible; one that no provider is configured for stays due and says `logged_only`;
a failed one is retried up to five times and then stops as `permanent_failure`. Nothing is recorded as sent because it
was logged.

Reminder creation still happens via the /api/reminders endpoint.
"""
from __future__ import annotations

import calendar
import html
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import get_db_background as get_db  # scheduler: fail-fast, never block UI
from core import email as mail
from core.email import send_email
from core.timeutils import utcnow

log = logging.getLogger("aegis.reminders")

_scheduler: BackgroundScheduler | None = None

MAX_ATTEMPTS = 5


# ─────────────────────────────────────────────────────────────────────────────
# Email template for reminders
# ─────────────────────────────────────────────────────────────────────────────

def _reminder_parts(title: str, message: str, module: str, remind_at: str) -> tuple[str, str]:
    """(html, text) of one reminder. Every dynamic value is escaped; the text carries the same information."""
    mod_label = (module or "platform").upper()
    body_text = (message or "This is your scheduled ThemisIQ reminder.").strip()
    esc = html.escape
    body_html = esc(body_text).replace("\n", "<br>")
    page = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:0 auto;padding:24px">
      <div style="background:#1e3a8a;color:white;padding:16px 20px;border-radius:8px 8px 0 0">
        <div style="font-size:11px;font-weight:700;letter-spacing:1px;opacity:.7;text-transform:uppercase">ThemisIQ &middot; {esc(mod_label)}</div>
        <div style="font-size:18px;font-weight:700;margin-top:4px">Reminder: {esc(title)}</div>
      </div>
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-top:none;border-radius:0 0 8px 8px;padding:20px">
        <p style="color:#1e293b;font-size:14px;line-height:1.6">{body_html}</p>
        <p style="color:#94a3b8;font-size:11px;margin-top:16px;border-top:1px solid #e2e8f0;padding-top:12px">
          Scheduled for: {esc(str(remind_at))}<br>
          This reminder was set up in ThemisIQ. You can manage your reminders in the platform.
        </p>
      </div>
    </div>
    """
    text = (f"ThemisIQ ({mod_label})\nReminder: {title}\n\n{body_text}\n\nScheduled for: {remind_at}\n"
            "This reminder was set up in ThemisIQ. You can manage your reminders in the platform.")
    return page, text


def _next_time(remind_at: str, interval: str) -> str | None:
    """The time of the next occurrence of a recurring reminder, computed here so it works on every database."""
    try:
        base = datetime.strptime(str(remind_at).replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if interval == "daily":
        nxt = base + timedelta(days=1)
    elif interval == "weekly":
        nxt = base + timedelta(days=7)
    elif interval == "monthly":
        month = base.month % 12 + 1
        year = base.year + (1 if base.month == 12 else 0)
        nxt = base.replace(year=year, month=month, day=min(base.day, calendar.monthrange(year, month)[1]))
    else:
        return None
    return nxt.strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────────────────────────────────────
# Job
# ─────────────────────────────────────────────────────────────────────────────

def _process_due_reminders() -> None:
    """Send the email reminders whose remind_at has passed and reschedule the recurring ones that were accepted."""
    db = get_db()
    try:
        _now_str = utcnow().strftime("%Y-%m-%d %H:%M:%S")
        due = db.execute(
            "SELECT * FROM email_reminders "
            "WHERE is_sent = 0 AND remind_at <= %s "
            "AND COALESCE(delivery_status, '') NOT IN ('suppressed', 'permanent_failure') "
            "ORDER BY remind_at ASC LIMIT 50",
            (_now_str,)
        ).fetchall()

        if not due:
            return

        log.info("Reminder scheduler: %d due reminder(s)", len(due))

        for r in due:
            rid = r["id"]
            title = r["title"] or "Reminder"
            msg = r["message"] or ""
            module = r["module"] or "platform"
            to = (r["recipient_email"] or "").strip()

            if not mail.valid_address(to):
                db.execute(
                    "UPDATE email_reminders SET delivery_status = 'suppressed', "
                    "delivery_error = 'no valid recipient address' WHERE id = %s", (rid,))
                continue

            body_html, body_text = _reminder_parts(title, msg, module, r["remind_at"] or "")
            result = send_email(to=to, subject=f"ThemisIQ reminder: {title[:80]}", body_html=body_html,
                                body_text=body_text)
            status = result.get("status")

            if result.get("ok"):
                db.execute(
                    "UPDATE email_reminders SET is_sent = 1, sent_at = CURRENT_TIMESTAMP, "
                    "delivery_status = 'provider_accepted', delivery_error = NULL WHERE id = %s", (rid,))
                log.info("Reminder %d accepted by the provider (%s)", rid, result.get("provider"))

                interval = (r["repeat_interval"] or "none").lower()
                if interval in ("daily", "weekly", "monthly"):
                    when = _next_time(r["remind_at"], interval)
                    if when:
                        try:
                            db.execute(
                                "INSERT INTO email_reminders "
                                "(module, entity_type, entity_id, title, message, "
                                " recipient_id, recipient_email, remind_at, repeat_interval, created_by) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                (r["module"], r["entity_type"], r["entity_id"], r["title"], r["message"],
                                 r["recipient_id"], r["recipient_email"], when, r["repeat_interval"], r["created_by"]),
                            )
                        except Exception as exc:
                            log.warning("Failed to reschedule reminder %d: %s", rid, exc)
            elif status == mail.STATUS_LOGGED:
                db.execute(
                    "UPDATE email_reminders SET delivery_status = 'logged_only', "
                    "delivery_error = 'no mail provider is configured: nothing was sent' WHERE id = %s", (rid,))
            elif status == mail.STATUS_SUPPRESSED:
                db.execute(
                    "UPDATE email_reminders SET delivery_status = 'suppressed', delivery_error = %s WHERE id = %s",
                    (str(result.get("reason") or "suppressed")[:200], rid))
            else:
                attempts = (r["attempts"] or 0) + 1
                final = bool(result.get("permanent")) or attempts >= MAX_ATTEMPTS
                db.execute(
                    "UPDATE email_reminders SET attempts = %s, delivery_status = %s, delivery_error = %s WHERE id = %s",
                    (attempts, "permanent_failure" if final else "failed", str(result.get("error") or "send failed")[:200],
                     rid))
                log.warning("Reminder %d was not sent (attempt %d): %s", rid, attempts, result.get("error"))

        db.commit()

    except Exception as exc:
        log.error("Reminder scheduler job failed: %s", exc)
    finally:
        db.close()


def _process_all_tenants() -> None:
    """The scheduled job: every organization in turn. A scheduler has no request to take a tenant from, so a bare
    connection would see none of an organization's reminders."""
    from core.email_outbox import for_each_tenant
    for_each_tenant(lambda _org: _process_due_reminders(), "Email reminders")


def _deliver_outbox() -> None:
    """Send what the outbox holds, for every organization in turn."""
    try:
        from core.email_outbox import deliver_all_tenants
        deliver_all_tenants()
    except Exception as exc:
        log.error("Email outbox delivery failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _process_all_tenants,
        IntervalTrigger(minutes=5),
        id="reminder_processor",
        replace_existing=True,
        misfire_grace_time=60,
    )
    _scheduler.add_job(
        _deliver_outbox,
        IntervalTrigger(minutes=1),
        id="email_outbox",
        replace_existing=True,
        misfire_grace_time=30,
        max_instances=1,
    )
    _scheduler.start()
    log.info("Reminder scheduler started: reminders every 5 minutes, the email outbox every minute")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("Reminder scheduler stopped")
