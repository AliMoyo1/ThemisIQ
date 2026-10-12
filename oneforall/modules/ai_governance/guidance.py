"""
AI governance G3: the checklist of one AI use read against the records that exist, and a reviewer's "not applicable".

`checklist.evaluate` says what each step needs and why; here each step is given where it stands from the owning module's
own records (read through the viewer's scope, so a record they cannot open is never named or counted), what to open to
do it, and any judgement a reviewer recorded. Like the rest of the service layer, nothing here commits.
"""
import json
import logging
from urllib.parse import quote

from core.rbac import has_capability
from core.timeutils import utcnow
from modules.ai_governance import checklist, rules, service
from modules.ai_governance.service import APP, ServiceError
from modules.governance import relationships
from modules.governance.entity_scope import describe_record, entity_scope_sql, may_view_kind

log = logging.getLogger("oneforall.ai_governance")

_AIIA, _DPIA, _ROPA, _DOC, _AIMS = ("sentinel", "aiia"), ("sentinel", "dpia"), ("sentinel", "ropa"), ("aria", "document"), ("orm", "aims")
_MAX_REASON = 500


def _ids(values) -> list:
    return sorted({int(v) for v in values if v is not None})


def _marks(values) -> str:
    return ",".join(["%s"] * len(values))


def _linked_ids(db, user, application_id, kind) -> list:
    return [l["entity_id"] for l in relationships.list_links(db, user, APP, application_id)
            if (l["module"], l["entity_type"]) == kind]


def _no_access() -> dict:
    return {"state": "no_access", "stale": False, "records": []}


def _unavailable() -> dict:
    return {"state": "unavailable", "stale": False, "records": []}


# ── One adapter per step: the records of the owning module this viewer may open ──

def _aiia(db, user, application_id, changed):
    if not may_view_kind(user, _AIIA):
        return _no_access()
    scope, params = entity_scope_sql(_AIIA, user, "a")
    rows = db.execute(
        "SELECT a.id, a.ref_number, a.title, a.status, a.updated_at FROM sentinel_aiia a "
        f"WHERE a.application_id = %s AND {scope} ORDER BY a.updated_at DESC LIMIT 20", [application_id, *params]).fetchall()
    return checklist.progress([{"title": f"{r['ref_number']}: {r['title']}", "url": f"/ai-governance/assessments/{r['id']}",
                                "status": r["status"], "updated_at": str(r["updated_at"] or ""),
                                "ref": ["sentinel", "aiia", r["id"]]} for r in rows], changed)


def _by_ids(db, user, kind, table, columns, ids, url, title):
    scope, params = entity_scope_sql(kind, user, "t")
    rows = db.execute(f"SELECT {columns} FROM {table} t WHERE t.id IN ({_marks(ids)}) AND {scope} ORDER BY t.id",
                      [*ids, *params]).fetchall() if ids else []
    return [{"title": title(r), "url": url(r), "status": r["status"], "updated_at": str(r["updated_at"] or ""),
             "ref": [kind[0], kind[1], r["id"]]} for r in rows]


def _dpia(db, user, application_id, changed):
    if not may_view_kind(user, _DPIA):
        return _no_access()
    from_aiia = db.execute("SELECT dpia_id FROM sentinel_aiia WHERE application_id = %s AND dpia_id IS NOT NULL", (application_id,)).fetchall()
    ids = _ids([*_linked_ids(db, user, application_id, _DPIA), *[r[0] for r in from_aiia]])
    return checklist.progress(_by_ids(
        db, user, _DPIA, "sentinel_dpias", "t.id, t.ref_number, t.title, t.status, t.updated_at", ids,
        lambda r: f"/sentinel/?open=dpia:{r['id']}", lambda r: f"{r['ref_number']}: {r['title']}"), changed)


def _ropa(db, user, application_id, changed):
    if not may_view_kind(user, _ROPA):
        return _no_access()
    from_aiia = db.execute("SELECT ropa_id FROM sentinel_aiia WHERE application_id = %s AND ropa_id IS NOT NULL", (application_id,)).fetchall()
    ids = _ids([*_linked_ids(db, user, application_id, _ROPA), *[r[0] for r in from_aiia]])
    return checklist.progress(_by_ids(
        db, user, _ROPA, "sentinel_ropa", "t.id, t.ref_number, t.processing_name AS name, t.status, t.updated_at", ids,
        lambda r: f"/sentinel/?open=ropa:{r['id']}", lambda r: f"{r['ref_number']}: {r['name']}"), changed)


def _policy(db, user, application_id, changed):
    if not may_view_kind(user, _DOC):
        return _no_access()
    ids = _ids(_linked_ids(db, user, application_id, _DOC))
    scope, params = entity_scope_sql(_DOC, user, "t")
    rows = db.execute(
        f"SELECT t.id, t.doc_id, t.title, t.status, t.updated_at FROM aria_documents t WHERE t.id IN ({_marks(ids)}) AND {scope} ORDER BY t.id",
        [*ids, *params]).fetchall() if ids else []
    return checklist.progress([{"title": r["title"], "url": f"/aria/documents?open={quote(str(r['doc_id'] or ''), safe='')}",
                                "status": r["status"], "updated_at": str(r["updated_at"] or ""),
                                "ref": ["aria", "document", r["id"]]} for r in rows], changed)


def _aims(db, user, application_id, changed):
    if not may_view_kind(user, _AIMS):
        return _no_access()
    scope, params = entity_scope_sql(_AIMS, user, "t")
    rows = db.execute(
        f"SELECT t.id, t.ref, t.title, t.status, t.updated_at FROM aims_assessments t WHERE t.application_id = %s AND {scope} "
        "ORDER BY t.updated_at DESC LIMIT 20", [application_id, *params]).fetchall()
    return checklist.progress([{"title": f"{r['ref']}: {r['title']}", "url": "/orm/aims", "status": r["status"],
                                "updated_at": str(r["updated_at"] or ""), "ref": ["orm", "aims", r["id"]]} for r in rows], changed)


def _vendor(db, user, application_id, changed):
    app = db.execute("SELECT a.vendor_id, cv.name FROM applications a LEFT JOIN canonical_vendors cv ON cv.id = a.vendor_id "
                     "WHERE a.id = %s", (application_id,)).fetchone()
    if not app or app["vendor_id"] is None:
        return {"state": "not_started", "stale": False, "records": []}
    records = [{"title": app["name"], "url": "/vendors", "status": "registered", "updated_at": ""}]
    if may_view_kind(user, ("sentinel", "vendor")):
        row = db.execute("SELECT dpa_status, updated_at FROM sentinel_vendors WHERE canonical_id = %s LIMIT 1", (app["vendor_id"],)).fetchone()
        if row:
            records.append({"title": f"{app['name']}: data protection agreement", "url": "/sentinel/vendors",
                            "status": row["dpa_status"] or "pending", "updated_at": str(row["updated_at"] or "")})
    if may_view_kind(user, ("grid", "vendor")):
        row = db.execute(
            "SELECT a.score, a.assessment_date FROM grid_vendor_assessments a JOIN grid_vendors v ON v.id = a.vendor_id "
            "WHERE v.canonical_id = %s ORDER BY a.assessment_date DESC LIMIT 1", (app["vendor_id"],)).fetchone()
        if row:
            records.append({"title": f"{app['name']}: audit assessment ({row['score']}%)", "url": "/grid/vendors",
                            "status": "completed", "updated_at": str(row["assessment_date"] or "")})
    done = [r for r in records if r["status"] in ("signed", "completed")]
    # A provider review is done when the agreement is signed and an assessment exists; either alone is in progress.
    state = "complete" if len({r["status"] for r in done}) == 2 else "in_progress"
    return {"state": state, "stale": False, "records": records}


_ADAPTERS = {"aiia": _aiia, "dpia": _dpia, "ropa": _ropa, "vendor": _vendor, "aims": _aims, "policy": _policy}

_OPEN = {  # what opens the work when nothing has been started: the owning module's own form
    "aiia": ("Start the assessment", "/ai-governance/assessments/new?application_id={id}"),
    "dpia": ("Open Privacy", "/sentinel/"),
    "ropa": ("Open Privacy", "/sentinel/"),
    "vendor": ("Open the vendor directory", "/vendors"),
    "aims": ("Open the AI management assessments", "/orm/aims"),
    "policy": ("Open policies", "/aria/documents"),
}


# ── Overrides ───────────────────────────────────────────────────────────────

def _overrides(db, application_id) -> dict:
    rows = db.execute(
        "SELECT o.step_key, o.reason, o.rule_version, o.fingerprint, o.set_at, u.full_name FROM ai_use_step_overrides o "
        "LEFT JOIN users u ON u.id = o.set_by WHERE o.application_id = %s", (application_id,)).fetchall()
    return {r["step_key"]: {"reason": r["reason"], "rule_version": r["rule_version"], "fingerprint": r["fingerprint"],
                            "set_at": str(r["set_at"] or ""), "set_by": r["full_name"]} for r in rows}


def get_checklist(db, user, application_id: int) -> "dict | None":
    """The steps of one AI use with their applicability, reasons, progress, any recorded judgement, and what opens the work.
    None when the viewer may not open the application."""
    service._require(user, "ai_use.view")
    if not describe_record(db, APP, application_id, user):
        return None
    profile = service.get_profile(db, user, application_id)
    if profile is None:
        return {"rule_version": checklist.RULE_VERSION, "profile": False, "steps": [], "unresolved": []}
    changed = profile.get("material_changed_at")
    overrides = _overrides(db, application_id)
    steps = []
    for step in checklist.evaluate(profile):
        try:
            progressed = _ADAPTERS[step["key"]](db, user, application_id, changed)
        except Exception:
            log.warning("AI governance checklist: %s could not be read", step["key"], exc_info=True)
            progressed = _unavailable()
        override = overrides.get(step["key"])
        judged = None
        if override:
            judged = {**override, "out_of_date": override["fingerprint"] != profile["fingerprint"]}
        label, url = _OPEN[step["key"]]
        step.update(
            state=progressed["state"], stale=progressed["stale"], records=progressed["records"], override=judged,
            action={"label": label, "url": url.format(id=application_id) + (("&" if "?" in url else "?") + f"aig_return={application_id}")},
            effective=("not_applicable" if judged and not judged["out_of_date"] and step["applicability"] == "required" else step["applicability"]))
        steps.append(step)
    unresolved = [s["key"] for s in steps if s["effective"] == "required" and s["state"] != "complete"]
    return {"rule_version": checklist.RULE_VERSION, "profile": True, "steps": steps, "unresolved": unresolved,
            "snapshot": checklist.snapshot(steps)}


def set_step_not_applicable(db, user, application_id: int, key: str, reason) -> dict:
    """A reviewer rules a step out, with a reason. Stored with the rule version and the fingerprint of the facts it was
    judged against, so it shows as out of date when the use changes."""
    service._require(user, "ai_use.review")
    if key not in checklist.STEPS:
        raise ServiceError(404, "Unknown step.")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "Application not found.")
    profile = service.get_profile(db, user, application_id)
    if profile is None:
        raise ServiceError(409, "Add the AI profile first.")
    reason = (reason or "").strip() if isinstance(reason, str) or reason is None else ""
    if len(reason) < 3:
        raise ServiceError(422, "Say why this step does not apply.")
    if len(reason) > _MAX_REASON:
        raise ServiceError(422, f"The reason is too long (at most {_MAX_REASON} characters).")
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO ai_use_step_overrides (application_id, step_key, reason, rule_version, fingerprint, set_by, set_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (application_id, step_key) DO UPDATE SET reason = excluded.reason, "
        "rule_version = excluded.rule_version, fingerprint = excluded.fingerprint, set_by = excluded.set_by, set_at = excluded.set_at",
        (application_id, key, reason, checklist.RULE_VERSION, profile["fingerprint"], user["id"], now))
    return {"key": key, "events": [], "audit": [("ai_step_not_applicable", "application", application_id, f"{key}: {reason[:120]}")]}


def clear_step_judgement(db, user, application_id: int, key: str) -> dict:
    service._require(user, "ai_use.review")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "Application not found.")
    done = db.execute("DELETE FROM ai_use_step_overrides WHERE application_id = %s AND step_key = %s", (application_id, key)).rowcount
    if done != 1:
        raise ServiceError(404, "Nothing was recorded for this step.")
    return {"key": key, "events": [], "audit": [("ai_step_reset", "application", application_id, key)]}


# ── What an assessment form can start from ──────────────────────────────────

_AIIA_DEPLOYMENT = {"vendor_service": "cloud", "embedded_vendor": "cloud"}
_AIIA_AUTONOMY = {"assist_only": "decision_support", "recommend": "decision_support",
                  "decide_with_review": "human_in_loop", "decide_automatically": "automated"}


def aiia_prefill(db, user, application_id: int) -> "dict | None":
    """The answers an AI impact assessment for this use can start from, with where they came from. The form shows the
    source and the time, and what it was prefilled from is never changed afterwards by a later profile edit."""
    service._require(user, "ai_use.view")
    shown = describe_record(db, APP, application_id, user)
    profile = service.get_profile(db, user, application_id) if shown else None
    if profile is None:
        return None
    categories = set(profile["data_categories"])
    chips = []
    if categories & {"personal", "sensitive_personal", "health"}:
        chips.append("Personal")
    if "financial" in categories:
        chips.append("Transactional")
    if categories & {"internal", "confidential", "public"}:
        chips.append("Operational")
    vendor_provided = profile["deployment"] in ("vendor_service", "embedded_vendor")
    people = [rules.AFFECTED_PEOPLE.get(p, p) for p in profile["affected_people"] if p != "none"]
    return {
        "fields": {
            "title": f"{shown['title']}: AI impact assessment", "ai_system_name": shown["title"], "application_id": application_id,
            "system_description": profile["purpose"] or "", "deployment_env": _AIIA_DEPLOYMENT.get(profile["deployment"], ""),
            "autonomy_level": _AIIA_AUTONOMY.get(profile["autonomy"], "decision_support"),
            "third_party": 1 if vendor_provided else 0, "third_party_details": profile["provider_note"] or "",
            "data_categories": chips, "sensitive_data": 1 if categories & {"sensitive_personal", "health"} else 0,
            "stakeholders_direct": ", ".join(people), "influences_customers": 1 if "customers" in profile["affected_people"] else 0,
        },
        "source": {"kind": "AI profile", "name": shown["title"], "updated_at": profile["updated_at"]},
    }
