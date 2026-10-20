"""
AI governance G4: decisions on an AI use (plans/ai-governance/07-g4-decision-lifecycle-build.md).

The owner of a use, or a reviewer, asks for a decision; a decider approves, approves with named conditions and an expiry,
returns it or rejects it. What was decided on is frozen with the decision: the facts of the profile, the checklist, the
assessments, the AI controls with the proof held for them and the quality checks, each as the decider saw it. A later
change never edits that record: the workspace state is derived by comparing it with the use as it is now.

Like the rest of the service layer, every function takes the caller's connection and user, checks the capability and the
unit scope itself, never commits, and returns what the route does once it has committed: audit entries and events. A
system the caller may not open answers exactly like one that does not exist.
"""
import hashlib
import json
import logging

from core import ai_rollout, events
from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance import controls, evaluations, guidance, quality, regulation, rules, service
from modules.ai_governance.service import APP, ServiceError
from modules.governance.entity_scope import describe_record, describe_records, entity_scope_sql, may_view_kind

log = logging.getLogger("oneforall.ai_governance")

AIIA = ("sentinel", "aiia")
OUTCOMES = {"approve": "approved", "approve_with_conditions": "approved_with_conditions",
            "return": "returned", "reject": "rejected"}
APPROVALS = ("approved", "approved_with_conditions")
STANDING = ("approved", "approved_with_conditions", "rejected")
MAX_TEXT = 1000
MAX_CONDITIONS = 20
HISTORY_LIMIT = 50
QUEUE_LIMIT = 300

STATE_LABELS = {"none": "No decision", "approved": "Approved", "approved_with_conditions": "Approved with conditions",
                "needs_re_review": "Needs re-review", "expired": "Approval expired", "rejected": "Not approved",
                "revoked": "Revoked"}


# ── Pure rules ──────────────────────────────────────────────────────────────

def derive_state(standing, current, today, proof_expired=False, waiting=False, signals=()) -> dict:
    """The workspace state, from the latest approved or rejected decision and the use as it is now. Nothing is stored:
    `standing` is a dict with status, expires_at, revoked_at, profile_fingerprint and tier (or None), `current` has the
    fingerprint and tier now."""
    out = {"state": "none", "reasons": [], "waiting": bool(waiting)}
    if standing is None:
        return out
    if standing["status"] == "rejected":
        out["state"] = "rejected"
        return out
    if standing.get("revoked_at"):
        out["state"] = "revoked"
        return out
    expires = str(standing.get("expires_at") or "")[:10]
    if expires and expires < today:
        out.update(state="expired", reasons=[f"The approval ran out on {expires}."])
        return out
    reasons = []
    if standing.get("profile_fingerprint") != current.get("fingerprint"):
        reasons.append("A fact the decision covered has changed.")
    if standing.get("tier") != current.get("tier"):
        reasons.append(f"The tier changed from {standing.get('tier') or 'none'} to {current.get('tier') or 'none'}.")
    if proof_expired:
        reasons.append("Proof the decision relied on has expired.")
    reasons.extend(signals)
    if reasons:
        out.update(state="needs_re_review", reasons=reasons)
        return out
    out["state"] = standing["status"]
    return out


def brief_hash(manifest: dict) -> str:
    """A short digest of what a decider was shown, so signing can be refused when the facts moved in between."""
    stable = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32]


def _proposal_source_hash(row) -> "str | None":
    """A new proposal hashes its full record; older proposals hashed only the source brief."""
    if row is None:
        return None
    try:
        frozen = json.loads(row["manifest"] or "{}")
    except (TypeError, ValueError):
        frozen = {}
    return frozen.get("source_hash") if isinstance(frozen, dict) and frozen.get("source_hash") else row["manifest_hash"]


def _hash_as_asked(row, current: dict) -> str:
    """The current brief's digest over what the asker could see. A step the asker could not open was not part of what
    they put forward, so a decider who can open it is not refused for seeing more; any other moved fact still counts."""
    try:
        frozen = json.loads(row["manifest"] or "{}") if row is not None else {}
    except (TypeError, ValueError):
        frozen = {}
    steps = (frozen.get("checklist") or {}).get("steps") if isinstance(frozen, dict) else None
    hidden = {s["key"]: s for s in steps or [] if isinstance(s, dict) and s.get("state") == "no_access" and "key" in s}
    if not hidden:
        return brief_hash(current)
    view = {**current, "checklist": {**current["checklist"],
                                     "steps": [hidden.get(s["key"], s) for s in current["checklist"]["steps"]]}}
    return brief_hash(view)


def _proposal_intact(row) -> bool:
    if row is None or not row["manifest_hash"] or not row["manifest"]:
        return True  # Legacy requests may have no captured brief.
    try:
        frozen = json.loads(row["manifest"])
    except (TypeError, ValueError):
        return False
    return isinstance(frozen, dict) and brief_hash(frozen) == row["manifest_hash"]


def _proposal_access_gap(row, current, user) -> bool:
    if row is None or not row["manifest"]:
        return False
    try:
        frozen = json.loads(row["manifest"])
    except (TypeError, ValueError):
        return False
    if not isinstance(frozen, dict):
        return False
    if isinstance(frozen.get("assessments"), list) and isinstance(current.get("assessments"), dict):
        return True
    if frozen.get("controls") and not controls.can_view(user):
        return True
    before = {s["key"]: s for s in (frozen.get("checklist") or {}).get("steps", [])}
    return any(s.get("state") == "no_access" and before.get(s["key"], {}).get("state") != "no_access"
               for s in (current.get("checklist") or {}).get("steps", []))


def proof_expired_in(manifest, today) -> bool:
    for item in (manifest or {}).get("proof", []):
        expires = str(item.get("expires") or "")[:10]
        if expires and expires < today:
            return True
    return False


def changes_since(old: dict, new: dict, limit: int = 20) -> list:
    """Sentences describing how the use differs now from the manifest a decision was signed on."""
    lines = []
    old_facts, new_facts = (old.get("profile") or {}).get("facts", {}), (new.get("profile") or {}).get("facts", {})
    for field in sorted(set(old_facts) | set(new_facts)):
        if old_facts.get(field) != new_facts.get(field):
            lines.append(f"The {field.replace('_', ' ')} changed.")
    if (old.get("profile") or {}).get("tier") != (new.get("profile") or {}).get("tier"):
        lines.append(f"The tier changed from {(old.get('profile') or {}).get('tier')} to {(new.get('profile') or {}).get('tier')}.")
    old_steps = {s["key"]: s for s in (old.get("checklist") or {}).get("steps", [])}
    for step in (new.get("checklist") or {}).get("steps", []):
        before = old_steps.get(step["key"])
        if before is None:
            continue
        if (before["effective"], before["state"]) != (step["effective"], step["state"]):
            lines.append(f"{step['title']}: {before['state'].replace('_', ' ')} then, {step['state'].replace('_', ' ')} now.")
    old_assessments = {a["id"]: a for a in (old.get("assessments") or []) if isinstance(a, dict) and "id" in a}
    for a in (new.get("assessments") or []):
        if isinstance(a, dict) and "id" in a:
            before = old_assessments.get(a["id"])
            if before is None:
                lines.append(f"A new assessment, {a['ref']}, was added.")
            elif (before["status"], before["version"]) != (a["status"], a["version"]):
                lines.append(f"{a['ref']} changed ({before['status']} then, {a['status']} now).")
    if old.get("proof") != new.get("proof"):
        lines.append("The proof held for the AI controls changed.")
    if old.get("evaluations") != new.get("evaluations"):
        lines.append("The recorded evaluation outcomes changed.")
    if old.get("intended_scope") != new.get("intended_scope"):
        lines.append("The intended scope of use changed.")
    if old.get("accountability") != new.get("accountability"):
        lines.append("The accountable people changed.")
    return lines[:limit]


# ── Reading the use as it is now ────────────────────────────────────────────

def _today() -> str:
    return utcnow().strftime("%Y-%m-%d")


def _app(db, user, application_id):
    """The application row when the viewer may open it (a hidden one is a missing one)."""
    if not describe_record(db, APP, application_id, user):
        return None
    return db.execute("SELECT id, name, owner_user_id, business_unit_id, is_active FROM applications WHERE id = %s",
                      (application_id,)).fetchone()


def _assessments(db, user, application_id):
    if not may_view_kind(user, AIIA):
        return {"state": "no_access"}
    scope, params = entity_scope_sql(AIIA, user, "a")
    rows = db.execute(
        "SELECT a.id, a.ref_number, a.title, a.status, a.overall_classification, a.version, a.updated_at FROM sentinel_aiia a "
        f"WHERE a.application_id = %s AND {scope} ORDER BY a.id LIMIT 20", [application_id, *params]).fetchall()
    return [{"id": r["id"], "ref": r["ref_number"], "status": r["status"],
             "classification": r["overall_classification"], "version": r["version"]} for r in rows]


def _evaluation_manifest(db, user, application_id):
    runs = evaluations.list_runs(db, user, application_id)["runs"]
    recorded = []
    for run in runs:
        artifact = None
        if run["artifact_id"] is not None:
            item_id = run["artifact_id"]
            if describe_record(db, ("evidence", "item"), item_id, user):
                item = db.execute("SELECT version FROM evidence_items WHERE id = %s", (item_id,)).fetchone()
                artifact = {"id": item_id, "version": item["version"] if item else None}
            else:
                artifact = {"restricted": True}
        recorded.append({
            "id": run["id"], "version": run["version"], "name": run["name"], "state": run["state"],
            "stale": run["stale"], "test_set_version": run["test_set_version"],
            "rubric_version": run["rubric_version"], "subject_version": run["subject_version"],
            "scores": run["scores"], "thresholds": run["thresholds"],
            "review_outcome": run["review_outcome"], "finished_at": run["finished_at"],
            "artifact": artifact})
    more = False
    if len(runs) == evaluations.MAX_RUNS_SHOWN:
        count = db.execute("SELECT COUNT(*) AS n FROM ai_evaluation_runs WHERE application_id = %s",
                           (application_id,)).fetchone()["n"]
        more = count > len(runs)
    return recorded, more


def build_manifest(db, user, application_id: int) -> "dict | None":
    """What a decision is signed on, built from the owning modules under the viewer's own scope. None when the viewer
    may not open the system. It carries facts and record references, never the names of other records: those are looked up
    again for whoever reads it (`present_manifest`), so a decision cannot disclose a title to someone who may not open it.
    Time-sensitive evaluation and proof status are included so a newly stale source requires a fresh brief."""
    app = _app(db, user, application_id)
    if app is None:
        return None
    profile = service.get_profile(db, user, application_id)
    plan = guidance.get_checklist(db, user, application_id)
    if profile is None or plan is None:
        return None
    steps = []
    for s in plan["steps"]:
        steps.append({
            "key": s["key"], "title": s["title"], "applicability": s["applicability"], "effective": s["effective"],
            "state": s["state"], "stale": s["stale"],
            "override": ({"reason": s["override"]["reason"], "out_of_date": s["override"]["out_of_date"]} if s["override"] else None),
            "records": [{"ref": r.get("ref"), "status": r["status"], "version": r.get("version"),
                         "source_version_id": r.get("source_version_id"),
                         "updated_at": r.get("updated_at") or ""} for r in s["records"]]})
    found = controls.use_controls(db, user, application_id, proof_limit=None)
    ai_controls, proof = [], []
    for item in found or []:
        ai_controls.append({
            "id": item["control"]["id"], "ref": item["control"]["ref"],
            "applicable": item["applicable"], "implemented": item["implemented"],
            "mapped_to": [m["id"] for m in item["mapped_to"]],
            "proof": {k: item["proof"][k] for k in ("current", "expired", "verified")}})
        proof.extend({"id": p["id"], "version": p["version"], "expired": p["expired"],
                      "verified": p["verified"], "expires": p.get("expires")} for p in item["proof"]["items"])
    proof = sorted({p["id"]: p for p in proof}.values(), key=lambda p: p["id"])
    evaluation_rows, evaluations_partial = _evaluation_manifest(db, user, application_id)
    assessment_rows = _assessments(db, user, application_id)
    scope = {"purpose": profile.get("purpose"), "capability_type": profile.get("capability_type"),
             "provider": profile.get("provider_note"), "intended_users": profile.get("intended_users"),
             "affected_people": profile.get("affected_people"), "deployment": profile.get("deployment"),
             "data_categories": profile.get("data_categories"), "jurisdictions": profile.get("jurisdictions"),
             "external_access": profile.get("external_access"), "autonomy": profile.get("autonomy"),
             "human_oversight": profile.get("human_oversight"), "target_launch": profile.get("target_launch"),
             "business_unit_id": app["business_unit_id"]}
    gaps = []
    if not app["owner_user_id"]:
        gaps.append({"key": "owner", "title": "System owner is not named"})
    if not profile.get("sponsor_user_id") or not profile.get("sponsor_name"):
        gaps.append({"key": "sponsor", "title": "Accountable sponsor is not named"})
    for field, title in (("purpose", "Purpose is not recorded"), ("intended_users", "Intended users are not recorded"),
                         ("deployment", "Deployment is not recorded"), ("jurisdictions", "Jurisdictions are not recorded")):
        if not scope[field]:
            gaps.append({"key": field, "title": title})
    if not evaluation_rows:
        gaps.append({"key": "evaluation", "title": "No evaluation outcome is recorded"})
    elif evaluation_rows[0]["stale"] or evaluation_rows[0]["state"] != "passed":
        gaps.append({"key": "evaluation", "title": "The latest evaluation is not a current pass"})
    if evaluations_partial:
        gaps.append({"key": "evaluation_history", "title": "Older evaluation runs are outside this brief"})
    if isinstance(assessment_rows, list) and len(assessment_rows) == 20:
        assessment_scope, assessment_params = entity_scope_sql(AIIA, user, "a")
        assessment_count = db.execute(
            f"SELECT COUNT(*) AS n FROM sentinel_aiia a WHERE a.application_id = %s AND {assessment_scope}",
            [application_id, *assessment_params]).fetchone()["n"]
        if assessment_count > len(assessment_rows):
            gaps.append({"key": "assessment_history", "title": "Older AI impact assessments are outside this brief"})
    if controls.can_view(user) and len(found or []) == 200:
        control_scope, control_params = entity_scope_sql(("orm", "aims"), user, "m")
        control_count = db.execute(
            "SELECT COUNT(*) AS n FROM aims_assessments m JOIN aims_risks r ON r.assessment_id = m.id "
            f"WHERE m.application_id = %s AND {control_scope}", [application_id, *control_params]).fetchone()["n"]
        if control_count > len(found):
            gaps.append({"key": "control_history", "title": "Some AI control assessments are outside this brief"})
    review = quality.evaluate(db, user, application_id) or {"findings": [], "unchecked": [], "rule_version": quality.RULE_VERSION}
    facts = {f: profile[f] for f in service.MATERIAL_FIELDS if f != "sponsor_user_id"}
    facts["human_oversight"] = profile.get("human_oversight")
    return {
        "application": {"id": app["id"], "name": app["name"]},
        "accountability": {"owner_user_id": app["owner_user_id"],
                           "sponsor_user_id": profile.get("sponsor_user_id")},
        "intended_scope": scope,
        "review_due": profile.get("next_review_at"),
        "gaps": gaps,
        "profile": {"version": profile["version"], "fingerprint": profile["fingerprint"], "tier": profile["tier"],
                    "tier_adopted": profile["adopted_tier"] is not None, "tier_rule_version": profile["tier_rule_version"],
                    "facts": facts},
        "checklist": {"rule_version": plan["rule_version"], "steps": steps, "unresolved": plan["unresolved"]},
        "assessments": assessment_rows,
        "evaluations": evaluation_rows,
        "controls": ai_controls,
        "proof": proof,
        "quality": {"rule_version": review["rule_version"], "unchecked": review["unchecked"],
                    "open": [{"key": f["key"], "rule": f["rule"], "severity": f["severity"]}
                             for f in review["findings"] if not f["dismissed"]]},
    }


def present_manifest(db, user, frozen) -> dict:
    """A manifest with the names of the records in it looked up again for this viewer. A record they may not open is
    named by nothing but its kind (`restricted`); an AI control or an assessment likewise."""
    import copy
    out = copy.deepcopy(frozen)
    wanted: dict = {}

    def want(kind, record_id):
        if record_id is not None:
            wanted.setdefault(kind, set()).add(record_id)

    for step in out.get("checklist", {}).get("steps", []):
        for rec in step.get("records", []):
            if rec.get("ref"):
                want((rec["ref"][0], rec["ref"][1]), rec["ref"][2])
    assessments = out.get("assessments")
    if isinstance(assessments, list):
        for a in assessments:
            want(AIIA, a.get("id"))
    for c in out.get("controls", []):
        want(("orm", "ai_control"), c.get("id"))
    for p in out.get("proof", []):
        want(("evidence", "item"), p.get("id"))
    for run in out.get("evaluations", []):
        artifact = run.get("artifact") or {}
        want(("evidence", "item"), artifact.get("id"))
    found = {kind: describe_records(db, kind, sorted(ids), user) for kind, ids in wanted.items()}

    def name(entry, kind, record_id):
        shown = found.get(kind, {}).get(record_id)
        if shown is None:
            entry.clear()
            entry["restricted"] = True
        else:
            entry["title"] = shown["title"]
            entry["url"] = shown["url"]
            entry["restricted"] = False

    for step in out.get("checklist", {}).get("steps", []):
        for rec in step.get("records", []):
            if rec.get("ref"):
                name(rec, (rec["ref"][0], rec["ref"][1]), rec["ref"][2])
            else:
                rec.update(title=None, url=None, restricted=False)
    if isinstance(assessments, list):
        for a in assessments:
            name(a, AIIA, a.get("id"))
    for c in out.get("controls", []):
        name(c, ("orm", "ai_control"), c.get("id"))
        if not c["restricted"]:
            c.pop("mapped_to", None)
            c.pop("proof", None)
    for p in out.get("proof", []):
        name(p, ("evidence", "item"), p.get("id"))
    for run in out.get("evaluations", []):
        artifact = run.get("artifact") or {}
        if artifact.get("id") is not None:
            name(artifact, ("evidence", "item"), artifact["id"])
    scope = out.get("intended_scope")
    if isinstance(scope, dict) and scope.get("business_unit_id") is not None:
        unit = db.execute("SELECT name FROM business_units WHERE id = %s", (scope["business_unit_id"],)).fetchone()
        scope["business_unit_name"] = unit["name"] if unit else None
    people = out.get("accountability")
    if isinstance(people, dict):
        app_org = service._application_org(db, out.get("application", {}).get("id")) or user.get("org_id")
        for role in ("owner", "sponsor"):
            person_id = people.pop(role + "_user_id", None)
            person = db.execute("SELECT full_name, org_id, is_active, deleted_at FROM users WHERE id = %s", (person_id,)).fetchone() if person_id else None
            people[role] = (person["full_name"] if person and person["is_active"] and not person["deleted_at"] and app_org is not None
                            and person["org_id"] == app_org and service._same_org(user, person["org_id"]) else None)
    return out


# ── Decisions as rows ───────────────────────────────────────────────────────

def _names(db, ids) -> dict:
    wanted = sorted({i for i in ids if i})
    if not wanted:
        return {}
    rows = db.execute(f"SELECT id, full_name FROM users WHERE id IN ({','.join(['%s'] * len(wanted))})", wanted).fetchall()
    return {r["id"]: r["full_name"] for r in rows}


def _conditions(db, decision_ids) -> dict:
    if not decision_ids:
        return {}
    rows = db.execute(
        "SELECT id, decision_id, position, text, due_date, status, met_by, met_at, note FROM ai_use_decision_conditions "
        f"WHERE decision_id IN ({','.join(['%s'] * len(decision_ids))}) ORDER BY decision_id, position", list(decision_ids)).fetchall()
    out: dict = {}
    for r in rows:
        out.setdefault(r["decision_id"], []).append({
            "id": r["id"], "text": r["text"], "due_date": str(r["due_date"] or "")[:10] or None, "status": r["status"],
            "met_by": r["met_by"], "met_at": service._text(r["met_at"]), "note": r["note"]})
    return out


def _present(db, rows) -> list:
    """Decision rows as dicts with names and conditions, without the manifest (that is a call of its own)."""
    rows = list(rows)
    names = _names(db, [i for r in rows for i in (r["requested_by"], r["decided_by"], r["revoked_by"],
                                                   r["assigned_decider_id"] if "assigned_decider_id" in r.keys() else None)])
    conditions = _conditions(db, [r["id"] for r in rows])
    out = []
    for r in rows:
        met_names = _names(db, [c["met_by"] for c in conditions.get(r["id"], [])])
        out.append({
            "id": r["id"], "application_id": r["application_id"], "status": r["status"], "version": r["version"],
            "requested_by": names.get(r["requested_by"]), "requested_at": service._text(r["requested_at"]),
            "request_note": r["request_note"], "decided_by": names.get(r["decided_by"]),
            "decided_at": service._text(r["decided_at"]), "rationale": r["rationale"],
            "expires_at": str(r["expires_at"] or "")[:10] or None, "tier": r["tier"],
            "profile_version": r["profile_version"], "rule_version": r["rule_version"],
            "override_reason": r["override_reason"], "separation_enforced": bool(r["separation_enforced"]),
            "manifest_hash": r["manifest_hash"], "revoked_at": service._text(r["revoked_at"]),
            "revoked_by": names.get(r["revoked_by"]), "revoked_reason": r["revoked_reason"],
            "assigned_decider_id": r["assigned_decider_id"] if "assigned_decider_id" in r.keys() else None,
            "assigned_decider": names.get(r["assigned_decider_id"] if "assigned_decider_id" in r.keys() else None),
            "conditions": [{**c, "met_by": met_names.get(c["met_by"])} for c in conditions.get(r["id"], [])]})
    return out


def _load(db, user, decision_id):
    """A decision row whose system the caller may open; anything else is a 404."""
    row = db.execute("SELECT * FROM ai_use_decisions WHERE id = %s", (decision_id,)).fetchone()
    if row is None or _app(db, user, row["application_id"]) is None:
        raise ServiceError(404, "Decision not found.")
    return row


def _text(value, what: str, minimum: int = 3, required: bool = True):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ServiceError(422, f"Say {what}.")
        return None
    if not isinstance(value, str):
        raise ServiceError(422, f"The text for {what} must be text.")
    value = value.strip()
    if len(value) < minimum:
        raise ServiceError(422, f"Say {what}.")
    if len(value) > MAX_TEXT:
        raise ServiceError(422, f"Keep {what} to {MAX_TEXT} characters or fewer.")
    return value


def _date(value, what: str):
    if value in (None, ""):
        return None
    from datetime import datetime
    try:
        when = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ServiceError(422, f"The {what} must be a date.")
    if when <= utcnow().date():
        raise ServiceError(422, f"The {what} must be a later date.")
    return when.isoformat()


def _clean_conditions(raw) -> list:
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_CONDITIONS:
        raise ServiceError(422, f"Send the conditions as a list of at most {MAX_CONDITIONS}.")
    out = []
    for item in raw:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            raise ServiceError(422, "Each condition must be text or an object with text.")
        out.append({"text": _text(item.get("text"), "what the condition is", minimum=3),
                    "due_date": _date(item.get("due_date"), "due date of a condition")})
    return out


# ── Reading ─────────────────────────────────────────────────────────────────

def _standing_and_open(db, application_id):
    rows = db.execute("SELECT * FROM ai_use_decisions WHERE application_id = %s ORDER BY id DESC LIMIT %s",
                      (application_id, HISTORY_LIMIT + 1)).fetchall()
    open_request = next((r for r in rows if r["status"] == "proposed"), None)
    standing = next((r for r in rows if r["status"] in STANDING), None)
    if standing is None:
        # The history shown in the UI is bounded, but the standing decision must
        # remain authoritative even after many returned decision requests.
        standing = db.execute(
            "SELECT * FROM ai_use_decisions WHERE application_id = %s "
            "AND status IN ('approved','approved_with_conditions','rejected') ORDER BY id DESC LIMIT 1",
            (application_id,),
        ).fetchone()
    return rows, open_request, standing


def reopening_facts(db, application_id: int, decided_at) -> list:
    """What was recorded about a use after a decision was signed that reopens it. Names no record."""
    facts = []
    if evaluations.failed_since(db, application_id, decided_at):
        facts.append("An evaluation failed or did not finish after the decision was signed.")
    if regulation.confirmed_since(db, application_id, decided_at):
        facts.append("A regulatory change was confirmed for this use after the decision was signed.")
    return facts


def _state_of(standing, current, today, waiting, signals=()) -> dict:
    manifest = None
    if standing is not None and standing["manifest"]:
        try:
            manifest = json.loads(standing["manifest"])
        except (TypeError, ValueError):
            manifest = None
    return derive_state(
        None if standing is None else {
            "status": standing["status"], "expires_at": standing["expires_at"], "revoked_at": standing["revoked_at"],
            "profile_fingerprint": standing["profile_fingerprint"], "tier": standing["tier"]},
        current, today, proof_expired=proof_expired_in(manifest, today), waiting=waiting, signals=signals)


def get_decisions(db, user, application_id: int) -> "dict | None":
    """The standing state of a system, its open request, its history and what the viewer may do. None when hidden."""
    service._require(user, "ai_use.view")
    app = _app(db, user, application_id)
    if app is None:
        return None
    from modules.ai_governance import oversight
    oversight_status = oversight.summary_for_use(db, user, application_id)
    profile = service.get_profile(db, user, application_id)
    rows, open_request, standing = _standing_and_open(db, application_id)
    today = _today()
    current = {"fingerprint": profile["fingerprint"], "tier": profile["tier"]} if profile else {"fingerprint": None, "tier": None}
    signals = reopening_facts(db, application_id, standing["decided_at"]) if standing is not None and standing["status"] in APPROVALS else ()
    state = _state_of(standing, current, today, waiting=open_request is not None, signals=signals)
    state["label"] = STATE_LABELS[state["state"]]
    present = _present(db, rows[:HISTORY_LIMIT])
    by_id = {p["id"]: p for p in present}
    if standing is not None and standing["id"] not in by_id:
        by_id[standing["id"]] = _present(db, [standing])[0]
    separation = ai_rollout.separation_required(user.get("org_id"))
    owner = app["owner_user_id"] == user["id"]
    can_decide_role = has_capability(user, "ai_use.decide")
    blocked = None
    if open_request is not None and can_decide_role and separation and (user["id"] == open_request["requested_by"] or owner):
        blocked = "Someone other than the person who asked, and the system's owner, has to decide."
    revocable = standing is not None and standing["status"] in APPROVALS and not standing["revoked_at"]
    return {
        "application": {"id": app["id"], "name": app["name"], "active": bool(app["is_active"])},
        "oversight": oversight_status,
        "state": state,
        "latest": by_id.get(standing["id"]) if standing is not None else None,
        "open_request": by_id.get(open_request["id"]) if open_request is not None else None,
        "history": [p for p in present if p["status"] != "proposed"],
        "separation_required": separation,
        "can": {
            "request": bool(profile and app["is_active"] and open_request is None
                            and (owner or has_capability(user, "ai_use.review"))),
            "decide": bool(open_request is not None and can_decide_role and blocked is None),
            "decide_blocked": blocked,
            "revoke": bool(can_decide_role and revocable),
            "withdraw": bool(open_request is not None and (open_request["requested_by"] == user["id"]
                                                           or has_capability(user, "ai_use.review"))),
            "conditions": bool(owner or has_capability(user, "ai_use.review") or can_decide_role),
            "assign": bool(open_request is not None and (has_capability(user, "ai_use.review") or can_decide_role))}}


def get_brief(db, user, application_id: int) -> "dict | None":
    """What a decider would be shown now: the manifest, its digest, what blocks an approval, and what changed since the
    standing decision. None when the viewer may not open the system or it has no profile."""
    service._require(user, "ai_use.view")
    manifest = build_manifest(db, user, application_id)
    if manifest is None:
        return None
    _rows, open_request, standing = _standing_and_open(db, application_id)
    steps = {s["key"]: s for s in manifest["checklist"]["steps"]}
    old = None
    if standing is not None and standing["manifest"]:
        try:
            old = json.loads(standing["manifest"])
        except (TypeError, ValueError):
            old = None
    unresolved = ([{"key": k, "title": steps[k]["title"]} for k in manifest["checklist"]["unresolved"]]
                  + manifest["gaps"])
    return {
        "manifest": present_manifest(db, user, manifest), "hash": brief_hash(manifest),
        "unresolved": unresolved, "needs_override": bool(unresolved),
        "proposal_access_limited": _proposal_access_gap(open_request, manifest, user),
        "proposal_changed": bool(open_request is not None and (
            not _proposal_intact(open_request) or
            (_proposal_source_hash(open_request)
             and _proposal_source_hash(open_request) != _hash_as_asked(open_request, manifest)))),
        "changed_since_standing": changes_since(present_manifest(db, user, old),
                                                 present_manifest(db, user, manifest)) if old else [],
        "open_request_id": open_request["id"] if open_request is not None else None}


def get_decision(db, user, decision_id: int) -> dict:
    """One decision with the manifest it was signed on. Titles are looked up again for this viewer: a record they may
    not open is named by nothing but its kind."""
    service._require(user, "ai_use.view")
    row = _load(db, user, decision_id)
    out = _present(db, [row])[0]
    manifest = None
    if row["manifest"]:
        try:
            manifest = json.loads(row["manifest"])
        except (TypeError, ValueError):
            manifest = None
    out["manifest"] = present_manifest(db, user, manifest) if manifest else None
    return out


def list_queue(db, user) -> dict:
    """Open requests and re-reviews the viewer may act on or follow, inside their unit scope."""
    service._require(user, "ai_use.view")
    scope, params = entity_scope_sql(APP, user, "a")
    today = _today()
    requests = db.execute(
        "SELECT d.id, d.application_id, d.requested_at, d.request_note, d.requested_by, a.name, a.owner_user_id "
        f"FROM ai_use_decisions d JOIN applications a ON a.id = d.application_id WHERE d.status = 'proposed' AND {scope} "
        "ORDER BY d.requested_at, d.id LIMIT %s", [*params, QUEUE_LIMIT]).fetchall()
    names = _names(db, [r["requested_by"] for r in requests])
    standing = db.execute(
        "SELECT d.* FROM ai_use_decisions d JOIN applications a ON a.id = d.application_id "
        "WHERE d.status IN ('approved', 'approved_with_conditions') AND d.revoked_at IS NULL "
        "AND d.id = (SELECT MAX(x.id) FROM ai_use_decisions x WHERE x.application_id = d.application_id "
        "AND x.status IN ('approved', 'approved_with_conditions', 'rejected')) "
        f"AND a.is_active = 1 AND {scope} ORDER BY d.id LIMIT %s", [*params, QUEUE_LIMIT]).fetchall()
    profiles = {}
    if standing:
        marks = ",".join(["%s"] * len(standing))
        for p in db.execute(f"SELECT application_id, fingerprint, provisional_tier, adopted_tier FROM ai_use_profiles "
                            f"WHERE application_id IN ({marks})", [r["application_id"] for r in standing]).fetchall():
            profiles[p["application_id"]] = {"fingerprint": p["fingerprint"],
                                             "tier": rules.effective_tier(p["provisional_tier"], p["adopted_tier"])}
    app_names = {r["id"]: r["name"] for r in db.execute(
        f"SELECT id, name FROM applications WHERE id IN ({','.join(['%s'] * len(standing))})",
        [r["application_id"] for r in standing]).fetchall()} if standing else {}
    re_reviews = []
    for r in standing:
        state = _state_of(r, profiles.get(r["application_id"], {"fingerprint": None, "tier": None}), today, False,
                          signals=reopening_facts(db, r["application_id"], r["decided_at"]))
        if state["state"] in ("needs_re_review", "expired"):
            re_reviews.append({"application_id": r["application_id"], "name": app_names.get(r["application_id"]),
                               "state": state["state"], "label": STATE_LABELS[state["state"]], "reasons": state["reasons"],
                               "decision_id": r["id"], "decided_at": service._text(r["decided_at"]),
                               "url": f"/ai-governance/systems/{r['application_id']}#decisions"})
    open_conditions = []
    if standing:
        by_decision = {r["id"]: r for r in standing}
        marks = ",".join(["%s"] * len(by_decision))
        for c in db.execute(
                "SELECT decision_id, COUNT(*) AS n_open, MIN(due_date) AS next_due, "
                "SUM(CASE WHEN due_date IS NOT NULL AND due_date < %s THEN 1 ELSE 0 END) AS n_overdue "
                f"FROM ai_use_decision_conditions WHERE status = 'open' AND decision_id IN ({marks}) GROUP BY decision_id",
                [today, *by_decision]).fetchall():
            d = by_decision[c["decision_id"]]
            open_conditions.append({
                "application_id": d["application_id"], "name": app_names.get(d["application_id"]), "decision_id": d["id"],
                "open": c["n_open"], "overdue": int(c["n_overdue"] or 0), "next_due": str(c["next_due"] or "")[:10] or None,
                "url": f"/ai-governance/systems/{d['application_id']}#decisions"})
        open_conditions.sort(key=lambda e: (e["next_due"] is None, e["next_due"] or "", e["name"] or ""))
    can_decide = has_capability(user, "ai_use.decide")
    return {
        "requests": [{"id": r["id"], "application_id": r["application_id"], "name": r["name"],
                      "requested_by": names.get(r["requested_by"]), "requested_at": service._text(r["requested_at"]),
                      "note": r["request_note"], "url": f"/ai-governance/systems/{r['application_id']}#decisions",
                      "yours": r["requested_by"] == user["id"] or r["owner_user_id"] == user["id"]} for r in requests],
        "re_reviews": re_reviews, "conditions": open_conditions, "can_decide": can_decide}


# ── Changing ────────────────────────────────────────────────────────────────

def _stale(db, decision_id) -> ServiceError:
    row = db.execute("SELECT status, version FROM ai_use_decisions WHERE id = %s", (decision_id,)).fetchone()
    return ServiceError(409, "This request was changed by someone else. Reload it and try again.",
                        current_version=row["version"] if row else None, status_now=row["status"] if row else None)


def request_decision(db, user, application_id: int, note=None, brief=None, *, proposed_conditions=None,
                     proposed_expires_at=None, proposed_review_due=None) -> dict:
    service._require(user, "ai_use.view")
    app = _app(db, user, application_id)
    if app is None:
        raise ServiceError(404, "Application not found.")
    profile = service.get_profile(db, user, application_id)
    if profile is None:
        raise ServiceError(409, "Add the AI profile first.")
    if not app["is_active"]:
        raise ServiceError(409, "A retired use cannot be put forward for a decision. Restore it first.")
    if not (app["owner_user_id"] == user["id"] or has_capability(user, "ai_use.review")):
        raise ServiceError(403, "Access denied.")
    note = _text(note, "the note", required=False)
    manifest = build_manifest(db, user, application_id)
    if manifest is None:
        raise ServiceError(409, "Add the AI profile first.")
    source_digest = brief_hash(manifest)
    if brief is not None and brief != source_digest:
        raise ServiceError(409, "The brief changed while you were reviewing. Reload it before asking for a decision.",
                           brief_changed=True)
    clean_proposal = _clean_conditions(proposed_conditions)
    proposal_expiry = _date(proposed_expires_at, "proposed expiry")
    proposal_review = _date(proposed_review_due, "proposed review date")
    manifest["source_hash"] = source_digest
    manifest["proposed_terms"] = {"conditions": clean_proposal, "expires_at": proposal_expiry,
                                  "review_due": proposal_review or manifest["review_due"]}
    proposal_digest = brief_hash(manifest)
    now = service._now()
    new_id = insert_returning_id(
        db,
        "INSERT INTO ai_use_decisions (application_id, status, requested_by, requested_at, request_note, business_unit_id, "
        "profile_version, profile_fingerprint, tier, rule_version, manifest, manifest_hash, "
        "version, created_at, updated_at) VALUES (%s, 'proposed', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s) "
        "ON CONFLICT (application_id) WHERE status = 'proposed' DO NOTHING",
        (application_id, user["id"], now, note, app["business_unit_id"],
         manifest["profile"]["version"], manifest["profile"]["fingerprint"], manifest["profile"]["tier"],
         manifest["checklist"]["rule_version"], json.dumps(manifest, sort_keys=True, default=str), proposal_digest, now, now))
    if new_id is None:  # one open request per system: the same request again returns the one already open
        existing = db.execute("SELECT * FROM ai_use_decisions WHERE application_id = %s AND status = 'proposed'",
                              (application_id,)).fetchone()
        return {"decision": _present(db, [existing])[0], "created": False, "events": [], "audit": []}
    event = events.enqueue(
        db, events.AI_DECISION_REQUESTED, "ai_governance", "application", application_id,
        {"decision_id": new_id, "application_id": application_id, "business_unit_id": app["business_unit_id"]},
        user_id=user["id"], org_id=user.get("org_id"), dedup_key=f"ai_use.decision_requested:{new_id}")
    row = db.execute("SELECT * FROM ai_use_decisions WHERE id = %s", (new_id,)).fetchone()
    return {"decision": _present(db, [row])[0], "created": True, "events": [event],
            "audit": [("ai_decision_requested", "application", application_id, f"decision {new_id} asked for")]}


def decide(db, user, decision_id: int, outcome, *, rationale=None, conditions=None, expires_at=None, override_reason=None,
           brief=None, expected_version=None, review_due=None) -> dict:
    service._require(user, "ai_use.decide")
    row = _load(db, user, decision_id)
    if outcome not in OUTCOMES:
        raise ServiceError(422, "Choose approve, approve with conditions, return or reject.")
    if row["status"] != "proposed":
        raise ServiceError(409, "This request has already been decided.", status_now=row["status"],
                           current_version=row["version"])
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the request you are deciding.")
    if row["version"] != expected_version:
        raise _stale(db, decision_id)
    app = _app(db, user, row["application_id"])
    separation = ai_rollout.separation_required(user.get("org_id"))
    if separation and (user["id"] == row["requested_by"] or user["id"] == app["owner_user_id"]):
        raise ServiceError(403, "Someone other than the person who asked, and the system's owner, has to decide.")

    approving = outcome in ("approve", "approve_with_conditions")
    status = OUTCOMES[outcome]
    if not approving:
        rationale = _text(rationale, "why", minimum=3)
    else:
        rationale = _text(rationale, "why", minimum=3, required=False)
    clean_conditions = _clean_conditions(conditions)
    if outcome == "approve_with_conditions" and not clean_conditions:
        raise ServiceError(422, "Name at least one condition, or approve without conditions.")
    if outcome != "approve_with_conditions" and clean_conditions:
        raise ServiceError(422, "Conditions go with approving with conditions.")
    expires = _date(expires_at, "expiry") if approving else None
    review_date = _date(review_due, "review date") if approving else None
    if not approving and expires_at not in (None, ""):
        raise ServiceError(422, "An expiry goes with an approval.")
    if not approving and review_due not in (None, ""):
        raise ServiceError(422, "A review date goes with an approval.")

    manifest = build_manifest(db, user, row["application_id"])
    if manifest is None:
        raise ServiceError(409, "Add the AI profile first.")
    digest = brief_hash(manifest)
    if approving and brief != digest:
        raise ServiceError(409, "The facts changed while you were reviewing. Reload the brief and decide again.",
                           brief_changed=True)
    if approving and not _proposal_intact(row):
        raise ServiceError(409, "The proposed brief could not be verified. Withdraw and request a new decision.",
                           brief_changed=True)
    if approving and _proposal_access_gap(row, manifest, user):
        raise ServiceError(403, "This account cannot verify all sources in the proposed brief. Assign a decider with source access.")
    if approving and _proposal_source_hash(row) and _proposal_source_hash(row) != _hash_as_asked(row, manifest):
        raise ServiceError(409, "The brief changed after the decision was requested. Withdraw and request a new decision.",
                           brief_changed=True)
    override = None
    gaps = manifest["checklist"]["unresolved"] + [g["key"] for g in manifest["gaps"]]
    if approving and gaps:
        override = _text(override_reason, "why the decision goes ahead with review gaps unresolved", minimum=10)
    elif override_reason not in (None, ""):
        raise ServiceError(422, "An override reason goes with approving while review gaps remain.")

    if row["manifest"]:
        try:
            proposal = json.loads(row["manifest"])
            if isinstance(proposal, dict) and isinstance(proposal.get("proposed_terms"), dict):
                manifest["proposed_terms"] = proposal["proposed_terms"]
                manifest["proposal_hash"] = row["manifest_hash"]
        except (TypeError, ValueError):
            pass
    manifest["decision_terms"] = {"outcome": status, "rationale": rationale,
                                  "conditions": clean_conditions, "expires_at": expires,
                                  "review_due": review_date or manifest["review_due"],
                                  "override_reason": override}
    signed_digest = brief_hash(manifest)
    now = service._now()
    moved = db.execute(
        "UPDATE ai_use_decisions SET status = %s, decided_by = %s, decided_at = %s, rationale = %s, expires_at = %s, "
        "profile_version = %s, profile_fingerprint = %s, tier = %s, rule_version = %s, manifest = %s, manifest_hash = %s, "
        "override_reason = %s, separation_enforced = %s, version = version + 1, updated_at = %s "
        "WHERE id = %s AND status = 'proposed' AND version = %s",
        (status, user["id"], now, rationale, expires, manifest["profile"]["version"], manifest["profile"]["fingerprint"],
         manifest["profile"]["tier"], manifest["checklist"]["rule_version"], json.dumps(manifest, sort_keys=True, default=str),
         signed_digest, override, 1 if separation else 0, now, decision_id, expected_version)).rowcount
    if moved != 1:
        raise _stale(db, decision_id)
    for position, c in enumerate(clean_conditions, start=1):
        db.execute("INSERT INTO ai_use_decision_conditions (decision_id, position, text, due_date, status) VALUES (%s, %s, %s, %s, 'open')",
                   (decision_id, position, c["text"], c["due_date"]))
    event = events.enqueue(
        db, events.AI_DECISION_MADE, "ai_governance", "application", row["application_id"],
        {"decision_id": decision_id, "application_id": row["application_id"], "status": status,
         "business_unit_id": app["business_unit_id"]},
        user_id=user["id"], org_id=user.get("org_id"), dedup_key=f"ai_use.decision_made:{decision_id}")
    audit = [("ai_decision_made", "application", row["application_id"], f"decision {decision_id}: {status}")]
    if override:
        audit.append(("ai_decision_override", "application", row["application_id"],
                      f"decision {decision_id} went ahead with {len(gaps)} review gap(s) unresolved"))
    if not separation:
        audit.append(("ai_decision_unseparated", "application", row["application_id"],
                      f"decision {decision_id} was made while separation of duties is off"))
    done = db.execute("SELECT * FROM ai_use_decisions WHERE id = %s", (decision_id,)).fetchone()
    return {"decision": _present(db, [done])[0], "events": [event], "audit": audit}


def withdraw(db, user, decision_id: int) -> dict:
    service._require(user, "ai_use.view")
    row = _load(db, user, decision_id)
    if not (row["requested_by"] == user["id"] or has_capability(user, "ai_use.review")):
        raise ServiceError(403, "Access denied.")
    if row["status"] != "proposed":
        raise ServiceError(409, "Only an open request can be withdrawn.", status_now=row["status"])
    now = service._now()
    moved = db.execute(
        "UPDATE ai_use_decisions SET status = 'withdrawn', decided_by = %s, decided_at = %s, version = version + 1, "
        "updated_at = %s WHERE id = %s AND status = 'proposed' AND version = %s",
        (user["id"], now, now, decision_id, row["version"])).rowcount
    if moved != 1:
        raise _stale(db, decision_id)
    return {"events": [], "audit": [("ai_decision_withdrawn", "application", row["application_id"], f"decision {decision_id}")]}


def revoke(db, user, decision_id: int, reason) -> dict:
    service._require(user, "ai_use.decide")
    row = _load(db, user, decision_id)
    if row["status"] not in APPROVALS:
        raise ServiceError(409, "Only an approval can be revoked.", status_now=row["status"])
    if row["revoked_at"]:
        raise ServiceError(409, "This approval was already revoked.")
    reason = _text(reason, "why it is being revoked", minimum=3)
    app = _app(db, user, row["application_id"])
    now = service._now()
    moved = db.execute(
        "UPDATE ai_use_decisions SET revoked_at = %s, revoked_by = %s, revoked_reason = %s, version = version + 1, "
        "updated_at = %s WHERE id = %s AND revoked_at IS NULL AND version = %s",
        (now, user["id"], reason, now, decision_id, row["version"])).rowcount
    if moved != 1:
        raise _stale(db, decision_id)
    event = events.enqueue(
        db, events.AI_DECISION_REVOKED, "ai_governance", "application", row["application_id"],
        {"decision_id": decision_id, "application_id": row["application_id"], "business_unit_id": app["business_unit_id"]},
        user_id=user["id"], org_id=user.get("org_id"), dedup_key=f"ai_use.decision_revoked:{decision_id}")
    return {"events": [event], "audit": [("ai_decision_revoked", "application", row["application_id"],
                                          f"decision {decision_id}: {reason[:120]}")]}


def set_condition(db, user, condition_id: int, met, note=None) -> dict:
    """Mark a condition of an approval met, or open again. The decision as signed is not touched."""
    service._require(user, "ai_use.view")
    cond = db.execute("SELECT * FROM ai_use_decision_conditions WHERE id = %s", (condition_id,)).fetchone()
    if cond is None:
        raise ServiceError(404, "Condition not found.")
    row = _load(db, user, cond["decision_id"])
    app = _app(db, user, row["application_id"])
    if not (app["owner_user_id"] == user["id"] or has_capability(user, "ai_use.review") or has_capability(user, "ai_use.decide")):
        raise ServiceError(403, "Access denied.")
    if not isinstance(met, bool):
        raise ServiceError(422, "Say whether the condition is met.")
    note = _text(note, "the note", required=False)
    now = service._now()
    if met:
        db.execute("UPDATE ai_use_decision_conditions SET status = 'met', met_by = %s, met_at = %s, note = %s WHERE id = %s",
                   (user["id"], now, note, condition_id))
    else:
        db.execute("UPDATE ai_use_decision_conditions SET status = 'open', met_by = NULL, met_at = NULL, note = %s WHERE id = %s",
                   (note, condition_id))
    return {"events": [], "audit": [("ai_condition_met" if met else "ai_condition_reopened", "application",
                                     row["application_id"], f"decision {row['id']}, condition {cond['position']}")]}
