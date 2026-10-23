"""
Themis, the platform guide: a knowledge base of how to do things in ThemisIQ, and retrieval over it.

The guide searches local entries under the signed-in person's role. It does not
send free-text questions to an AI provider. Selected-record answers are handled
separately by core.themis_work through the owning module's scoped services.

Each entry names:
- area and caps: who may be shown it. The area follows the shell's navigation (core.onboarding.open_areas) and caps
  are an any-of list of capabilities. An entry is only offered to someone who can open its page.
- path: the page where the task happens, and nav: its label in the module menu.
- labels: the exact button labels the answer mentions.
- sources: the template or script files where nav and labels appear. tests/test_platform_guide.py fails if a label or
  a path disappears from the code, so the guide cannot drift silently.
- show: the label (or a CSS selector starting with # or .) the page highlights after "Take me there".
"""
import math
import re

from core.rbac import has_capability

_T = "modules/launcher/templates/"
_PLATFORM = _T + "platform_base.html"


def _e(id, area, path, title, answer, *, keywords="", nav=None, labels=(), sources=(), caps=(), show=None):
    return {"id": id, "area": area, "caps": list(caps), "path": path, "title": title, "nav": nav,
            "labels": list(labels), "sources": list(sources), "keywords": keywords, "answer": answer, "show": show}


ENTRIES = [
    # ── Getting around ───────────────────────────────────────────────────────
    _e("platform.tours", None, None, "Take a guided tour",
       "Open Themis (the question mark at the bottom right) and choose Get started. You will see a short checklist "
       "and the guided tours for the modules your role can open. A tour highlights each part of the screen and "
       "explains it, and you can stop at any time with Escape.",
       keywords="tour guide onboarding new start started begin learn walkthrough help first time getting"),
    _e("platform.search", None, "/", "Search across every module",
       "Use the search box at the top of any page, or press Ctrl+K. It searches risks, controls, policies, audits, "
       "vendors and more across the modules you can open, grouped by module.",
       keywords="search find look locate ctrl k global", show="#globalSearch"),
    _e("platform.my-work", None, "/my-work", "See everything assigned to you",
       "My Work brings together everything assigned to you across modules in one list. Use Take me there to open "
       "it. You can search, filter and save a view, and managers can switch to My team's.",
       keywords="my work assigned tasks todo inbox mine team assignments due", labels=["My team's"],
       sources=[_T + "my_work.html"], show="#myWorkQ"),
    _e("platform.notifications", None, "/", "Read your notifications",
       "Press the bell at the top right. Assignments, approvals waiting for you and deadline alerts arrive there. "
       "You can mark them all as read.",
       keywords="notification notifications bell alert alerts unread messages", show="#notifBtn"),
    _e("platform.tasks", None, "/tasks", "Create and track tasks",
       "Open Task Board from the Command Centre menu and press New Task. Tasks move through To Do, In Progress, "
       "Review and Done.",
       keywords="task tasks kanban board todo create assign", nav="Task Board", labels=["New Task"],
       sources=[_PLATFORM, _T + "task_board.html"], show="New Task"),
    _e("platform.calendar", None, "/calendar", "Add an event to the calendar",
       "Open Calendar from the Command Centre menu and press Add Event. The calendar also shows audit dates, "
       "reviews and exercises.",
       keywords="calendar event schedule date reminder meeting", nav="Calendar", labels=["Add Event"],
       sources=[_PLATFORM, _T + "calendar.html"], show="Add Event"),
    _e("platform.reports", None, "/reports", "Create and run a report",
       "Open Reports from the Command Centre menu and press New Report, choose what it covers, then Run Now. "
       "Each run is kept as a frozen snapshot that can be signed off independently and shared by an expiring link.",
       keywords="report reports reporting run snapshot board executive summary export share",
       nav="Reports", labels=["New Report", "Run Now"], sources=[_PLATFORM, _T + "reports.html"],
       show="New Report"),
    _e("platform.workflows", None, "/workflows", "Set up a workflow",
       "Open Workflows from the Command Centre menu. Press New Workflow to build one, or install a ready-made one "
       "with Install Workflow. Steps can carry service levels and escalate when they are missed.",
       keywords="workflow workflows approval chain process sla escalate automation",
       nav="Workflows", labels=["New Workflow", "Install Workflow"], sources=[_PLATFORM, _T + "workflows.html"],
       show="New Workflow"),
    _e("platform.evidence-upload", None, "/evidence/", "Upload evidence",
       "Open Evidence Repository from the Command Centre menu and press Upload Evidence. Give it an owner and an "
       "expiry date, then link it to the controls, audits, incidents or risks it supports. One file can serve "
       "them all.",
       keywords="evidence upload file proof document attach vault repository",
       nav="Evidence Repository", labels=["Upload Evidence"],
       sources=[_PLATFORM, "modules/evidence/templates/evidence_index.html"], show="Upload Evidence"),
    _e("platform.evidence-find", None, "/evidence/", "Find evidence",
       "Open Evidence Repository and press Find evidence, then describe what you are looking for. You can save "
       "your filters for next time.",
       keywords="evidence find search locate proof", nav="Evidence Repository", labels=["Find evidence"],
       sources=[_PLATFORM, "modules/evidence/templates/evidence_index.html"], show="Find evidence"),
    _e("platform.vendors", None, "/vendors", "Add a vendor",
       "Open Vendor Directory from the Command Centre menu and press Add Vendor. Then use Register in Audit, "
       "Register in Privacy or Register in Resilience, so every team works from the same record.",
       keywords="vendor vendors supplier third party add directory",
       nav="Vendor Directory", labels=["Add Vendor", "Register in Audit", "Register in Privacy", "Register in Resilience"],
       sources=[_PLATFORM, _T + "vendor_directory.html"], show="Add Vendor"),
    _e("platform.risk-register", None, "/risk-register", "See every risk in one register",
       "Open Risk Register from the Command Centre menu. It brings together risks raised in any module. Press "
       "New Risk to add one.",
       keywords="risk register all risks combined unified", nav="Risk Register", labels=["New Risk"],
       sources=[_PLATFORM, _T + "risk_register.html"], show="New Risk"),
    _e("platform.analytics", None, "/analytics", "See trends over time",
       "Open Analytics from the Command Centre menu for trend charts of your compliance and risk position over "
       "time. Press Refresh Snapshot to bring the figures up to date.",
       keywords="analytics trend trends history chart charts metrics over time",
       nav="Analytics", labels=["Refresh Snapshot"], sources=[_PLATFORM, _T + "analytics.html"]),
    _e("platform.org-structure", None, "/governance/", "Set up business units",
       "Open Org Structure from the Command Centre menu. Business units decide who sees which records. "
       "Press Add Business Unit to add one.",
       keywords="business unit units org structure organisation organization department division",
       nav="Org Structure", labels=["Add Business Unit"],
       sources=[_PLATFORM, "modules/governance/templates/index.html"], caps=["governance.entities.view"],
       show="Add Business Unit"),
    _e("platform.mfa", None, "/mfa/setup", "Turn on two-step sign-in",
       "Open two-step sign-in setup with Take me there. Scan the code with an authenticator app, enter the code it "
       "shows, and keep your backup codes somewhere safe: Print these codes is on the same page.",
       keywords="mfa two step two factor 2fa authenticator authentication otp security sign in secure account",
       labels=["Print these codes"], sources=[_T + "mfa_setup.html"]),
    _e("platform.password", None, "/change-password", "Change your password",
       "Open your account menu at the bottom of the left rail and choose Change Password.",
       keywords="password change reset forgot new", nav="Change Password", sources=["templates/base_shell.html"]),
    _e("platform.profile", None, "/profile", "Manage your profile and sessions",
       "Open your profile from the account menu at the bottom of the left rail. You can see where you are signed in, "
       "and set quiet hours for email with Save quiet hours.",
       keywords="profile account sessions signed in devices quiet hours email preferences",
       labels=["Save quiet hours"], sources=[_T + "profile.html"]),

    # ── Administration ──────────────────────────────────────────────────────
    _e("admin.add-user", None, "/admin/users", "Add a user",
       "Open User Management and press New User. Give the person the specialist role for their work; their role "
       "decides which modules they see. You can also bring in many people at once with Import Excel.",
       keywords="user users add invite new person account staff member role onboard colleague",
       nav="User Management", labels=["New User", "Import Excel"], sources=[_PLATFORM, _T + "admin_users.html"],
       caps=["platform.manage_users", "platform.manage_org_users"], show="New User"),
    _e("admin.deactivate-user", None, "/admin/users", "Deactivate or reactivate a user",
       "Open User Management, find the person and press Deactivate. A deactivated account can be brought back with "
       "Reactivate.",
       keywords="deactivate disable remove user leaver offboard reactivate suspend",
       nav="User Management", labels=["Deactivate", "Reactivate"], sources=[_PLATFORM, _T + "admin_users.html"],
       caps=["platform.manage_users", "platform.manage_org_users"]),
    _e("admin.frameworks", None, "/admin/frameworks", "Activate or add a standard",
       "Open Frameworks under administration to choose which standards are active. Press Custom Framework to add "
       "one of your own.",
       keywords="framework frameworks standard standards activate iso soc add custom",
       nav="Frameworks", labels=["Custom Framework"], sources=[_PLATFORM, _T + "admin_frameworks.html"],
       caps=["platform.manage_users"], show="Custom Framework"),
    _e("admin.audit-log", None, "/admin/logs", "Check the audit log",
       "Open Audit Log to see who did what in your organisation. Filter by date or type, and press Export CSV to "
       "keep a copy.",
       keywords="audit log trail history who did what activity changes record login",
       nav="Audit Log", labels=["Export CSV"], sources=[_PLATFORM, _T + "admin_logs.html"],
       caps=["platform.view_audit_log"]),
    _e("admin.api-keys", None, "/admin/api-keys", "Create an API key",
       "Open API Keys under administration and press Generate Key. Choose read or write access. Copy the key "
       "straight away; it is shown once.",
       keywords="api key keys integration token rest access developer",
       nav="API Keys", labels=["Generate Key"], sources=[_PLATFORM, _T + "admin_api_keys.html"],
       caps=["platform.manage_users"], show="Generate Key"),
    _e("admin.webhooks", None, "/admin/webhooks", "Send events to another system",
       "Open Webhooks under administration and press New Webhook, then use Test to check the receiving system.",
       keywords="webhook webhooks integration notify external system callback slack teams",
       nav="Webhooks", labels=["New Webhook", "Test"], sources=[_PLATFORM, _T + "admin_webhooks.html"],
       caps=["platform.manage_users"], show="New Webhook"),
    _e("admin.email", None, "/admin/email", "Set up email sending",
       "Open email settings in the administration menu, enter the sender details, press Save Configuration, then "
       "press Send Test Email to check it works.",
       keywords="email smtp sender mail settings configure notifications send",
       labels=["Send Test Email", "Save Configuration"], sources=[_T + "admin_email.html"],
       caps=["platform.manage_users"], show="Send Test Email"),
    _e("admin.ai-policy", None, "/admin/ai-policy", "Set your organisation's AI policy",
       "Open AI Policy under administration. Choose the AI providers, the kinds of data that may be sent, which AI "
       "features are on and a monthly budget, then press Save policy. A request the policy refuses never leaves "
       "the platform.",
       keywords="ai policy artificial intelligence provider budget data allowed features llm model",
       nav="AI Policy", labels=["Save policy"], sources=[_PLATFORM, _T + "admin_ai_policy.html"],
       caps=["ai_governance.policy.manage"], show="Save policy"),
    _e("admin.security", None, "/admin/security", "Require two-step sign-in",
       "Open Security under administration to set your organisation's sign-in policy, then press Save Policy.",
       keywords="security policy mfa require enforce two step sign in password rules",
       nav="Security", labels=["Save Policy"], sources=[_PLATFORM, _T + "admin_security.html"],
       caps=["platform.manage_users"]),

    # ── Governance (ARIA) ───────────────────────────────────────────────────
    _e("aria.frameworks", "aria", "/aria/frameworks", "Work with standards and controls",
       "In Governance, open Frameworks to see the standards you follow and their controls, with each control's "
       "status.",
       keywords="framework frameworks standard controls control iso status requirements",
       nav="Frameworks", sources=["modules/aria/templates/aria_sidebar.html"]),
    _e("aria.mapping", "aria", "/aria/mapping", "Map controls across standards",
       "In Governance, open Control Mapping, choose the standards and press Auto-Map Selected Frameworks. Review "
       "each proposed match and press Accept or Reject. A different reviewer approves each match.",
       keywords="map mapping control controls equivalent across standards integrated management system ims crosswalk",
       nav="Control Mapping", labels=["Auto-Map Selected Frameworks", "Accept", "Reject"],
       sources=["modules/aria/templates/aria_sidebar.html", "modules/aria/templates/mapping.html"],
       show="Auto-Map Selected Frameworks"),
    _e("aria.generate-policy", "aria", "/aria/ai-generator", "Draft a policy with ARIA",
       "In Governance, open AI Policy Generator, pick the control and the document type, and press Generate Policy "
       "Document. Edit the draft, press Apply template and preview to see it in your template, then send it for "
       "approval. The author can never approve their own version.",
       keywords="policy generate draft write procedure standard guideline document ai generator create",
       nav="AI Policy Generator", labels=["Generate Policy Document", "Apply template and preview"],
       sources=["modules/aria/templates/aria_sidebar.html", "modules/aria/templates/ai_generator.html"],
       show="Generate Policy Document"),
    _e("aria.add-document", "aria", "/aria/documents", "Add or upload a policy",
       "In Governance, open Policies & Documents and press Add Document, or Upload an existing file. When it is "
       "ready, press Submit for Approval.",
       keywords="policy document add upload new procedure submit approval",
       nav="Policies & Documents", labels=["Add Document", "Upload", "Submit for Approval"],
       sources=["modules/aria/templates/aria_sidebar.html", "modules/aria/templates/documents.html"],
       show="Add Document"),
    _e("aria.revise-policy", "aria", "/aria/documents", "Revise a policy and compare versions",
       "In Governance, open Policies & Documents, open the policy and press Start a revision. The approved version "
       "stays in force until the new one is approved. Use Compare to see two versions side by side.",
       keywords="revise revision update policy version compare change edit review",
       nav="Policies & Documents", labels=["Start a revision", "Compare"],
       sources=["modules/aria/templates/aria_sidebar.html", "modules/aria/templates/documents.html",
                "modules/aria/templates/policy_workbench.html"]),
    _e("aria.templates", "aria", "/aria/templates", "Use your own document template",
       "In Governance, open Document Templates and press Upload Template. Generated policies can then be previewed "
       "in your own branded template.",
       keywords="template templates branding branded word docx layout letterhead",
       nav="Document Templates", labels=["Upload Template"],
       sources=["modules/aria/templates/aria_sidebar.html", "modules/aria/templates/templates.html"],
       show="Upload Template"),
    _e("aria.ask", "aria", "/aria/ask", "Ask a question about your policies",
       "In Governance, open Ask ARIA AI and type your question. Answers come from your approved policies and "
       "controls, with the source shown. If they do not cover it, ARIA says so. Press New Chat to start a fresh "
       "conversation.",
       keywords="ask question policies answer what does our policy say aria chat",
       nav="Ask ARIA AI", labels=["New Chat"],
       sources=["modules/aria/templates/aria_sidebar.html", "modules/aria/templates/ask.html"]),
    _e("aria.gap-analysis", "aria", "/aria/ai-generator", "Run a gap analysis",
       "In Governance, open AI Policy Generator and press Run Gap Analysis to compare a standard with what you have.",
       keywords="gap analysis gaps missing compare readiness assessment",
       nav="AI Policy Generator", labels=["Run Gap Analysis"],
       sources=["modules/aria/templates/aria_sidebar.html", "modules/aria/templates/ai_generator.html"],
       show="Run Gap Analysis"),
    _e("aria.risks", "aria", "/aria/risks", "Record a governance risk",
       "In Governance, open Risk Register and press Add Risk. Governance risks are tied to the controls and "
       "policies that treat them.",
       keywords="governance risk add control policy register",
       nav="Risk Register", labels=["Add Risk"],
       sources=["modules/aria/templates/aria_sidebar.html", "modules/aria/templates/risks.html"], show="Add Risk"),

    # ── Audit (GRID) ────────────────────────────────────────────────────────
    _e("grid.new-audit", "grid", "/grid/audits", "Plan an audit",
       "In Audit, open Audits and press New Audit. Set the scope, objective, criteria and method. To audit several "
       "standards at once, choose them all: equivalent controls are linked and badged.",
       keywords="audit new create plan schedule internal external integrated scope",
       nav="Audits", labels=["New Audit"], sources=["modules/grid/templates/index.html"], show="New Audit"),
    _e("grid.import-checklist", "grid", "/grid/audits", "Import an existing checklist",
       "In Audit, open the audit and press Import Checklist to bring in a checklist you already have instead of "
       "retyping it.",
       keywords="import checklist excel spreadsheet existing upload questions",
       nav="Audits", labels=["Import Checklist"], sources=["modules/grid/templates/index.html"]),
    _e("grid.finding", "grid", "/grid/findings", "Record a finding",
       "In Audit, open Findings and press New Finding. Attach the evidence, then plan the corrective action and "
       "track it to closure.",
       keywords="finding findings nonconformity non conformity nc issue observation corrective action cap",
       nav="Findings", labels=["New Finding"], sources=["modules/grid/templates/index.html"], show="New Finding"),
    _e("grid.evidence", "grid", "/grid/evidence", "Attach evidence to an audit",
       "In Audit, open Evidence and press Link Evidence to attach proof from the Evidence Repository, or Browse "
       "Vault to choose a file already stored.",
       keywords="evidence attach link audit proof control vault",
       nav="Evidence", labels=["Link Evidence", "Browse Vault"], sources=["modules/grid/templates/index.html"]),
    _e("grid.request-policy", "grid", "/grid/audits", "Ask for a missing policy during an audit",
       "In Audit, on the control that needs it, press Request Policy from ARIA. The policy owner is asked without "
       "you leaving the audit.",
       keywords="request policy missing owner audit aria ask",
       nav="Audits", labels=["Request Policy from ARIA"], sources=["modules/grid/templates/index.html"]),
    _e("grid.reports", "grid", "/grid/reports", "Produce an audit report",
       "In Audit, open Reports and choose PDF Report or Word Report.",
       keywords="audit report pdf word download export",
       nav="Reports", labels=["PDF Report", "Word Report"], sources=["modules/grid/templates/index.html"]),
    _e("grid.vendors", "grid", "/grid/vendors", "Assess a vendor in an audit",
       "In Audit, open Vendors and press Add Vendor, then Assess to record the vendor assessment.",
       keywords="vendor supplier assessment audit third party assess",
       nav="Vendors", labels=["Add Vendor", "Assess"], sources=["modules/grid/templates/index.html"],
       show="Add Vendor"),
    _e("grid.share", "grid", "/grid/audits", "Share an audit with an external auditor",
       "In Audit, open the audit and create a read only share link for the external auditor. The link expires.",
       keywords="share external auditor link read only expiring certification body"),

    # ── Resilience (BCM) ────────────────────────────────────────────────────
    _e("bcm.bia", "bcm", "/bcm/bia", "Run a business impact analysis",
       "In Resilience, open Business Impact Analysis and press Add BIA Record for each critical process. Set its "
       "recovery objectives and what it depends on.",
       keywords="bia business impact analysis critical process rto rpo recovery objective",
       nav="Business Impact Analysis", labels=["Add BIA Record"], sources=["modules/bcm/templates/index.html"],
       show="Add BIA Record"),
    _e("bcm.plan", "bcm", "/bcm/plans", "Write a continuity plan",
       "In Resilience, open Continuity Plans and press New Plan, or Generate Plan for a first draft from a scenario "
       "that a person then checks and approves.",
       keywords="continuity plan bcp disaster recovery plan write create draft generate",
       nav="Continuity Plans", labels=["New Plan", "Generate Plan"], sources=["modules/bcm/templates/index.html"],
       show="New Plan"),
    _e("bcm.activate", "bcm", "/bcm/plans", "Activate a continuity plan",
       "In Resilience, open Continuity Plans, open the plan and press Activate Plan. Press Stand Down Plan when the "
       "disruption is over.",
       keywords="activate invoke plan stand down disruption crisis",
       nav="Continuity Plans", labels=["Activate Plan", "Stand Down Plan"],
       sources=["modules/bcm/templates/index.html"]),
    _e("bcm.incident", "bcm", "/bcm/incidents", "Report and run an incident",
       "In Resilience, open Incidents and press Report Incident. Log decisions with Log Decision as you go. Alerts "
       "that are not acknowledged in time move on to the next person, by severity.",
       keywords="incident report outage disruption crisis log decision escalate",
       nav="Incidents", labels=["Report Incident", "Log Decision"], sources=["modules/bcm/templates/index.html"],
       show="Report Incident"),
    _e("bcm.exercise", "bcm", "/bcm/exercises", "Plan an exercise",
       "In Resilience, open Exercises & Testing and press New Exercise, or pick one from the Scenario Library with "
       "Use This Scenario.",
       keywords="exercise test drill tabletop simulation scenario rehearse",
       nav="Exercises & Testing", labels=["New Exercise", "Use This Scenario"],
       sources=["modules/bcm/templates/index.html"], show="New Exercise"),

    # ── Privacy (Sentinel) ──────────────────────────────────────────────────
    _e("sentinel.breach", "sentinel", "/sentinel/breaches", "Report a data breach",
       "In Privacy, open Data Breaches and press Report Breach. Each jurisdiction the breach touches becomes its "
       "own obligation with its own deadline, and you record for each whether you notify and why.",
       keywords="breach data breach leak exposure incident notify regulator authority 72 hours deadline report",
       nav="Data Breaches", labels=["Report Breach"], sources=["modules/sentinel/templates/index.html"],
       show="Report Breach"),
    _e("sentinel.dpia", "sentinel", "/sentinel/dpia", "Start a DPIA",
       "In Privacy, open DPIA Assessments and press New DPIA. You can ask for a first draft to review.",
       keywords="dpia data protection impact assessment high risk processing privacy assessment",
       nav="DPIA Assessments", labels=["New DPIA"], sources=["modules/sentinel/templates/index.html"],
       show="New DPIA"),
    _e("sentinel.ropa", "sentinel", "/sentinel/ropa", "Record a processing activity",
       "In Privacy, open RoPA Records and press Add Record. Give the purpose, legal basis, data and retention.",
       keywords="ropa record processing activity article 30 register purpose legal basis",
       nav="RoPA Records", labels=["Add Record"], sources=["modules/sentinel/templates/index.html"],
       show="Add Record"),
    _e("sentinel.dsr", "sentinel", "/sentinel/dsr", "Handle a subject request",
       "In Privacy, open Subject Requests and press New DSR. Each request carries its legal deadline, and you can "
       "draft the reply for review.",
       keywords="dsr dsar subject access request erasure deletion rectification individual data request",
       nav="Subject Requests", labels=["New DSR"], sources=["modules/sentinel/templates/index.html"],
       show="New DSR"),
    _e("sentinel.consent", "sentinel", "/sentinel/consent", "Record consent",
       "In Privacy, open Consent Management and press Add Consent Record.",
       keywords="consent record opt in withdraw marketing permission",
       nav="Consent Management", labels=["Add Consent Record"], sources=["modules/sentinel/templates/index.html"],
       show="Add Consent Record"),
    _e("sentinel.transfers", "sentinel", "/sentinel/transfers", "Record an international transfer",
       "In Privacy, open Intl. Transfers and press Add Transfer, with the safeguard that covers it.",
       keywords="international transfer cross border scc safeguard country export data",
       nav="Intl. Transfers", labels=["Add Transfer"], sources=["modules/sentinel/templates/index.html"],
       show="Add Transfer"),
    _e("sentinel.notice", "sentinel", "/sentinel/notices", "Write a privacy notice",
       "In Privacy, open Privacy Notices and press Add Notice, or Generate Notice for a first draft to review.",
       keywords="privacy notice statement policy website draft generate",
       nav="Privacy Notices", labels=["Add Notice", "Generate Notice"],
       sources=["modules/sentinel/templates/index.html"]),
    _e("sentinel.vendors", "sentinel", "/sentinel/vendors", "Track a processor's data protection agreement",
       "In Privacy, open Vendor Management and press Add Vendor to record the processor and its agreement status.",
       keywords="processor vendor dpa data processing agreement supplier privacy",
       nav="Vendor Management", labels=["Add Vendor"], sources=["modules/sentinel/templates/index.html"]),
    _e("sentinel.jurisdictions", "sentinel", "/sentinel/jurisdictions", "Work with jurisdiction rule cards",
       "In Privacy, open Jurisdiction Manager. Rule cards are drafted by a privacy specialist with Draft a rule card "
       "and approved by a different DPO before they can set a deadline.",
       keywords="jurisdiction jurisdictions rule card law country regulator notification rules gdpr popia",
       nav="Jurisdiction Manager", labels=["Draft a rule card"], sources=["modules/sentinel/templates/index.html"]),

    # ── Enterprise risk (ERM) ───────────────────────────────────────────────
    _e("erm.add-risk", "erm", "/erm/register", "Add an enterprise risk",
       "In Enterprise Risk, open Risk Register and press Add Risk. Give it an owner, rate it with your scales and "
       "add the treatments.",
       keywords="risk add new enterprise register owner score rate treatment",
       nav="Risk Register", labels=["Add Risk"], sources=["modules/erm/templates/index.html", "modules/erm/templates/_erm_sidebar.html"], show="Add Risk"),
    _e("erm.appetite", "erm", "/erm/appetite", "Set risk appetite",
       "In Enterprise Risk, open Risk Appetite and press Set Appetite for each area. Risks above it are flagged.",
       keywords="appetite tolerance threshold limit acceptable risk level",
       nav="Risk Appetite", labels=["Set Appetite"], sources=["modules/erm/templates/index.html", "modules/erm/templates/_erm_sidebar.html"],
       show="Set Appetite"),
    _e("erm.kri", "erm", "/erm/indicators", "Add a key risk indicator",
       "In Enterprise Risk, open Indicators and press Add KRI, then set its thresholds and record values over time.",
       keywords="kri key risk indicator indicators metric threshold measure",
       nav="Indicators", labels=["Add KRI"], sources=["modules/erm/templates/index.html", "modules/erm/templates/_erm_sidebar.html"], show="Add KRI"),
    _e("erm.assessment", "erm", "/erm/assessments", "Run a risk assessment",
       "In Enterprise Risk, open Assessments and press New Assessment to send questions and turn the answers into "
       "risks.",
       keywords="assessment questionnaire survey risk assessment evaluate",
       nav="Assessments", labels=["New Assessment"], sources=["modules/erm/templates/index.html", "modules/erm/templates/_erm_sidebar.html"],
       show="New Assessment"),
    _e("erm.obligations", "erm", "/erm/obligations", "Track a regulatory obligation",
       "In Enterprise Risk, open Obligations and press Add Obligation.",
       keywords="obligation obligations regulatory compliance requirement law regulation",
       nav="Obligations", labels=["Add Obligation"], sources=["modules/erm/templates/index.html", "modules/erm/templates/_erm_sidebar.html"],
       show="Add Obligation"),
    _e("erm.scenario", "erm", "/erm/scenario-studio", "Test a what-if scenario",
       "In Enterprise Risk, open Scenario Studio and press New Scenario. Start from a template, tick what is affected, "
       "set what changes and read the effect against today. On the Brief step press Generate board pack to freeze the numbers.",
       keywords="scenario what if stress test simulate board pack baseline template",
       nav="Scenario Studio", labels=["New Scenario", "Generate board pack"],
       sources=["modules/erm/templates/_erm_sidebar.html", "modules/erm/templates/scenario_studio.html"],
       caps=["erm.scenario.view"], show="New Scenario"),
    _e("erm.board-report", "erm", "/erm/", "Prepare a board report on risk",
       "In Enterprise Risk, on the dashboard, press Board Report PDF for the report, or Generate AI Narrative for a "
       "narrative you review before sharing.",
       keywords="board report summary executive narrative directors",
       labels=["Board Report PDF", "Generate AI Narrative"], sources=["modules/erm/templates/index.html"],
       show="Board Report PDF"),

    # ── Operations risk (ORM) ───────────────────────────────────────────────
    _e("orm.event", "orm", "/orm/events", "Log a loss event or near miss",
       "In Operations Risk, open Events and press Log Event. Record what happened and its impact, then follow it "
       "to the root cause.",
       keywords="event loss near miss incident operational log record root cause",
       nav="Events", labels=["Log Event"], sources=["modules/orm/templates/index.html"], show="Log Event"),
    _e("orm.rcsa", "orm", "/orm/assessment", "Run a risk and control self assessment",
       "In Operations Risk, open RCSA and press New Assessment. Teams rate their own risks and controls and add "
       "actions where needed.",
       keywords="rcsa self assessment control risk rating team",
       nav="RCSA", labels=["New Assessment"], sources=["modules/orm/templates/index.html"],
       show="New Assessment"),
    _e("orm.kri", "orm", "/orm/indicators", "Track an operational indicator",
       "In Operations Risk, open KRI Indicators and press Add KRI, then record values over time.",
       keywords="kri indicator operational metric threshold",
       nav="KRI Indicators", labels=["Add KRI"], sources=["modules/orm/templates/index.html"], show="Add KRI"),

    # ── AI Governance ───────────────────────────────────────────────────────
    _e("aig.register", "ai_governance", "/ai-governance/register", "Register an AI use",
       "In AI Governance, open Register an AI use and answer the short guided form. It stays a draft until you "
       "press Submit for review. A reviewer then accepts it into the inventory.",
       keywords="ai use register intake new system tool model chatbot copilot submit request",
       nav="Register an AI use", labels=["Submit for review"],
       sources=["modules/ai_governance/templates/_ai_sidebar.html", "static/js/ai_governance_intake.js"],
       caps=["ai_use.intake_create"]),
    _e("aig.my-requests", "ai_governance", "/ai-governance/requests", "Follow your AI requests",
       "In AI Governance, open My requests to see the AI uses you have asked for and where each one stands.",
       keywords="my requests status ai use submitted follow track",
       nav="My requests", sources=["modules/ai_governance/templates/_ai_sidebar.html"],
       caps=["ai_use.submit"]),
    _e("aig.review", "ai_governance", "/ai-governance/review", "Review new AI requests",
       "In AI Governance, open Requests to see the AI uses waiting for review. Accept one with Add to the inventory, "
       "or ask the requester for more information.",
       keywords="review requests queue accept inventory triage ai use",
       nav="Requests", labels=["Add to the inventory"],
       sources=["modules/ai_governance/templates/_ai_sidebar.html", "static/js/ai_governance_lists.js"],
       caps=["ai_use.review"]),
    _e("aig.decide", "ai_governance", "/ai-governance/decisions", "Decide on an AI use",
       "In AI Governance, open Reviews and decisions. Someone other than the requester decides, for example with "
       "Approve with conditions, and presses Record the decision. The decision is signed on a frozen record of what "
       "was shown.",
       keywords="decide decision approve reject conditions ai use sign off",
       nav="Reviews and decisions", labels=["Approve with conditions", "Record the decision"],
       sources=["modules/ai_governance/templates/_ai_sidebar.html", "static/js/ai_governance_decisions.js"],
       caps=["ai_use.decide"]),
    _e("aig.assessment", "ai_governance", "/ai-governance/assessments", "Run an AI impact assessment",
       "In AI Governance, open Impact assessments and press New assessment. It is prefilled from the AI use.",
       keywords="aiia ai impact assessment risk harm assess",
       nav="Impact assessments", labels=["New assessment"],
       sources=["modules/ai_governance/templates/_ai_sidebar.html", "modules/ai_governance/templates/assessments.html"],
       caps=["ai_assessment.view"], show="New assessment"),
    _e("aig.monitoring", "ai_governance", "/ai-governance/monitoring", "Monitor an approved AI use",
       "In AI Governance, open Monitoring and press Record an evaluation run to log how the AI use performed "
       "against its thresholds.",
       keywords="monitor monitoring evaluation run performance drift threshold oversight",
       nav="Monitoring", labels=["Record an evaluation run"],
       sources=["modules/ai_governance/templates/_ai_sidebar.html", "static/js/ai_governance_monitoring.js"]),
    _e("aig.inventory", "ai_governance", "/ai-governance/systems", "See your AI systems",
       "In AI Governance, open AI systems for every accepted AI use, its tier and its status.",
       keywords="ai systems inventory list catalogue register all ai uses",
       nav="AI systems", sources=["modules/ai_governance/templates/_ai_sidebar.html"]),
    _e("aig.packs", "ai_governance", "/ai-governance/packs", "Prepare a review pack for auditors",
       "In AI Governance, open Review packs to prepare or receive a pack that shows auditors the record behind an "
       "AI use.",
       keywords="review pack auditor evidence ai use proof export",
       nav="Review packs", sources=["modules/ai_governance/templates/_ai_sidebar.html"],
       caps=["ai_pack.manage", "ai_pack.receive"]),
]

_BY_ID = {e["id"]: e for e in ENTRIES}

# ── Retrieval ───────────────────────────────────────────────────────────────
_STOP = frozenset("""how do i a an the is it to in on of my me can what where when why which who does did will would
should could am are was were be been have has had this that with for from about use up out go get set want need
please there here our we you your new""".split())
_SYNONYMS = {
    "policy": ["document", "procedure"], "document": ["policy"], "breach": ["leak", "exposure"],
    "leak": ["breach"], "incident": ["outage", "disruption"], "audit": ["audits"], "user": ["person", "colleague"],
    "person": ["user"], "colleague": ["user"], "add": ["create", "new"], "create": ["add"], "remove": ["deactivate"],
    "delete": ["deactivate"], "supplier": ["vendor"], "vendor": ["supplier"], "kri": ["indicator"],
    "indicator": ["kri"], "aiia": ["assessment"], "dsar": ["dsr"], "mfa": ["two", "factor"],
}


def _stem(t: str) -> str:
    for suffix, keep in (("ments", 5), ("ment", 5), ("ings", 6), ("ing", 6), ("ions", 6), ("ion", 5), ("ies", 4),
                         ("es", 4), ("s", 3)):
        if t.endswith(suffix) and len(t) > keep and not t.endswith("ss"):
            return t[:-len(suffix)] + ("y" if suffix == "ies" else "")
    return t


def _words(text: str) -> list:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in _STOP and (len(w) > 1 or w.isdigit())]


def tokens(text: str) -> set:
    """Stems of the meaningful words in an entry's text."""
    return {_stem(w) for w in _words(text)}


def _query(text: str) -> list:
    """One group per meaningful word of a question: its stem and its synonyms' stems."""
    return [{_stem(w)} | {_stem(s) for s in _SYNONYMS.get(w, ())} for w in dict.fromkeys(_words(text))]


def _fields(e):
    # Button labels count as body text: a label like "Register in Audit" must not make an entry look like it is
    # about audits.
    return (tokens(e["title"] + " " + (e["nav"] or "")), tokens(e["keywords"]),
            tokens(e["answer"] + " " + " ".join(e["labels"])))


_INDEX = {e["id"]: _fields(e) for e in ENTRIES}
_IDF = {}
for _title, _kw, _body in _INDEX.values():
    for _t in _title | _kw | _body:
        _IDF[_t] = _IDF.get(_t, 0) + 1
_IDF = {t: math.log(1 + len(ENTRIES) / n) for t, n in _IDF.items()}


def visible(entry, user, areas) -> bool:
    if entry["area"] and entry["area"] not in areas:
        return False
    return not entry["caps"] or any(has_capability(user, c) for c in entry["caps"])


def _score(groups, e):
    title, kw, body = _INDEX[e["id"]]
    score, matched = 0.0, 0
    for group in groups:
        best = max(_IDF.get(t, 0) * (3 if t in title else 2 if t in kw else 1 if t in body else 0) for t in group)
        if best > 0:
            score, matched = score + best, matched + 1
    # Most of the question must match: a two-word question needs both words, a three-word one two of them.
    return score if score > 0 and matched >= 0.6 * len(groups) else 0.0


def search(question: str, user, areas, *, page: str = "", limit: int = 4, hidden: bool = False):
    """Entries this person may use, best first, as (score, entry).

    With hidden=True, also return the best score among entries this person may not use, so the caller can say
    "not available to your role" instead of offering a weaker, wrong match.
    """
    groups = _query(question)
    here = next((e["area"] for e in ENTRIES if e["area"] and page.startswith("/" + e["area"].replace("_", "-"))),
                None)
    scored, best_hidden = [], 0.0
    for e in ENTRIES if groups else ():
        score = _score(groups, e)
        if score <= 0:
            continue
        if not visible(e, user, areas):
            best_hidden = max(best_hidden, score)
            continue
        if here and e["area"] == here:
            score *= 1.15
        scored.append((round(score, 3), e))
    scored.sort(key=lambda s: (-s[0], s[1]["id"]))
    return (scored[:limit], best_hidden) if hidden else scored[:limit]


# ── Answering ───────────────────────────────────────────────────────────────
# A question must reach this score before the guide claims to know the answer.
MIN_SCORE = 6.0

_MASKS = [
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[email]"),
    (re.compile(r"\+?\d[\d\s().-]{6,}\d"), "[number]"),
]


def mask(question: str) -> str:
    """Omit contact details and long numbers from the local guide search."""
    for pattern, repl in _MASKS:
        question = pattern.sub(repl, question)
    return question


def target(entry_id: str, allowed_ids) -> dict | None:
    """The page an answer may open: only an entry that was retrieved for, and is open to, this person."""
    e = _BY_ID.get(entry_id or "")
    if not e or e["id"] not in allowed_ids or not e["path"]:
        return None
    return {"id": e["id"], "path": e["path"], "title": e["title"], "show": e["show"]}


def not_for_you() -> str:
    return ("That isn't available to your role in ThemisIQ. If you need it, ask your administrator. I can help with "
            "anything you can open: try Get started for the guided tours.")


def not_covered() -> str:
    return ("I'm not sure about that one. Try asking it another way, for example \"How do I report a breach?\", or "
            "open Get started for the guided tours of the modules you can use.")
