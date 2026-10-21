# 03. Specialist module journeys and connections

**Status:** Proposed design. Read with the [programme index](README.md), [AI Governance workbench](01-ai-governance-specialist-workspace.md), [Evidence Vault plan](02-evidence-vault-and-assurance.md), and [delivery gates](05-delivery-and-acceptance.md). The source observations below describe the reviewed repository snapshot, not a production audit.

## 1. One connected case, distinct owners

Consider a customer service AI assistant. Governance owns its application and business process identity. AI Governance owns its use profile and approval. Sentinel owns its data processing and privacy assessments. ARIA owns policies and controls. GRID owns an audit and its findings. BCM owns service continuity. ORM owns an outage event and controls. ERM owns enterprise exposure and appetite. The Vault owns artifact versions. Each record points to the other records through authorized, typed relationships and preserves its own history. A specialist opens one case view and follows the links rather than maintaining eight copies of the same vendor, owner or policy.

The shared relationship contract needs source kind and ID, target kind and ID, relationship meaning, creator, timestamp, provenance and lifecycle. A relationship is navigable only when the viewer may read both ends. Counts and AI context obey the same rule. An event or link does not silently change the target module's status. Its owner accepts or rejects the proposed effect.

| Shared fact or event | Owning source | Consumers and expected reaction |
| --- | --- | --- |
| Application, process, asset or vendor changes | Governance / canonical vendor service | AI Governance, Sentinel, BCM, ERM and GRID see a material change signal; each decides whether reassessment is needed. |
| New or changed AI use | AI Governance | Sentinel receives a candidate processing or DPIA review; ARIA and GRID receive applicable control/review work; ERM receives an exposure signal. |
| Control, policy or requirement changes | ARIA / Governance | GRID, AI Governance and Vault flag potentially stale mapping or proof; existing approvals retain their historical basis. |
| Audit finding, rejected proof or overdue action | GRID | ERM and source module receive an attributed signal; no automatic risk acceptance or case closure. |
| Breach, DSR deadline or privacy assessment change | Sentinel | Relevant AI use, process, ERM and BCM case surfaces show source and deadline; legal determination stays with privacy specialists. |
| Continuity gap or failed exercise | BCM | ERM and affected AI/system owner receive source-backed exposure; completed exercise history remains intact. |
| Operational event or deteriorating KRI | ORM | ERM, BCM and affected AI use show the change; any predictive score explains the input. |
| Risk treatment or accepted exception | ERM | Source control or case shows owner, validity period, conditions and next review; expired acceptance is not a standing approval. |

## 2. Governance and canonical vendor foundation

**Current source:** Governance already contains application, process and asset records, relationships and a shared canonical vendor path. My Work and related items exist. The proposed work is a usable entity view and reliable source-change signals, not a new master-data store.

**Journey:** A specialist searches for a system, opens a 360-degree record and sees its process, data assets, vendor, AI uses, policies, controls, risks, privacy records, audits, incidents, BCM dependencies and current proof. The header shows record owner, business unit, source, last confirmed date and any disputed relationship. A change to a vendor or critical process creates a review candidate for affected modules with the changed fields and prior value. The source owner confirms or dismisses that candidate.

**Contract:** Use stable canonical IDs and typed, authorized links. Resolve duplicate vendor names through the existing canonical vendor service; retain historical aliases and references before merging. Never delete or reassign an in-use vendor because labels look similar. Business-unit ownership and organization-wide records must remain explicit. The entity view can summarize downstream status only from permitted source records with a timestamp and definition.

**Acceptance:** One canonical vendor can be found from its AI use, RoPA, BIA, risk and audit without duplicate creation. A restricted entity's title, count and existence do not leak through links, dashboard cards, search or exports. A vendor merge preserves all source references and historic reports.

## 3. ARIA: frameworks, policies and control assurance

**Current source:** ARIA holds framework/control and policy workflows and contributes to connected compliance. The reviewed UI has a Generate Report path that signals success after a timeout without a completed report. This must be corrected before presenting that action as functional.

**Journey:** A control owner opens a requirement, sees applicability, canonical-control mapping, policy version, implementation owner, proof requests, audit results, exceptions and affected AI uses. Changes to a policy trigger an explicit review of linked control implementation and AI guidance. A specialist can reuse a previous answer or proof across mapped frameworks only after checking period, scope and reviewer outcome. A policy generated with AI is a draft requiring a named editor and approver; it is not deployed control evidence.

**Contract:** ARIA owns requirement and policy text and version. Governance owns a canonical control identity where shared controls are used. The Vault owns file versions. GRID owns audit acceptance. A framework library import follows the existing [framework import plan](../ciso-assistant-features/05-framework-library-import.md): provenance, edition, license and mapping review. Add a source-backed report job or remove the nonfunctional button until one exists.

**Acceptance:** A requirement view shows which specific version of policy and proof was considered, and a report action returns a real job and output or an explicit error. Control reuse does not turn an unaudited requirement green. Historic audits retain their original framework edition.

## 4. GRID: audit and assessment review desk

**Current source:** GRID owns audits, questions, findings and module-specific evidence rows/files, and it mirrors some files into the Vault. Prior plans cover assurance quality, answer reuse and respondent assignments.

**Journey:** An audit lead starts from applicable framework/controls and sees unanswered questions, overdue respondents, current proof, rejected proof, open findings and sign-off readiness. A respondent supplies an answer or points to an existing Vault artifact. The reviewer records acceptance or return for that audit and evidence period. Findings create owned corrective work and a risk signal where relevant. A closed assessment freezes the questions, answers, proof versions, reviewer decisions and source scope used for the conclusion.

**Contract:** GRID retains audit-specific opinion, answer and finding history. A Vault artifact family is the canonical file identity, with a migration/adapter for `grid_evidence_files`; do not drop existing GRID records or their audit trail. Reused answers declare their source assessment, controls, changed assumptions and reviewer. The respondent-assignment and external questionnaire plans remain separate optional entry methods, not a second audit lifecycle.

**Acceptance:** An accepted proof version in one audit is not silently accepted in another. A new Vault version opens a review impact task without rewriting the frozen audit. Findings appear once in My Work and link to the affected control, risk and artifact.

## 5. BCM: resilience connected to operations and AI

**Current source:** BCM has BIA, plans, exercises, incidents and its own evidence/document surfaces. In the reviewed code, dashboard API failure can lead to example data, and some report actions use types not registered by the shared report engine. Both are truth defects.

**Journey:** A continuity specialist opens a critical process and sees dependent applications, AI uses, vendors, recovery targets, latest BIA, approved plan, last exercise, incidents and current proof. The work view prioritizes untested plans, overdue exercises, material dependency changes and recovery assumptions without current evidence. After an exercise, the specialist records actual recovery against target and routes a failed result to ERM/ORM with a source link and owner. The board view shows tested coverage and gaps with a clear denominator.

**Contract:** BCM owns BIA, exercise and plan lifecycle. Governance owns process/application/vendor identity. Vault holds file versions; BCM accepts sufficiency for its own claims. ERM consumes risk signals but owns appetite and treatment. Replace example fallback values with unavailable/partial states; register and implement BCM report types in the shared report engine or hide the actions.

**Acceptance:** A failed BCM source cannot show invented exercises or favorable coverage. A changed critical vendor identifies impacted BIAs and plans. The plan, exercise and incident report buttons produce real scoped outputs or a visible unavailable state.

## 6. Sentinel: privacy operations by jurisdiction

**Current source:** Sentinel has privacy records, assessments, breaches, DSRs and jurisdiction workflows. The reviewed dashboard has sample-data fallback and at least two hardcoded summary figures. Legal rule content must be reviewed before a live decision relies on it.

**Journey:** A privacy specialist starts with due decisions: breach clocks, DSR deadlines, DPIA review, RoPA changes, processor/vendor issues and AI uses that process personal data. A processing record links to its process, system, vendor, jurisdiction and AI use. For a suspected breach, the specialist records discovery, classification, applicable jurisdictions, notice decisions, evidence and deadline computation. Each jurisdiction card states source, rule version, trigger, timezone and the person who approved the interpretation. A countdown is a deterministic calculation from accepted trigger facts; AI may summarize the case but cannot choose the trigger or legal obligation.

**Contract:** Sentinel owns RoPA, DPIA, breach and DSR records and legal applicability decision. AI Governance may propose an AIIA or privacy review link; it does not create a final DPIA conclusion. ARIA supplies mapped privacy controls, Vault supplies artifact versions, ERM receives source-backed exposure, and Governance supplies entity identity. Zimbabwe CDPA and other jurisdictions need maintained source texts, applicability tests, approval/version history and effective dates before appearing as authoritative operational rules.

**Acceptance:** No hardcoded or sample counts on a failed source. One breach can show multiple jurisdiction obligations with distinct clocks, owners and notice decisions. A missing trigger appears as unresolved, never as a running authoritative countdown. A system change identifies which RoPA and DPIA records require review without replacing their prior sign-off.

## 7. ERM: enterprise exposure and accountable acceptance

**Current source:** ERM already has risk register, appetite, indicators, external context, predictive risk intelligence and report paths. A separate [risk acceptance plan](../ciso-assistant-features/04-risk-acceptance-and-exceptions.md) covers governed exceptions.

**Journey:** The risk owner opens an exposure and sees events, controls, obligations, audits, privacy cases, continuity gaps, AI uses, external context and current treatment evidence. New signals appear in a triage inbox with severity, confidence, source, freshness and suggested link. A specialist confirms relevance and either updates an existing risk or opens a new one. A risk acceptance records decision maker, scope, reason, residual level, conditions, expiry and review, with separation of proposer and approver. Predictive insight shows factors, data gaps and trend alongside the underlying register. External web findings are advisory until a person verifies business relevance and source credibility.

**Contract:** ERM owns appetite, rating, treatment and acceptance; contributing modules own facts and incidents. Predictive output is a derived view with input versions and model/rule version. Never allow a generated narrative or probability score to approve an exception. Source scope must apply to CSV, dashboard, report and AI prompt. The system should distinguish no observed incidents from no telemetry.

**Acceptance:** A risk's score, treatment and predictive contribution can be traced to specific permitted records and their as-of time. An expired acceptance returns to action. A misleading or unavailable model signal cannot overwrite the human register.

## 8. ORM: events, controls and operational indicators

**Current source:** ORM has event, KRI and RCSA workflows and an operational dashboard. Its events and losses are separate from ERM risk decisions.

**Journey:** An operations-risk specialist records an event once, classifies affected process/system/AI use, confirms financial and customer impact, assigns root cause and corrective controls, and closes only after evidence and review. Repeated events and breached KRIs suggest reassessment of related RCSA/control and an ERM signal. The ORM dashboard prioritizes recurrence, overdue corrective work, KRI trends and loss patterns with clear measurement windows.

**Contract:** ORM owns event facts, KRI definitions, thresholds and RCSA. Governance supplies canonical process/application IDs. BCM receives continuity implications; Sentinel receives suspected privacy implications; ERM accepts exposure signals; GRID may test corrective-control operation; Vault holds supporting proof. Statistical or AI anomaly suggestions cite contributing events and baseline; they never fabricate missing incident history or change a KRI threshold.

**Acceptance:** An incident follows one event ID through closure, risk review and proof. Reopened findings do not silently reopen the event. Restricted events do not contribute visible counts or snippets for an unauthorized user.

## 9. Common module design and test contract

Every module home should show **Act now**, **Portfolio**, **Trends**, and **Coverage/quality** with definitions and drilldowns. Empty, unavailable and partial data are different states. Historical decisions and reviews remain stable. Source records carry organization and business-unit scope. Derived links, metrics, AI context, notifications and exports enforce the same scope. An action must have one canonical owner and close in its source module; My Work is its shared projection. The [platform plan](04-platform-truth-navigation-and-reports.md) defines reusable UI and reporting behavior; the [delivery plan](05-delivery-and-acceptance.md) sequences the underlying changes.
