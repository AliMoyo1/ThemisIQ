"""
One AI impact assessment as a document on the report kit.

Built from the assessment `assessments.get_assessment` returns: the record the AI Governance page opens, read through the caller's capability
and business unit scope. A system or a privacy record the reader may not open arrives marked `restricted` and is not named. The scores
and the classification are the stored ones, and an impact dimension that is not scored reads `n/a` and is counted as not scored. The last
section lists the records connected to the assessment (the AI system, the privacy records it cites, other assessments of the same
system, linked records, the system's evidence), each one the reader may open.
"""
from core.report_kit import theme
from core.report_kit.helpers import facts_table, label, lines
from core.report_kit.model import Callout, Chart, Col, Heading, Kpi, Kpis, Paragraphs, Report, Table
from core.timeutils import utcnow
from database import get_db
from modules.governance import connected_records
from modules.launcher import report_documents as documents
from modules.sentinel.record_profiles.document import add_profile_sections

KEY = ("sentinel", "aiia")            # the stored identity of an assessment (saved links and evidence keep working)


def _named(record) -> "str | None":
    """`REF Title` of a linked privacy record, or None when none is linked or the reader may not open it (it is not named)."""
    if not record or record.get("restricted"):
        return None
    return " ".join(part for part in (record.get("ref"), record.get("title")) if part) or None


def _score(row) -> "int | None":
    return int(row["likelihood"]) * int(row["impact"]) if row["likelihood"] is not None and row["impact"] is not None else None


def _connections(db, a) -> dict:
    direct = []
    if a.get("application_id"):
        direct.append((("governance", "application"), a["application_id"], "assesses"))
    direct += [(("sentinel", "ropa"), a["ropa_id"], "cites")] if a.get("ropa_id") else []
    direct += [(("sentinel", "dpia"), a["dpia_id"], "cites")] if a.get("dpia_id") else []
    cited_by = []
    if a.get("application_id"):
        cited_by = [(KEY, r[0], "assesses the same AI system")
                    for r in db.execute("SELECT id FROM sentinel_aiia WHERE application_id = %s AND id != %s ORDER BY id",
                                        (a["application_id"], a["id"])).fetchall()]
    # the files of the records this assessment rests on (the Vault does not attach files to an assessment itself)
    evidence = [(("governance", "application"), a["application_id"])] if a.get("application_id") else []
    evidence += [(("sentinel", "ropa"), a["ropa_id"])] if a.get("ropa_id") else []
    evidence += [(("sentinel", "dpia"), a["dpia_id"])] if a.get("dpia_id") else []
    return {"direct": direct, "cited_by": cited_by, "evidence": evidence}


def build(user, a, now=None) -> Report:
    """The assessment `a` (as `get_assessment` returns it) for the person `user`, who may already open it."""
    now = now or utcnow()
    meta = documents.module_meta(user, "ai_governance", "AI impact assessment", a.get("title") or "Untitled assessment", theme.OPERATIONAL, now)
    meta.section, meta.reference = "Assessments", ", ".join(part for part in (a.get("ref_number"), f"version {a['version']}" if a.get("version") else "") if part)
    report = Report(meta)
    impacts = a.get("impacts") or []
    scored = [r for r in impacts if r["applicable"] and _score(r) is not None]
    unscored = [r for r in impacts if r["applicable"] and _score(r) is None]
    not_applicable = [r for r in impacts if not r["applicable"]]
    overall, residual = a.get("overall_classification"), a.get("residual_classification")
    report.add(Heading("Assessment at a glance"), Kpis([
        Kpi("Status", label(a.get("status"))),
        Kpi("Overall classification", label(overall) if overall else "n/a",
            "no rating framework is active" if overall == "unrated" else ("from the scored impacts" if overall else "nothing is scored yet")),
        Kpi("Residual classification", label(residual) if residual else "n/a", "after the mitigation" if residual else "not assessed"),
        Kpi("Autonomy", label(a.get("autonomy_level")) if a.get("autonomy_level") else "n/a"),
        Kpi("Deployment", label(a.get("deployment_env")) if a.get("deployment_env") else "n/a"),
        Kpi("Third party AI", "Yes" if a.get("third_party") else "No", "", "warn" if a.get("third_party") else "neutral"),
    ]))

    ranked = sorted(scored, key=lambda r: (-_score(r), r["dimension_name"]))
    top = ranked[0] if ranked else None
    report.add(
        Chart("bar", "Impact score by dimension", [(r["dimension_name"], _score(r)) for r in ranked],
              x_label="Likelihood times impact (1 to 25)", y_label="Dimension", unit="points", half=True, max_value=25,
              takeaway=(f"{top['dimension_name']} scores highest: {int(top['likelihood'])} times {int(top['impact'])}, {_score(top)} of 25." if top else ""),
              empty_text="No impact dimension is scored yet."),
        Chart("donut", "Impact dimensions by state",
              [("Scored", len(scored)), ("Applies, not yet scored", len(unscored)), ("Does not apply", len(not_applicable))],
              unit="dimensions", half=True, centre=f"{len(scored)}/{len(impacts)}" if impacts else "",
              takeaway=(f"{len(scored)} of {len(impacts)} dimensions are scored."
                        + (f" {len(unscored)} still {'needs' if len(unscored) == 1 else 'need'} a score." if unscored else "")) if impacts else "",
              empty_text="No impact dimension is defined."))

    report.add(Heading("Impact by dimension"),
               Table("Likelihood and impact, each from 1 to 5",
                     [Col("Dimension", "dim", weight=1.5), Col("Applies", "applies", weight=0.8), Col("Likelihood", "l", weight=0.9, align="right"),
                      Col("Impact", "i", weight=0.8, align="right"), Col("Score", "s", weight=0.7, align="right"), Col("Reasoning", "why", weight=3.2)],
                     [{"dim": r["dimension_name"], "applies": "Yes" if r["applicable"] else "No", "l": r["likelihood"], "i": r["impact"],
                       "s": _score(r), "why": r["description"]} for r in impacts], sheet_name="Impacts"))

    system = a.get("application") or {}
    report.add(Heading("The AI system"), facts_table("What it is and where it runs", [
        ("AI system", a.get("ai_system_name")), ("Registered system", None if system.get("restricted") else system.get("name")),
        ("Business unit", a.get("business_unit")), ("Department", a.get("department")), ("Owner", a.get("owner")),
        ("Business process", a.get("business_process")),
        ("Deployment", label(a.get("deployment_env")) if a.get("deployment_env") else None),
        ("Autonomy", label(a.get("autonomy_level")) if a.get("autonomy_level") else None),
        ("Third party AI", ("Yes. " + (a.get("third_party_details") or "")).strip() if a.get("third_party") else "No"),
        ("Influences customers", "Yes" if a.get("influences_customers") else "No"),
        ("Uses sensitive data", "Yes" if a.get("sensitive_data") else "No"),
        ("Data categories", ", ".join(a.get("data_categories") or []) or "None recorded"),
        ("Record of processing", _named(a.get("ropa"))), ("Data protection impact assessment", _named(a.get("dpia"))),
    ], sheet_name="System"))
    for title, text in (("What the system does", a.get("system_description")), ("Outputs and decisions", a.get("outputs_decisions")),
                        ("Who is affected, directly", a.get("stakeholders_direct")), ("Who is affected, indirectly", a.get("stakeholders_indirect")),
                        ("Mitigation measures", a.get("mitigation_measures"))):
        report.add(Paragraphs(title, lines(text) or ["Not recorded."]))

    add_profile_sections(report, "aiia", a)

    db = get_db()
    try:
        report.add(*connected_records.section(db, user, KEY, a["id"], **_connections(db, a)))
    finally:
        db.close()

    report.add(Callout("What this document is", [
        "It states what the assessment records on the date above: the scores are the assessor's own and the classification follows from them.",
        "It is not an approval. Whether the system may be used is a decision for the AI governance function.",
    ], kind="limit"))
    return report
