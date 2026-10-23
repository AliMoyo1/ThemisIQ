"""
One business continuity plan as a document on the report kit.

Built from the plan the Resilience page opens (`data_service.get_plan`, handed in by the route only after the caller's business unit scope
let them open it), the processes it covers with their recovery time objectives (`list_bia_plan_links`, which leaves out a process the
caller may not open), its AI reviews, its activation history and the text of the plan. Nothing is computed twice: a figure that is not
recorded reads `n/a`. The last section lists the records connected to the plan (the exercises that tested it, the incidents it was
activated for, linked records, evidence), each one the reader may open.
"""
from core.report_kit import identity, markdown, theme
from core.report_kit.helpers import SEVERITY_COLOUR, facts_table, label
from core.report_kit.model import Callout, Chart, Col, Heading, Kpi, Kpis, Report, Table
from core.timeutils import utcnow
from database import get_db
from modules.bcm import data_service as ds
from modules.governance import connected_records
from modules.governance.data_service import bu_scope_ids
from modules.launcher import report_documents as documents

KEY = ("bcm", "plan")


def _review_kpi(plan, now) -> Kpi:
    due = identity.to_utc(plan.get("next_review"))
    if due is None:
        return Kpi("Next review", "n/a", "no date is set", "warn")
    days = (due.date() - now.date()).days
    return Kpi("Next review", identity.format_day(plan["next_review"]),
               f"{abs(days)} days overdue" if days < 0 else f"in {days} days", "bad" if days < 0 else "neutral")


def _connections(db, plan, covered, activations) -> dict:
    """The exercises that name this plan and the incidents it was activated for, as the arguments `connected_records.section` takes."""
    exercises = db.execute("SELECT id, status FROM bcm_exercises WHERE plan_id = %s ORDER BY id", (plan["id"],)).fetchall()
    cited = [(("bcm", "exercise"), r["id"], f"is tested by ({label(r['status']).lower()})") for r in exercises]
    cited += [(("bcm", "incident"), i, "was activated for") for i in sorted({a["incident_id"] for a in activations if a.get("incident_id")})]
    return {"cited_by": cited, "evidence": [(("bcm", "bia"), c["bia_id"]) for c in covered],     # the files of each covered process
            "skip": {(("bcm", "bia"), c["bia_id"]) for c in covered}}                           # the processes are in the coverage table


def build(user, plan, now=None) -> Report:
    """The plan `plan` (as `get_plan` returns it) for the person `user`, who may already open it."""
    now = now or utcnow()
    meta = documents.module_meta(user, "bcm", "Business continuity plan", plan.get("title") or "Untitled plan", theme.OPERATIONAL, now)
    meta.section, meta.reference = "Plans", f"Plan {plan['id']}, version {plan.get('version') or 'n/a'}"
    report = Report(meta)
    covered = ds.list_bia_plan_links(plan_id=plan["id"], bu_scope=bu_scope_ids(user))
    reviews, activations = ds.list_plan_reviews(plan["id"]), ds.list_plan_activations(plan["id"])

    report.add(Heading("Plan at a glance"), Kpis([
        Kpi("Status", label(plan.get("status"))),
        Kpi("Version", str(plan.get("version") or "n/a")),
        Kpi("Process or unit owner", str(plan.get("owner") or "n/a")),
        Kpi("Last reviewed", identity.format_day(plan.get("last_reviewed")) or "n/a"),
        _review_kpi(plan, now),
        Kpi("In force", "Active plan" if plan.get("is_active_plan") else "Not activated", "", "warn" if plan.get("is_active_plan") else "neutral"),
    ]))

    timed = sorted((c for c in covered if c.get("rto_hours") is not None), key=lambda c: (c["rto_hours"], c["process_name"]))
    untimed = len(covered) - len(timed)
    tight = timed[0] if timed else None
    take = (f"The tightest objective is {tight['process_name']}: {identity.plural(tight['rto_hours'], 'hour')}." if tight else "")
    if untimed and tight:
        take += f" {identity.plural(untimed, 'covered process')} {'has' if untimed == 1 else 'have'} no recovery time objective recorded."
    scored = [r for r in reviews if r.get("overall_score") is not None][::-1]
    report.add(
        Chart("bar", "Recovery time objective of each process the plan covers", [(c["process_name"], c["rto_hours"]) for c in timed],
              x_label="Hours to recover", y_label="Process", unit="hours", half=True,
              colours=[SEVERITY_COLOUR.get(str(c.get("criticality") or "").lower(), theme.SILVER_LIGHT) for c in timed], takeaway=take,
              empty_text="No process with a recovery time objective is linked to this plan."),
        Chart("line", "AI review score of the plan over time", [(identity.format_day(r["created_at"]), r["overall_score"]) for r in scored],
              x_label="Review date", y_label="Score out of 100", unit="points", half=True, max_value=100,
              takeaway=(f"The latest score is {scored[-1]['overall_score']} out of 100." if scored else ""),
              empty_text="The plan has not been reviewed by the AI assistant."))

    description = str(plan.get("description") or "").strip()
    # a plan made from a description alone stores it as its text too: shown once, as the plan, and not again as a description
    described = [] if description and description == str(plan.get("content") or "").strip() else [("Description", description)]
    report.add(Heading("Scope and coverage"),
               facts_table("The plan", [("Type", plan.get("plan_type")), ("Department", plan.get("department")), ("Scope", plan.get("scope")),
                                         ("Review frequency", label(plan.get("review_frequency")) if plan.get("review_frequency") else None),
                                         *described], sheet_name="Plan"),
               Table("Processes this plan covers", [Col("Process", "process", weight=2.4), Col("Criticality", "criticality", weight=1.1),
                                                     Col("Recovery time objective (hours)", "rto", weight=1.3, align="right", kind="int"),
                                                     Col("Cover", "cover", weight=1.0)],
                     [{"process": c["process_name"], "criticality": label(c.get("criticality")) if c.get("criticality") else None,
                       "rto": c.get("rto_hours"), "cover": label(c.get("coverage_type"))}
                      for c in sorted(covered, key=lambda c: (c["rto_hours"] is None, c["rto_hours"] or 0, c["process_name"]))],
                     empty_text="No business impact analysis is linked to this plan, or none that you may open.", sheet_name="Coverage"))
    if activations:
        report.add(Table("Activation history", [Col("Date", "date", weight=1.2, kind="date"), Col("Action", "action", weight=1.0),
                                                Col("Reason", "reason", weight=3.0), Col("By", "by", weight=1.4)],
                         [{"date": a.get("created_at"), "action": label(a.get("action")), "reason": a.get("reason"), "by": a.get("activated_by")}
                          for a in activations], sheet_name="Activations"))
    if str(plan.get("content") or "").strip():
        report.add(Heading("The plan"), *markdown.blocks(plan["content"], "Plan text"))

    db = get_db()
    try:
        report.add(*connected_records.section(db, user, KEY, plan["id"], **_connections(db, plan, covered, activations)))
    finally:
        db.close()

    report.add(Callout("What this document is", [
        "It is the text of the plan as held in ThemisIQ on the date above, with the coverage and review figures recorded against it.",
        "It does not say that the plan works. The exercises under Connected records show when it was tested.",
    ], kind="limit"))
    return report
