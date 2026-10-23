"""Render recorded profile answers and missing-field signals in scoped documents.

The wording describes the stored record. A gap is a review prompt, never an
automated conclusion that a legal duty has been met or breached.
"""
from core.report_kit.model import Callout, Col, Heading, Table
from modules.sentinel.record_profiles import get_profile
from modules.sentinel.record_profiles.model import flat_text, is_empty


def _answer(field, value):
    if is_empty(value):
        return "Not recorded"
    if field.kind == "bool":
        return "Yes" if value in (True, 1, "1", "true") else "No"
    return flat_text(value)


def add_profile_sections(report, kind: str, record: dict):
    profile = get_profile(kind, record.get("regulation"))
    made, needed = profile.completeness(record)
    gaps = profile.gaps(record)
    report.add(Heading("Record readiness"), Callout("Review before external use", [
        f"{made} of {needed} applicable profile fields have an answer. This is completeness, not a compliance score.",
        f"Jurisdiction: {profile.regime['name']}; legal wording status: {profile.regime['status']}.",
        profile.regime["record_basis"],
        ("The independent AI decision is recorded separately in AI Governance Decisions."
         if kind == "aiia" else "A privacy specialist must review the facts, citations and jurisdiction before filing."),
    ], kind="limit"))
    report.add(Table("Answers still needed", [Col("Section", "section"), Col("Field", "field"), Col("Reference", "anchor")],
                     [{"section": gap.section, "field": gap.label, "anchor": gap.anchor or "Not verified"} for gap in gaps],
                     empty_text="No required profile field is blank. Specialist review is still needed.", sheet_name="Record gaps"))
    for section in profile.sections:
        fields = [field for field in section.fields if field.store == "details" and profile.applies(field, record)]
        if not fields:
            continue
        report.add(Table(section.label,
                         [Col("Question", "question", weight=2), Col("Recorded answer", "answer", weight=4),
                          Col("Reference", "anchor", weight=1.2)],
                         [{"question": profile.label(field), "answer": _answer(field, record.get(field.key)),
                           "anchor": profile.anchor(field) or "Not verified"} for field in fields],
                         sheet_name=section.label[:28]))
