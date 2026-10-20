"""Versioned jurisdiction interpretations and per-breach notification obligations.

Only a DPO-approved card and a confirmed, sourced trigger can produce an
operational deadline. Existing registry clocks remain labelled indicative.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.rbac import has_capability
from database import get_db, insert_returning_id
from modules.governance.entity_scope import entity_scope_sql


def _allowed(user: dict, capability: str) -> None:
    if not has_capability(user, capability):
        raise PermissionError("This action needs a privacy specialist")


def _day(raw, name: str) -> str:
    try:
        return date.fromisoformat(str(raw)).isoformat()
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an ISO date") from None


def _trigger(raw) -> str | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Trigger must be an ISO timestamp with a timezone") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Trigger must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def create_card(data: dict, user: dict) -> int:
    _allowed(user, "sentinel.jurisdiction.draft")
    key = str(data.get("jurisdiction_key") or "").strip()
    notice_type = str(data.get("notice_type") or "").strip()
    if not key or len(key) > 64 or not notice_type or len(notice_type) > 64:
        raise ValueError("Choose a jurisdiction and notice type")
    fields = ("source_title", "source_url", "rule_summary", "trigger_definition", "timezone")
    values = [str(data.get(field) or "").strip() for field in fields]
    if any(not value or len(value) > 2000 for value in values):
        raise ValueError("Supply the source, interpretation, trigger and timezone")
    source_url = urlsplit(values[1])
    if source_url.scheme != "https" or not source_url.hostname or source_url.username or source_url.password:
        raise ValueError("Use an HTTPS legal source URL")
    try:
        ZoneInfo(values[4])
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Choose an IANA timezone") from None
    start = _day(data.get("effective_from"), "Effective from")
    end = _day(data["effective_to"], "Effective to") if data.get("effective_to") else None
    if end and end < start:
        raise ValueError("Effective end precedes the start")
    asap = data.get("asap") is True
    hours = data.get("deadline_hours")
    if asap:
        hours = None
    elif type(hours) is not int or not 1 <= hours <= 8760:
        raise ValueError("Set a positive deadline in hours, or mark the rule ASAP")
    db = get_db()
    try:
        previous = db.execute(
            "SELECT MAX(version) FROM sentinel_jurisdiction_rule_cards "
            "WHERE jurisdiction_key=%s AND notice_type=%s", (key, notice_type),
        ).fetchone()[0]
        card_id = insert_returning_id(db,
            "INSERT INTO sentinel_jurisdiction_rule_cards "
            "(jurisdiction_key,notice_type,version,source_title,source_url,rule_summary,"
            "trigger_definition,timezone,deadline_hours,asap,effective_from,effective_to,created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (key, notice_type, (previous or 0) + 1, *values, hours, int(asap), start, end, user["id"]),
        )
        db.commit()
        return card_id
    finally:
        db.close()


def approve_card(card_id: int, user: dict) -> None:
    _allowed(user, "sentinel.jurisdiction.approve")
    db = get_db()
    try:
        changed = db.execute(
            "UPDATE sentinel_jurisdiction_rule_cards SET state='approved',approved_by=%s,"
            "approved_at=CURRENT_TIMESTAMP WHERE id=%s AND state='draft' AND created_by<>%s",
            (user["id"], card_id, user["id"]),
        ).rowcount
        if changed != 1:
            raise LookupError("Draft rule card not found or independent approval is required")
        db.commit()
    finally:
        db.close()


def list_cards(user: dict) -> list[dict]:
    _allowed(user, "module.sentinel.access")
    db = get_db()
    try:
        return [dict(row) for row in db.execute(
            "SELECT id,jurisdiction_key,notice_type,version,state,source_title,source_url,"
            "rule_summary,trigger_definition,timezone,deadline_hours,asap,effective_from,"
            "effective_to,created_by,approved_by,approved_at "
            "FROM sentinel_jurisdiction_rule_cards ORDER BY jurisdiction_key,notice_type,version DESC"
        ).fetchall()]
    finally:
        db.close()


def add_obligation(breach_id: int, data: dict, user: dict) -> int:
    _allowed(user, "sentinel.breach.manage")
    card_id = data.get("rule_card_id")
    if type(card_id) is not int or card_id < 1:
        raise ValueError("Choose a rule card")
    applicability = data.get("applicability", "under_review")
    if applicability not in ("under_review", "applies", "not_applicable"):
        raise ValueError("Choose an applicability decision")
    trigger = _trigger(data.get("trigger_at"))
    source = str(data.get("trigger_source") or "").strip()
    if applicability == "applies" and not source:
        raise ValueError("Record the source of the trigger determination")
    if len(source) > 2000:
        raise ValueError("Trigger source is too long")
    owner_id = data.get("owner_user_id") or user["id"]
    if type(owner_id) is not int or owner_id < 1:
        raise ValueError("Choose an owner in this organization")
    db = get_db()
    try:
        scope, params = entity_scope_sql(("sentinel", "breach"), user, "b")
        breach = db.execute(f"SELECT b.id FROM sentinel_breaches b WHERE b.id=%s AND {scope}",
                            [breach_id, *params]).fetchone()
        card = db.execute("SELECT id,jurisdiction_key,notice_type FROM sentinel_jurisdiction_rule_cards "
                          "WHERE id=%s", (card_id,)).fetchone()
        owner = db.execute("SELECT id FROM users WHERE id=%s AND org_id=%s "
                           "AND is_active=1 AND deleted_at IS NULL",
                           (owner_id, user.get("org_id"))).fetchone()
        if owner is None:
            raise ValueError("Choose an owner in this organization")
        if breach is None or card is None:
            raise LookupError("Breach or rule card not found")
        existing = db.execute("SELECT id FROM sentinel_breach_obligations "
                              "WHERE breach_id=%s AND rule_card_id=%s",
                              (breach_id, card_id)).fetchone()
        if existing is not None:
            raise ValueError("This rule card is already attached to the breach")
        duplicate_notice = db.execute(
            "SELECT o.id FROM sentinel_breach_obligations o "
            "JOIN sentinel_jurisdiction_rule_cards c ON c.id=o.rule_card_id "
            "WHERE o.breach_id=%s AND c.jurisdiction_key=%s AND c.notice_type=%s",
            (breach_id, card["jurisdiction_key"], card["notice_type"]),
        ).fetchone()
        if duplicate_notice is not None:
            raise ValueError("This jurisdiction and notice type already has an obligation")
        oid = insert_returning_id(db,
            "INSERT INTO sentinel_breach_obligations "
            "(breach_id,rule_card_id,applicability,trigger_at,trigger_source,owner_user_id,created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (breach_id, card_id, applicability, trigger, source,
             owner_id, user["id"]),
        )
        db.commit()
        return oid
    finally:
        db.close()


def update_obligation_facts(obligation_id: int, data: dict, user: dict) -> None:
    """Revise a legal applicability or trigger fact with a permanent change record."""
    _allowed(user, "sentinel.breach.manage")
    applicability = data.get("applicability")
    if applicability not in ("under_review", "applies", "not_applicable"):
        raise ValueError("Choose an applicability decision")
    trigger = _trigger(data.get("trigger_at"))
    source = str(data.get("trigger_source") or "").strip()
    if applicability == "applies" and not source:
        raise ValueError("Record the source of the trigger determination")
    if len(source) > 2000:
        raise ValueError("Trigger source is too long")
    db = get_db()
    try:
        scope, params = entity_scope_sql(("sentinel", "breach"), user, "b")
        row = db.execute(
            "SELECT o.id,o.applicability,o.trigger_at,o.trigger_source,o.decision "
            "FROM sentinel_breach_obligations o "
            "JOIN sentinel_breaches b ON b.id=o.breach_id "
            f"WHERE o.id=%s AND {scope}", [obligation_id, *params],
        ).fetchone()
        if row is None:
            raise LookupError("Obligation not found")
        before = {field: row[field] for field in ("applicability", "trigger_at", "trigger_source", "decision")}
        after = {"applicability": applicability, "trigger_at": trigger,
                 "trigger_source": source, "decision": "pending"}
        if all(before[key] == after[key] for key in ("applicability", "trigger_at", "trigger_source")):
            return
        db.execute("UPDATE sentinel_breach_obligations SET applicability=%s,trigger_at=%s,"
                   "trigger_source=%s,decision='pending',decision_reason=NULL,decided_by=NULL,"
                   "decided_at=NULL WHERE id=%s",
                   (applicability, trigger, source, obligation_id))
        db.execute("INSERT INTO sentinel_obligation_history "
                   "(obligation_id,change_kind,before_json,after_json,changed_by) "
                   "VALUES (%s,'facts',%s,%s,%s)",
                   (obligation_id, json.dumps(before, default=str), json.dumps(after), user["id"]))
        db.commit()
    finally:
        db.close()


def list_obligations(breach_id: int, user: dict, *, now: datetime | None = None) -> list[dict]:
    _allowed(user, "module.sentinel.access")
    db = get_db()
    try:
        scope, params = entity_scope_sql(("sentinel", "breach"), user, "b")
        breach = db.execute(f"SELECT b.id FROM sentinel_breaches b WHERE b.id=%s AND {scope}",
                            [breach_id, *params]).fetchone()
        if breach is None:
            raise LookupError("Breach not found")
        rows = db.execute(
            "SELECT o.id,o.breach_id,o.applicability,o.trigger_at,o.trigger_source,"
            "o.decision,o.decision_reason,o.owner_user_id,o.decided_by,o.decided_at,"
            "c.id AS rule_card_id,c.jurisdiction_key,c.notice_type,c.version,c.state AS rule_state,"
            "c.source_title,c.source_url,c.rule_summary,c.trigger_definition,c.timezone,"
            "c.deadline_hours,c.asap,c.effective_from,c.effective_to,c.approved_by,c.approved_at "
            "FROM sentinel_breach_obligations o JOIN sentinel_jurisdiction_rule_cards c "
            "ON c.id=o.rule_card_id WHERE o.breach_id=%s ORDER BY c.jurisdiction_key,c.notice_type,o.id",
            (breach_id,),
        ).fetchall()
        result = []
        for raw in rows:
            item = dict(raw)
            state = "unresolved"
            deadline = None
            if item["applicability"] == "not_applicable":
                state = "not_applicable"
            elif item["rule_state"] != "approved":
                state = "awaiting_rule_approval"
            elif item["applicability"] != "applies":
                state = "awaiting_applicability"
            elif not item["trigger_at"]:
                state = "missing_trigger"
            else:
                trigger = _trigger(item["trigger_at"])
                local_day = datetime.fromisoformat(trigger).astimezone(ZoneInfo(item["timezone"])).date().isoformat()
                if local_day < item["effective_from"] or (item["effective_to"] and local_day > item["effective_to"]):
                    state = "rule_outside_effective_dates"
                elif item["asap"]:
                    state = "asap"
                else:
                    due = datetime.fromisoformat(trigger) + timedelta(hours=item["deadline_hours"])
                    deadline = due.isoformat()
                    state = "overdue" if due < (now or datetime.now(timezone.utc)) else "running"
            item["clock"] = {"state": state, "deadline_at": deadline,
                             "authoritative": state in ("running", "overdue", "asap")}
            result.append(item)
        return result
    finally:
        db.close()


def decide_obligation(obligation_id: int, decision: str, reason: str, user: dict) -> None:
    _allowed(user, "sentinel.breach.manage")
    if decision not in ("notify", "do_not_notify", "deferred") or not isinstance(reason, str) or len(reason.strip()) < 10:
        raise ValueError("Choose a decision and explain the reason")
    db = get_db()
    try:
        scope, params = entity_scope_sql(("sentinel", "breach"), user, "b")
        found = db.execute(
            "SELECT o.id,o.decision,o.decision_reason FROM sentinel_breach_obligations o "
            "JOIN sentinel_breaches b ON b.id=o.breach_id "
            f"WHERE o.id=%s AND {scope}", [obligation_id, *params],
        ).fetchone()
        if found is None:
            raise LookupError("Obligation not found")
        db.execute("UPDATE sentinel_breach_obligations SET decision=%s,decision_reason=%s,"
                   "decided_by=%s,decided_at=CURRENT_TIMESTAMP WHERE id=%s",
                   (decision, reason.strip(), user["id"], obligation_id))
        db.execute("INSERT INTO sentinel_obligation_history "
                   "(obligation_id,change_kind,before_json,after_json,changed_by) "
                   "VALUES (%s,'decision',%s,%s,%s)",
                   (obligation_id, json.dumps({"decision": found["decision"],
                                                "reason": found["decision_reason"]}),
                    json.dumps({"decision": decision, "reason": reason.strip()}), user["id"]))
        db.commit()
    finally:
        db.close()
