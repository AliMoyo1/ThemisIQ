# Features page: content breakdown

Companion to [PLAN-features-page.md](PLAN-features-page.md). Date: 2026-10-20. This is the content brief for
`/features`: what each section says, what it shows, and how the two flagship stories (Sentinel across jurisdictions and
the integrated management system in ARIA and GRID) are demonstrated. Owner decisions applied: AI Governance is the
seventh module, no numbers are published, the security section waits for the owner's go.

Every capability below was checked against `master` (`790ce1c`) and names its source, so copy can be traced. Wording
is a draft for review, written from the visitor's side. No em dashes in final copy.

## Page outline

| # | Section | Anchor | Job |
| --- | --- | --- | --- |
| 0 | Header and search | `#top` | Say what the page is; let a visitor find a capability fast |
| 1 | What sets ThemisIQ apart | `#why` | Five platform-wide strengths before the detail |
| 1a | AI across the platform | `#ai` | **The AI story**: what the assistants do in every module, and the guardrails |
| 2 | Governance and controls (ARIA) | `#governance` | Frameworks, policies, controls; **policy authoring studio**; **IMS story part 1** |
| 3 | Audit (GRID) | `#audit` | Audits, findings, corrective action; **IMS story part 2** |
| 4 | Privacy (Sentinel) | `#privacy` | **Multi-jurisdiction story** |
| 5 | Resilience (BCM) | `#resilience` | Impact analysis to incident response |
| 6 | Enterprise risk (ERM) | `#enterprise-risk` | Appetite, KRIs, scenarios, horizon scanning |
| 7 | Operations risk (ORM) | `#operations-risk` | Events, RCSA, KRIs |
| 8 | AI Governance | `#ai-governance` | The seventh module |
| 9 | Evidence Vault | `#evidence` | One proof, many uses |
| 10 | Work, notifications and reporting | `#work` | How people actually get through the day |
| 10a | Connected governance | `#connected` | The layer that ties records together across modules |
| 11 | Integration and administration | `#platform` | API, webhooks, users, units |
| 12 | Security and trust | `#security` | **Held** until the owner's go |
| 13 | Frameworks and jurisdictions | `#frameworks` | The catalogue, without counts |
| 14 | Demo request | `#contact` | Same form as the landing page |

Each module section uses the same template so the page scans well:

1. Eyebrow (module name and discipline) and a one line promise.
2. A screenshot or an interactive study (one per section, never both large).
3. Three to six capability groups, each a short heading with two to four one-line capabilities.
4. "Works with" chips naming the other modules it connects to.
5. A role tag row for the filter (Compliance, Privacy, Audit, Risk, Continuity, AI, IT and security, Leadership).

## 0. Header and search

- Title: **Everything ThemisIQ does, in one place.**
- Line: "Every module, the shared evidence vault and the everyday tools that keep the work moving. Search for a
  capability or filter by your role." (No count: numbers are on hold.)
- Search box (filters the capability lines as you type) and role chips. Results keep their section heading so context
  is not lost. With no script, the full page still reads top to bottom.

## 1. What sets ThemisIQ apart (`#why`)

Five tiles, each with one sentence and a link to where it is proven further down. These are the "one of the best"
argument, stated as facts a buyer can check in the demo, not as superlatives.

| Tile | Copy | Proven in |
| --- | --- | --- |
| **Connected, not bolted together** | "A confirmed breach can open work in risk, operations and audit, and every team sees its own next step from the same event." | Sentinel, ERM, ORM, GRID event path (`sentinel.breach.confirmed`) |
| **One control, many standards** | "Map equivalent controls across standards once, then audit them side by side in one integrated audit, with the same evidence." | Sections 2 and 3 |
| **Rules for each jurisdiction, approved by people** | "Each privacy rule is drafted by a specialist and approved by a different DPO before it drives a deadline." | Section 4 |
| **A second pair of eyes built in** | "Decisions, mappings and rule changes ask for someone other than the author to approve them." | AI decisions, IMS mapping review, Sentinel cards, report sign-off |
| **AI you can govern** | "Every assistant follows your organisation's AI policy, cites its sources where it answers from your records, and leaves the decision to a person." | Section 1a and the AI line in each module |

## 1a. AI across the platform (`#ai`)

Promise: **"An assistant in every module, working from your records, governed by your policy."**

AI is a headline of the page, so it gets its own section here and a highlighted "AI" line in every module section.

### What the assistants do, by module (each line is a registered AI feature)

| Module | Assistance |
| --- | --- |
| ARIA | Write a policy, procedure, standard, guideline or framework for a control (also as one integrated document across standards); gap analysis; Ask ARIA with sources; control generation for a framework; proposed control matches across standards |
| GRID | Read an imported checklist; suggest control details; risk score audit items in bulk; gap analysis; audit report narrative; incident checklist; compliance questions |
| Sentinel | Research a processing activity; full DPIA draft; suggest risks; score a record of processing; suggest a legal basis; assess a breach; draft a reply to a subject request; draft a privacy notice; vendor check; compare two regimes (gap analysis); privacy chat |
| BCM | Draft a continuity plan from a scenario; review a plan; suggest incident actions; answer from your continuity documents; board narrative; chat |
| ERM | Score a risk and suggest scores; suggest treatments; write risk statements; suggest assessment questions and find risks in the answers; remediation plan; horizon scan with checked sources; board narratives; chat |
| ORM | Analyse an event; trend narrative; chat |
| AI Governance | Explain an AI use in plain words for reviewers |
| Evidence Vault | Find evidence by meaning; suggest links to controls, audits and risks you can see |
| Platform | Morning briefing; executive summary; predictive risk; how-do-I guide |

### The guardrails (the part competitors rarely show)

- **Your policy decides**: per organisation, which providers, which kinds of data, which features and a monthly budget.
  A refused call never leaves the platform.
- **Grounded, with sources**: answers drawn from your records say where they came from; external sources are checked
  before they are cited.
- **People decide**: drafts are drafts; approvals, decisions and publication are always a person's act, and many need a
  second person.
- **Kept on record**: every AI call is logged with its feature, outcome and usage; every AI feature is registered with
  what it reads, what it leaves out and what happens to its answer.
- **Scope respected**: suggestions are checked against what the person may open before they are shown.
- **Honest when unavailable**: if the assistant is off or fails, nothing is invented; the person is told and the manual
  path stays open.

Showcase: a module switcher (ARIA, Sentinel, BCM, ERM, GRID, AI Governance) that swaps one example assistant card,
each with its "Human review required" and source line, plus a small "AI policy" card showing the four controls.

Copy notes: say "when an AI provider is configured"; never imply automatic approval; no count of AI features (numbers on
hold). Source: `core/ai_policy.py` (`FEATURES`), `core/ai_declarations.py`, `core/ai_client.py`.

## 2. Governance and controls: ARIA (`#governance`)

Promise: **"Give every control its context, across every standard you follow."**

### Policy authoring studio (flagship)

The single most demonstrable AI feature, shown as a five step interactive study with a real looking document.

1. **Generate.** Pick a control and a document type (policy, procedure, standard, guideline or framework). The assistant
   writes a complete first draft in the voice the standard expects, for your organisation's name, with optional
   instructions from the requester ("emphasise remote work"). Option: an **integrated document** that covers the control
   and its mapped controls in other standards in one text (links to the IMS story below).
2. **Edit.** The draft opens in the Policy Workbench as a working draft. Edit the text, save as you go, discard a draft
   or recover a discarded one. Several authors can contribute and each is recorded.
3. **Preview in your template.** Build the draft into your own branded Word template (uploaded once under Templates) and
   see the finished document as a PDF preview before anything is official.
4. **Approve.** Confirm the build as a version, choose an approver, submit. The author and the person who submitted can
   never approve it. Compare any two retained versions line by line.
5. **Publish and reuse.** On approval the version is published, filed in the Evidence Vault under that exact version,
   and attached as evidence to the matching GRID controls. Start a revision later without touching what was approved.

Footnote: "Illustrative example. Every draft is reviewed and approved by people before it is published." Copy note:
the authoring workflow is switched on per organisation.

Source: `modules/aria/routes.py` (`/api/generate-policy` with `integrated_framework_id` and `custom_instructions`,
`/api/generate-gap-analysis`, templates), `modules/aria/ai_generator.py` (document types, framework voice),
`modules/aria/routes_policy_workflow.py` and `policy_workflow_service.py` (drafts: save, discard, recover, build,
preview, confirm, submit, decide; requester and authors excluded from approving), `policy_preview.py` (conversion
worker), `policy_storage.py` (branded DOCX and PDF preview), `policy_publication.py` (Evidence Vault and GRID evidence by
version), `templates/policy_workbench.html` (working draft, compare versions, history).

### IMS story, part 1: one set of controls for many standards

The flagship interactive study for this section, built like the landing page's existing studies (illustrative data,
labelled as such).

1. **Pick standards.** Chips for, say, ISO 9001, ISO 14001, ISO 45001 and ISO 27001. The visitor selects two or more.
2. **See the overlap.** A three column view: controls shared by the selected standards (integrated), controls partly
   matched, and controls unique to one standard. Example rows show a document control or management review clause
   lining up across standards.
3. **See how matches are found.** A small three step strip: grouped by topic, compared by wording, and only the unclear
   pairs offered to the assistant. Proposed matches wait in a queue.
4. **See who approves.** A proposed match card with "Awaiting a different reviewer". The person who proposed it cannot
   approve it.
5. **Hand off to audit.** A button "Audit these together" scrolls to section 3, where the same controls appear in one
   integrated audit.

Footnote: "Illustrative example. Matches in your organisation are proposed from your frameworks and approved by your
reviewers."

Source: `core/auto_mapper.py` (three pass matching, IMS status), `modules/aria/templates/mapping.html` (IMS Control
Mapping, Integrated Controls, Unique Controls, Partial Matches, "Awaiting a different reviewer").

### Capability groups

- **Frameworks**: load standards from the catalogue, manage their controls, track status per control.
- **Integrated management system**: propose equivalent controls across standards, review matches with a second person,
  see each control's integrated status.
- **Policies and documents**: author, review and approve policies with versions; generate a reviewable first draft for a
  control; publish an approved version; keep the history.
- **Ask ARIA**: ask a question and get an answer drawn from your approved policies and controls, with the source shown.
- **Controls and evidence**: attach proof from the Evidence Vault to the control it supports.
- **Gap analysis**: an assisted gap analysis of a framework against what is already in place.
- **Branded documents**: upload your company templates and apply them to policy documents.
- **Governance risks**: a risk list tied to controls and policies.
- **Activity log**: who changed which control, policy or document.
- **Compliance projects**: run a certification or readiness project per framework from the platform.

Works with: GRID, Evidence Vault, ERM, AI Governance.

## 3. Audit: GRID (`#audit`)

Promise: **"Plan, run and close audits, alone or across several standards at once."**

### IMS story, part 2: one integrated audit

Interactive study continuing from section 2.

1. **Create an integrated audit.** A form preview with "Integrated audit" switched on and several standards selected.
2. **Controls arrive mapped.** One checklist holds every selected standard's controls. Equivalent controls are linked
   from the approved ARIA matches, and each control is badged integrated, partly matched or unique, so the team tests
   equivalents side by side and reuses the same evidence. (Results are not copied between controls automatically; do
   not claim "test once, pass all".)
3. **Findings to closure.** A nonconformity raised on a shared control, its corrective action plan, due date, evidence
   and sign-off on one timeline.
4. **Share with the auditor.** A time limited share link for an external auditor.

Footnote: "Illustrative example."

Source: `modules/grid/data_service.py` (`is_integrated`, `framework_ids`, mappings created from approved
`aria_control_mappings` of type equivalent or IMS equivalent, IMS status badge), `grid_share_links`,
`grid_non_conformances`, `grid_audit_signoffs`, `grid_timeline`.

### Capability groups

- **Audit planning**: scope, objective, criteria and method; single standard or integrated audits; units and owners.
- **Fieldwork**: checklists per control, comments, evidence with versions, remote audit sessions and findings.
- **Findings and corrective action**: nonconformities with evidence, corrective action plans, reminders, approvals and
  sign-off.
- **Vendors**: vendor assessments within the audit programme.
- **Reporting**: compliance scores and audit reports; a timeline of what happened.
- **External auditors**: expiring share links to a read only audit view; review packs for AI audits (see section 8).
- **Policy requests**: ask the policy owner for a missing or updated policy from inside an audit.
- **Checklist import**: bring in an existing audit checklist instead of retyping it.
- **Audit assistant**: ask questions about the audit in an in-module chat.

Works with: ARIA, Evidence Vault, Sentinel (a breach can open an audit review), ERM.

## 4. Privacy: Sentinel (`#privacy`)

Promise: **"One privacy desk for every jurisdiction you answer to."**

### Multi-jurisdiction story: one breach, several duties

The flagship study for this section. It extends the landing page's jurisdiction picker, which shows one rule at a
time, into the thing Sentinel actually does: hold several obligations on one breach.

**Panel A: the rule library.** Cards for every jurisdiction Sentinel supports, grouped by region with a region filter
(the full list is in section 13). Each card shows: the authority, the kind of notice, what starts the clock, the period or "as soon as
reasonably possible", the source, and its status. Status is the point of the panel:

- **Draft**: written by a privacy specialist, with its source and effective dates.
- **Approved**: approved by a different DPO. Only an approved card can produce a deadline.
- **Indicative**: a reference timing that is labelled as an internal target, not a legal deadline.

**Panel B: one breach, several obligations.** A sample breach affecting people in two or three jurisdictions. The
visitor adds jurisdictions; each becomes its own obligation row with:

- the approved card it follows,
- the trigger time recorded with its timezone and source facts,
- its own countdown (or "as soon as reasonably possible" where the law sets no hours),
- a decision: notify, or record why not.

**Panel C: requests from people.** Subject requests with their own timing per jurisdiction, labelled as an internal
target where the law sets no single period.

Footnote, carried over from the landing page and strengthened: "Illustrative example. Rules are approved by your own
privacy specialists. Notification duties depend on the event and current law."

Copy rule: name every jurisdiction (owner decision: all will be ready at launch), but never show a count (numbers on
hold). Launch gate: before the page goes live, each card's rule is confirmed by the privacy specialist and approved by
a different DPO, as `plans/2026-10-governance-rework/15` requires; any card not ready is left off rather than shown as
approved.

Source: `modules/sentinel/obligations.py` (versioned cards, DPO approval, per breach obligations with sourced trigger
and timezone, decisions; "only a DPO approved card and a confirmed, sourced trigger can produce an operational
deadline"), `modules/sentinel/jurisdictions.py` (registry, breach and request timing, authorities, ASAP handling),
`scheduler.py` (breach and request deadline monitoring).

### Capability groups

- **Records of processing**: processing activities, data flows, legitimate interest assessments.
- **Assessments**: DPIAs with an assisted first draft for review.
- **Breaches**: register, severity, per jurisdiction obligations and deadlines, alerts to the people named to receive
  them, and an alternate contact for deadline alerts.
- **Requests from people**: subject requests with deadlines and overdue alerts.
- **Consent and vendors**: consent records; vendors with data protection agreement status, shared with the vendor
  directory.
- **Policies and training**: privacy policies and staff training.
- **Privacy notices**: the notices you publish, kept with the processing they describe.
- **Controllers and processors**: who acts in which role for each processing activity.
- **Legal bases**: the lawful basis recorded for each activity.
- **International transfers**: cross-border transfers and their safeguards, which matters most when you answer to
  several jurisdictions.
- **Retention**: retention periods with scheduled reviews.
- **Security measures**: the technical and organisational measures that protect personal data.
- **Compliance score and export**: a privacy compliance score and an export for regulators or auditors.
- **Privacy assistant**: in-module chat and assisted analysis of DPIAs, records and breaches, for review.

Works with: ERM (regulatory obligation), ORM (operational event), GRID (audit review), Evidence Vault, AI Governance
(AI impact assessments).

## 5. Resilience: BCM (`#resilience`)

Promise: **"Know what matters most, and be ready when it stops."**

### Showcase

Screenshot of the BCM dashboard, plus a small incident escalation strip: an incident raised, the named owner alerted,
no acknowledgement within the window for its severity, the alert moves to the next person. Source:
`modules/bcm/escalation.py`.

### Capability groups

- **Business impact analysis**: processes, recovery objectives, impact ratings, resources and dependencies.
- **Dependency map**: the processes, systems and suppliers that depend on each other.
- **Plans**: continuity plans with reviews, activation records and links to the processes they protect.
- **Incidents**: incident log with actions, decisions, updates and stakeholders; escalation to alternates when an alert
  is not acknowledged.
- **Exercises and training**: exercises from a scenario library; training modules with attestations.
- **Communications**: message templates and a contact tree.
- **Suppliers and compliance**: vendor assessments; continuity controls with their evidence.
- **Ask your plans**: questions answered from your uploaded continuity documents.
- **Continuity risks**: risks to recovery, kept with the processes they affect.
- **Reports and board narrative**: continuity reports with an assisted narrative for review.

Works with: ORM, ERM, Evidence Vault, Sentinel.

## 6. Enterprise risk: ERM (`#enterprise-risk`)

Promise: **"See the risks that shape your objectives, and test them before they happen."**

### Showcase

Scenario Studio, already teased on the landing page: baseline against a what if, the risks and controls affected, and
a board pack snapshot. Second, smaller: the horizon scan review queue with source verification.

Third, compact: **predictive risk**. A static panel (not a second interactive) showing the signals it combines from
every module (exercise age in BCM, control gaps in ARIA, breaches in Sentinel, findings in GRID, repeat events in ORM,
appetite in ERM), how each contributes, and the confidence shown for human review. Labelled illustrative, with a link
"Try the interactive version" to the landing page's intelligence section. Source: `core/predictive_risk.py`.

### Capability groups

- **Your risk framework**: scales, impact dimensions, matrix bands and taxonomy set to your organisation.
- **Register and appetite**: enterprise risks linked to objectives and pillars, risk statements, appetite and accepted
  risks with their history.
- **Key risk indicators**: KRIs with history and thresholds.
- **Assessments**: questionnaire based risk assessments and a risk library.
- **Contributing factors and treatments**: what drives each risk and what is being done about it.
- **Regulatory obligations**: obligations tracked as risks (fed by Sentinel breaches, for example).
- **Scenario Studio**: compare scenarios with the baseline and capture a board pack.
- **Horizon scanning**: when web search is set up, scan for emerging risks from a list of trusted sources, with cited
  sources checked before use.
- **Emerging risks**: a watch list before a risk enters the register.
- **Rating guide**: a shared guide so every unit rates risk the same way.
- **Score history and workflow**: how each risk's rating moved and who approved it.
- **Reports and risk assistant**: board reports and an in-module chat.
- **Cross-module risk register**: one register that brings risks raised in any module together.

Works with: every other module; the predictive risk view draws on all of them.

## 7. Operations risk: ORM (`#operations-risk`)

Promise: **"Capture what happened, learn why, and stop it repeating."**

### Capability groups

- **Events**: loss and near miss events from templates, with a workflow history.
- **Risk and control self assessment**: risks, controls and actions per assessment.
- **Key risk indicators**: KRIs with history.
- **AI management assessments**: operational assessment of AI uses, linked to AI Governance.
- **AI controls**: controls for AI uses, suggested for review and linked to the assessment.
- **Reports and operations assistant**: reports and an in-module chat.

Works with: Sentinel, BCM, ERM, AI Governance.

## 8. AI Governance (`#ai-governance`), the seventh module

Promise: **"Know every AI use, decide on it with evidence, and keep watching it."**

### Showcase: the life of one AI use

A horizontal journey with one panel per stage, using the workspace screenshot:

1. **Register**: a specialist describes the AI use in a guided intake, saved as a draft until submitted.
2. **Review and tier**: a reviewer accepts it into the inventory; the tier follows the answers, and a reviewer can adopt
   a different tier with a reason.
3. **Assess**: AI impact assessments, linked privacy and operational assessments, and a checklist that says what is
   left before a decision.
4. **Decide**: someone other than the person who asked approves, approves with conditions, returns or rejects, signed
   on a frozen brief of what they were shown.
5. **Watch**: monitoring and evaluations, human oversight arrangements reviewed by a second person, and regulatory
   changes checked against affected uses.
6. **Prove**: review packs for auditors and a full activity history.

Source: `modules/ai_governance/` (`service.py`, `assessments.py`, `checklist.py`, `decisions.py`, `monitoring.py`,
`evaluations.py`, `oversight.py`, `regulation.py`, `review_packs.py`, `literacy.py`, `imports.py`,
`platform_features.py`).

### Capability groups

- **Inventory and intake**: AI systems register, guided intake, bulk import from a form export.
- **Assessment**: AI impact assessments with configurable dimensions; guidance on which assessments apply.
- **Decisions**: separation of duties, conditions with expiry, re-review when a covered fact changes.
- **Monitoring**: evaluations, oversight, regulatory change impact.
- **People**: AI literacy courses for specialists with renewal and completion reporting.
- **Assurance**: review packs; a register of the platform's own AI features and how they are used.
- Note for copy: say "for your governance and risk specialists"; AI Governance is switched on per organisation.

Works with: Sentinel, ORM, ARIA, GRID, Evidence Vault.

## 9. Evidence Vault (`#evidence`)

Promise: **"Store the proof once. Use it wherever it counts."**

Showcase: the landing page's "one file, many uses" study, extended with an expiry timeline and a campaign view.

- **Library**: one library across modules, with owners, periods, expiry and review dates.
- **Linking**: link one item to controls, audits, incidents and risks; see where it is used before you change it.
- **Renewal**: reminders before expiry; controls are rescored when evidence is removed or expires.
- **Evidence campaigns**: ask owners for evidence, track the requests, and review what comes back.
- **Find**: search across evidence, with suggested links limited to what you are allowed to see.
- **Integrity**: file fingerprints and duplicate detection within your organisation.
- **Office to PDF**: open Office files as PDF for review.

## 10. Work, notifications and reporting (`#work`)

Promise: **"Everyone knows what is theirs, and leaders get the picture."**

- **Command Centre**: a home page each person can arrange, with the cards their role needs first.
- **My Work and team view**: everything assigned to you across modules; managers see their team.
- **Tasks, calendar and workflows**: task board, calendar reminders, workflows with service levels.
- **Connected records and search**: related items across modules and one search bar.
- **Notifications**: in-app alerts; email with quiet hours and daily or weekly summaries; urgent alerts bypass quiet
  hours for the people named to receive them. Copy note: email needs a sender to be configured.
- **Reports**: build reports, freeze a snapshot, have it signed off by an independent reviewer, share it with a named,
  expiring link; saved views and analytics.
- **Readiness**: findings that show what is incomplete before an audit or a review.
- **Timeline and metrics**: an organisation timeline of key events and a metrics view across modules.
- **Platform guide**: an in-app guide that answers "how do I" questions about ThemisIQ.

## 10a. Connected governance (`#connected`)

Promise: **"Change one thing, and everything connected to it knows."**

This is the layer behind "Connected, not bolted together" in section 1, and a strong differentiator to show.

- **The connected view of a record**: open a system, process, data asset, vendor or control and see everything
  connected to it, grouped by module, with its proof and any open change signals. Only records you are allowed to open
  are shown. Source: `modules/governance/entity360.py`.
- **Change signals**: when a record others depend on changes (an application's criticality or provider, a process's
  recovery targets, a vendor's risk level, a control's status, a finding's severity, a replaced file), the owners of
  connected records are asked to look again, and confirm or dismiss with a reason. Source:
  `modules/governance/change_signals.py`.
- **Control effectiveness**: each control gets an effectiveness score from several factors, recalculated nightly.
  Source: `modules/governance/effectiveness.py`, `scheduler.py`.
- **Related items**: link records across modules; a link never gives access to a record you could not already open.
  Source: `modules/governance/relationships.py`.
- **Business entities**: applications, processes and data assets as shared records every module can refer to.

Showcase: a small interactive map. Select a vendor; its links light up into a BCM process, a Sentinel processing
activity, a GRID vendor assessment and an ERM risk; change the vendor's risk level and the connected owners get a
signal. Labelled illustrative.

## 11. Integration and administration (`#platform`)

- **API**: REST API with keys and read or write scopes.
- **Webhooks and connectors**: outbound webhooks; Slack and Teams notifications.
- **Import and export**: bulk import and export for core records; user import from a spreadsheet.
- **Organisation and units**: business units, controlled transfers between units, people directory.
- **Roles**: specialist roles per discipline, licences per module.
- **Audit log**: who did what, kept per organisation.
- **Vendor directory**: one directory of suppliers shared by audit, privacy and continuity, with each module's view
  of the same vendor.
- **Framework administration**: manage the framework catalogue available to your organisation.
- **Email and AI settings**: configure the mail sender, connectors and your organisation's AI policy in one place.

## 12. Security and trust (`#security`), held

Drafted, not published until the owner confirms the security work is done. Draft claims, all true today:

- Data kept separate for each organisation.
- Access by role and by business unit.
- Two-step sign in available to every user. (Policy enforced MFA only after findings H2 and H3 are fixed.)
- Every assistant governed by your organisation's AI policy: providers, kinds of data, features and a monthly budget.
- An audit log of actions.

## 13. Frameworks and jurisdictions (`#frameworks`)

- A table of the standards in the catalogue, by family (information security, privacy, quality, environment, health and
  safety, continuity, AI, service management, industry), with "what ThemisIQ does with it": controls, IMS mapping,
  audit checklists. No total count.
- A jurisdictions block for Sentinel naming every supported jurisdiction by region, with the line "Rules are drafted
  by your privacy specialists and approved by a different DPO before they set a deadline." No count.

| Region | Jurisdictions (law named on the card) |
| --- | --- |
| Africa | Zimbabwe (Cyber and Data Protection Act), South Africa (POPIA), Kenya (Data Protection Act 2019), Nigeria (Data Protection Act 2023), Ghana (Data Protection Act 2012) |
| Europe | European Union (GDPR), United Kingdom (UK GDPR) |
| Middle East | United Arab Emirates (PDPL 2021), Saudi Arabia (PDPL), Qatar (PDPPL 2016), Bahrain (PDPL 2018) |
| Americas | California (CCPA and CPRA), Brazil (LGPD), Canada (PIPEDA), Canada (Consumer Privacy Protection Act, proposed) |
| Asia-Pacific | India (DPDP Act 2023), Singapore (PDPA), Australia (Privacy Act 1988), New Zealand (Privacy Act 2020), Japan (APPI), South Korea (PIPA) |

Source: `modules/sentinel/jurisdictions.py` on `master`. Copy rule: Canada's Consumer Privacy Protection Act is a bill, so
the page calls it proposed and the legal reviewer confirms its status (and whether a later bill replaced it) before
launch.

## 14. Demo request (`#contact`)

Reuse the landing page form and copy: "Tell us what your team needs to connect."

## What the landing page links to

| Landing element | Goes to |
| --- | --- |
| New "What's inside" tiles | Sections 2 to 11, one tile each |
| Seventh module tab: AI Governance | `#ai-governance` |
| Privacy jurisdiction study, "Explore the example" | `#privacy` |
| Framework ribbon | `#frameworks` |
| Nav "Features" | page top |

## Assets needed

Screenshots (light theme, same frame as today): AI Governance overview and an AI use workspace; ARIA IMS Control
Mapping; a GRID integrated audit checklist with IMS badges; Sentinel breach with obligations; BCM incident with
escalation; Evidence Vault library; My Work; a signed off report. All from a demo organisation with invented data.

## How ARIA connects to AIIAs, DPIAs and continuity plans (for the Connected governance study)

| Record | Lives in | Automatic connection to ARIA | Manual connection | Not connected today |
| --- | --- | --- | --- | --- |
| DPIA | Sentinel | When a DPIA is completed, ARIA controls whose name or description matches its data categories are linked to it as "mitigates" (`core/event_handlers.py`, `dpia_links_to_aria_controls`). A high risk DPIA also opens a risk entry and a task. | Related Items, both ways | ARIA does not draft DPIAs; Sentinel does |
| AIIA | AI Governance (stored in the Sentinel tables) | Through the AI use: its checklist shows the AIIA, DPIA, RoPA, AI management assessment and the **ARIA policy** linked to that use, each with its state and a button to the owning module (`modules/ai_governance/guidance.py`). The AIIA itself links to the AI system, a DPIA and a RoPA. AI controls map to canonical controls and show the proof held for them (`modules/ai_governance/controls.py`). | Related Items, both ways | No AI draft for an AIIA |
| Continuity plan (BCP) | BCM | When a plan is activated, a task asks the compliance team in ARIA to check that the related controls still work (`plan_activation_triggers_control_review`). Approval and stand down create follow up tasks. | Related Items, both ways; BCM compliance controls can be linked to ARIA controls the same way | ARIA does not draft plans; BCM does |
| Policy (ARIA) | ARIA | Publishing files it in the Evidence Vault and on matching GRID controls; a policy falling out of Approved opens a re-review task | Related Items | |

## Coverage check: every module page has a home on `/features`

Built from the page templates and single page app views on `master`. Any new page must be added here.

| Module | Pages and views | Section |
| --- | --- | --- |
| ARIA | dashboard, frameworks, framework detail, IMS mapping, documents, policy workbench, assisted generator, Ask ARIA, templates, risks, audit log | 2 |
| GRID | dashboard, audits, audit detail, controls, findings, evidence, frameworks, vendors, reports, chat, shared audit for externals | 3 |
| Sentinel | dashboard, RoPA, data flows, DPIA, LIA, breaches, DSR, consent, notices, controllers, legal bases, transfers, retention, security, vendors, policies, training, jurisdictions and cards, reports, chat | 4 |
| BCM | dashboard, BIA, plans, incidents, exercises, scenarios, risks, dependencies, training, documents, compliance, vendors, comms, contacts, reports, chat | 5 |
| ERM | register, appetite, objectives, statements, indicators, assessments, library, obligations, external (horizon scan), rating guide, framework admin, reports, chat, Scenario Studio | 6 |
| ORM | events, indicators, assessment (RCSA), AI controls, AIMS, reports, chat | 7 |
| AI Governance | overview, inventory, intake, requests, review, workspace, assessments, decisions, monitoring, regulatory, packs, literacy, import, platform features | 8 |
| Evidence | Evidence Vault library, campaigns | 9 |
| Platform | Command Centre, My Work, task board, calendar, workflows, reports, analytics, metrics, timeline, readiness, projects, risk register, connected records, people directory, vendor directory, profile and MFA | 10, 10a, 11 |
| Administration | users, security, AI policy, API keys, webhooks, connectors, email, frameworks, logs | 11, 12 |
| Operator only | diagnostics, super admin | Not listed: internal tools |

## Open questions

1. Resolved: name all jurisdictions, gated on approved cards at launch (owner decision, 2026-10-20).
2. Resolved: a compact static predictive risk panel in the ERM section, linking to the landing page's interactive
   version (recommendation adopted, see the plan).
3. Resolved: industry framing stays general (owner decision, 2026-10-20). No sector names in headings or examples.
