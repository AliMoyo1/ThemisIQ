"""Build capability-sheet.md: every capability line of the features page, with the code that backs it.

Run from the repository root: python plans/2026-10-landing-page/build_capability_sheet.py [git-ref]
Each line names a code path and a pattern that must be present at the ref (default origin/master), and a pattern for the
tests that exercise it. "Present" means the code exists at that ref; it is not a claim that the feature was tried by hand.
"""
import subprocess
import sys

REF = sys.argv[1] if len(sys.argv) > 1 else "origin/master"
M = "oneforall/modules/"
C = "oneforall/core/"

# (section, capability copy, roles, code path, code pattern, test pattern, setup note)
LINES = [
    # 1a AI across the platform
    ("AI", "Every assistant follows your organisation's AI policy: providers, kinds of data, features and a monthly budget", "AI, IT and security", C + "ai_policy.py", r"def _refusal", r"ai_policy", ""),
    ("AI", "A refused AI call never leaves the platform, and the refusal is recorded", "AI, IT and security", C + "ai_policy.py", r"record_usage\(ticket, \"refused\"", r"refused", ""),
    ("AI", "Every AI call is logged with its feature, outcome and usage", "AI, IT and security", C + "ai_policy.py", r"def record_usage", r"ai_usage_log", ""),
    ("AI", "Every AI feature is registered with what it reads, what it leaves out and what happens to its answer", "AI, IT and security", C + "ai_declarations.py", r"class Declaration", r"ai_declarations", ""),
    ("AI", "If the assistant is off or fails, nothing is invented and the manual path stays open", "All", C + "ai_client.py", r"class AIUnavailable", r"AIUnavailable|ai_unavailable", ""),
    ("AI", "A domain guardrail on every prompt: separate fact from inference, never invent a clause or source", "AI", C + "ai_client.py", r"_GRC_GUARDRAIL = ", r"GUARDRAIL|guardrail", ""),
    ("AI", "Text a person typed is passed to the model as data, not as instructions", "AI, IT and security", C + "ai_client.py", r"def wrap_user_input", r"wrap_user_input", "HOLD: do not publish until security finding M3 (prompt injection) is fixed"),
    ("AI", "Platform briefing, executive summary and predictive risk", "Leadership", C + "ai_policy.py", r"launcher.api_executive_summary", r"executive_summary|predictive", "AI provider"),
    ("AI", "An in-app guide that answers how-do-I questions", "All", M + "launcher/routes_platform.py", r"launcher.api_trainer_ask", r"trainer", ""),

    # 2 ARIA
    ("ARIA", "Load standards from the framework catalogue and manage their controls", "Compliance", M + "aria/routes.py", r"@router.get\(\"/frameworks\"", r"framework", ""),
    ("ARIA", "Propose equivalent controls across standards (topic, wording, then AI for unclear pairs)", "Compliance", C + "auto_mapper.py", r"Three-pass approach", r"auto_map", "AI provider for the third pass"),
    ("ARIA", "A different reviewer approves each proposed control match", "Compliance", M + "aria/templates/mapping.html", r"Awaiting a different reviewer", r"mapping", ""),
    ("ARIA", "See each control's integrated (IMS) status across your standards", "Compliance", C + "auto_mapper.py", r"def get_ims_status_bulk", r"ims", ""),
    ("ARIA", "Generate a policy, procedure, standard, guideline or framework document for a control", "Compliance, AI", M + "aria/ai_generator.py", r"_DOC_TYPE_GUIDE = ", r"generate_policy|generate-policy", "AI provider"),
    ("ARIA", "Generate one integrated document covering a control and its mapped controls in other standards", "Compliance, AI", M + "aria/routes.py", r"integrated_framework_id", r"integrated_framework", "AI provider"),
    ("ARIA", "Add your own instructions to a generated draft", "Compliance, AI", M + "aria/routes.py", r"custom_instructions: str = Form", r"custom_instructions", "AI provider"),
    ("ARIA", "Edit the working draft: save, discard and recover", "Compliance", M + "aria/routes_policy_workflow.py", r"/api/policy-drafts/\{draft_id\}/recover", r"policy_draft|recover_draft", "Authoring switched on per organisation"),
    ("ARIA", "Build the draft into your branded Word template and preview it as a PDF", "Compliance", M + "aria/routes_policy_workflow.py", r"/api/policy-drafts/\{draft_id\}/preview", r"preview", "Authoring switched on per organisation; conversion worker"),
    ("ARIA", "Upload company branding templates for policy documents", "Compliance", M + "aria/routes.py", r"@router.post\(\"/api/templates\"", r"templates", ""),
    ("ARIA", "Confirm a version and send it for approval; the author and the requester cannot approve it", "Compliance", M + "aria/policy_workflow_service.py", r"the requester cannot approve their own submission", r"approv", "Authoring switched on per organisation"),
    ("ARIA", "Compare two retained versions line by line", "Compliance", M + "aria/templates/policy_workbench.html", r"Compare retained versions", r"compare", ""),
    ("ARIA", "On approval, the version is filed in the Evidence Vault and attached to matching GRID controls", "Compliance, Audit", M + "aria/policy_publication.py", r"Copy the approved version's branded file into the Evidence Vault", r"publication", ""),
    ("ARIA", "Assisted gap analysis of a framework", "Compliance, AI", M + "aria/routes.py", r"/api/generate-gap-analysis", r"gap_analysis|gap-analysis", "AI provider"),
    ("ARIA", "Ask ARIA: answers from your approved policies and controls, with the source shown", "All, AI", M + "aria/routes.py", r"@router.get\(\"/ask\"", r"ask", "AI provider"),
    ("ARIA", "A governance risk list tied to controls and policies", "Compliance, Risk", M + "aria/routes.py", r"@router.get\(\"/risks\"", r"aria.*risk", ""),
    ("ARIA", "An activity log of control, policy and document changes", "Compliance", M + "aria/routes.py", r"@router.get\(\"/audit-log\"", r"audit_log|audit-log", ""),
    ("ARIA", "Compliance projects per framework", "Compliance", M + "launcher", r"@router.get\(\"/projects\"", r"projects", ""),

    # 3 GRID
    ("GRID", "Plan audits with scope, objective, criteria and method", "Audit", M + "grid/data_service.py", r"scope, objective, criteria, methodology", r"grid", ""),
    ("GRID", "Run one integrated audit across several standards", "Audit", M + "grid/data_service.py", r"is_integrated", r"is_integrated|integrated", ""),
    ("GRID", "Controls arrive mapped from approved ARIA equivalences and show an IMS badge", "Audit", M + "grid/data_service.py", r"ims_equivalent", r"ims", ""),
    ("GRID", "Checklists per control, with comments and versioned evidence", "Audit", M + "grid/data_service.py", r"grid_evidence_versions", r"grid", ""),
    ("GRID", "Remote audit sessions and findings", "Audit", M + "grid/routes.py", r"grid_remote_sessions", r"remote", ""),
    ("GRID", "Nonconformities with evidence and corrective action plans", "Audit", M + "grid/data_service.py", r"grid_non_conformances", r"non_conform|nonconform|_nc", ""),
    ("GRID", "Reminders, approvals and audit sign-off", "Audit", M + "grid/data_service.py", r"grid_audit_signoffs", r"signoff|sign_off", ""),
    ("GRID", "Vendor assessments within the audit programme", "Audit", M + "grid/data_service.py", r"grid_vendor_assessments", r"vendor", ""),
    ("GRID", "Compliance scores, audit reports and a timeline", "Audit, Leadership", M + "grid/data_service.py", r"grid_timeline", r"grid", ""),
    ("GRID", "Expiring share links to a read only audit view for external auditors", "Audit", M + "grid/templates/shared_audit.html", r".", r"share", ""),
    ("GRID", "Ask the policy owner for a missing or updated policy from inside an audit", "Audit, Compliance", M + "grid/data_service.py", r"grid_policy_requests", r"policy_request", ""),
    ("GRID", "Import an existing audit checklist", "Audit, AI", C + "ai_policy.py", r"grid.parse_checklist_with_ai", r"checklist", "AI provider for reading the file"),
    ("GRID", "Audit assistant: questions, control details, risk scoring, report narrative", "Audit, AI", C + "ai_policy.py", r"grid.generate_report_narrative", r"grid.*ai|ai.*grid", "AI provider"),

    # 4 Sentinel
    ("Sentinel", "Rule cards per jurisdiction: authority, notice, trigger, period, source and effective dates", "Privacy", M + "sentinel/obligations.py", r"def create_card", r"obligation|jurisdiction_card", ""),
    ("Sentinel", "A different DPO approves each rule card before it can set a deadline", "Privacy", M + "sentinel/obligations.py", r"def approve_card", r"approve_card", ""),
    ("Sentinel", "One breach, several obligations, each with its own trigger, timezone and countdown", "Privacy", M + "sentinel/obligations.py", r"def add_obligation", r"obligation", ""),
    ("Sentinel", "Record the notify or not-notify decision per obligation, with a reason", "Privacy", M + "sentinel/obligations.py", r"def decide_obligation", r"decide_obligation", ""),
    ("Sentinel", "Jurisdictions grouped by region, with authority, breach timing and subject request timing", "Privacy", M + "sentinel/jurisdictions.py", r"def jurisdictions_by_region", r"jurisdiction", ""),
    ("Sentinel", "Laws with no fixed hours show as as soon as reasonably possible", "Privacy", M + "sentinel/jurisdictions.py", r"def is_asap_jurisdiction", r"asap", ""),
    ("Sentinel", "Breach and subject request deadlines monitored, with alerts", "Privacy", M + "sentinel/scheduler.py", r".", r"breach|dsr", "Email needs a sender"),
    ("Sentinel", "Records of processing, data flows and legitimate interest assessments", "Privacy", M + "sentinel/data_service.py", r"sentinel_lia", r"ropa|lia", ""),
    ("Sentinel", "DPIAs with an AI first draft for review", "Privacy, AI", M + "sentinel/ai_service.py", r"def ai_generate_full_dpia", r"dpia", "AI provider"),
    ("Sentinel", "Breach register with severity and an AI assessment for review", "Privacy, AI", M + "sentinel/ai_service.py", r"def ai_assess_breach", r"breach", "AI provider for the assessment"),
    ("Sentinel", "Subject requests with deadlines and an AI drafted reply for review", "Privacy, AI", M + "sentinel/ai_service.py", r"def ai_draft_dsr_response", r"dsr", "AI provider for the draft"),
    ("Sentinel", "Consent records", "Privacy", M + "sentinel/data_service.py", r"sentinel_consent", r"consent", ""),
    ("Sentinel", "Vendors with data protection agreement status, shared with the vendor directory", "Privacy", M + "sentinel/data_service.py", r"sentinel_vendors", r"vendor", ""),
    ("Sentinel", "Privacy notices, with an AI draft for review", "Privacy, AI", M + "sentinel/ai_service.py", r"def ai_generate_privacy_notice", r"notice", "AI provider for the draft"),
    ("Sentinel", "Controllers and processors per processing activity", "Privacy", M + "sentinel/routes.py", r"/api/controllers", r"controller", ""),
    ("Sentinel", "Legal basis per activity, with an AI suggestion for review", "Privacy, AI", M + "sentinel/ai_service.py", r"def ai_suggest_legal_basis", r"legal_basis", "AI provider for the suggestion"),
    ("Sentinel", "International transfers and their safeguards", "Privacy", M + "sentinel/routes.py", r"/api/transfers", r"transfer", ""),
    ("Sentinel", "Retention periods with scheduled reviews", "Privacy", M + "sentinel/routes.py", r"/api/retention", r"retention", ""),
    ("Sentinel", "Technical and organisational security measures", "Privacy, IT and security", M + "sentinel/routes.py", r"/api/security", r"security", ""),
    ("Sentinel", "Privacy compliance score and audit export", "Privacy, Leadership", M + "sentinel/routes.py", r"/api/compliance-score", r"compliance_score|compliance-score", ""),
    ("Sentinel", "Compare two privacy regimes (AI gap analysis)", "Privacy, AI", M + "sentinel/ai_service.py", r"def ai_gap_analysis", r"gap", "AI provider"),
    ("Sentinel", "Privacy policies and staff training", "Privacy", M + "sentinel/data_service.py", r"sentinel_training", r"training", ""),
    ("Sentinel", "An alternate privacy contact for deadline alerts", "Privacy", M + "sentinel", r"alternate", r"alternate", ""),

    # 5 BCM
    ("BCM", "Business impact analysis: processes, recovery objectives, impact ratings and resources", "Continuity", M + "bcm/data_service.py", r"bcm_bia_resources", r"bia", ""),
    ("BCM", "A dependency map of processes, systems and suppliers", "Continuity", M + "bcm/data_service.py", r"bcm_dependency_edges", r"dependenc", ""),
    ("BCM", "Continuity plans with reviews, activation records and links to the processes they protect", "Continuity", M + "bcm/data_service.py", r"bcm_plan_activations", r"plan", ""),
    ("BCM", "Draft a plan from a scenario and review a plan with AI, for a person to check", "Continuity, AI", M + "bcm/ai_service.py", r"def generate_plan", r"generate_plan|review_plan", "AI provider"),
    ("BCM", "Incident log with actions, decisions, updates and stakeholders", "Continuity", M + "bcm/data_service.py", r"bcm_incident_decisions", r"incident", ""),
    ("BCM", "Unacknowledged incident alerts move to an alternate, by severity", "Continuity", M + "bcm/escalation.py", r".", r"escalation", "Email needs a sender for mail; in-app works without"),
    ("BCM", "Exercises from a scenario library", "Continuity", M + "bcm/data_service.py", r"bcm_scenario_library", r"exercise|scenario", ""),
    ("BCM", "Training modules with attestations", "Continuity", M + "bcm/data_service.py", r"bcm_training_attestations", r"training", ""),
    ("BCM", "Message templates and a contact tree", "Continuity", M + "bcm/data_service.py", r"bcm_contact_nodes", r"contact|comm", ""),
    ("BCM", "Supplier assessments and continuity controls with evidence", "Continuity", M + "bcm/data_service.py", r"bcm_compliance_evidence", r"compliance", ""),
    ("BCM", "Ask questions of your uploaded continuity documents", "Continuity, AI", M + "bcm/ai_service.py", r"def rag_ask", r"rag", "AI provider"),
    ("BCM", "Continuity risks with the processes they affect", "Continuity, Risk", M + "bcm/data_service.py", r"bcm_risks", r"bcm.*risk", ""),
    ("BCM", "Reports and an AI board narrative for review", "Continuity, Leadership, AI", M + "bcm/ai_service.py", r"def generate_board_narrative", r"narrative", "AI provider"),

    # 6 ERM
    ("ERM", "Your own risk framework: scales, impact dimensions, matrix bands and taxonomy", "Risk", M + "erm/data_service.py", r"erm_framework_matrix_bands", r"framework", ""),
    ("ERM", "Enterprise risks linked to objectives and pillars, with risk statements", "Risk", M + "erm/data_service.py", r"erm_objectives", r"objective|statement", ""),
    ("ERM", "Risk appetite and accepted risks with their history", "Risk, Leadership", M + "erm/data_service.py", r"erm_risk_acceptances", r"appetite|acceptance", ""),
    ("ERM", "Key risk indicators with history and thresholds", "Risk", M + "erm/data_service.py", r"erm_kri_history", r"kri", ""),
    ("ERM", "Questionnaire risk assessments and a risk library", "Risk", M + "erm/data_service.py", r"erm_assessment_responses", r"assessment", ""),
    ("ERM", "Contributing factors and treatments", "Risk", M + "erm/data_service.py", r"erm_cf_treatments", r"contributing|treatment", ""),
    ("ERM", "Regulatory obligations tracked as risks", "Risk, Privacy", M + "erm/data_service.py", r"erm_regulatory_obligations", r"obligation", ""),
    ("ERM", "Scenario Studio: compare scenarios with the baseline and capture a board pack", "Risk, Leadership", M + "erm/routes_scenarios.py", r"scenario-studio", r"scenario", ""),
    ("ERM", "Horizon scanning from trusted sources, with citations checked before use", "Risk, AI", M + "erm/scan_jobs.py", r".", r"scan", "Web search must be configured"),
    ("ERM", "Emerging risks watch list", "Risk", M + "erm/data_service.py", r"erm_emerging_risks", r"emerging", ""),
    ("ERM", "A rating guide so every unit rates risk the same way", "Risk", M + "erm/routes.py", r"rating-guide", r"rating", ""),
    ("ERM", "Score history and the approval workflow of each risk", "Risk", M + "erm/data_service.py", r"erm_risk_workflow_history", r"workflow|history", ""),
    ("ERM", "AI help: scores, treatments, statements, assessment questions, remediation plan, board narratives", "Risk, AI", M + "erm/ai_service.py", r"def ", r"erm.*ai|ai_service", "AI provider"),
    ("ERM", "Predictive risk from signals across every module, with contribution and confidence shown", "Risk, Leadership", C + "predictive_risk.py", r"Predictive AI Risk Analytics Engine", r"predictive", ""),
    ("ERM", "One risk register that brings risks raised in any module together", "Risk", M + "launcher", r"@router.get\(\"/risk-register\"", r"risk_register", ""),

    # 7 ORM
    ("ORM", "Loss and near miss events from templates, with workflow history", "Risk", M + "orm/data_service.py", r"orm_event_workflow_history", r"event", ""),
    ("ORM", "Risk and control self assessment with actions", "Risk", M + "orm/data_service.py", r"orm_rcsa_actions", r"rcsa", ""),
    ("ORM", "Key risk indicators with history", "Risk", M + "orm/data_service.py", r"orm_kri_history", r"kri", ""),
    ("ORM", "AI management assessments and AI controls", "Risk, AI", M + "orm/routes.py", r"\"aims\"", r"aims", ""),
    ("ORM", "Event analysis, trend narrative and chat with AI, for review", "Risk, AI", M + "orm/ai_service.py", r"def ", r"orm", "AI provider"),

    # 8 AI Governance
    ("AI Governance", "AI systems inventory and guided intake, saved as a draft until submitted", "AI", M + "ai_governance/routes.py", r"@router.get\(\"/register\"", r"intake|register", "Switched on per organisation"),
    ("AI Governance", "A reviewer accepts each use; the tier follows the answers and can be adopted with a reason", "AI", M + "ai_governance/service.py", r"def adopt_tier", r"adopt_tier", ""),
    ("AI Governance", "AI impact assessments with configurable dimensions, prefilled from the AI use", "AI, Privacy", M + "ai_governance/guidance.py", r"def aiia_prefill", r"aiia", ""),
    ("AI Governance", "A checklist of which assessments apply and what is left before a decision", "AI", M + "ai_governance/guidance.py", r"def get_checklist", r"checklist", ""),
    ("AI Governance", "Decisions by someone other than the requester, signed on a frozen brief", "AI, Leadership", M + "ai_governance/decisions.py", r"Someone other than the person who asked", r"decision", ""),
    ("AI Governance", "Conditions with expiry, and re-review when a covered fact changes", "AI", M + "ai_governance/decisions.py", r"needs_re_review", r"re_review|conditions", ""),
    ("AI Governance", "Monitoring and evaluations", "AI", M + "ai_governance/evaluations.py", r".", r"evaluation", ""),
    ("AI Governance", "Human oversight arrangements reviewed by a second person", "AI", M + "ai_governance/oversight.py", r".", r"oversight", ""),
    ("AI Governance", "Regulatory changes checked against affected AI uses", "AI, Compliance", M + "ai_governance/regulation.py", r".", r"regulat", ""),
    ("AI Governance", "Review packs for auditors", "AI, Audit", M + "ai_governance/review_packs.py", r".", r"pack", ""),
    ("AI Governance", "AI literacy courses for specialists with renewal and completion reporting", "AI", M + "ai_governance/literacy.py", r"def course_coverage", r"literacy", ""),
    ("AI Governance", "Bulk import of AI uses from a form export", "AI", M + "ai_governance/imports.py", r".", r"import", ""),
    ("AI Governance", "A register of the platform's own AI features and how they are used", "AI, IT and security", M + "ai_governance/platform_features.py", r".", r"platform_feature", ""),
    ("AI Governance", "Explain an AI use in plain words for reviewers", "AI", C + "ai_policy.py", r"governance.explain_ai_use", r"explain", "AI provider"),

    # 9 Evidence
    ("Evidence", "One evidence library with owners, periods, expiry and review dates", "All", M + "evidence/routes.py", r"review_due_date", r"evidence", ""),
    ("Evidence", "Link one item to controls, audits, incidents and risks", "All", M + "evidence/routes.py", r"link_entity_type", r"evidence_link|link", ""),
    ("Evidence", "Controls are rescored when evidence is removed or expires", "Compliance", M + "evidence/routes.py", r"rescore|effectiveness", r"rescores", ""),
    ("Evidence", "Evidence campaigns: request evidence from owners and review it", "Compliance, Audit", M + "evidence_campaigns/routes.py", r".", r"campaign", ""),
    ("Evidence", "Find evidence by its content, with suggested links limited to what you can see", "All, AI", M + "evidence/find.py", r".", r"find", "AI provider for meaning search"),
    ("Evidence", "File fingerprints and duplicate detection within your organisation", "All", M + "evidence/routes.py", r"Duplicate detection", r"duplicate", ""),
    ("Evidence", "Open Office files as PDF for review", "All", M + "evidence/routes.py", r"libreoffice", r"pdf", "LibreOffice on the server"),

    # 10 Work
    ("Work", "A Command Centre each person can arrange", "All", M + "launcher", r"command_centre|my-dashboard", r"command_centre|layout", ""),
    ("Work", "My Work across modules, and a team view for managers", "All", M + "launcher", r"@router.get\(\"/my-work\"", r"my_work", ""),
    ("Work", "Task board, calendar reminders and workflows with service levels", "All", M + "launcher", r"@router.get\(\"/workflows\"", r"workflow|task|calendar", ""),
    ("Work", "Related items across modules and one search bar", "All", M + "governance/relationships.py", r"def create_link", r"related|search", ""),
    ("Work", "In-app notifications and email with quiet hours and daily or weekly summaries", "All", C + "email_outbox.py", r"quiet", r"quiet|summary", "Email needs a sender"),
    ("Work", "Reports with frozen snapshots, independent sign-off and named expiring shares", "Leadership, Audit", M + "launcher/routes_reports.py", r"sign|share", r"report", ""),
    ("Work", "Saved views and analytics", "All", M + "saved_views", r".", r"saved_view", ""),
    ("Work", "Readiness findings before an audit or review", "Compliance, Audit", M + "readiness", r".", r"readiness", ""),
    ("Work", "An organisation timeline and a metrics view", "Leadership", M + "launcher", r"@router.get\(\"/timeline\"", r"timeline|metrics", ""),

    # 10a Connected governance
    ("Connected", "The connected view of a record, grouped by module, limited to what you may open", "All", M + "governance/entity360.py", r"The connected view of one record", r"entity360|connected", ""),
    ("Connected", "Change signals: owners of connected records are asked to look again, and can confirm or dismiss", "All", M + "governance/change_signals.py", r"Material change signals", r"change_signal", ""),
    ("Connected", "A nightly control effectiveness score", "Compliance", M + "governance/effectiveness.py", r"Control Effectiveness Engine", r"effectiveness", ""),
    ("Connected", "Shared business entities: applications, processes and data assets", "All", M + "governance/entity_scope.py", r"\(\"governance\", \"process\"\)", r"business_process|data_asset", ""),
    ("Connected", "A confirmed breach can open work in risk, operations and audit", "Privacy, Risk, Audit", C + "event_handlers.py", r"def breach_triggers_bcm_incident", r"breach", ""),

    # 11 Platform
    ("Platform", "REST API with keys and read or write scopes", "IT and security", M + "launcher/routes_api_v1.py", r"_require_write_key", r"api_v1|api_key", ""),
    ("Platform", "Outbound webhooks, and Slack and Teams notifications", "IT and security", C + "webhooks.py", r".", r"webhook", ""),
    ("Platform", "Bulk import and export of core records; user import from a spreadsheet", "IT and security", M + "launcher/_user_import.py", r"def bulk_create_users", r"import", ""),
    ("Platform", "Business units, controlled transfers between units and a people directory", "IT and security", M + "launcher/routes_people.py", r".", r"business_unit|transfer", ""),
    ("Platform", "Specialist roles per discipline and licences per module", "IT and security", C + "rbac.py", r"def user_modules", r"rbac", ""),
    ("Platform", "An audit log per organisation", "IT and security", C + "rls.py", r"public.audit_log", r"audit_log", ""),
    ("Platform", "One vendor directory shared by audit, privacy and continuity", "All", M + "launcher", r"@router.get\(\"/vendors\"", r"vendor", ""),
    ("Platform", "Email, connectors and the organisation's AI policy configured in one place", "IT and security", M + "launcher/templates/admin_ai_policy.html", r".", r"ai_policy", ""),
]


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def present(path, pattern):
    out = git("grep", "-c", "-E", pattern, REF, "--", path)
    return sum(int(line.rsplit(":", 1)[1]) for line in out.splitlines() if line.rsplit(":", 1)[-1].isdigit()) > 0


def tests_for(pattern):
    out = git("grep", "-l", "-i", "-E", pattern, REF, "--", "oneforall/tests")
    return len(out.splitlines())


rows, missing = [], []
for section, copy, roles, path, pattern, test_pattern, note in LINES:
    ok = present(path, pattern)
    if not ok:
        missing.append((section, copy, path, pattern))
    rows.append((section, copy, roles, f"`{path.replace('oneforall/', '')}`", "Present" if ok else "**Missing**",
                 str(tests_for(test_pattern)), note or "None"))

commit = git("rev-parse", "--short", REF).strip()
out = [
    "# Capability sheet for the features page",
    "",
    f"Generated by `build_capability_sheet.py` against `{REF}` (`{commit}`). Regenerate after every release that adds or",
    "changes a feature. **Present** means the code that backs the line exists at that commit (a pattern in the named",
    "file was found); **Tests** is how many test files mention the feature's key words, a pointer for the reviewer, not a",
    "proof. A line goes on the site only when it is Present, its copy is approved, and its setup note is reflected in the",
    "copy. No counts from this sheet are published (owner decision: numbers on hold).",
    "",
    f"Lines: {len(rows)}. Missing: {len(missing)}.",
    "",
    "| Section | Capability (draft copy) | Roles | Code | Status | Tests | Needs setup |",
    "| --- | --- | --- | --- | --- | --- | --- |",
]
out += ["| " + " | ".join(r) + " |" for r in rows]
out += ["", "## Not claimed", "",
        "- AI drafting of AI impact assessments: no such feature exists (plan 17 schedules it). The live landing page's",
        "  assisted drafting panel must drop AIIA until it ships.",
        "- Policy enforced MFA: held until security findings H2 and H3 are fixed.",
        "- Any count of modules, frameworks, jurisdictions, record types or AI features.",
        ""]
open("plans/2026-10-landing-page/capability-sheet.md", "w", encoding="utf-8").write("\n".join(out))
print(f"{len(rows)} lines, {len(missing)} missing")
for m in missing:
    print("MISSING", m)
