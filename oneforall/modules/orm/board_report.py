"""
The Operations Risk board report as a document on the shared report kit (decision D7 of PLAN_report_exports_2026-10-21.md).

Every figure is one the ORM dashboard shows to the person who generates it (`get_dashboard_stats`: the events visible through the
caller's own business unit scope, the last 30 days and the 30 days before them). The words that interpret a figure are written by
rule from the figures; no model is called. The AI narrative stays on the page for those who want it.
"""
from core.report_kit import identity, theme
from core.report_kit.helpers import ROWS_IN_DOCUMENT, by_count, empty, label, leader, tidy_number
from core.report_kit.model import Callout, Chart, Col, Heading, Kpi, Kpis, Report, Table
from core.timeutils import utcnow
from modules.launcher import report_documents as documents
from modules.orm import data_service as ds

DAYS = 30


def _usd(value) -> str:
    return f"USD {identity.fmt_int(value)}"


def _versus(delta, show, days) -> str:
    """How a figure moved against the period before it, in words."""
    if not delta:
        return f"unchanged on the previous {days} days"
    return f"{'up' if delta > 0 else 'down'} {show(abs(delta))} on the previous {days} days"


def board_report(user, days=DAYS):
    now = utcnow()
    stats = ds.get_dashboard_stats(days=days, user=user)
    events, d_events = stats["total_events"], stats["total_events_delta"]
    loss, d_loss = stats["financial_loss"], stats["financial_loss_delta"]
    customers, d_customers = stats["customers_affected"], stats["customers_delta"]
    hours, d_hours = stats["downtime_hours"], stats["downtime_delta"]
    overdue = stats["sla_overdue"]

    report = Report(documents.module_meta(
        user, "orm", "Operations risk board report", f"Operational risk events of the last {days} days: loss, impact and what needs a decision",
        theme.BOARD, now))
    report.add(Heading("Headline measures"), Kpis([
        Kpi("Events recorded", identity.fmt_int(events), _versus(d_events, identity.fmt_int, days)),
        Kpi("Financial loss, USD", identity.fmt_int(loss), _versus(d_loss, _usd, days), "bad" if loss else "neutral"),
        Kpi("Customers affected", identity.fmt_int(customers), _versus(d_customers, identity.fmt_int, days)),
        Kpi("Downtime", f"{tidy_number(hours)} hours", _versus(d_hours, lambda v: f"{tidy_number(v)} hours", days)),
        Kpi("Open events past a due time", identity.fmt_int(overdue), "response or resolution time passed, not resolved or closed",
            "bad" if overdue else "neutral"),
    ]))

    kinds = by_count({label(r["event_type"]): r["cnt"] for r in stats["by_type"]}, none_label="No type", limit=8, other="Other types")
    largest = [(identity.ellipsize(r["title"], 40), r["financial_impact"]) for r in stats["top5_by_impact"]]
    report.add(
        Heading("At a glance"),
        Chart("bar", f"Events by type, last {days} days", kinds, x_label="Number of events", y_label="Event type", unit="events", half=True,
              takeaway=leader(kinds, events, "type", "event"),
              empty_text=empty(f"No event was recorded in the last {days} days.")),
        Chart("bar", f"Largest losses, last {days} days", largest, x_label="Financial impact, USD", y_label="Event", unit="USD", half=True,
              takeaway=(f"The largest event cost {_usd(stats['top5_by_impact'][0]['financial_impact'])}." if stats["top5_by_impact"] else ""),
              empty_text=empty("No event with a financial impact was recorded.")),
        Chart("bar", "Events recorded, this period against the one before",
              [(f"Previous {days} days", events - d_events), (f"Last {days} days", events)], x_label="Number of events", y_label="Period",
              unit="events", half=True, takeaway=f"Events are {_versus(d_events, identity.fmt_int, days)}."),
        Chart("bar", "Financial loss, this period against the one before",
              [(f"Previous {days} days", loss - d_loss), (f"Last {days} days", loss)], x_label="Financial loss, USD", y_label="Period",
              unit="USD", half=True, takeaway=f"Financial loss is {_versus(d_loss, _usd, days)}."))

    decisions = []
    if overdue:
        decisions.append(f"{identity.plural(overdue, 'open event is', 'open events are')} past a response or resolution time: confirm who is "
                         f"clearing {'it' if overdue == 1 else 'them'}.")
    if d_loss > 0:
        decisions.append(f"Financial loss is {_usd(d_loss)} higher than in the previous {days} days: ask the owners of the largest events for "
                         "the cause and the fix.")
    if decisions:
        report.add(Callout("Decisions for the board", decisions, kind="decision"))

    report.add(
        Heading("The events behind the figures"),
        Table(f"Largest losses, last {days} days",
              [Col("Event", "title", weight=3.4), Col("Type", "type", weight=1.4), Col("Severity", "severity", weight=1),
               Col("Financial impact, USD", "impact", "right", 1.4, "int")],
              [{"title": r["title"], "type": label(r["event_type"]), "severity": label(r["severity"]) if r.get("severity") else None,
                "impact": r["financial_impact"]} for r in stats["top5_by_impact"]],
              empty_text="No event with a financial impact was recorded in this period.", sheet_name="Largest losses"),
        Table("The ten most recent events, whatever their date",
              [Col("Event", "title", weight=3.2), Col("Type", "type", weight=1.3), Col("Severity", "severity", weight=0.9),
               Col("Status", "status", weight=1), Col("Recorded", "recorded", weight=1.1, kind="date"),
               Col("Impact, USD", "impact", "right", 1, "int")],
              [{"title": r["title"], "type": label(r["event_type"]), "severity": label(r["severity"]) if r.get("severity") else None,
                "status": label(r["status"]), "recorded": r.get("created_at"), "impact": r.get("financial_impact")}
               for r in stats["recent_events"]],
              empty_text="No event is recorded.", sheet_name="Recent events", max_rows=ROWS_IN_DOCUMENT))
    report.add(Callout("What these figures are", [
        "Events are counted by the date they were recorded in the platform, not the date they occurred.",
        f"The previous period is the {days} days immediately before the last {days} days.",
        "Amounts are shown in US dollars, as the Operations Risk page shows them."], kind="limit"))
    return report
