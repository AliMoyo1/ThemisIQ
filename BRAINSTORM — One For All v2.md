# One For All v2 — Brainstorming Document

**Date:** 16 May 2026
**Author:** Ali Moyo + Claude
**Status:** Discussion draft — no code yet

---

## Where We Are Now

Four modules ported and functional: ARIA (policy/compliance), GRID (audit), BCM Sentinel (business continuity), and Data Protection Sentinel (privacy). Each works independently with its own SPA template, color scheme, and navigation pattern. The launcher ties them together, but once you enter a module, you're in a separate world.

The goal of this brainstorming: turn four tools that share a database into one tool that shares a brain.

---

## Inspiration Analysis

Reviewed 72 screenshots across three platforms: ANSR (industrial change/incident management), Kelsa/ANSR (service delivery control tower), and GRACE by Ampicus Cyber (continuous compliance). Here's what stands out.

### What ANSR Does Well

**Visual workflow engine.** Their approval flows aren't just configured — they're drawn. A change request flows through parallel approval lanes (Operations, EBA, Mechanical Maintenance, Safety & Fire Services), converges at a CFT Evaluation node, then fans out again to department heads. The user sees the entire chain as a flowchart. This is the gold standard for incident response workflows.

**Process hazard analysis methods.** HAZOP, BOWTIE, What-If, FMEA, FTA — they offer a dropdown of recognized analysis methodologies. For us, this means incident root-cause analysis shouldn't be freeform text. It should be structured by methodology.

**MOC Checkpoint matrices.** A table of activities with Applicable/Not Applicable flags, action details, responsible person, target date, and attachment slots. This pattern maps directly to compliance control checklists, audit evidence collection, and BCM exercise tasks.

**Configurable KPI dashboards.** Users pick chart type (bar, stacked bar, pie, area, table, timeseries, line, funnel, single value) and the data dimension. Department-wise KPI, stage-wise KPI, funnel views showing pipeline progression. The funnel view (73 MOCs Initiated → 62 Approved → 33 Ready → 18 CFT Done → 11 Technical Review → 9 All Approvals → 7 Checkpoint Tasks → Change Completed) is exactly what we need for policy lifecycle, audit progress, incident resolution, and DPIA stages.

**Multi-step conditional forms.** Incident creation walks through: incident area → type → root cause categories (checkboxes) → parties involved → investigation details. Each step shows/hides fields based on prior answers. Not just tabs — conditional logic.

### What GRACE Does Well

**Project-centric compliance.** Instead of "here's a list of controls," GRACE says "here's your ISO 27001 project" and everything — evidence checklist, action tracker, overview dashboard — lives under that project. Multiple frameworks (PCI SSF, ISO 27001, PCI DSS) run as parallel projects. This is the mental model we should adopt: a "Compliance Project" is the top-level container.

**Evidence as a first-class entity.** Evidence isn't just a file upload on a control. It has its own lifecycle: uploaded → pending review → under auditor review → approved/rejected. Evidence can be tagged, made reusable across frameworks, linked to multiple controls. There's an Evidence Repository page that shows all evidence across all projects. The upload flow lets you add shared tags, per-file tags, shared notes, per-file notes, and a "Make reusable across frameworks" checkbox.

**Role-specific dashboards.** GRACE has three distinct dashboard views: Client Admin (sees everything + assignment capabilities), Contributor (sees My Projects + Evidence Submitted + Pending Review + Approved), and Auditor (sees Pending Reviews + Under Review + Reviewed by Me + Queue Size + CISO Executive Dashboard). Each role sees what matters to them, not a one-size-fits-all.

**AI-assisted evidence analysis.** Upload a document, click "Generate AI Analysis," and it does: Indexing → Summary → AI Analysis. Then you get a "Chat with Evidences" panel where you ask questions about compliance gaps, content, and recommendations. This is exactly what we should do with ARIA policies, GRID audit evidence, and BCM plans.

**Action Tracker with auto-creation.** When evidence is rejected, the system auto-creates an action item: "Evidence Rejected — Auto-created checklist item." The action item tracks severity, observation, action point, assigned person, target date, and has tabs for Details, Comments, Evidence FIs, and History. This is a workflow engine in disguise.

**Multi-company context switching.** A "Switch Company Context" modal lets the user toggle between companies. For enterprise deployment, this maps to multi-tenancy or department-level isolation.

### What Kelsa/ANSR Control Tower Does Well

**SLA-driven oversight.** Everything is measured against SLAs. Request volume by month, SLA compliance trend, breach breakdown (Met SLA / Minor Breach / Major Breach), team health cards with SLA compliance % and average resolution time. The "Top SLA Risks" table shows which tickets are closest to breaching. This pattern applies to every module: policy review deadlines, audit evidence due dates, incident response SLAs, DPIA completion targets.

**Horizontal bar charts for status-by-category.** Simple but effective — shows On Track / At Risk / Overdue per category in a stacked horizontal bar. Works for any dimension.

---

## The Big Ideas

### 1. One Shell, Four Lenses

**Current state:** Each module is its own SPA with its own sidebar, topbar, and color scheme. You navigate between modules via the launcher, which feels like switching apps.

**Proposed state:** A single persistent app shell with:
- A narrow icon sidebar on the left (always visible) for module switching — like ANSR
- A topbar with breadcrumb navigation showing: Module > Section > Item
- A secondary sidebar (collapsible) that shows the current module's navigation tree
- A unified notification bell, user menu, and global search in the topbar
- Module accent colors only as subtle indicators (sidebar icon highlight, section headers), not full-page color schemes

The key insight from GRACE: even though they have Projects, Evidence, Review, and Analytics as separate sections, they all feel like the same app because the shell never changes. Only the content area swaps.

**What changes technically:** We'd build a single `base_shell.html` that all modules inherit. The current per-module SPAs become sections within the shell. Module switching is a sidebar click that swaps the content area, not a full page navigation.

### 2. Compliance Projects as the Organizing Principle

**Current state:** ARIA manages frameworks and controls. GRID manages audits. These are separate worlds.

**Proposed state:** Introduce a "Compliance Project" entity that sits above modules. A project might be "ISO 27001:2022 Certification" and it pulls in:
- ARIA: the framework, its controls, policies mapped to those controls
- GRID: the audit(s) targeting those controls, evidence collection
- BCM: continuity plans linked to those controls
- Sentinel: DPIAs, RoPA entries, breach procedures relevant to that framework

This is how GRACE works — the project is the container, and evidence, checklists, and actions are children of it. For us, a Compliance Project would be the cross-module umbrella that lets someone say "show me everything related to our ISO 27001 effort."

**Multi-standard support:** Each project maps to one or more standards. The platform ships with built-in mappings for ISO 9001, ISO 14001, ISO 20000-1, ISO 27001, ISO 31000, ISO 45001, ISO 50001, and SOC 2 / PCI DSS. An "Add Standard" wizard lets users import custom frameworks via CSV/JSON or build them manually. Cross-mapping between standards (e.g., ISO 27001 Annex A.8 ↔ SOC 2 CC6) is already partially built in ARIA — we'd promote it to a platform-level feature.

### 3. Universal Workflow Engine

**Current state:** Workflows are hardcoded. A policy goes Draft → Review → Approved. An incident goes Open → Investigating → Resolved. These state machines live in route handlers.

**Proposed state:** A platform-level workflow engine where:
- Workflows are defined as directed graphs (like the ANSR approval flow diagrams)
- Each node is a stage with: entry conditions, assigned role(s), required actions, auto-notifications, SLA timer
- Transitions between nodes can be: manual approval, conditional (if severity > 3 → escalate), automatic (after 48h with no action → reminder)
- Parallel paths supported (ANSR-style: multiple departments must approve simultaneously before convergence)
- Workflows are reusable templates: "Standard Policy Approval," "Critical Incident Response," "Evidence Review Chain"

**What this enables:**
- Policy lifecycle: Draft → Author Review → Compliance Review → Legal Review → Board Approval → Published (with conditional fast-track for minor updates)
- Incident response: Declared → Triage → Impact Assessment → (parallel: Comms Plan + Recovery Actions + Stakeholder Notification) → Resolution → Post-Incident Review → Closed
- Audit evidence: Uploaded → Pending Review → Auditor Review → Approved/Rejected (with auto-action-item on rejection, like GRACE)
- DPIA processing: Initiated → Screening → Full Assessment → DPO Review → Published

**Visual workflow builder:** Users should be able to see and edit workflows as flowcharts, not just as configuration tables. The ANSR screenshots show this is possible and highly valuable for compliance managers who think visually.

### 4. Evidence as a Platform Entity

**Current state:** Evidence is scattered. GRID has evidence uploads per audit control. ARIA has document attachments. BCM has plan documents. Sentinel has DPIA attachments.

**Proposed state:** A centralized Evidence Repository (like GRACE) where:
- Any file upload anywhere in the platform creates an evidence record
- Evidence has: file, tags, notes, upload date, uploader, status (draft/submitted/under review/approved/rejected), linked entities
- Evidence can be linked to multiple controls, across multiple frameworks, across multiple modules
- "Make reusable across frameworks" checkbox during upload
- Evidence search: find by filename, tags, status, uploader, linked framework
- Evidence approval workflow: configurable per project (some need auditor sign-off, some are auto-approved)
- AI analysis on evidence: upload a document, get automatic indexing + summary + gap identification + chat capability

**Why this matters:** During an ISO 27001 audit, the same "Information Security Policy" document might satisfy controls A.5.1 (Policies for information security), relate to a BCM plan, and be evidence for a DPIA. Today you'd upload it three times. With a centralized evidence repository, you upload once and link everywhere.

### 5. Role-Specific Dashboards

**Current state:** Each module has one dashboard that shows the same thing to everyone.

**Proposed state:** Three dashboard tiers (inspired by GRACE):

**Executive Dashboard** (for Super Admin, Compliance Manager, DPO):
- Cross-module KPIs: overall compliance score, critical risk count, overdue actions, audit readiness
- Risk Heatmap: severity × status matrix
- Compliance Score Over Time trend
- Evidence Submission Velocity
- At-Risk Items and High Rejection Rate Areas

**Operational Dashboard** (for module-specific roles like Policy Author, Audit Lead, BCM Manager):
- Module-specific metrics with actionable cards
- "Needs Attention" / "Due Soon" / "Overdue" traffic-light KPIs
- Assignment distribution charts (who's carrying the load)
- Progress funnels (like ANSR's MOC funnel)

**Contributor Dashboard** (for Control Owner, Auditor, BCM Responder, Privacy Analyst):
- "My Tasks" with overdue/due today/upcoming counts
- "My Projects" card grid
- Items assigned to me, pending my action
- Personal completion stats

**Auditor/External Dashboard** (for External Auditor):
- Read-only cross-module view
- Evidence status overview
- Pending Reviews queue

### 6. SLA-Driven Everything

**Inspired by:** Kelsa/ANSR Control Tower's SLA tracking.

Every actionable item in the platform gets an SLA:
- Policy review: 14 days from submission to approval
- Audit evidence: 7 days from assignment to upload
- Incident response: 1 hour for critical, 4 hours for high, 24 hours for medium
- DPIA completion: 30 days from initiation
- Breach notification: 72 hours (GDPR requirement)
- BCM plan review: quarterly

SLA configuration is per-project, per-item-type. The dashboard shows:
- SLA compliance % (overall and per team/department)
- Breach trend over time
- Top SLA risks (items closest to breaching)
- Team health cards (SLA compliance + average resolution time)

Automatic escalation when SLAs are at risk: email notification at 75% of time elapsed, escalation to manager at 90%, breach notification at 100%.

### 7. Structured Incident & Change Management

**Inspired by:** ANSR's multi-step incident forms and process hazard analysis.

**Incident lifecycle redesign:**
1. **Declaration** — multi-step form: What happened → Impact assessment → Severity classification (auto-suggested by AI based on description) → Initial responders
2. **Triage** — structured root cause analysis using recognized methodologies (selectable: 5-Whys, Fishbone/Ishikawa, HAZOP, Bowtie, FMEA, FTA, Fault Tree)
3. **Response** — parallel workstreams: Communications (internal + external templates), Recovery Actions (assigned tasks with SLAs), Stakeholder Management (notification log)
4. **Resolution** — checkpoint matrix (like ANSR's MOC Checkpoints): list of required actions, applicable/NA flag, responsible person, target date, evidence attachment, completion status
5. **Post-Incident Review** — structured lessons-learned form, control improvement recommendations, auto-link to relevant ARIA controls for remediation

**Change management integration:** When an incident reveals a control gap, the system can auto-create a change request that flows through its own approval workflow. This bridges BCM → ARIA.

### 8. AI Everywhere, Consistently

**Current state:** Each module has its own AI stub service with different capabilities.

**Proposed state:** A unified AI service layer with consistent patterns across all modules:

**Document Intelligence** (everywhere):
- Upload any document → auto-index, summarize, extract key entities
- "Chat with this document" on any attachment (GRACE-style)
- Cross-reference against framework requirements

**Smart Suggestions** (context-aware):
- Policy drafting: suggest content based on framework requirements and existing policies
- Audit: gap analysis by comparing evidence against control requirements
- BCM: incident action suggestions based on incident type and severity
- Sentinel: DPIA risk scoring based on processing descriptions

**Narrative Generation** (for reporting):
- Executive summaries for any dashboard view
- Board report narratives from statistics
- Audit report generation from findings

**Classification & Routing** (for workflow):
- Auto-classify incident severity from description
- Auto-suggest framework mappings for new controls
- Auto-tag evidence based on content analysis

### 9. Unified Notification & Communication System

**Current state:** No notification system.

**Proposed state:**
- In-app notification panel (bell icon in topbar, like GRACE)
- Notification types: assignment, approval request, SLA warning, SLA breach, status change, comment/mention
- Notification preferences per user (in-app only, email, or both)
- @mentions in comments across all modules
- Communication templates for incident response: pre-built templates for internal notifications, external stakeholder comms, regulatory notifications (GDPR breach notification)
- Audit trail: every notification sent is logged

### 10. Reporting Engine

**Current state:** Each module has basic stats. No cross-module reporting.

**Proposed state:**

**Board-Level Reports:**
- Cross-module compliance posture report
- Risk landscape summary (risks from ARIA + BCM + Sentinel in one view)
- Audit readiness scorecard
- Incident trend analysis
- Privacy programme status

**Operational Reports:**
- Per-standard compliance status (ISO 27001: 78% controls satisfied, 12% in progress, 10% not started)
- Evidence collection progress per project
- SLA performance by team
- Overdue items aging report

**Configurable Dashboards:**
- ANSR-style chart type picker (bar, line, pie, funnel, table, timeseries)
- Drag-and-drop KPI cards
- Save/share dashboard configurations
- Export to PDF for board packs

**Automated Scheduled Reports:**
- Weekly compliance digest
- Monthly board report
- Quarterly audit readiness summary

### 11. Multi-Standard Governance Framework

**Standards to support out of the box:**

| Standard | Domain | Key Additions to Platform |
|---|---|---|
| ISO 9001:2015 | Quality Management | Process approach, customer focus metrics, continual improvement tracking |
| ISO 14001:2015 | Environmental Management | Environmental aspects register, legal compliance tracking, environmental KPIs |
| ISO 20000-1:2018 | IT Service Management | Service catalogue, SLA management, capacity planning, incident/problem/change management |
| ISO 27001:2022 | Information Security | Already covered by ARIA + GRID |
| ISO 31000:2018 | Risk Management | Already partially covered — needs formal risk framework alignment |
| ISO 45001:2018 | Occupational Health & Safety | Hazard identification, OH&S risk register, worker consultation records |
| ISO 50001:2018 | Energy Management | Energy baseline, EnPIs, energy review, significant energy uses |
| SOC 2 | Service Organization Controls | Trust services criteria, type I/II report support |
| PCI DSS | Payment Card Industry | Cardholder data environment scope, SAQ support |
| GDPR | Data Protection | Already covered by Sentinel |
| Custom | User-defined | Import via CSV/JSON, define clauses, map to controls |

**Architecture:** A `governance_standards` table with standard metadata. A `standard_requirements` table with individual clauses/controls. A `requirement_mappings` table for cross-standard mapping (ISO 27001 A.8.1 ↔ SOC 2 CC6.1 ↔ PCI DSS 3.1). When a user satisfies a control in one standard, the platform highlights mapped controls in other standards that may also be satisfied.

**ESG Support:** The Kelsa/ANSR screenshots show ESG assessment questionnaires with sections for Compliance & Governance, Health & Safety, Environment, Supply Chain, Labour & Human Rights. This is a natural extension — ESG frameworks (GRI, SASB, TCFD) as additional standards with questionnaire-based assessment.

### 12. Checkpoint Matrices

**Inspired by:** ANSR's MOC Checkpoint system.

A reusable pattern across all modules:

| Use Case | Heading | Activities |
|---|---|---|
| Audit Evidence Collection | Control Clause | Evidence items required, applicable/NA, upload status, reviewer, due date |
| Incident Response Checklist | Response Phase | Required actions, assigned responder, completion status, evidence |
| BCM Exercise Tasks | Exercise Objective | Tasks to complete, responsible person, pass/fail, observations |
| Policy Review Checklist | Review Criteria | Items to verify, reviewer assessment, comments |
| Compliance Questionnaire | Assessment Area | Questions, Yes/No/NA, evidence reference, score |

Build this once as a platform component, then use it everywhere.

---

## Technical Approach (High Level)

### New Database Entities

```
compliance_projects       — top-level project container
project_standards         — which standards a project covers
governance_standards      — standard metadata (ISO 9001, etc.)
standard_requirements     — individual clauses per standard
requirement_mappings      — cross-standard control mapping
evidence_repository       — centralized evidence store
evidence_links            — evidence ↔ entity relationships
workflow_templates        — reusable workflow definitions
workflow_instances         — running workflow instances
workflow_nodes            — stages within a workflow
workflow_transitions      — edges between stages
workflow_actions          — pending/completed actions in a workflow
notifications             — user notifications
notification_preferences  — per-user notification settings
sla_definitions           — SLA rules per entity type
sla_instances             — tracked SLAs on specific items
dashboard_configs         — saved dashboard layouts per user
report_templates          — saved report configurations
checkpoint_templates      — reusable checkpoint matrix definitions
checkpoint_instances      — checkpoint matrices in use
checkpoint_items          — individual items within a matrix
```

### New Platform Services

```
core/workflow_engine.py    — workflow execution, transition logic, SLA timers
core/evidence_service.py   — centralized evidence CRUD, linking, search
core/notification_service.py — notification dispatch, email integration
core/sla_service.py        — SLA tracking, escalation logic
core/reporting_service.py  — cross-module report generation
core/ai_service.py         — unified AI layer (document intelligence, classification)
```

### Migration Path

This isn't a rewrite — it's an evolution. The existing modules keep working while we layer platform services on top:

1. **Phase A — Unified Shell:** Replace per-module SPAs with a single app shell. Modules become content panels within it. No backend changes.
2. **Phase B — Compliance Projects + Multi-Standard:** Add the project entity, governance standards tables, and requirement mappings. Existing ARIA frameworks become children of projects.
3. **Phase C — Evidence Repository:** Centralize evidence. Existing file uploads migrate to the evidence repository with backward-compatible links.
4. **Phase D — Workflow Engine:** Build the engine. Migrate hardcoded state machines to workflow definitions. Start with policy approval and evidence review.
5. **Phase E — Notifications + SLAs:** Add notification infrastructure and SLA tracking. Wire into existing entities.
6. **Phase F — Dashboards + Reporting:** Build role-specific dashboards and the reporting engine. Replace current per-module dashboards.
7. **Phase G — AI Unification:** Consolidate AI services into a single platform layer with consistent patterns across modules.

---

## Open Questions for Discussion

1. **Workflow builder UI:** Should we build a visual drag-and-drop workflow editor (like ANSR), or start with a template library where users pick and customize pre-built workflows?

2. **Multi-tenancy:** The GRACE "Switch Company Context" feature — do we need this? If this is deployed for one enterprise, departments might serve the same purpose. If it's multi-tenant (MSP serving multiple clients), we need full data isolation.

3. **Evidence AI depth:** How far do we go with AI evidence analysis? Simple summarization? Full gap-analysis against the linked control requirement? Conversational Q&A with the document? All three?

4. **Offline capability:** Since this is hosted on a Windows laptop, do we need offline support? If the laptop loses network, should users still be able to view dashboards and enter data?

5. **ESG integration:** Is ESG (Environmental, Social, Governance) in scope for v2, or is it a v3 addition?

6. **External auditor portal:** Should external auditors get a stripped-down web interface they can access remotely, or do they always use the platform on-site?

7. **Dashboard customization depth:** Full drag-and-drop dashboard builder (like ANSR's chart type picker), or curated role-based views with limited customization?

8. **Mobile responsiveness:** Enterprise laptop deployment suggests desktop-first, but should the UI be responsive enough for tablet use during on-site audits?

---

## Priority Recommendation

If I had to sequence by impact, I'd go:

1. **Unified Shell** — biggest bang for "feels like one app" with least backend change
2. **Role-Specific Dashboards** — immediately makes every user's experience better
3. **Multi-Standard Governance** — unlocks ISO 9001, 14001, 20000-1, 31000, 50001 support
4. **Evidence Repository** — cross-module reuse is a daily pain point for compliance teams
5. **Workflow Engine** — the foundation for everything else (SLAs, notifications, approval chains)
6. **SLA Tracking + Notifications** — automates follow-up and escalation
7. **Reporting Engine** — board reporting and cross-module analytics
8. **AI Unification** — cherry on top, builds on all the above

---

*This document is for discussion. Nothing is decided. Let's talk through what resonates, what's missing, and what order makes sense for your organization.*
