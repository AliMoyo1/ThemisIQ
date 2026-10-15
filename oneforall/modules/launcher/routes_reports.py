"""
Launcher sub-router: Reporting engine: definitions, runs, report generation.

A run is frozen when it is generated (plans/2026-10-governance-rework/04 section 5). Generating one reads through the
viewer's own scope, stores the figures with who, when, which scope and which sources, hashes them, and never recomputes
them: opening a saved run decodes what was stored. A person may open only a run generated for them while their access is
what it was then; a refusal is written to the audit log. Running a definition again makes a new run, linked to the
earlier one with a summary of what changed.
"""
import csv
import io
import json as json_lib

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from core.best_effort import swallowed
from core.rbac import user_modules
from core.timeutils import utcnow
from database import insert_returning_id
from modules.governance.data_service import bu_scope_ids
from modules.governance.entity_scope import canonical_key, describe_record
from modules.launcher import report_builders as builders, report_snapshot as snap
from modules.launcher._route_helpers import (
    _JSONResp, require_auth, has_capability, log_audit,
    shell_ctx, shell_templates, get_db,
    _json_body,)
from modules.launcher.scoped_metrics import run_scope_key

router = APIRouter()


REPORT_TYPES = {
    "compliance_summary": "Compliance Summary",
    "risk_report": "Risk Report",
    "audit_status": "Audit Status",
    "privacy_overview": "Privacy Overview",
    "bcm_readiness": "BCM Readiness",
    "sla_performance": "SLA Performance",
    "executive_brief": "Executive Brief",
    "executive_summary": "Executive Summary",
    "bcm_coverage": "BCM: Analysis coverage",
    "bcm_plans": "BCM: Plan status",
    "bcm_incidents": "BCM: Incidents",
    "bcm_exercises": "BCM: Exercises",
    "bcm_summary": "BCM: Programme summary",
    **{key: preset["label"] for key, preset in builders.PRESETS.items()},
}

# The groups the page offers when somebody creates a report. A case report is made from a record, not from this list.
REPORT_GROUPS = [
    ("Standard reports", ["compliance_summary", "risk_report", "audit_status", "privacy_overview", "bcm_readiness",
                          "sla_performance", "executive_brief", "executive_summary"]),
    ("Business continuity", ["bcm_coverage", "bcm_plans", "bcm_incidents", "bcm_exercises", "bcm_summary"]),
    ("By audience", ["preset_specialist", "preset_management", "preset_board"]),
]

QUICK_DESCRIPTION = "Quick report"
_AUTO = object()  # "find the earlier run yourself"
_NO_ACCESS = ("Your access has changed since this report was generated, so its saved output is hidden. "
              "Generate the report again to see what you may open now.")


def _report_result(db, user, report_type, parameters=None):
    """The figures of one report type, read only through the requesting user's scope."""
    if report_type not in REPORT_TYPES:
        raise ValueError("Unknown report type")
    return builders.build(db, user, report_type, parameters).result


# ── Building and freezing ───────────────────────────────────────────────────

def _now() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _ip(request) -> str:
    client = getattr(request, "client", None)
    return client.host if client else ""


def _scope_of(db, user) -> dict:
    """Who the figures cover, in words and in identifiers."""
    units = bu_scope_ids(user)
    org_name = None
    try:
        row = db.execute("SELECT name FROM organizations WHERE id = %s", (user.get("org_id"),)).fetchone()
        org_name = row["name"] if row else None
    except Exception:
        swallowed("report scope: organization name")
        org_name = None
    if units is None:
        label, ids = "Whole organization", None
    elif units == [-1]:
        label, ids = "Organization-wide records only (no business unit is assigned to this person)", []
    else:
        ids = sorted(int(u) for u in units)
        root = None
        try:
            marks = ",".join(["%s"] * len(ids))
            names = {r["id"]: r["name"] for r in db.execute(
                f"SELECT id, name FROM business_units WHERE id IN ({marks})", ids).fetchall()}
            root = names.get(user.get("business_unit_id"))
        except Exception:
            swallowed("report scope: business unit names")
            root = None
        label = (root or "Own business unit") + (f" and {len(ids) - 1} unit{'s' if len(ids) > 2 else ''} below it"
                                                  if len(ids) > 1 else "") + ", and organization-wide records"
    scope = {"org_id": user.get("org_id"), "org_name": org_name, "whole_organization": units is None,
             "business_unit_ids": ids, "organization_wide_only": units == [-1], "modules": sorted(user_modules(user)),
             "label": label}
    scope["fingerprint"] = snap.scope_fingerprint(scope)
    return scope


def _parameters(defn) -> dict:
    try:
        got = json_lib.loads(defn["parameters_json"] or "{}")
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _envelope(db, user, definition_id, name, report_type, parameters, previous=None) -> dict:
    """Read the report and wrap it. `previous` is (run id, its envelope) when this is a run again."""
    built = builders.build(db, user, report_type, parameters)
    now = _now()
    scope = _scope_of(db, user)
    version = builders.definition_version(report_type)
    if report_type == "preset_case":
        name = f"{REPORT_TYPES[report_type]}: {(built.result.get('entity') or {}).get('title') or 'record'}"
    env = {
        "format": snap.FORMAT,
        "run": {"definition_id": definition_id, "definition_name": name, "report_type": report_type,
                "type_label": REPORT_TYPES[report_type], "definition_version": version, "generated_at": now,
                "generated_by": {"id": user["id"], "name": user.get("full_name") or user.get("username")}},
        "scope": scope,
        "period": {"basis": "as_of", "as_of": now,
                   "note": "Every figure is read at the moment the report is generated. There is no period filter."},
        "result": built.result, "sources": built.sources, "inputs": built.inputs,
        "limitations": built.limitations, "exclusions": built.exclusions, "complete": built.complete,
        "decision_status": snap.DECISION_STATUS, "narrative": None, "changes": None,
    }
    if previous and previous[1] is not None:
        env["changes"] = snap.change_summary(previous[1], previous[0], built.result, scope, version)
    return env


def _store(db, user, definition_id, env, previous_id, request) -> int:
    text, digest = snap.encode(env)
    run_id = insert_returning_id(
        db,
        "INSERT INTO report_runs (definition_id, status, triggered_by, completed_at, result_json, snapshot_hash, "
        "previous_run_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (definition_id, "completed", run_scope_key(user), env["run"]["generated_at"], text, digest, previous_id))
    db.commit()
    log_audit(user, "platform", "report_run", entity_type="report_run", entity_id=run_id,
              details=f"{env['run']['report_type']} v{env['run']['definition_version']} sha256={digest[:16]}",
              ip=_ip(request))
    return run_id


def _previous_for(db, user, definition_id):
    """The latest frozen run of this definition that this person may still open, as (id, envelope), else None."""
    row = db.execute(
        "SELECT id, result_json, snapshot_hash FROM report_runs WHERE definition_id = %s AND status = 'completed' "
        "AND snapshot_hash IS NOT NULL AND triggered_by = %s ORDER BY id DESC LIMIT 1",
        (definition_id, run_scope_key(user))).fetchone()
    if row and snap.intact(row["result_json"], row["snapshot_hash"]):
        return row["id"], json_lib.loads(row["result_json"])
    return None


def _failed(db, user, definition_id, reason) -> None:
    try:
        db.execute("INSERT INTO report_runs (definition_id, status, triggered_by, error) VALUES (%s,'failed',%s,%s)",
                   (definition_id, run_scope_key(user), reason[:200]))
        db.commit()
    except Exception:
        swallowed("recording a failed report run")


NOTE_KINDS = ("note", "dispute")


def _notes(db, run_id) -> list:
    rows = db.execute(
        "SELECT id, kind, figure, body, author_id, author_name, created_at FROM report_run_notes "
        "WHERE run_id = %s ORDER BY id", (run_id,)).fetchall()
    return [dict(r) for r in rows]


def _present(row, with_records=False) -> dict:
    """What a person is given for one saved run. Never recomputed: legacy runs say that they are legacy."""
    out = {"id": row["id"], "run_id": row["id"], "definition_id": row["definition_id"], "status": row["status"],
           "started_at": row["started_at"], "completed_at": row["completed_at"], "error": row["error"],
           "report_name": row.get("report_name"), "report_type": row.get("report_type"),
           "description": row.get("description"), "previous_run_id": row.get("previous_run_id"),
           "frozen": False, "legacy": False, "result": None}
    text, digest = row.get("result_json"), row.get("snapshot_hash")
    if digest:
        if not snap.intact(text, digest):
            out["integrity_failed"] = True
            return out
        env = json_lib.loads(text)
        out["report_name"] = (env.get("run") or {}).get("definition_name") or out["report_name"]
        if not with_records:
            env["inputs"] = {k: {"count": len(v.get("ids") or []), "truncated": v.get("truncated", False)}
                             for k, v in (env.get("inputs") or {}).items()}
        out.update(frozen=True, hash=digest, result=env.get("result"), snapshot=env)
    else:
        out["legacy"] = True
        if text:
            try:
                out["result"] = json_lib.loads(text)
            except ValueError:
                out["result"] = None
        out["legacy_note"] = (
            "This run was saved before reports were frozen. " +
            ("Its figures are shown as they were stored, without the scope or the sources they were read from."
             if out["result"] is not None else
             "Its output was not kept and it is not recomputed, because today's figures would carry the name of an "
             "older run. Run the report again."))
    return out


def _open(db, user, run_id, request, action):
    """The run row when this person may open it, else (None, response). A refusal is written to the audit log."""
    row = db.execute(
        "SELECT rr.*, rd.name AS report_name, rd.report_type, rd.description "
        "FROM report_runs rr LEFT JOIN report_definitions rd ON rr.definition_id = rd.id WHERE rr.id = %s",
        (run_id,)).fetchone()
    if not row:
        return None, _JSONResp({"error": "Not found"}, status_code=404)
    verdict = snap.decide(user, row["triggered_by"], run_scope_key(user))
    if verdict == snap.ALLOW:
        return dict(row), None
    log_audit(user, "platform", "report_run_denied", entity_type="report_run", entity_id=run_id,
              details=f"{action}: {verdict}", ip=_ip(request))
    if verdict == snap.ACCESS_CHANGED:
        return None, _JSONResp({"error": _NO_ACCESS, "reason": "access_changed"}, status_code=403)
    return None, _JSONResp({"error": "Not found"}, status_code=404)


def _integrity_refusal(user, run_id, request):
    log_audit(user, "platform", "report_run_integrity_failed", entity_type="report_run", entity_id=run_id,
              ip=_ip(request))
    return _JSONResp({"error": "This saved report failed its integrity check and cannot be shown.",
                      "reason": "integrity"}, status_code=409)


def _execute(request, db, user, defn, previous=_AUTO):
    """Run one definition now. `previous` is (run id, its envelope or None), None for no earlier run, or left out to
    find the latest earlier run this person may still open. Returns the response."""
    report_type = defn["report_type"]
    if report_type not in REPORT_TYPES:
        return _JSONResp({"error": "Unknown report type"}, status_code=400)
    params = _parameters(defn)
    if previous is _AUTO:
        previous = _previous_for(db, user, defn["id"])
    try:
        env = _envelope(db, user, defn["id"], defn["name"], report_type, params, previous)
    except builders.RecordNotAvailable:
        return _JSONResp({"error": "Not found"}, status_code=404)
    except ValueError as exc:
        return _JSONResp({"error": str(exc)}, status_code=400)
    except Exception:
        builders.log.warning("Report %s could not be generated", report_type, exc_info=True)
        _failed(db, user, defn["id"], "The report could not be generated.")
        return _JSONResp({"error": "The report could not be generated. Nothing was saved as a result."}, status_code=500)
    run_id = _store(db, user, defn["id"], env, previous[0] if previous else None, request)
    row = db.execute(
        "SELECT rr.*, rd.name AS report_name, rd.report_type, rd.description FROM report_runs rr "
        "LEFT JOIN report_definitions rd ON rr.definition_id = rd.id WHERE rr.id = %s", (run_id,)).fetchone()
    return _JSONResp(_present(dict(row)))


def _quick_definition(db, user, report_type, parameters=None, name=None) -> dict:
    """The person's own standing definition for a quick report of this type, made once and reused, so that each run
    is linked to the one before it."""
    params = json_lib.dumps(parameters or {}, sort_keys=True)
    row = db.execute(
        "SELECT * FROM report_definitions WHERE created_by = %s AND report_type = %s AND description = %s "
        "AND is_active = 1 AND COALESCE(parameters_json, '{}') = %s ORDER BY id LIMIT 1",
        (user["id"], report_type, QUICK_DESCRIPTION, params)).fetchone()
    if row:
        return dict(row)
    did = insert_returning_id(
        db, "INSERT INTO report_definitions (name, description, report_type, modules, parameters_json, schedule, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        ((name or REPORT_TYPES[report_type])[:200], QUICK_DESCRIPTION, report_type, "", params, "", user["id"]))
    db.commit()
    return dict(db.execute("SELECT * FROM report_definitions WHERE id = %s", (did,)).fetchone())


# ── Pages and definitions ───────────────────────────────────────────────────

@router.get("/reports", response_class=HTMLResponse)
@require_auth
async def reports_page(request: Request):
    """Reporting engine page."""
    ctx = shell_ctx(request, active_module="platform", active_section="reports")
    ctx["report_types"] = REPORT_TYPES
    ctx["report_groups"] = [(title, [(k, REPORT_TYPES[k]) for k in keys]) for title, keys in REPORT_GROUPS]
    return shell_templates.TemplateResponse(request, "reports.html", ctx)


@router.get("/api/reports/definitions")
@require_auth
async def api_report_definitions(request: Request):
    """List report definitions."""
    user = request.state.user
    where = "" if user.get("is_super_admin") else "WHERE rd.created_by = %s"
    params = () if user.get("is_super_admin") else (user["id"],)
    db = get_db()
    try:
        rows = db.execute(
            "SELECT rd.*, u.full_name as creator_name "
            "FROM report_definitions rd LEFT JOIN users u ON rd.created_by = u.id "
            f"{where} ORDER BY rd.created_at DESC", params
        ).fetchall()
    finally:
        db.close()
    return _JSONResp([dict(r) for r in rows])


def _checked_parameters(report_type, data):
    """(parameters dict, error text). A case report must name a record it can be made from."""
    parameters = data.get("parameters", {})
    if not isinstance(parameters, dict):
        return None, "Parameters must be an object"
    if report_type == "preset_case":
        subject = builders.valid_subject(parameters)
        if subject is None:
            return None, "A case report needs a record: parameters.subject with module, entity_type and entity_id"
        parameters = {"subject": subject}
    return parameters, None


@router.post("/api/reports/definitions", status_code=201)
@require_auth
async def api_report_definition_create(request: Request):
    """Create a report definition."""
    data = await _json_body(request)
    report_type = data.get("report_type", "compliance_summary")
    if report_type not in REPORT_TYPES:
        return _JSONResp({"error": "Unknown report type"}, status_code=400)
    parameters, problem = _checked_parameters(report_type, data)
    if problem:
        return _JSONResp({"error": problem}, status_code=400)
    db = get_db()
    try:
        rid = insert_returning_id(
            db,
            "INSERT INTO report_definitions (name, description, report_type, modules, parameters_json, schedule, created_by) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                data.get("name", ""),
                data.get("description", ""),
                report_type,
                data.get("modules", ""),
                json_lib.dumps(parameters),
                data.get("schedule", ""),
                request.state.user["id"],
            )
        )
        db.commit()
    finally:
        db.close()
    log_audit(request.state.user, "platform", "report_create", details=f"Created report: {data.get('name')}")
    return _JSONResp({"id": rid}, status_code=201)


@router.put("/api/reports/definitions/{rid}")
@require_auth
async def api_report_definition_update(request: Request, rid: int):
    """Update a report definition."""
    data = await _json_body(request)
    if "report_type" in data and data["report_type"] not in REPORT_TYPES:
        return _JSONResp({"error": "Unknown report type"}, status_code=400)
    if data.get("report_type") == "preset_case":
        _, problem = _checked_parameters("preset_case", data)
        if problem:
            return _JSONResp({"error": problem}, status_code=400)
    if "parameters" in data and not isinstance(data["parameters"], dict):
        return _JSONResp({"error": "Parameters must be an object"}, status_code=400)
    user = request.state.user
    db = get_db()
    try:
        owner = db.execute("SELECT created_by FROM report_definitions WHERE id = %s", (rid,)).fetchone()
        if not owner or (not user.get("is_super_admin") and owner["created_by"] != user["id"]):
            return _JSONResp({"error": "Not found"}, status_code=404)
        fields, params = [], []
        for key in ("name", "description", "report_type", "modules", "schedule", "is_active"):
            if key in data:
                fields.append(f"{key} = %s")
                params.append(data[key])
        if "parameters" in data:
            fields.append("parameters_json = %s")
            params.append(json_lib.dumps(data["parameters"]))
        if fields:
            params.append(rid)
            db.execute(f"UPDATE report_definitions SET {', '.join(fields)} WHERE id = %s", params)
            db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


@router.delete("/api/reports/definitions/{rid}")
@require_auth
async def api_report_definition_delete(request: Request, rid: int):
    """Disable a report definition."""
    user = request.state.user
    if not has_capability(user, "platform.manage_users"):
        return _JSONResp({"error": "Forbidden"}, status_code=403)
    db = get_db()
    try:
        owner = db.execute("SELECT created_by FROM report_definitions WHERE id = %s", (rid,)).fetchone()
        if not owner or (not user.get("is_super_admin") and owner["created_by"] != user["id"]):
            return _JSONResp({"error": "Not found"}, status_code=404)
        db.execute("UPDATE report_definitions SET is_active = 0 WHERE id = %s", (rid,))
        db.commit()
    finally:
        db.close()
    return _JSONResp({"success": True})


# ── Runs ────────────────────────────────────────────────────────────────────

@router.post("/api/reports/quick-run")
@require_auth
async def api_report_quick_run(request: Request):
    """Generate a report of one type now, under the person's standing definition for it. The one call every
    "Generate report" button makes, so that none of them reports success before there is a saved run."""
    data = await _json_body(request)
    report_type = data.get("report_type")
    if report_type not in REPORT_TYPES:
        return _JSONResp({"error": "Unknown report type"}, status_code=400)
    parameters, name = None, None
    if report_type == "preset_case":
        subject = builders.valid_subject({"subject": data.get("subject")})
        if subject is None:
            return _JSONResp({"error": "A case report needs a record"}, status_code=400)
        parameters = {"subject": subject}
    user = request.state.user
    db = get_db()
    try:
        if parameters:
            shown = describe_record(db, canonical_key(subject["module"], subject["entity_type"]), subject["entity_id"], user)
            if shown is None:
                return _JSONResp({"error": "Not found"}, status_code=404)
            name = f"{REPORT_TYPES[report_type]}: {shown['title']}"
        defn = _quick_definition(db, user, report_type, parameters, name)
        return _execute(request, db, user, defn)
    finally:
        db.close()


@router.post("/api/reports/{rid}/run")
@require_auth
async def api_report_run(request: Request, rid: int):
    """Generate a report (run it now)."""
    user = request.state.user
    db = get_db()
    try:
        defn = db.execute("SELECT * FROM report_definitions WHERE id = %s", (rid,)).fetchone()
        if (not defn or not defn["is_active"] or
                (not user.get("is_super_admin") and defn["created_by"] != user["id"])):
            return _JSONResp({"error": "Report not found"}, status_code=404)
        return _execute(request, db, user, dict(defn))
    finally:
        db.close()


@router.get("/api/reports/runs")
@require_auth
async def api_report_runs(request: Request):
    """List the runs this person may open. The figures are not in the list."""
    user = request.state.user
    db = get_db()
    try:
        def_id = request.query_params.get("definition_id", "")
        where = ["1=1"]
        params = []
        if not user.get("is_super_admin"):
            where.extend(["rd.created_by = %s", "rr.triggered_by = %s"])
            params.extend([user["id"], run_scope_key(user)])
        if def_id:
            if not def_id.isdecimal():
                return _JSONResp({"error": "Invalid definition id"}, status_code=400)
            where.append("rr.definition_id = %s")
            params.append(int(def_id))
        rows = db.execute(
            "SELECT rr.id, rr.definition_id, rr.status, rr.started_at, rr.completed_at, rr.error, rr.previous_run_id, "
            "rr.snapshot_hash, rd.name as report_name, rd.report_type "
            "FROM report_runs rr "
            "LEFT JOIN report_definitions rd ON rr.definition_id = rd.id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY rr.started_at DESC, rr.id DESC LIMIT 50",
            params
        ).fetchall()
    finally:
        db.close()
    out = []
    for r in rows:
        item = dict(r)
        item["frozen"] = bool(item.pop("snapshot_hash"))
        out.append(item)
    return _JSONResp(out)


@router.get("/api/reports/runs/{run_id}")
@require_auth
async def api_report_run_get(request: Request, run_id: int):
    """One saved run, as it was generated. Never recomputed."""
    user = request.state.user
    db = get_db()
    try:
        row, refusal = _open(db, user, run_id, request, "open")
        if refusal:
            return refusal
    finally:
        db.close()
    shown = _present(row, with_records=request.query_params.get("records") == "1")
    if shown.get("integrity_failed"):
        return _integrity_refusal(user, run_id, request)
    db = get_db()
    try:
        shown["notes"] = _notes(db, run_id)
    finally:
        db.close()
    if shown.get("frozen"):
        shown["figures"] = sorted(snap.flatten(shown.get("result")))
    return _JSONResp(shown)


@router.post("/api/reports/runs/{run_id}/notes", status_code=201)
@require_auth
async def api_report_run_note(request: Request, run_id: int):
    """Record a note, or a dispute of one figure, against a saved run. The run itself is never changed: the figure
    stays as it was generated, and the note sits beside it with who wrote it and when."""
    data = await _json_body(request)
    kind = data.get("kind", "note")
    body = str(data.get("body") or "").strip()
    figure = str(data.get("figure") or "").strip() or None
    if kind not in NOTE_KINDS:
        return _JSONResp({"error": "Choose note or dispute"}, status_code=400)
    if not body or len(body) > 1000:
        return _JSONResp({"error": "Write what you want to record, in up to 1000 characters"}, status_code=400)
    user = request.state.user
    db = get_db()
    try:
        row, refusal = _open(db, user, run_id, request, "note")
        if refusal:
            return refusal
        if not row.get("snapshot_hash"):
            return _JSONResp({"error": "This run was saved before reports were frozen, so there is no figure to dispute. "
                                       "Run the report again."}, status_code=409)
        if figure is not None:
            known = snap.flatten((json_lib.loads(row["result_json"]) or {}).get("result"))
            if figure not in known:
                return _JSONResp({"error": "That figure is not in this run"}, status_code=400)
        note_id = insert_returning_id(
            db,
            "INSERT INTO report_run_notes (run_id, kind, figure, body, author_id, author_name) VALUES (%s,%s,%s,%s,%s,%s)",
            (run_id, kind, figure, body, user["id"], user.get("full_name") or user.get("username")))
        db.commit()
    finally:
        db.close()
    log_audit(user, "platform", f"report_run_{kind}", entity_type="report_run", entity_id=run_id,
              details=f"figure={figure or '-'}", ip=_ip(request))
    return _JSONResp({"id": note_id, "run_id": run_id, "kind": kind, "figure": figure}, status_code=201)


@router.get("/api/reports/runs/{run_id}/export")
@require_auth
async def api_report_run_export(request: Request, run_id: int):
    """The frozen figures of one run as a CSV file, with the scope, sources and limitations above them."""
    user = request.state.user
    db = get_db()
    try:
        row, refusal = _open(db, user, run_id, request, "export")
        if refusal:
            return refusal
    finally:
        db.close()
    if not row.get("snapshot_hash"):
        return _JSONResp({"error": "This run was saved before reports were frozen and has no complete output to export. "
                                   "Run the report again."}, status_code=409)
    if not snap.intact(row.get("result_json"), row.get("snapshot_hash")):
        return _integrity_refusal(user, run_id, request)
    buffer = io.StringIO()
    csv.writer(buffer).writerows(snap.csv_rows(json_lib.loads(row["result_json"])))
    log_audit(user, "platform", "report_run_export", entity_type="report_run", entity_id=run_id,
              details=f"sha256={row['snapshot_hash'][:16]}", ip=_ip(request))
    return Response(buffer.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="report-run-{run_id}.csv"', "Cache-Control": "no-store"})


@router.post("/api/reports/runs/{run_id}/rerun")
@require_auth
async def api_report_run_again(request: Request, run_id: int):
    """Run the same definition again. The earlier run is not touched; the new one is linked to it, with what changed."""
    user = request.state.user
    db = get_db()
    try:
        row, refusal = _open(db, user, run_id, request, "rerun")
        if refusal:
            return refusal
        defn = db.execute("SELECT * FROM report_definitions WHERE id = %s", (row["definition_id"],)).fetchone()
        if (not defn or not defn["is_active"] or
                (not user.get("is_super_admin") and defn["created_by"] != user["id"])):
            return _JSONResp({"error": "This report's definition is no longer available"}, status_code=404)
        earlier = None
        if row.get("snapshot_hash") and snap.intact(row.get("result_json"), row.get("snapshot_hash")):
            earlier = json_lib.loads(row["result_json"])
        return _execute(request, db, user, dict(defn), previous=(run_id, earlier))
    finally:
        db.close()


# ── The AI executive summary ────────────────────────────────────────────────

_SUMMARY_SYSTEM = ("You are a GRC reporting assistant writing for a board of directors. Be concise and professional. "
                   "Use only the figures you are given. Do not state a legal conclusion or an assurance opinion.")


@router.post("/api/reports/executive-summary")
@require_auth
async def api_executive_summary(request: Request):
    """The executive figures as a frozen run, with a draft narrative when the AI policy allows one.

    The figures never depend on the model: with AI off, refused or failing, the run is still made and complete, and the
    response says why there is no narrative. A narrative is a draft that nobody has reviewed."""
    from core import ai_client
    from core.ai_policy import AIPolicyError
    user = request.state.user
    db = get_db()
    try:
        defn = _quick_definition(db, user, "executive_summary")
        previous = _previous_for(db, user, defn["id"])
        try:
            env = _envelope(db, user, defn["id"], defn["name"], "executive_summary", {}, previous)
        except Exception:
            builders.log.warning("Executive summary figures could not be read", exc_info=True)
            _failed(db, user, defn["id"], "The figures could not be read.")
            return _JSONResp({"error": "The figures could not be read just now. Nothing was saved as a result."},
                             status_code=500)
        stats = env["result"]
        narrative, problem = None, None
        if not ai_client.is_configured():
            problem = "AI is not configured, so no narrative was written. The figures are complete."
        else:
            given = {k: v for k, v in stats.items() if v is not None}
            missing = sorted(k for k, v in stats.items() if v is None)
            prompt = (
                f"Figures:\n{json_lib.dumps(given)}\n\n"
                + (f"These figures are not available to the requesting user and must not be described: {', '.join(missing)}.\n"
                   if missing else "")
                + "These figures cover only records visible to the requesting user. A zero is a count of zero; a missing "
                  "figure is not a zero. Write a 3-4 paragraph executive summary for a board of directors covering "
                  "compliance posture, key risks, active audits, privacy status and business continuity readiness. "
                  "Highlight urgent items. Plain prose paragraphs only, no markdown and no bullet points.")
            try:
                got = ai_client.create_message_full(
                    [{"role": "user", "content": prompt}], system=_SUMMARY_SYSTEM, max_tokens=1500,
                    feature="launcher.api_executive_summary")
                narrative = {"state": "draft", "text": got.get("text") or "", "model": got.get("model") or "",
                             "feature": "launcher.api_executive_summary", "generated_at": _now(),
                             "basis": "The figures of this run only. No record title or document is given to the model.",
                             "approval": "not_reviewed"}
            except AIPolicyError as exc:
                problem = f"{exc} The figures are complete."
            except Exception:
                builders.log.warning("Executive summary narrative failed", exc_info=True)
                problem = "The narrative could not be written just now. The figures are complete."
        env["narrative"] = narrative
        run_id = _store(db, user, defn["id"], env, previous[0] if previous else None, request)
    finally:
        db.close()
    return _JSONResp({
        "run_id": run_id, "stats": stats, "narrative": narrative["text"] if narrative else None,
        "narrative_state": narrative["state"] if narrative else "unavailable", "narrative_note": problem,
        "generated_at": env["run"]["generated_at"], "complete": env["complete"], "limitations": env["limitations"],
        "frozen": True,
    })
