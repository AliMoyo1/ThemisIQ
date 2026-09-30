"""
PLAN-36 P05: evidence collection campaigns -- request state machine and
campaign coordination.

Confirmed by direct research (not assumed) before writing this: GRID's own
grid_evidence_items/files cannot be generalized here (hard FK'd to
grid_controls, no org_id, no request-before-a-file-exists phase, no
module/entity_type polymorphism) -- this is new ground, matching
task_plan.md's own fallback design. evidence_requests.evidence_id always
points at the canonical Evidence Vault row (evidence_items); this module
never stores a file itself.

State machine: requested -> submitted -> in_review -> accepted (terminal)
               in_review -> returned -> submitted (resubmit)
               requested/submitted/in_review/returned -> overdue (scheduler,
                   due_date passed) -> submitted (late submission still allowed)
               any non-terminal -> cancelled (terminal, explicit reason, audited)

Reuses rather than reinvents: notifications (raw INSERT, same convention
every other module uses), task_board and calendar_events (polymorphic
module/entity_type/entity_id tagging, same convention evidence/GRID
already use), and email_reminders + core/reminder_scheduler.py's existing
5-minute drain job for reminder delivery -- no new per-module cron loop
for sending mail.
"""
from __future__ import annotations

import datetime as _dt

from core.timeutils import utcnow


class CampaignError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class NotFoundError(CampaignError):
    def __init__(self, message: str = "Not found."):
        super().__init__("NOT_FOUND", message, 404)


class ForbiddenError(CampaignError):
    def __init__(self, message: str = "You do not have access to this."):
        super().__init__("FORBIDDEN", message, 403)


class StaleVersionError(CampaignError):
    def __init__(self, message: str = "This changed since you last loaded it."):
        super().__init__("STALE_VERSION", message, 409)


class InvalidTransitionError(CampaignError):
    def __init__(self, message: str):
        super().__init__("INVALID_TRANSITION", message, 409)


_TERMINAL_STATUSES = ("accepted", "cancelled")
_REMINDER_WINDOW_DAYS = 3


def _now() -> str:
    return utcnow().isoformat()


def _remind_at_str(dt) -> str:
    """email_reminders.remind_at is compared as a plain string against
    strftime('%Y-%m-%d %H:%M:%S') in core/reminder_scheduler.py's own
    _process_due_reminders -- an ISO8601 'T'-separated value here would
    still often compare correctly by luck, but not reliably (ASCII 'T'
    sorts after the space in some rows and before digits in others
    depending on the exact strings involved). Match the real comparator's
    own format exactly rather than assume ISO8601 is safe."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(row):
    return dict(row) if row else None


def _notify(db, user_id, module, title, message, link):
    if not user_id:
        return
    db.execute(
        "INSERT INTO notifications (user_id, module, title, message, link) VALUES (%s,%s,%s,%s,%s)",
        (user_id, module, title, message, link),
    )


def _record_event(db, request_id, from_status, to_status, changed_by, notes=""):
    db.execute(
        "INSERT INTO evidence_request_events (request_id, from_status, to_status, changed_by, notes, changed_at) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (request_id, from_status, to_status, changed_by, notes or "", _now()),
    )


# ─────────────────────────────────────────────────────────────────────────
# Campaigns
# ─────────────────────────────────────────────────────────────────────────

def create_campaign(db, actor: dict, *, name: str, description: str = "",
                     due_date: str, start_date: str | None = None,
                     business_unit_id: int | None = None, recurrence: str = "none") -> dict:
    if not (name or "").strip():
        raise CampaignError("INVALID_INPUT", "A campaign name is required.", 422)
    if not due_date:
        raise CampaignError("INVALID_INPUT", "A due date is required.", 422)
    now = _now()
    db.execute(
        "INSERT INTO evidence_campaigns (org_id, business_unit_id, name, description, owner_user_id, "
        "start_date, due_date, status, recurrence, created_by, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s)",
        (actor["org_id"], business_unit_id, name.strip(), description or "", actor["id"],
         start_date, due_date, recurrence, actor["id"], now, now),
    )
    db.commit()
    campaign_id = db.execute(
        "SELECT id FROM evidence_campaigns WHERE org_id=%s ORDER BY id DESC LIMIT 1", (actor["org_id"],)
    ).fetchone()["id"]
    return get_campaign(db, actor, campaign_id)


def get_campaign(db, actor: dict, campaign_id: int) -> dict | None:
    row = db.execute(
        "SELECT * FROM evidence_campaigns WHERE id=%s AND org_id=%s", (campaign_id, actor["org_id"]),
    ).fetchone()
    return _row_to_dict(row)


def list_campaigns(db, actor: dict, *, status: str | None = None) -> list[dict]:
    q = "SELECT * FROM evidence_campaigns WHERE org_id=%s"
    params: list = [actor["org_id"]]
    if status:
        q += " AND status=%s"
        params.append(status)
    q += " ORDER BY due_date ASC"
    return [dict(r) for r in db.execute(q, params).fetchall()]


def campaign_coverage(db, actor: dict, campaign_id: int) -> dict:
    """requested/submitted/in_review/accepted/returned/overdue/cancelled
    counts, plus 'uncovered' as an alias total of everything not yet
    accepted or cancelled -- task_plan.md's own named coverage fields."""
    campaign = get_campaign(db, actor, campaign_id)
    if campaign is None:
        raise NotFoundError("Campaign not found.")
    rows = db.execute(
        "SELECT status, COUNT(*) AS n FROM evidence_requests WHERE campaign_id=%s GROUP BY status",
        (campaign_id,),
    ).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    total = sum(counts.values())
    uncovered = total - counts.get("accepted", 0) - counts.get("cancelled", 0)
    return {
        "requested": counts.get("requested", 0), "submitted": counts.get("submitted", 0),
        "in_review": counts.get("in_review", 0), "accepted": counts.get("accepted", 0),
        "returned": counts.get("returned", 0), "overdue": counts.get("overdue", 0),
        "cancelled": counts.get("cancelled", 0), "total": total, "uncovered": uncovered,
    }


def close_campaign(db, actor: dict, campaign_id: int, *, force: bool = False, reason: str | None = None) -> dict:
    """Refuses to close while any request is non-terminal, unless force=True
    with a reason -- task_plan.md's own 'campaign close cannot hide
    unresolved/returned requests without explicit override and audit'."""
    campaign = get_campaign(db, actor, campaign_id)
    if campaign is None:
        raise NotFoundError("Campaign not found.")
    if campaign["status"] == "closed":
        return campaign
    coverage = campaign_coverage(db, actor, campaign_id)
    if coverage["uncovered"] > 0 and not force:
        raise InvalidTransitionError(
            f"{coverage['uncovered']} request(s) are not yet accepted or cancelled. "
            "Pass force with a reason to close anyway."
        )
    if force and not (reason or "").strip():
        raise CampaignError("INVALID_INPUT", "A reason is required to force-close with unresolved requests.", 422)
    now = _now()
    db.execute(
        "UPDATE evidence_campaigns SET status='closed', closed_at=%s, closed_by=%s, "
        "close_override_reason=%s, updated_at=%s WHERE id=%s",
        (now, actor["id"], reason if force else None, now, campaign_id),
    )
    if force and coverage["uncovered"] > 0:
        db.execute(
            "INSERT INTO audit_log (user_id, username, module, action, entity_type, entity_id, details, org_id) "
            "VALUES (%s,%s,'evidence_campaigns','force_close','evidence_campaign',%s,%s,%s)",
            (actor["id"], actor.get("username", ""), campaign_id,
             f"Force-closed campaign \"{campaign['name']}\" with {coverage['uncovered']} unresolved request(s): {reason}",
             actor["org_id"]),
        )
    db.commit()
    return get_campaign(db, actor, campaign_id)


# ─────────────────────────────────────────────────────────────────────────
# Requests
# ─────────────────────────────────────────────────────────────────────────

def create_request(db, actor: dict, *, campaign_id: int | None, module: str, entity_type: str,
                    entity_id: str, title: str, instructions: str = "", assignee_id: int,
                    reviewer_id: int, due_date: str, business_unit_id: int | None = None) -> dict:
    if not (title or "").strip():
        raise CampaignError("INVALID_INPUT", "A title is required.", 422)
    if not due_date:
        raise CampaignError("INVALID_INPUT", "A due date is required.", 422)
    if not assignee_id or not reviewer_id:
        raise CampaignError("INVALID_INPUT", "An assignee and a reviewer are required.", 422)
    if campaign_id is not None and get_campaign(db, actor, campaign_id) is None:
        raise NotFoundError("Campaign not found.")
    now = _now()
    db.execute(
        "INSERT INTO evidence_requests (org_id, business_unit_id, campaign_id, module, entity_type, "
        "entity_id, title, instructions, assignee_id, reviewer_id, due_date, status, lock_version, "
        "created_by, created_at, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'requested',1,%s,%s,%s)",
        (actor["org_id"], business_unit_id, campaign_id, module, entity_type, str(entity_id),
         title.strip(), instructions or "", assignee_id, reviewer_id, due_date,
         actor["id"], now, now),
    )
    request_id = db.execute(
        "SELECT id FROM evidence_requests WHERE org_id=%s ORDER BY id DESC LIMIT 1", (actor["org_id"],)
    ).fetchone()["id"]
    _record_event(db, request_id, None, "requested", actor["id"], "Request created")

    link = f"/evidence-campaigns/requests/{request_id}"
    _notify(db, assignee_id, "evidence_campaigns", "Evidence requested",
            f"\"{title.strip()}\" is due {due_date}.", link)
    db.execute(
        "INSERT INTO task_board (title, description, module, entity_type, entity_id, assigned_to, "
        "due_date, status, created_by, created_at, updated_at) "
        "VALUES (%s,%s,'evidence_campaigns','evidence_request',%s,%s,%s,'todo',%s,%s,%s)",
        (f"Submit evidence: {title.strip()}", instructions or "", request_id, assignee_id, due_date,
         actor["id"], now, now),
    )
    db.execute(
        "INSERT INTO calendar_events (title, description, event_type, module, entity_type, entity_id, "
        "start_date, end_date, assigned_to, status, created_by, created_at) "
        "VALUES (%s,%s,'deadline','evidence_campaigns','evidence_request',%s,%s,%s,%s,'scheduled',%s,%s)",
        (f"Evidence due: {title.strip()}", instructions or "", request_id, due_date, due_date,
         assignee_id, actor["id"], now),
    )
    db.commit()
    return get_request(db, actor, request_id)


def get_request(db, actor: dict, request_id: int) -> dict | None:
    row = db.execute(
        "SELECT * FROM evidence_requests WHERE id=%s AND org_id=%s", (request_id, actor["org_id"]),
    ).fetchone()
    return _row_to_dict(row)


def list_requests(db, actor: dict, *, campaign_id: int | None = None, assignee_id: int | None = None,
                   reviewer_id: int | None = None, status: str | None = None) -> list[dict]:
    q = "SELECT * FROM evidence_requests WHERE org_id=%s"
    params: list = [actor["org_id"]]
    if campaign_id is not None:
        q += " AND campaign_id=%s"
        params.append(campaign_id)
    if assignee_id is not None:
        q += " AND assignee_id=%s"
        params.append(assignee_id)
    if reviewer_id is not None:
        q += " AND reviewer_id=%s"
        params.append(reviewer_id)
    if status:
        q += " AND status=%s"
        params.append(status)
    q += " ORDER BY due_date ASC"
    return [dict(r) for r in db.execute(q, params).fetchall()]


def list_request_events(db, actor: dict, request_id: int) -> list[dict]:
    if get_request(db, actor, request_id) is None:
        raise NotFoundError("Request not found.")
    rows = db.execute(
        "SELECT * FROM evidence_request_events WHERE request_id=%s ORDER BY changed_at ASC", (request_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def submit_request(db, actor: dict, request_id: int, *, evidence_id: int, expected_lock_version: int) -> dict:
    """Object-level authorization (must be this request's own assignee),
    matching aria.policy's _draft_can_edit_document pattern -- not a role
    capability, since fulfilling your own assignment is not a management
    action. evidence_id must resolve through the real Evidence Vault
    scoped fetch, so a request can never be 'satisfied' by a file the
    submitter cannot actually see/own."""
    from modules.evidence.routes import _scoped_evidence_item

    request = get_request(db, actor, request_id)
    if request is None:
        raise NotFoundError("Request not found.")
    if request["assignee_id"] != actor["id"]:
        raise ForbiddenError("Only this request's assignee may submit evidence for it.")
    if request["status"] not in ("requested", "returned", "overdue"):
        raise InvalidTransitionError(f"Cannot submit while status is '{request['status']}'.")
    if request["lock_version"] != expected_lock_version:
        raise StaleVersionError()
    evidence_row = _scoped_evidence_item(db, evidence_id, actor)
    if evidence_row is None:
        raise CampaignError("INVALID_INPUT", "That evidence item could not be found.", 422)

    now = _now()
    updated = db.execute(
        "UPDATE evidence_requests SET status='submitted', evidence_id=%s, submitted_at=%s, "
        "lock_version=lock_version+1, updated_at=%s WHERE id=%s AND lock_version=%s",
        (evidence_id, now, now, request_id, expected_lock_version),
    )
    if getattr(updated, "rowcount", 1) == 0:
        raise StaleVersionError()
    _record_event(db, request_id, request["status"], "submitted", actor["id"])
    _notify(db, request["reviewer_id"], "evidence_campaigns", "Evidence submitted for review",
            f"\"{request['title']}\" is ready for your review.",
            f"/evidence-campaigns/requests/{request_id}")
    db.commit()
    return get_request(db, actor, request_id)


def start_review(db, actor: dict, request_id: int, expected_lock_version: int) -> dict:
    request = get_request(db, actor, request_id)
    if request is None:
        raise NotFoundError("Request not found.")
    if request["reviewer_id"] != actor["id"]:
        raise ForbiddenError("Only this request's assigned reviewer may start review.")
    if request["status"] != "submitted":
        raise InvalidTransitionError(f"Cannot start review while status is '{request['status']}'.")
    if request["lock_version"] != expected_lock_version:
        raise StaleVersionError()
    now = _now()
    updated = db.execute(
        "UPDATE evidence_requests SET status='in_review', lock_version=lock_version+1, updated_at=%s "
        "WHERE id=%s AND lock_version=%s",
        (now, request_id, expected_lock_version),
    )
    if getattr(updated, "rowcount", 1) == 0:
        raise StaleVersionError()
    _record_event(db, request_id, "submitted", "in_review", actor["id"])
    db.commit()
    return get_request(db, actor, request_id)


def decide_request(db, actor: dict, request_id: int, *, decision: str, notes: str = "",
                    expected_lock_version: int) -> dict:
    """decision: 'accept' or 'return'. Self-accept prevention (task_plan.md's
    own named acceptance line): the reviewer may never be the same person
    as the assignee, checked here against the request's own recorded
    assignee_id -- not just 'is this user generally allowed to review
    things', since that alone would not stop someone reviewing their own
    submission if they happened to hold both roles."""
    if decision not in ("accept", "return"):
        raise CampaignError("INVALID_INPUT", "decision must be 'accept' or 'return'.", 422)
    request = get_request(db, actor, request_id)
    if request is None:
        raise NotFoundError("Request not found.")
    if request["reviewer_id"] != actor["id"]:
        raise ForbiddenError("Only this request's assigned reviewer may decide it.")
    if request["assignee_id"] == actor["id"]:
        raise ForbiddenError("A request's assignee may not also decide their own submission.")
    if request["status"] != "in_review":
        raise InvalidTransitionError(f"Cannot decide while status is '{request['status']}'.")
    if decision == "return" and not (notes or "").strip():
        raise CampaignError("INVALID_INPUT", "A note is required when returning a submission.", 422)
    if request["lock_version"] != expected_lock_version:
        raise StaleVersionError()

    new_status = "accepted" if decision == "accept" else "returned"
    now = _now()
    updated = db.execute(
        "UPDATE evidence_requests SET status=%s, reviewed_by=%s, reviewed_at=%s, review_notes=%s, "
        "lock_version=lock_version+1, updated_at=%s WHERE id=%s AND lock_version=%s",
        (new_status, actor["id"], now, notes or "", now, request_id, expected_lock_version),
    )
    if getattr(updated, "rowcount", 1) == 0:
        raise StaleVersionError()
    _record_event(db, request_id, "in_review", new_status, actor["id"], notes)
    _notify(db, request["assignee_id"], "evidence_campaigns",
            "Evidence accepted" if new_status == "accepted" else "Evidence returned",
            notes or (f"\"{request['title']}\" was {new_status}."),
            f"/evidence-campaigns/requests/{request_id}")
    if new_status == "accepted":
        db.execute(
            "UPDATE task_board SET status='done', updated_at=%s "
            "WHERE module='evidence_campaigns' AND entity_type='evidence_request' AND entity_id=%s",
            (now, request_id),
        )
    db.commit()
    return get_request(db, actor, request_id)


def cancel_request(db, actor: dict, request_id: int, *, reason: str, expected_lock_version: int) -> dict:
    request = get_request(db, actor, request_id)
    if request is None:
        raise NotFoundError("Request not found.")
    if request["status"] in _TERMINAL_STATUSES:
        raise InvalidTransitionError(f"Cannot cancel a request that is already '{request['status']}'.")
    if not (reason or "").strip():
        raise CampaignError("INVALID_INPUT", "A reason is required to cancel a request.", 422)
    if request["lock_version"] != expected_lock_version:
        raise StaleVersionError()
    now = _now()
    updated = db.execute(
        "UPDATE evidence_requests SET status='cancelled', lock_version=lock_version+1, updated_at=%s "
        "WHERE id=%s AND lock_version=%s",
        (now, request_id, expected_lock_version),
    )
    if getattr(updated, "rowcount", 1) == 0:
        raise StaleVersionError()
    _record_event(db, request_id, request["status"], "cancelled", actor["id"], reason)
    db.execute(
        "INSERT INTO audit_log (user_id, username, module, action, entity_type, entity_id, details, org_id) "
        "VALUES (%s,%s,'evidence_campaigns','cancel','evidence_request',%s,%s,%s)",
        (actor["id"], actor.get("username", ""), request_id,
         f"Cancelled request \"{request['title']}\": {reason}", actor["org_id"]),
    )
    db.execute(
        "UPDATE task_board SET status='done', updated_at=%s "
        "WHERE module='evidence_campaigns' AND entity_type='evidence_request' AND entity_id=%s",
        (now, request_id),
    )
    db.commit()
    return get_request(db, actor, request_id)


# ─────────────────────────────────────────────────────────────────────────
# Scheduler-facing: overdue transition, reminders, recurrence
# ─────────────────────────────────────────────────────────────────────────

def mark_overdue_requests(db, org_id: int) -> int:
    """Transitions past-due, still-open requests to 'overdue'. A late
    submission from 'overdue' still moves it back into the normal flow
    (see submit_request's accepted from_states) -- this is a visibility
    flag, not a dead end."""
    today = utcnow().date().isoformat()
    rows = db.execute(
        "SELECT id, status, assignee_id, title FROM evidence_requests WHERE org_id=%s "
        "AND due_date < %s AND status IN ('requested','submitted','in_review','returned')",
        (org_id, today),
    ).fetchall()
    now = _now()
    for r in rows:
        db.execute(
            "UPDATE evidence_requests SET status='overdue', updated_at=%s WHERE id=%s", (now, r["id"]),
        )
        _record_event(db, r["id"], r["status"], "overdue", None, "Automatically marked overdue by scheduled sweep")
        _notify(db, r["assignee_id"], "evidence_campaigns", "Evidence request overdue",
                f"\"{r['title']}\" is now overdue.", f"/evidence-campaigns/requests/{r['id']}")
    if rows:
        db.commit()
    return len(rows)


def schedule_reminders(db, org_id: int) -> int:
    """T-3-day reminder for still-'requested' requests, via the existing
    email_reminders table/engine rather than a new send mechanism.
    Idempotent by construction: the reminder title is deterministic per
    request, and this checks for an existing un-sent row with that exact
    title before inserting another one -- a request only ever needs (and
    gets) one T-3 reminder per due date."""
    soon = (utcnow().date() + _dt.timedelta(days=_REMINDER_WINDOW_DAYS)).isoformat()
    rows = db.execute(
        "SELECT er.id, er.title, er.due_date, er.assignee_id, u.email AS assignee_email "
        "FROM evidence_requests er JOIN users u ON u.id = er.assignee_id "
        "WHERE er.org_id=%s AND er.status='requested' AND er.due_date <= %s",
        (org_id, soon),
    ).fetchall()
    scheduled = 0
    for r in rows:
        title = f"Evidence due soon: {r['title']}"
        existing = db.execute(
            "SELECT 1 FROM email_reminders WHERE module='evidence_campaigns' AND entity_type='evidence_request' "
            "AND entity_id=%s AND title=%s AND is_sent=0",
            (r["id"], title),
        ).fetchone()
        if existing:
            continue
        db.execute(
            "INSERT INTO email_reminders (module, entity_type, entity_id, title, message, recipient_id, "
            "recipient_email, remind_at, repeat_interval, created_by) "
            "VALUES ('evidence_campaigns','evidence_request',%s,%s,%s,%s,%s,%s,'none',NULL)",
            (r["id"], title, f"Due {r['due_date']}.", r["assignee_id"], r["assignee_email"] or "",
             _remind_at_str(utcnow())),
        )
        scheduled += 1
    if scheduled:
        db.commit()
    return scheduled


def generate_recurring_campaigns(db, org_id: int) -> int:
    """For each closed campaign with recurrence set, generates the next
    cycle once -- idempotent via recurrence_source_id: a campaign is only
    ever generated from a given source campaign once, checked before
    creating another."""
    offsets = {"monthly": 30, "quarterly": 91, "annual": 365}
    rows = db.execute(
        "SELECT * FROM evidence_campaigns WHERE org_id=%s AND status='closed' AND recurrence != 'none'",
        (org_id,),
    ).fetchall()
    generated = 0
    for c in rows:
        already = db.execute(
            "SELECT 1 FROM evidence_campaigns WHERE recurrence_source_id=%s", (c["id"],),
        ).fetchone()
        if already:
            continue
        days = offsets.get(c["recurrence"])
        if not days:
            continue
        old_due = _dt.date.fromisoformat(c["due_date"][:10])
        new_due = (old_due + _dt.timedelta(days=days)).isoformat()
        now = _now()
        db.execute(
            "INSERT INTO evidence_campaigns (org_id, business_unit_id, name, description, owner_user_id, "
            "due_date, status, recurrence, recurrence_source_id, created_by, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,'draft',%s,%s,%s,%s,%s)",
            (c["org_id"], c["business_unit_id"], c["name"], c["description"], c["owner_user_id"],
             new_due, c["recurrence"], c["id"], c["created_by"], now, now),
        )
        generated += 1
    if generated:
        db.commit()
    return generated
