"""
AI governance G6a: the AI review pack (plans/ai-governance/09-g6-build-plan.md).

A pack is a frozen, named, read-only account of one AI use, issued to one signed-in person of the same organization with an
expiry, revocable, and opened only through the checks below. What goes in it is read through the author's own scope, so
nothing the author cannot open is in it; people's names and free text go in only when the author chose so; and what the
author reviewed in the preview is what is issued (the preview carries a hash of the content, and issuing it again with a
changed record is refused).

It never says a use is compliant, certified or ready. Anything missing or unreadable is listed as such.

Like the rest of the service layer, every function takes the caller's connection and user, checks the capability and the
scope itself, never commits, and returns the audit entries and events the route handles once it has committed.
Opening a pack is the one exception to "raise on refusal": a refusal is returned, not raised, so the route can commit the
record of it.
"""
import hashlib
import json
import logging
import re
from datetime import timedelta

from core import events
from core.rbac import CAPABILITIES, has_capability
from core.sql_like import ci_like, like_pattern
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance import service
from modules.ai_governance.service import APP, ServiceError
from modules.governance.entity_scope import describe_record

log = logging.getLogger("oneforall.ai_governance")

FORMAT = 1
NAME_MIN, NAME_MAX, PURPOSE_MAX, REASON_MAX = 3, 120, 500, 1000
EXPIRY_DEFAULT_DAYS, EXPIRY_MAX_DAYS = 30, 90
ITEMS_MAX, LINE_MAX, TITLE_MAX = 50, 500, 300
RECIPIENT_SEARCH_MAX = 20
DISCLAIMER = ("This pack states what ThemisIQ held about this AI use on the date it was generated. It is not a certification "
              "and it does not say the use is compliant. What is missing, expired or could not be read is shown as such.")
NOT_FOUND = "Review pack not found."
_STATE_NOTES = {
    "no_access": "Not included. The person who prepared this pack does not have access to this part of the record.",
    "unavailable": "Not included. This part could not be read when the pack was prepared.",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SLUG = re.compile(r"[^a-z0-9]+")


# ── Rules (pure) ────────────────────────────────────────────────────────────

def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(manifest: dict) -> str:
    """sha256 of the manifest without the moment it was generated and without the hash itself: the same record, read twice,
    hashes the same, which is what lets a preview be compared with what is issued."""
    body = {k: v for k, v in manifest.items() if k not in ("generated_at", "hash")}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def preview_hash(manifest: dict, options: dict) -> str:
    """Bind the preview to both the frozen content and the proposed sharing choices.

    The recipient id is used only in this fingerprint. It is never put in the
    recipient-facing manifest.
    """
    sharing = {key: options[key] for key in ("name", "purpose", "recipient_id", "expires_days",
                                           "allow_download", "include_people", "include_notes")}
    return hashlib.sha256(canonical({"manifest_hash": manifest["hash"], "sharing": sharing}).encode("utf-8")).hexdigest()


def _text(value, limit) -> "str | None":
    if not isinstance(value, str):
        return None
    value = _CONTROL.sub("", value).strip()
    return value[:limit] or None


def clean_options(raw, need_recipient: bool = False) -> tuple:
    """(options, errors). A pack has a name, an optional purpose, two redaction choices, a download right, an expiry in days
    and a recipient. Everything a person did not choose is the careful answer: no names, no notes, no download."""
    errors = {}
    raw = raw if isinstance(raw, dict) else {}
    name = _text(raw.get("name"), NAME_MAX + 1)
    if not name or len(name) < NAME_MIN:
        errors["name"] = f"Give the pack a name of at least {NAME_MIN} characters."
    elif len(name) > NAME_MAX:
        errors["name"] = f"Keep the name to {NAME_MAX} characters or fewer."
    purpose = raw.get("purpose")
    if purpose in (None, ""):
        purpose = None
    elif not isinstance(purpose, str):
        errors["purpose"] = "The purpose must be text."
        purpose = None
    else:
        purpose = _CONTROL.sub("", purpose).strip()
        if len(purpose) > PURPOSE_MAX:
            errors["purpose"] = f"Keep the purpose to {PURPOSE_MAX} characters or fewer."
        purpose = purpose or None
    flags = {}
    for field in ("include_people", "include_notes", "allow_download"):
        value = raw.get(field, False)
        if not isinstance(value, bool):
            errors[field] = "Choose yes or no."
            value = False
        flags[field] = value
    days = raw.get("expires_days", EXPIRY_DEFAULT_DAYS)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= EXPIRY_MAX_DAYS:
        errors["expires_days"] = f"Choose an expiry from 1 to {EXPIRY_MAX_DAYS} days."
        days = EXPIRY_DEFAULT_DAYS
    recipient = raw.get("recipient_id")
    if recipient in (None, "") and not need_recipient:
        recipient = None
    elif isinstance(recipient, bool) or not isinstance(recipient, int) or recipient < 1:
        errors["recipient_id"] = "Choose who the pack is for."
        recipient = None
    return ({"name": name, "purpose": purpose, **flags, "expires_days": days, "recipient_id": recipient}, errors)


def _lines(item: dict, options: dict) -> list:
    lines = [str(x) for x in item.get("detail") or [] if x]
    if options["include_people"]:
        lines += [f"{label}: {name}" for label, name in item.get("people") or [] if name]
    if options["include_notes"]:
        lines += [f"{label}: {text}" for label, text in item.get("notes") or [] if text]
    return [_CONTROL.sub("", line)[:LINE_MAX] for line in lines]


def assemble(sections: list, options: dict, application_name: str, unit_name, generated_at: str) -> dict:
    """The manifest from facts already read. Each raw section is {key, title, state, note, items}; an item is
    {title, status, when, detail: [str], people: [(label, name)], notes: [(label, text)]}. People and notes are dropped
    here unless the options keep them, so there is one place that decides what leaves."""
    out = []
    for section in sections:
        raw_items = section.get("items") or []
        items = [{"title": str(item.get("title") or "(untitled)")[:TITLE_MAX], "status": item.get("status"),
                  "when": item.get("when"), "lines": _lines(item, options)} for item in raw_items[:ITEMS_MAX]]
        state = section.get("state") or ("ok" if items else "empty")
        note = _STATE_NOTES.get(state) or section.get("note")
        if len(raw_items) > ITEMS_MAX:
            note = f"Showing the first {ITEMS_MAX} of {len(raw_items)}."
        out.append({"key": section["key"], "title": section["title"], "state": state, "note": note, "items": items})
    gaps = next((s for s in out if s["key"] == "gaps"), None)
    manifest = {
        "format": FORMAT, "generated_at": generated_at, "application": {"name": application_name}, "unit": unit_name,
        "options": {"include_people": options["include_people"], "include_notes": options["include_notes"]},
        "disclaimer": DISCLAIMER, "sections": out,
        "summary": {"gaps": len(gaps["items"]) if gaps else 0,
                    "not_shown": [s["title"] for s in out if s["state"] in ("no_access", "unavailable")]},
    }
    manifest["hash"] = content_hash(manifest)
    return manifest


def changed_sections(old: dict, new: dict) -> list:
    """Titles of the sections whose state or items differ between two manifests built with the same options."""
    def keyed(manifest):
        return {s["key"]: (s["title"], canonical([s["state"], s["items"]])) for s in manifest.get("sections", [])}
    before, after = keyed(old), keyed(new)
    changed = [after[k][0] for k in after if k not in before or before[k][1] != after[k][1]]
    changed += [before[k][0] for k in before if k not in after]
    return changed


def open_refusal(pack: dict, viewer_id, now: str) -> "str | None":
    """Why a recipient may not open the pack now: a stable code, or None when they may."""
    if pack["status"] != "issued":
        return "revoked"
    if str(pack["expires_at"])[:19] <= str(now)[:19]:
        return "expired"
    if pack["recipient_user_id"] != viewer_id:
        return "wrong_recipient"
    return None


def verifies(manifest_json, stored_hash) -> "dict | None":
    """The manifest when it still hashes to the stored value, else None."""
    try:
        manifest = json.loads(manifest_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(manifest, dict) or content_hash(manifest) != stored_hash or manifest.get("hash") != stored_hash:
        return None
    return manifest


# ── Reading what goes in ────────────────────────────────────────────────────

def _item(title, status=None, when=None, detail=None, people=None, notes=None) -> dict:
    return {"title": title, "status": status, "when": str(when)[:10] if when else None, "detail": detail or [],
            "people": people or [], "notes": notes or []}


def _slug(title: str) -> str:
    return _SLUG.sub("_", title.lower()).strip("_")


def _guard(key, title, build):
    try:
        return build()
    except Exception:
        log.warning("AI review pack: %s could not be read", key, exc_info=True)
        return {"key": key, "title": title, "state": "unavailable", "items": [], "note": None}


def _names(db, ids) -> dict:
    wanted = sorted({i for i in ids if i})
    if not wanted:
        return {}
    rows = db.execute(f"SELECT id, full_name FROM users WHERE id IN ({','.join(['%s'] * len(wanted))})", wanted).fetchall()
    return {r["id"]: r["full_name"] for r in rows}


def _join(codes, labels) -> str:
    return ", ".join(labels.get(c, str(c)) for c in codes or [])


def _use_section(db, shown) -> dict:
    app, profile, labels = shown["application"], shown["profile"], shown["labels"]
    tier = labels["tiers"].get(profile["tier"], profile["tier"])
    basis = (f"adopted by a reviewer on {profile['adopted_at'][:10]}" if profile["adopted_tier"] and profile["adopted_at"]
             else "provisional, from the screening rules")
    detail = [f"Purpose: {profile['purpose']}" if profile["purpose"] else "Purpose: not recorded",
              f"Tier: {tier} ({basis})",
              f"Business unit: {app['business_unit'] or 'Organization wide'}",
              f"Status: {'Active' if app['active'] else 'Retired'}"]
    yes_no = {True: "Yes", False: "No"}
    for label, value in (("Use type", labels["capability_type"].get(profile["capability_type"])),
                         ("Autonomy", labels["autonomy"].get(profile["autonomy"])),
                         ("Human oversight", profile["human_oversight"]),
                         ("Intended users", profile["intended_users"]),
                         ("Reachable by people outside the organization", yes_no.get(profile["external_access"])),
                         ("Affects decisions about people", yes_no.get(profile["affects_decisions"])),
                         ("Deployment", labels["deployment"].get(profile["deployment"])),
                         ("Provider", app["vendor"] or profile["provider_note"]),
                         ("Data", _join(profile["data_categories"], labels["data_categories"])),
                         ("People affected", _join(profile["affected_people"], labels["affected_people"])),
                         ("Jurisdictions", _join(profile["jurisdictions"], labels["jurisdictions"])),
                         ("Criticality", app["criticality"]),
                         ("Last reviewed", (profile["last_reviewed_at"] or "")[:10] or "not yet"),
                         ("Next review", (profile["next_review_at"] or "")[:10] or "not set")):
        if value:
            detail.append(f"{label}: {value}")
    if profile["missing"]:
        detail.append("Not yet answered: " + ", ".join(m.replace("_", " ") for m in profile["missing"]))
    names = _names(db, [profile["adopted_by"]])
    notes = []
    if profile["adopted_tier"] and profile["adopted_tier_reason"]:
        notes.append(("Why this tier was adopted", profile["adopted_tier_reason"]))
    if not app["active"] and app["retired_reason"]:
        notes.append(("Why it was retired", app["retired_reason"]))
    people = [("Owner", app["owner"])] + ([("Tier adopted by", names.get(profile["adopted_by"]))] if profile["adopted_tier"] else [])
    return {"key": "use", "title": "The AI use", "items": [_item(app["name"], status=tier, detail=detail, people=people, notes=notes)]}


def _decision_section(decided) -> dict:
    state, latest = decided["state"], decided["latest"]
    items = []
    detail = list(state["reasons"])
    people, notes, when = [], [], None
    if latest:
        when = latest["decided_at"]
        if latest["expires_at"]:
            detail.append(f"Decision expires {latest['expires_at']}")
        detail.append(f"Tier when decided: {latest['tier']}")
        people.append(("Decided by", latest["decided_by"]))
        notes += [("Rationale", latest["rationale"]), ("Reason for an override", latest["override_reason"])]
    items.append(_item(f"Decision: {state['label']}", status=state["state"], when=when, detail=detail, people=people, notes=notes))
    if decided["open_request"]:
        request = decided["open_request"]
        items.append(_item("A request for a decision is waiting", status="proposed", when=request["requested_at"],
                           people=[("Asked by", request["requested_by"])], notes=[("Note", request["request_note"])]))
    for condition in (latest or {}).get("conditions", []):
        items.append(_item(f"Condition: {condition['text']}", status=condition["status"], when=condition["due_date"],
                           detail=["Due " + condition["due_date"]] if condition["due_date"] else [],
                           people=[("Met by", condition["met_by"])], notes=[("Note", condition["note"])]))
    for earlier in decided["history"][:5]:
        if latest and earlier["id"] == latest["id"]:
            continue
        items.append(_item(f"Earlier decision: {earlier['status'].replace('_', ' ')}", status=earlier["status"],
                           when=earlier["decided_at"], people=[("Decided by", earlier["decided_by"])],
                           notes=[("Rationale", earlier["rationale"])]))
    return {"key": "decision", "title": "Decision", "items": items}


def _controls_section(rows) -> dict:
    items = []
    for row in rows:
        c, proof = row["control"], row["proof"]
        status = ("not applicable" if not row["applicable"] else "implemented" if row["implemented"] else "not implemented")
        detail = [f"Part of {row['assessment']['ref'] or ''} {row['assessment']['title']}".replace("  ", " ").strip()]
        if row["mapped"]:
            detail.append("Mapped to: " + ", ".join(m["title"] for m in row["mapped_to"]))
            detail.append(f"Proof: {proof['current']} current, {proof['expired']} expired, {proof['verified']} verified")
            for p in proof["items"][:5]:
                bits = [f"version {p['version']}" if p["version"] else "", f"expires {p['expires']}" if p["expires"] else "",
                        "verified" if p["verified"] else "not verified", "expired" if p["expired"] else ""]
                detail.append(f"{p['title']} ({', '.join(b for b in bits if b)})")
            if row["applicable"] and row["implemented"] and proof["current"] == 0:
                detail.append("No current proof is attached.")
        else:
            detail.append("Not mapped to a canonical control, so no proof can be shown.")
        items.append(_item(f"{c['ref'] or ''} {c['title']}".strip(), status=status, detail=detail))
    return {"key": "controls", "title": "AI controls and their proof", "items": items}


def _evaluations_section(listing) -> dict:
    items = []
    for run in listing["runs"][:10]:
        detail = [f"Test set: {run['test_set_name']} {run['test_set_version'] or ''}".strip() if run["test_set_name"] else "",
                  f"Rubric: {run['rubric_version']}" if run["rubric_version"] else "",
                  f"Evaluated: {run['subject_version']}", f"Evaluator: {run['evaluator']}",
                  "Out of date: the use changed or the run is old" if run["stale"] else ""]
        if run["scores"]:
            detail.append("Scores: " + ", ".join(
                f"{k} {v:g}" + (f" (needs {run['thresholds'][k]:g})" if k in run["thresholds"] else "")
                for k, v in sorted(run["scores"].items())))
        if run["review_outcome"]:
            detail.append(f"Reviewed: {run['review_outcome']}")
        items.append(_item(run["name"], status=run["state_label"], when=run["finished_at"] or run["recorded_at"],
                           detail=[d for d in detail if d], notes=[("Note", run["notes"]), ("Reviewer's note", run["review_note"])]))
    return {"key": "evaluations", "title": "Evaluations", "items": items}


def _regulatory_section(confirmed) -> dict:
    return {"key": "regulatory", "title": "Regulatory changes confirmed for this use", "items": [
        _item(r["title"], status="confirmed", when=r["effective_date"],
              detail=[f"Posted under {r['framework_name']}" + (f", severity {r['severity']}" if r["severity"] else ""),
                      f"Matched because: {r['basis']}" if r["basis"] else ""],
              notes=[("Reviewer's note", r["review_note"])]) for r in confirmed]}


def _gap_sections(db, user, application_id) -> list:
    from modules.ai_governance import guidance, quality
    words = {"not_started": "not started", "in_progress": "in progress"}
    gaps, exceptions, unread = [], [], []
    plan = guidance.get_checklist(db, user, application_id) or {"steps": []}
    for step in plan["steps"]:
        if step["state"] == "unavailable":
            unread.append(step["title"])
        elif step["effective"] == "required" and step["state"] != "complete":
            gaps.append(_item(f"{step['title']} is required and {words.get(step['state'], step['state'])}", status="gap",
                              detail=step["reasons"][:1]))
        elif step["effective"] in ("required", "recommended") and step["state"] == "complete" and step["stale"]:
            gaps.append(_item(f"{step['title']} was completed before the use changed", status="out of date"))
        if step["override"]:
            o = step["override"]
            exceptions.append(_item(f"{step['title']}: judged not applicable", status="out of date" if o["out_of_date"] else "recorded",
                                    when=o["set_at"], people=[("Judged by", o["set_by"])], notes=[("Reason", o["reason"])]))
    review = quality.evaluate(db, user, application_id) or {"findings": [], "unchecked": []}
    for finding in review["findings"]:
        if finding["dismissed"]:
            d = finding["dismissed"]
            exceptions.append(_item(f"{finding['title']}: set aside", status="set aside", when=d["at"],
                                    detail=[f"Until {d['expires_at']}"] if d["expires_at"] else [],
                                    people=[("Set aside by", d["by"])], notes=[("Reason", d["reason"])]))
        else:
            gaps.append(_item(finding["title"], status=finding["severity"], detail=[finding["why"]]))
    unread += review["unchecked"]
    if unread:
        gaps.append(_item("Could not be checked: " + ", ".join(sorted(set(unread))), status="unknown"))
    return [{"key": "gaps", "title": "Known gaps", "items": gaps,
             "note": None if gaps else "No gap was found by the checks that could run."},
            {"key": "exceptions", "title": "Exceptions and findings set aside", "items": exceptions}]


def _from_tab(tab_sections) -> list:
    out = []
    for section in tab_sections:
        items = []
        for it in section["items"]:
            detail = [d for d in (it["subtitle"], f"Source: {it['source']}" if it["source"] else None,
                                  f"Link: {it['provenance']}" if it.get("provenance") else None) if d]
            items.append(_item(it["title"], status=it["status"], when=it["updated_at"], detail=detail))
        out.append({"key": _slug(section["title"]), "title": section["title"], "state": section["state"],
                    "note": section["note"], "items": items})
    return out


def _collect(db, user, application_id: int) -> tuple:
    """(application, raw sections) read as `user`, or a 404 when the use is hidden or has no AI profile."""
    from modules.ai_governance import controls, decisions, evaluations, regulation, workspace
    service._require(user, "ai_use.view")
    shown = workspace.get_system(db, user, application_id)
    if shown is None or shown["profile"] is None:
        raise ServiceError(404, "AI use not found.")
    sections = [_use_section(db, shown)]

    def decision():
        decided = decisions.get_decisions(db, user, application_id)
        if decided is None:
            raise RuntimeError("hidden")
        return _decision_section(decided)
    sections.append(_guard("decision", "Decision", decision))

    for tab in ("assessments", "risks_controls", "data_vendors", "evidence"):
        got = workspace.get_tab(db, user, application_id, tab)
        sections += _from_tab(got["sections"] if got else [])

    def proof():
        rows = controls.use_controls(db, user, application_id)
        if rows is None:
            raise RuntimeError("hidden")
        return _controls_section(rows)
    sections.append(_guard("controls", "AI controls and their proof", proof))

    def runs():
        listing = evaluations.list_runs(db, user, application_id)
        if listing is None:
            raise RuntimeError("hidden")
        return _evaluations_section(listing)
    sections.append(_guard("evaluations", "Evaluations", runs))
    sections.append(_guard("regulatory", "Regulatory changes confirmed for this use",
                           lambda: _regulatory_section(regulation.confirmed_for(db, user, application_id))))
    try:
        sections += _gap_sections(db, user, application_id)
    except Exception:
        log.warning("AI review pack: the gaps could not be read", exc_info=True)
        sections.append({"key": "gaps", "title": "Known gaps", "state": "unavailable", "items": []})
    return shown["application"], sections


def build(db, user, application_id: int, options: dict) -> dict:
    app, sections = _collect(db, user, application_id)
    return assemble(sections, options, app["name"], app["business_unit"], service._now())


# ── Recipients ──────────────────────────────────────────────────────────────

def _person(db, user_id) -> "dict | None":
    row = db.execute("SELECT id, org_id, business_unit_id, is_active, is_super_admin, deleted_at, full_name, email "
                     "FROM users WHERE id = %s", (user_id,)).fetchone()
    if row is None:
        return None
    roles = [r["role_key"] for r in db.execute("SELECT role_key FROM user_roles WHERE user_id = %s", (user_id,)).fetchall()]
    return {"id": row["id"], "org_id": row["org_id"], "business_unit_id": row["business_unit_id"], "roles": roles,
            "is_super_admin": bool(row["is_super_admin"]), "active": bool(row["is_active"]) and row["deleted_at"] is None,
            "name": row["full_name"], "email": row["email"]}


def find_recipients(db, user, q) -> list:
    """People of this organization who could be sent a pack, found by name or email. Two characters at least."""
    service._require(user, "ai_pack.manage")
    q = (q or "").strip() if isinstance(q, str) else ""
    if len(q) < 2:
        return []
    roles = sorted(CAPABILITIES["ai_pack.receive"])
    sql = ("SELECT DISTINCT u.id, u.full_name, u.email FROM users u JOIN user_roles ur ON ur.user_id = u.id "
           f"WHERE u.is_active = 1 AND u.deleted_at IS NULL AND u.id != %s AND ur.role_key IN ({','.join(['%s'] * len(roles))}) "
           f"AND ({ci_like('u.full_name')} OR {ci_like('u.email')})")
    params = [user["id"], *roles, like_pattern(q), like_pattern(q)]
    if user.get("org_id") is not None:
        sql, params = sql + " AND u.org_id = %s", [*params, user["org_id"]]
    rows = db.execute(sql + " ORDER BY u.full_name LIMIT %s", [*params, RECIPIENT_SEARCH_MAX]).fetchall()
    return [{"id": r["id"], "name": r["full_name"], "email": r["email"]} for r in rows]


def _recipient_or_422(db, user, recipient_id) -> dict:
    person = _person(db, recipient_id) if recipient_id else None
    ok = (person is not None and person["active"] and person["id"] != user["id"]
          and person["org_id"] == user.get("org_id") and has_capability(person, "ai_pack.receive"))
    if not ok:
        raise ServiceError(422, "Some details need fixing.", errors={
            "recipient_id": "Choose an active person of your organization who can receive review packs."})
    return person


# ── Operations ──────────────────────────────────────────────────────────────

def preview(db, user, application_id: int, raw_options) -> dict:
    """What a pack would hold right now, and whether the options are complete. Nothing is stored."""
    service._require(user, "ai_pack.manage")
    options, errors = clean_options(raw_options)
    manifest = build(db, user, application_id, options)
    recipient = None
    if options["recipient_id"]:
        try:
            person = _recipient_or_422(db, user, options["recipient_id"])
            recipient = {"id": person["id"], "name": person["name"], "email": person["email"]}
        except ServiceError as exc:
            errors.update(exc.extra.get("errors") or {})
    elif "recipient_id" not in errors:
        errors["recipient_id"] = "Choose who the pack is for."
    return {"manifest": manifest, "hash": preview_hash(manifest, options), "options": options,
            "recipient": recipient, "problems": errors}


def _summary(row, names) -> dict:
    now = service._now()
    state = ("revoked" if row["status"] == "revoked" else "expired" if str(row["expires_at"])[:19] <= now[:19] else "open")
    return {"id": row["id"], "name": row["name"], "purpose": row["purpose"], "application_name": row["application_name"],
            "state": state, "recipient": names.get(row["recipient_user_id"]), "issued_by": names.get(row["issued_by"]),
            "issued_at": service._text(row["issued_at"]), "expires_at": service._text(row["expires_at"]),
            "allow_download": bool(row["allow_download"]), "include_people": bool(row["include_people"]),
            "include_notes": bool(row["include_notes"]), "hash": row["manifest_hash"], "generated_at": service._text(row["generated_at"]),
            "revoked_at": service._text(row["revoked_at"]), "revoke_reason": row["revoke_reason"],
            "revoked_by": names.get(row["revoked_by"]), "version": row["version"]}


def issue(db, user, application_id: int, raw_options, expected_hash) -> dict:
    service._require(user, "ai_pack.manage")
    options, errors = clean_options(raw_options, need_recipient=True)
    if errors:
        raise ServiceError(422, "Some details need fixing.", errors=errors)
    manifest = build(db, user, application_id, options)
    current_hash = preview_hash(manifest, options)
    if not isinstance(expected_hash, str) or expected_hash != current_hash:
        raise ServiceError(409, "The record changed after you previewed it. Look at the new preview before issuing.",
                           hash=current_hash)
    recipient = _recipient_or_422(db, user, options["recipient_id"])
    unit = db.execute("SELECT business_unit_id FROM applications WHERE id = %s", (application_id,)).fetchone()
    now = service._now()
    expires = (utcnow() + timedelta(days=options["expires_days"])).strftime("%Y-%m-%d %H:%M:%S")
    pack_id = insert_returning_id(
        db,
        "INSERT INTO ai_review_packs (application_id, application_name, business_unit_id, name, purpose, status, recipient_user_id, "
        "allow_download, include_people, include_notes, expires_at, manifest, manifest_hash, generated_at, issued_by, issued_at, "
        "version, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, 'issued', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)",
        (application_id, manifest["application"]["name"], unit["business_unit_id"] if unit else None, options["name"],
         options["purpose"], recipient["id"], int(options["allow_download"]), int(options["include_people"]),
         int(options["include_notes"]), expires, canonical(manifest), manifest["hash"], manifest["generated_at"], user["id"], now,
         now, now))
    out_events = [events.enqueue(
        db, events.AI_PACK_ISSUED, "ai_governance", "application", application_id,
        {"pack_id": pack_id, "application_id": application_id, "recipient_id": recipient["id"],
         "business_unit_id": unit["business_unit_id"] if unit else None},
        user_id=user["id"], org_id=user.get("org_id"), dedup_key=f"ai_pack.issued:{pack_id}")]
    row = db.execute("SELECT * FROM ai_review_packs WHERE id = %s", (pack_id,)).fetchone()
    names = _names(db, [row["recipient_user_id"], row["issued_by"]])
    return {"pack": _summary(row, names), "events": out_events,
            "audit": [("ai_pack_issued", "application", application_id, f"pack {pack_id} for user {recipient['id']}")]}


def _manager_row(db, user, pack_id):
    """A pack the caller may manage: they hold ai_pack.manage and may open its use. Anything else is a 404."""
    service._require(user, "ai_pack.manage")
    row = db.execute("SELECT * FROM ai_review_packs WHERE id = %s", (pack_id,)).fetchone()
    if row is None or not describe_record(db, APP, row["application_id"], user):
        raise ServiceError(404, NOT_FOUND)
    return row


def revoke(db, user, pack_id: int, reason, expected_version) -> dict:
    row = _manager_row(db, user, pack_id)
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the pack you are revoking.")
    reason = _text(reason, REASON_MAX + 1)
    if not reason or len(reason) < 3:
        raise ServiceError(422, "Say why the pack is being withdrawn.", errors={"reason": "Say why the pack is being withdrawn."})
    if len(reason) > REASON_MAX:
        raise ServiceError(422, f"Keep the reason to {REASON_MAX} characters or fewer.")
    if row["status"] == "revoked":
        raise ServiceError(409, "This pack was already revoked.", current_version=row["version"])
    now = service._now()
    moved = db.execute(
        "UPDATE ai_review_packs SET status = 'revoked', revoked_by = %s, revoked_at = %s, revoke_reason = %s, "
        "version = version + 1, updated_at = %s WHERE id = %s AND status = 'issued' AND version = %s",
        (user["id"], now, reason, now, pack_id, expected_version)).rowcount
    if moved != 1:
        raise ServiceError(409, "This pack was changed by someone else. Reload it and try again.")
    done = db.execute("SELECT * FROM ai_review_packs WHERE id = %s", (pack_id,)).fetchone()
    names = _names(db, [done["recipient_user_id"], done["issued_by"], done["revoked_by"]])
    return {"pack": _summary(done, names), "events": [],
            "audit": [("ai_pack_revoked", "application", row["application_id"], f"pack {pack_id}")]}


def list_for_application(db, user, application_id: int) -> "dict | None":
    """The packs issued for one use, with who opened each and when. None when the use is hidden."""
    service._require(user, "ai_pack.manage")
    if not describe_record(db, APP, application_id, user):
        return None
    rows = db.execute("SELECT * FROM ai_review_packs WHERE application_id = %s ORDER BY id DESC LIMIT 100",
                      (application_id,)).fetchall()
    names = _names(db, [i for r in rows for i in (r["recipient_user_id"], r["issued_by"], r["revoked_by"])])
    out = []
    for row in rows:
        entry = _summary(row, names)
        seen = db.execute("SELECT COUNT(*) AS n, MAX(created_at) AS last FROM ai_review_pack_events WHERE pack_id = %s AND action != 'denied'",
                          (row["id"],)).fetchone()
        entry.update(opened=seen["n"], last_opened_at=service._text(seen["last"]))
        out.append(entry)
    return {"packs": out}


def access_history(db, user, pack_id: int) -> dict:
    row = _manager_row(db, user, pack_id)
    events_rows = db.execute("SELECT user_id, action, reason, created_at FROM ai_review_pack_events WHERE pack_id = %s "
                             "ORDER BY id DESC LIMIT 200", (pack_id,)).fetchall()
    names = _names(db, [r["user_id"] for r in events_rows])
    return {"pack": _summary(row, _names(db, [row["recipient_user_id"], row["issued_by"], row["revoked_by"]])),
            "events": [{"who": names.get(r["user_id"]), "action": r["action"], "reason": r["reason"],
                        "at": service._text(r["created_at"])} for r in events_rows]}


def changes_since(db, user, pack_id: int) -> dict:
    """Which sections of the pack differ from the record as the caller sees it now. Advisory: the caller's scope may differ
    from the author's."""
    row = _manager_row(db, user, pack_id)
    old = verifies(row["manifest"], row["manifest_hash"])
    if old is None:
        raise ServiceError(409, "This pack no longer matches its recorded hash.")
    options = {"include_people": bool(row["include_people"]), "include_notes": bool(row["include_notes"])}
    new = build(db, user, row["application_id"], options)
    return {"changed": changed_sections(old, new), "generated_at": service._text(row["generated_at"]),
            "same": content_hash(old) == content_hash(new)}


def list_mine(db, user) -> dict:
    """Packs addressed to the caller that they can open now. A pack that is revoked, expired, or whose issuer has lost the
    right to share it is not listed, and nothing says it exists."""
    service._require(user, "ai_pack.receive")
    now = service._now()
    rows = db.execute("SELECT * FROM ai_review_packs WHERE recipient_user_id = %s AND status = 'issued' AND expires_at > %s "
                      "ORDER BY id DESC LIMIT 100", (user["id"], now)).fetchall()
    cache, shown = {}, []
    for row in rows:
        key = (row["issued_by"], row["application_id"])
        if key not in cache:
            cache[key] = _issuer_problem(db, row)
        if cache[key] is None and verifies(row["manifest"], row["manifest_hash"]) is not None:
            shown.append(row)
    names = _names(db, [r["issued_by"] for r in shown])
    return {"packs": [{"id": r["id"], "name": r["name"], "purpose": r["purpose"], "application_name": r["application_name"],
                       "issued_by": names.get(r["issued_by"]), "issued_at": service._text(r["issued_at"]),
                       "expires_at": service._text(r["expires_at"]), "allow_download": bool(r["allow_download"])} for r in shown]}


def _issuer_problem(db, row) -> "str | None":
    """Why this pack can no longer be shown on the issuer's authority, or None. The pack is withdrawn from view the moment
    the person who issued it may no longer open the use or share packs."""
    issuer = _person(db, row["issued_by"])
    if issuer is None or not issuer["active"]:
        return "issuer_gone"
    if not has_capability(issuer, "ai_pack.manage"):
        return "issuer_lost_right"
    if not describe_record(db, APP, row["application_id"], issuer):
        return "issuer_lost_scope"
    return None


def _log(db, pack_id, user_id, action, reason=None) -> None:
    db.execute("INSERT INTO ai_review_pack_events (pack_id, user_id, action, reason, created_at) VALUES (%s, %s, %s, %s, %s)",
               (pack_id, user_id, action, reason, service._now()))


def open_pack(db, user, pack_id: int, action: str = "viewed") -> dict:
    """Open a pack to read ("viewed") or to download ("downloaded").

    Returns {"pack": {...}, "manifest": {...}} or {"refused": code, "http": 404 or 403}. A refusal is recorded and the
    caller commits it. The recipient is refused, with the same 404 as for a pack that does not exist, when the pack is not
    issued or has expired, when the caller is not the recipient, when the pack no longer hashes to its recorded value, and
    when the issuer has lost the right to share it. A manager of the use may always read what was issued for it."""
    if action not in ("viewed", "downloaded"):
        raise ServiceError(400, "Unknown action.")
    row = db.execute("SELECT * FROM ai_review_packs WHERE id = %s", (pack_id,)).fetchone()
    if row is None:
        return {"refused": "not_found", "http": 404}
    manager = has_capability(user, "ai_pack.manage") and bool(describe_record(db, APP, row["application_id"], user))
    if not manager:
        reason = open_refusal(row, user["id"], service._now())
        if reason is None and not has_capability(user, "ai_pack.receive"):
            reason = "no_right"
        reason = reason or _issuer_problem(db, row)
        if reason:
            _log(db, pack_id, user["id"], "denied", reason)
            return {"refused": reason, "http": 404}
    manifest = verifies(row["manifest"], row["manifest_hash"])
    if manifest is None:
        log.error("AI review pack %s no longer matches its recorded hash", pack_id)
        _log(db, pack_id, user["id"], "denied", "integrity")
        return {"refused": "integrity", "http": 404}
    if action == "downloaded" and not manager and not row["allow_download"]:
        _log(db, pack_id, user["id"], "denied", "download_not_allowed")
        return {"refused": "download_not_allowed", "http": 403}
    _log(db, pack_id, user["id"], action)
    names = _names(db, [row["recipient_user_id"], row["issued_by"], row["revoked_by"]])
    summary = _summary(row, names)
    if not manager:  # a recipient is told what they need to read it, not how it was handled
        summary = {k: summary[k] for k in ("id", "name", "purpose", "application_name", "issued_by", "issued_at", "expires_at",
                                           "allow_download", "hash", "generated_at")}
    return {"pack": summary, "manifest": manifest, "manager": manager}


def export_document(opened: dict) -> dict:
    """The downloadable form of an opened pack: the account, who it is for, and how to check it is unchanged."""
    return {"pack": opened["pack"], "manifest": opened["manifest"],
            "check": "hash is the sha256 of the manifest as JSON with sorted keys and no spaces, without generated_at and hash."}
