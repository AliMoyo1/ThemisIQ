# 05. Delivery sequence and acceptance

**Status:** Proposed delivery plan, not an implementation log. Read with the [programme index](README.md), [AI Governance workbench](01-ai-governance-specialist-workspace.md), [Evidence Vault plan](02-evidence-vault-and-assurance.md), [module journeys](03-specialist-module-journeys.md), [platform contract](04-platform-truth-navigation-and-reports.md), the [AI Governance execution ledger](../ai-governance/05-execution-ledger.md), and [PLAN-37](../PLAN-37-connected-compliance-experience.md).

## 1. Delivery principles and decisions

Build vertical journeys through existing source modules. A release is useful only when a specialist can move from a visible problem to its source, act with the right permission, see the consequence and explain the result. Do not start by redesigning every dashboard in isolation. Existing G1 to G7 records, pilot organization, historical packs and audit events remain part of the system; the team must reconcile their actual deployed state before a migration.

### Decisions to record before schema or UI work

| Decision | Recommended default | Decision owner and effect |
| --- | --- | --- |
| AI Governance user group | Governance specialists are full users; external requesters use customer Forms export first | Product owner and customer governance lead approve the role model. |
| Initial request entry | Versioned Google/Microsoft Forms export through specialist preview/import | Customer administrator owns the external form; ThemisIQ owns the mapping contract. No direct Forms integration in first slice. |
| Future invitation form | Defer until import has real usage data and a separate security design | Security and product owner approve invitation expiry, verification, upload and abuse controls. |
| Literacy transition | Remove learner/course navigation from specialist workspace; retain history and APIs until consumer review | Product owner names separate staff learning project and decides if only completion signals return. |
| Evidence semantics | Publish linked, current and reviewer-accepted measures separately | Assurance owner approves target-specific acceptance rules. |
| Report audience and retention | Frozen scoped run for internal reports; recipient-bound packs for external sharing | Information owner approves classifications, expiry, deletion and revocation behavior. |
| Jurisdiction rules | Human-reviewed, versioned legal content before operational clocks or conclusions | Privacy/legal owner signs off sources, effective dates and jurisdiction applicability. |
| Risk acceptance | Human authority, expiry and conditions; no AI approval | Risk governance owner approves the delegated-authority matrix. |
| Temporary Gmail sender | Dedicated organization-controlled mailbox with scoped internal traffic; do not use current XOR-stored Admin credentials | Security and operations approve mailbox type, secret path, From identity, quota, monitoring and fallback. See [06](06-email-notifications-and-delivery.md). |

Record each decision with owner, date, affected schemas/routes, data migration need and open risks. Product copy must not label an unresolved decision as implemented.

## 2. Phase 0: reconcile baseline and specify contracts

**Objective:** Establish what is actually built, deployed and in use. The older planning files mix shipped and proposed milestones, so start with a source and tenant inventory rather than treating those labels as release evidence.

**Work:** Inventory current branch, production release, feature flags and tenant access; list existing AI Governance records, literacy completions, Vault versions/links, GRID and BCM file mirrors, report definitions and saved runs. Map the current requests/decisions/evaluations/oversight schema and APIs to the new journey. Inspect representative non-sensitive customer Forms exports before fixing CSV/XLSX parser rules. Define the shared record reference and relationship vocabulary, permission matrix, metric registry, evidence statuses and report snapshot format. Document each area's data classification and retention. Resolve product decisions above.

**Outputs:** A versioned baseline matrix (built, proposed, deferred), route/schema inventory, source-of-truth contract, metric definitions, import field guide and sample mapping, migration impact notes, access matrix and current-state screenshots. The baseline should be checked with the customer governance lead, privacy lead and technical owner.

**Gate:** No data is migrated or hidden until there is an identified reader, retention decision, rollback path and preservation check. No new AI use, Vault or report identifier is invented where a canonical one already exists.

Email delivery runs as a parallel workstream. Complete [E0 inventory](06-email-notifications-and-delivery.md) in this phase, including current sender configuration, role-specific alerts, sensitive content, volumes and the organizational owner of the temporary Gmail account. Do not enable real sending from the existing XOR settings path.

## 3. Phase 1: repair truthful data surfaces

**Objective:** Users can trust the current system while the new experience is built.

**Slice A, dashboards:** Remove BCM and Sentinel sample fallback values; source Sentinel RoPA denominator and coverage or show not measured; add unavailable/partial/stale states. Introduce a small shared response for source freshness and eligibility. Document and scope the current module counters. Each card drilldown must reconcile with the authorized source list.

**Slice B, reports:** Replace ARIA's timer success action with a real report path or remove it pending one. Register and implement BCM requested report types or disable those buttons. Freeze saved report run output and apply recipient authorization on read. Preserve earlier runs and identify which legacy runs were never frozen; label them as legacy/current recomputation rather than pretending they are snapshots.

**Slice C, Vault measures:** Label current metadata confidence accurately; define and implement linked/current/accepted coverage separately without breaking historical link data. Add source/denominator disclosures to charts that use these measures.

**Acceptance gate:** A failed source cannot render a sample value. A report button proves a persisted run and opens its output; a later data change does not alter a saved run. Counts, list rows and exports have matching scopes. Release notes call out any deliberate metric definition change.

In parallel, complete email [E1 sender safety and truthful status](06-email-notifications-and-delivery.md). A console fallback, missing address or failed provider cannot be recorded as delivered before any module relies on email for an urgent workflow.

## 4. Phase 2: Evidence Vault find, file and assure

**Objective:** A specialist can use the Vault productively at 500+ artifacts and distinguish uploaded material from accepted proof.

**Slice A, library:** List-first screen, persistent full-width search, saved filters, actionable views, compact detail drawer, accessible responsive behavior, pagination and bounded metadata queries. Link counts and reasons appear only for authorized targets. Upload supports source, owner, evidence period and review due date with guided linking.

**Slice B, version and proof:** Establish artifact-family identity, immutable version history, link/claim outcome and renewal rules. Migrate existing link semantics without rewriting old audit opinions. New versions generate an impact list; eligible links are proposed for carry-forward and require target owner review. Expired, superseded and archived material never counts as current proof. GRID and BCM adapters reuse one file identity while keeping their source-specific decisions.

**Slice C, intelligent assistance:** Add an assurance inspector for explicit defects and conservative duplicate/reuse suggestions. Full-text indexing comes only after classification, extraction and tenant/access controls are designed; AI navigation follows reliable ordinary search. Existing evidence campaigns feed My Work and the source claim view.

**Acceptance gate:** From a GRID question, AI use or BCM plan, the same current Vault artifact can be found and linked in a bounded number of steps. The receiving module still requires its own acceptance. A replaced artifact retains historical decisions and flags dependent current claims for review. Wrong-unit searches and AI suggestions leak no content or count.

## 5. Phase 3: AI Governance specialist home and external intake

**Objective:** The AI Governance landing page becomes a specialist dashboard and case workbench, and external form responses enter an accountable review flow.

**Slice A, navigation and home:** Introduce Overview, Requests, AI Systems, Reviews, Monitoring and Reports/packs with source-backed cards and charts. Keep existing G1 to G7 case routes, history, decisions and oversight accessible through the new structure. Move platform feature administration to the operator view. Remove literacy from specialist navigation only after its routes, completions and consumers have a retention/deprecation path.

**Slice B, Forms import:** Publish minimum question list and versioned Google/Microsoft Forms mapping guide. Add upload preview, row validation, owner and business-unit resolution, duplicates, correction revisions, idempotency and specialist confirmation. Attribute the import action to the signed-in specialist, with separate external requester facts. Allow a manual internal entry path. Imported content remains untrusted until triaged.

**Slice C, review desk:** Show known-system matches, applicable historical audits, controls, policy versions, vendor records, data processing, previous decisions and evidence. Extract verified facts only as candidate reuse. Open missing owner, missing proof or unanswered privacy/risk questions as named items. Use source module workflows for DPIA, AIIA, audit, risk and control work. Provide independent decision desk, condition follow-up and a scoped external response pack that distinguishes approved answers from unresolved matters.

**Acceptance gate:** A sample external response can be imported twice without duplicate case creation; a corrected response creates a revision with diff; an unknown owner remains unresolved. A governance specialist can complete review and export a response without creating a requester login. The approver cannot approve their own request where the decision rule requires independence. AI disabled leaves the full manual path usable.

Enable email [E2 pilot templates](06-email-notifications-and-delivery.md) for named internal AI Governance reviews only after intent/outbox, recipient scope and the temporary sender gate are ready. The external requester response remains a human-controlled export in this phase.

## 6. Phase 4: integrated module journeys and shared work

**Objective:** Make the source connections in [03](03-specialist-module-journeys.md) navigable and actionable without duplicating records.

Start with one representative application/process/vendor/AI use chain. Add typed links to Sentinel processing and DPIA, ARIA controls, GRID audit, BCM BIA/plan, ORM event and ERM risk. Publish material-change candidates from source events, with reviewer acknowledgement and idempotent delivery. Add a canonical entity 360-degree view, source-specific impact lists and My Work projections. Then extend to remaining module types. Bring assessment reuse, respondent assignment, formal exceptions and regulatory impact forward only when their source lifecycle and access matrix are explicit.

**Acceptance gate:** A vendor change identifies affected cases and creates one actionable review per owning module, without changing their signed decisions. An audit finding appears as GRID work and an attributed ERM signal; closing one does not silently close the other. All links and aggregates honor the reader's scope. A source module remains usable if the relationship service is unavailable, and the missing cross-module view is labelled partial.

Extend email [E3](06-email-notifications-and-delivery.md) to evidence, audit and continuity work as source owners approve it. Critical Sentinel and BCM escalation requires an alternate contact path and reviewed legal/incident clock before activation.

## 7. Phase 5: reliable reporting and governed intelligence

**Objective:** Offer management and board viewpoints that explain source, freshness, scope, limitations and the decision they support.

Create the shared metric registry and case/specialist/management/board presets. Freeze snapshots with source IDs and versions. Add quality and trend visualizations only when definitions, denominators and drilldowns reconcile. Add policy Q&A, external context and predictive explanations through the existing AI policy gate, scoped retrieval, citations, review and manual fallback. Track answer quality and hallucination/abstention outcomes. Do not extend AI into approvals, legal applicability or evidence acceptance.

**Acceptance gate:** A saved board report is stable over time, a data-poor report clearly states its missing inputs, and each number can be traced to authorized source records. External context cannot silently create a risk; a verified human decision is recorded in ERM. A policy answer cites the exact permitted version and says when no suitable policy is available.

## 8. Phase 6: optional entry and ecosystem expansion

After Forms import has real usage and measured pain, decide whether to build a limited invitation form. Design single-use or bounded invitation tokens, expiry, allowed organization and case, requester identity verification, anti-abuse, file scanning, consent/privacy notice, resumability and revocation. A requester can submit and view only their own receipt or clarification prompt; the governance specialist controls triage, internal links and decisions. A signed response may be returned through an approved channel. Reuse the existing intake lifecycle; do not build a second request table.

Other optional work includes approved source-system connectors, semantic evidence retrieval, model-component registry, public trust publication and shadow-AI discovery. Each requires a separate threat model, data-source owner, quality measure and pilot decision. No optional feature blocks Phases 1 to 5.

When a managed mail service identity is available, complete email [E4 provider cutover](06-email-notifications-and-delivery.md) as an operational release. Keep the same intents, templates and source actions, compare real acceptance and bounce outcomes, then revoke the temporary Gmail credential.

## 9. Migration, security and rollback

### Data migration inventory

| Existing data | Planned treatment | Reversal and audit constraint |
| --- | --- | --- |
| AI requests, profiles, decisions, evaluations and oversight | Preserve IDs and histories; add import provenance and new view projections | New UI can be turned off without deleting or reinterpreting standing decisions. |
| AI literacy courses, versions and completions | Retain read-only or archived access until external-project interface and retention are approved | No deletion merely because navigation is removed; exports and prior attestations remain available. |
| Vault items, versions and links | Add family/proof semantics through additive migration and backfill with explicit ambiguous cases | Keep bytes and earlier link decisions; do not infer acceptance from a link. |
| GRID/BCM mirrored files | Map to a canonical artifact family while retaining source record IDs and acceptance history | Reversible mapping/alias; check duplicates, hashes, ownership and access before any file cleanup. |
| Legacy reports | Distinguish frozen runs from historical recomputation and preserve old definitions | Never relabel a recomputed legacy view as an immutable report. |

Before a production migration, take and verify a restorable database backup, inventory tenant schemas and non-empty legacy tables, prove the migration on a representative copy, verify permissions and row security for the app role, and record a stop/rollback criterion. Use additive schema changes and gated UI/API behavior where possible. Migration scripts must be resumable or safely reversible. Preserve the current healthy service until readiness and a real specialist flow are checked. Do not assume a health endpoint proves tenant data or authorization quality.

### Security checks for every slice

- Organization and business-unit isolation at query, aggregate, search, link, prompt and export layers, including unknown and organization-wide ownership states.
- Capability and independent-decision enforcement in APIs, not only hidden buttons. External file and form content is untrusted; validate type, size, parsing, upload path and injection handling.
- Cross-module links do not grant read rights. AI providers receive only policy-allowed, minimum permitted fields. Imported contact data has purpose, retention and access rules.
- Audit records identify actor, source/version, decision and reason. Logs omit passwords, tokens and full sensitive payloads. Failed background jobs are visible and retry idempotently.
- A restricted or revoked report, evidence item or link is removed from all derived views and citations, with preservation of authorized historic audit history.

## 10. Verification strategy for implementation

This document proposes future checks; none were run while writing the plans. For each slice, capture a failing behavioral check for the relevant gap before changing it and run focused checks on the affected module and shared contracts. Use representative PostgreSQL tenant schemas for migrations, scope and report snapshots. Cover unit, API, integration, migration and browser journeys. A full suite is a later stage gate only when requested and when the larger stage is ready.

Required role scenarios include requester/importer, specialist reviewer, independent decider, module owner, board reader, wrong-business-unit employee, platform operator and external recipient. Check empty tenant, 500+ artifacts, duplicate/corrected import, expired proof, unavailable source, stale cache, revoked recipient, AI-disabled path and concurrent decision/version update. Conduct a manual specialist walkthrough with Ali Moyo and Vivian Tsongorera or designated governance users using pilot data; record observations and any differences from the plan. Do not treat a pilot login's existence as evidence the end-to-end workflow passed.

## 11. Measurable success criteria

| Outcome | Measurement in pilot | Target-setting rule |
| --- | --- | --- |
| Triage effort | Median active specialist minutes per complete imported request; count manual corrections separately | Measure baseline first, then agree improvement with governance lead. |
| Review clarity | Percentage of requests with named owner, outstanding items and decision basis visible in one case | Define eligible requests and sample audit before setting target. |
| Evidence findability | Time and search steps to find a known current item among 500+ mixed artifacts | Use actual permitted roles and a known-answer set; exclude inaccessible items. |
| Proof quality | Number of accepted, current claims versus linked-only claims; reviewer disagreement rate | Do not optimize by automatically accepting more proof. |
| Response reliability | Percentage of external responses traceable to source facts, decision and limitations | Human review required for all pilot exports. |
| Reporting trust | Reconciliation of card, drilldown, saved report and permitted source rows | Zero unexplained differences for release-gating metrics. |
| Cross-module work | Time from source change to owner-visible review and closure in owning module | Include failed-delivery and duplicate-event cases. |
| AI usefulness | Accepted suggestions, corrected drafts, citation failures and abstention quality | AI must never be required to complete the workflow. |

Do not invent business success percentages before baseline measurement. Keep usability findings and data-quality defects visible alongside adoption numbers.

## 12. Release order, responsibility and completion record

The product/governance lead owns terminology, role model, workflow and acceptance. Privacy/legal owns jurisdiction rule approval and retention. Module owners own facts and decisions in their domains. Engineering owns shared contracts, migration, permission enforcement and observability. Security reviews external intake, file handling, AI data movement and external report access. Pilot specialists validate the real navigation and output. A phase is complete only when its source owner signs off behavior and the focused evidence above is attached to an execution ledger.

Record, for every implemented slice: issue and design decision; code/schema change; migration and backfill result; focused checks and their environment; manual journey outcome; authorization review; rollout cohort; observed metrics; rollback action; and unresolved limitations. Update the older programme ledger with links rather than rewriting past status. Mark *planned*, *built*, *verified locally*, *pilot live* and *generally released* separately.
