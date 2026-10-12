"""
AI governance G5: regulatory impact on AI uses (plans/ai-governance/08-g5-build-plan.md).

A change posted to the Regulatory Inbox is matched, by a fixed table and nothing else, to the AI uses whose intended
jurisdictions it concerns. The match is a candidate for a person to confirm or dismiss. Nothing is inferred from a
jurisdiction label alone: a confirmed candidate becomes one owned task and one fact on the use, and a dismissed one does not
come back unless the source change itself changes. Nothing here fetches regulation text; the inbox is manual, so whether a
source is current is the person's responsibility and the screen says so.

Like the rest of the service layer, every function takes the caller's connection and user, checks capability and unit scope
itself, never commits, and returns audit entries and events.
"""
import hashlib
import json

from core import events
from core.rbac import has_capability
from database import insert_returning_id
from modules.ai_governance import service
from modules.ai_governance.service import APP, ServiceError
from modules.governance.entity_scope import entity_scope_sql

STATUSES = ("candidate", "confirmed", "dismissed")
LIMIT = 300

# A fixed table, not legal advice: a fragment of the framework name an update was posted under, and the intended
# jurisdictions of an AI use (core vocabulary of the AI profile) it concerns. Longest fragment wins, so "uk gdpr" is not
# read as "gdpr". A name this table does not know matches nothing, which is the safe answer.
FRAMEWORK_JURISDICTIONS = (
    ("artificial intelligence act", ("EU",)),
    ("protection of personal information", ("ZA",)),
    ("cyber and data protection", ("ZW",)),
    ("data protection regulation", ("EU",)),
    ("eu ai act", ("EU",)),
    ("uk gdpr", ("UK",)),
    ("gdpr", ("EU",)),
    ("popia", ("ZA",)),
    ("ndpa", ("NG",)),
    ("ndpr", ("NG",)),
    ("ccpa", ("US",)),
    ("cpra", ("US",)),
    ("hipaa", ("US",)),
    ("nigeria data protection", ("NG",)),
    ("kenya data protection", ("KE",)),
    ("ghana data protection", ("GH",)),
    ("uae pdpl", ("AE",)),
)


def jurisdictions_for(framework_name) -> list:
    name = str(framework_name or "").lower()
    for fragment, codes in sorted(FRAMEWORK_JURISDICTIONS, key=lambda e: -len(e[0])):
        if fragment in name:
            return list(codes)
    return []


def fingerprint(update) -> str:
    """What identifies the change itself: moving any of it is a material change to the source."""
    parts = [str(update[k] or "") for k in ("framework_name", "title", "summary", "source_url", "effective_date", "affected_refs")]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def matches(update, profile_jurisdictions) -> "str | None":
    """The basis sentence when an AI use with these intended jurisdictions is a candidate for this update, else None."""
    wanted = jurisdictions_for(update["framework_name"])
    shared = [c for c in wanted if c in (profile_jurisdictions or [])]
    if not shared:
        return None
    return f"The change was posted under {update['framework_name']} and the use's intended jurisdictions include {', '.join(shared)}."


def _present(rows) -> list:
    return [{
        "id": r["id"], "update_id": r["update_id"], "application_id": r["application_id"], "status": r["status"],
        "basis": r["basis"], "title": r["title"], "framework_name": r["framework_name"], "severity": r["severity"],
        "effective_date": str(r["effective_date"] or "")[:10] or None, "source_url": r["source_url"],
        "system": r["name"], "reviewed_at": service._text(r["reviewed_at"]), "review_note": r["review_note"],
        "version": r["version"], "url": f"/ai-governance/systems/{r['application_id']}#monitoring"} for r in rows]


_SELECT = ("SELECT i.id, i.update_id, i.application_id, i.status, i.basis, i.reviewed_at, i.review_note, i.version, "
           "u.title, u.framework_name, u.severity, u.effective_date, u.source_url, a.name "
           "FROM ai_regulatory_impacts i JOIN regulatory_updates u ON u.id = i.update_id "
           "JOIN applications a ON a.id = i.application_id")


def refresh(db, user) -> dict:
    """Propose candidates for the open updates among the AI uses the reviewer may open. Idempotent: an existing row is left
    as it is, except a dismissed one whose source change has moved, which is proposed again."""
    service._require(user, "ai_use.review")
    scope, params = entity_scope_sql(APP, user, "a")
    uses = db.execute(
        "SELECT p.application_id, p.jurisdictions, a.business_unit_id FROM ai_use_profiles p "
        f"JOIN applications a ON a.id = p.application_id WHERE a.is_active = 1 AND {scope} LIMIT %s", [*params, 2000]).fetchall()
    profiles = [(r["application_id"], r["business_unit_id"], service._json_list(r["jurisdictions"])) for r in uses]
    updates = db.execute("SELECT * FROM regulatory_updates WHERE status = 'open' ORDER BY id DESC LIMIT %s", (LIMIT,)).fetchall()
    created = reopened = 0
    now = service._now()
    for update in updates:
        stamp = fingerprint(update)
        for application_id, unit, jurisdictions in profiles:
            basis = matches(update, jurisdictions)
            if basis is None:
                continue
            new_id = insert_returning_id(
                db,
                "INSERT INTO ai_regulatory_impacts (update_id, application_id, business_unit_id, status, basis, update_fingerprint, "
                "version, created_at, updated_at) VALUES (%s, %s, %s, 'candidate', %s, %s, 1, %s, %s) "
                "ON CONFLICT (update_id, application_id) DO NOTHING",
                (update["id"], application_id, unit, basis, stamp, now, now))
            if new_id is not None:
                created += 1
                continue
            moved = db.execute(
                "UPDATE ai_regulatory_impacts SET status = 'candidate', basis = %s, update_fingerprint = %s, version = version + 1, "
                "updated_at = %s WHERE update_id = %s AND application_id = %s AND status = 'dismissed' AND update_fingerprint != %s",
                (basis, stamp, now, update["id"], application_id, stamp)).rowcount
            reopened += moved
    return {"created": created, "reopened": reopened, "events": [],
            "audit": [("ai_regulatory_refresh", "regulatory_update", 0, f"{created} proposed, {reopened} proposed again")] if created or reopened else []}


def list_queue(db, user, status="candidate") -> dict:
    service._require(user, "ai_use.view")
    if status not in STATUSES:
        raise ServiceError(400, "Unknown status filter.")
    scope, params = entity_scope_sql(APP, user, "a")
    rows = db.execute(f"{_SELECT} WHERE i.status = %s AND {scope} ORDER BY i.id DESC LIMIT %s", [status, *params, LIMIT]).fetchall()
    return {"items": _present(rows), "status": status, "can_review": has_capability(user, "ai_use.review"),
            "note": "Changes are posted by people to the Regulatory Inbox with their source. Nothing here fetches regulation text, "
                    "so check that the source is current before confirming."}


def review(db, user, impact_id: int, decision, reason, expected_version) -> dict:
    """Confirm or dismiss a candidate. Confirming makes one task for the owner and raises one event; dismissing needs a reason."""
    service._require(user, "ai_use.review")
    scope, params = entity_scope_sql(APP, user, "a")
    row = db.execute(f"{_SELECT} WHERE i.id = %s AND {scope}", [impact_id, *params]).fetchone()
    if row is None:
        raise ServiceError(404, "Impact not found.")
    if decision not in ("confirm", "dismiss"):
        raise ServiceError(422, "Choose confirm or dismiss.")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the candidate you are reviewing.")
    if row["status"] != "candidate":
        raise ServiceError(409, "This candidate was already reviewed.", status_now=row["status"], current_version=row["version"])
    reason = (reason or "").strip() if isinstance(reason, str) or reason is None else ""
    if decision == "dismiss" and len(reason) < 3:
        raise ServiceError(422, "Say why this change does not concern the use.")
    if len(reason) > 1000:
        raise ServiceError(422, "Keep the reason to 1000 characters or fewer.")
    now = service._now()
    app = db.execute("SELECT owner_user_id, business_unit_id, name FROM applications WHERE id = %s", (row["application_id"],)).fetchone()
    task = None
    out_events = []
    if decision == "confirm":
        task = insert_returning_id(
            db,
            "INSERT INTO task_board (title, description, module, entity_type, entity_id, assigned_to, priority, status, due_date, created_by) "
            "VALUES (%s, %s, 'ai_governance', 'application', %s, %s, %s, 'todo', %s, %s)",
            (f"Regulatory change: {app['name']}: {row['title']}"[:255],
             (reason or f"Confirmed as concerning this use: {row['framework_name']}.")[:1000], row["application_id"],
             app["owner_user_id"], "high" if row["severity"] == "high" else "medium", row["effective_date"], user["id"]))
        out_events.append(events.enqueue(
            db, events.AI_REGULATORY_CONFIRMED, "ai_governance", "application", row["application_id"],
            {"impact_id": impact_id, "application_id": row["application_id"], "business_unit_id": app["business_unit_id"]},
            user_id=user["id"], org_id=user.get("org_id"), dedup_key=f"ai_use.regulatory_confirmed:{impact_id}"))
    moved = db.execute(
        "UPDATE ai_regulatory_impacts SET status = %s, reviewed_by = %s, reviewed_at = %s, review_note = %s, task_id = %s, "
        "version = version + 1, updated_at = %s WHERE id = %s AND status = 'candidate' AND version = %s",
        ("confirmed" if decision == "confirm" else "dismissed", user["id"], now, reason or None, task, now, impact_id,
         expected_version)).rowcount
    if moved != 1:
        raise ServiceError(409, "This candidate was changed by someone else. Reload it and try again.")
    done = db.execute(f"{_SELECT} WHERE i.id = %s", (impact_id,)).fetchone()
    return {"item": _present([done])[0], "events": out_events,
            "audit": [({"confirm": "ai_regulatory_confirmed", "dismiss": "ai_regulatory_dismissed"}[decision], "application",
                       row["application_id"], f"update {row['update_id']}")]}


def confirmed_for(db, user, application_id: int) -> list:
    service._require(user, "ai_use.view")
    scope, params = entity_scope_sql(APP, user, "a")
    rows = db.execute(f"{_SELECT} WHERE i.application_id = %s AND i.status = 'confirmed' AND {scope} ORDER BY i.id DESC LIMIT 20",
                      [application_id, *params]).fetchall()
    return _present(rows)


def confirmed_since(db, application_id: int, since) -> list:
    """Impacts confirmed for the use after `since` (any when None). Names nothing: the decision only needs to know."""
    sql = "SELECT id FROM ai_regulatory_impacts WHERE application_id = %s AND status = 'confirmed'"
    params = [application_id]
    if since:
        sql += " AND reviewed_at > %s"
        params.append(str(since))
    return [r["id"] for r in db.execute(sql + " LIMIT 20", params).fetchall()]
