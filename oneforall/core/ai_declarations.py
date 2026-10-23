"""
What each place the platform calls a model says about itself (plans/2026-10-governance-rework/04 section 6).

`core.ai_policy.FEATURES` says which kinds of data a feature sends and is what an organization's policy is enforced
against. This module says the rest, once, so that a reviewer can read what a use case does without reading its code: its
task, which records it reads and what it leaves out, who starts it, what becomes of the answer, whether a person
reviews it before it counts, and what the person gets when the assistant is not available.

Each declaration describes what the code does today. tests/test_ai_declarations.py keeps the register complete, keeps
the vocabulary closed, and checks the two claims that can drift from the code: a feature that says "unavailable" has no
canned answer, and a feature that says "applied" is on the list of those that write without review.

The AI call policy (`ai_policy.authorize`) and the usage log (metadata only: who, feature, provider, model, tokens,
outcome) apply to every entry. Nothing here widens what a policy allows.
"""
from dataclasses import asdict, dataclass

from core.ai_policy import FEATURES

# What becomes of the answer, and whether a person reviews it before it counts.
APPROVAL = {
    "person": "Shown to the person who asked. Nothing is kept unless they save or apply it.",
    "beside_record": "Saved beside the record in its own AI field or as a separate AI record. The owner's own fields "
                     "are not changed.",
    "fills_empty": "Fills fields the owner left empty. It never replaces what a person wrote.",
    "applied": "Written into the data without a review step. A reviewer should check what it wrote.",
    "unattended": "Runs without a person and stores its result.",
}

# What the person gets when the assistant is off, refused by policy or failing.
FALLBACK = {
    "unavailable": "Nothing is generated or saved, and the person is told the assistant is not available.",
    "rules": "Ordinary rules or filters answer instead, and the answer says so.",
    "labelled": "A placeholder text that says it is a placeholder. It is not an analysis.",
    "template": "A fixed template, not generated for this record.",
    "empty": "Nothing is returned.",
    "defaults": "Neutral default values when the answer cannot be read, with the reason in the text.",
}


@dataclass(frozen=True)
class Declaration:
    task: str          # what it is for
    reads: str         # the record classes whose content goes into the prompt
    leaves_out: str    # what is deliberately not sent
    trigger: str       # who or what starts it
    output: str        # what is shown or stored
    approval: str      # a key of APPROVAL
    fallback: str      # a key of FALLBACK


def _d(*args) -> Declaration:
    return Declaration(*args)


_PERSON = "person"
_ASKED = "The question the person typed"

DECLARATIONS = {
    # ── ARIA and the platform core ──────────────────────────────────────────
    "aria.ask": _d("Answer a question from the policy library",
                   "Policy and control excerpts the person may open, chosen by the question",
                   "Anything the person may not open; a document that is not published", "ai_use.review (an AI Governance question)",
                   "An answer with citations, shown", "person", "unavailable"),
    "aria.generate_policy": _d("Draft a policy or procedure",
                               "The control, its framework and the person's own instructions",
                               "Other records and other organizations", "Module access to ARIA",
                               "A draft document that goes through the approval workflow", "beside_record", "unavailable"),
    "aria.generate_gap_analysis": _d("Write a gap analysis narrative for one framework",
                                     "Control references, names and statuses of that framework",
                                     "Evidence content and policy text", "Module access to ARIA", "Shown", "person",
                                     "unavailable"),
    "core.compose_briefing": _d("Summarize the day's governance advisories",
                                "The advisories already computed from the organization's records: severity, title, detail",
                                "Record content beyond those lines", "The daily advisory job, and the first Command Centre "
                                "read of the day by a super administrator", "A summary line saved with the day's briefing",
                                "unattended", "rules"),
    "core.generate_controls_for_framework": _d("Draft controls for a framework",
                                               "The framework's name, description and modules",
                                               "Every record of the organization", "manage_frameworks", "Shown as a list",
                                               "person", "unavailable"),
    "core.auto_map_controls": _d("Classify two ambiguous controls from different frameworks as equivalent, related or none",
                                 "The reference, name and description of two controls",
                                 "Evidence, status and owners", "Module access to ARIA, and only when the person ticks use AI",
                                 "Proposals remain outside IMS calculations until a different specialist reviews them",
                                 "person", "rules"),
    # ── BCM ─────────────────────────────────────────────────────────────────
    "bcm.review_plan": _d("Review one continuity plan",
                          "The plan's title and content", "Other plans and incidents", "bcm.plan.manage",
                          "A review record attached to the plan, with the person who asked and the provider", "beside_record",
                          "unavailable"),
    "bcm.suggest_incident_actions": _d("Suggest immediate actions for an incident",
                                       "The incident's title, type, severity and description, and the active frameworks",
                                       "Other incidents and plans", "bcm.ai.use", "Shown", "person", "unavailable"),
    "bcm.rag_ask": _d("Answer a question from uploaded continuity documents",
                      "Excerpts of the uploaded documents that match the question", "Documents that did not match",
                      "bcm.ai.use", "An answer with the chunks it cites, saved as a question and answer record",
                      "beside_record", "unavailable"),
    "bcm.chat": _d("Continuity assistant chat", _ASKED + " and the recent chat", "Records of the organization",
                   "bcm.ai.use", "The reply, saved in the person's chat history", "person", "labelled"),
    "bcm.generate_plan": _d("Draft a continuity plan from a scenario",
                            "The scenario, scope and industry the person entered", "Records of the organization",
                            "bcm.ai.use", "Shown as a draft", "person", "labelled"),
    "bcm.generate_board_narrative": _d("Write the continuity section of a board report",
                                       "Programme figures: counts and shares, no titles", "Record titles and content",
                                       "bcm.report.generate", "Shown", "person", "labelled"),
    # ── ERM ─────────────────────────────────────────────────────────────────
    "erm.score_risk": _d("Suggest a likelihood and impact for one risk",
                         "That risk's title, description and category", "Other risks", "erm.ai.use, and the risk must be "
                         "in the person's business unit", "A suggestion. The owner's score is changed only when a person "
                         "confirms it", "person", "unavailable"),
    "erm.suggest_scores": _d("Suggest scores against the organization's rating framework",
                             "The risk text the person typed and the rating scale", "Other risks", "erm.ai.use", "Shown",
                             "person", "unavailable"),
    "erm.suggest_treatment": _d("Suggest a treatment for a risk", "The risk text and scores the person typed",
                                "Other risks", "erm.ai.use", "Shown", "person", "unavailable"),
    "erm.suggest_ice_rationale": _d("Explain a rule-based control effectiveness score in one sentence",
                                    "The control's title and description and which rule factors pass",
                                    "Other controls", "erm.risk.view", "One sentence shown beside the score", "person",
                                    "empty"),
    "erm.generate_board_narrative": _d("Write the risk section of a board report",
                                       "Risk statistics and the categories in breach of appetite", "Risk titles",
                                       "erm.report.generate", "Shown", "person", "labelled"),
    "erm.chat": _d("Risk assistant chat", _ASKED + ", the recent chat and risk statistics", "Risk titles and content",
                   "erm.ai.use", "The reply, saved in the person's chat history", "person", "labelled"),
    "erm.generate_risk_statement": _d("Write a cause, event and consequence risk statement",
                                      "The category and description the person typed", "Other risks", "erm.ai.use",
                                      "Shown", "person", "unavailable"),
    "erm.suggest_assessment_questions": _d("Suggest questions for a risk assessment",
                                           "The assessment type, linked risk titles and existing questions",
                                           "Responses", "erm.ai.use", "Shown", "person", "unavailable"),
    "erm.identify_risks_from_responses": _d("Propose risks from assessment responses",
                                            "The assessment title and its responses (the first 3000 characters)",
                                            "Other assessments", "erm.ai.use",
                                            "Candidate risks shown; a person creates the ones they accept", "person",
                                            "unavailable"),
    "erm.smart_remediation_plan": _d("Propose a remediation plan for one risk",
                                     "That risk's title, description, category and score", "Other risks",
                                     "erm.ai.use, and the risk must be in the person's business unit", "Shown", "person",
                                     "unavailable"),
    "erm.scan_emerging_risks_grounded": _d("Scan approved public sources for emerging risks",
                                           "The organization's pillars, frameworks and top risk categories",
                                           "Risk titles and content", "An external-context scan started by a person or "
                                           "the weekly job", "Candidate items saved as unreviewed emerging risks with "
                                           "their cited source", "beside_record", "empty"),
    "erm.scan_emerging_risks": _d("Scan from the model's own knowledge for emerging risks",
                                  "The organization's pillars, frameworks and top risk categories",
                                  "Risk titles and content", "An external-context scan started by a person or the weekly "
                                  "job, when no grounded source is available", "Candidate items saved as unreviewed "
                                  "emerging risks, marked as from model knowledge", "beside_record", "empty"),
    "erm.generate_board_pack_narrative": _d("Write the narrative of a board pack",
                                            "The board pack's frozen snapshot and the list of references it may cite",
                                            "Anything outside the snapshot",
                                            "erm.boardpack.generate", "A narrative saved with the pack whose citations "
                                            "were each checked against the snapshot", "beside_record", "unavailable"),
    "erm.scenario_draft": _d("Draft a scenario from one sentence",
                             "The sentence the person typed (no email addresses or long numbers) and the titles and "
                             "categories of risks, controls and indicators in the person's business units",
                             "Descriptions, scores, evidence and records of other units",
                             "erm.scenario.manage and erm.ai.use",
                             "A proposal shown in the new scenario form. Only the records a person keeps are linked",
                             "person", "unavailable"),
    "erm.scenario_shocks": _d("Suggest likelihood, impact or control changes for a scenario's linked items",
                              "The scenario's title, assumptions and horizon, the linked risks and controls with "
                              "their baseline scores, and counts of past loss events",
                              "Descriptions, evidence and unlinked records", "erm.scenario.manage and erm.ai.use",
                              "Suggestions shown beside each item. A person accepts or edits each one; accepted ones "
                              "are marked as AI suggested", "person", "unavailable"),
    "erm.scenario_gaps": _d("Suggest records that a scenario may be missing",
                            "The scenario's title, description and assumptions and the titles of records not yet "
                            "linked, in the person's business units", "Descriptions, scores and evidence",
                            "erm.scenario.manage and erm.ai.use", "Suggestions shown. A person links the ones they accept",
                            "person", "unavailable"),
    "erm.scenario_explain": _d("Explain a scenario's impact result in plain language",
                               "The calculated result: headline, risk titles with baseline and scenario scores, "
                               "appetite and totals", "Descriptions, evidence and records outside the result",
                               "erm.scenario.manage and erm.ai.use",
                               "A summary and points shown, each tied to a risk or category in the result", "person",
                               "unavailable"),
    "erm.scenario_challenge": _d("Ask questions that test a scenario's assumptions",
                                 "The scenario's own fields, how many records of each type are linked, and the "
                                 "data quality issues found", "Record descriptions and evidence",
                                 "erm.scenario.manage and erm.ai.use", "Questions shown. Nothing is saved", "person",
                                 "unavailable"),
    # ── Evidence, Governance, AI Governance ─────────────────────────────────
    "evidence.api_evidence_suggest_links": _d("Suggest which controls and audits an evidence item belongs to",
                                              "The item's title, description, category and tags, and candidate "
                                              "control and audit names", "The file's content", "Any signed-in person who "
                                              "may open the item", "Suggestions shown; a person links the ones they accept",
                                              "person", "unavailable"),
    "evidence.find_evidence": _d("Read a question into Vault filters", _ASKED, "Every record and file content",
                                 "Any person using Find evidence", "Filters, shown and applied to the person's own "
                                 "scoped search", "person", "rules"),
    "governance.explain_ai_use": _d("Explain in words why an AI use has its status",
                                    "Facts already computed by rules about that AI use, each with an id",
                                    "Anything not in those facts", "ai_use.view", "An explanation citing fact ids, shown",
                                    "person", "rules"),
    "governance.run_drift_check": _d("Summarize a regulatory update against the controls it may touch",
                                     "The update's title and summary and the references of controls that match",
                                     "Control content beyond the reference", "governance.entities.manage, and the "
                                     "evidence expiry job", "A summary and a status on the regulatory update record",
                                     "applied", "rules"),
    # ── GRID ────────────────────────────────────────────────────────────────
    "grid.batch_risk_score": _d("Rate audit items by risk",
                                "Audit item names and descriptions of one checklist, with the framework name",
                                "Evidence and findings", "Checklist import by a person with GRID access",
                                "Suggested levels appear in the import preview. Imported levels start at Medium until a "
                                "person explicitly selects another level", "person", "defaults"),
    "grid.parse_checklist_with_ai": _d("Read a pasted compliance checklist into items",
                                       "The pasted text (the first 6000 characters)", "Everything else",
                                       "Checklist import by a person with GRID access", "Items shown for the person to "
                                       "import", "person", "unavailable"),
    "grid.generate_gap_analysis": _d("Write an audit gap analysis",
                                     "Control ids, names, statuses, risk levels and evidence counts of one audit",
                                     "Evidence content", "grid.ai.gap_analysis", "Shown", "person", "defaults"),
    "grid.suggest_control_details": _d("Suggest a description and evidence list for an audit control",
                                       "The control id, name and framework name", "Other controls",
                                       "grid.ai.gap_analysis", "Shown", "person", "defaults"),
    "grid.generate_report_narrative": _d("Write the executive summary of an audit report",
                                         "The audit's name, framework, completion figures and top critical gaps",
                                         "Finding text and evidence", "grid.ai.report",
                                         "Text placed in the generated report file", "person", "defaults"),
    "grid.ask_compliance_ai": _d("Audit assistant", _ASKED + " and the context the page passes",
                                 "Records of the organization", "grid.ai.gap_analysis", "Shown", "person", "unavailable"),
    "grid.generate_incident_checklist": _d("Draft an incident response checklist",
                                           "The incident's title, type, severity, description, data types and cause",
                                           "Other incidents", "grid.control.assign", "Checklist items shown", "person",
                                           "template"),
    # ── Platform pages ──────────────────────────────────────────────────────
    "launcher.api_predictive_risk": _d("Describe a predicted rise in risk",
                                       "Counts and trends computed by the platform's own prediction rules",
                                       "Record titles and content", "Any signed-in person, once per cache window",
                                       "An advisory shown on the Command Centre. A critical prediction is also put in "
                                       "the ERM emerging-risk inbox for a person to review; it does not create a risk",
                                       "beside_record", "rules"),
    "launcher.api_tasks_ai_prioritize": _d("Order a person's own open tasks",
                                           "Titles and due dates of the person's own tasks", "Tasks of other people",
                                           "Any signed-in person", "A suggested order, shown", "person", "unavailable"),
    "launcher.api_executive_summary": _d("Write a board narrative from the executive figures",
                                         "The figures of the frozen run that is being made: counts only",
                                         "Record titles, content and documents", "Any signed-in person, for the "
                                         "records they may open", "A draft narrative saved with the frozen run, marked "
                                         "not reviewed", "beside_record", "unavailable"),
    # ── ORM ─────────────────────────────────────────────────────────────────
    "orm.analyze_event": _d("Suggest a root cause and actions for one operational event",
                            "That event's title, type, severity, description and impact figures", "Other events",
                            "orm.ai.use, and the event must be in the person's business unit",
                            "Fills the corrective and preventive action and the root cause category when they were "
                            "empty", "fills_empty", "unavailable"),
    "orm.generate_trend_narrative": _d("Write the operational risk section of a board report",
                                       "Event statistics for the period: counts and amounts", "Event titles",
                                       "orm.report.generate", "Shown", "person", "labelled"),
    "orm.chat": _d("Operational risk assistant chat", _ASKED + " and the recent chat", "Records of the organization",
                   "orm.ai.use", "The reply, saved in the person's chat history", "person", "labelled"),
    # ── Sentinel (privacy) ──────────────────────────────────────────────────
    "sentinel.ai_research": _d("Research a privacy question", _ASKED, "Case records and personal data",
                               "sentinel.ai.assess", "Shown", "person", "unavailable"),
    "sentinel.ai_generate_full_dpia": _d("Draft the sections of a DPIA from its fields",
                                         "That DPIA's description and processing fields", "Other assessments",
                                         "sentinel.ai.assess", "Saved in the DPIA's own AI field, beside the assessor's "
                                         "text", "beside_record", "unavailable"),
    "sentinel.ai_suggest_risks": _d("Suggest privacy risks for a processing activity",
                                    "The processing description the person typed", "Other records",
                                    "sentinel.ai.assess", "Shown", "person", "unavailable"),
    "sentinel.ai_score_ropa": _d("Rate the risk of a processing record",
                                 "That record's processing fields", "Other records", "sentinel.ai.assess",
                                 "Saved in the record's AI fields", "beside_record", "unavailable"),
    "sentinel.ai_suggest_legal_basis": _d("Suggest a lawful basis for a processing purpose",
                                          "The purpose and categories the person typed", "Other records",
                                          "sentinel.ai.assess", "Shown. The lawful basis is the DPO's decision", "person",
                                          "unavailable"),
    "sentinel.ai_assess_breach": _d("Assess the likely impact of a breach",
                                    "That breach's description, data types and counts", "Other breaches",
                                    "sentinel.ai.assess", "Saved in the breach's AI assessment field. Notification "
                                    "duties are the DPO's decision", "beside_record", "unavailable"),
    "sentinel.ai_draft_dsr_response": _d("Draft a reply to a data subject request",
                                         "That request's type and description", "Other requests",
                                         "sentinel.ai.assess", "Saved in the request's AI draft field. A person sends "
                                         "the reply", "beside_record", "unavailable"),
    "sentinel.ai_generate_privacy_notice": _d("Draft a privacy notice from the person's entries",
                                              "The organization and processing details the person typed", "Case records",
                                              "sentinel.ai.assess", "Shown", "person", "unavailable"),
    "sentinel.ai_vendor_check": _d("Assess a vendor's data protection posture",
                                   "That vendor's record fields", "Other vendors", "sentinel.ai.assess",
                                   "Saved in the vendor's AI assessment field", "beside_record", "unavailable"),
    "sentinel.ai_chat": _d("Privacy assistant chat", _ASKED, "Case records and personal data", "sentinel.ai.assess",
                           "Shown", "person", "unavailable"),
    "sentinel.ai_gap_analysis": _d("Compare compliance across several regulations",
                                   "The regulations the person selected and the answers they typed", "Case records",
                                   "sentinel.ai.assess", "Shown", "person", "unavailable"),
}


def declaration(feature: str) -> dict:
    """The declaration of one feature as a plain dict, with the words for its approval and fallback."""
    d = DECLARATIONS[feature]
    label, categories = FEATURES[feature]
    out = asdict(d)
    out.update(feature=feature, label=label, categories=list(categories),
               approval_words=APPROVAL[d.approval], fallback_words=FALLBACK[d.fallback])
    return out


# The features that write into the data without a review step. A change to this set is a decision, not a refactor.
WRITES_WITHOUT_REVIEW = frozenset(k for k, d in DECLARATIONS.items() if d.approval == "applied")
