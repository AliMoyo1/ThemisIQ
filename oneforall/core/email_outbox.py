"""
The email outbox (plans/2026-10-governance-rework/06 sections 3 and 6).

A source records its action, then asks for a message here. A worker, outside any request and outside the source's own
transaction, resolves the recipient at the moment of sending, renders a versioned template, sends it and records what
happened. The in-app notice and the source action stay the truth: a delivery state is a fact about mail, never about the
work, and a provider's acceptance is not proof that anyone read the message.

States of one delivery:

    queued, retry_due     waiting to be sent, now or after a backoff
    sending               leased by a worker for a few minutes
    provider_accepted     the provider took the message (not: it arrived, not: it was read)
    logged_only           no provider is configured: nothing left the platform
    suppressed            deliberately not sent, with the reason (person left, no address, not allowed to open the
                          record, the action is no longer open, preference off)
    permanent_failure     could not be sent and will not be retried, shown to an administrator

One delivery per organization, source action, recipient, purpose and threshold: asking twice is one message.
"""
import json
import logging
from datetime import datetime, timedelta

from core import email_templates as templates
from core.best_effort import swallowed
from core.timeutils import utcnow

log = logging.getLogger("oneforall.email_outbox")

QUEUED, SENDING, ACCEPTED, RETRY, FAILED, SUPPRESSED, LOGGED = (
    "queued", "sending", "provider_accepted", "retry_due", "permanent_failure", "suppressed", "logged_only")
LEASE_MINUTES = 5
MAX_ATTEMPTS = 5
BACKOFF_MINUTES = (5, 15, 60, 180, 360)
MAX_AGE_HOURS = 48
DAILY_CAP = 200          # provider accepted per UTC day for everything that is not critical; a setting may lower it
CRITICAL_CEILING = 2     # critical mail may go up to this multiple of the cap
PER_MINUTE = 20          # messages other than critical handed to the provider in one pass (a minute), all organizations
RETENTION_DAYS = 180     # an ended delivery is kept this long, then deleted (06 section 10, question 5)
_PRIORITY_RANK = {templates.CRITICAL: 0, templates.OPERATOR: 1, templates.ACTION: 2, templates.INFO: 3}
# The people who administer an organization. "admin" is the spelling older role lists used.
ADMIN_ROLES = ("super_admin", "org_admin", "admin")


def _stamp(moment=None) -> str:
    return (moment or utcnow()).strftime("%Y-%m-%d %H:%M:%S")


def dedupe_key(org_id, source, recipient_user_id, purpose, threshold="") -> str:
    module, kind, record_id = source
    return f"{org_id or 0}|{module}:{kind}:{record_id}|{recipient_user_id}|email|{purpose}|{threshold or ''}"


# ── Asking for a message ────────────────────────────────────────────────────

def enqueue(db, template_key, *, recipient_user_id, org_id, route, fields, source, purpose, threshold="",
            priority=None, send_after=None) -> "int | None":
    """Record that a message should go to one person. Returns the outbox id, or None when the template or its fields
    are not acceptable (nothing is queued, and the reason is logged without the field values).

    The caller owns the transaction and commits. Calling again for the same action, person, purpose and threshold
    returns the delivery that already exists, so a retried event never sends twice. A due date that moves is a new
    threshold."""
    template = templates.get(template_key)
    try:
        cleaned = templates.clean_fields(template, fields)
    except templates.TemplateError as exc:
        log.warning("Email not queued: %s", exc)
        return None
    if not templates.route_allowed(template, route):
        log.warning("Email not queued: route not allowed for %s", template_key)
        return None
    key = dedupe_key(org_id, source, recipient_user_id, purpose, threshold)
    prio = priority or template.priority
    db.execute(
        "INSERT INTO email_outbox (org_id, dedupe_key, template_key, template_version, priority, recipient_user_id, "
        "source_module, source_type, source_id, purpose, route, fields_json, status, next_attempt_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued',%s) ON CONFLICT(dedupe_key) DO NOTHING",
        (org_id, key, template_key, template.version, prio, recipient_user_id, source[0], source[1], source[2], purpose,
         route, json.dumps({k: v for k, v in (fields or {}).items() if k in (*template.fields, *template.optional)},
                           sort_keys=True), send_after))
    row = db.execute("SELECT id FROM email_outbox WHERE dedupe_key = %s", (key,)).fetchone()
    return row["id"] if row else None


def enqueue_safely(db, *args, **kwargs) -> "int | None":
    """`enqueue` for a producer that must never lose its own work to a mail problem."""
    try:
        return enqueue(db, *args, **kwargs)
    except Exception:
        swallowed("email outbox enqueue")
        return None


# ── Checks made at the moment of sending ────────────────────────────────────

_CAP_DONE = ("Closed", "Verification")      # a corrective action plan that no longer waits on the assignee
_BREACH_DONE = ("resolved", "closed", "contained")  # the states the Sentinel deadline monitor stops watching
_DSR_DONE = ("completed", "closed")


def _capabilities(user) -> set:
    from core.rbac import user_capabilities
    return user_capabilities(user)


def _still_open(db, row, user) -> bool:
    """Is the action this message is about still open, and still this person's? A reminder for work that was done,
    withdrawn or reassigned is not sent. The purpose says whose the message is: an escalation goes to the people the
    assignee answers to, and a reminder to the person who asked for it."""
    kind = (row["source_module"], row["source_type"])
    rid = row["source_id"]
    purpose = str(row["purpose"] or "")
    if kind == ("grid", "nc"):
        nc = db.execute(
            "SELECT status, assigned_to, cap_status FROM grid_non_conformances WHERE id = %s", (rid,)).fetchone()
        if not nc or nc["status"] == "closed" or (nc["cap_status"] or "") in _CAP_DONE:
            return False
        return purpose.startswith("escalation") or nc["assigned_to"] == user["id"]
    if kind == ("grid", "control"):
        ctrl = db.execute("SELECT status, assignee_id FROM grid_controls WHERE id = %s", (rid,)).fetchone()
        if not ctrl or ctrl["status"] == "Complete":
            return False
        if purpose.startswith("reminder"):
            return db.execute(
                "SELECT 1 FROM grid_reminders WHERE control_id = %s AND user_id = %s AND active = 1",
                (rid, user["id"])).fetchone() is not None
        return purpose.startswith("escalation") or ctrl["assignee_id"] == user["id"]
    if kind == ("grid", "digest"):
        sub = db.execute("SELECT active FROM grid_digest_subscriptions WHERE id = %s", (rid,)).fetchone()
        return bool(sub and sub["active"])
    if kind == ("evidence", "item"):
        item = db.execute(
            "SELECT status, expiry_date, owner_user_id, uploaded_by FROM evidence_items WHERE id = %s", (rid,)).fetchone()
        return bool(item and item["status"] == "current" and item["expiry_date"]
                    and (item["owner_user_id"] or item["uploaded_by"]) == user["id"])
    if kind == ("platform", "task"):
        task = db.execute("SELECT status, assigned_to FROM task_board WHERE id = %s", (rid,)).fetchone()
        return bool(task and task["status"] not in ("done", "cancelled") and task["assigned_to"] == user["id"])
    if kind == ("ai_governance", "intake"):
        from modules.governance.data_service import bu_scope_ids
        req = db.execute(
            "SELECT status, assigned_reviewer_id, business_unit_id FROM ai_use_intake_requests WHERE id = %s",
            (rid,)).fetchone()
        if not (req and req["status"] == "submitted" and req["assigned_reviewer_id"] == user["id"]):
            return False
        scope = bu_scope_ids(user)
        return "ai_use.review" in _capabilities(user) and (
            scope is None or req["business_unit_id"] is None or req["business_unit_id"] in scope)
    if kind == ("ai_governance", "decision"):
        from modules.governance.entity_scope import describe_record
        dec = db.execute(
            "SELECT status, assigned_decider_id, application_id FROM ai_use_decisions WHERE id = %s", (rid,)).fetchone()
        if not (dec and dec["status"] == "proposed" and dec["assigned_decider_id"] == user["id"]):
            return False
        return ("ai_use.decide" in _capabilities(user)
                and describe_record(db, ("governance", "application"), dec["application_id"], user) is not None)
    if kind == ("bcm", "incident"):
        inc = db.execute("SELECT status, commander_user_id FROM bcm_incidents WHERE id = %s", (rid,)).fetchone()
        return bool(inc and (inc["status"] or "").lower() not in ("closed", "resolved")
                    and inc["commander_user_id"] == user["id"])
    if kind == ("bcm", "escalation"):
        from modules.bcm import escalation
        inc = db.execute(
            "SELECT status, acknowledged_at, business_unit_id FROM bcm_incidents WHERE id = %s", (rid,)).fetchone()
        if not (inc and escalation.is_live(inc["status"]) and not inc["acknowledged_at"]):
            return False
        return escalation.can_open(user, {"business_unit_id": inc["business_unit_id"]})
    if kind == ("bcm", "exercise"):
        ex = db.execute("SELECT status, owner_id FROM bcm_exercises WHERE id = %s", (rid,)).fetchone()
        return bool(ex and (ex["status"] or "").lower() == "planned" and ex["owner_id"] == user["id"])
    if kind == ("sentinel", "breach"):
        breach = db.execute("SELECT status, notify_deadline FROM sentinel_breaches WHERE id = %s", (rid,)).fetchone()
        return bool(breach and (breach["status"] or "") not in _BREACH_DONE and breach["notify_deadline"])
    if kind == ("sentinel", "dsr"):
        dsr = db.execute("SELECT status FROM sentinel_dsr WHERE id = %s", (rid,)).fetchone()
        return bool(dsr and (dsr["status"] or "") not in _DSR_DONE)
    return True  # a kind with no check is sent; the template says only what the person's own access reveals


def user_for_scope(db, user_row) -> dict:
    """The user dict that scope checks (entity_scope, bu_scope_ids) take, built from a users row."""
    from core.auth import licensed_modules_for
    roles = [r["role_key"] for r in db.execute(
        "SELECT role_key FROM user_roles WHERE user_id = %s", (user_row["id"],)).fetchall()]
    return {"id": user_row["id"], "username": user_row["username"], "email": user_row["email"],
            "full_name": user_row["full_name"], "org_id": user_row["org_id"], "roles": roles,
            "is_super_admin": bool(user_row["is_super_admin"] or 0),
            "business_unit_id": user_row["business_unit_id"],
            "licensed_modules": licensed_modules_for(db, user_row["org_id"])}


def _may_open(db, row, person) -> bool:
    """A person is not told about a record they could not open. A kind that is not a linkable record has no such
    check and is allowed."""
    from modules.governance.entity_scope import canonical_key, describe_record, is_linkable
    key = canonical_key(row["source_module"], row["source_type"])
    if not is_linkable(key):
        return True
    return describe_record(db, key, row["source_id"], person) is not None


# Summaries a person asked for by name. The master switch for action mail does not turn them off, and the daily
# summary mode does not replace them.
OPTED_IN = ("summary.weekly", "summary.mywork")
PREFERENCE_KEYS = ("email.action", "email.mode", "email.weekly", "email.quiet", "email.utc_offset")
SUMMARY_HOUR = 7   # local hour at which a daily or weekly summary may first be sent


def _parse_quiet(value: str):
    """(start, end) in minutes since midnight from "22:00-07:00", or None."""
    try:
        start, end = str(value or "").split("-", 1)
        out = []
        for part in (start, end):
            hour, minute = part.strip().split(":", 1)
            hour, minute = int(hour), int(minute)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            out.append(hour * 60 + minute)
        return (out[0], out[1]) if out[0] != out[1] else None
    except (ValueError, AttributeError):
        return None


def preferences(db, user_id) -> dict:
    """What a person chose about their mail (profile page). Defaults: action mail on, one by one, no weekly summary, no
    quiet hours, UTC."""
    marks = ",".join(["%s"] * len(PREFERENCE_KEYS))
    raw = {r["pref_key"]: str(r["pref_value"] or "").strip() for r in db.execute(
        f"SELECT pref_key, pref_value FROM user_preferences WHERE user_id = %s AND pref_key IN ({marks})",
        (user_id, *PREFERENCE_KEYS)).fetchall()}
    try:
        offset = int(raw.get("email.utc_offset") or 0)
    except ValueError:
        offset = 0
    return {
        "action": raw.get("email.action", "").lower() not in ("off", "0", "false", "no"),
        "mode": "daily" if raw.get("email.mode", "").lower() == "daily" else "immediate",
        "weekly": raw.get("email.weekly", "").lower() in ("on", "1", "true", "yes"),
        "quiet": _parse_quiet(raw.get("email.quiet", "")),
        "utc_offset": max(-720, min(840, offset)),
    }


def local_now(prefs: dict, now):
    return now + timedelta(minutes=prefs["utc_offset"])


def quiet_until(prefs: dict, now):
    """The UTC moment a person's quiet hours end, when `now` is inside them; else None."""
    window = prefs.get("quiet")
    if not window:
        return None
    start, end = window
    local = local_now(prefs, now)
    minutes = local.hour * 60 + local.minute
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if start < end:
        if not start <= minutes < end:
            return None
        ends_local = midnight + timedelta(minutes=end)
    else:  # overnight, such as 22:00 to 07:00
        if minutes >= start:
            ends_local = midnight + timedelta(days=1, minutes=end)
        elif minutes < end:
            ends_local = midnight + timedelta(minutes=end)
        else:
            return None
    return ends_local - timedelta(minutes=prefs["utc_offset"])


def _accepted_today(db, now) -> int:
    start = now.strftime("%Y-%m-%d") + " 00:00:00"
    return db.execute(
        "SELECT COUNT(*) FROM email_outbox WHERE status = 'provider_accepted' AND sent_at >= %s", (start,)).fetchone()[0]


def _set(db, row_id, **cols):
    sets = ", ".join(f"{k} = %s" for k in cols)
    db.execute(f"UPDATE email_outbox SET {sets} WHERE id = %s", [*cols.values(), row_id])


# ── Sending ─────────────────────────────────────────────────────────────────

def _deliver_one(db, row, now, cap, calls=None) -> str:
    """Send one delivery, or decide not to. `calls` (a list) gets an item when the provider was actually called, which is
    what the per minute budget counts: a suppression or a postponement is a local decision and costs nothing."""
    from core import email as mail
    template = templates.get(row["template_key"])
    user_row = db.execute(
        "SELECT id, username, email, full_name, org_id, is_active, is_super_admin, business_unit_id FROM users "
        "WHERE id = %s", (row["recipient_user_id"],)).fetchone()

    def done(status, **extra):
        _set(db, row["id"], status=status, leased_until=None, **extra)
        return status

    if not user_row or not user_row["is_active"]:
        return done(SUPPRESSED, suppress_reason="recipient_inactive")
    if row["org_id"] is not None and user_row["org_id"] is not None and user_row["org_id"] != row["org_id"] \
            and not user_row["is_super_admin"]:
        return done(SUPPRESSED, suppress_reason="recipient_in_another_organization")
    address = (user_row["email"] or "").strip()
    if not mail.valid_address(address):
        return done(SUPPRESSED, suppress_reason="no_valid_address")
    person = user_for_scope(db, user_row)
    prefs = preferences(db, user_row["id"])
    asked_for = row["template_key"] in OPTED_IN
    if row["priority"] in (templates.ACTION, templates.INFO) and not prefs["action"] and not asked_for:
        return done(SUPPRESSED, suppress_reason="preference_off")
    if row["priority"] == templates.ACTION and prefs["mode"] == "daily" and not asked_for:
        return done(SUPPRESSED, suppress_reason="in_daily_summary")
    if not _still_open(db, row, person):
        return done(SUPPRESSED, suppress_reason="no_longer_open")
    if not _may_open(db, row, person):
        return done(SUPPRESSED, suppress_reason="not_allowed_to_open_the_record")
    if row["priority"] != templates.CRITICAL:
        until = quiet_until(prefs, now)
        if until is not None:  # not an attempt: it waits for the person's quiet hours to end, then is checked again
            return done(RETRY, next_attempt_at=_stamp(until), last_error="quiet hours; postponed")

    accepted = _accepted_today(db, now)
    ceiling = cap * CRITICAL_CEILING if row["priority"] == templates.CRITICAL else cap
    if accepted >= ceiling:
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=10, second=0)
        return done(RETRY, next_attempt_at=_stamp(tomorrow), last_error="daily cap reached; postponed")

    try:
        fields = json.loads(row["fields_json"] or "{}")
        message = templates.render(row["template_key"], fields, row["route"], mail.app_origin())
    except templates.TemplateError as exc:
        return done(FAILED, suppress_reason="template_error", last_error=str(exc)[:200])

    db.commit()  # the checks above only read: no transaction is held open while the provider is called
    if calls is not None:
        calls.append(row["id"])
    result = mail.send_email(to=address, subject=message["subject"], body_html=message["html"],
                             body_text=message["text"])
    status = result.get("status")
    attempts = (row["attempts"] or 0) + 1
    provider = result.get("provider")
    if status == mail.STATUS_ACCEPTED:
        return done(ACCEPTED, attempts=attempts, provider=provider, sent_at=_stamp(now), last_error=None)
    if status == mail.STATUS_LOGGED:
        return done(LOGGED, attempts=attempts, provider=provider, last_error="no provider is configured")
    if status == mail.STATUS_SUPPRESSED:
        return done(SUPPRESSED, attempts=attempts, suppress_reason=result.get("reason") or "suppressed")
    # failed: retry with a backoff until the attempts or the age run out
    created = row["created_at"]
    try:
        age = now - datetime.strptime(str(created)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        age = timedelta(0)
    permanent = bool(result.get("permanent")) or attempts >= MAX_ATTEMPTS or age > timedelta(hours=MAX_AGE_HOURS)
    error = str(result.get("error") or "send failed")[:200]
    critical = row["priority"] == templates.CRITICAL
    if permanent:
        outcome = done(FAILED, attempts=attempts, provider=provider, last_error=error)
        if critical:
            _tell_administrators(db, row, attempts)
        return outcome
    wait = BACKOFF_MINUTES[min(attempts - 1, len(BACKOFF_MINUTES) - 1)]
    outcome = done(RETRY, attempts=attempts, provider=provider, last_error=error,
                   next_attempt_at=_stamp(now + timedelta(minutes=wait)))
    if critical and attempts == 1:
        # Not a silent retry until after the deadline: someone is told at the first failure that a human contact
        # may be needed, while the retries continue (06 section 3).
        _tell_administrators(db, row, attempts)
    return outcome


def _tell_administrators(db, row, attempts: int = 1) -> None:
    """A critical message that could not be sent is shown to the people who manage email, in the app, so it is not lost
    with the mail."""
    try:
        marks = ",".join(["%s"] * len(ADMIN_ROLES))
        admins = db.execute(
            "SELECT DISTINCT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id "
            f"WHERE ur.role_key IN ({marks}) AND u.is_active = 1 "
            "AND (u.org_id = %s OR u.org_id IS NULL OR %s IS NULL)",
            (*ADMIN_ROLES, row["org_id"], row["org_id"])).fetchall()
        message = ("A critical message could not be accepted by the mail provider. Check the delivery queue and follow "
                   "the contact runbook." if attempts <= 1 else
                   f"A critical message was not accepted by the mail provider after {attempts} attempts and will not be "
                   "retried. Follow the contact runbook.")
        for admin in admins:
            db.execute(
                "INSERT INTO notifications (user_id, module, title, message, link) VALUES (%s,%s,%s,%s,%s)",
                (admin["id"], "platform", "A critical notification could not be sent by email", message,
                 "/admin/email"))
    except Exception:
        swallowed("email outbox administrator notice")


PAUSE_KEY = "email_outbox_paused"


def is_paused(db) -> bool:
    """Has an administrator paused sending (06 section 7: drain the old queue deliberately before a provider switch)?
    A pause holds everything except critical mail, so a pause that is forgotten never costs a deadline alert."""
    row = db.execute("SELECT value FROM settings WHERE key = %s", (PAUSE_KEY,)).fetchone()
    return bool(row and str(row["value"]).strip().lower() in ("1", "true", "yes", "on"))


def set_paused(db, paused: bool) -> None:
    db.execute(
        "INSERT INTO settings(key, value) VALUES (%s, %s) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (PAUSE_KEY, "1" if paused else "0"))


def deliver_due(db=None, *, now=None, limit=50, cap=None, per_minute=None, budget=None) -> dict:
    """Send what is due. Safe to run from several workers: a row is leased with a compare-and-set before it is sent, and
    nothing is held open while the provider is called.

    At most `per_minute` messages other than critical go to the provider in one pass. Every organization sends through
    the same account, so the worker passes one `budget` ({"n": remaining}) to all of them; critical mail is neither
    counted nor held. A message left over stays queued for the next minute."""
    own = db is None
    if own:
        from database import get_db_background
        db = get_db_background()
    now = now or utcnow()
    cap = cap or DAILY_CAP
    if budget is None:
        budget = {"n": PER_MINUTE if per_minute is None else int(per_minute)}
    summary = {"examined": 0, ACCEPTED: 0, LOGGED: 0, SUPPRESSED: 0, RETRY: 0, FAILED: 0}
    try:
        stamp = _stamp(now)
        only_critical = "AND priority = 'critical' " if is_paused(db) else ""
        # Waiting rows, and rows a worker leased and never finished (it died): their lease has run out
        due = db.execute(
            "SELECT * FROM email_outbox WHERE "
            "((status IN ('queued', 'retry_due') AND (next_attempt_at IS NULL OR next_attempt_at <= %s) "
            "AND (leased_until IS NULL OR leased_until < %s)) OR (status = 'sending' AND leased_until < %s)) "
            + only_critical +
            "ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'operator' THEN 1 WHEN 'action' THEN 2 ELSE 3 END, id "
            "LIMIT %s", (stamp, stamp, stamp, int(limit))).fetchall()
        for row in due:
            if row["priority"] != templates.CRITICAL and budget["n"] <= 0:
                break  # ordered critical first: what is left is all ordinary mail, and it waits for the next minute
            claimed = db.execute(
                "UPDATE email_outbox SET status = 'sending', leased_until = %s WHERE id = %s "
                "AND (status IN ('queued', 'retry_due') OR (status = 'sending' AND leased_until < %s))",
                (_stamp(now + timedelta(minutes=LEASE_MINUTES)), row["id"], stamp))
            db.commit()
            if getattr(claimed, "rowcount", 1) != 1:
                continue
            summary["examined"] += 1
            calls: list = []
            try:
                outcome = _deliver_one(db, row, now, cap, calls)
            except Exception:
                swallowed("email outbox delivery")
                db.rollback()
                _set(db, row["id"], status=RETRY, leased_until=None, last_error="unexpected error",
                     next_attempt_at=_stamp(now + timedelta(minutes=15)), attempts=(row["attempts"] or 0) + 1)
                outcome = RETRY
            db.commit()
            summary[outcome] = summary.get(outcome, 0) + 1
            if calls and row["priority"] != templates.CRITICAL:
                budget["n"] -= 1
    finally:
        if own:
            db.close()
    return summary


# ── What an administrator sees ──────────────────────────────────────────────

def by_provider(db, *, days: int = 30, now=None) -> dict:
    """Deliveries of the last `days` days as {provider: {status: n}}: what a provider cutover is compared on (accepted,
    suppressed and failed under the old identity and under the new one). Rows never handed to a provider are under
    "none"."""
    since = _stamp((now or utcnow()) - timedelta(days=days))
    out: dict = {}
    for r in db.execute(
            "SELECT COALESCE(provider, 'none') AS provider, status, COUNT(*) AS n FROM email_outbox "
            "WHERE created_at >= %s GROUP BY COALESCE(provider, 'none'), status", (since,)).fetchall():
        out.setdefault(r["provider"], {})[r["status"]] = r["n"]
    return out


def summary(db) -> dict:
    counts = {r["status"]: r["n"] for r in db.execute(
        "SELECT status, COUNT(*) AS n FROM email_outbox GROUP BY status").fetchall()}
    attention = db.execute(
        "SELECT id, template_key, priority, source_module, source_type, source_id, status, suppress_reason, last_error, "
        "attempts, created_at FROM email_outbox WHERE status IN ('permanent_failure', 'logged_only', 'retry_due') "
        "ORDER BY CASE priority WHEN 'critical' THEN 0 ELSE 1 END, id DESC LIMIT 50").fetchall()
    return {"counts": counts, "attention": [dict(r) for r in attention], "paused": is_paused(db),
            "by_provider": by_provider(db)}


_ENDED = (ACCEPTED, SUPPRESSED, FAILED, LOGGED)


def purge_old(db, *, now=None, days: int = RETENTION_DAYS) -> int:
    """Delete the deliveries that ended more than `days` days ago and return how many. A delivery that is waiting,
    retrying or leased is never touched, however old. The deduplication key goes with the row: an action that is still
    open after that long and is asked for again is told once more, which is a reminder and not a duplicate."""
    cutoff = _stamp((now or utcnow()) - timedelta(days=int(days)))
    marks = ",".join(["%s"] * len(_ENDED))
    cur = db.execute(f"DELETE FROM email_outbox WHERE status IN ({marks}) AND created_at < %s", [*_ENDED, cutoff])
    return max(getattr(cur, "rowcount", 0) or 0, 0)


_PURGED_ON: dict = {}   # organization id -> the UTC day of the last purge made by this process


def _purge_once_a_day(db, org_id) -> None:
    today = utcnow().strftime("%Y-%m-%d")
    if _PURGED_ON.get(org_id) == today:
        return
    removed = purge_old(db)
    db.commit()
    _PURGED_ON[org_id] = today
    if removed:
        log.info("Email outbox: %d ended deliveries older than %d days removed (organization %s)", removed,
                 RETENTION_DAYS, org_id)


def requeue(db, outbox_id: int) -> bool:
    """Put a delivery that was logged only or failed back in the queue (an administrator's action, after fixing the
    configuration). Returns False when it was already sent or does not exist."""
    cur = db.execute(
        "UPDATE email_outbox SET status = 'queued', attempts = 0, next_attempt_at = NULL, leased_until = NULL, "
        "last_error = NULL WHERE id = %s AND status IN ('logged_only', 'permanent_failure', 'retry_due')", (outbox_id,))
    return getattr(cur, "rowcount", 0) == 1


def _tenant_entries(label: str) -> list:
    """The schemas a background mail job must visit, in stable organization order."""
    from database import list_active_tenants
    try:
        tenants = list_active_tenants()
    except Exception:
        swallowed(f"{label}: list of organizations")
        return []
    from config import settings
    tenants = sorted(tenants)
    if not settings.is_postgres():
        tenants = tenants[:1]  # one database holds every organization: a pass for each would repeat the same rows
    if not tenants:
        tenants = [(None, None)]  # an installation with no organization rows is one tenant: its own database
    return tenants


def for_each_tenant(job, label: str = "email job", *, tenants=None) -> list:
    """Run job(org_id) in each tenant schema. A caller may reuse one snapshot and choose its order.

    A scheduler has no request to take a tenant from: a bare connection stays on the public schema and sees none of an
    organization's rows. One organization failing is recorded and does not stop the others (the BCM and ARIA jobs use
    the same pattern)."""
    from database import tenant_context
    if tenants is None:
        tenants = _tenant_entries(label)
    results = []
    for org_id, slug in tenants:
        try:
            # Not as a super administrator: the shared users table is then limited to this organization by its policy
            with tenant_context(org_id, slug, is_super_admin=False):
                results.append(job(org_id))
        except Exception:
            swallowed(f"{label} for organization {org_id}")
    return results


def organization_people(db, org_id, roles) -> list:
    """Ids of the active users of an organization who hold one of `roles`, in id order.

    A platform operator (users.is_super_admin) is not part of an organization's staff: what an organization's work
    generates does not go to them (06 section 4: no tenant case detail to a platform operator without a support grant).
    A user with no organization recorded is treated as belonging to the single organization of an older installation."""
    roles = tuple(roles)
    if not roles:
        return []
    marks = ",".join(["%s"] * len(roles))
    rows = db.execute(
        "SELECT DISTINCT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id "
        f"WHERE ur.role_key IN ({marks}) AND u.is_active = 1 AND COALESCE(u.is_super_admin, 0) = 0 "
        "AND (%s IS NULL OR u.org_id = %s OR u.org_id IS NULL) ORDER BY u.id", [*roles, org_id, org_id]).fetchall()
    return [r["id"] for r in rows]


FAILURE_WINDOW_DAYS = 7


def report_failures(db, org_id, *, now=None) -> int:
    """Tell the administrators of an organization by email that messages could not be accepted (template
    delivery.failure): how many ended as a permanent failure in the last seven days, at most once a day for each count.
    A critical failure is shown in the app at once, separately; this covers the ordinary ones, whose address or
    recipient was wrong. The report is not itself counted as a failure it reports."""
    now = now or utcnow()
    since = _stamp(now - timedelta(days=FAILURE_WINDOW_DAYS))
    count = db.execute(
        "SELECT COUNT(*) FROM email_outbox WHERE status = 'permanent_failure' AND template_key != 'delivery.failure' "
        "AND created_at >= %s", (since,)).fetchone()[0]
    if not count:
        return 0
    asked = 0
    for uid in organization_people(db, org_id, ADMIN_ROLES):
        if enqueue_safely(db, "delivery.failure", recipient_user_id=uid, org_id=org_id, route="/admin/email",
                          fields={"count": count}, source=("platform", "email_queue", 0), purpose="failures",
                          threshold=f"{now:%Y-%m-%d}|{count}"):
            asked += 1
    db.commit()
    return asked


def _deliver_and_report(org_id, **kwargs) -> dict:
    got = deliver_due(**kwargs)
    from database import get_db_background
    db = get_db_background()
    try:
        _purge_once_a_day(db, org_id)
        report_failures(db, org_id)
        from modules.launcher import summary_mail
        summary_mail.ask_summaries(db, org_id)
    except Exception:
        swallowed(f"email failure report and summaries for organization {org_id}")
        db.rollback()
    finally:
        db.close()
    return got


def deliver_all_tenants(**kwargs) -> dict:
    """The worker's entry point: send what is due in every organization, one after the other, and tell its
    administrators about the messages that could not be accepted.

    Each organization gets a first share of the ordinary-mail budget. Unused shares are then available to the others.
    The first organization rotates so a budget smaller than the tenant count still reaches every tenant over time.
    Critical mail is checked for every tenant in the first pass and never spends the ordinary-mail budget."""
    totals: dict = {}
    tenants = _tenant_entries("email outbox delivery")
    if not tenants:
        return totals
    budget = kwargs.pop("budget", None)
    per_minute = kwargs.pop("per_minute", None)
    if budget is None:
        budget = {"n": PER_MINUTE if per_minute is None else int(per_minute)}
    allowance = max(0, int(budget["n"]))
    budget["n"] = allowance
    now = kwargs.get("now") or utcnow()
    minute = now.toordinal() * 1440 + now.hour * 60 + now.minute
    step = allowance if 0 < allowance < len(tenants) else 1
    offset = minute * step % len(tenants)
    tenants = tenants[offset:] + tenants[:offset]
    share, extra = divmod(allowance, len(tenants))
    shares = {org_id: share + (index < extra) for index, (org_id, _) in enumerate(tenants)}

    def first_pass(org_id):
        local = {"n": shares[org_id]}
        try:
            return _deliver_and_report(org_id, budget=local, **kwargs)
        finally:
            budget["n"] -= shares[org_id] - local["n"]

    def collect(got):
        for key, value in (got or {}).items():
            totals[key] = totals.get(key, 0) + value

    for got in for_each_tenant(first_pass, "email outbox delivery", tenants=tenants):
        collect(got)
    if budget["n"] > 0:
        for got in for_each_tenant(lambda _org: deliver_due(budget=budget, **kwargs),
                                   "email outbox spare capacity", tenants=tenants):
            collect(got)
    return totals
