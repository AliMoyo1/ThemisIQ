"""AI impact assessment definition used by AI Governance.

These are internal assurance questions, not a claim that a jurisdiction requires
this exact form. Statutory classification stays with the regulation workflow.
"""

from modules.sentinel.record_profiles.model import Field, Section


def sections() -> tuple:
    return (
        Section("identity", "Use and accountability", (
            Field("title", "Assessment title", store="column", required=True),
            Field("ai_system_name", "AI system", store="column", required=True),
            Field("owner", "Accountable owner", store="column", required=True),
            Field("business_process", "Business process", store="column"),
            Field("intended_use", "Intended use and boundaries", "longtext", required=True),
            Field("prohibited_use", "Uses that are not permitted", "longtext"),
            Field("model_provider", "Model or provider identity"),
            Field("model_version", "Model version and release"),
        )),
        Section("context", "People, data and decisions", (
            Field("system_description", "How the system works", "longtext", store="column", required=True),
            Field("outputs_decisions", "Outputs and decisions", "longtext", store="column", required=True),
            Field("stakeholders_direct", "People directly affected", "longtext", store="column"),
            Field("stakeholders_indirect", "People indirectly affected", "longtext", store="column"),
            Field("data_categories", "Data categories", "multiselect", store="column", json_list=True),
            Field("data_provenance", "Data origin, permission and quality", "longtext"),
            Field("privacy_linkage", "Privacy assessment and processing record rationale", "longtext"),
            Field("deployment_context", "Where and by whom the model is used", "longtext"),
        )),
        Section("impact", "Impact and safeguards", (
            Field("harm_scenarios", "Foreseeable harms and affected groups", "longtext", required=True),
            Field("fairness_evaluation", "Fairness and bias evaluation", "longtext"),
            Field("accuracy_evaluation", "Accuracy, robustness and security evaluation", "longtext"),
            Field("explainability", "How an affected person can understand an output", "longtext"),
            Field("human_oversight", "Human review, override and appeal", "longtext", required=True),
            Field("mitigation_measures", "Risk treatments", "longtext", store="column", required=True),
            Field("residual_rationale", "Remaining risk and limitations", "longtext"),
        )),
        Section("assurance", "Testing, monitoring and decision", (
            Field("evaluation_evidence", "Evaluation method and evidence", "longtext"),
            Field("monitoring_plan", "Drift, incident and change monitoring", "longtext", required=True),
            Field("rollback_plan", "When use stops and how to roll back", "longtext"),
            Field("consultation", "Who was consulted and what they said", "longtext"),
            Field("assessment_recommendation", "Assessor recommendation and unresolved conditions", "longtext", required=True,
                  help="The independent approval or refusal is recorded separately in AI Governance Decisions."),
            Field("proposed_review", "Proposed next review", "date"),
        )),
    )
