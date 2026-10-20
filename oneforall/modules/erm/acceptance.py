"""Human risk acceptance decisions, separate from treatment labels and risk status."""
from __future__ import annotations

import hashlib
import json
from datetime import date

from config import settings
from core.rbac import has_capability
from core.timeutils import utcnow
from database import get_db, insert_returning_id
from modules.governance.entity_scope import entity_scope_sql


class AcceptanceConflict(ValueError):
    """The source or pending decision changed during review."""


def _stamp():
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _org(user):
    org_id = user.get("org_id")
    if not org_id:
        raise ValueError("Select an organization before managing acceptance")
    return int(org_id)


def _risk(db, user, risk_id, *, lock=False):
    scope, params = entity_scope_sql(("erm", "risk"), user, "r")
    suffix = " FOR UPDATE" if lock and settings.is_postgres() else ""
    row = db.execute(
        f"SELECT r.* FROM erm_enterprise_risks r WHERE r.id=%s AND {scope}{suffix}",
        [risk_id, *params],
    ).fetchone()
    if row is None:
        raise LookupError("Risk not found")
    return dict(row)


_SOURCE_FIELDS = (
    "id", "title", "category", "business_unit_id", "owner_id", "likelihood", "impact",
    "residual_likelihood", "residual_impact", "treatment", "status", "updated_at",
)


def _snapshot(db, risk):
    appetite = db.execute(
        "SELECT max_score, appetite_level, updated_at FROM erm_risk_appetite WHERE category=%s",
        (risk.get("category"),),
    ).fetchone()
    source = {key: risk.get(key) for key in _SOURCE_FIELDS}
    source["current_score"] = (risk.get("likelihood") or 0) * (risk.get("impact") or 0)
    if risk.get("residual_likelihood") is not None and risk.get("residual_impact") is not None:
        source["planned_residual_score"] = risk["residual_likelihood"] * risk["residual_impact"]
    else:
        source["planned_residual_score"] = None
    source["appetite"] = dict(appetite) if appetite else None
    payload = json.dumps(source, sort_keys=True, separators=(",", ":"), default=str)
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _date(value, field):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a date in YYYY-MM-DD format")


def _required_text(payload, field, limit=4000):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"{field} is required and must be at most {limit} characters")
    return value.strip()


def _visible_row(db, user, acceptance_id):
    scope, params = entity_scope_sql(("erm", "risk"), user, "r")
    row = db.execute(
        "SELECT a.*, r.title AS risk_title FROM erm_risk_acceptances a "
        "JOIN erm_enterprise_risks r ON r.id=a.risk_id "
        f"WHERE a.id=%s AND a.org_id=%s AND {scope}",
        [acceptance_id, _org(user), *params],
    ).fetchone()
    if row is None:
        raise LookupError("Acceptance not found")
    return dict(row)


def _present(db, user, row):
    result = dict(row)
    result["source_snapshot"] = json.loads(result["source_snapshot"])
    risk = _risk(db, user, row["risk_id"])
    _, current_hash = _snapshot(db, risk)
    if row["status"] == "approved":
        if str(row["expires_on"])[:10] < utcnow().date().isoformat():
            result["effective_status"] = "expired"
        elif current_hash != row["source_hash"]:
            result["effective_status"] = "needs_re_review"
        else:
            result["effective_status"] = "approved"
    else:
        result["effective_status"] = row["status"]
    return result


def propose(user, risk_id, payload):
    if not has_capability(user, "erm.acceptance.propose"):
        raise PermissionError("Risk acceptance proposal is not permitted")
    org_id = _org(user)
    reason = _required_text(payload, "reason")
    alternatives = _required_text(payload, "alternatives")
    scope_note = _required_text(payload, "scope_note")
    conditions = str(payload.get("conditions") or "").strip()[:4000]
    review_on = _date(payload.get("review_on"), "review_on")
    expires_on = _date(payload.get("expires_on"), "expires_on")
    if review_on < utcnow().date() or expires_on <= utcnow().date() or review_on > expires_on:
        raise ValueError("Set a future expiry and a review date no later than expiry")
    db = get_db()
    try:
        risk = _risk(db, user, risk_id, lock=True)
        if not user.get("is_super_admin") and risk.get("owner_id") != user["id"]:
            raise PermissionError("Only the named risk owner may propose acceptance")
        if risk.get("status") == "closed":
            raise ValueError("A closed risk cannot be accepted")
        snapshot, fingerprint = _snapshot(db, risk)
        active = db.execute(
            "SELECT id FROM erm_risk_acceptances WHERE org_id=%s AND risk_id=%s "
            "AND status='approved' AND source_hash=%s AND expires_on >= %s LIMIT 1",
            (org_id, risk_id, fingerprint, utcnow().date().isoformat()),
        ).fetchone()
        if active:
            raise AcceptanceConflict("This risk already has a current approval")
        existing = db.execute(
            "SELECT id FROM erm_risk_acceptances WHERE org_id=%s AND risk_id=%s AND status='submitted'",
            (org_id, risk_id),
        ).fetchone()
        if existing:
            raise AcceptanceConflict("An acceptance proposal is already awaiting a decision")
        new_id = insert_returning_id(db,
            "INSERT INTO erm_risk_acceptances "
            "(org_id, risk_id, proposed_by, reason, alternatives, conditions, scope_note, "
            "review_on, expires_on, source_snapshot, source_hash) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (org_id, risk_id, user["id"], reason, alternatives, conditions, scope_note,
             review_on.isoformat(), expires_on.isoformat(), snapshot, fingerprint),
        )
        if new_id is None:
            raise AcceptanceConflict("An acceptance proposal is already awaiting a decision")
        db.execute(
            "INSERT INTO erm_risk_acceptance_events (acceptance_id, to_status, actor_id, note) "
            "VALUES (%s,'submitted',%s,%s)", (new_id, user["id"], reason),
        )
        db.commit()
        return new_id
    finally:
        db.close()


def list_for_risk(user, risk_id):
    db = get_db()
    try:
        _risk(db, user, risk_id)
        rows = db.execute(
            "SELECT a.*, r.title AS risk_title FROM erm_risk_acceptances a "
            "JOIN erm_enterprise_risks r ON r.id=a.risk_id "
            "WHERE a.risk_id=%s AND a.org_id=%s ORDER BY a.id DESC",
            (risk_id, _org(user)),
        ).fetchall()
        return [_present(db, user, row) for row in rows]
    finally:
        db.close()


def detail(user, acceptance_id):
    db = get_db()
    try:
        row = _visible_row(db, user, acceptance_id)
        result = _present(db, user, row)
        result["events"] = [dict(event) for event in db.execute(
            "SELECT from_status, to_status, actor_id, note, created_at "
            "FROM erm_risk_acceptance_events WHERE acceptance_id=%s ORDER BY id",
            (acceptance_id,),
        ).fetchall()]
        return result
    finally:
        db.close()


def decide(user, acceptance_id, payload):
    if not has_capability(user, "erm.acceptance.decide"):
        raise PermissionError("Risk acceptance decision is not permitted")
    decision = payload.get("decision")
    if decision not in {"approved", "rejected", "returned"}:
        raise ValueError("decision must be approved, rejected or returned")
    note = _required_text(payload, "note")
    try:
        expected = int(payload.get("version"))
    except (TypeError, ValueError):
        raise ValueError("version is required")
    db = get_db()
    try:
        row = _visible_row(db, user, acceptance_id)
        risk = _risk(db, user, row["risk_id"], lock=True)
        if row["proposed_by"] == user["id"]:
            raise PermissionError("The proposer cannot decide their own acceptance")
        if row["status"] != "submitted" or row["version"] != expected:
            raise AcceptanceConflict("The proposal has already changed")
        if decision == "approved":
            today = utcnow().date().isoformat()
            if str(row["expires_on"])[:10] <= today or str(row["review_on"])[:10] < today:
                raise AcceptanceConflict("The review or expiry date has passed; request a new proposal")
            active = db.execute(
                "SELECT id FROM erm_risk_acceptances WHERE org_id=%s AND risk_id=%s "
                "AND status='approved' AND source_hash=%s AND expires_on >= %s AND id<>%s LIMIT 1",
                (_org(user), row["risk_id"], row["source_hash"], today, acceptance_id),
            ).fetchone()
            if active:
                raise AcceptanceConflict("This risk already has a current approval")
        _, fingerprint = _snapshot(db, risk)
        if fingerprint != row["source_hash"]:
            raise AcceptanceConflict("The risk or appetite changed; request a new proposal")
        stamp = _stamp()
        changed = db.execute(
            "UPDATE erm_risk_acceptances SET status=%s, version=version+1, decided_by=%s, "
            "decided_at=%s, decision_note=%s, updated_at=%s "
            "WHERE id=%s AND org_id=%s AND version=%s AND status='submitted'",
            (decision, user["id"], stamp, note, stamp, acceptance_id, _org(user), expected),
        )
        if changed.rowcount != 1:
            raise AcceptanceConflict("The proposal has already changed")
        db.execute(
            "INSERT INTO erm_risk_acceptance_events "
            "(acceptance_id, from_status, to_status, actor_id, note) VALUES (%s,%s,%s,%s,%s)",
            (acceptance_id, "submitted", decision, user["id"], note),
        )
        db.commit()
        return decision
    finally:
        db.close()


def revoke(user, acceptance_id, payload):
    if not has_capability(user, "erm.acceptance.decide"):
        raise PermissionError("Risk acceptance revocation is not permitted")
    note = _required_text(payload, "note")
    try:
        expected = int(payload.get("version"))
    except (TypeError, ValueError):
        raise ValueError("version is required")
    db = get_db()
    try:
        row = _visible_row(db, user, acceptance_id)
        if row["status"] != "approved" or row["version"] != expected:
            raise AcceptanceConflict("The approval has already changed")
        stamp = _stamp()
        changed = db.execute(
            "UPDATE erm_risk_acceptances SET status='revoked', version=version+1, "
            "updated_at=%s WHERE id=%s AND org_id=%s AND status='approved' AND version=%s",
            (stamp, acceptance_id, _org(user), expected),
        )
        if changed.rowcount != 1:
            raise AcceptanceConflict("The approval has already changed")
        db.execute(
            "INSERT INTO erm_risk_acceptance_events "
            "(acceptance_id, from_status, to_status, actor_id, note) "
            "VALUES (%s,'approved','revoked',%s,%s)",
            (acceptance_id, user["id"], note),
        )
        db.commit()
    finally:
        db.close()
