"""
Audit module (GRID): the audit report as a PDF or a Word document, on the shared report kit.

One snapshot of the audit is read once (`gather`), every figure in the report is computed from it once (`figures`), and the
same figures feed the cover, the charts, the tables and the narrative prompt. The cover, the footer (module, who, when, page
numbers), the silver look and the charts belong to `core/report_kit`; this module only decides what an audit report says.

Two tiers (PLAN_report_exports_2026-10-21.md, decision D3): the operational report carries every control, finding and
response; the board summary is the short, decision oriented one (headline measures, three charts, the top gaps, what needs a
decision).

Security: every text is cleaned before it is placed in a document, a file name is built from numbers only, and the file is
written inside the tenant's own report folder.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from core.best_effort import swallowed
from core.email import app_origin
from core.report_kit import grounding, identity, theme
from core.report_kit.model import (Actor, Callout, Chart, Col, Heading, Kpi, Kpis, Meta, Paragraphs, Report, Table)
from core.report_kit.render_docx import render_docx
from core.report_kit.render_pdf import render_pdf
from core.timeutils import utcnow
from database import get_current_tenant, get_db
from modules.evidence.scope import current_library_sql, evidence_scope_sql

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "data/reports"))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

CONTROL_ROWS = 400            # an audit with more controls than this is cut in the document, and the document says so
SEVERITY_ORDER = ["critical", "major", "minor"]
RISK_ORDER = ["Critical", "High", "Medium", "Low"]
SEVERITY_COLOURS = {"Critical": theme.GRAPHITE, "High": theme.SLATE, "Medium": theme.SILVER_DEEP, "Low": theme.SILVER}


def _report_output_dir() -> Path:
    """Keep generated files from different organizations in separate folders."""
    tenant = get_current_tenant() or "public"
    if not re.fullmatch(r"[a-z0-9_-]{1,80}", tenant):
        raise ValueError("Invalid report tenant")
    output_dir = REPORTS_DIR / tenant
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _clean(text) -> str:
    return identity.clean_text(text, keep_newlines=False)


def _status_label(status, due_date, today) -> str:
    """One state per control: complete, overdue (not complete and past its date), in progress, or not started."""
    if status == "Complete":
        return "Complete"
    if due_date and str(due_date)[:10] < today:
        return "Overdue"
    return "In Progress" if status == "In Progress" else "Not Started"


# ── Reading the audit ───────────────────────────────────────────────────────

def gather(audit_id: int, viewer=None) -> dict | None:
    """Everything the report needs about one audit, read once. None when there is no such audit."""
    from modules.grid import data_service as ds

    db = get_db()
    try:
        audit = db.execute(
            "SELECT a.*, f.name AS framework_name, bu.name AS bu_name, u.full_name AS lead_name "
            "FROM grid_audits a LEFT JOIN grid_frameworks f ON a.framework_id=f.id "
            "LEFT JOIN business_units bu ON bu.id=a.business_unit_id LEFT JOIN users u ON u.id=a.lead_id WHERE a.id=%s",
            (audit_id,)).fetchone()
        if not audit:
            return None
        audit = dict(audit)
        controls = [dict(r) for r in db.execute(
            "SELECT c.*, u.full_name AS assignee_name, "
            "(SELECT COUNT(*) FROM grid_evidence_items ei WHERE ei.control_id=c.id) AS items_total, "
            "(SELECT COUNT(DISTINCT ei.id) FROM grid_evidence_items ei JOIN grid_evidence_files ef ON ef.evidence_item_id=ei.id "
            " WHERE ei.control_id=c.id) AS items_covered, "
            "(SELECT COUNT(*) FROM grid_evidence_files ef WHERE ef.control_id=c.id) AS files "
            "FROM grid_controls c LEFT JOIN users u ON c.assignee_id=u.id WHERE c.audit_id=%s ORDER BY c.control_id",
            (audit_id,)).fetchall()]
        ncs = [dict(r) for r in db.execute(
            "SELECT nc.*, u.full_name AS assigned_name, c.control_id AS ctrl_ref, c.name AS control_name "
            "FROM grid_non_conformances nc LEFT JOIN users u ON nc.assigned_to=u.id LEFT JOIN grid_controls c ON nc.control_id=c.id "
            "WHERE nc.audit_id=%s "
            "ORDER BY CASE nc.severity WHEN 'critical' THEN 1 WHEN 'major' THEN 2 WHEN 'minor' THEN 3 ELSE 4 END, nc.id",
            (audit_id,)).fetchall()]
        responses = [dict(r) for r in db.execute(
            "SELECT nc.title, nc.severity, nc.mgmt_response_status, nc.mgmt_response, nc.response_deadline, "
            "u.full_name AS responder_name, nc.mgmt_response_at FROM grid_non_conformances nc "
            "LEFT JOIN users u ON nc.mgmt_response_by=u.id WHERE nc.audit_id=%s AND nc.mgmt_response_status IS NOT NULL "
            "ORDER BY nc.mgmt_response_at DESC", (audit_id,)).fetchall()]
        signoffs = [dict(r) for r in db.execute(
            "SELECT s.role, s.signed_at, s.comment, u.full_name AS user_name FROM grid_audit_signoffs s "
            "LEFT JOIN users u ON s.user_id=u.id WHERE s.audit_id=%s ORDER BY s.signed_at", (audit_id,)).fetchall()]
        vault_files = []
        if viewer is not None:
            scope, params = evidence_scope_sql(viewer)
            rows = db.execute(
                "SELECT DISTINCT e.id, e.title, e.version, el.entity_type AS source_type "
                "FROM evidence_items e JOIN evidence_links el ON el.evidence_id=e.id "
                f"WHERE {scope} AND {current_library_sql()} AND el.deleted_at IS NULL "
                "AND el.module='grid' AND ("
                "(el.entity_type='audit' AND el.entity_id=%s) OR "
                "(el.entity_type='control' AND el.entity_id IN (SELECT id FROM grid_controls WHERE audit_id=%s)) OR "
                "(el.entity_type='nc' AND el.entity_id IN (SELECT id FROM grid_non_conformances WHERE audit_id=%s))) "
                "ORDER BY e.id, el.entity_type", [*params, audit_id, audit_id, audit_id],
            ).fetchall()
            origin = app_origin()
            seen = set()
            for row in rows:
                if row["id"] in seen:
                    continue
                seen.add(row["id"])
                vault_files.append({"title": row["title"], "version": row["version"],
                                    "source": {"audit": "Audit", "control": "Control", "nc": "Finding"}.get(row["source_type"], "Record"),
                                    "vault_url": identity.safe_link(f"{origin}/evidence/?open=item:{row['id']}") if origin else ""})
    finally:
        db.close()
    evidence = ds.get_evidence_completeness(audit_id)   # the figures the Evidence tab shows, counted the same way
    return {"audit": audit, "controls": controls, "ncs": ncs, "responses": responses, "signoffs": signoffs,
            "evidence": evidence, "vault_files": vault_files, "today": utcnow().strftime("%Y-%m-%d")}


def _nc_open(nc) -> bool:
    """Closed means the finding's status or its corrective action plan status says closed, as everywhere else in GRID."""
    return str(nc.get("status") or "open").lower() != "closed" and str(nc.get("cap_status") or "Open") != "Closed"


def figures(data: dict) -> dict:
    """Every figure of the report, computed once from one snapshot."""
    controls, today = data["controls"], data["today"]
    states = [_status_label(c.get("status"), c.get("due_date"), today) for c in controls]
    total = len(controls)
    complete = states.count("Complete")
    by_risk = {}
    for control, state in zip(controls, states):
        level = str(control.get("risk_level")).title() if control.get("risk_level") else "Unrated"
        slot = by_risk.setdefault(level, {"complete": 0, "not_complete": 0})
        slot["complete" if state == "Complete" else "not_complete"] += 1
    ncs = data["ncs"]
    by_severity = {}
    for nc in ncs:
        severity = str(nc.get("severity") or "unrated").lower()
        slot = by_severity.setdefault(severity, {"open": 0, "closed": 0})
        slot["open" if _nc_open(nc) else "closed"] += 1
    ev = data["evidence"]
    files, approved, pending, rejected = ev["totalFiles"], ev["approvedFiles"], ev["pendingFiles"], ev["rejectedFiles"]
    gaps = [c for c, s in zip(controls, states)
            if s != "Complete" and str(c.get("risk_level") or "").title() in ("Critical", "High")]
    return {
        "total": total, "complete": complete, "not_complete": total - complete,
        "overdue": states.count("Overdue"), "in_progress": states.count("In Progress"), "not_started": states.count("Not Started"),
        "completion_pct": identity.pct(complete, total) if total else None,
        "by_risk": by_risk, "critical_high_open": len(gaps), "gaps": gaps,
        "nc_total": len(ncs), "nc_open": sum(1 for n in ncs if _nc_open(n)), "nc_closed": sum(1 for n in ncs if not _nc_open(n)),
        "nc_by_severity": by_severity,
        "nc_open_critical": sum(1 for n in ncs if _nc_open(n) and str(n.get("severity") or "").lower() == "critical"),
        "files_total": files, "files_approved": approved, "files_pending": pending, "files_rejected": rejected,
        "files_other": max(files - approved - pending - rejected, 0),
        "items_total": ev["totalItems"], "items_with_evidence": ev["itemsWithEvidence"],
        "responses": len(data["responses"]), "signoffs": len(data["signoffs"]), "states": states,
    }


def narrative_inputs(data: dict, fig: dict) -> dict:
    """What the model is told: the figures of the report, under the names the report uses, and nothing else."""
    audit = data["audit"]
    return {"auditName": audit.get("name"), "framework": audit.get("framework_name"), "completionPct": fig["completion_pct"] or 0,
            "totalControls": fig["total"], "complete": fig["complete"], "pending": fig["not_complete"], "overdue": fig["overdue"],
            "auditDate": audit.get("audit_date"), "criticalGaps": [_clean(c.get("name")) for c in fig["gaps"]][:5]}


def checked_narrative(data: dict, fig: dict, narrative: dict | None):
    """(narrative or None, a sentence saying why it was left out or how it was checked)."""
    if not narrative:
        return None, ""
    text = " ".join([str(narrative.get("executive_summary") or ""), *[str(f) for f in narrative.get("key_findings") or []],
                     str(narrative.get("conclusion") or "")])
    if not text.strip():
        return None, ""
    allowed = {k: v for k, v in fig.items() if k not in ("gaps", "states")}
    allowed["names"] = [data["audit"].get("name"), data["audit"].get("framework_name"),
                        *[c.get("name") for c in fig["gaps"]], *[c.get("control_id") for c in fig["gaps"]]]
    allowed["dates"] = [data["audit"].get("audit_date"), data["audit"].get("start_date"), data["audit"].get("end_date")]
    today = utcnow()
    result = grounding.check(text, allowed, extra=[today.day, today.month, today.year])
    return (narrative, result.sentence()) if result.ok else (None, result.sentence())


# ── The report ──────────────────────────────────────────────────────────────

def _org_name(actor) -> str:
    """The organization of the person who generates the report, by name (empty when it cannot be read)."""
    try:
        db = get_db()
        try:
            row = db.execute("SELECT name FROM organizations WHERE id = %s", ((actor or {}).get("org_id"),)).fetchone()
        finally:
            db.close()
        return row["name"] if row else ""
    except Exception:
        swallowed("audit report: organization name")
        return ""


def build_report(data: dict, *, actor, tier: str = theme.OPERATIONAL, narrative=None, narrative_note: str = "",
                 org_name: str = "") -> Report:
    audit, fig = data["audit"], figures(data)
    start, end, on = audit.get("start_date"), audit.get("end_date"), audit.get("audit_date")
    period = (f"Audit period: {identity.format_day(start)} to {identity.format_day(end)}" if start and end else
              f"Audit date: {identity.format_day(on)}" if on else f"As of {identity.format_when(data['today'])}")
    scope = f"Business unit: {audit['bu_name']}" if audit.get("bu_name") else "Whole organization (this audit is not tied to one business unit)"
    kind = "Audit report" if tier == theme.OPERATIONAL else "Summary for the board"
    framework = _clean(audit.get("framework_name"))
    meta = Meta(
        title=_clean(audit.get("name")) or "Audit report", module="grid", tier=tier, org_name=org_name, scope=scope, period=period,
        subtitle=f"{kind}: {framework}" if framework else kind,
        generated_at=utcnow(), generated_by=Actor.of_user(actor), reference=f"Audit {audit['id']}")
    report = Report(meta)
    done, total = fig["complete"], fig["total"]
    pct = fig["completion_pct"]
    ev_share = identity.pct(fig["files_approved"], fig["files_total"]) if fig["files_total"] else None

    kpis = [Kpi("Controls", identity.fmt_int(total)),
            Kpi("Complete", identity.fmt_int(done), f"{pct}% of controls" if pct is not None else "", "good" if done else "neutral"),
            Kpi("Not complete", identity.fmt_int(fig["not_complete"]), "includes the overdue ones"),
            Kpi("Overdue", identity.fmt_int(fig["overdue"]), "past their due date", "bad" if fig["overdue"] else "neutral"),
            Kpi("Open findings", identity.fmt_int(fig["nc_open"]), f"of {identity.fmt_int(fig['nc_total'])} raised",
                "warn" if fig["nc_open"] else "neutral"),
            Kpi("Evidence approved", identity.fmt_int(fig["files_approved"]), f"of {identity.fmt_int(fig['files_total'])} files"
                + (f" ({ev_share}%)" if ev_share is not None else ""))]
    messages = []
    if pct is not None:
        messages.append(f"{identity.fmt_int(done)} of {identity.fmt_int(total)} controls ({pct}%) are complete.")
    if fig["overdue"]:
        messages.append(f"{identity.plural(fig['overdue'], 'control')} {'is' if fig['overdue'] == 1 else 'are'} overdue.")
    if fig["nc_total"]:
        messages.append(f"{identity.fmt_int(fig['nc_open'])} of {identity.fmt_int(fig['nc_total'])} findings are still open.")
    if fig["files_total"]:
        messages.append(f"{identity.fmt_int(fig['files_approved'])} of {identity.fmt_int(fig['files_total'])} evidence files ({ev_share}%) are approved.")
    decisions = []
    if fig["nc_open_critical"]:
        decisions.append(f"{identity.plural(fig['nc_open_critical'], 'critical finding')} still open: confirm the owner and the due date of each.")
    if fig["overdue"]:
        decisions.append(f"{identity.plural(fig['overdue'], 'overdue control')}: agree a recovery date for each.")
    if fig["critical_high_open"]:
        decisions.append(f"{identity.plural(fig['critical_high_open'], 'critical or high risk control')} not complete: confirm who completes them and by when.")
    if fig["files_rejected"]:
        decisions.append(f"{identity.plural(fig['files_rejected'], 'evidence file')} rejected: confirm who resubmits.")

    status_rows = [r for r in (("Complete", done, theme.GRAPHITE), ("In progress", fig["in_progress"], theme.SILVER_DEEP),
                               ("Not started", fig["not_started"], theme.SILVER_LIGHT), ("Overdue", fig["overdue"], theme.BAD)) if r[1]]
    donut = Chart("donut", "Controls by status", [(label, value) for label, value, _ in status_rows], unit="controls", half=True,
                  centre=f"{pct}%" if pct is not None else "", colours=[colour for _, _, colour in status_rows] or None,
                  takeaway=(f"{identity.fmt_int(done)} of {identity.fmt_int(total)} controls are complete; "
                            f"{identity.fmt_int(fig['overdue'])} are overdue." if total else ""),
                  empty_text="This audit has no controls yet, so there is nothing to chart.")
    known = RISK_ORDER + ["Unrated"]
    risk_levels = [lvl for lvl in known if lvl in fig["by_risk"]] + [lvl for lvl in fig["by_risk"] if lvl not in known]
    risk_stack = Chart(
        "stack", "Controls by risk level: complete and not complete",
        [(lvl, [("Complete", fig["by_risk"][lvl]["complete"]), ("Not complete", fig["by_risk"][lvl]["not_complete"])]) for lvl in risk_levels],
        x_label="Number of controls", y_label="Risk level", half=True, colours=[theme.GRAPHITE, theme.SILVER],
        takeaway=(f"{identity.plural(fig['critical_high_open'], 'critical or high risk control')} {'is' if fig['critical_high_open'] == 1 else 'are'} not complete."
                  if total else ""), empty_text="This audit has no controls yet, so there is nothing to chart.")
    sev_names = [s for s in SEVERITY_ORDER if s in fig["nc_by_severity"]] + [s for s in fig["nc_by_severity"] if s not in SEVERITY_ORDER]
    nc_stack = Chart(
        "stack", "Findings by severity: open and closed",
        [(s.capitalize(), [("Open", fig["nc_by_severity"][s]["open"]), ("Closed", fig["nc_by_severity"][s]["closed"])]) for s in sev_names],
        x_label="Number of findings", y_label="Severity", half=True, colours=[theme.GRAPHITE, theme.SILVER],
        takeaway=(f"{identity.fmt_int(fig['nc_open'])} of {identity.fmt_int(fig['nc_total'])} findings are open, "
                  f"{identity.fmt_int(fig['nc_open_critical'])} of them critical." if fig["nc_total"] else ""),
        empty_text="No finding has been raised in this audit.")
    ev_rows = [("Approved", fig["files_approved"]), ("Awaiting review", fig["files_pending"]), ("Rejected", fig["files_rejected"])]
    if fig["files_other"]:
        ev_rows.append(("Other status", fig["files_other"]))
    evidence = Chart("bar", "Evidence files by review state", [r for r in ev_rows], x_label="Number of files", y_label="Review state", unit="files",
                     half=True, takeaway=(f"{identity.fmt_int(fig['files_approved'])} of {identity.fmt_int(fig['files_total'])} files are approved; "
                                          f"{identity.fmt_int(fig['files_pending'])} await review." if fig["files_total"] else ""),
                     empty_text="No evidence file has been uploaded for this audit.")

    nar_blocks = []
    if narrative:
        paragraphs = [p for p in (_clean(narrative.get("executive_summary")), *[("• " + _clean(f)) for f in narrative.get("key_findings") or []],
                                  _clean(narrative.get("conclusion"))) if p and p != "• "]
        nar_blocks = [Paragraphs("Draft narrative", paragraphs, label=f"Written by an AI model from the figures of this report, not reviewed. {narrative_note}")]
    elif narrative_note:
        nar_blocks = [Callout("Draft narrative left out", [narrative_note, "The figures in this report are the saved figures of the audit."], "limit")]

    report.add(Heading("Headline measures", "Read from the audit when this report was generated."), Kpis(kpis))
    if messages:
        report.add(Callout("Key messages", messages, "note"))
    if tier == theme.BOARD:
        report.add(Heading("Decisions needed"), Callout("For the board to decide or note", decisions or [
            "No item in these figures needs a board decision."], "decision"))
        report.add(Heading("At a glance"), donut, risk_stack, nc_stack)
        report.add(Heading("The gaps that matter most"), Table(
            "Critical and high risk controls that are not complete", _control_columns(),
            [_control_row(c, s) for c, s in _gap_rows(data, fig)][:5],
            note=(f"The five with the earliest due dates of {identity.fmt_int(fig['critical_high_open'])}."
                  if fig["critical_high_open"] > 5 else ""), empty_text="Every critical and high risk control is complete.", sheet_name="Gaps"))
        report.add(*nar_blocks)
    else:
        report.add(Heading("At a glance"), donut, risk_stack, nc_stack, evidence)
        report.add(*nar_blocks)
        if decisions:
            report.add(Heading("Needs attention"), Callout("What the figures call for", decisions, "decision"))
        report.add(Heading("Controls"), Table(
            "Every control in this audit", _control_columns(), [_control_row(c, s) for c, s in zip(data["controls"], fig["states"])][:CONTROL_ROWS],
            note=(f"Evidence shows how many of the control's evidence items have at least one file. "
                  + (f"Showing the first {CONTROL_ROWS} of {identity.fmt_int(total)} controls." if total > CONTROL_ROWS else "")).strip(),
            empty_text="This audit has no controls yet.", sheet_name="Controls"))
        ncs = data["ncs"]
        report.add(Heading("Findings"), Table(
            f"Findings: {identity.fmt_int(fig['nc_total'])} raised, {identity.fmt_int(fig['nc_open'])} open, {identity.fmt_int(fig['nc_closed'])} closed",
            [Col("Finding", "title", weight=4), Col("Severity", "severity", weight=1), Col("CAP status", "cap", weight=1.3),
             Col("State", "state", weight=0.9), Col("Assigned to", "assignee", weight=1.6), Col("Control", "control", weight=1.1)],
            [{"title": _clean(n.get("title")), "severity": (_clean(n.get("severity")) or "n/a").capitalize(), "cap": _clean(n.get("cap_status")),
              "state": "Open" if _nc_open(n) else "Closed", "assignee": _clean(n.get("assigned_name")), "control": _clean(n.get("ctrl_ref"))} for n in ncs],
            max_rows=150, empty_text="No finding has been raised in this audit.", sheet_name="Findings"))
        if data["responses"]:
            report.add(Table("Management responses", [Col("Finding", "title", weight=3), Col("Response status", "status", weight=1.3),
                                                      Col("By", "by", weight=1.5), Col("Response", "text", weight=4)],
                             [{"title": _clean(r.get("title")), "status": _clean(r.get("mgmt_response_status")), "by": _clean(r.get("responder_name")),
                               "text": identity.ellipsize(r.get("mgmt_response"), 280)} for r in data["responses"]],
                             max_rows=60, note="Long responses are shortened here; the full text is on the finding.", sheet_name="Responses"))
        if _clean(audit.get("conclusion")):
            report.add(Paragraphs("Conclusion recorded by the auditor", [_clean(audit.get("conclusion"))]))
        if data["signoffs"]:
            report.add(Table("Sign-offs", [Col("Role", "role", weight=1.2), Col("Name", "name", weight=2), Col("Date", "date", weight=1.2, kind="date"),
                                           Col("Comment", "comment", weight=4)],
                             [{"role": _clean(s.get("role")).title(), "name": _clean(s.get("user_name")), "date": s.get("signed_at"),
                               "comment": _clean(s.get("comment"))} for s in data["signoffs"]], sheet_name="Sign-offs"))
        report.add(Heading("Connected documents"), Table(
            "Files in the Evidence Vault", [Col("File", "title", weight=4, link="vault_url"),
                                            Col("Version", "version", weight=1, kind="int"),
                                            Col("Connected to", "source", weight=1.5)],
            data.get("vault_files") or [],
            empty_text="No Vault document linked to this audit, its controls or findings is visible to the report reader.",
            sheet_name="Vault documents"))
    report.add(Heading("Basis and limits"), Callout("How to read this report", [
        "Every figure is read from the audit at the moment this report was generated.",
        "A control is overdue when it is not complete and its due date is before today. Not complete includes the overdue ones.",
        "Evidence counts follow the Evidence tab: a file awaiting review has the status Uploaded or Pending.",
        "A finding is closed when its status or its corrective action plan status is Closed."], "note"))
    return report


def _control_columns():
    return [Col("Control ID", "ref", weight=1.2), Col("Control", "name", weight=4.2), Col("Risk", "risk", weight=1),
            Col("Due", "due", weight=1.3, kind="date"), Col("Evidence", "evidence", weight=1.9), Col("Status", "status", weight=1.2)]


def _control_row(control, state) -> dict:
    items, covered, files = control.get("items_total") or 0, control.get("items_covered") or 0, control.get("files") or 0
    evidence = (f"{covered} of {items} items" if items else (f"{files} file(s), no checklist" if files else "No checklist"))
    return {"ref": _clean(control.get("control_id")), "name": _clean(control.get("name")), "risk": _clean(control.get("risk_level")) or "n/a",
            "due": control.get("due_date") or None, "evidence": evidence, "status": state}


def _gap_rows(data, fig):
    pairs = [(c, s) for c, s in zip(data["controls"], fig["states"])
             if s != "Complete" and str(c.get("risk_level") or "").title() in ("Critical", "High")]
    return sorted(pairs, key=lambda cs: (str(cs[0].get("due_date") or "9999"), str(cs[0].get("control_id") or "")))


# ── The files ───────────────────────────────────────────────────────────────

def _write(audit_id: int, extension: str, body: bytes) -> dict:
    timestamp = int(utcnow().timestamp())
    filename = f"grid-report-{int(audit_id)}-{timestamp}.{extension}"
    if not re.fullmatch(rf"grid-report-\d+-\d+\.{extension}", filename):
        raise ValueError("Unsafe report filename generated")
    path = _report_output_dir() / filename
    path.write_bytes(body)
    return {"filePath": str(path), "fileName": filename, "size": len(body)}


def prepare(audit_id: int, *, actor, tier: str = theme.OPERATIONAL, narrative_fn=None) -> Report:
    """Read the audit, ask for a narrative with the report's own figures, check it, and build the report."""
    data = gather(audit_id, viewer=actor)
    if not data:
        raise ValueError(f"Audit {audit_id} not found")
    fig = figures(data)
    narrative, note = None, ""
    if narrative_fn is not None:
        try:
            narrative, note = checked_narrative(data, fig, narrative_fn(narrative_inputs(data, fig)))
        except Exception:
            narrative, note = None, ""      # AI unavailable: the report is complete without it
    return build_report(data, actor=actor, tier=tier, narrative=narrative, narrative_note=note, org_name=_org_name(actor))


def generate_pdf_report(audit_id: int, *, actor, tier: str = theme.OPERATIONAL, narrative_fn=None) -> dict:
    """Generate the PDF into the tenant's report folder. Returns {"filePath", "fileName", "size"}."""
    return _write(audit_id, "pdf", render_pdf(prepare(audit_id, actor=actor, tier=tier, narrative_fn=narrative_fn)))


def generate_docx_report(audit_id: int, *, actor, tier: str = theme.OPERATIONAL, narrative_fn=None) -> dict:
    """Generate the Word document into the tenant's report folder. Returns {"filePath", "fileName", "size"}."""
    return _write(audit_id, "docx", render_docx(prepare(audit_id, actor=actor, tier=tier, narrative_fn=narrative_fn)))
