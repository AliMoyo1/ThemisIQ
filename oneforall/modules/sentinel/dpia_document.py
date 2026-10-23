"""
One data protection impact assessment (DPIA) as a document on the report kit.

Built from the record `data_service.get_dpia` returns, the same record the Privacy page opens, and handed in by the route only after the
caller's business unit scope let them open it. Nothing is computed twice: the ratings, the risk lines and the text are the stored values,
a missing one reads `Not recorded` or `n/a`, and the text an AI assistant wrote is marked as such. The last section lists the records
connected to this one (the RoPA entry it assesses, the assessments that cite it, linked records, evidence), each one the reader may open.
"""
import re
from collections import Counter

from core.report_kit import identity, markdown, theme
from core.report_kit.helpers import SEVERITY_COLOUR, facts_table, label, lines, severity_rows
from core.report_kit.model import Callout, Chart, Col, Heading, Kpi, Kpis, Paragraphs, Report, Table
from core.timeutils import utcnow
from database import get_db
from modules.governance import connected_records
from modules.launcher import report_documents as documents
from modules.sentinel.record_profiles.document import add_profile_sections

LEVEL = {"low": 1, "medium": 2, "high": 3}
TONE = {"low": "good", "medium": "warn", "high": "bad"}
_RATED = re.compile(r"\(\s*likelihood:\s*(\w+)\s*[,;]\s*impact:\s*(\w+)\s*\)", re.I)
KEY = ("sentinel", "dpia")


def _flag(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


def _consulted(value) -> str:
    return "Yes" if _flag(value) else "Not recorded"


def _rating(value) -> str:
    return str(value or "").strip().lower()


def risk_rows(raw) -> list:
    """The identified risks, one per line of the stored list (the form saves one text with a line for each risk). A line written as
    `Text (Likelihood: Medium, Impact: High)` gives its two ratings; a line without them is a risk with none recorded."""
    rows = []
    for line in lines(raw):
        line = line.strip(" -•\t")
        if not line:
            continue
        found = _RATED.search(line)
        text = _RATED.sub(" ", line).strip() if found else line
        rows.append({"risk": text, "likelihood": label(found.group(1).lower()) if found else None,
                     "impact": label(found.group(2).lower()) if found else None})
    return rows


def _level_row(text, level):
    return f"{text}: {label(level)}" if level else f"{text}: not recorded"


def _connections(db, d) -> dict:
    """What this DPIA points at and what points at it, as the arguments `connected_records.section` takes: the RoPA entry it assesses
    (named on the DPIA, or naming the DPIA) and its files, and the AI impact assessments that cite it."""
    entries = [d["ropa_id"]] if d.get("ropa_id") else []
    entries += [r[0] for r in db.execute("SELECT id FROM sentinel_ropa WHERE dpia_id = %s ORDER BY id", (d["id"],)).fetchall()
                if r[0] not in entries]
    cited_by = [(("sentinel", "aiia"), r[0], "is cited by")
                for r in db.execute("SELECT id FROM sentinel_aiia WHERE dpia_id = %s ORDER BY id", (d["id"],)).fetchall()]
    return {"direct": [(("sentinel", "ropa"), i, "assesses") for i in entries], "cited_by": cited_by,
            "evidence": [(("sentinel", "ropa"), i) for i in entries]}


def build(user, d, now=None) -> Report:
    """The DPIA `d` (as `get_dpia` returns it) for the person `user`, who may already open it."""
    now = now or utcnow()
    meta = documents.module_meta(user, "sentinel", "Data protection impact assessment", d.get("title") or "Untitled DPIA", theme.OPERATIONAL, now)
    meta.section, meta.reference = "DPIA Assessments", d.get("ref_number") or ""
    report = Report(meta)
    overall, residual = _rating(d.get("overall_risk")), _rating(d.get("residual_risk"))
    cats, special = lines(d.get("data_categories")), lines(d.get("special_cats"))
    risks = risk_rows(d.get("risks"))

    tiles = [
        Kpi("Status", label(d.get("status"))),
        Kpi("Overall risk", label(overall) if overall else "n/a", "before the measures" if overall else "not rated", TONE.get(overall, "neutral")),
        Kpi("Residual risk", label(residual) if residual else "n/a", "after the measures" if residual else "not rated", TONE.get(residual, "neutral")),
        Kpi("DPO consulted", _consulted(d.get("dpo_consulted")), "", "good" if _flag(d.get("dpo_consulted")) else "warn"),
        Kpi("Authority consulted", _consulted(d.get("auth_consulted"))),
        Kpi("Data subjects", str(d.get("subject_count") or "n/a"), "approximate" if d.get("subject_count") else ""),
    ]
    if d.get("owner"):                  # the assessor or owner the form records
        tiles.append(Kpi("Assessor or owner", str(d["owner"])))
    due = identity.to_utc(d.get("due_date"))
    if due is not None:
        late = due.date() < now.date() and _rating(d.get("status")) not in ("completed", "approved")
        tiles.append(Kpi("Due date", identity.format_day(d["due_date"]), "past the due date" if late else "", "bad" if late else "neutral"))
    report.add(Heading("Assessment at a glance"), Kpis(tiles))

    if overall in LEVEL and residual in LEVEL:
        gap = LEVEL[overall] - LEVEL[residual]
        take = (f"The measures lower the rated risk from {label(overall)} to {label(residual)}." if gap > 0 else
                f"The measures leave the rated risk at {label(residual)}." if gap == 0 else
                f"The residual risk ({label(residual)}) is rated above the overall risk ({label(overall)}): check the ratings.")
    else:
        take = "Both the overall and the residual risk need a rating before the measures can be compared."
    impact_counts = Counter(_rating(r["impact"]) for r in risks)
    impact_rows, impact_colours = severity_rows(impact_counts)
    rated = sum(n for level, n in impact_counts.items() if level)
    high_impact = impact_counts.get("high", 0) + impact_counts.get("critical", 0)
    unrated = impact_counts.get("", 0)
    impact_take = ""
    if risks:
        impact_take = (f"{identity.fmt_int(high_impact)} of {identity.plural(rated, 'rated risk')} {'has' if high_impact == 1 else 'have'} a high impact."
                       if rated else "No impact is recorded for any identified risk.")
        if unrated and rated:
            impact_take += f" {identity.plural(unrated, 'risk')} {'has' if unrated == 1 else 'have'} no impact recorded."
    report.add(
        Chart("bar", "Risk level before and after the measures",
              [(_level_row("Before the measures", overall), LEVEL.get(overall)), (_level_row("After the measures", residual), LEVEL.get(residual))],
              x_label="Risk level (1 low, 2 medium, 3 high)", y_label="Stage", unit="level", half=True, max_value=3, takeaway=take,
              colours=[SEVERITY_COLOUR.get(overall, theme.SILVER_LIGHT), SEVERITY_COLOUR.get(residual, theme.SILVER_LIGHT)],
              empty_text="No risk rating is recorded."),
        Chart("bar", "Identified risks by impact", impact_rows, x_label="Number of risks", y_label="Impact", unit="risks", half=True,
              colours=impact_colours, takeaway=impact_take, empty_text="No risk is recorded for this assessment."))
    if cats or special:
        report.add(Chart("donut", "Personal data in scope by kind",
                         [("Ordinary data categories", len(cats)), ("Special category data", len(special))],
                         unit="categories", half=True, centre=f"{len(cats) + len(special)}",
                         takeaway=(f"{len(special)} of {len(cats) + len(special)} data categories are special category data." if special
                                   else "No special category data is recorded."),
                         empty_text="No data category is recorded."))

    controller = d.get("controller_name") or d.get("org_name")       # the form does not ask for it: shown when the record holds it
    transfer = _rating(d.get("intl_transfer")) in ("yes", "planned")
    report.add(Heading("The processing"), facts_table("What is processed, why and how", [
        ("Purpose", d.get("purpose")), ("Description", d.get("activity_desc") or d.get("description")),
        ("Type of activity", d.get("activity_type")), ("Legal basis", d.get("legal_basis")), ("Regulation", d.get("regulation")),
        *((("Controller", controller),) if controller else ()), ("Data subjects", d.get("data_subjects")),
        ("Approximate number of data subjects", d.get("subject_count")), ("Data categories", ", ".join(cats)),
        ("Special category data", ", ".join(special) or "None recorded"), ("Retention", d.get("retention")), ("Systems", d.get("systems")),
        ("Processors", d.get("processors")), ("International transfer", d.get("intl_transfer")),
        *((("Transfer destination", d.get("transfer_dest")), ("Transfer mechanism", d.get("transfer_mech"))) if transfer else ()),
    ], sheet_name="Processing"))

    report.add(Heading("Risks, necessity and measures"),
               Table("Identified risks", [Col("Risk", "risk", weight=4.0), Col("Likelihood", "likelihood", weight=1.1), Col("Impact", "impact", weight=1.1)],
                     risks, empty_text="No risk is recorded for this assessment.", sheet_name="Risks"))
    for title, text in (("Necessity", d.get("necessity")), ("Proportionality", d.get("proportionality")), ("Measures and controls", d.get("mitigations"))):
        report.add(Paragraphs(title, lines(text) or ["Not recorded."]))

    dpo = " ".join(part for part in (d.get("dpo_name") and f"Data protection officer: {d['dpo_name']}.",
                                     d.get("dpo_email") and f"Contact: {d['dpo_email']}.") if part)
    consult = [("The data protection officer is recorded as consulted." if _flag(d.get("dpo_consulted"))
                else "No consultation of the data protection officer is recorded.") + (f" {dpo}" if dpo else ""),
               "The supervisory authority is recorded as consulted." if _flag(d.get("auth_consulted"))
               else "No consultation of the supervisory authority is recorded.",
               "Data subjects or their representatives are recorded as consulted." if _flag(d.get("subjects_consulted"))
               else "No consultation of data subjects or their representatives is recorded."]
    consult += lines(d.get("consult_notes"))
    report.add(Heading("Consultation"), Paragraphs("Who was consulted", consult))

    add_profile_sections(report, "dpia", d)

    if str(d.get("ai_full_dpia") or "").strip():
        report.add(Heading("Full assessment text", "Written by the AI assistant from the assessment data."))
        first = True
        for block in markdown.blocks(d["ai_full_dpia"], "Draft text"):
            if isinstance(block, Paragraphs) and first:
                block.label, first = "Written by the AI assistant. The application does not record that a person reviewed it.", False
            report.add(block)

    db = get_db()
    try:
        report.add(*connected_records.section(db, user, KEY, d["id"], **_connections(db, d)))
    finally:
        db.close()

    report.add(Callout("What this document is", [
        "It states what is recorded in the assessment on the date above. It is not legal advice.",
        "Whether the residual risk is acceptable, and whether the supervisory authority must be consulted first, are decisions for the data "
        "protection officer and the controller.",
    ], kind="limit"))
    return report
