"""
AI governance: precedents for an AI use or a request (plans/2026-10-governance-rework/01 section 5).

A specialist reviewing a use should not start from nothing when the organization has already looked at something like it.
This lists the other AI uses the viewer may open that look like this one, in three bands:

* verified same use   a specialist confirmed it is the same use
* possible match      the same or a very similar name, or the same provider with a similar purpose
* related precedent   the same provider, or the same kind of data in the same way of being provided

Each candidate carries why it matched, how it differs, who owns it, and what was last decided about it, and nothing more: a
name alone is weak evidence, a prior approval is about that use and never carries over, and only a specialist can say two
uses are the same (or are not). The rules are deterministic and versioned; no model decides a match.

Every read is inside the viewer's own business unit scope, so a use they cannot open is not a candidate and does not
change a count.
"""
import re

from core.rbac import has_capability
from modules.ai_governance import rules, service
from modules.ai_governance.service import APP, ServiceError
from modules.governance import relationships
from modules.governance.entity_scope import describe_record, entity_scope_sql

RULE_VERSION = "p1"
VERDICTS = ("same_use", "related", "not_related")
LIMIT_SCANNED = 2000
LIMIT_SHOWN = 10
NOTE_MAX = 500
_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "are", "our", "use", "used", "using", "tool", "system", "ai"}


def _normal(text) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _words(text) -> set:
    return {w for w in re.findall(r"[a-z0-9]{4,}", (text or "").lower()) if w not in _STOP}


def compare(subject: dict, other: dict) -> "dict | None":
    """Why `other` may be the same as, or a precedent for, `subject`; None when nothing points to it. Pure: both are
    plain dicts of name, provider, deployment, data_categories, purpose (and the fields shown as differences)."""
    reasons, score = [], 0
    want, have = _normal(subject.get("name")), _normal(other.get("name"))
    same_name = bool(want) and want == have
    similar_name = (not same_name and len(want) >= 4 and len(have) >= 4 and (want in have or have in want))
    if same_name:
        reasons.append("Same name")
        score += 50
    elif similar_name:
        reasons.append("Similar name")
        score += 25
    p_want, p_have = _normal(subject.get("provider")), _normal(other.get("provider"))
    same_provider = len(p_want) >= 3 and p_want == p_have
    if same_provider:
        reasons.append("Same provider")
        score += 20
    shared_words = _words(subject.get("purpose")) & _words(other.get("purpose"))
    union = _words(subject.get("purpose")) | _words(other.get("purpose"))
    similar_purpose = bool(union) and len(shared_words) / len(union) >= 0.4 and len(shared_words) >= 2
    if similar_purpose:
        reasons.append("Similar purpose")
        score += 15
    shared_data = sorted(set(subject.get("data_categories") or []) & set(other.get("data_categories") or []))
    same_way = bool(subject.get("deployment")) and subject.get("deployment") == other.get("deployment")
    if shared_data and same_way:
        reasons.append("Same way of being provided and shares " + ", ".join(rules.DATA_CATEGORIES.get(c, c).lower() for c in shared_data[:3]))
        score += 8
    if score < 20:
        return None
    band = "possible_match" if (same_name or similar_name or (same_provider and similar_purpose)) else "related_precedent"
    return {"band": band, "score": score, "reasons": reasons}


def differences(subject: dict, other: dict) -> list:
    """What differs between the two, in plain words, so a match is never read as "the same in every way"."""
    out = []
    for field, label, vocab in (("deployment", "How it is provided", rules.DEPLOYMENT), ("autonomy", "How much it decides", rules.AUTONOMY),
                                ("provider", "Provider", None)):
        a, b = subject.get(field), other.get(field)
        if (a or None) != (b or None) and (a or b):
            show = (lambda v: (vocab or {}).get(v, v) if v else "Not recorded")
            out.append({"field": field, "label": label, "this": show(a), "other": show(b)})
    for field, label, vocab in (("data_categories", "Kinds of data", rules.DATA_CATEGORIES),
                                ("affected_people", "Who is affected", rules.AFFECTED_PEOPLE),
                                ("jurisdictions", "Jurisdictions", rules.JURISDICTIONS)):
        a, b = sorted(subject.get(field) or []), sorted(other.get(field) or [])
        if a != b:
            names = lambda values: ", ".join(vocab.get(v, v) for v in values) or "Not recorded"
            out.append({"field": field, "label": label, "this": names(a), "other": names(b)})
    return out


# ── Reading ─────────────────────────────────────────────────────────────────

def _subject_from_profile(db, user, application_id) -> "dict | None":
    shown = service.get_profile(db, user, application_id)
    app = db.execute("SELECT a.name, cv.name AS vendor FROM applications a LEFT JOIN canonical_vendors cv ON cv.id = a.vendor_id "
                     "WHERE a.id = %s", (application_id,)).fetchone()
    if shown is None or app is None:
        return None
    return {"name": app["name"], "provider": app["vendor"] or shown["provider_note"], "deployment": shown["deployment"],
            "autonomy": shown["autonomy"], "data_categories": shown["data_categories"], "affected_people": shown["affected_people"],
            "jurisdictions": shown["jurisdictions"], "purpose": shown["purpose"]}


def _subject_from_request(answers: dict) -> dict:
    return {"name": answers.get("name"), "provider": answers.get("provider_name"), "deployment": answers.get("deployment"),
            "autonomy": answers.get("autonomy"), "data_categories": answers.get("data_categories") or [],
            "affected_people": answers.get("affected_people") or [], "jurisdictions": answers.get("jurisdictions") or [],
            "purpose": answers.get("purpose")}


def _verdicts(db, kind, subject_id) -> dict:
    rows = db.execute(
        "SELECT v.candidate_application_id, v.verdict, v.note, v.decided_at, u.full_name FROM ai_precedent_verdicts v "
        "LEFT JOIN users u ON u.id = v.decided_by WHERE v.subject_kind = %s AND v.subject_id = %s", (kind, subject_id)).fetchall()
    return {r["candidate_application_id"]: {"verdict": r["verdict"], "note": r["note"], "by": r["full_name"],
                                            "at": service._text(r["decided_at"])} for r in rows}


def _enrich(db, user, application_id) -> dict:
    last = db.execute(
        "SELECT status, decided_at, expires_at, revoked_at FROM ai_use_decisions WHERE application_id = %s "
        "AND status IN ('approved', 'approved_with_conditions', 'rejected') ORDER BY id DESC LIMIT 1", (application_id,)).fetchone()
    run = db.execute("SELECT name, result_state, COALESCE(finished_at, recorded_at) AS at FROM ai_evaluation_runs "
                     "WHERE application_id = %s ORDER BY COALESCE(finished_at, recorded_at) DESC, id DESC LIMIT 1",
                     (application_id,)).fetchone()
    links = []
    try:
        links = [{"kind": f"{l['module']}/{l['entity_type']}", "title": l["title"], "label": l["label"], "url": l["url"]}
                 for l in relationships.list_links(db, user, APP, application_id)][:6]
    except Exception:
        links = []
    return {
        "decision": ({"status": last["status"], "decided_at": str(last["decided_at"] or "")[:10] or None,
                      "expires_at": str(last["expires_at"] or "")[:10] or None, "revoked": bool(last["revoked_at"])}
                     if last else None),
        "evaluation": ({"name": run["name"], "state": run["result_state"], "at": str(run["at"] or "")[:10] or None} if run else None),
        "linked": links}


def _candidates(db, user, subject, exclude_application_id, verdicts) -> dict:
    scope, params = entity_scope_sql(APP, user, "a")
    rows = db.execute(
        "SELECT a.id, a.name, a.is_active, a.business_unit_id, bu.name AS bu_name, u.full_name AS owner_name, cv.name AS vendor, "
        "p.provider_note, p.deployment, p.autonomy, p.data_categories, p.affected_people, p.jurisdictions, p.purpose, "
        "p.provisional_tier, p.adopted_tier, p.last_reviewed_at "
        "FROM applications a JOIN ai_use_profiles p ON p.application_id = a.id "
        "LEFT JOIN business_units bu ON bu.id = a.business_unit_id LEFT JOIN users u ON u.id = a.owner_user_id "
        "LEFT JOIN canonical_vendors cv ON cv.id = a.vendor_id "
        f"WHERE {scope} ORDER BY a.name, a.id LIMIT %s", [*params, LIMIT_SCANNED]).fetchall()
    bands = {"verified_same_use": [], "possible_match": [], "related_precedent": []}
    set_aside = []
    for r in rows:
        if r["id"] == exclude_application_id:
            continue
        other = {"name": r["name"], "provider": r["vendor"] or r["provider_note"], "deployment": r["deployment"],
                 "autonomy": r["autonomy"], "data_categories": service._json_list(r["data_categories"]),
                 "affected_people": service._json_list(r["affected_people"]), "jurisdictions": service._json_list(r["jurisdictions"]),
                 "purpose": r["purpose"]}
        verdict = verdicts.get(r["id"])
        match = compare(subject, other)
        if verdict is None and match is None:
            continue
        tier = rules.effective_tier(r["provisional_tier"], r["adopted_tier"])
        item = {"kind": "application", "id": r["id"], "name": r["name"], "url": f"/ai-governance/systems/{r['id']}",
                "active": bool(r["is_active"]), "owner": r["owner_name"], "business_unit": r["bu_name"],
                "tier": tier, "tier_label": rules.TIER_LABELS[tier], "provider": other["provider"],
                "last_reviewed_at": str(r["last_reviewed_at"] or "")[:10] or None,
                "reasons": match["reasons"] if match else [], "score": match["score"] if match else 0,
                "differences": differences(subject, other), "verdict": verdict}
        if verdict and verdict["verdict"] == "not_related":
            set_aside.append(item)
        elif verdict and verdict["verdict"] == "same_use":
            bands["verified_same_use"].append(item)
        elif verdict and verdict["verdict"] == "related":
            bands["related_precedent"].append(item)
        else:
            bands[match["band"]].append(item)
    for key in bands:
        bands[key].sort(key=lambda i: (-i["score"], i["name"].lower(), i["id"]))
    shown = {key: items[:LIMIT_SHOWN] for key, items in bands.items()}
    for items in shown.values():
        for item in items:
            item.update(_enrich(db, user, item["id"]))
    return {"bands": shown, "set_aside": set_aside[:LIMIT_SHOWN],
            "more": {key: max(0, len(items) - LIMIT_SHOWN) for key, items in bands.items()}}


def _wrap(subject, found) -> dict:
    found["none"] = not any(found["bands"].values()) and not found["set_aside"]
    found["rule_version"] = RULE_VERSION
    found["subject"] = {"name": subject.get("name"), "provider": subject.get("provider")}
    found["note"] = ("A match is a prompt to look, not evidence of sameness. A decision about another use is about that use "
                     "and does not carry over to this one.")
    return found


def for_use(db, user, application_id: int) -> "dict | None":
    service._require(user, "ai_use.review")
    if not describe_record(db, APP, application_id, user):
        return None
    subject = _subject_from_profile(db, user, application_id)
    if subject is None:
        return None
    return _wrap(subject, _candidates(db, user, subject, application_id, _verdicts(db, "application", application_id)))


def for_request(db, user, intake_id: int) -> dict:
    service._require(user, "ai_use.review")
    row = service._review_intake(db, user, intake_id)
    subject = _subject_from_request(service._intake(row)["answers"])
    return _wrap(subject, _candidates(db, user, subject, row["application_id"], _verdicts(db, "request", intake_id)))


# ── A specialist's verdict ──────────────────────────────────────────────────

def set_verdict(db, user, subject_kind: str, subject_id, candidate_id, verdict, note=None) -> dict:
    """Record that a candidate is the same use, a related one, or not related; `verdict=None` takes a verdict back. Only a
    reviewer who may open both records can say so. Nothing else changes: a verdict never links, merges or approves."""
    service._require(user, "ai_use.review")
    if subject_kind not in ("application", "request"):
        raise ServiceError(400, "Say whether the verdict is about a use or a request.")
    for value in (subject_id, candidate_id):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ServiceError(400, "Send the ids as whole numbers.")
    if verdict is not None and verdict not in VERDICTS:
        raise ServiceError(422, "Choose same use, related or not related.")
    if subject_kind == "application":
        if not describe_record(db, APP, subject_id, user):
            raise ServiceError(404, "Not found.")
        org = user.get("org_id")
    else:
        org = service._review_intake(db, user, subject_id)["org_id"]
    if not describe_record(db, APP, candidate_id, user) or (subject_kind == "application" and candidate_id == subject_id):
        raise ServiceError(404, "Not found.")
    note = (note or "").strip() if isinstance(note, str) or note is None else None
    if note is None or len(note) > NOTE_MAX:
        raise ServiceError(422, f"Keep the note to {NOTE_MAX} characters or fewer.")
    existing = db.execute("SELECT id FROM ai_precedent_verdicts WHERE subject_kind = %s AND subject_id = %s "
                          "AND candidate_application_id = %s", (subject_kind, subject_id, candidate_id)).fetchone()
    now = service._now()
    if verdict is None:
        if existing:
            db.execute("DELETE FROM ai_precedent_verdicts WHERE id = %s", (existing["id"],))
        action = "ai_precedent_cleared"
    elif existing:
        db.execute("UPDATE ai_precedent_verdicts SET verdict = %s, note = %s, decided_by = %s, decided_at = %s WHERE id = %s",
                   (verdict, note or None, user["id"], now, existing["id"]))
        action = "ai_precedent_verdict"
    else:
        db.execute("INSERT INTO ai_precedent_verdicts (org_id, subject_kind, subject_id, candidate_application_id, verdict, note, "
                   "decided_by, decided_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                   (org, subject_kind, subject_id, candidate_id, verdict, note or None, user["id"], now))
        action = "ai_precedent_verdict"
    entity = "application" if subject_kind == "application" else "ai_use_intake"
    return {"verdict": verdict, "candidate_id": candidate_id, "events": [],
            "audit": [(action, entity, subject_id, f"candidate {candidate_id}: {verdict or 'taken back'}")]}
