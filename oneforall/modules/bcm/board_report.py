"""
The Resilience (business continuity) board report as a document on the shared report kit (decision D7 of
PLAN_report_exports_2026-10-21.md).

Every figure is a `core.metric_state` metric of the Resilience dashboard, read through the caller's own business unit scope: a
number that was measured, a number with nothing to measure ("Not measured", with the reason) or a number that could not be read
("Unavailable"). Neither of the last two is ever drawn as a zero. The words that interpret a figure are written by rule from the
figures; no model is called. The AI narrative stays on the page for those who want it.
"""
from core.report_kit import identity, theme
from core.report_kit.helpers import empty, label, metric_kpi, severity_rows
from core.report_kit.model import Callout, Chart, Col, Heading, Kpis, Report, Table
from core.timeutils import utcnow
from modules.bcm import dashboard_metrics
from modules.launcher import report_documents as documents


def _detail(metric) -> dict:
    return (metric or {}).get("detail") or {}


def _value(metric):
    return (metric or {}).get("value")


def _percent_text(metric):
    value = _value(metric)
    return None if value is None else f"{value}%"


def _why(metric, what) -> str:
    """The sentence a chart shows when its metric holds nothing to draw: the metric's own reason, else a plain statement."""
    return (metric or {}).get("note") or empty(what)


def board_report(user):
    now = utcnow()
    stats = dashboard_metrics.stats(user)
    m = stats["metrics"]
    plans, incidents, bia, exercises = m.get("bcm.plans"), m.get("bcm.active_incidents"), m.get("bcm.bia_with_plan"), m.get("bcm.exercises_completed")
    risks, levels = m.get("bcm.open_risks"), m.get("bcm.risk_levels")
    plan_detail, bia_detail, ex_detail, level_detail = _detail(plans), _detail(bia), _detail(exercises), _detail(levels)

    report = Report(documents.module_meta(
        user, "bcm", "Business continuity board report", "The continuity position for the board: plans, incidents, exercises and what needs a decision",
        theme.BOARD, now))
    kpis = [
        metric_kpi(plans, note=(f"{identity.fmt_int(plan_detail.get('approved'))} approved, {identity.fmt_int(plan_detail.get('activated'))} activated"
                                if plan_detail else "")),
        metric_kpi(incidents, note=f"of {identity.fmt_int(_detail(incidents).get('all'))} recorded" if _detail(incidents) else "", tone="bad"),
        metric_kpi(bia, text=_percent_text(bia), note=(f"{identity.fmt_int(bia_detail.get('covered'))} of {identity.fmt_int(bia_detail.get('total'))} analyses"
                                                       if bia_detail.get("total") else "")),
        metric_kpi(exercises, text=_percent_text(exercises), note=(f"{identity.fmt_int(ex_detail.get('completed'))} of {identity.fmt_int(ex_detail.get('total'))} exercises"
                                                                   if ex_detail.get("total") else "")),
        metric_kpi(risks, tone="warn"),
    ]
    report.add(Heading("Headline measures"), Kpis([k for k in kpis if k is not None]))

    rows, colours = severity_rows({k: v for k, v in level_detail.items() if v})
    top = level_detail.get("critical", 0) + level_detail.get("high", 0)
    in_review = plan_detail.get("in_review") or 0
    approved = plan_detail.get("approved") or 0
    plan_total = _value(plans) or 0
    statuses = [(name, count) for name, count in (("Approved", approved), ("In review", in_review),
                                                  ("Other states", max(plan_total - approved - in_review, 0))) if count]
    covered, bia_total = bia_detail.get("covered") or 0, bia_detail.get("total") or 0
    done, ex_total = ex_detail.get("completed") or 0, ex_detail.get("total") or 0
    charts = []
    if levels is not None:
        charts.append(Chart("bar", "Continuity risks by level", rows, x_label="Number of risks", y_label="Level", unit="risks", half=True,
                            colours=colours, takeaway=(f"{identity.fmt_int(top)} of {identity.fmt_int(_value(levels))} continuity risks are critical or high."
                                                       if _value(levels) else ""), empty_text=_why(levels, "No continuity risk is recorded.")))
    if plans is not None:
        charts.append(Chart("bar", "Continuity plans by status", statuses, x_label="Number of plans", y_label="Status", unit="plans", half=True,
                            takeaway=(f"{identity.fmt_int(approved)} of {identity.fmt_int(plan_total)} plans ({identity.pct(approved, plan_total)}%) are approved."
                                      if plan_total else ""), empty_text=_why(plans, "No continuity plan is recorded.")))
    if bia is not None:
        charts.append(Chart("donut", "Business impact analyses with a continuity plan",
                            [("With a plan", covered), ("Without a plan", max(bia_total - covered, 0))], unit="analyses", half=True,
                            centre=_percent_text(bia) or "", takeaway=(f"{identity.fmt_int(covered)} of {identity.fmt_int(bia_total)} analyses have a plan linked to them."
                                                                      if bia_total else ""), empty_text=_why(bia, "No business impact analysis is recorded.")))
    if exercises is not None:
        charts.append(Chart("donut", "Exercises completed",
                            [("Completed, in review or closed", done), ("Not completed", max(ex_total - done, 0))], unit="exercises", half=True,
                            centre=_percent_text(exercises) or "", takeaway=(f"{identity.fmt_int(done)} of {identity.fmt_int(ex_total)} exercises are completed, "
                                                                            "in review or closed." if ex_total else ""),
                            empty_text=_why(exercises, "No exercise is recorded.")))
    if charts:
        report.add(Heading("At a glance"), *charts)

    decisions = []
    if _value(incidents):
        n = _value(incidents)
        decisions.append(f"{identity.plural(n, 'active incident')}: confirm who commands {'it' if n == 1 else 'each'} and the recovery position.")
    if bia_total and bia_total > covered:
        n = bia_total - covered
        decisions.append(f"{identity.plural(n, 'business impact analysis', 'business impact analyses')} with no continuity plan: agree which plans are written first.")
    if top:
        decisions.append(f"{identity.plural(top, 'continuity risk is', 'continuity risks are')} critical or high: confirm the treatment owner for "
                         f"{'it' if top == 1 else 'each'}.")
    if decisions:
        report.add(Callout("Decisions for the board", decisions, kind="decision"))

    active = stats.get("active_incidents")
    listed = stats.get("plan_status")
    if active is not None or listed is not None:
        report.add(Heading("The records behind the figures"))
    if active is not None:
        report.add(Table(
            "Active incidents, newest first (up to five)",
            [Col("Incident", "title", weight=3.2), Col("Severity", "severity", weight=1), Col("Status", "status", weight=1.2),
             Col("Declared", "declared_at", weight=1.2, kind="date"), Col("Commander", "assigned", weight=1.4)],
            [{"title": r["title"], "severity": label(r.get("severity")) if r.get("severity") else None, "status": label(r.get("status")),
              "declared_at": r.get("declared_at"), "assigned": r.get("assigned") or None} for r in active],
            empty_text="No incident is active.", sheet_name="Active incidents"))
    if listed is not None:
        report.add(Table(
            "Continuity plans, activated first (up to six)",
            [Col("Plan", "title", weight=3.2), Col("Owner", "owner", weight=1.6), Col("Status", "status", weight=1.2), Col("Activated", "activated", weight=1)],
            [{"title": r["title"], "owner": r.get("owner") or None, "status": label(r.get("status")),
              "activated": "Yes" if r.get("is_active_plan") else "No"} for r in listed],
            empty_text="No continuity plan is recorded.", sheet_name="Plans"))
    report.add(Callout("What these figures are", [
        "Every figure is the one on the Resilience dashboard for the person who generated this report. Not measured means nothing is recorded "
        "to measure; Unavailable means the source could not be read. Neither is a zero.",
        "Exercises completed counts completed, in review and closed exercises against all exercises, cancelled ones included.",
        "Plans by status shows approved and in review; every other state is grouped as Other states."], kind="limit"))
    return report
