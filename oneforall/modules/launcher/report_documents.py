"""
The documents of the Reports page: a frozen run becomes a shared-kit report (PDF, workbook, print view).

Nothing here recomputes a figure. Every number, chart series and table row comes from the envelope that was frozen when the
run was generated (`result`), so the document, the CSV and the page cannot disagree. A chart and the table beside it are
built from the same dict in the same function.

Tier (decision D3 of PLAN_report_exports_2026-10-21.md): a board report is short, summary first and decision oriented
(headline measures, the movement, the top items, what needs a decision). An operational report carries the detail.
"""
import json
from dataclasses import dataclass, field

from core.best_effort import swallowed
from core.email import app_origin
from core.report_kit import grounding, identity, theme
from core.report_kit.helpers import (ROWS_IN_DOCUMENT, SEVERITY_COLOUR, empty as _empty, label as _label, slices as _slices)
from core.report_kit.model import (Actor, Callout, Chart, Col, Heading, Kpi, Kpis, Meta, Paragraphs, Report, Table)
from database import get_db
from modules.governance.data_service import bu_scope_ids
from modules.evidence.scope import current_library_sql, evidence_scope_sql
from modules.governance.entity_scope import canonical_key, describe_record
from modules.launcher import report_snapshot as snap

# ── What kind of report each type is ────────────────────────────────────────

BOARD_TYPES = frozenset({"executive_brief", "executive_summary", "preset_board"})

# The module a report reads from, by the navigation name; reports that span modules belong to the Command Centre.
MODULE_OF = {
    "compliance_summary": "aria", "audit_status": "grid", "privacy_overview": "sentinel", "bcm_readiness": "bcm",
    "bcm_coverage": "bcm", "bcm_plans": "bcm", "bcm_incidents": "bcm", "bcm_exercises": "bcm", "bcm_summary": "bcm",
}

STATUS_ORDER = ["Implemented", "Approved", "Under Review", "In Progress", "Partially Implemented", "Needs Update", "Draft",
                "Not Started", "Not Implemented"]


def tier_of(report_type) -> str:
    return theme.BOARD if report_type in BOARD_TYPES else theme.OPERATIONAL


# ── Small helpers ───────────────────────────────────────────────────────────

def _n(value):
    """A figure as it was frozen: a number, or None when the source could not be read. Never a zero for a missing one."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _count_kpi(label, value, note="", tone="neutral") -> Kpi:
    figure = _n(value)
    return Kpi(label, identity.fmt_int(figure), note, tone if figure else "neutral")


def _share(part, whole):
    part, whole = _n(part), _n(whole)
    return None if part is None or whole is None else identity.pct(part, whole)


# What a figure is called when a document lists a change (the last part of its path in the frozen result).
FIGURE_LABELS = {
    "controls_total": "Controls in scope", "controls_compliant": "Controls implemented", "compliance_pct": "Controls implemented (%)",
    "total_controls": "Controls in scope", "compliant": "Controls implemented", "non_compliant": "Controls not started or not implemented",
    "partial": "Controls in progress or partly implemented", "risks_critical": "Critical risks", "risks_high": "High risks",
    "risks_open": "Open risks", "total_open": "Open risks", "audits_active": "Active audits", "breaches_open": "Open breaches",
    "sla_breaches": "Breached service clocks", "dsrs_open": "Open data subject requests", "dsr_open": "Open data subject requests",
    "incidents_active": "Active incidents", "active_incidents": "Active incidents", "bcm_plans": "Continuity plans",
    "tasks_open": "Open tasks", "tasks_overdue": "Overdue tasks", "ropa_count": "Processing records", "dpia_count": "Impact assessments",
    "total_audits": "Audits recorded", "completed": "Completed", "open_ncs": "Open audit findings", "active": "Active",
    "total_tracked": "Service clocks", "breached": "Breached", "resolved": "Resolved", "plans": "Continuity plans",
    "exercises_completed": "Exercises completed", "unrated": "Risks not rated",
}


def _figure_label(path) -> str:
    parts = [p for p in str(path).split(".") if p and p != "sections"]
    if not parts:
        return "Figure"
    last = parts[-1]
    if "by_framework" in parts:
        at = parts.index("by_framework")
        if len(parts) > at + 2:
            return f"{parts[at + 1]}: " + {"total": "controls", "ok": "implemented"}.get(last, _label(last).lower())
    if len(parts) >= 2 and parts[-2].startswith("by_"):
        return f"{_label(last)} by {parts[-2][3:].replace('_', ' ')}"
    if last in FIGURE_LABELS:
        return FIGURE_LABELS[last]
    return " ".join(_label(p) for p in parts[-2:]) if len(parts) > 1 else _label(last)


def _module_label(key) -> str:
    return "No source module" if key in (None, "", "unassigned") else identity.module_name(key)


def org_name_of(db, user) -> str:
    """The name of the organization the person belongs to, or an empty string when it cannot be read."""
    try:
        row = db.execute("SELECT name FROM organizations WHERE id = %s", ((user or {}).get("org_id"),)).fetchone()
        return row["name"] if row else ""
    except Exception:
        swallowed("report scope: organization name")
        return ""


def scope_words(db, user):
    """(label, business unit ids): who a report's figures cover, in words, and the units behind the words (None: all of them).
    The Reports page and the module reports use this one sentence, so a cover never describes the scope two ways."""
    units = bu_scope_ids(user)
    if units is None:
        return "Whole organization", None
    if units == [-1]:
        return "Organization-wide records only (no business unit is assigned to this person)", []
    ids = sorted(int(u) for u in units)
    root = None
    try:
        marks = ",".join(["%s"] * len(ids))
        names = {r["id"]: r["name"] for r in db.execute(
            f"SELECT id, name FROM business_units WHERE id IN ({marks})", ids).fetchall()}
        root = names.get(user.get("business_unit_id"))
    except Exception:
        swallowed("report scope: business unit names")
    below = f" and {len(ids) - 1} unit{'s' if len(ids) > 2 else ''} below it" if len(ids) > 1 else ""
    return (root or "Own business unit") + below + ", and organization-wide records", ids


def module_meta(user, module, title, subtitle, tier, now) -> Meta:
    """The cover of a module's own report: the viewer's organization and scope, who generates it, and when."""
    db = get_db()
    try:
        scope, _ = scope_words(db, user)
        org = org_name_of(db, user)
    finally:
        db.close()
    return Meta(title=title, subtitle=subtitle, module=module, tier=tier, org_name=org, scope=scope,
                period=f"As of {identity.format_when(now)}", generated_at=now, generated_by=Actor.of_user(user))


@dataclass
class Part:
    title: str
    kpis: list = field(default_factory=list)
    charts: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    messages: list = field(default_factory=list)      # one line findings, each computed from the figures
    decisions: list = field(default_factory=list)     # what needs a decision, each triggered by a figure
    attention: list = field(default_factory=list)     # (label, count) pairs: what needs attention, for the board's one chart


def _decision(count, singular, plural_form, action):
    figure = _n(count)
    return f"{identity.plural(figure, singular, plural_form)}: {action}" if figure else None


# ── The report types ────────────────────────────────────────────────────────

def _part_compliance(res, compact) -> Part:
    total, done = _n(res.get("total_controls")), _n(res.get("compliant"))
    not_started, partial = _n(res.get("non_compliant")), _n(res.get("partial"))
    share = _share(done, total)
    part = Part("Compliance")
    other = None if None in (total, done, not_started, partial) else max(total - done - not_started - partial, 0)
    part.kpis = [
        Kpi("Controls in scope", identity.fmt_int(total)),
        Kpi("Implemented", identity.fmt_int(done), f"{share}% of controls" if share is not None else "", "good" if done else "neutral"),
        _count_kpi("Not started or not implemented", not_started, tone="bad"),
        Kpi("In progress or partly implemented", identity.fmt_int(partial)),
    ]
    if other:
        part.kpis.append(Kpi("In another state", identity.fmt_int(other), "See the status chart"))
    if share is not None:
        part.messages.append(f"{identity.fmt_int(done)} of {identity.fmt_int(total)} controls ({share}%) are implemented.")
    by_status = res.get("by_status") or {}
    # Implemented first, then the largest groups, so the states that are folded into "Other states" are the smallest.
    rows = sorted(by_status.items(), key=lambda kv: (kv[0] != "Implemented", -kv[1],
                                                     STATUS_ORDER.index(kv[0]) if kv[0] in STATUS_ORDER else len(STATUS_ORDER),
                                                     str(kv[0]).lower()))
    slices = _slices([(_label(k), v) for k, v in rows])
    status_total = sum(by_status.values()) if by_status else None
    part.charts.append(Chart(
        "donut", "Controls by status", slices, unit="controls", half=True,
        centre=f"{share}%" if share is not None else "",
        takeaway=(f"Implemented controls are {share}% of all {identity.fmt_int(status_total)} controls in scope."
                  if share is not None and status_total else ""),
        empty_text=_empty("No controls are in scope, or they could not be read.")))
    frameworks = [f for f in res.get("by_framework") or [] if _n(f.get("total"))]
    shares = sorted(((f["name"], identity.pct(f.get("ok") or 0, f["total"])) for f in frameworks), key=lambda r: (-r[1], r[0]))
    if len(shares) == 1:
        take = f"{shares[0][0]} has {shares[0][1]}% of its {identity.fmt_int(frameworks[0]['total'])} controls implemented."
    elif shares:
        take = f"Highest: {shares[0][0]} at {shares[0][1]}%. Lowest: {shares[-1][0]} at {shares[-1][1]}%."
    else:
        take = ""
    part.charts.append(Chart(
        "bar", "Implemented share by framework", shares[:8] if compact else shares, unit="%", max_value=100, half=True,
        x_label="Percent of controls implemented", y_label="Framework", takeaway=take,
        empty_text=_empty("No framework has controls in scope.")))
    if not compact and frameworks:
        stack = [(f["name"], [("Implemented", f.get("ok") or 0), ("Not yet implemented", f["total"] - (f.get("ok") or 0))])
                 for f in sorted(frameworks, key=lambda f: -f["total"])]
        left = max(frameworks, key=lambda f: f["total"] - (f.get("ok") or 0))
        part.charts.append(Chart(
            "stack", "Controls by framework: implemented and still to do", stack, x_label="Number of controls", y_label="Framework",
            takeaway=(f"{left['name']} has the most controls still to implement: {identity.fmt_int(left['total'] - (left.get('ok') or 0))}."
                      if left["total"] - (left.get("ok") or 0) else "Every control in every framework is implemented."),
            colours=[theme.GRAPHITE, theme.SILVER]))
    if not compact:
        empty = len(res.get("by_framework") or []) - len(frameworks)
        part.tables.append(Table(
            "Frameworks with controls in scope", [Col("Framework", "framework", weight=3), Col("Controls", "controls", "right", 1, "int"),
                                                  Col("Implemented", "implemented", "right", 1, "int"),
                                                  Col("Share implemented", "share", "right", 1.3, "pct")],
            [{"framework": f["name"], "controls": f.get("total"), "implemented": f.get("ok") or 0,
              "share": _share(f.get("ok") or 0, f.get("total"))} for f in sorted(frameworks, key=lambda f: f["name"])],
            note=(f"{identity.plural(empty, 'other active framework')} {'has' if empty == 1 else 'have'} no controls in scope and "
                  f"{'is' if empty == 1 else 'are'} not listed." if empty > 0 else ""),
            empty_text="No active framework has controls in scope.", sheet_name="Frameworks"))
    if not_started:
        part.decisions.append(f"{identity.plural(not_started, 'control')} not started or not implemented: agree a target date for them.")
    return part


def _risk_levels(res):
    levels = res.get("by_level") or {}
    total = _n(res.get("total_open"))
    rated = sum(levels.get(k, 0) for k in theme.SEVERITY_ORDER)
    unrated = max(total - rated, 0) if total is not None else 0
    return levels, total, unrated


def _part_risk(res, compact) -> Part:
    levels, total, unrated = _risk_levels(res)
    part = Part("Risk")
    if total is None:
        part.messages.append("Risks could not be read, so no risk figure is shown.")
        part.charts.append(Chart("bar", "Open risks by level", [], empty_text=_empty("Risks could not be read.")))
        return part
    crit, high = levels.get("critical", 0), levels.get("high", 0)
    part.kpis = [Kpi("Open risks", identity.fmt_int(total)), _count_kpi("Critical", crit, tone="bad"),
                 _count_kpi("High", high, tone="warn"), Kpi("Medium", identity.fmt_int(levels.get("medium", 0))),
                 Kpi("Low", identity.fmt_int(levels.get("low", 0)))]
    if unrated:
        part.kpis.append(Kpi("Not rated", identity.fmt_int(unrated)))
    rows = [(k.capitalize(), levels.get(k, 0)) for k in theme.SEVERITY_ORDER]
    colours = [SEVERITY_COLOUR[k] for k in theme.SEVERITY_ORDER]
    if unrated:
        rows.append(("Not rated", unrated))
        colours.append(SEVERITY_COLOUR["unrated"])
    share = identity.pct(crit + high, total) if total else None
    take = (f"{identity.fmt_int(crit + high)} of {identity.fmt_int(total)} open risks ({share}%) are critical or high."
            if share is not None else "")
    part.charts.append(Chart("bar", "Open risks by level", rows, takeaway=take, x_label="Number of open risks",
                             y_label="Risk level", unit="risks", colours=colours, half=not compact,
                             empty_text=_empty("There are no open risks.")))
    if take:
        part.messages.append(take)
    by_module = sorted(((_module_label(k), v) for k, v in (res.get("by_module") or {}).items() if v), key=lambda r: (-r[1], r[0]))
    if by_module and not compact:
        part.charts.append(Chart("bar", "Open risks by where they are recorded", by_module, half=True,
                                 x_label="Number of open risks", y_label="Register or module", unit="risks",
                                 takeaway=f"{by_module[0][0]} holds the most open risks: {identity.fmt_int(by_module[0][1])} of {identity.fmt_int(total)}."))
    top = res.get("top_risks")
    if top is not None:
        rows_t = top[:5] if compact else top
        part.tables.append(Table(
            "Highest scoring open risks", [Col("Risk", "title", weight=4), Col("Level", "level", weight=1), Col("Recorded in", "module", weight=1.6),
                                           Col("Treatment", "treatment", weight=1.3), Col("Status", "status", weight=1.2)],
            [{"title": r.get("title"), "level": _label(r.get("risk_level")), "module": _module_label(r.get("source_module")),
              "treatment": _label(r.get("treatment")) if r.get("treatment") else None, "status": _label(r.get("status"))} for r in rows_t],
            empty_text="No open risk is recorded.", sheet_name="Top risks"))
    decision = _decision(crit, "critical risk", "critical risks", "agree an owner and a treatment date for each.")
    if decision:
        part.decisions.append(decision)
    part.attention = [("Critical risks", crit), ("High risks", high)]
    return part


def _part_audit(res, compact) -> Part:
    total, active, done, findings = (_n(res.get(k)) for k in ("total_audits", "active", "completed", "open_ncs"))
    part = Part("Audit")
    part.kpis = [Kpi("Audits recorded", identity.fmt_int(total)), Kpi("Planning or active", identity.fmt_int(active)),
                 Kpi("Completed", identity.fmt_int(done)), _count_kpi("Open audit findings", findings, tone="warn")]
    by_status = res.get("by_status")
    if by_status:
        rows = [(_label(k), v) for k, v in sorted(by_status.items(), key=lambda kv: str(kv[0]))]
    elif None not in (total, active, done):
        rows = [("Planning or active", active), ("Completed", done), ("Other stages", max(total - active - done, 0))]
    else:
        rows = []
    if not compact:
        part.charts.append(Chart(
            "bar", "Audits by stage", rows, x_label="Number of audits", y_label="Audit stage", unit="audits", half=True,
            takeaway=(f"{identity.fmt_int(active)} of {identity.fmt_int(total)} audits are planned or active and "
                      f"{identity.fmt_int(done)} are complete." if None not in (total, active, done) else ""),
            empty_text=_empty("No audit is recorded, or audits could not be read.")))
    if findings:
        part.decisions.append(f"{identity.plural(findings, 'audit finding')} still open: confirm owners and due dates.")
    part.attention = [("Open audit findings", findings)] if findings is not None else []
    return part


def _part_privacy(res, compact) -> Part:
    ropa, dpia, breaches, dsr = (_n(res.get(k)) for k in ("ropa_count", "dpia_count", "breaches_open", "dsr_open"))
    part = Part("Privacy")
    part.kpis = [Kpi("Processing records", identity.fmt_int(ropa)), Kpi("Impact assessments", identity.fmt_int(dpia)),
                 _count_kpi("Open breaches", breaches, tone="bad"), _count_kpi("Open data subject requests", dsr, tone="warn")]
    open_rows = [(k, v) for k, v in (("Open breaches", breaches), ("Open data subject requests", dsr)) if v is not None]
    held_rows = [(k, v) for k, v in (("Processing records", ropa), ("Impact assessments", dpia)) if v is not None]
    if not compact:
        part.charts.append(Chart("bar", "Privacy items open now", open_rows, x_label="Number of items", y_label="Item", unit="items", half=True,
                                 takeaway=(f"{identity.plural(breaches, 'breach', 'breaches')} and "
                                           f"{identity.plural(dsr, 'data subject request')} are open." if None not in (breaches, dsr) else ""),
                                 empty_text=_empty("No open privacy item.")))
        part.charts.append(Chart("bar", "Privacy records held", held_rows, x_label="Number of records", y_label="Register", unit="records",
                                 half=True, takeaway=(f"{identity.fmt_int(ropa)} processing records and {identity.fmt_int(dpia)} impact "
                                                      "assessments are on file." if None not in (ropa, dpia) else ""),
                                 empty_text=_empty("No privacy record is held.")))
    if breaches:
        part.decisions.append(f"{identity.plural(breaches, 'open breach', 'open breaches')}: confirm the notification position and who leads.")
    if dsr:
        part.decisions.append(f"{identity.plural(dsr, 'data subject request')} waiting: confirm the response deadline is met.")
    part.attention = [(k, v) for k, v in (("Open breaches", breaches), ("Open data subject requests", dsr)) if v is not None]
    return part


def _part_bcm_readiness(res, compact) -> Part:
    plans, incidents, exercises = (_n(res.get(k)) for k in ("plans", "active_incidents", "exercises_completed"))
    part = Part("Continuity readiness")
    part.kpis = [Kpi("Continuity plans", identity.fmt_int(plans)), _count_kpi("Active incidents", incidents, tone="bad"),
                 Kpi("Exercises completed", identity.fmt_int(exercises))]
    rows = [(k, v) for k, v in (("Continuity plans", plans), ("Active incidents", incidents), ("Exercises completed", exercises)) if v is not None]
    if not compact:
        part.charts.append(Chart("bar", "Continuity records in scope", rows, x_label="Number of records", y_label="Record", unit="records",
                                 half=True, takeaway=(f"{identity.plural(plans, 'plan')} {'is' if plans == 1 else 'are'} held, "
                                                      f"{identity.plural(incidents, 'incident')} {'is' if incidents == 1 else 'are'} active and "
                                                      f"{identity.plural(exercises, 'exercise')} {'is' if exercises == 1 else 'are'} complete."
                                                      if None not in (plans, incidents, exercises) else ""),
                                 empty_text=_empty("No continuity record is in scope.")))
    if incidents:
        part.decisions.append(f"{identity.plural(incidents, 'active incident')}: note the response in hand and who leads it.")
    part.attention = [("Active incidents", incidents)] if incidents is not None else []
    return part


def _part_sla(res, compact) -> Part:
    total, active, breached, resolved = (_n(res.get(k)) for k in ("total_tracked", "active", "breached", "resolved"))
    part = Part("Service clocks")
    part.kpis = [Kpi("Service clocks", identity.fmt_int(total)), Kpi("Active", identity.fmt_int(active)),
                 _count_kpi("Breached", breached, tone="bad"), Kpi("Resolved", identity.fmt_int(resolved))]
    by_status = res.get("by_status")
    if by_status:
        rows = [(_label(k), v) for k, v in sorted(by_status.items(), key=lambda kv: str(kv[0]))]
    elif None not in (total, active, resolved):
        rows = [("Active", active), ("Resolved", resolved), ("Other states", max(total - active - resolved, 0))]
    else:
        rows = []
    if not compact:
        part.charts.append(Chart("donut", "Service clocks by state", _slices(rows), unit="clocks", half=True,
                                 centre=identity.fmt_int(total) if total is not None else "",
                                 takeaway=(f"{identity.fmt_int(active)} of {identity.fmt_int(total)} clocks are running."
                                           if None not in (active, total) else ""),
                                 empty_text=_empty("No service clock is tracked.")))
        if None not in (total, breached) and total:
            share = identity.pct(breached, total)
            part.charts.append(Chart("stack", "Clocks that breached their deadline",
                                     [("All clocks", [("Breached", breached), ("Not breached", max(total - breached, 0))])], half=True,
                                     x_label="Number of clocks", unit="clocks", colours=[theme.GRAPHITE, theme.SILVER],
                                     takeaway=f"{identity.fmt_int(breached)} of {identity.fmt_int(total)} clocks ({share}%) breached."))
    if breached:
        part.decisions.append(f"{identity.plural(breached, 'service clock')} breached: review whether the cause is being fixed.")
    part.attention = [("Breached service clocks", breached)] if breached is not None else []
    return part


def _part_brief(res, compact) -> Part:
    total, done = _n(res.get("controls_total")), _n(res.get("controls_compliant"))
    share = _share(done, total)
    crit, high, audits, breaches, sla = (_n(res.get(k)) for k in
                                         ("risks_critical", "risks_high", "audits_active", "breaches_open", "sla_breaches"))
    part = Part("Executive brief")
    part.kpis = [Kpi("Controls implemented", f"{share}%" if share is not None else "n/a",
                     f"{identity.fmt_int(done)} of {identity.fmt_int(total)} controls", "neutral"),
                 _count_kpi("Critical risks", crit, tone="bad"), _count_kpi("High risks", high, tone="warn"),
                 Kpi("Active audits", identity.fmt_int(audits)), _count_kpi("Open breaches", breaches, tone="bad"),
                 _count_kpi("Breached service clocks", sla, "active and past their deadline", tone="bad")]
    if share is not None:
        part.messages.append(f"{identity.fmt_int(done)} of {identity.fmt_int(total)} controls ({share}%) are implemented.")
    if None not in (crit, high):
        part.messages.append(f"{identity.plural(crit, 'risk')} {'is' if crit == 1 else 'are'} critical and {identity.fmt_int(high)} high.")
    if None not in (total, done) and total:
        part.charts.append(Chart("donut", "Controls implemented", [("Implemented", done), ("Not yet implemented", max(total - done, 0))],
                                 unit="controls", half=True, centre=f"{share}%",
                                 takeaway=f"{identity.fmt_int(done)} of {identity.fmt_int(total)} controls are implemented.",
                                 colours=[theme.GRAPHITE, theme.SILVER]))
    else:
        part.charts.append(Chart("donut", "Controls implemented", [], half=True, empty_text=_empty("No controls are in scope.")))
    attention = [(k, v) for k, v in (("Critical risks", crit), ("High risks", high), ("Open breaches", breaches),
                                     ("Breached service clocks", sla)) if v is not None]
    part.attention = attention
    part.charts.append(Chart("bar", "Items that need attention", attention, x_label="Number of items", y_label="Item", unit="items",
                             half=True, takeaway=(f"{identity.fmt_int(sum(v for _, v in attention))} items across risks, breaches and "
                                                  "service clocks need attention." if attention else ""),
                             empty_text=_empty("Nothing needs attention.")))
    for text in (_decision(crit, "critical risk", "critical risks", "agree an owner and a treatment date for each."),
                 _decision(breaches, "open breach", "open breaches", "confirm the notification position and who leads."),
                 _decision(sla, "breached service clock", "breached service clocks", "review whether the cause is being fixed.")):
        if text:
            part.decisions.append(text)
    return part


def _part_summary(res, compact) -> Part:
    pct_ = _n(res.get("compliance_pct"))
    total, done = _n(res.get("controls_total")), _n(res.get("controls_compliant"))
    risks, crit, audits, breaches, dsrs, incidents, tasks_open, overdue = (
        _n(res.get(k)) for k in ("risks_open", "risks_critical", "audits_active", "breaches_open", "dsrs_open",
                                 "incidents_active", "tasks_open", "tasks_overdue"))
    part = Part("Executive summary")
    part.kpis = [Kpi("Controls implemented", f"{pct_}%" if pct_ is not None else "n/a",
                     f"{identity.fmt_int(done)} of {identity.fmt_int(total)} controls"),
                 Kpi("Open risks", identity.fmt_int(risks)), _count_kpi("Critical risks", crit, tone="bad"),
                 Kpi("Active audits", identity.fmt_int(audits)), _count_kpi("Open breaches", breaches, tone="bad"),
                 _count_kpi("Open data subject requests", dsrs, tone="warn"), _count_kpi("Active incidents", incidents, tone="bad"),
                 _count_kpi("Overdue tasks", overdue, f"of {identity.fmt_int(tasks_open)} open tasks" if tasks_open is not None else "",
                            tone="warn")]
    if pct_ is not None:
        part.messages.append(f"{identity.fmt_int(done)} of {identity.fmt_int(total)} controls ({pct_}%) are implemented.")
    if None not in (risks, crit):
        part.messages.append(f"{identity.plural(risks, 'risk')} {'is' if risks == 1 else 'are'} open and {identity.fmt_int(crit)} "
                             f"{'is' if crit == 1 else 'are'} critical.")
    if None not in (total, done) and total:
        part.charts.append(Chart("donut", "Controls implemented", [("Implemented", done), ("Not yet implemented", max(total - done, 0))],
                                 unit="controls", half=True, centre=f"{pct_}%" if pct_ is not None else "",
                                 takeaway=f"{identity.fmt_int(done)} of {identity.fmt_int(total)} controls are implemented.",
                                 colours=[theme.GRAPHITE, theme.SILVER]))
    else:
        part.charts.append(Chart("donut", "Controls implemented", [], half=True, empty_text=_empty("No controls are in scope.")))
    attention = [(k, v) for k, v in (("Critical risks", crit), ("Open breaches", breaches), ("Open data subject requests", dsrs),
                                     ("Active incidents", incidents), ("Overdue tasks", overdue)) if v is not None]
    part.attention = attention
    part.charts.append(Chart("bar", "Items that need attention", attention, x_label="Number of items", y_label="Item", unit="items",
                             half=True, takeaway=(f"{identity.fmt_int(sum(v for _, v in attention))} items need attention across "
                                                  "risks, privacy, continuity and tasks." if attention else ""),
                             empty_text=_empty("Nothing needs attention.")))
    for text in (_decision(crit, "critical risk", "critical risks", "agree an owner and a treatment date for each."),
                 _decision(breaches, "open breach", "open breaches", "confirm the notification position and who leads."),
                 _decision(incidents, "active incident", "active incidents", "note the response in hand and who leads it."),
                 _decision(overdue, "overdue task", "overdue tasks", "ask the owners to clear or re-plan them.")):
        if text:
            part.decisions.append(text)
    return part


def _part_bcm_coverage(res, compact) -> Part:
    total, covered, without = (_n(res.get(k)) for k in ("analyses", "with_plan", "without_plan"))
    cov = _n(res.get("coverage_pct"))
    part = Part("Analysis coverage")
    part.kpis = [Kpi("Business impact analyses", identity.fmt_int(total)), Kpi("With a continuity plan", identity.fmt_int(covered)),
                 _count_kpi("Without a plan", without, tone="bad"), Kpi("Coverage", f"{cov}%" if cov is not None else "n/a")]
    rows = [("With a plan", covered), ("Without a plan", without)] if None not in (covered, without) else []
    part.charts.append(Chart("donut", "Analyses with a continuity plan", _slices(rows), unit="analyses", half=True,
                             centre=f"{cov}%" if cov is not None else "", colours=[theme.GRAPHITE, theme.SILVER],
                             takeaway=(f"{identity.fmt_int(covered)} of {identity.fmt_int(total)} analyses ({cov}%) have a plan."
                                       if cov is not None else ""), empty_text=_empty("No business impact analysis is recorded.")))
    uncovered = res.get("uncovered")
    if uncovered is not None:
        part.tables.append(Table(
            "Analyses with no continuity plan", [Col("Process", "name", weight=4), Col("Criticality", "criticality", weight=1.2),
                                                 Col("RTO (hours)", "rto_hours", "right", 1.1, "number")],
            [{"name": r.get("name"), "criticality": _label(r.get("criticality")) if r.get("criticality") else None,
              "rto_hours": r.get("rto_hours")} for r in uncovered],
            max_rows=ROWS_IN_DOCUMENT, more_in_excel=True, empty_text="Every analysis has a plan.", sheet_name="No plan"))
    if without:
        part.decisions.append(f"{identity.plural(without, 'business impact analysis', 'business impact analyses')} with no continuity plan: "
                              "assign an owner to write one.")
    return part


def _part_bcm_plans(res, compact) -> Part:
    plans, activated, overdue = (_n(res.get(k)) for k in ("plans", "activated", "review_overdue"))
    part = Part("Continuity plans")
    part.kpis = [Kpi("Plans", identity.fmt_int(plans)), Kpi("Activated", identity.fmt_int(activated)),
                 _count_kpi("Review overdue", overdue, tone="warn")]
    rows = [(_label(k), v) for k, v in sorted((res.get("by_status") or {}).items(), key=lambda kv: str(kv[0]))]
    part.charts.append(Chart("donut", "Plans by status", _slices(rows), unit="plans", half=True, centre=identity.fmt_int(plans) if plans is not None else "",
                             takeaway=(f"{identity.fmt_int(overdue)} of {identity.fmt_int(plans)} plans are past their review date."
                                       if None not in (overdue, plans) else ""), empty_text=_empty("No continuity plan is recorded.")))
    listing = res.get("list")
    if listing is not None:
        part.tables.append(Table(
            "Continuity plans", [Col("Plan", "title", weight=3.5), Col("Status", "status", weight=1.2), Col("Owner", "owner", weight=1.6),
                                 Col("Version", "version", weight=0.9), Col("Last reviewed", "last_reviewed", weight=1.3, kind="date"),
                                 Col("Next review", "next_review", weight=1.3, kind="date"), Col("Activated", "activated", "center", 1)],
            [{**r, "status": _label(r.get("status")), "activated": "Yes" if r.get("activated") else "No"} for r in listing],
            max_rows=ROWS_IN_DOCUMENT, more_in_excel=True, sheet_name="Plans"))
    if overdue:
        part.decisions.append(f"{identity.plural(overdue, 'plan')} past the review date: agree when each will be reviewed.")
    return part


def _part_bcm_incidents(res, compact) -> Part:
    incidents, active, with_times = (_n(res.get(k)) for k in ("incidents", "active", "resolved_with_times"))
    hours = _n(res.get("average_hours_to_resolve"))
    part = Part("Incidents")
    part.kpis = [Kpi("Incidents", identity.fmt_int(incidents)), _count_kpi("Active", active, tone="bad"),
                 Kpi("Average hours to resolve", identity.fmt_number(hours) if hours is not None else "n/a",
                     f"from {identity.fmt_int(with_times)} resolved incidents with times" if with_times else "no resolved incident has both times")]
    severity = res.get("by_severity") or {}
    rows = [(_label(k), v) for k, v in sorted(severity.items(), key=lambda kv: (theme.SEVERITY_ORDER.index(str(kv[0]).lower())
                                                                              if str(kv[0]).lower() in theme.SEVERITY_ORDER else 9, str(kv[0])))]
    colours = [SEVERITY_COLOUR.get(label.lower(), theme.SILVER_LIGHT) for label, _ in rows]
    part.charts.append(Chart("bar", "Incidents by severity", rows, x_label="Number of incidents", y_label="Severity", unit="incidents",
                             colours=colours, half=True,
                             takeaway=(f"{identity.fmt_int(active)} of {identity.fmt_int(incidents)} incidents are still active."
                                       if None not in (active, incidents) else ""), empty_text=_empty("No incident is recorded.")))
    by_status = sorted(((_label(k), v) for k, v in (res.get("by_status") or {}).items()), key=lambda r: (-r[1], r[0]))
    part.charts.append(Chart("bar", "Incidents by status", by_status, x_label="Number of incidents", y_label="Status", unit="incidents", half=True,
                             empty_text=_empty("No incident is recorded.")))
    listing = res.get("list")
    if listing is not None:
        part.tables.append(Table(
            "Incidents, newest first", [Col("Incident", "title", weight=3.5), Col("Severity", "severity", weight=1), Col("Status", "status", weight=1.1),
                                        Col("Declared", "declared_at", weight=1.4, kind="date"), Col("Resolved", "resolved_at", weight=1.4, kind="date")],
            [{**r, "severity": _label(r.get("severity")), "status": _label(r.get("status"))} for r in listing],
            max_rows=ROWS_IN_DOCUMENT, more_in_excel=True, sheet_name="Incidents"))
    if active:
        part.decisions.append(f"{identity.plural(active, 'active incident')}: note the response in hand and who leads it.")
    return part


def _part_bcm_exercises(res, compact) -> Part:
    total, done = _n(res.get("exercises")), _n(res.get("completed"))
    completion, score, scored = _n(res.get("completion_pct")), _n(res.get("average_effectiveness")), _n(res.get("scored"))
    part = Part("Exercises")
    part.kpis = [Kpi("Exercises", identity.fmt_int(total)), Kpi("Completed", identity.fmt_int(done)),
                 Kpi("Completion", f"{completion}%" if completion is not None else "n/a"),
                 Kpi("Average effectiveness", identity.fmt_number(score) if score is not None else "n/a",
                     f"from {identity.fmt_int(scored)} scored exercises" if scored else "no exercise is scored")]
    rows = sorted(((_label(k), v) for k, v in (res.get("by_status") or {}).items()), key=lambda r: (-r[1], r[0]))
    part.charts.append(Chart("bar", "Exercises by status", rows, x_label="Number of exercises", y_label="Status", unit="exercises", half=True,
                             takeaway=(f"{identity.fmt_int(done)} of {identity.fmt_int(total)} exercises ({completion}%) are completed, "
                                       "awaiting review or closed." if completion is not None else ""),
                             empty_text=_empty("No exercise is recorded.")))
    listing = res.get("list")
    if listing is not None:
        part.tables.append(Table(
            "Exercises, newest first", [Col("Exercise", "title", weight=3), Col("Type", "type", weight=1.1), Col("Status", "status", weight=1.2),
                                        Col("Scheduled", "scheduled_date", weight=1.3, kind="date"), Col("Objectives met", "objectives", "right", 1.2),
                                        Col("Effectiveness", "effectiveness_score", "right", 1.2, "number")],
            [{**r, "type": _label(r.get("type")) if r.get("type") else None, "status": _label(r.get("status")),
              "objectives": (f"{identity.fmt_int(r.get('objectives_met'))} of {identity.fmt_int(r.get('objectives_total'))}"
                             if r.get("objectives_total") is not None else None)} for r in listing],
            max_rows=ROWS_IN_DOCUMENT, more_in_excel=True, sheet_name="Exercises"))
    return part


def _part_bcm_summary(res, compact) -> list:
    parts = [_part_bcm_coverage(res.get("coverage") or {}, compact), _part_bcm_plans(res.get("plans") or {}, compact),
             _part_bcm_incidents(res.get("incidents") or {}, compact), _part_bcm_exercises(res.get("exercises") or {}, compact)]
    risks = res.get("risks")
    part = Part("Continuity risks")
    if risks is None:
        part.messages.append("Continuity risks could not be read.")
    else:
        levels = risks.get("by_level") or {}
        part.kpis = [Kpi("Open continuity risks", identity.fmt_int(risks.get("open"))), _count_kpi("Critical", levels.get("critical"), tone="bad"),
                     _count_kpi("High", levels.get("high"), tone="warn")]
        rows = [(k.capitalize(), levels.get(k, 0)) for k in theme.SEVERITY_ORDER]
        part.charts.append(Chart("bar", "Open continuity risks by level", rows, x_label="Number of open risks", y_label="Risk level", unit="risks",
                                 colours=[SEVERITY_COLOUR[k] for k in theme.SEVERITY_ORDER], half=True,
                                 takeaway=(f"{identity.fmt_int((levels.get('critical') or 0) + (levels.get('high') or 0))} of "
                                           f"{identity.fmt_int(risks.get('open'))} open continuity risks are critical or high."),
                                 empty_text=_empty("There are no open continuity risks.")))
    return parts + [part]


def _part_case(res, compact) -> list:
    """The connected view of one record: who and what it is, what is connected to it, the proof held, what changed."""
    entity = res.get("entity") or {}
    head = Part(f"{entity.get('kind_label') or 'Record'}: {entity.get('title') or ''}")
    sections = res.get("connections") or []
    proof = res.get("proof") or {}
    counts = proof.get("counts") or {}
    connected = sum(len(s.get("items") or []) for s in sections)
    head.kpis = [Kpi("Connected records", identity.fmt_int(connected)), Kpi("Files held as proof", identity.fmt_int(counts.get("files"))),
                 Kpi("Proof accepted", identity.fmt_int(counts.get("accepted"))),
                 Kpi("Changes to look at", identity.fmt_int(len((res.get("changes") or {}).get("items") or [])))]
    by_module = [(s.get("title"), len(s.get("items") or [])) for s in sections if s.get("items")]
    head.charts.append(Chart("bar", "Connected records by module", by_module, x_label="Number of connected records", y_label="Module",
                             unit="records", half=True, empty_text=_empty("Nothing is connected to this record."),
                             takeaway=(f"{identity.fmt_int(connected)} records are connected, most of them in {max(by_module, key=lambda r: r[1])[0]}."
                                       if by_module else "")))
    items = proof.get("items") or []
    if items:
        states = {}
        for item in items:
            states[item.get("state") or "Not stated"] = states.get(item.get("state") or "Not stated", 0) + 1
        head.charts.append(Chart("donut", "Proof held for this record, by state", _slices(sorted(states.items(), key=lambda kv: (-kv[1], kv[0]))),
                                 unit="files", half=True, centre=identity.fmt_int(len(items)),
                                 takeaway=f"{identity.fmt_int(counts.get('accepted'))} of {identity.fmt_int(len(items))} files are accepted proof."))
    head.tables.append(Table(
        "What is connected", [Col("Module", "module", weight=1.4), Col("Kind", "kind", weight=1.4), Col("Record", "title", weight=3.4),
                              Col("Relationship", "relationship", weight=1.6), Col("State", "state", weight=1.1)],
        [{"module": s.get("title"), "kind": i.get("kind_label"), "title": i.get("title"), "relationship": i.get("relationship"),
          "state": "Confirmed" if i.get("confirmed") else _label(i.get("state") or "proposed")}
         for s in sections for i in s.get("items") or []],
        max_rows=ROWS_IN_DOCUMENT, more_in_excel=True, empty_text="Nothing is connected to this record.", sheet_name="Connected"))
    if items:
        head.tables.append(Table(
            "Proof held in the Evidence Vault", [Col("File", "title", weight=3.5, link="vault_url"), Col("Version", "version", "right", 0.8), Col("State", "state", weight=1.6),
                                                 Col("Expires", "expiry_date", weight=1.2, kind="date")],
            items, max_rows=ROWS_IN_DOCUMENT, more_in_excel=True, sheet_name="Proof"))
    changes = (res.get("changes") or {}).get("items") or []
    if changes:
        head.tables.append(Table("Changes to look at", [Col("Change", "text", weight=4)],
                                 [{"text": c.get("text") or c.get("title") or c.get("label") or str(c)} for c in changes],
                                 max_rows=ROWS_IN_DOCUMENT, sheet_name="Changes"))
    return [head]


PART_BUILDERS = {
    "compliance_summary": _part_compliance, "risk_report": _part_risk, "audit_status": _part_audit,
    "privacy_overview": _part_privacy, "bcm_readiness": _part_bcm_readiness, "sla_performance": _part_sla,
    "executive_brief": _part_brief, "executive_summary": _part_summary, "bcm_coverage": _part_bcm_coverage,
    "bcm_plans": _part_bcm_plans, "bcm_incidents": _part_bcm_incidents, "bcm_exercises": _part_bcm_exercises,
}
COMPOSITE_BUILDERS = {"bcm_summary": _part_bcm_summary, "preset_case": _part_case}


# ── Trend over saved runs ───────────────────────────────────────────────────

def _brief_controls_pct(r):
    return _share(r.get("controls_compliant"), r.get("controls_total"))


def _board_critical(r):
    return _n((((r.get("sections") or {}).get("risk_report") or {}).get("by_level") or {}).get("critical"))


TRENDS = {
    "executive_brief": [("Controls implemented over saved runs", "%", _brief_controls_pct),
                        ("Critical risks over saved runs", "risks", lambda r: _n(r.get("risks_critical")))],
    "executive_summary": [("Controls implemented over saved runs", "%", lambda r: _n(r.get("compliance_pct"))),
                          ("Critical risks over saved runs", "risks", lambda r: _n(r.get("risks_critical")))],
    "preset_board": [("Controls implemented over saved runs", "%",
                      lambda r: _brief_controls_pct((r.get("sections") or {}).get("executive_brief") or {})),
                     ("Critical risks over saved runs", "risks", _board_critical)],
}


def _trend_points(db, row, env, report_type):
    """[(title, unit, [(label, value)])] read from this person's earlier frozen runs of the same definition, the same scope
    and the same definition version. Nothing is recomputed, and no run after this one is used. None when it cannot be read."""
    if not db or not row or report_type not in TRENDS:
        return None
    try:
        rows = db.execute(
            "SELECT id, result_json, snapshot_hash FROM report_runs WHERE definition_id = %s AND status = 'completed' "
            "AND snapshot_hash IS NOT NULL AND triggered_by = %s AND id <= %s ORDER BY id DESC LIMIT 12",
            (row["definition_id"], row["triggered_by"], row["id"])).fetchall()
    except Exception:
        swallowed("report document: earlier runs for the trend")
        return None
    fingerprint = (env.get("scope") or {}).get("fingerprint")
    version = (env.get("run") or {}).get("definition_version")
    frozen_runs = []
    for item in reversed(rows):
        if not snap.intact(item["result_json"], item["snapshot_hash"]):
            continue
        frozen = json.loads(item["result_json"])
        if (frozen.get("scope") or {}).get("fingerprint") == fingerprint and (frozen.get("run") or {}).get("definition_version") == version:
            frozen_runs.append(frozen)
    stamps = [identity.to_utc((f.get("run") or {}).get("generated_at")) for f in frozen_runs]
    plain = [f"{s.day} {s.strftime('%b')}" if s else "?" for s in stamps]
    labels = plain if len(set(plain)) == len(plain) else [f"{s.day} {s.strftime('%b %H:%M')}" if s else "?" for s in stamps]
    series = []
    for title, unit, pick in TRENDS[report_type]:
        points = [(label, value) for label, frozen in zip(labels, frozen_runs)
                  for value in [pick(frozen.get("result") or {})] if value is not None]
        series.append((title, unit, points))
    return series


def _trend_blocks(series) -> list:
    blocks = [Heading("Movement over time", "Each point is a figure frozen in a saved run of this report, for the same scope.")]
    if not series or all(len(points) < 2 for _, _, points in series):
        saved = max((len(points) for _, _, points in series or []), default=0)
        blocks.append(Chart("line", "Trend", [], empty_text=(
            f"A trend needs at least two saved runs of this report ({identity.fmt_int(saved)} so far). Run it again later and the "
            "movement appears here.")))
        return blocks
    for title, unit, points in series:
        if len(points) < 2:
            blocks.append(Chart("line", title, [], half=True, empty_text="A trend needs at least two saved runs with this figure."))
            continue
        first, last = points[0], points[-1]
        change = last[1] - first[1]
        suffix = "%" if unit == "%" else ""
        words = ("unchanged" if change == 0 else
                 f"{'up' if change > 0 else 'down'} {identity.fmt_int(abs(change))}{' points' if unit == '%' else ''}")
        blocks.append(Chart(
            "line", title, points, unit="%" if unit == "%" else "", y_label="Percent" if unit == "%" else "Number of risks",
            x_label="Run date", half=True, max_value=100 if unit == "%" else None,
            takeaway=f"From {first[0]} to {last[0]} the figure is {words} ({identity.fmt_int(first[1])}{suffix} to {identity.fmt_int(last[1])}{suffix})."))
    return blocks


# ── Narrative, review status and basis ──────────────────────────────────────

def narrative_check(env):
    """The grounding result of the draft narrative of a run (every number in it looked up in the run's figures), or None when
    the run has no narrative."""
    narrative = env.get("narrative")
    if not narrative or not str(narrative.get("text") or "").strip():
        return None
    when = identity.to_utc((env.get("run") or {}).get("generated_at"))
    extra = [] if when is None else [when.day, when.month, when.year]
    return grounding.check(narrative["text"], env.get("result"), extra)


def _narrative_blocks(env) -> list:
    check = narrative_check(env)
    if check is None:
        return []
    narrative = env["narrative"]
    who = f" by {narrative.get('model')}" if narrative.get("model") else ""
    if not check.ok:
        return [Callout("Draft narrative left out", [
            f"A draft narrative was written{who}, but it is not printed here. {check.sentence()}",
            "The figures in this report are the saved figures. Read the draft on screen, correct it, and have a person review it "
            "before it is circulated."], "limit")]
    return [Paragraphs("Draft narrative", [p for p in str(narrative["text"]).split("\n\n") if p.strip()],
                       label=f"Written{who}, not reviewed. It describes the figures of this run only. {check.sentence()}")]


def _review_line(db, run_id, env) -> str:
    status = (env.get("decision_status") or {}).get("text") or ""
    if not db or run_id is None:
        return status
    try:
        last = db.execute(
            "SELECT s.decision, s.reason, s.signed_at, u.full_name, u.username FROM report_run_signoffs s "
            "LEFT JOIN users u ON u.id = s.signer_id WHERE s.run_id = %s ORDER BY s.id DESC LIMIT 1", (run_id,)).fetchone()
    except Exception:
        swallowed("report document: the sign off line")
        return status
    if not last:
        return status
    who = last["full_name"] or last["username"] or "a reviewer"
    return (f"Independent review: {last['decision']} by {who} on {identity.format_day(last['signed_at'])}. "
            f"Reason recorded: {identity.clean_text(last['reason'], keep_newlines=False)}")


def _figure(value) -> str:
    if value is None:
        return "n/a"
    return identity.fmt_int(value) if float(value) == int(value) else identity.fmt_number(value, 1)


SOURCE_STATE = {"read": "Read", "not_in_scope": "Not open to the person who generated it", "unavailable": "Could not be read"}


def _basis_blocks(env, db, run_id, row, tier) -> list:
    sources = [{"source": s.get("label"), "state": SOURCE_STATE.get(s.get("state"), s.get("state")), "records": s.get("records")}
               for s in env.get("sources") or []]
    limits = list(env.get("limitations") or []) + ["Left out: " + e for e in env.get("exclusions") or []]
    basis = [(env.get("period") or {}).get("note") or "Every figure is read at the moment the report is generated.",
             "Complete: every source was read." if env.get("complete") else
             "Not complete: a source could not be read, so its figures are n/a, never zero.",
             _review_line(db, run_id, env)]
    if row and row.get("snapshot_hash"):
        basis.append(f"Saved as generated. Integrity check (SHA-256): {row['snapshot_hash']}")
    blocks = [Heading("Basis and limits")]
    changes = env.get("changes")
    if changes:
        head = (f"Since run {changes.get('previous_run_id')}: {identity.fmt_int(changes.get('changed'))} figure(s) changed and "
                f"{identity.fmt_int(changes.get('unchanged'))} did not.")
        if changes.get("scope_changed"):
            head += " The scope is not the same as then."
        if changes.get("definition_changed"):
            head += " The report definition has changed."
        moved = [{"label": _figure_label(c.get("path")), "was": _figure(c.get("was")), "now": _figure(c.get("now")),
                  "delta": _figure(c.get("delta")) if c.get("delta") is not None else "n/a"}
                 for c in (changes.get("changes") or [])[: (8 if tier == theme.BOARD else 25)]]
        blocks.append(Table("Movement since the previous run", [Col("Figure", "label", weight=4), Col("Was", "was", "right", 1),
                                                                 Col("Now", "now", "right", 1), Col("Change", "delta", "right", 1)],
                            moved, note=head, empty_text=head, sheet_name="Movement"))
    blocks.append(Callout("How to read this report", [b for b in basis if b], "note"))
    if limits:
        blocks.append(Callout("What this report cannot tell you", limits, "limit"))
    if tier == theme.OPERATIONAL and sources:
        blocks.append(Table("Sources read", [Col("Source", "source", weight=3), Col("What happened", "state", weight=3),
                                             Col("Records", "records", "right", 1, "int")], sources, sheet_name="Sources"))
    return blocks


# ── The document ────────────────────────────────────────────────────────────

# The eight tiles of the board preset, picked by label from its parts: one figure of each kind, risk figures from the risk
# report (which reads both registers) and never from the brief.
BOARD_PRESET_TILES = ["Controls implemented", "Open risks", "Critical", "Open breaches", "Open data subject requests",
                      "Active incidents", "Active audits", "Open audit findings"]
COMPOSITE_PRESETS = ("preset_specialist", "preset_management", "preset_case", "bcm_summary")


def _parts_for(env, compact) -> list:
    report_type = (env.get("run") or {}).get("report_type")
    result = env.get("result") or {}
    if report_type in PART_BUILDERS:
        return [PART_BUILDERS[report_type](result, compact)]
    if report_type in COMPOSITE_BUILDERS:
        return COMPOSITE_BUILDERS[report_type](result, compact)
    if str(report_type).startswith("preset_"):
        from modules.launcher import report_builders
        order = list(report_builders.PRESETS.get(report_type, {}).get("parts") or ())
        sections = result.get("sections") or {}
        return [PART_BUILDERS[name](sections[name], compact) for name in order if name in sections and name in PART_BUILDERS]
    return []


def _meta(env, report_type, run_id, viewer, db, exported_at) -> Meta:
    run, scope = env.get("run") or {}, env.get("scope") or {}
    by = run.get("generated_by") or {}
    username = by.get("username") or ""
    if not username and by.get("id") and db:
        try:
            found = db.execute("SELECT username FROM users WHERE id = %s", (by["id"],)).fetchone()
            username = found["username"] if found else ""
        except Exception:
            swallowed("report document: the generator's username")
            username = ""
    tier = tier_of(report_type)
    module = MODULE_OF.get(report_type, "platform")
    if report_type == "preset_case":
        module = ((env.get("result") or {}).get("entity") or {}).get("module") or "platform"
    label = run.get("type_label")
    return Meta(
        title=str(run.get("definition_name") or label or "Report"),
        subtitle=(f"{label}. " if label and label != run.get("definition_name") else "") + theme.TIERS[tier]["meaning"],
        module=module, tier=tier, org_name=scope.get("org_name") or "", scope=scope.get("label") or "",
        period=f"As of {identity.format_when(run.get('generated_at'))}", generated_at=run.get("generated_at"),
        generated_by=Actor(name=by.get("name") or username or "Unknown user", username=username),
        reference=f"Run {run_id}" if run_id else "",
        exported_by=Actor.of_user(viewer) if viewer else None, exported_at=exported_at if viewer else None)


def _case_vault_addresses(env, parts, db, viewer):
    """Link frozen proof rows only when the current viewer can still open them."""
    entity = (env.get("result") or {}).get("entity") or {}
    try:
        key = canonical_key(entity.get("module"), entity.get("entity_type"))
        record_id = int(entity.get("entity_id"))
    except (TypeError, ValueError):
        return False
    if not describe_record(db, key, record_id, viewer):
        return False
    origin = app_origin()
    for part in parts:
        for table in part.tables:
            if table.title != "Proof held in the Evidence Vault":
                continue
            ids = sorted({item["id"] for item in table.rows if type(item.get("id")) is int and item["id"] > 0})
            if not ids:
                continue
            scope, params = evidence_scope_sql(viewer)
            allowed = set()
            for start in range(0, len(ids), 300):
                batch = ids[start:start + 300]
                rows = db.execute(
                    "SELECT e.id FROM evidence_items e WHERE e.id IN (" + ",".join(["%s"] * len(batch)) + ") AND "
                    + current_library_sql() + " AND " + scope,
                    [*batch, *params],
                ).fetchall()
                allowed.update(row["id"] for row in rows)
            if allowed != set(ids):
                return False
            for item in table.rows:
                if origin and item.get("id") in allowed:
                    item["vault_url"] = identity.safe_link(f"{origin}/evidence/?open=item:{item['id']}")
    return True


def build_document(env, *, db=None, row=None, run_id=None, viewer=None, exported_at=None) -> Report:
    """The report document of one frozen run. `row` is the report_runs row (for the trend and the integrity hash)."""
    report_type = (env.get("run") or {}).get("report_type")
    tier = tier_of(report_type)
    meta = _meta(env, report_type, run_id, viewer, db, exported_at)
    parts = _parts_for(env, compact=tier == theme.BOARD)
    if report_type == "preset_case" and db is not None and viewer is not None:
        if not _case_vault_addresses(env, parts, db, viewer):
            raise PermissionError("The case or its frozen proof is no longer in the reader's scope")
    report = Report(meta)
    note = (env.get("period") or {}).get("note")

    if tier == theme.BOARD:
        board_charts = [c for part in parts for c in part.charts]
        if report_type == "preset_board":
            pool = {k.label: k for part in parts for k in part.kpis}
            tiles = [Kpi("Critical risks", k.value, k.note, k.tone) if k.label == "Critical" else k
                     for k in (pool[name] for name in BOARD_PRESET_TILES if name in pool)]
            merged = {}
            for part in parts:
                for label, count in part.attention:
                    merged.setdefault(label, count)       # the same item named twice keeps its first figure
            board_charts = [c for c in board_charts if c.title != "Items that need attention"]
            if merged:
                total = sum(merged.values())
                board_charts.insert(1, Chart("bar", "Items that need attention", list(merged.items()), x_label="Number of items",
                                             y_label="Item", unit="items", half=True,
                                             takeaway=f"{identity.fmt_int(total)} items across risks, privacy, continuity, audit and service clocks need attention."))
        else:
            tiles = [k for part in parts for k in part.kpis][:8]
        messages = list(dict.fromkeys(m for part in parts for m in part.messages))
        decisions = list(dict.fromkeys(d for part in parts for d in part.decisions))     # two parts may state the same decision
        report.add(Heading("Headline measures", note), Kpis(tiles))
        if messages:
            report.add(Callout("Key messages", messages, "note"))
        report.add(Heading("Decisions needed"),
                   Callout("For the board to decide or note", decisions or [
                       "No item in these figures needs a board decision. Read the movement and the limits below."], "decision"))
        report.add(Heading("At a glance"), *board_charts)
        report.add(*_trend_blocks(_trend_points(db, row, env, report_type)))
        report.add(*_narrative_blocks(env))
    else:
        if report_type in COMPOSITE_PRESETS:
            for part in parts:
                report.add(Heading(part.title), Kpis(part.kpis) if part.kpis else None, *part.charts, *part.tables)
        else:
            for part in parts:
                report.add(Heading("Headline measures", note), Kpis(part.kpis) if part.kpis else None)
                if part.messages:
                    report.add(Callout("Key messages", part.messages, "note"))
                report.add(Heading("At a glance"), *part.charts)
                if part.tables:
                    report.add(Heading("Detail"), *part.tables)
        decisions = list(dict.fromkeys(d for part in parts for d in part.decisions))
        if decisions:
            report.add(Heading("Needs attention"), Callout("What the figures call for", decisions, "decision"))
        report.add(*_narrative_blocks(env))
    report.add(*_basis_blocks(env, db, run_id, row, tier))
    return report


def filename_stem(env, run_id) -> str:
    run = env.get("run") or {}
    return f"ThemisIQ_{run.get('definition_name') or run.get('report_type') or 'report'}_run{run_id}"
