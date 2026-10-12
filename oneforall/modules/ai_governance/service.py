"""
AI governance service: intake, the AI profile, retiring a use, and duplicate suggestions.

An AI use is one `applications` row with one `ai_use_profiles` row (field ownership: plans/ai-governance/05-execution-
ledger.md). Staff describe a use in an intake request and never write `applications`; a reviewer promotes the request
into a new application or links it to an existing one, and from then on the profile owns the facts about the use.

Every function takes the caller's connection and the signed-in user, checks the capability and the business-unit scope
itself, never commits, and returns what the route does once the change is committed: the audit entries to write and the
events to deliver. A request that is not the caller's to see answers exactly like one that does not exist.
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta

from core import events
from core.rbac import has_capability
from core.timeutils import utcnow
from core.vendor_link import ensure_canonical
from database import insert_returning_id
from modules.ai_governance import rules
from modules.governance.data_service import bu_scope_ids
from modules.governance.entity_scope import describe_record, entity_scope_sql

log = logging.getLogger("oneforall.ai_governance")

APP = ("governance", "application")
CRITICALITY = ("low", "medium", "high", "critical")
MAX_REASON = 1000
_KEY_RE = re.compile(r"[A-Za-z0-9_.:-]{1,80}")

# What a decision covers: when any of these changes, an earlier approval no longer describes the use.
MATERIAL_FIELDS = ("purpose", "capability_type", "deployment", "provider_note", "data_categories", "affected_people",
                   "autonomy", "jurisdictions", "external_access", "affects_decisions")

_PROFILE_FIELDS = ("purpose", "capability_type", "intended_users", "affected_people", "autonomy", "deployment",
                   "provider_note", "data_categories", "jurisdictions", "external_access", "affects_decisions",
                   "human_oversight", "target_launch")
_JSON_FIELDS = ("affected_people", "data_categories", "jurisdictions")
_BOOL_FIELDS = ("external_access", "affects_decisions")
# The profile calls the provider's name `provider_note`; the intake form asks for `provider_name`.
_INTAKE_TO_PROFILE = {"provider_name": "provider_note"}


class ServiceError(Exception):
    """A refused operation. `message` is safe to show; it never names a record the caller may not open."""

    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def _now() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _require(user: dict, capability: str) -> None:
    if not has_capability(user, capability):
        raise ServiceError(403, "Access denied.")


def _in_scope(user: dict, unit) -> bool:
    scope = bu_scope_ids(user)
    return scope is None or unit is None or unit in scope


def _same_org(user: dict, row_org) -> bool:
    return user.get("org_id") is None or row_org is None or row_org == user["org_id"]


def _text(value) -> "str | None":
    return str(value) if value is not None else None


def _json_list(raw) -> list:
    try:
        value = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _reason(text, what: str, minimum: int = 3) -> str:
    text = (text or "").strip() if isinstance(text, str) else ""
    if len(text) < minimum:
        raise ServiceError(422, f"Say {what}.")
    if len(text) > MAX_REASON:
        raise ServiceError(422, f"The {what.split(' ', 1)[-1]} is too long (at most {MAX_REASON} characters).")
    return text


def fingerprint(answers: dict) -> str:
    """A short hash of the facts a decision covers, so a later change can be told from an edit that changes nothing."""
    covered = {f: (sorted(answers.get(f) or []) if f in _JSON_FIELDS else answers.get(f)) for f in MATERIAL_FIELDS}
    return hashlib.sha256(json.dumps(covered, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ── Intake requests ─────────────────────────────────────────────────────────

def _intake(row) -> dict:
    try:
        answers = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError):
        answers = {}
    return {
        "id": row["id"], "status": row["status"], "version": row["version"], "answers": answers,
        "screening": rules.screen(answers), "business_unit_id": row["business_unit_id"],
        "application_id": row["application_id"], "review_note": row["review_note"],
        "submitted_by": row["submitted_by"], "reviewed_by": row["reviewed_by"], "source_ref": row["source_ref"],
        "submitted_at": _text(row["submitted_at"]), "reviewed_at": _text(row["reviewed_at"]),
        "created_at": _text(row["created_at"]), "updated_at": _text(row["updated_at"]),
    }


def _with_names(db, intakes: list) -> list:
    """Add the author's and the owner's name to requests that are about to be shown."""
    ids = sorted({i for item in intakes for i in (item["submitted_by"], item["answers"].get("owner_user_id")) if i})
    names = {}
    if ids:
        rows = db.execute(f"SELECT id, full_name FROM users WHERE id IN ({','.join(['%s'] * len(ids))})", ids).fetchall()
        names = {r["id"]: r["full_name"] for r in rows}
    for item in intakes:
        item["author_name"] = names.get(item["submitted_by"])
        item["owner_name"] = names.get(item["answers"].get("owner_user_id"))
    return intakes


def _load(db, intake_id: int):
    return db.execute("SELECT * FROM ai_use_intake_requests WHERE id = %s", (intake_id,)).fetchone()


def _visible_to_author(user, row) -> bool:
    return bool(row) and row["submitted_by"] == user["id"] and _same_org(user, row["org_id"])


def _visible_to_reviewer(user, row) -> bool:
    return (bool(row) and has_capability(user, "ai_use.review") and _same_org(user, row["org_id"])
            and _in_scope(user, row["business_unit_id"]))


def _own_intake(db, user, intake_id: int):
    row = _load(db, intake_id)
    if not _visible_to_author(user, row):
        raise ServiceError(404, "Request not found.")
    return row


def _review_intake(db, user, intake_id: int):
    _require(user, "ai_use.review")
    row = _load(db, intake_id)
    if not _visible_to_reviewer(user, row):
        raise ServiceError(404, "Request not found.")
    return row


def get_intake(db, user, intake_id: int) -> dict:
    """The author's own request, or a reviewer's in-scope one. Anything else is 404."""
    row = _load(db, intake_id)
    if not (_visible_to_author(user, row) or _visible_to_reviewer(user, row)):
        raise ServiceError(404, "Request not found.")
    return _with_names(db, [_intake(row)])[0]


def _check_unit(db, user, unit) -> "int | None":
    """The business unit an intake belongs to: the author's own when none is chosen, else one inside their scope."""
    if unit is None:
        return user.get("business_unit_id") or None
    scope = bu_scope_ids(user)
    if scope is not None and unit not in scope:
        raise ServiceError(400, "Choose a business unit you belong to.")
    if not db.execute("SELECT 1 FROM business_units WHERE id = %s AND is_active = 1", (unit,)).fetchone():
        raise ServiceError(400, "Choose a business unit you belong to.")
    return unit


def _check_owner(db, user, owner_id) -> None:
    if owner_id is None:
        return
    row = db.execute("SELECT org_id, is_active, deleted_at FROM users WHERE id = %s", (owner_id,)).fetchone()
    if not row or not row["is_active"] or row["deleted_at"] or not _same_org(user, row["org_id"]):
        raise ServiceError(400, "Choose the owner from the people in your organization.")


def _clean_answers(db, user, raw) -> dict:
    answers, errors = rules.clean(raw)
    if errors:
        raise ServiceError(422, "Some answers need fixing.", errors=errors)
    if "business_unit_id" in answers:
        answers["business_unit_id"] = _check_unit(db, user, answers["business_unit_id"])
    if "owner_user_id" in answers:
        _check_owner(db, user, answers["owner_user_id"])
    return answers


def create_draft(db, user, raw_answers, idempotency_key=None, source_ref=None) -> dict:
    """Start a draft. The same idempotency key from the same person returns the draft already made."""
    _require(user, "ai_use.submit")
    if idempotency_key is not None and not _KEY_RE.fullmatch(str(idempotency_key)):
        raise ServiceError(400, "The idempotency key must be 1 to 80 letters, digits or . _ : -.")
    if source_ref is not None and not re.fullmatch(r"(vendor|process):\d{1,9}", str(source_ref)):
        raise ServiceError(400, "Unknown source.")
    answers = _clean_answers(db, user, raw_answers or {})
    answers.setdefault("business_unit_id", user.get("business_unit_id") or None)
    answers.setdefault("owner_user_id", user["id"])
    if idempotency_key:
        existing = db.execute(
            "SELECT * FROM ai_use_intake_requests WHERE submitted_by = %s AND idempotency_key = %s",
            (user["id"], idempotency_key)).fetchone()
        if existing:
            return {"intake": _intake(existing), "created": False, "audit": [], "events": []}
    new_id = insert_returning_id(
        db,
        "INSERT INTO ai_use_intake_requests (org_id, business_unit_id, submitted_by, status, payload, source_ref, "
        "idempotency_key) VALUES (%s, %s, %s, 'draft', %s, %s, %s) ON CONFLICT DO NOTHING",
        (user.get("org_id"), answers.get("business_unit_id"), user["id"], json.dumps(answers), source_ref,
         idempotency_key or None))
    if new_id is None:  # lost a race with the same key: the winner's draft is the answer
        row = db.execute("SELECT * FROM ai_use_intake_requests WHERE submitted_by = %s AND idempotency_key = %s",
                         (user["id"], idempotency_key)).fetchone()
        return {"intake": _intake(row), "created": False, "audit": [], "events": []}
    return {"intake": _intake(_load(db, new_id)), "created": True,
            "audit": [("ai_use_draft_created", "ai_use_intake", new_id, "draft created")], "events": []}


def _compare_and_set(db, intake_id: int, expected_version, statuses: tuple, **sets) -> bool:
    """One atomic step that only applies to the version the person was looking at, in an allowed status."""
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the request you are changing.")
    columns = ", ".join(f"{name} = %s" for name in sets)
    marks = ",".join(["%s"] * len(statuses))
    done = db.execute(
        f"UPDATE ai_use_intake_requests SET {columns}, version = version + 1, updated_at = %s "
        f"WHERE id = %s AND version = %s AND status IN ({marks})",
        (*sets.values(), _now(), intake_id, expected_version, *statuses)).rowcount
    return done == 1


def _stale(db, intake_id: int) -> ServiceError:
    row = _load(db, intake_id)
    return ServiceError(409, "This request was changed by someone else. Reload it and try again.",
                        current_version=row["version"] if row else None, status_now=row["status"] if row else None)


def save_draft(db, user, intake_id: int, raw_answers, expected_version) -> dict:
    """Replace the answers of the author's own draft or returned request."""
    _require(user, "ai_use.submit")
    row = _own_intake(db, user, intake_id)
    if row["status"] not in ("draft", "returned"):
        raise ServiceError(409, "Only a draft or a returned request can be edited.")
    changed = _clean_answers(db, user, raw_answers or {})
    answers = {**json.loads(row["payload"] or "{}"), **changed}
    if not _compare_and_set(db, intake_id, expected_version, ("draft", "returned"),
                            payload=json.dumps(answers), business_unit_id=answers.get("business_unit_id")):
        raise _stale(db, intake_id)
    return {"intake": _intake(_load(db, intake_id)), "audit": [], "events": []}


def submit(db, user, intake_id: int, expected_version) -> dict:
    """Hand a complete draft to the reviewers. Submitting again changes nothing."""
    _require(user, "ai_use.submit")
    row = _own_intake(db, user, intake_id)
    if row["status"] == "submitted":
        return {"intake": _intake(row), "audit": [], "events": [], "already": True}
    if row["status"] not in ("draft", "returned"):
        raise ServiceError(409, "This request has already been decided.")
    answers = json.loads(row["payload"] or "{}")
    missing = rules.missing_for_submit(answers)
    if missing:
        raise ServiceError(422, "Answer the required questions before submitting: "
                           + ", ".join(rules.label(f) for f in missing) + ".", missing=missing)
    screening = rules.screen(answers)
    if not _compare_and_set(db, intake_id, expected_version, ("draft", "returned"), status="submitted",
                            submitted_at=_now(), provisional_tier=screening["tier"],
                            tier_rule_version=screening["rule_version"], review_note=None):
        raise _stale(db, intake_id)
    event = events.enqueue(db, events.AI_USE_SUBMITTED, "ai_governance", "ai_use_intake", intake_id,
                           {"intake_id": intake_id, "business_unit_id": row["business_unit_id"]},
                           user_id=user["id"], org_id=user.get("org_id"), dedup_key=f"ai_use.submitted:{intake_id}:{expected_version}")
    return {"intake": _intake(_load(db, intake_id)), "events": [event],
            "audit": [("ai_use_submitted", "ai_use_intake", intake_id, f"provisional tier {screening['tier']}")]}


def list_mine(db, user, status=None) -> list:
    _require(user, "ai_use.submit")
    sql, params = "SELECT * FROM ai_use_intake_requests WHERE submitted_by = %s", [user["id"]]
    if status:
        sql, params = sql + " AND status = %s", [*params, status]
    return _with_names(db, [_intake(r) for r in db.execute(sql + " ORDER BY updated_at DESC, id DESC LIMIT 200", params).fetchall()])


def review_queue(db, user, status="submitted", limit=100) -> list:
    """Requests a reviewer may see: their organization's, inside their business-unit scope."""
    _require(user, "ai_use.review")
    sql, params = "SELECT * FROM ai_use_intake_requests WHERE status = %s", [status]
    if user.get("org_id") is not None:
        sql, params = sql + " AND org_id = %s", [*params, user["org_id"]]
    scope = bu_scope_ids(user)
    if scope is not None:
        sql += f" AND (business_unit_id IS NULL OR business_unit_id IN ({','.join(['%s'] * len(scope))}))"
        params += list(scope)
    rows = db.execute(sql + " ORDER BY submitted_at, id LIMIT %s", [*params, max(1, min(int(limit), 200))]).fetchall()
    return _with_names(db, [_intake(r) for r in rows])


def return_to_author(db, user, intake_id: int, note, expected_version) -> dict:
    row = _review_intake(db, user, intake_id)
    note = _reason(note, "what the author needs to add or change")
    if not _compare_and_set(db, intake_id, expected_version, ("submitted",), status="returned", review_note=note,
                            reviewed_by=user["id"], reviewed_at=_now()):
        raise _stale(db, intake_id)
    event = events.enqueue(db, events.AI_USE_RETURNED, "ai_governance", "ai_use_intake", intake_id,
                           {"intake_id": intake_id}, user_id=user["id"], org_id=user.get("org_id"),
                           dedup_key=f"ai_use.returned:{intake_id}:{expected_version}")
    return {"intake": _intake(_load(db, intake_id)), "events": [event],
            "audit": [("ai_use_returned", "ai_use_intake", intake_id, "returned to the author")]}


def reject(db, user, intake_id: int, reason, expected_version) -> dict:
    row = _review_intake(db, user, intake_id)
    reason = _reason(reason, "why the request is rejected")
    if not _compare_and_set(db, intake_id, expected_version, ("submitted",), status="rejected", review_note=reason,
                            reviewed_by=user["id"], reviewed_at=_now()):
        raise _stale(db, intake_id)
    event = events.enqueue(db, events.AI_USE_REJECTED, "ai_governance", "ai_use_intake", intake_id,
                           {"intake_id": intake_id}, user_id=user["id"], org_id=user.get("org_id"),
                           dedup_key=f"ai_use.rejected:{intake_id}")
    return {"intake": _intake(_load(db, intake_id)), "events": [event],
            "audit": [("ai_use_rejected", "ai_use_intake", intake_id, "rejected")]}


# ── Promoting a request into the inventory ──────────────────────────────────

def _new_application(db, user, row, answers: dict, spec: dict) -> int:
    name = (spec.get("name") or answers.get("name") or "").strip()
    if not name or len(name) > 120:
        raise ServiceError(422, "Give the application a name of up to 120 characters.")
    owner = spec.get("owner_user_id", answers.get("owner_user_id"))
    _check_owner(db, user, owner)
    unit = spec.get("business_unit_id", row["business_unit_id"])
    if unit is not None and not _in_scope(user, unit):
        raise ServiceError(400, "Choose a business unit you belong to.")
    if unit is None and bu_scope_ids(user) not in (None, [-1]):
        raise ServiceError(400, "Choose a business unit you belong to.")  # an organization-wide use is for someone with no unit
    criticality = spec.get("criticality") or "medium"
    if criticality not in CRITICALITY:
        raise ServiceError(422, "Criticality must be low, medium, high or critical.")
    vendor_name = (spec.get("vendor_name") or "").strip()
    vendor_id = ensure_canonical(db, vendor_name) if vendor_name else None
    return insert_returning_id(
        db,
        "INSERT INTO applications (name, description, application_type, hosting, vendor_id, business_unit_id, "
        "owner_user_id, criticality, is_active) VALUES (%s, %s, 'AI system', %s, %s, %s, %s, %s, 1)",
        (name, (answers.get("purpose") or None), (answers.get("deployment") or None), vendor_id, unit, owner, criticality))


def approve(db, user, intake_id: int, expected_version, *, application_id=None, new_application=None,
            corrections=None, adopted_tier=None, tier_reason=None, note=None) -> dict:
    """Promote a submitted request: link it to one existing application, or create one. Approving again returns the
    same application and creates nothing."""
    row = _review_intake(db, user, intake_id)
    if row["status"] == "approved":
        return {"intake": _intake(row), "application_id": row["application_id"], "created_application": False,
                "audit": [], "events": [], "already": True}
    if row["status"] != "submitted":
        raise ServiceError(409, "Only a submitted request can be approved.")
    if (application_id is None) == (new_application is None):
        raise ServiceError(400, "Link the request to one existing application or create a new one.")
    if adopted_tier is not None and (adopted_tier not in rules.TIERS or adopted_tier == "needs_review"):
        raise ServiceError(422, "Choose lower, moderate or elevated.")
    if adopted_tier is not None:
        tier_reason = _reason(tier_reason, "why you chose this tier")
    answers = {**json.loads(row["payload"] or "{}"), **(_clean_answers(db, user, corrections) if corrections else {})}
    if not isinstance(new_application, (dict, type(None))):
        raise ServiceError(400, "Send the new application as an object.")

    if application_id is not None:
        if isinstance(application_id, bool) or not isinstance(application_id, int):
            raise ServiceError(400, "Choose an application.")
        if not describe_record(db, APP, application_id, user):
            raise ServiceError(404, "Application not found.")
        if db.execute("SELECT 1 FROM ai_use_profiles WHERE application_id = %s", (application_id,)).fetchone():
            raise ServiceError(409, "That application already has an AI profile.", application_id=application_id)

    # Claim the request first: of two reviewers acting together only one gets past this line, and a retry of the
    # same call finds the work already done instead of creating a second application.
    claimed = _compare_and_set(db, intake_id, expected_version, ("submitted",), status="approved",
                               review_note=(note or "").strip()[:MAX_REASON] or None, reviewed_by=user["id"],
                               reviewed_at=_now())
    if not claimed:
        current = _load(db, intake_id)
        if current and current["status"] == "approved":
            return {"intake": _intake(current), "application_id": current["application_id"],
                    "created_application": False, "audit": [], "events": [], "already": True}
        raise _stale(db, intake_id)

    created = application_id is None
    if created:
        application_id = _new_application(db, user, row, answers, new_application or {})
    db.execute("UPDATE ai_use_intake_requests SET application_id = %s WHERE id = %s", (application_id, intake_id))
    profile = _insert_profile(db, user, application_id, answers, adopted_tier, tier_reason)
    event = events.enqueue(db, events.AI_USE_APPROVED, "ai_governance", "application", application_id,
                           {"intake_id": intake_id, "application_id": application_id}, user_id=user["id"],
                           org_id=user.get("org_id"), dedup_key=f"ai_use.approved:{intake_id}")
    audit = [("ai_use_approved", "application", application_id,
              f"request {intake_id} accepted, {'application created' if created else 'linked to an existing application'}"
              + (" (the reviewer accepted their own request)" if row["submitted_by"] == user["id"] else ""))]
    if created:
        audit.append(("application_created", "application", application_id, "from an AI use request"))
    audit.append(("ai_profile_created", "application", application_id, f"provisional tier {profile['provisional_tier']}"))
    return {"intake": _intake(_load(db, intake_id)), "application_id": application_id, "created_application": created,
            "events": [event], "audit": audit}


# ── The AI profile ──────────────────────────────────────────────────────────

def _profile_values(answers: dict) -> dict:
    values = {}
    for source, value in answers.items():
        target = _INTAKE_TO_PROFILE.get(source, source)
        if target in _PROFILE_FIELDS:
            values[target] = value
    return values


def _screening_input(values: dict) -> dict:
    return {("provider_name" if k == "provider_note" else k): v for k, v in values.items()}


def _next_review(last, cadence_months):
    if not cadence_months:
        return None
    start = utcnow() if not last else datetime.strptime(str(last)[:19], "%Y-%m-%d %H:%M:%S")
    return (start + timedelta(days=30 * int(cadence_months))).strftime("%Y-%m-%d")


def _insert_profile(db, user, application_id: int, answers: dict, adopted_tier=None, tier_reason=None) -> dict:
    values = _profile_values(answers)
    screening = rules.screen(_screening_input(values))
    now = _now()
    cadence = answers.get("review_cadence_months")
    db.execute(
        "INSERT INTO ai_use_profiles (application_id, purpose, capability_type, intended_users, affected_people, "
        "autonomy, deployment, provider_note, data_categories, jurisdictions, external_access, affects_decisions, "
        "human_oversight, target_launch, last_reviewed_at, next_review_at, provisional_tier, tier_rule_version, "
        "tier_reasons, adopted_tier, adopted_tier_reason, adopted_by, adopted_at, fingerprint, created_by, updated_by) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (application_id, values.get("purpose"), values.get("capability_type"), values.get("intended_users"),
         json.dumps(values.get("affected_people") or []), values.get("autonomy"), values.get("deployment"),
         values.get("provider_note"), json.dumps(values.get("data_categories") or []),
         json.dumps(values.get("jurisdictions") or []), _bit(values.get("external_access")),
         _bit(values.get("affects_decisions")), values.get("human_oversight"), values.get("target_launch"),
         now, _next_review(None, cadence), screening["tier"], screening["rule_version"],
         json.dumps(screening["reasons"]), adopted_tier, tier_reason if adopted_tier else None,
         user["id"] if adopted_tier else None, now if adopted_tier else None, fingerprint(values),
         user["id"], user["id"]))
    return {"provisional_tier": screening["tier"]}


def _bit(value):
    return None if value is None else (1 if value else 0)


def _profile(row) -> "dict | None":
    if row is None:
        return None
    out = {k: row[k] for k in ("id", "application_id", "version", "review_cadence_months")}
    out["material_changed_at"] = _text(row["material_changed_at"])
    for field in _PROFILE_FIELDS:
        value = row[field]
        out[field] = _json_list(value) if field in _JSON_FIELDS else (None if value is None else (bool(value) if field in _BOOL_FIELDS else value))
    screening = rules.screen({("provider_name" if k == "provider_note" else k): v for k, v in out.items()})
    out.update({
        "provisional_tier": row["provisional_tier"], "adopted_tier": row["adopted_tier"],
        "adopted_tier_reason": row["adopted_tier_reason"], "adopted_by": row["adopted_by"],
        "adopted_at": _text(row["adopted_at"]), "tier_rule_version": row["tier_rule_version"],
        "tier": rules.effective_tier(row["provisional_tier"], row["adopted_tier"]),
        "tier_reasons": _json_list(row["tier_reasons"]), "missing": screening["missing"],
        "last_reviewed_at": _text(row["last_reviewed_at"]), "next_review_at": _text(row["next_review_at"]),
        "fingerprint": row["fingerprint"], "updated_at": _text(row["updated_at"]),
    })
    return out


def get_profile(db, user, application_id: int) -> "dict | None":
    """The profile of an application the user may open (None when there is none, or the application is hidden)."""
    _require(user, "ai_use.view")
    if not describe_record(db, APP, application_id, user):
        return None
    return _profile(db.execute("SELECT * FROM ai_use_profiles WHERE application_id = %s", (application_id,)).fetchone())


def update_profile(db, user, application_id: int, raw_answers, expected_version) -> dict:
    """A reviewer edits the facts the profile owns. The provisional tier is recalculated; an adopted tier stays until the
    reviewer adopts another. A change to a covered fact changes the fingerprint a later decision compares against."""
    _require(user, "ai_use.review")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "Application not found.")
    row = db.execute("SELECT * FROM ai_use_profiles WHERE application_id = %s", (application_id,)).fetchone()
    if row is None:
        raise ServiceError(404, "This application has no AI profile yet.")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the profile you are changing.")
    answers = _clean_answers(db, user, raw_answers or {})
    answers.pop("business_unit_id", None)
    answers.pop("owner_user_id", None)
    current = _profile(row)
    merged = {**{f: current[f] for f in _PROFILE_FIELDS}, **_profile_values(answers)}
    screening = rules.screen(_screening_input(merged))
    cadence = raw_answers.get("review_cadence_months") if isinstance(raw_answers, dict) else None
    sets = {f: (json.dumps(merged[f]) if f in _JSON_FIELDS else _bit(merged[f]) if f in _BOOL_FIELDS else merged[f])
            for f in _PROFILE_FIELDS}
    sets.update(provisional_tier=screening["tier"], tier_rule_version=screening["rule_version"],
                tier_reasons=json.dumps(screening["reasons"]), fingerprint=fingerprint(merged), updated_by=user["id"])
    if fingerprint(merged) != row["fingerprint"]:
        sets["material_changed_at"] = _now()  # what a step done before this moment was done against has changed
    if cadence is not None:
        if isinstance(cadence, bool) or not isinstance(cadence, int) or not 1 <= cadence <= 60:
            raise ServiceError(422, "The review cadence must be a whole number of months from 1 to 60.")
        sets["review_cadence_months"] = cadence
        sets["next_review_at"] = _next_review(row["last_reviewed_at"], cadence)
    columns = ", ".join(f"{k} = %s" for k in sets)
    done = db.execute(
        f"UPDATE ai_use_profiles SET {columns}, version = version + 1, updated_at = %s WHERE id = %s AND version = %s",
        (*sets.values(), _now(), row["id"], expected_version)).rowcount
    if done != 1:
        raise ServiceError(409, "This profile was changed by someone else. Reload it and try again.")
    material = fingerprint(merged) != row["fingerprint"]
    out = {"profile": _profile(db.execute("SELECT * FROM ai_use_profiles WHERE id = %s", (row["id"],)).fetchone()),
           "events": [], "audit": [("ai_profile_updated", "application", application_id,
                                    "a fact the decision covers changed" if material else "edited")]}
    if material:
        out["events"].append(events.enqueue(
            db, events.AI_USE_MATERIAL_CHANGE, "ai_governance", "application", application_id,
            {"application_id": application_id, "fingerprint": fingerprint(merged)}, user_id=user["id"],
            org_id=user.get("org_id"), dedup_key=f"ai_use.material_change:{application_id}:{fingerprint(merged)}"))
    return out


def create_profile(db, user, application_id: int, raw_answers) -> dict:
    """Give an application that has none its AI profile (a reviewer's act)."""
    _require(user, "ai_use.review")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "Application not found.")
    if db.execute("SELECT 1 FROM ai_use_profiles WHERE application_id = %s", (application_id,)).fetchone():
        raise ServiceError(409, "This application already has an AI profile.", application_id=application_id)
    answers = _clean_answers(db, user, raw_answers or {})
    profile = _insert_profile(db, user, application_id, answers)
    return {"profile": _profile(db.execute("SELECT * FROM ai_use_profiles WHERE application_id = %s",
                                           (application_id,)).fetchone()),
            "events": [], "audit": [("ai_profile_created", "application", application_id,
                                     f"provisional tier {profile['provisional_tier']}")]}


def adopt_tier(db, user, application_id: int, tier, reason, expected_version) -> dict:
    """A reviewer records the tier they adopt and why. It does not approve the use; it only replaces the provisional tier."""
    _require(user, "ai_use.review")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "Application not found.")
    if tier not in rules.TIERS or tier == "needs_review":
        raise ServiceError(422, "Choose lower, moderate or elevated.")
    reason = _reason(reason, "why you chose this tier")
    row = db.execute("SELECT version FROM ai_use_profiles WHERE application_id = %s", (application_id,)).fetchone()
    if row is None:
        raise ServiceError(404, "This application has no AI profile yet.")
    done = db.execute(
        "UPDATE ai_use_profiles SET adopted_tier = %s, adopted_tier_reason = %s, adopted_by = %s, adopted_at = %s, "
        "updated_by = %s, version = version + 1, updated_at = %s WHERE application_id = %s AND version = %s",
        (tier, reason, user["id"], _now(), user["id"], _now(), application_id, expected_version)).rowcount
    if done != 1:
        raise ServiceError(409, "This profile was changed by someone else. Reload it and try again.")
    return {"profile": get_profile(db, user, application_id), "events": [],
            "audit": [("ai_tier_adopted", "application", application_id, f"tier {tier}")]}


def mark_reviewed(db, user, application_id: int) -> dict:
    """Record that a reviewer looked over the profile today and set the next review date from its cadence."""
    _require(user, "ai_use.review")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "Application not found.")
    row = db.execute("SELECT review_cadence_months FROM ai_use_profiles WHERE application_id = %s", (application_id,)).fetchone()
    if row is None:
        raise ServiceError(404, "This application has no AI profile yet.")
    now = _now()
    db.execute("UPDATE ai_use_profiles SET last_reviewed_at = %s, next_review_at = %s, updated_by = %s, updated_at = %s, "
               "version = version + 1 WHERE application_id = %s",
               (now, _next_review(now, row["review_cadence_months"]), user["id"], now, application_id))
    return {"profile": get_profile(db, user, application_id), "events": [],
            "audit": [("ai_profile_reviewed", "application", application_id, "profile reviewed")]}


# ── Retiring a use ──────────────────────────────────────────────────────────

def retire(db, user, application_id: int, reason) -> dict:
    """Take an application out of use without deleting it: its history, assessments and links stay."""
    _require(user, "ai_use.review")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "Application not found.")
    reason = _reason(reason, "why this use is being retired")
    done = db.execute(
        "UPDATE applications SET is_active = 0, retired_reason = %s, retired_at = %s, retired_by = %s, updated_at = %s "
        "WHERE id = %s AND is_active = 1", (reason, _now(), user["id"], _now(), application_id)).rowcount
    if done != 1:
        raise ServiceError(409, "This application is already retired.")
    event = events.enqueue(db, events.AI_USE_RETIRED, "ai_governance", "application", application_id,
                           {"application_id": application_id}, user_id=user["id"], org_id=user.get("org_id"),
                           dedup_key=f"ai_use.retired:{application_id}")
    return {"application_id": application_id, "events": [event],
            "audit": [("ai_use_retired", "application", application_id, "retired")]}


def restore(db, user, application_id: int) -> dict:
    _require(user, "ai_use.review")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "Application not found.")
    done = db.execute(
        "UPDATE applications SET is_active = 1, retired_reason = NULL, retired_at = NULL, retired_by = NULL, "
        "updated_at = %s WHERE id = %s AND is_active = 0", (_now(), application_id)).rowcount
    if done != 1:
        raise ServiceError(409, "This application is not retired.")
    return {"application_id": application_id, "events": [],
            "audit": [("ai_use_restored", "application", application_id, "restored")]}


# ── Looking for an application this use may already be ──────────────────────

def search_applications(db, user, q, limit=20) -> list:
    """Applications the reviewer may open that have no AI profile yet, found by name: what a request can be linked to."""
    _require(user, "ai_use.review")
    q = (q or "").strip()
    if len(q) < 2:
        return []
    from core.sql_like import ci_like, like_pattern
    scope, params = entity_scope_sql(APP, user, "a")
    rows = db.execute(
        "SELECT a.id, a.name FROM applications a WHERE a.is_active = 1 "
        "AND NOT EXISTS (SELECT 1 FROM ai_use_profiles p WHERE p.application_id = a.id) "
        f"AND {scope} AND {ci_like('a.name')} ORDER BY a.name LIMIT %s",
        [*params, like_pattern(q), max(1, min(int(limit), 50))]).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def _normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def find_duplicates(db, user, name, provider=None, limit=5) -> list:
    """Applications the user may open that this use may already be, with the reason each matched. Hidden applications
    never appear: a reviewer matches those from their own, wider, view."""
    _require(user, "ai_use.submit")
    want, vendor = _normal(name), _normal(provider)
    if len(want) < 3 and len(vendor) < 3:
        return []
    scope, params = entity_scope_sql(APP, user, "a")
    rows = db.execute(
        "SELECT a.id, a.name, a.is_active, cv.name AS vendor_name, "
        "(SELECT 1 FROM ai_use_profiles p WHERE p.application_id = a.id) AS has_profile "
        "FROM applications a LEFT JOIN canonical_vendors cv ON cv.id = a.vendor_id "
        f"WHERE a.is_active = 1 AND {scope} ORDER BY a.name LIMIT 2000", params).fetchall()
    found = []
    for row in rows:
        have, have_vendor = _normal(row["name"]), _normal(row["vendor_name"])
        reason, rank = None, 0
        if want and have == want:
            reason, rank = "Same name", 3
        elif len(want) >= 4 and have and (want in have or have in want) and min(len(have), len(want)) >= 4:
            reason, rank = "Similar name", 2
        elif len(vendor) >= 3 and vendor == have_vendor:
            reason, rank = "Same provider", 1
        if reason:
            found.append((rank, row["name"], {"id": row["id"], "name": row["name"], "reason": reason,
                                              "has_ai_profile": bool(row["has_profile"]),
                                              "url": f"/ai-governance/systems/{row['id']}"}))
    found.sort(key=lambda item: (-item[0], item[1].lower()))
    return [item[2] for item in found[:max(1, min(int(limit), 10))]]


# ── "Uses AI or embedded AI?" on a vendor or a business process ─────────────

USES_AI = ("yes", "no", "unknown")
_FLAGS = {  # kind -> (table, what else may set it besides a reviewer)
    "vendor": ("canonical_vendors", ("sentinel.vendor.manage", "grid.vendor.manage", "bcm.vendor.manage")),
    "process": ("business_processes", ("governance.entities.manage",)),
}


def set_uses_ai(db, user, kind: str, record_id, answer, note=None, source=None) -> dict:
    """Record whether a vendor or a business process uses AI, who said so and why. Yes and unknown put it in the
    reviewers' queue; nothing is created and no risk is asserted by saying so."""
    if kind not in _FLAGS:
        raise ServiceError(404, "Not found.")
    table, managers = _FLAGS[kind]
    if not (has_capability(user, "ai_use.review") or any(has_capability(user, c) for c in managers)):
        raise ServiceError(403, "Access denied.")
    if answer not in USES_AI:
        raise ServiceError(422, "Answer yes, no or not sure.")
    if isinstance(record_id, bool) or not isinstance(record_id, int):
        raise ServiceError(404, "Not found.")
    note = (note or "").strip() if isinstance(note, str) or note is None else None
    source = (source or "").strip() if isinstance(source, str) or source is None else None
    if note is None or source is None or len(note) > 500 or len(source) > 120:
        raise ServiceError(422, "The note must be text of at most 500 characters and the source at most 120.")
    if kind == "process":
        if not describe_record(db, ("governance", "process"), record_id, user):
            raise ServiceError(404, "Not found.")
    elif not db.execute("SELECT 1 FROM canonical_vendors WHERE id = %s", (record_id,)).fetchone():
        raise ServiceError(404, "Not found.")
    db.execute(
        f"UPDATE {table} SET uses_ai = %s, uses_ai_note = %s, uses_ai_source = %s, uses_ai_set_by = %s, uses_ai_set_at = %s "
        "WHERE id = %s", (answer, note or None, source or None, user["id"], _now(), record_id))
    return {"kind": kind, "id": record_id, "answer": answer, "events": [],
            "audit": [("uses_ai_set", kind, record_id, f"answer {answer}")]}


def flagged_queue(db, user, limit=100) -> list:
    """Vendors and business processes said to use AI (or not known to) that no AI use or open request covers yet."""
    _require(user, "ai_use.review")
    from urllib.parse import quote
    limit = max(1, min(int(limit), 200))
    items = []
    for row in db.execute(
        "SELECT cv.id, cv.name, cv.uses_ai, cv.uses_ai_note, cv.uses_ai_source, cv.uses_ai_set_at FROM canonical_vendors cv "
        "WHERE cv.uses_ai IN ('yes', 'unknown') "
        "AND NOT EXISTS (SELECT 1 FROM applications a JOIN ai_use_profiles p ON p.application_id = a.id WHERE a.vendor_id = cv.id) "
        "AND NOT EXISTS (SELECT 1 FROM ai_use_intake_requests i WHERE i.source_ref = 'vendor:' || cv.id "
        "AND i.status IN ('draft', 'submitted', 'returned')) ORDER BY cv.name LIMIT %s", (limit,)).fetchall():
        items.append(("vendor", row))
    scope, params = entity_scope_sql(("governance", "process"), user, "bp")
    for row in db.execute(
        "SELECT bp.id, bp.name, bp.uses_ai, bp.uses_ai_note, bp.uses_ai_source, bp.uses_ai_set_at FROM business_processes bp "
        f"WHERE bp.is_active = 1 AND bp.uses_ai IN ('yes', 'unknown') AND {scope} "
        "AND NOT EXISTS (SELECT 1 FROM cross_module_links l JOIN ai_use_profiles p ON p.application_id = l.source_id "
        "WHERE l.source_module = 'governance' AND l.source_type = 'application' AND l.target_module = 'governance' "
        "AND l.target_type = 'process' AND l.target_id = bp.id) "
        "AND NOT EXISTS (SELECT 1 FROM cross_module_links l JOIN ai_use_profiles p ON p.application_id = l.target_id "
        "WHERE l.target_module = 'governance' AND l.target_type = 'application' AND l.source_module = 'governance' "
        "AND l.source_type = 'process' AND l.source_id = bp.id) "
        "AND NOT EXISTS (SELECT 1 FROM ai_use_intake_requests i WHERE i.source_ref = 'process:' || bp.id "
        "AND i.status IN ('draft', 'submitted', 'returned')) ORDER BY bp.name LIMIT %s", [*params, limit]).fetchall():
        items.append(("process", row))
    return [{"kind": kind, "id": row["id"], "name": row["name"], "answer": row["uses_ai"], "note": row["uses_ai_note"],
             "source": row["uses_ai_source"], "set_at": _text(row["uses_ai_set_at"]),
             "register_url": f"/ai-governance/register?source={kind}:{row['id']}&name={quote(row['name'] or '')}"}
            for kind, row in items]


# ── After the commit ────────────────────────────────────────────────────────

def audit(user, result) -> None:
    """Write the audit entries of a committed change (a no-op for a repeat that changed nothing)."""
    from core.middleware import log_audit
    for action, entity_type, entity_id, details in (result or {}).get("audit") or []:
        log_audit(user, "ai_governance", action, entity_type, entity_id, details=details)


def deliver(result) -> None:
    """Deliver the events of a committed change; the sweeper picks up whatever this cannot."""
    events.deliver_committed((result or {}).get("events") or [])
