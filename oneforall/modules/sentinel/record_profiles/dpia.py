"""DPIA record definition shared by the form, readiness view and document.

Legal references are resolved by the selected regime. An empty anchor means the
specific duty has not been verified for that regime, not that it does not exist.
"""

from modules.sentinel.record_profiles.model import Cond, Field, Section


def sections() -> tuple:
    return (
        Section("screening", "Screening and accountability", (
            Field("title", "Assessment title", store="column", required=True),
            Field("regulation", "Jurisdiction", store="column", required=True),
            Field("owner", "Assessment owner", store="column", required=True),
            Field("due_date", "Next review or completion due", "date", store="column"),
            Field("screening_reason", "Why an impact assessment is needed", "longtext", required=True,
                  anchor="screening_cases"),
            Field("screening_decision", "Screening decision", "select", options=("required", "prudent", "not_required")),
            Field("screening_approved_by", "Who confirmed the screening decision"),
            Field("screening_date", "Screening date", "date"),
            Field("assessor_role", "Assessor role and independence"),
        )),
        Section("processing", "Processing and data flow", (
            Field("activity_desc", "Processing operations", "longtext", store="column", required=True,
                  anchor="systematic"),
            Field("purpose", "Purpose", "longtext", store="column", required=True),
            Field("data_subjects", "People affected", store="column", required=True),
            Field("data_categories", "Personal data categories", "multiselect", store="column", json_list=True,
                  required=True),
            Field("special_cats", "Special category data", "multiselect", store="column", json_list=True),
            Field("data_flow", "Collection, use, storage and deletion flow", "longtext", required=True),
            Field("data_sources", "Sources of the data", "longtext"),
            Field("sharing_parties", "Recipients and sharing arrangements", "longtext"),
            Field("intl_transfer", "International transfer", store="column"),
            Field("transfer_dest", "Transfer destination", store="column", when=Cond("intl_transfer", "transfers")),
            Field("transfer_mech", "Transfer safeguard", store="column", when=Cond("intl_transfer", "transfers")),
            Field("retention", "Retention and deletion", store="column"),
        )),
        Section("necessity", "Necessity and proportionality", (
            Field("legal_basis", "Lawful basis", "select", store="column", list_name="lawful_bases", required=True),
            Field("necessity", "Why the processing is necessary", "longtext", store="column", required=True,
                  anchor="necessity"),
            Field("proportionality", "Why the extent of processing is proportionate", "longtext", store="column",
                  required=True, anchor="necessity"),
            Field("alternatives", "Less intrusive alternatives considered", "longtext"),
            Field("rights_controls", "How people exercise their rights", "longtext", anchor="rights"),
        )),
        Section("risks", "Risks and controls", (
            Field("risks", "Identified risks to people", "multiselect", store="column", json_list=True,
                  required=True, anchor="risks"),
            Field("overall_risk", "Overall risk before controls", "select", store="column", list_name="three_levels"),
            Field("mitigations", "Measures and controls", "longtext", store="column", required=True,
                  anchor="measures"),
            Field("residual_risk", "Risk after controls", "select", store="column", list_name="three_levels"),
            Field("risk_owner", "Owner of the remaining risk"),
            Field("risk_acceptance_reason", "Reason for accepting remaining risk", "longtext"),
        )),
        Section("consultation", "Consultation and decision", (
            Field("dpo_consulted", "Data protection officer consulted", "bool", store="column", anchor="dpo_advice"),
            Field("dpo_advice", "Data protection officer advice", "longtext", anchor="dpo_advice"),
            Field("subjects_consulted", "People or representatives consulted", "bool", store="column",
                  anchor="subject_views"),
            Field("consult_notes", "Consultation record and differing views", "longtext", store="column"),
            Field("auth_consulted", "Supervisory authority consulted", "bool", store="column",
                  anchor="prior_consultation"),
            Field("consultation_decision", "Prior consultation decision and rationale", "longtext",
                  anchor="prior_consultation"),
            Field("decision", "Assessment conclusion and conditions", "longtext", required=True),
            Field("decision_by", "Independent decision maker"),
            Field("decision_date", "Decision date", "date"),
            Field("review_trigger", "What will trigger a reassessment", "longtext", anchor="review_dpia"),
        )),
    )
