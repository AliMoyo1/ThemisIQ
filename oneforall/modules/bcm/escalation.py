"""
BCM incident acknowledgement and escalation (plans/2026-10-governance-rework/13).

A declared incident has a commander. How long the commander has to acknowledge it depends on the severity. When the window
ends with no acknowledgement, the BCM managers who can open the incident are told once, in the app and by a critical email
(a reference and a link, never a title). This module is the policy (the windows, the due time, the state, who is the
alternate) and the job that applies it. The data service stores the clock; nothing here edits an incident's own facts.
"""
import logging
from datetime import datetime, timedelta

from core.timeutils import utcnow

log = logging.getLogger("bcm.escalation")

# Minutes the commander has to acknowledge, by severity. Low has no clock.
WINDOWS = {"critical": 15, "high": 30, "medium": 60}
# The tier names the Sentinel breach handler writes for the incident it opens (core/event_handlers.py).
_ALIASES = {"major": "high", "significant": "medium"}
DONE = ("resolved", "closed")
_FORMAT = "%Y-%m-%d %H:%M:%S"


def window_minutes(severity) -> "int | None":
    key = str(severity or "").strip().lower()
    return WINDOWS.get(_ALIASES.get(key, key))


def is_live(status) -> bool:
    return str(status or "").strip().lower() not in DONE


def stamp(moment) -> str:
    return moment.strftime(_FORMAT)


def parse(value) -> "datetime | None":
    text = str(value or "").strip().replace("T", " ")[:19]
    try:
        return datetime.strptime(text, _FORMAT)
    except ValueError:
        return None


def due_from(severity, now) -> "str | None":
    """When an incident of this severity declared (or handed over) now must be acknowledged by; None when it has no clock."""
    minutes = window_minutes(severity)
    return stamp(now + timedelta(minutes=minutes)) if minutes else None


# ── The clock, as columns to store ──────────────────────────────────────────

def new_clock(severity, status, commander_user_id, actor_id, now) -> dict:
    """The clock columns of an incident being declared. A person who names themselves as commander has acknowledged by
    doing so: they plainly know, and an alarm 15 minutes later would only teach people to ignore it."""
    due = due_from(severity, now) if is_live(status) else None
    out = {"ack_due_at": due, "acknowledged_at": None, "acknowledged_by": None, "escalated_at": None}
    if due and commander_user_id and commander_user_id == actor_id:
        out.update(acknowledged_at=stamp(now), acknowledged_by=actor_id)
    return out


def clock_after_update(before: dict, data: dict, actor_id, now) -> dict:
    """The clock columns to change when `data` is applied to an incident that is `before`. {} when nothing restarts.

    A new commander must acknowledge (the clock restarts), and so must the commander of an incident that is reopened. A
    raised severity shortens the time left; a lowered one never lengthens it, or editing the severity would be a way to
    switch the clock off."""
    status = data.get("status", before.get("status"))
    severity = data.get("severity", before.get("severity"))
    commander = data.get("commander_user_id", before.get("commander_user_id"))
    reopened = (not is_live(before.get("status"))) and is_live(status)
    handed_over = "commander_user_id" in data and data["commander_user_id"] != before.get("commander_user_id")
    if (reopened or handed_over) and is_live(status):
        return new_clock(severity, status, commander, actor_id, now)
    if "severity" in data and is_live(status) and not before.get("acknowledged_at"):
        due = due_from(severity, now)
        if due and (not before.get("ack_due_at") or due < before["ack_due_at"]):
            return {"ack_due_at": due}
    return {}


# ── What a person is shown ──────────────────────────────────────────────────

def state(inc: dict, now=None) -> str:
    """none | awaiting | overdue | escalated | acknowledged."""
    if inc.get("acknowledged_at"):
        return "acknowledged"
    if not inc.get("ack_due_at"):
        return "none"
    if inc.get("escalated_at"):
        return "escalated"
    due = parse(inc["ack_due_at"])
    return "overdue" if due and due <= (now or utcnow()) else "awaiting"


def with_state(inc: dict, now=None, names: "dict | None" = None) -> dict:
    """The incident with the state of its clock added: ack_state, ack_minutes (the window of its severity) and, when it
    was acknowledged, the name of the person."""
    out = dict(inc)
    out["ack_state"] = state(inc, now)
    out["ack_minutes"] = window_minutes(inc.get("severity"))
    out["acknowledged_by_name"] = (names or {}).get(inc.get("acknowledged_by"))
    return out


# ── Who is the alternate ────────────────────────────────────────────────────

_PERSON_COLUMNS = "id, username, email, full_name, org_id, is_super_admin, business_unit_id"


def can_open(person: dict, incident: dict) -> bool:
    """The module's own rule for an incident: no unit means the whole organization, otherwise the person's unit tree."""
    from core.rbac import has_capability
    from modules.governance.data_service import bu_scope_ids
    if not has_capability(person, "module.bcm.access"):
        return False
    licensed = person.get("licensed_modules")
    if licensed is not None and "bcm" not in licensed:
        return False
    scope = bu_scope_ids(person)
    unit = incident.get("business_unit_id")
    return scope is None or unit is None or unit in scope


def alternates(db, org_id, incident: dict) -> list:
    """Ids of the people to tell when nobody acknowledged: the BCM managers of the organization who can open the incident
    and, when there is none, the organization's super administrators who can. Never a platform operator, and nobody who
    could not open the incident: a message must not reveal a case to a person who cannot open it."""
    from core import email_outbox
    for roles in (("bcm_manager",), ("super_admin",)):
        found = []
        for user_id in email_outbox.organization_people(db, org_id, roles):
            row = db.execute(f"SELECT {_PERSON_COLUMNS} FROM users WHERE id = %s", (user_id,)).fetchone()
            if row and can_open(email_outbox.user_for_scope(db, row), incident):
                found.append(user_id)
        if found:
            return found
    return []


# ── The job ─────────────────────────────────────────────────────────────────

_DUE_SQL = (
    "SELECT id, severity, status, business_unit_id, commander_user_id, ack_due_at FROM bcm_incidents "
    "WHERE ack_due_at IS NOT NULL AND ack_due_at <= %s AND acknowledged_at IS NULL AND escalated_at IS NULL "
    "AND LOWER(COALESCE(status, '')) NOT IN ('resolved', 'closed') ORDER BY ack_due_at, id LIMIT 100")


def _note(db, incident_id, text) -> None:
    db.execute("INSERT INTO bcm_incident_updates (incident_id, author, note) VALUES (%s, %s, %s)",
               (incident_id, "System", text))


def _tell_alternates(db, org_id, inc, minutes) -> int:
    """In-app notices and critical emails to the alternates of one incident; returns how many were told. Reference only:
    the title stays in the incident."""
    from core import email_outbox
    people = alternates(db, org_id, inc)
    link = f"/bcm/?open=incident:{inc['id']}"
    reference = f"INC-{inc['id']}"
    for user_id in people:
        db.execute(
            "INSERT INTO notifications (user_id, module, title, message, link) VALUES (%s, %s, %s, %s, %s)",
            (user_id, "bcm", f"Incident {reference} was not acknowledged",
             f"Nobody acknowledged incident {reference} within {minutes} minutes. Open it to take it over or to name a "
             "commander.", link))
        email_outbox.enqueue_safely(
            db, "bcm.escalation", recipient_user_id=user_id, org_id=org_id, route=link,
            fields={"reference": reference, "minutes": minutes}, source=("bcm", "escalation", inc["id"]),
            purpose="escalation", threshold=str(inc["ack_due_at"]))
    if not people:
        # Nobody who can open it could be told. The administrators are told, in the app and without the reference, that
        # the organization has no one in that position: a configuration to fix, not a case to read.
        for user_id in email_outbox.organization_people(db, org_id, email_outbox.ADMIN_ROLES):
            db.execute(
                "INSERT INTO notifications (user_id, module, title, message, link) VALUES (%s, %s, %s, %s, %s)",
                (user_id, "bcm", "A BCM incident was not acknowledged",
                 "An incident was not acknowledged in time and no BCM manager who can open it could be told. Assign a "
                 "BCM manager to the business unit.", "/bcm/"))
    return len(people)


def escalate_due(db, org_id, now=None) -> int:
    """Escalate, once, every live incident of this organization whose window ended without an acknowledgement. Returns how
    many were escalated. Safe to run again and from two workers: the claim is one conditional update, and the notices and
    the email requests are written in the same transaction, so a worker that dies leaves the incident to be tried again."""
    now = now or utcnow()
    escalated = 0
    for row in db.execute(_DUE_SQL, (stamp(now),)).fetchall():
        inc = dict(row)
        claim = db.execute(
            "UPDATE bcm_incidents SET escalated_at = %s WHERE id = %s AND escalated_at IS NULL AND acknowledged_at IS NULL",
            (stamp(now), inc["id"]))
        if getattr(claim, "rowcount", 0) != 1:
            db.rollback()
            continue
        minutes = window_minutes(inc["severity"]) or 0
        try:
            told = _tell_alternates(db, org_id, inc, minutes)
            _note(db, inc["id"], f"Not acknowledged within {minutes} minutes. "
                  + ("The BCM managers were told." if told else "Nobody who can open it could be told."))
            db.commit()
        except Exception:
            db.rollback()
            log.exception("BCM incident %s could not be escalated", inc["id"])
            continue
        escalated += 1
        try:
            from core.middleware import log_audit
            log_audit(None, "bcm", "incident_escalated", "incident", inc["id"],
                      details=f"Not acknowledged within {minutes} minutes; {told} alternate(s) told", org_id=org_id)
        except Exception:
            log.warning("The escalation of incident %s was made but its audit entry was not written", inc["id"])
    return escalated


def run_all_tenants() -> int:
    """The scheduled job: one pass in every organization, bound to it (a bare connection sees none of a tenant's rows)."""
    from core import email_outbox
    from database import get_db_background

    def one(org_id):
        db = get_db_background()
        try:
            return escalate_due(db, org_id)
        finally:
            db.close()

    return sum(n for n in email_outbox.for_each_tenant(one, "BCM incident escalation") if isinstance(n, int))
