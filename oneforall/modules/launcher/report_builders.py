"""
What each report type reads, and what it leaves out (plans/2026-10-governance-rework/04 section 5).

A builder returns the flat figures of one report type. It reads only through the viewer's own scope, and through a
`Reader`, so that the run can say afterwards which sources it read, which it could not read and which the viewer may not
open at all. A figure from a source that was not read is `None`: never a zero.

`build()` returns what the snapshot envelope stores; `routes_reports` freezes it. The viewpoint presets (specialist
portfolio, management, board, case) are templates over these same builders: they compose existing report types into one
run and add no store of their own.
"""
import logging
from dataclasses import dataclass, field

from core.best_effort import attempt
from core.metric_registry import (
    BREACH_ACTIVE, CONTROL_IMPLEMENTED, EXERCISE_COMPLETED, INCIDENT_ACTIVE)
from core.report_kit import identity
from database import sql_current_date
from modules.launcher.report_snapshot import RECORD_CAP
from modules.launcher.scoped_metrics import scoped_count, table_scope

log = logging.getLogger("oneforall.reports")

LIST_CAP = 200

# table -> (what the viewer calls it, the module whose access governs it)
SOURCES = {
    "controls": ("Controls", "aria"),
    "aria_documents": ("Controlled documents", "aria"),
    "evidence_items": ("Vault artifacts", "evidence"),
    "applications": ("Applications", "ai_governance"),
    "ai_use_profiles": ("AI use profiles", "ai_governance"),
    "aims_assessments": ("AIMS assessments", "orm"),
    "aims_risks": ("AIMS risks", "orm"),
    "frameworks": ("Frameworks", "aria"),
    "risk_register": ("Platform risk register", "platform"),
    "erm_enterprise_risks": ("Enterprise risks", "erm"),
    "grid_audits": ("Audits", "grid"),
    "grid_controls": ("Audit controls", "grid"),
    "grid_non_conformances": ("Audit findings", "grid"),
    "sentinel_ropa": ("Processing records", "sentinel"),
    "sentinel_dpias": ("Impact assessments", "sentinel"),
    "sentinel_breaches": ("Breaches", "sentinel"),
    "sentinel_dsr": ("Data subject requests", "sentinel"),
    "bcm_plans": ("Continuity plans", "bcm"),
    "bcm_bia_records": ("Business impact analyses", "bcm"),
    "bcm_incidents": ("Incidents", "bcm"),
    "bcm_exercises": ("Exercises", "bcm"),
    "bcm_risks": ("Continuity risks", "bcm"),
    "sla_instances": ("Service clocks", "platform"),
    "task_board": ("Tasks", "platform"),
}

# These are source-owned revision fields, not a claim that every mutation updates them.
# Keep the mapping explicit so a schema change cannot silently invent a version.
SOURCE_REVISIONS = {
    "controls": ("version", "last_updated"),
    "frameworks": (None, "updated_at"),
    "risk_register": (None, "updated_at"),
    "erm_enterprise_risks": (None, "updated_at"),
    "sentinel_ropa": (None, "updated_at"),
    "sentinel_dpias": (None, "updated_at"),
    "sentinel_breaches": (None, "updated_at"),
    "sentinel_dsr": (None, "updated_at"),
    "bcm_plans": ("version", "updated_at"),
    "bcm_bia_records": (None, "updated_at"),
    "bcm_incidents": (None, "updated_at"),
    "bcm_exercises": (None, "updated_at"),
    "bcm_risks": (None, "updated_at"),
    "task_board": (None, "updated_at"),
}

class RecordNotAvailable(Exception):
    """A case report was asked for a record the person may not open, or that does not exist. The two answer alike."""


READ, NOT_IN_SCOPE, UNAVAILABLE = "read", "not_in_scope", "unavailable"
_SEVERITY = {READ: 0, NOT_IN_SCOPE: 1, UNAVAILABLE: 2}


class Reader:
    """Reads through the viewer's scope and remembers what became of each source."""

    def __init__(self, db, user):
        self.db, self.user = db, user
        self.state = {}      # table -> read | not_in_scope | unavailable
        self.notes = []      # sentences a builder adds to the report's limitations
        self.custom = []     # sources that are not one table: (key, label, module, state)
        self.extra_inputs = {}

    def hidden(self, table) -> bool:
        return table_scope(table, self.user)[0] == "(1 = 0)"

    def _mark(self, table, state):
        if _SEVERITY[state] >= _SEVERITY.get(self.state.get(table), -1):
            self.state[table] = state

    def read(self, tables, fn, default=None):
        """Run `fn()` when the viewer may open every table; otherwise return `default` and say why."""
        tables = (tables,) if isinstance(tables, str) else tuple(tables)
        closed = [t for t in tables if self.hidden(t)]
        if closed:
            for t in closed:
                self._mark(t, NOT_IN_SCOPE)
            return default
        out, ok = default, False
        with attempt(self.db, f"report read of {', '.join(tables)}"):
            out = fn()
            ok = True
        for t in tables:
            self._mark(t, READ if ok else UNAVAILABLE)
        return out if ok else default

    def count(self, table, where="", params=()):
        return self.read(table, lambda: scoped_count(self.db, self.user, table, where, params))

    def rows(self, table, sql, params=(), alias=""):
        """`sql` has `{scope}` where the viewer's scope for `table` goes; returns a list of dicts or None."""
        def go():
            scope, sp = table_scope(table, self.user, alias)
            return [dict(r) for r in self.db.execute(sql.format(scope=scope), [*sp, *params]).fetchall()]
        return self.read(table, go)

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def manifest(self, declared) -> list:
        out = []
        for table in declared:
            label, module = SOURCES.get(table, (table, ""))
            state = self.state.get(table, READ)
            records = None
            if state == READ:
                records = self.read(table, lambda t=table: scoped_count(self.db, self.user, t))
            out.append({"source": table, "label": label, "module": module,
                        "state": self.state.get(table, state), "records": records})
        for key, label, module, state in self.custom:
            out.append({"source": key, "label": label, "module": module, "state": state, "records": None})
        return out

    def inputs(self, declared) -> dict:
        """Authorized row IDs and source-recorded revisions, frozen with the report."""
        out = {}
        for table in declared:
            if self.state.get(table) != READ:
                continue
            version_field, changed_field = SOURCE_REVISIONS.get(table, (None, None))
            fields = ["id", *[name for name in (version_field, changed_field) if name]]
            rows = self.rows(table, "SELECT " + ", ".join(fields) + " FROM " + table +
                             " WHERE {scope} ORDER BY id LIMIT " + str(RECORD_CAP + 1))
            if rows is None:
                continue
            selected = rows[:RECORD_CAP]
            out[table] = {
                "ids": [row["id"] for row in selected],
                "truncated": len(rows) > RECORD_CAP,
                "revision_state": "source_recorded" if version_field or changed_field else "not_recorded",
                "revisions": [{"id": row["id"], "version": row.get(version_field) if version_field else None,
                               "last_recorded_change": row.get(changed_field) if changed_field else None}
                              for row in selected] if version_field or changed_field else [],
            }
        out.update(self.extra_inputs)
        return out


@dataclass
class Built:
    result: dict
    sources: list
    inputs: dict
    limitations: list
    exclusions: list
    complete: bool
    parts: list = field(default_factory=list)


# ── The report types ────────────────────────────────────────────────────────

def _compliance_summary(r, lists=True):
    c = r.count

    def by_framework():
        scope, params = table_scope("controls", r.user, "c")
        fs, fp = table_scope("frameworks", r.user, "f")
        rows = r.db.execute(
            "SELECT f.name, COUNT(c.id) AS total, "
            f"SUM(CASE WHEN c.{CONTROL_IMPLEMENTED} THEN 1 ELSE 0 END) AS ok "
            "FROM frameworks f LEFT JOIN controls c ON c.framework_id = f.id "
            f"AND {scope} WHERE f.is_active = 1 AND {fs} GROUP BY f.id", [*params, *fp]).fetchall()
        return [dict(x) for x in rows]

    def by_status():
        scope, params = table_scope("controls", r.user)
        rows = r.db.execute(
            f"SELECT COALESCE(status, 'none') AS status, COUNT(*) AS n FROM controls WHERE {scope} GROUP BY status",
            params).fetchall()
        return {x["status"]: x["n"] for x in rows}

    out = {
        "total_controls": c("controls"),
        "compliant": c("controls", CONTROL_IMPLEMENTED),
        "non_compliant": c("controls", "status IN ('Not Started','Not Implemented')"),
        "partial": c("controls", "status IN ('In Progress','Partially Implemented')"),
        "by_status": r.read("controls", by_status),
        "by_framework": r.read(("frameworks", "controls"), by_framework),
    }
    r.note("Compliant means the control's status is Implemented. A control whose documentation is only approved is not counted "
           "as implemented, and the statuses are listed in full under by status so that every control is accounted for.")
    return out


def _open_risks(r):
    """Every open risk the viewer may read, from both registers, banded the way the Risk Register page and the Command Centre
    band them. None when neither register could be read. A report that counted one register would understate the other."""
    user, db = r.user, r.db

    def enterprise():
        scope, params = table_scope("erm_enterprise_risks", user)
        return db.execute("SELECT title, likelihood, impact, treatment, status FROM erm_enterprise_risks "
                          f"WHERE {scope} AND status != 'closed'", params).fetchall()

    def platform():
        scope, params = table_scope("risk_register", user)
        return db.execute("SELECT title, likelihood, impact, risk_level, source_module, treatment, status FROM risk_register "
                          f"WHERE {scope} AND status != 'closed'", params).fetchall()

    ent = r.read("erm_enterprise_risks", enterprise)
    plat = r.read("risk_register", platform)
    if ent is None and plat is None:
        return None
    ent_read = ent is not None
    ent, plat = ent or [], plat or []
    levels = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    by_module, ranked = {}, []
    for row in ent:
        score = (row["likelihood"] or 0) * (row["impact"] or 0)
        level = "critical" if score >= 20 else "high" if score >= 12 else "medium" if score >= 6 else "low"
        levels[level] += 1
        ranked.append((score, {"title": row["title"], "risk_level": level, "source_module": "erm",
                               "treatment": row["treatment"], "status": row["status"]}))
    for row in plat:
        if row["risk_level"] in levels:
            levels[row["risk_level"]] += 1
        module = row["source_module"] or "unassigned"
        by_module[module] = by_module.get(module, 0) + 1
        ranked.append(((row["likelihood"] or 0) * (row["impact"] or 0), {
            "title": row["title"], "risk_level": row["risk_level"], "source_module": row["source_module"],
            "treatment": row["treatment"], "status": row["status"]}))
    if ent_read:
        by_module["erm"] = by_module.get("erm", 0) + len(ent)  # the register page says erm: 0 too when there are none
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    total = len(ent) + len(plat)
    return {"total": total, "levels": levels, "unrated": total - sum(levels.values()), "by_module": by_module, "ranked": ranked}


_RISK_BANDS_NOTE = ("Open means a status other than closed. Enterprise risks are banded by likelihood times impact: critical 20 and "
                    "over, high 12 to 19, medium 6 to 11, low under 6, as on the Risk Register page; platform risks keep the "
                    "level they were recorded with. The Enterprise Risk module bands its own risks with its rating framework, "
                    "so its dashboard can count them differently.")


def _risk_report(r, lists=True):
    got = _open_risks(r)
    if got is None:
        return {"total_open": None, "by_level": None, "unrated": None, "by_module": None, "top_risks": None}
    r.note(_RISK_BANDS_NOTE)
    return {"total_open": got["total"], "by_level": got["levels"], "unrated": got["unrated"], "by_module": got["by_module"],
            "top_risks": [row for _, row in got["ranked"][:10]] if lists else None}


# A finding is closed when its status or its corrective action plan status says closed, as everywhere in the Audit module.
NC_OPEN = "COALESCE(status, 'open') != 'closed' AND COALESCE(cap_status, 'Open') != 'Closed'"


def _audit_status(r, lists=True):
    c = r.count
    return {"total_audits": c("grid_audits"),
            "active": c("grid_audits", "status IN ('Planning','Active')"),
            "completed": c("grid_audits", "status IN ('Completed','Complete')"),
            "by_status": _by(r, "grid_audits", "status"),
            "open_ncs": c("grid_non_conformances", NC_OPEN)}


def _privacy_overview(r, lists=True):
    c = r.count
    return {"ropa_count": c("sentinel_ropa"), "dpia_count": c("sentinel_dpias"),
            "breaches_open": c("sentinel_breaches", BREACH_ACTIVE),
            "dsr_open": c("sentinel_dsr", "status NOT IN ('completed','closed')")}


def _bcm_readiness(r, lists=True):
    c = r.count
    return {"plans": c("bcm_plans"), "active_incidents": c("bcm_incidents", INCIDENT_ACTIVE),
            "exercises_completed": c("bcm_exercises", EXERCISE_COMPLETED)}


def _sla_performance(r, lists=True):
    c = r.count
    return {"total_tracked": c("sla_instances"), "active": c("sla_instances", "status = 'active'"),
            "breached": c("sla_instances", "breached = 1"), "resolved": c("sla_instances", "status = 'resolved'"),
            "by_status": _by(r, "sla_instances", "status")}


def _executive_brief(r, lists=True):
    c = r.count
    risks = _open_risks(r)
    r.note("Risks are the enterprise risks and the platform risk register together, counted as in the risk report. " + _RISK_BANDS_NOTE)
    return {"controls_total": c("controls"), "controls_compliant": c("controls", CONTROL_IMPLEMENTED),
            "risks_critical": None if risks is None else risks["levels"]["critical"],
            "risks_high": None if risks is None else risks["levels"]["high"],
            "audits_active": c("grid_audits", "status IN ('Planning','Active')"),
            "breaches_open": c("sentinel_breaches", BREACH_ACTIVE),
            "sla_breaches": c("sla_instances", "breached = 1 AND status = 'active'")}


def _percent(done, total):
    """A share rounded half up, so 5 of 8 is 63 percent as it is on the pages and in the documents (round() gives 62)."""
    return None if not total else identity.pct(done, total)


def _executive_summary(r, lists=True):
    """The figures the board narrative is written from. The model is given these and nothing else."""
    c = r.count
    total, done = c("controls"), c("controls", CONTROL_IMPLEMENTED)
    risks = _open_risks(r)
    r.note("Risks are the enterprise risks and the platform risk register together, counted as in the risk report. " + _RISK_BANDS_NOTE)
    return {
        "controls_total": total, "controls_compliant": done,
        "compliance_pct": _percent(done, total) if total is not None and done is not None else None,
        "risks_open": None if risks is None else risks["total"],
        "risks_critical": None if risks is None else risks["levels"]["critical"],
        "audits_active": c("grid_audits", "status IN ('Planning','Active')"),
        "breaches_open": c("sentinel_breaches", BREACH_ACTIVE),
        "dsrs_open": c("sentinel_dsr", "status NOT IN ('completed','closed')"),
        "incidents_active": c("bcm_incidents", INCIDENT_ACTIVE),
        "bcm_plans": c("bcm_plans"),
        "tasks_open": c("task_board", "status NOT IN ('done','cancelled')"),
        "tasks_overdue": c("task_board", f"due_date IS NOT NULL AND due_date != '' AND due_date < {sql_current_date()} "
                                         "AND status NOT IN ('done','cancelled')"),
    }


def _bcm_coverage(r, lists=True):
    c = r.count
    total = c("bcm_bia_records")

    def covered():
        scope, params = table_scope("bcm_bia_records", r.user, "b")
        return r.db.execute(
            f"SELECT COUNT(*) FROM bcm_bia_records b WHERE {scope} "
            "AND EXISTS (SELECT 1 FROM bcm_bia_plan_links l WHERE l.bia_id = b.id)", params).fetchone()[0]
    done = r.read("bcm_bia_records", covered) if total is not None else None
    uncovered = None
    if lists and total is not None:
        uncovered = r.rows(
            "bcm_bia_records",
            "SELECT b.id, b.process_name AS name, b.criticality, b.rto_hours FROM bcm_bia_records b WHERE {scope} "
            "AND NOT EXISTS (SELECT 1 FROM bcm_bia_plan_links l WHERE l.bia_id = b.id) "
            f"ORDER BY b.process_name LIMIT {LIST_CAP}", alias="b")
    if total == 0:
        r.note("No business impact analysis is recorded, so coverage is not measured.")
    return {"analyses": total, "with_plan": done,
            "without_plan": None if total is None or done is None else total - done,
            "coverage_pct": None if total is None or done is None else _percent(done, total),
            "uncovered": uncovered}


def _by(r, table, column):
    got = r.rows(table, f"SELECT COALESCE({column}, 'none') AS k, COUNT(*) AS n FROM {table} WHERE {{scope}} GROUP BY {column}")
    return None if got is None else {x["k"]: x["n"] for x in got}


def _bcm_plans(r, lists=True):
    c = r.count
    out = {
        "plans": c("bcm_plans"), "by_status": _by(r, "bcm_plans", "status"),
        "activated": c("bcm_plans", "is_active_plan = 1"),
        "review_overdue": c("bcm_plans", f"next_review IS NOT NULL AND next_review != '' AND next_review < {sql_current_date()} "
                                         "AND status != 'archived'"),
        "list": None,
    }
    if lists:
        out["list"] = r.rows(
            "bcm_plans",
            "SELECT id, title, status, owner, version, last_reviewed, next_review, is_active_plan AS activated FROM bcm_plans "
            f"WHERE {{scope}} ORDER BY title LIMIT {LIST_CAP}")
    return out


def _hours(start, end):
    from datetime import datetime
    try:
        a = datetime.fromisoformat(str(start).replace("Z", "")[:19])
        b = datetime.fromisoformat(str(end).replace("Z", "")[:19])
    except (TypeError, ValueError):
        return None
    hours = (b - a).total_seconds() / 3600
    return hours if hours >= 0 else None


def _bcm_incidents(r, lists=True):
    c = r.count
    resolved = r.rows(
        "bcm_incidents",
        "SELECT COALESCE(declared_at, started_at, created_at) AS began, resolved_at FROM bcm_incidents "
        "WHERE {scope} AND resolved_at IS NOT NULL ORDER BY id DESC LIMIT 1000")
    spans = [h for h in (_hours(x["began"], x["resolved_at"]) for x in (resolved or [])) if h is not None]
    out = {
        "incidents": c("bcm_incidents"), "active": c("bcm_incidents", INCIDENT_ACTIVE),
        "by_severity": _by(r, "bcm_incidents", "severity"), "by_status": _by(r, "bcm_incidents", "status"),
        "resolved_with_times": len(spans) if resolved is not None else None,
        "average_hours_to_resolve": round(sum(spans) / len(spans), 1) if spans else None,
        "list": None,
    }
    if resolved is not None and not spans:
        r.note("No resolved incident has both a start and a resolution time, so the time to resolve is not measured.")
    if resolved is not None and len(resolved) >= 1000:
        r.note("The average time to resolve uses the 1000 most recently created resolved incidents.")
    if lists:
        out["list"] = r.rows(
            "bcm_incidents",
            "SELECT id, title, severity, status, COALESCE(declared_at, started_at, created_at) AS declared_at, resolved_at "
            f"FROM bcm_incidents WHERE {{scope}} ORDER BY id DESC LIMIT {LIST_CAP}")
    return out


def _bcm_exercises(r, lists=True):
    c = r.count
    total = c("bcm_exercises")
    done = c("bcm_exercises", EXERCISE_COMPLETED)
    scored = r.rows("bcm_exercises",
                    "SELECT effectiveness_score AS s FROM bcm_exercises WHERE {scope} AND effectiveness_score IS NOT NULL")
    out = {
        "exercises": total, "completed": done,
        "completion_pct": _percent(done, total) if total is not None and done is not None else None,
        "by_status": _by(r, "bcm_exercises", "status"),
        "closed_with_frozen_report": r.count("bcm_exercises", "status = 'closed' AND report_hash IS NOT NULL"),
        "scored": len(scored) if scored is not None else None,
        "average_effectiveness": round(sum(x["s"] for x in scored) / len(scored), 1) if scored else None,
        "list": None,
    }
    if total == 0:
        r.note("No exercise is recorded, so the completion share is not measured.")
    if lists:
        out["list"] = r.rows(
            "bcm_exercises",
            "SELECT id, title, type, status, scheduled_date, objectives_met, objectives_total, effectiveness_score "
            f"FROM bcm_exercises WHERE {{scope}} ORDER BY id DESC LIMIT {LIST_CAP}")
    return out


def _bcm_summary(r, lists=True):
    risks = r.read("bcm_risks", lambda: _bcm_risk_levels(r))
    return {"coverage": _bcm_coverage(r, lists), "plans": _bcm_plans(r, lists), "incidents": _bcm_incidents(r, lists),
            "exercises": _bcm_exercises(r, lists), "risks": risks}


def _bcm_risk_levels(r):
    scope, params = table_scope("bcm_risks", r.user)
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for row in r.db.execute(f"SELECT score FROM bcm_risks WHERE {scope} AND status != 'closed'", params).fetchall():
        score = int(row["score"] or 0)
        counts["critical" if score >= 20 else "high" if score >= 12 else "medium" if score >= 6 else "low"] += 1
    return {"open": sum(counts.values()), "by_level": counts}


def _case(r, lists=True, subject=None):
    """The connected view of one record, frozen: what is connected to it, the proof held for it and what changed."""
    from modules.governance import entity360
    subject = subject or {}
    got = entity360.get_connected(r.db, r.user, subject.get("module"), subject.get("entity_type"), subject.get("entity_id"))
    if got is None:
        raise RecordNotAvailable()
    unavailable = bool(got.get("unavailable")) or any(
        (got.get(k) or {}).get("state") == "unavailable" for k in ("proof", "changes"))
    r.custom.append(("connected_record", "The record, what is connected to it, its proof and its change signals",
                     "governance", UNAVAILABLE if unavailable else READ))
    keys = [f"{section.get('key')}/{c['entity_type']}/{c['entity_id']}"
            for section in got.get("connections") or [] for c in section.get("items") or []]
    r.extra_inputs["connected_records"] = {
        "ids": [f"{subject.get('module')}/{subject.get('entity_type')}/{subject.get('entity_id')}", *keys[:RECORD_CAP]],
        "truncated": len(keys) > RECORD_CAP}
    r.note("Only connected records the person who generated this report may open are shown. A record they cannot open is "
           "not named or counted, and a connection nobody confirmed is marked as proposed.")
    return got


BUILDERS = {
    "compliance_summary": _compliance_summary, "risk_report": _risk_report, "audit_status": _audit_status,
    "privacy_overview": _privacy_overview, "bcm_readiness": _bcm_readiness, "sla_performance": _sla_performance,
    "executive_brief": _executive_brief, "executive_summary": _executive_summary, "bcm_coverage": _bcm_coverage, "bcm_plans": _bcm_plans,
    "bcm_incidents": _bcm_incidents, "bcm_exercises": _bcm_exercises, "bcm_summary": _bcm_summary,
}

# Every table a type reads, in the order the manifest lists them.
READS = {
    "compliance_summary": ("controls", "frameworks"),
    "risk_report": ("erm_enterprise_risks", "risk_register"),
    "audit_status": ("grid_audits", "grid_non_conformances"),
    "privacy_overview": ("sentinel_ropa", "sentinel_dpias", "sentinel_breaches", "sentinel_dsr"),
    "bcm_readiness": ("bcm_plans", "bcm_incidents", "bcm_exercises"),
    "sla_performance": ("sla_instances",),
    "executive_brief": ("controls", "erm_enterprise_risks", "risk_register", "grid_audits", "sentinel_breaches", "sla_instances"),
    "executive_summary": ("controls", "erm_enterprise_risks", "risk_register", "grid_audits", "sentinel_breaches", "sentinel_dsr",
                          "bcm_incidents",
                          "bcm_plans", "task_board"),
    "bcm_coverage": ("bcm_bia_records",),
    "bcm_plans": ("bcm_plans",),
    "bcm_incidents": ("bcm_incidents",),
    "bcm_exercises": ("bcm_exercises",),
    "bcm_summary": ("bcm_bia_records", "bcm_plans", "bcm_incidents", "bcm_exercises", "bcm_risks"),
}

# The viewpoint presets: templates over the types above (section 5). `lists` is whether record level lists are included.
PRESETS = {
    "preset_specialist": {
        "label": "Specialist portfolio report",
        "purpose": "The queue, the gaps and the decisions of the modules you work in.",
        "parts": ("compliance_summary", "risk_report", "audit_status", "privacy_overview", "bcm_readiness", "sla_performance"),
        "lists": True,
        "limitations": ("Only the modules you may open are included. A module you cannot open is not shown and not counted.",)},
    "preset_management": {
        "label": "Management report",
        "purpose": "Progress, aging and bottlenecks for the units you lead.",
        "parts": ("compliance_summary", "risk_report", "audit_status", "sla_performance", "bcm_readiness"),
        "lists": True,
        "limitations": ("Trend is the change since the previous run of this report. History before the first run is not kept.",
                        "Accountable owners are listed only where the source record carries one.")},
    "preset_board": {
        "label": "Board report",
        "purpose": "Material exposure, assurance and exceptions, with what the figures cannot say.",
        "parts": ("executive_brief", "risk_report", "privacy_overview", "bcm_readiness", "audit_status"),
        "lists": False,
        "limitations": ("A percentage is a share of the records in scope. It is not an independent assurance rating.",
                        "Implemented is a status recorded in the platform. It is reviewed assurance only where an audit "
                        "is listed.",
                        "Individual records are left out of this report. Use the specialist report to see them.")},
    "preset_case": {
        "label": "Case report",
        "purpose": "What is connected to one record, the proof held for it and what changed.",
        "parts": (), "lists": True, "limitations": ()},
}

# 2026-10-22.1: the executive figures count both risk registers and shares round half up; a trend only joins runs of one version.
DEFINITION_VERSIONS = {"default": "2026-10-22.1"}
CASE_SUBJECT_KEYS = ("module", "entity_type", "entity_id")


def definition_version(report_type) -> str:
    return DEFINITION_VERSIONS.get(report_type, DEFINITION_VERSIONS["default"])


def valid_subject(parameters) -> "dict | None":
    subject = (parameters or {}).get("subject")
    if not isinstance(subject, dict):
        return None
    module, kind, rid = (subject.get(k) for k in CASE_SUBJECT_KEYS)
    if not isinstance(module, str) or not isinstance(kind, str) or isinstance(rid, bool) or not isinstance(rid, int) or rid < 1:
        return None
    return {"module": module[:40], "entity_type": kind[:40], "entity_id": rid}


def build(db, user, report_type, parameters=None) -> Built:
    """Read one report. Raises ValueError for an unknown type and RecordNotAvailable for a case whose record the person
    cannot open."""
    if report_type in {"framework_auditor_register", "ai_systems_register", "ai_risk_register"}:
        from modules.launcher import register_reports
        try:
            if report_type == "framework_auditor_register":
                framework_id = (parameters or {}).get("framework_id")
                return register_reports.framework(db, user, framework_id,
                                                  audit_id=(parameters or {}).get("audit_id"))
            if report_type == "ai_systems_register":
                return register_reports.ai_systems(db, user)
            return register_reports.ai_risks(db, user)
        except register_reports.RegisterNotAvailable:
            raise RecordNotAvailable() from None
    r = Reader(db, user)
    if report_type in BUILDERS:
        result = BUILDERS[report_type](r)
        declared = READS[report_type]
        parts = []
        limitations = []
    elif report_type in PRESETS:
        preset = PRESETS[report_type]
        parts, declared = [], []
        if report_type == "preset_case":
            subject = valid_subject(parameters)
            if subject is None:
                raise ValueError("A case report needs a record")
            result = _case(r, subject=subject)
            declared = ()
        else:
            sections = {}
            for part in preset["parts"]:
                reads = READS[part]
                closed = [t for t in reads if r.hidden(t)]
                for t in reads:
                    if t not in declared:
                        declared.append(t)
                if len(closed) == len(reads):
                    parts.append({"type": part, "state": NOT_IN_SCOPE})
                    for t in reads:
                        r._mark(t, NOT_IN_SCOPE)
                    continue
                sections[part] = BUILDERS[part](r, lists=preset["lists"])
                parts.append({"type": part, "state": READ})
            result = {"preset": report_type, "sections": sections}
        limitations = list(preset["limitations"])
    else:
        raise ValueError("Unknown report type")
    declared = tuple(declared)
    inputs = r.inputs(declared)
    manifest = r.manifest(declared)
    limitations = [*limitations, *r.notes]
    if any(item.get("revision_state") == "source_recorded" for item in inputs.values()):
        limitations.append("Source versions and change times are copied as recorded. Some source workflows do not advance "
                           "these fields on every edit, so they are not a complete change history.")
    for table, captured in inputs.items():
        if captured.get("revision_state") == "not_recorded":
            label = SOURCES.get(table, (table, ""))[0]
            limitations.append(f"{label} have no source revision field. Their permitted identifiers are frozen, but "
                               "later edits to individual records cannot be dated from this report.")
        if captured.get("truncated"):
            label = SOURCES.get(table, (table, ""))[0]
            limitations.append(f"The {label} input list is capped at {RECORD_CAP} records; its count is exact, "
                               "but the frozen identifier list is incomplete.")
    for src in manifest:
        if src["state"] == NOT_IN_SCOPE:
            limitations.append(f"{src['label']} are not included: the person who generated this report may not open them.")
        elif src["state"] == UNAVAILABLE:
            limitations.append(f"{src['label']} could not be read when this report was generated. Its figures are blank, "
                               "not zero.")
    for part in parts:
        if part["state"] == NOT_IN_SCOPE:
            limitations.append(f"The {part['type'].replace('_', ' ')} section is left out: nothing it reads is open to "
                               "the person who generated this report.")
    complete = all(s["state"] != UNAVAILABLE for s in manifest)
    exclusions = _exclusions(report_type)
    return Built(result=result, sources=manifest, inputs=inputs, limitations=limitations, exclusions=exclusions,
                 complete=complete, parts=parts)


def _exclusions(report_type) -> list:
    base = ["Records in business units the person who generated this report may not open.",
            "Records of other organizations."]
    if report_type == "bcm_summary" or report_type.startswith("bcm_"):
        base.append("Lists show at most 200 records; the counts above them are exact.")
    return base
