"""
The daily and weekly "what needs you" summary (plans/2026-10-governance-rework/06 sections 3 and 4).

Only people who asked for one get one. The count is the count My Work shows that person, read through the same service
and the same scope, so the number in the message and the list behind its link are the same set; a message with nothing
to say is not sent. One message per person and period: the outbox key carries the local date or the ISO week.
"""
import logging
from datetime import timedelta

from core import email_outbox as outbox
from core.best_effort import swallowed
from core.timeutils import utcnow

log = logging.getLogger("oneforall.summary_mail")

# What My Work calls the things a person still has to do: not the changes, not what waits on someone else.
_OPEN_SECTIONS = ("needs_my_action", "due_soon", "overdue")
# A person with nothing waiting has no row to show that the period was checked: remember it for a while in this process.
_RECHECK_MINUTES = 30
_checked: dict = {}


def _period(prefs: dict, local):
    """(purpose, threshold) of the summary due for this person at their local time, or None."""
    if local.hour < outbox.SUMMARY_HOUR:
        return None
    if prefs["mode"] == "daily":
        return "daily", f"daily:{local:%Y-%m-%d}"
    if prefs["weekly"]:
        year, week, _ = local.isocalendar()
        return "weekly", f"weekly:{year}-W{week:02d}"
    return None


def ask_summaries(db, org_id, now=None) -> int:
    """Ask the outbox for the summaries that are due in this organization. Returns how many were asked for."""
    from modules.launcher import my_work_service
    now = now or utcnow()
    rows = db.execute(
        "SELECT DISTINCT u.id, u.username, u.email, u.full_name, u.org_id, u.is_super_admin, u.business_unit_id "
        "FROM users u JOIN user_preferences p ON p.user_id = u.id "
        "WHERE u.is_active = 1 AND (p.pref_key = 'email.mode' AND p.pref_value = 'daily' "
        "OR p.pref_key = 'email.weekly' AND p.pref_value = 'on') "
        "AND (u.org_id = %s OR u.org_id IS NULL OR %s IS NULL)", (org_id, org_id)).fetchall()
    asked = 0
    for row in rows:
        prefs = outbox.preferences(db, row["id"])
        due = _period(prefs, outbox.local_now(prefs, now))
        if due is None:
            continue
        purpose, threshold = due
        source = ("platform", "summary", row["id"])
        key = outbox.dedupe_key(org_id, source, row["id"], purpose, threshold)
        if db.execute("SELECT 1 FROM email_outbox WHERE dedupe_key = %s", (key,)).fetchone():
            continue
        last = _checked.get(key)
        if last is not None and now - last < timedelta(minutes=_RECHECK_MINUTES):
            continue
        _checked[key] = now
        try:
            person = outbox.user_for_scope(db, row)
            counts = my_work_service.get_my_work(person, page_size=1)["counts"]
        except Exception:
            swallowed(f"summary counts for user {row['id']}")
            db.rollback()
            continue
        count = sum(counts.get(name, 0) for name in _OPEN_SECTIONS)
        if count and outbox.enqueue_safely(
                db, "summary.mywork", recipient_user_id=row["id"], org_id=org_id, route="/my-work",
                fields={"count": count, "overdue": counts.get("overdue", 0)}, source=source, purpose=purpose,
                threshold=threshold):
            asked += 1
    db.commit()
    return asked
