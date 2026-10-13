"""
AI governance G5: records of evaluation runs (plans/ai-governance/08-g5-build-plan.md).

A reviewer records that a use was evaluated: against which test set and version, by which rubric, the version of what was
evaluated, who or what did the evaluating, the thresholds and the score of each dimension, and an optional Vault item as
the artifact. ThemisIQ does not run the evaluation and does not store prompts or answers. What it keeps honest is the
reading of a run:

* a run passes only when it completed, at least one dimension has a threshold, and every dimension that has one met it;
* a run that failed, was cancelled or errored is never shown as passed, and a completed run with no thresholds claims
  nothing at all;
* a run older than the use's last material change, or than half a year, is stale;
* a failed run proposes work and reopens a decision; it does not mark a control failed or an approval withdrawn.

Like the rest of the service layer, every function takes the caller's connection and user, checks capability and unit
scope itself, never commits, and returns audit entries and events. A hidden system answers like a missing one.
"""
import json
import re
from datetime import datetime

from core import events
from core.rbac import has_capability
from core.timeutils import utcnow
from database import insert_returning_id
from modules.ai_governance import service
from modules.ai_governance.service import APP, ServiceError
from modules.governance.entity_scope import describe_record

STATUSES = ("completed", "failed", "cancelled", "error")
EVALUATORS = {"deterministic": "Fixed checks", "human": "Reviewed by a person", "model_graded": "Graded by a model"}
RETENTIONS = ("none", "summary", "full")
REVIEW_OUTCOMES = ("accepted", "finding")
STALE_DAYS = 180
MAX_DIMENSIONS = 30
MAX_RUNS_SHOWN = 100
_NAME = re.compile(r"[A-Za-z0-9 _./:()+-]{1,60}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
STATE_LABELS = {"passed": "Passed", "failed": "Failed", "interrupted": "Did not finish", "ungated": "Recorded, no pass claimed"}


# ── Pure rules ──────────────────────────────────────────────────────────────

def outcome_of(status, scores, thresholds) -> dict:
    """{"state": passed|failed|interrupted|ungated, "failed": [dimensions below their threshold]}."""
    if status in ("cancelled", "error"):
        return {"state": "interrupted", "failed": []}
    below = sorted(d for d, floor in (thresholds or {}).items() if d in (scores or {}) and scores[d] < floor)
    if status == "failed":
        return {"state": "failed", "failed": below}
    gating = [d for d in (thresholds or {}) if d in (scores or {})]
    if not gating:
        return {"state": "ungated", "failed": []}
    return {"state": "failed" if below else "passed", "failed": below}


def is_stale(finished_at, material_changed_at, today: str) -> bool:
    """Older than the last material change of the use, or than STALE_DAYS."""
    day = str(finished_at or "")[:10]
    if not day:
        return True
    if material_changed_at and day < str(material_changed_at)[:10]:
        return True
    try:
        age = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(day, "%Y-%m-%d")).days
    except ValueError:
        return True
    return age > STALE_DAYS


def compare(old: dict, new: dict) -> dict:
    """What changed between two runs: per dimension the earlier and later score and the difference, the dimensions only one
    of them has, and whether the test set or rubric differ (so a change in score is not read as a change in the use)."""
    old_scores, new_scores = old.get("scores") or {}, new.get("scores") or {}
    rows = []
    for dim in sorted(set(old_scores) | set(new_scores)):
        before, after = old_scores.get(dim), new_scores.get(dim)
        rows.append({"dimension": dim, "before": before, "after": after,
                     "change": None if before is None or after is None else round(after - before, 4)})
    return {"dimensions": rows,
            "same_test_set": (old.get("test_set_name"), old.get("test_set_version")) == (new.get("test_set_name"), new.get("test_set_version")),
            "same_rubric": old.get("rubric_version") == new.get("rubric_version"),
            "subject_changed": old.get("subject_version") != new.get("subject_version"),
            "state": {"before": old.get("state"), "after": new.get("state")}}


# ── Cleaning ────────────────────────────────────────────────────────────────

def _text(raw, field, label, *, required=False, limit=200, errors=None):
    value = raw.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors[field] = f"Give the {label}."
        return None
    if not isinstance(value, str):
        errors[field] = f"The {label} must be text."
        return None
    value = _CONTROL.sub("", value).strip()
    if len(value) > limit:
        errors[field] = f"The {label} is too long (at most {limit} characters)."
        return None
    return value


def _stamp(raw, field, label, errors):
    value = raw.get(field)
    if value in (None, ""):
        return None
    try:
        when = datetime.strptime(str(value).replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S") if len(str(value)) > 10 \
            else datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        errors[field] = f"The {label} must be a date or a date and time."
        return None
    if when.date() > utcnow().date():
        errors[field] = f"The {label} cannot be in the future."
        return None
    return when.strftime("%Y-%m-%d %H:%M:%S")


def _numbers(raw, field, label, errors, *, low=0.0, high=100.0):
    value = raw.get(field)
    if value in (None, ""):
        return {}
    if not isinstance(value, dict) or len(value) > MAX_DIMENSIONS:
        errors[field] = f"Send the {label} as a list of at most {MAX_DIMENSIONS} named numbers."
        return {}
    out = {}
    for name, number in value.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name.strip()):
            errors[field] = f"A name in the {label} is not a plain dimension name (letters, digits and spaces, up to 60)."
            return {}
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not low <= number <= high:
            errors[field] = f"Every number in the {label} must be from {low:g} to {high:g}."
            return {}
        out[name.strip()] = float(number)
    return out


def clean(raw) -> dict:
    """The fields of a run to store, or a ServiceError(422) with a sentence for each field that is wrong."""
    if not isinstance(raw, dict):
        raise ServiceError(422, "Send the run as an object.", errors={"_": "Send the run as an object."})
    errors: dict = {}
    out = {
        "name": _text(raw, "name", "name of the run", required=True, errors=errors),
        "test_set_name": _text(raw, "test_set_name", "test set name", required=True, errors=errors),
        "test_set_version": _text(raw, "test_set_version", "test set version", required=True, limit=50, errors=errors),
        "rubric_version": _text(raw, "rubric_version", "rubric version", required=True, limit=50, errors=errors),
        "subject_version": _text(raw, "subject_version", "version of what was evaluated", required=True, limit=100, errors=errors),
        "notes": _text(raw, "notes", "notes", limit=2000, errors=errors),
    }
    out["evaluator"] = raw.get("evaluator")
    if out["evaluator"] not in EVALUATORS:
        errors["evaluator"] = "Say who or what evaluated it: fixed checks, a person, or a model."
    out["status"] = raw.get("status")
    if out["status"] not in STATUSES:
        errors["status"] = "Say how the run ended: completed, failed, cancelled or error."
    out["retention"] = raw.get("retention") or "none"
    if out["retention"] not in RETENTIONS:
        errors["retention"] = "Choose none, summary or full for what was kept of the cases."
    out["started_at"] = _stamp(raw, "started_at", "start time", errors)
    out["finished_at"] = _stamp(raw, "finished_at", "finish time", errors)
    if out["started_at"] and out["finished_at"] and out["finished_at"] < out["started_at"]:
        errors["finished_at"] = "The run cannot finish before it started."
    out["scores"] = _numbers(raw, "scores", "scores", errors)
    out["thresholds"] = _numbers(raw, "thresholds", "thresholds", errors)
    unknown = sorted(set(out["thresholds"]) - set(out["scores"]))
    if unknown and "thresholds" not in errors:
        errors["thresholds"] = "A threshold names a dimension that has no score: " + ", ".join(unknown[:3]) + "."
    for field, label in (("cases_total", "number of cases"), ("cases_failed", "number of failed cases")):
        value = raw.get(field)
        if value in (None, ""):
            out[field] = None
        elif isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000_000:
            errors[field] = f"The {label} must be a whole number."
            out[field] = None
        else:
            out[field] = value
    if out["cases_total"] is not None and out["cases_failed"] is not None and out["cases_failed"] > out["cases_total"]:
        errors["cases_failed"] = "More cases failed than were run."
    artifact = raw.get("artifact_id")
    out["artifact_id"] = None
    if artifact not in (None, ""):
        if isinstance(artifact, bool) or not isinstance(artifact, int):
            errors["artifact_id"] = "Choose the Vault item from the list."
        else:
            out["artifact_id"] = artifact
    if out["status"] == "completed":
        if not out["finished_at"]:
            errors.setdefault("finished_at", "Say when the run finished.")
        if not out["scores"]:
            errors.setdefault("scores", "A completed run needs at least one score.")
    if out["status"] == "failed" and not out["scores"]:
        errors.setdefault("scores", "A failed run needs the scores that failed it.")
    if errors:
        raise ServiceError(422, "Some answers need fixing.", errors=errors)
    return out


# ── Rows ────────────────────────────────────────────────────────────────────

def _load_json(raw) -> dict:
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _names(db, ids) -> dict:
    wanted = sorted({i for i in ids if i})
    if not wanted:
        return {}
    rows = db.execute(f"SELECT id, full_name FROM users WHERE id IN ({','.join(['%s'] * len(wanted))})", wanted).fetchall()
    return {r["id"]: r["full_name"] for r in rows}


def _present(db, rows, material_changed_at=None) -> list:
    today = utcnow().strftime("%Y-%m-%d")
    names = _names(db, [i for r in rows for i in (r["recorded_by"], r["reviewed_by"])])
    out = []
    for r in rows:
        scores, thresholds = _load_json(r["scores"]), _load_json(r["thresholds"])
        result = outcome_of(r["status"], scores, thresholds)
        out.append({
            "id": r["id"], "application_id": r["application_id"], "name": r["name"], "status": r["status"],
            "state": r["result_state"], "state_label": STATE_LABELS.get(r["result_state"], r["result_state"]),
            "failed_dimensions": result["failed"], "evaluator": r["evaluator"],
            "test_set_name": r["test_set_name"], "test_set_version": r["test_set_version"],
            "rubric_version": r["rubric_version"], "subject_version": r["subject_version"],
            "started_at": service._text(r["started_at"]), "finished_at": service._text(r["finished_at"]),
            "scores": scores, "thresholds": thresholds, "cases_total": r["cases_total"], "cases_failed": r["cases_failed"],
            "retention": r["retention"], "artifact_id": r["artifact_id"], "notes": r["notes"],
            "recorded_by": names.get(r["recorded_by"]), "recorded_at": service._text(r["recorded_at"]),
            "review_outcome": r["review_outcome"], "reviewed_by": names.get(r["reviewed_by"]),
            "reviewed_at": service._text(r["reviewed_at"]), "review_note": r["review_note"],
            "stale": is_stale(r["finished_at"] or r["recorded_at"], material_changed_at, today), "version": r["version"]})
    return out


def _app(db, user, application_id):
    if not describe_record(db, APP, application_id, user):
        return None
    return db.execute("SELECT id, name, owner_user_id, business_unit_id, is_active FROM applications WHERE id = %s",
                      (application_id,)).fetchone()


def _material_changed_at(db, application_id):
    row = db.execute("SELECT material_changed_at FROM ai_use_profiles WHERE application_id = %s", (application_id,)).fetchone()
    return row["material_changed_at"] if row else None


# ── Operations ──────────────────────────────────────────────────────────────

def record_run(db, user, application_id: int, raw) -> dict:
    service._require(user, "ai_use.review")
    app = _app(db, user, application_id)
    if app is None:
        raise ServiceError(404, "Application not found.")
    if not app["is_active"]:
        raise ServiceError(409, "A retired use cannot be evaluated. Restore it first.")
    fields = clean(raw)
    if fields["artifact_id"] is not None and not describe_record(db, ("evidence", "item"), fields["artifact_id"], user):
        raise ServiceError(400, "Choose a Vault item you can open.")
    result = outcome_of(fields["status"], fields["scores"], fields["thresholds"])
    now = service._now()
    new_id = insert_returning_id(
        db,
        "INSERT INTO ai_evaluation_runs (application_id, business_unit_id, name, test_set_name, test_set_version, rubric_version, "
        "subject_version, evaluator, status, result_state, started_at, finished_at, thresholds, scores, cases_total, cases_failed, "
        "retention, artifact_id, notes, recorded_by, recorded_at, version, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)",
        (application_id, app["business_unit_id"], fields["name"], fields["test_set_name"], fields["test_set_version"],
         fields["rubric_version"], fields["subject_version"], fields["evaluator"], fields["status"], result["state"],
         fields["started_at"], fields["finished_at"], json.dumps(fields["thresholds"]), json.dumps(fields["scores"]),
         fields["cases_total"], fields["cases_failed"], fields["retention"], fields["artifact_id"], fields["notes"],
         user["id"], now, now, now))
    out_events = []
    if result["state"] in ("failed", "interrupted"):
        out_events.append(events.enqueue(
            db, events.EVALUATION_FAILED, "ai_governance", "application", application_id,
            {"run_id": new_id, "application_id": application_id, "state": result["state"], "business_unit_id": app["business_unit_id"]},
            user_id=user["id"], org_id=user.get("org_id"), dedup_key=f"evaluation.failed:{new_id}"))
    row = db.execute("SELECT * FROM ai_evaluation_runs WHERE id = %s", (new_id,)).fetchone()
    return {"run": _present(db, [row], _material_changed_at(db, application_id))[0], "events": out_events,
            "audit": [("ai_evaluation_recorded", "application", application_id, f"run {new_id}: {result['state']}")]}


def list_runs(db, user, application_id: int) -> "dict | None":
    service._require(user, "ai_use.view")
    if _app(db, user, application_id) is None:
        return None
    rows = db.execute("SELECT * FROM ai_evaluation_runs WHERE application_id = %s ORDER BY COALESCE(finished_at, recorded_at) DESC, id DESC LIMIT %s",
                      (application_id, MAX_RUNS_SHOWN)).fetchall()
    runs = _present(db, rows, _material_changed_at(db, application_id))
    latest = runs[0] if runs else None
    previous = next((r for r in runs[1:] if r["test_set_name"] == (latest or {}).get("test_set_name")), None) if latest else None
    return {"runs": runs, "latest": latest, "previous": previous,
            "comparison": compare(previous, latest) if latest and previous else None,
            "can": {"record": has_capability(user, "ai_use.review"), "review": has_capability(user, "ai_use.review")}}


def compare_runs(db, user, older_id: int, newer_id: int) -> dict:
    service._require(user, "ai_use.view")
    rows = []
    for run_id in (older_id, newer_id):
        row = db.execute("SELECT * FROM ai_evaluation_runs WHERE id = %s", (run_id,)).fetchone()
        if row is None or _app(db, user, row["application_id"]) is None:
            raise ServiceError(404, "Run not found.")
        rows.append(row)
    if rows[0]["application_id"] != rows[1]["application_id"]:
        raise ServiceError(400, "Choose two runs of the same use.")
    older, newer = _present(db, rows)
    return {"comparison": compare(older, newer), "older": older, "newer": newer}


def review_run(db, user, run_id: int, outcome, note, expected_version) -> dict:
    """A reviewer accepts a passed run as evidence, or opens a finding for a failed or interrupted one. A finding is a
    proposed task for the owner; it marks no control failed and withdraws no approval."""
    service._require(user, "ai_use.review")
    row = db.execute("SELECT * FROM ai_evaluation_runs WHERE id = %s", (run_id,)).fetchone()
    if row is None or _app(db, user, row["application_id"]) is None:
        raise ServiceError(404, "Run not found.")
    if outcome not in REVIEW_OUTCOMES:
        raise ServiceError(422, "Choose accepted or finding.")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise ServiceError(400, "Send the version of the run you are reviewing.")
    if row["review_outcome"]:
        raise ServiceError(409, "This run was already reviewed.", current_version=row["version"])
    if outcome == "accepted" and row["result_state"] != "passed":
        raise ServiceError(409, "Only a run that passed can be accepted as evidence.")
    if outcome == "finding" and row["result_state"] == "passed":
        raise ServiceError(409, "A run that passed has nothing to open a finding about.")
    note = (note or "").strip() if isinstance(note, str) or note is None else ""
    if outcome == "finding" and len(note) < 3:
        raise ServiceError(422, "Say what the finding is.")
    if len(note) > 1000:
        raise ServiceError(422, "Keep the note to 1000 characters or fewer.")
    app = _app(db, user, row["application_id"])
    now = service._now()
    task = None
    if outcome == "finding":
        task = insert_returning_id(
            db,
            "INSERT INTO task_board (title, description, module, entity_type, entity_id, assigned_to, priority, status, created_by) "
            "VALUES (%s, %s, 'ai_governance', 'application', %s, %s, 'high', 'todo', %s)",
            (f"Evaluation finding: {app['name']}: {row['name']}"[:255], note, row["application_id"], app["owner_user_id"], user["id"]))
    moved = db.execute(
        "UPDATE ai_evaluation_runs SET review_outcome = %s, reviewed_by = %s, reviewed_at = %s, review_note = %s, review_task_id = %s, "
        "version = version + 1, updated_at = %s WHERE id = %s AND review_outcome IS NULL AND version = %s",
        (outcome, user["id"], now, note or None, task, now, run_id, expected_version)).rowcount
    if moved != 1:
        raise ServiceError(409, "This run was changed by someone else. Reload it and try again.")
    done = db.execute("SELECT * FROM ai_evaluation_runs WHERE id = %s", (run_id,)).fetchone()
    return {"run": _present(db, [done], _material_changed_at(db, row["application_id"]))[0], "events": [],
            "audit": [(f"ai_evaluation_{outcome}", "application", row["application_id"], f"run {run_id}")]}


def failed_since(db, application_id: int, since) -> list:
    """Runs that failed or did not finish and were recorded after `since` (any when None): what the platform learned after
    a decision was signed. It goes by when the run was recorded, not when it finished, because a decider could only have
    weighed what was recorded when they signed."""
    sql = ("SELECT id, name, result_state, recorded_at AS at FROM ai_evaluation_runs "
           "WHERE application_id = %s AND result_state IN ('failed', 'interrupted')")
    params = [application_id]
    if since:
        sql += " AND recorded_at > %s"
        params.append(str(since))
    return [dict(r) for r in db.execute(sql + " ORDER BY id DESC LIMIT 20", params).fetchall()]
