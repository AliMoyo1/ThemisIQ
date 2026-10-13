# 02. AI Governance feature journeys

**Status:** Proposed feature behavior. The [domain contract](01-domain-and-integrations.md) defines shared ownership and permissions; existing linked feature briefs retain their specialist detail. A feature is complete only when the stated user journey and guardrails work with the source module, including loading, denied, stale, and empty states.

## 1. Declare an AI use and discover embedded AI

**User experience.** A staff member chooses **Register an AI use** from AI Governance, Command Centre, or a permitted application record. The first screen asks only purpose, owner/BU, provider or internal build, intended users, data categories, and planned use. A draft can be resumed. Conditional questions ask about sensitive data, effects on people, autonomy, jurisdictions, external access, model changes, and target launch only when relevant. Before submission, show possible existing applications and the reason they matched. A reviewer either links to one existing application, promotes a new one, or returns the intake with named gaps.

**Connections and data sources.** Governance `applications`, business processes, and data assets provide identity; canonical vendors provide the provider; Sentinel RoPA/data flows provide processing details where permitted. Vendor onboarding and business-process registration get a small **Uses AI or embedded AI?** field with `yes/no/unknown`, a description and source of the assertion. `yes` or `unknown` proposes an intake task; it does not automatically create another application or assert risk. The intake request stores only unconfirmed facts until review. The [VerifyWise intake brief](../verifywise-features/01-ai-intake-inventory.md) owns the build slices.

**Guardrails and release check.** Duplicate suggestions reveal only records the actor may see; a reviewer can match hidden existing records through an authorized queue without disclosing them to the submitter. No staff write access is widened to all applications. An intake rerun or retry cannot create a second system. A provisional tier shows each rule and unanswered field; a qualified reviewer records the adopted tier and rationale. Do not call something legally high-risk merely because a model suggested it. Pilot users can submit, return, resume and find their next action without knowing the module architecture.

## 2. AI Systems inventory and connected workspace

**User experience.** The AI Systems list supports owner, BU, provider, use type, risk tier, approval state, review due, and `needs action` filters, with saved views and pagination. One system page has Overview, Assessments, Risks & Controls, Data & Vendors, Evidence, Decisions, Monitoring, and Activity. A compact path shows completed, missing, inapplicable and stale prerequisites. Every item opens the owning record and preserves a return path. A related-items list is primary; a bounded graph is optional.

**Connections and data sources.** Governance application/profile is the spine. Permission-aware adapters from Sentinel, ORM, ERM, ARIA, GRID, Vault, BCM and workflow supply status cards. Direct FKs, where meaningful, precede generic links; the shared relationship service supplies typed many-to-many edges. [VerifyWise relationship explorer](../verifywise-features/02-relationship-explorer.md) specifies list and graph behavior.

**Guardrails and release check.** The list, badges, graph, search, exports and board aggregates apply the same actor/org/BU/module checks. A user who cannot open a linked record receives no title, count, ID, snippet or existence hint. Unconfirmed and dangling links are labeled for authorized reviewers. Do not calculate a single opaque `AI compliance %`; show separate assessment, control, tested proof and decision states with denominators. At 500 systems and 5,000 proof items, the initial view stays bounded and navigable.

**Model and data lineage expansion.** If the pilot uses several models or provider versions in one application, add component/version rows linked to the application. Record purpose, owner, provider, release identifier, deployment dates, allowed data categories, known limitations and source of each assertion. Link existing Governance data assets and Sentinel data flows; store whether data is for training, validation, inference or retrieval only after the customer confirms the distinction. A vendor claim or uploaded model card remains owner-supplied until reviewed. Changing a current component creates a new version and a re-review signal rather than overwriting the version an approval covered.

## 3. Conditional assessment and obligation routing

**User experience.** After intake, a rules engine proposes a checklist such as AIIA, DPIA, RoPA update, vendor review, AIMS risk assessment, ARIA policy/control, security review, and evaluation. Each row says **why**, who owns it, what information will prefill, and what blocks a decision. A reviewer may mark a step not applicable with an explicit reason and date. Changes to purpose, data, autonomy, provider or jurisdiction recalculate candidate steps while preserving the earlier review snapshot.

**Connections and data sources.** The AIIA is written in AI Governance (moved from Sentinel, see [06](06-aiia-in-ai-governance.md)); Sentinel DPIA/RoPA remain the privacy assessment writers; ORM AIMS and ERM retain their risk methods; vendor review and ARIA own their records. The existing RoPA-to-DPIA mapping in [PLAN-19](../PLAN-19-ropa-dpia-integration.md) is reused. Organization policy and versioned ISO/IEC 42001, NIST AI RMF or other authorized framework mappings can propose controls. The Regulatory Inbox supplies reviewed jurisdiction changes. The checklist stores source record IDs/versions, rule version, applicable state and reviewer, not a copy of specialist answers.

**Guardrails and release check.** Rules are deterministic and explainable; external web text and AI cannot set legal applicability. Missing data results in `needs review`, not a low-risk default. AIIA snapshots the AI profile facts it actually assessed. A user can open and complete each required specialist form from the checklist and return to the same system. No automatic approval follows from a completed questionnaire or an attached file.

## 4. AI controls, policies, evidence and assurance quality

**User experience.** The Controls & Evidence view shows each applicable control, who owns implementation, last test, current accepted proof, gaps and next review. **Attach existing proof** comes before upload. AI policy, procedure, notice and record templates can be started from selected system facts, then edited and submitted through ARIA's named policy approval. The quality inspector flags unsupported claims, expired proof, unmapped controls, stale evaluation, and an overdue system review with one direct fix route.

**Connections and data sources.** ORM AI control catalogue maps to canonical controls; ARIA owns policy versions and framework mappings; GRID owns audit and findings; Vault owns evidence item/version, verification, expiry and requests. [CISO assurance inspector](../ciso-assistant-features/01-assurance-quality-inspector.md) derives issues without changing source status. Existing [ARIA policy authoring](../PLAN-35-aria-policy-authoring-flow.md) owns drafting, branded preview and publication. [VerifyWise evidence and auditor sharing](../verifywise-features/06-auditor-sharing-trust.md) governs later packs.

**Guardrails and release check.** A control map is a candidate until reviewed. A file is not proof of effectiveness by itself. Show `applicable`, `implemented`, `tested`, `current evidence`, and `reviewer accepted` separately. AI may recommend proof or draft a policy section with cited facts, but cannot sign off a control or publish. Every quality warning cites its rule, source version and permitted deep link; false positives have an audited dismissal or exception that does not change the underlying claim.

**Original template set.** Offer editable starting structures for AI acceptable use, system disclosure/notice, human oversight and escalation, vendor AI due diligence, evaluation plan, model/service change record, AI incident response, and decision record. ARIA owns policy/procedure/notice versions and approvals; BCM owns the incident playbook where it is a continuity artifact; the system workspace only links them. A template is guidance until adopted and reviewed by the organization. Do not copy competitor template text or licensed framework language.

## 5. Versioned decisions and formal risk acceptance

**User experience.** The owner submits a decision brief showing system purpose, version, affected data, current risk, required assessments, missing steps, selected evidence versions, and proposed conditions. Reviewers approve, approve with conditions, return, or reject. The page shows the latest decision and its expiry, plus prior decisions. A material change opens **Needs re-review** with a diff, while the prior snapshot remains intact. A high residual ERM risk can separately request time-limited management acceptance.

**Connections and data sources.** The existing workflow engine routes decision stages; My Work and Command Centre show the same canonical action ID. Sentinel, ORM, ERM, vendor, ARIA, GRID and Vault provide the referenced prerequisites and versions. [VerifyWise approval gates](../verifywise-features/03-approval-gates.md) owns the AI-use decision contract. [CISO formal risk acceptance](../ciso-assistant-features/04-risk-acceptance-and-exceptions.md) owns ERM exposure acceptance, which is not equivalent to approving an AI system.

**Guardrails and release check.** A permitted human signs a decision on a frozen source manifest. Separation of duties, concurrent edits, conditions, expiry, and policy-specific overrides are validated server-side. Approval cannot succeed with mandatory unresolved steps unless an authorized, explicit override is allowed and recorded. Reusing the prior approval after a material change is prohibited. A model suggestion or task completion cannot sign, accept risk or waive a legal obligation.

## 6. Evaluations and continuous monitoring

**User experience.** The Monitoring tab shows last evaluation, model/service version, test profile, selected results, incidents, control failures, evidence expiry and next review. Owners can compare runs and see failure examples with minimal retained content. A failed evaluation proposes a finding or review action; a reviewer decides its consequence. Model/provider/data/purpose changes and serious incidents trigger an understandable re-review notice.

**Connections and data sources.** [VerifyWise evaluations](../verifywise-features/04-evaluations-monitoring.md) starts with Ask ARIA's own retrieval and citation behavior, then an opt-in customer use pilot. Vault holds reviewed artifacts; ORM/ERM hold risks and controls; BCM holds relevant incidents and continuity work; Sentinel handles personal-data incidents. Source events update the workspace and My Work through the dependable event path, not by inventing a second monitoring truth.

**Guardrails and release check.** Store test-set, rubric, model and run versions, thresholds, evaluator type, retained-content choice, cost and provenance. Distinguish deterministic checks from model-graded judgment. No run, cancelled run, or stale telemetry must be displayed as a pass. Do not collect customer prompts, responses or live traffic without an approved source and retention contract. Before offering customer evaluations, prove tenant separation, provider policy, budget, timeouts and deletion behavior. Evaluation success is evidence for review, not certification or legal compliance.

**Operational oversight.** The system profile records where a human can review, override or stop consequential output and who owns that action. An AI-related failure, harmful output, unexplained decision or user challenge opens a scoped event in the appropriate existing owner: ORM/ERM for operational risk, Sentinel for personal-data breach or rights handling, and BCM for continuity impact. Link the event to the AI use and exact component version. A reported issue is triaged by a person, with severity, affected population, decision, remediation and feedback trail. Performance, fairness, drift and intervention rates appear only when a named, authorized telemetry source and measurement method exist; otherwise display `not measured`.

For confirmed EU use cases, the [EU AI Act extension](04-eu-ai-act-and-operational-assurance.md) turns the oversight arrangement into a versioned record and adds role-specific post-market planning, incident clocks and externally filed report evidence. This remains connected to existing monitoring and incident owners.

## 7. Regulatory and emerging-risk impact

**User experience.** A reviewer maintains a watchlist by jurisdiction, topic and AI use. A sourced change enters the existing Review Impact queue with issuer, publication and effective dates, status as proposal/adopted/guidance, summary, confidence and last check. The system proposes affected applications, controls, vendors and assessments; the reviewer confirms or rejects each link. Accepted impact creates one owned action with due date.

**Connections and data sources.** Extend Regulatory Inbox and ERM External Context as specified by [VerifyWise regulatory impact](../verifywise-features/05-regulatory-impact.md). Sentinel supplies reviewed jurisdiction context. AI Governance consumes confirmed impacts and shows affected AI systems. ARIA/GRID/ORM/ERM receive confirmed tasks in their owning workflows. External research sources require an approved source registry and provenance; copied law text and protected content require rights review.

**Guardrails and release check.** An external page is untrusted data. AI summarizes with citations but cannot adopt an obligation, change a control, or issue a legal conclusion. An unavailable source is stale, and an unreviewed candidate never appears as a confirmed requirement. Dismissal records a reason; deduplication prevents repeated alerts for the same source version. Wrong-BU users see no affected-record names or counts.

## 8. Role-based AI literacy

**User experience.** An administrator selects courses and acknowledgments for roles, business units or specific AI uses. Each staff member sees one assignment in My Work, completion requirements, a due date and renewal. Reviewers see coverage by role and system, with the number assigned and actually completed. An AI-use approval may require a named role to have current training if organization policy says so.

**Connections and data sources.** [VerifyWise literacy](../verifywise-features/07-ai-literacy-training.md) reconciles BCM training modules/attestations and Sentinel privacy training before any shared service or migration. User and role data supplies targeting; Vault can hold approved course/attestation evidence; workflow/My Work supplies assignments. Existing history stays in the owning module.

**Guardrails and release check.** Do not turn a scheduled course into a completed individual attestation. Training version, learner, score/acknowledgment, date and renewal are explicit. A training status does not approve the AI use or certify the organization. Reports and reminders remain BU-scoped and do not reveal individual outcomes to unauthorized viewers.

## 9. Contextual AI assistance

**User experience.** The workspace and source forms offer precise actions: **Find proof**, **Explain this status**, **Prepare AIIA/DPIA section**, **Draft policy or procedure**, and **Suggest related records**. Results separate source-backed facts from gaps and suggestions. Users can review, edit, discard, or save a draft in the owning module. Manual search and forms remain available when AI is disabled or fails.

**Connections and data sources.** [VerifyWise contextual advisor](../verifywise-features/08-contextual-ai-advisor.md) uses PLAN-37's one AI-service wrapper and permission-checked retrieval/citation service. Only selected, authorized versions of ARIA, GRID, Sentinel, BCM, ERM, ORM, Vault and Governance records enter the prompt. ARIA owns published policies; Sentinel owns saved AIIA/DPIA text; BCM owns BCPs. The Vault's own evidence-finding design remains the evidence search owner.

**Guardrails and release check.** Enforce provider/data-category policies before any call and check source permission again when a citation is shown. No cross-tenant retrieval, invisible source title, uncited factual claim, secret or raw personal-data dump. Prompt-injected document or web text is never an instruction. Output cannot approve, publish, mark compliant, alter a risk score or accept a link. Capture model/version, cited record versions, actor, approval of a saved draft, usage and cost. Evaluate factuality, no-match, citation resolution, latency, prompt injection and unauthorized-result leakage before each new source adapter.

## 10. Auditor packs, trust and reporting

**User experience.** A reviewer selects a system and time/version boundary to assemble an AI governance pack: inventory profile, approval and conditions, AIIA/DPIA, risk/control basis, evaluation results, training where relevant, current proof, known gaps and unresolved exceptions. They preview a manifest, recipient, redactions, expiry and download rights before issuing a named share. Command Centre offers aggregate views such as systems without owner, reviews due, high-risk systems without mitigation, and approved systems changed since decision. Each metric drills down to permitted records and explains its denominator.

**Connections and data sources.** Extend [VerifyWise auditor sharing](../verifywise-features/06-auditor-sharing-trust.md) and GRID's existing authenticated share flow. The Vault supplies exact file versions; the workflow/decision service supplies signatures and snapshots; source adapters supply current versus frozen state. Public trust publication, if later justified, uses a separate ARIA-approved, public-safe content workflow.

**Guardrails and release check.** Per-item authorization is checked at pack creation and every view/download. A frozen manifest is reproducible, while lost permission, revocation or expiry denies access. No anonymous evidence links in the pilot. Never render `certified`, a third-party seal, or a misleading readiness percentage without the corresponding independent attestation and approved claim. Unknown or missing data is visible as unknown, not counted compliant.

## 11. Shadow AI and runtime controls, discovery only

**User experience.** Only after an authorized connector exists, an owner may review an opt-in feed of unregistered AI tools and promote one into the normal intake path. Show source coverage, freshness, uncertainty and a correction action. A gateway or agent-tool control is a later product decision, not a toggle on the dashboard.

**Connections and data sources.** [VerifyWise shadow-AI feasibility](../verifywise-features/09-shadow-ai-gateway.md) requires a named customer source such as an approved proxy/SIEM/provider feed with documented fields, retention, residency and owner. The feed proposes links to canonical applications; it never becomes a new application or employee record by itself.

**Guardrails and release check.** No network scraping, endpoint agent, prompt capture or production gateway on the existing app service by default. Accept only consented data with tenant mapping and deletion rules. Do not claim complete detection from a partial source. A proxy needs separate isolation, keys, fail behavior, throughput, budget and rollback approval before design moves beyond discovery.

## 12. Govern ThemisIQ's own AI features

Use the same concepts to record Ask ARIA and other first-party AI features in a **platform-operator** inventory: feature owner, version/provider, allowed data classes, evaluation set, known limitations, incident path, deployment decision and review due. This is an internal oversight record, not a global customer inventory. The per-organization AI-service policy still governs each customer call; no customer prompt or evidence is copied into the platform inventory. Begin with Ask ARIA evaluation and provider policy because its retrieval, citation and data-handling behavior can be measured directly.
