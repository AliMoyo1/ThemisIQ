"""
AI governance G3: quality checks on one AI use (rule set v1).

Each check is deterministic, names its rule and version, says what it read, and points to the form that fixes it. A
check never changes what it looked at: it does not mark a control compliant or a use approved. A reviewer may dismiss a
finding with a reason; the dismissal is audited, applies only while what the finding was about has not changed (its
fingerprint) and has not expired, and never alters the underlying record.

A source that could not be read is reported as "could not be checked", never as a clean result.
"""
import hashlib
import json
import logging
from datetime import datetime

from core.timeutils import utcnow
from modules.ai_governance import controls, guidance, service
from modules.ai_governance.service import APP, ServiceError
from modules.governance.entity_scope import describe_record

log = logging.getLogger("oneforall.ai_governance")

RULE_VERSION = "v1"
SEVERITIES = ("error", "warning")
MAX_REASON = 500


def _fingerprint(*facts) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _finding(rule, severity, source_type, source_id, title, why, fix_label, fix_url, facts) -> dict:
    return {"key": f"{rule}:{source_type}:{source_id}", "rule": rule, "rule_version": RULE_VERSION, "severity": severity,
            "title": title, "why": why, "source": {"type": source_type, "id": source_id},
            "fix": {"label": fix_label, "url": fix_url}, "fingerprint": _fingerprint(rule, source_type, source_id, facts)}


def evaluate(db, user, application_id: int) -> "dict | None":
    """{"findings": [...], "unchecked": [...]} for one use, or None when the viewer may not open it."""
    service._require(user, "ai_use.view")
    if not describe_record(db, APP, application_id, user):
        return None
    findings, unchecked = [], []
    base = f"/ai-governance/systems/{application_id}"
    today = utcnow().strftime("%Y-%m-%d")

    app = db.execute("SELECT owner_user_id, is_active FROM applications WHERE id = %s", (application_id,)).fetchone()
    if app and app["is_active"] and app["owner_user_id"] is None:
        findings.append(_finding("owner_missing", "warning", "application", application_id, "This use has no owner",
                                 "Nobody is named as answerable for this use.", "Name an owner", base + "#overview", {"owner": None}))

    profile = service.get_profile(db, user, application_id)
    if profile and profile["next_review_at"] and profile["next_review_at"][:10] <= today and app and app["is_active"]:
        findings.append(_finding("review_overdue", "warning", "application", application_id, "The review is overdue",
                                 f"It was due on {profile['next_review_at'][:10]}.", "Review the profile", base + "#overview",
                                 {"due": profile["next_review_at"][:10], "reviewed": profile["last_reviewed_at"]}))

    try:
        plan = guidance.get_checklist(db, user, application_id)
        for step in (plan or {}).get("steps", []):
            if step["state"] == "unavailable":
                unchecked.append(step["title"])
                continue
            if step["effective"] == "required" and step["state"] == "not_started":
                findings.append(_finding("step_not_started", "error", "step", step["key"], f"{step['title']} is required and not started",
                                         step["reasons"][0], step["action"]["label"], step["action"]["url"],
                                         {"applicability": step["applicability"], "state": step["state"]}))
            elif step["effective"] in ("required", "recommended") and step["state"] == "complete" and step["stale"]:
                findings.append(_finding("step_stale", "warning", "step", step["key"], f"{step['title']} was done before the use changed",
                                         "The use's facts changed after this was last updated.", "Review it", step["records"][0]["url"],
                                         {"records": [r["updated_at"] for r in step["records"]]}))
            if step["override"] and step["override"]["out_of_date"]:
                findings.append(_finding("judgement_out_of_date", "warning", "step", step["key"],
                                         f"\"Not applicable\" for {step['title']} was judged against older facts",
                                         "The use changed after a reviewer ruled this step out.", "Look at it again", base + "#assessments",
                                         {"set_at": step["override"]["set_at"]}))
    except Exception:
        log.warning("AI governance quality: the checklist could not be read", exc_info=True)
        unchecked.append("Assessments")

    try:
        for item in controls.use_controls(db, user, application_id) or []:
            if not item["applicable"] or not item["implemented"]:
                continue
            name = f"{item['control']['ref'] or ''} {item['control']['title']}".strip()
            if not item["mapped"]:
                findings.append(_finding("control_unmapped", "warning", "ai_control", item["control"]["id"],
                                         f"{name} is implemented but not mapped to a canonical control",
                                         "Without a mapping the proof held for the control cannot be shown here.",
                                         "Map the control", base + "#risks_controls", {"mapped": False}))
            elif item["proof"]["current"] == 0:
                what = "all of its proof has expired" if item["proof"]["expired"] else "no proof is attached"
                findings.append(_finding("proof_missing" if not item["proof"]["expired"] else "proof_stale", "warning",
                                         "ai_control", item["control"]["id"], f"{name} is implemented but {what}",
                                         "An implemented control needs current proof; a file alone is not an accepted test.",
                                         "Attach proof in the Vault", "/evidence/", {"expired": item["proof"]["expired"]}))
    except Exception:
        log.warning("AI governance quality: the controls could not be read", exc_info=True)
        unchecked.append("AI controls")

    try:
        from modules.ai_governance import evaluations
        latest = (evaluations.list_runs(db, user, application_id) or {}).get("latest")
        if latest and latest["state"] in ("failed", "interrupted") and not latest["review_outcome"]:
            findings.append(_finding("evaluation_failed", "error", "evaluation", latest["id"],
                                     f"The latest evaluation, {latest['name']}, " + ("failed" if latest["state"] == "failed" else "did not finish"),
                                     "A run that failed or did not finish is not a pass, and nobody has reviewed it.",
                                     "Review the run", base + "#monitoring", {"state": latest["state"], "run": latest["id"]}))
        elif latest and latest["stale"]:
            findings.append(_finding("evaluation_stale", "warning", "evaluation", latest["id"],
                                     f"The latest evaluation, {latest['name']}, is out of date",
                                     "The use changed after it was run, or it is older than 180 days.",
                                     "Record a new evaluation", base + "#monitoring", {"run": latest["id"], "stale": True}))
    except Exception:
        log.warning("AI governance quality: evaluations could not be read", exc_info=True)
        unchecked.append("Evaluations")

    dismissed = _dismissals(db, application_id, today)
    for f in findings:
        d = dismissed.get(f["key"])
        f["dismissed"] = d if d and d["fingerprint"] == f["fingerprint"] else None
    order = {"error": 0, "warning": 1}
    findings.sort(key=lambda f: (order[f["severity"]], f["rule"], f["key"]))
    return {"rule_version": RULE_VERSION, "findings": findings, "unchecked": unchecked,
            "open": sum(1 for f in findings if not f["dismissed"])}


def _dismissals(db, application_id, today) -> dict:
    rows = db.execute(
        "SELECT d.finding_key, d.fingerprint, d.reason, d.dismissed_at, d.expires_at, u.full_name FROM ai_use_finding_dismissals d "
        "LEFT JOIN users u ON u.id = d.dismissed_by WHERE d.application_id = %s", (application_id,)).fetchall()
    out = {}
    for r in rows:
        if r["expires_at"] and str(r["expires_at"])[:10] < today:
            continue
        out[r["finding_key"]] = {"fingerprint": r["fingerprint"], "reason": r["reason"], "by": r["full_name"],
                                 "at": str(r["dismissed_at"] or "")[:10], "expires_at": str(r["expires_at"] or "")[:10] or None}
    return out


def dismiss(db, user, application_id: int, finding_key: str, reason, expires_at=None) -> dict:
    service._require(user, "ai_use.review")
    result = evaluate(db, user, application_id)
    if result is None:
        raise ServiceError(404, "Application not found.")
    found = next((f for f in result["findings"] if f["key"] == finding_key), None)
    if found is None:
        raise ServiceError(404, "That finding is not open for this use.")
    reason = (reason or "").strip() if isinstance(reason, str) or reason is None else ""
    if len(reason) < 3 or len(reason) > MAX_REASON:
        raise ServiceError(422, f"Say why, in 3 to {MAX_REASON} characters.")
    if expires_at not in (None, ""):
        try:
            when = datetime.strptime(str(expires_at)[:10], "%Y-%m-%d").date()
        except ValueError:
            raise ServiceError(422, "The expiry must be a date.")
        if when <= utcnow().date():
            raise ServiceError(422, "The expiry must be a later date.")
        expires_at = when.isoformat()
    else:
        expires_at = None
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO ai_use_finding_dismissals (application_id, finding_key, fingerprint, reason, dismissed_by, dismissed_at, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (application_id, finding_key) DO UPDATE SET fingerprint = excluded.fingerprint, "
        "reason = excluded.reason, dismissed_by = excluded.dismissed_by, dismissed_at = excluded.dismissed_at, expires_at = excluded.expires_at",
        (application_id, finding_key, found["fingerprint"], reason, user["id"], now, expires_at))
    return {"events": [], "audit": [("ai_finding_dismissed", "application", application_id, f"{finding_key}: {reason[:120]}")]}


def reopen(db, user, application_id: int, finding_key: str) -> dict:
    service._require(user, "ai_use.review")
    if not describe_record(db, APP, application_id, user):
        raise ServiceError(404, "Application not found.")
    done = db.execute("DELETE FROM ai_use_finding_dismissals WHERE application_id = %s AND finding_key = %s",
                      (application_id, finding_key)).rowcount
    if done != 1:
        raise ServiceError(404, "That finding was not dismissed.")
    return {"events": [], "audit": [("ai_finding_reopened", "application", application_id, finding_key)]}
