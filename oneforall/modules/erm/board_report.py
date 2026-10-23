"""
The Enterprise Risk board report as a document on the shared report kit (decision D7 of PLAN_report_exports_2026-10-21.md).

Every figure is one the ERM dashboard shows to the person who generates it: the headline counts and the posture block of
`get_dashboard_stats`, the band, category and level counts of `get_register_stats`, and the appetite position of
`get_appetite_status`, all through the caller's own business unit scope. The words that interpret a figure are written by rule
from the figures, so no model is called, nothing waits on an external service, and every sentence can be traced to a number on
the page. The AI narrative stays on the page for those who want it.
"""
from datetime import date

from core.report_kit import identity, theme
from core.report_kit.helpers import ROWS_IN_DOCUMENT, by_count, empty, label, leader, severity_rows, tidy_number
from core.report_kit.model import Callout, Chart, Col, Heading, Kpi, Kpis, Report, Table
from core.timeutils import utcnow
from modules.erm import data_service as ds
from modules.launcher import report_documents as documents


def _month_label(text) -> str:
    try:
        year, month = str(text)[:7].split("-")
        return date(int(year), int(month), 1).strftime("%b %Y")
    except (ValueError, TypeError):
        return str(text)


def _usd(value) -> str:
    return "n/a" if value is None else f"USD {identity.fmt_int(value)}"


def board_report(user):
    now = utcnow()
    stats = ds.get_dashboard_stats(None, user=user)
    register = ds.get_register_stats(user=user)
    appetite = ds.get_appetite_status(user=user)
    posture = stats.get("posture") or {}

    total, erm_n, platform_n = stats["total_risks"], stats["total_enterprise_risks"], stats["total_register_risks"]
    critical, high = stats["critical"], stats["high"]
    breaches, overdue, board_visible = stats["appetite_breaches"], stats["overdue_obligations"], stats["board_visible"]
    report = Report(documents.module_meta(
        user, "erm", "Enterprise risk board report", "The risk position for the board: exposure, appetite and what needs a decision",
        theme.BOARD, now))

    avg_rrr, avg_irr, loa = posture.get("avg_rrr"), posture.get("avg_irr"), posture.get("avg_loa")
    report.add(Heading("Headline measures"), Kpis([
        Kpi("Open risks", identity.fmt_int(total), f"{identity.fmt_int(erm_n)} enterprise and {identity.fmt_int(platform_n)} platform register; "
            f"{identity.fmt_int(stats['trend_total'])} added in the last 30 days"),
        Kpi("Critical enterprise risks", identity.fmt_int(critical), f"{identity.fmt_int(stats['trend_critical'])} added in the last 30 days",
            "bad" if critical else "neutral"),
        Kpi("High or critical enterprise risks", identity.fmt_int(high), "", "warn" if high else "neutral"),
        Kpi("Risks above appetite", identity.fmt_int(breaches), "residual exposure over the limit set for the category",
            "bad" if breaches else "neutral"),
        Kpi("Overdue obligations", identity.fmt_int(overdue), "regulatory obligations past their due date", "bad" if overdue else "neutral"),
        Kpi("Board-visible risks", identity.fmt_int(board_visible), "open risks marked for the board"),
        Kpi("Average residual rating", tidy_number(avg_rrr) if avg_rrr is not None else "n/a",
            f"average inherent rating {tidy_number(avg_irr)}" if avg_irr is not None else "no risk has a residual rating yet"),
        Kpi("Control assurance", f"{tidy_number(loa)}%" if loa is not None else "n/a",
            "average level of assurance of the controls" if loa is not None else "no control has been scored yet"),
    ]))

    bands, band_colours = severity_rows(register["by_level"])
    top_band = register["by_level"].get("critical", 0) + register["by_level"].get("high", 0)
    categories = by_count({label(k): v for k, v in register["by_category"].items()}, limit=8, other="Other categories")
    exposure = sorted(((label(a["category"]), identity.pct(a["current_max_score"], a["max_score"]))
                       for a in appetite if a["max_score"] and a["open_count"]), key=lambda r: (-r[1], r[0]))
    above = sum(1 for a in appetite if a["breached"])
    emv = [(name, value) for name, value in (("Inherent", posture.get("emv_i_total")), ("Residual", posture.get("emv_r_total")),
                                             ("After planned treatment", posture.get("emv_a_total"))) if value is not None]
    trajectory = [(_month_label(m["month"]), m["avg_rrr"]) for m in posture.get("trajectory") or [] if m.get("avg_rrr") is not None]
    charts = [
        Chart("bar", "Open risks by band, enterprise and platform registers", bands, x_label="Number of open risks", y_label="Band",
              unit="risks", half=True, colours=band_colours,
              takeaway=(f"{identity.fmt_int(top_band)} of {identity.fmt_int(register['total'])} open risks "
                        f"({identity.pct(top_band, register['total'])}%) are critical or high." if register["total"] else ""),
              empty_text=empty("No open risk is recorded.")),
        Chart("bar", "Open risks by category", categories, x_label="Number of open risks", y_label="Category", unit="risks", half=True,
              takeaway=leader(categories, register["total"], "category", "open risk", group_plural="categories"), empty_text=empty("No open risk is recorded.")),
        Chart("bar", "Exposure against appetite, by category", exposure, x_label="Highest residual score, percent of the appetite limit",
              y_label="Category", unit="%", max_value=max([100] + [v for _, v in exposure]),
              takeaway=(f"{identity.fmt_int(above)} of {identity.fmt_int(len(appetite))} categories are above their appetite limit; 100% is the limit."
                        if appetite else ""),
              empty_text=empty("No category has both an appetite limit and an open risk." if appetite else "No risk appetite is set.")),
    ]
    if len(emv) >= 2:
        charts.append(Chart(
            "bar", "Expected monetary value of the enterprise risks", emv, x_label="Expected loss, USD", y_label="Stage", unit="USD", half=True,
            takeaway=(f"Residual exposure is {_usd(posture.get('emv_r_total'))} against {_usd(posture.get('emv_i_total'))} before controls."
                      if posture.get("emv_i_total") is not None and posture.get("emv_r_total") is not None else "")))
    charts.append(Chart(
        "line", "Average residual risk rating by month", trajectory, x_label="Month", y_label="Average residual rating", unit="",
        half=len(emv) >= 2,
        takeaway=(f"The average residual rating was {tidy_number(trajectory[0][1])} in {trajectory[0][0]} and "
                  f"{tidy_number(trajectory[-1][1])} in {trajectory[-1][0]}." if len(trajectory) >= 2 else ""),
        empty_text=empty("Score history covers fewer than two months.")))
    report.add(Heading("At a glance"), *charts)

    decisions = []
    if breaches:
        decisions.append(f"{identity.plural(breaches, 'risk is', 'risks are')} above the appetite set for {'its' if breaches == 1 else 'their'} "
                         f"category: decide whether to treat, transfer or accept {'it' if breaches == 1 else 'them'}.")
    if critical:
        decisions.append(f"{identity.plural(critical, 'critical enterprise risk')}: confirm each has an owner and a treatment under way.")
    if overdue:
        decisions.append(f"{identity.plural(overdue, 'regulatory obligation')} overdue: agree who clears {'it' if overdue == 1 else 'them'}.")
    if not appetite:
        decisions.append("No risk appetite is set, so exposure cannot be compared with appetite: set a limit for each category.")
    if decisions:
        report.add(Callout("Decisions for the board", decisions, kind="decision"))
    if stats.get("actions_required"):
        report.add(Callout("Open actions, the first eight", [a["text"] for a in stats["actions_required"]]))

    def position(a):
        if not a["open_count"]:
            return "No open risk"
        return "Above appetite" if a["breached"] else "Within appetite"

    report.add(
        Heading("Where the exposure sits"),
        Table("Top five open risks by inherent score",
              [Col("Risk", "title", weight=3.4), Col("Category", "category", weight=1.4), Col("Likelihood", "likelihood", "right", 0.9, "int"),
               Col("Impact", "impact", "right", 0.8, "int"), Col("Score", "score", "right", 0.8, "int"), Col("Status", "status", weight=1.1)],
              [{"title": r["title"], "category": label(r["category"]), "likelihood": r["likelihood"], "impact": r["impact"],
                "score": r["score"], "status": label(r["status"])} for r in stats.get("top_critical_risks") or []],
              empty_text="No open risk is recorded.", sheet_name="Top risks"),
        Table("Risks to watch: residual rating 15 or above",
              [Col("Ref", "ref", weight=1.1), Col("Risk", "title", weight=3), Col("Category", "category", weight=1.3), Col("Owner", "owner", weight=1.4),
               Col("Residual", "rrr", "right", 0.9, "int"), Col("Inherent", "irr", "right", 0.9, "int"),
               Col("Assurance %", "loa", "right", 1, "number")],
              [{"ref": r.get("risk_ref"), "title": r["title"], "category": label(r["category"]), "owner": r.get("owner_name") or "Unassigned",
                "rrr": r["rrr"], "irr": r.get("irr_score"), "loa": r.get("loa_pct")} for r in posture.get("high_rrr") or []],
              empty_text="No risk has a residual rating of 15 or above.", sheet_name="Watchlist"),
        Table("Risk appetite by category",
              [Col("Category", "category", weight=2), Col("Appetite limit", "limit", "right", 1, "int"),
               Col("Highest residual score", "highest", "right", 1.3, "int"), Col("Open risks", "open", "right", 0.9, "int"),
               Col("Position", "position", weight=1.4)],
              [{"category": label(a["category"]), "limit": a["max_score"], "highest": a["current_max_score"] if a["open_count"] else None,
                "open": a["open_count"], "position": position(a)} for a in sorted(appetite, key=lambda a: str(a["category"]))],
              empty_text="No risk appetite is set.", sheet_name="Appetite", max_rows=ROWS_IN_DOCUMENT))
    report.add(Callout("What these figures are", [
        "The headline measures count the enterprise risk register. The band chart counts the enterprise and platform registers together, "
        "as the Reports tab of the page does.",
        "Residual exposure is the residual rating where it has been assessed and the inherent rating where it has not.",
        "Added in the last 30 days counts the open risks created in that period; a risk closed since then is not counted."], kind="limit"))
    return report
