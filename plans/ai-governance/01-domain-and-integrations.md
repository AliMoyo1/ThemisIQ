# 01. Domain, data sources, and cross-module contracts

**Status:** Proposed implementation contract. Read [programme index](README.md), PLAN-37, the current schema, and the live permission model before schema work. All names below for new tables and routes are proposals, not existing endpoints.

## 1. Concepts and source of truth

| Concept | Definition | Authoritative record | AI Governance projection |
| --- | --- | --- | --- |
| AI use | A business deployment or intended use of AI, including embedded vendor AI | One Governance `applications` row, marked by an AI profile | Searchable AI Systems entry and lifecycle summary |
| AI component | A provider model, hosted service, agent, or version used by an AI use | Versioned child record only when the pilot requires multiple components | Current version and change history; never flattened into one mutable name |
| Processing activity | Purpose and flow of personal data | Sentinel RoPA and Governance process/data assets | Linked context, never a second RoPA |
| AI impact | Effect on people, privacy, fairness, security and society | AI Governance AIIA (table `sentinel_aiia`, moved here by [06](06-aiia-in-ai-governance.md)) and the applicable Sentinel DPIA | Required/reviewed/expired status and deep link |
| AI management risk | Risk, treatment, and AI controls | ORM AIMS and ERM as applicable | Distinct inherent, current, and expected residual views |
| Approval | A decision by a permitted reviewer on a named version and its conditions | Existing workflow engine plus proposed immutable AI decision snapshot | Derived `needs review` or `approved` summary |
| Proof | A specific document/evidence version and its review state | Evidence Vault, GRID and ARIA records | Manifest, age, verification, permission-aware link |

**Field ownership before migration:** `applications` owns stable name, owner, business unit, department, vendor, hosting, criticality, and active/retired state. The AI profile owns stable use-specific facts: purpose, AI capability type, intended users/affected people, autonomy, deployment context, intended jurisdictions, model/service reference, and review cadence. The AIIA (owned by AI Governance from slice G3b; the Sentinel screen is gone, the table is unchanged) snapshots the facts and data categories considered at assessment time and owns impact dimensions, mitigation, classification, reviewers, and its status. RoPA owns processing purpose, categories, lawful basis, recipients, retention, and transfers; DPIA owns privacy assessment. A prefill displays its source and timestamp; changes never rewrite a submitted or approved assessment. Record the exact column-level mapping after inspecting the deployed schema and UI.

**Lifecycle vocabulary:** intake `draft -> submitted -> returned/approved/rejected`; application `active/retired`; assessment and policy states remain in their modules; AI decision `proposed -> approved/approved with conditions/rejected -> expired/revoked/needs re-review`. Workspace state is derived from the last valid decision and current prerequisite fingerprints. A decision never edits an AIIA, a risk, or a policy status. Missing, inaccessible, stale, and not applicable are separate display states.

## 2. Proposed persistence and migration contract

1. `ai_use_intake_requests`: tenant ownership, BU, submitter, draft payload and version, optional matched application ID, status, reviewer, decision reason, rule version, timestamps and idempotency key. Staff can submit without `governance.entities.manage`; only a permitted reviewer promotes or links an application.
2. `ai_use_profiles`: one-to-one by `application_id`, versioned changes or append-only history, AI-specific fields only, last-reviewed date and retired reason. Add a checked FK where migrations permit. Use tenant/schema ownership plus explicit BU authorization; do not assume a nullable `business_unit_id` is public.
3. `ai_use_decision_snapshots`: workflow instance ID, application/profile version, assessment references and versions, required steps and signed not-applicable reasons, reviewer and separation-of-duties result, evidence-version manifest, conditions, expiry, rule version, decision, timestamp. Append decisions; do not update the prior approval when a model changes.
4. Add `application_id` and a valid reference path to AIMS, set and validate `sentinel_aiia.application_id` from the screen, and define mappings between ORM's AI controls and canonical controls. Use strong FKs for one-to-one or one-to-many ownership; use the shared relationship service for cross-module many-to-many edges.
5. Add model-component records and evaluation-result records only when their feature slice is ready. They need stable application identity, version, provider, allowed metadata, status, and a retention rule. Raw prompts and responses are not inventory fields.
6. Define schema separately for SQLite development and PostgreSQL production through existing migration conventions; explicit constraints, indexes, rollback behavior, and tenant binding are required. Backfill old AIIA/application name matches into a review queue; never guess a match or invent a reviewer, approval, or evidence version.

## 3. Required module adapters and data contracts

Every adapter accepts actor, tenant, permitted business-unit set, and module capability. It returns `record_ref`, permitted title/summary, source status, source version or update time, deep link, visibility state, and freshness. It cannot return a count or an existence hint for an inaccessible row. A missing capability yields a generic unavailable section, not a redacted list of hidden titles. Adapters only read; writes go to the owning module's authorized service.

| Module/source | Data supplied to AI Governance | Write owner and cross-module action |
| --- | --- | --- |
| Governance `applications`, processes, `data_assets` | System identity, BU, owner, purpose, linked data and process | Governance creates/promotes/retire applications; AI intake calls its authorized service |
| Canonical vendor and module vendor records | Provider identity, contract/security review state, affected services | Vendor owner confirms relationship; procurement/registration can propose AI-use intake |
| AI Governance AIIA (moved from Sentinel, [06](06-aiia-in-ai-governance.md)) | Impact dimensions, classification, mitigation, status | AI Governance writes the assessment through its own service; the workspace reads the same rows in process and opens the exact record |
| Sentinel DPIA, RoPA, data flows, jurisdictions | Processing, affected people, reviewed jurisdiction context | Sentinel creates and approves these; workspace opens exact record |
| ORM AI controls and AIMS; ERM risks and appetite | AI control implementation, risk and treatment, approved acceptance | ORM/ERM retain scoring, treatment and acceptance; workspace explains basis and review age |
| ARIA frameworks, policies, canonical controls | AI policy version, mapped framework/control and implementation | ARIA owns policy drafting, named approval and publishing |
| GRID audit/finding; Evidence Vault | Test result, finding, proof item and exact version, review outcome | GRID owns audit decision; Vault owns files, versions, integrity and evidence requests |
| BCM incidents, plans, exercises | AI-related outage/incident and continuity evidence | BCM owns incident and response; a structured affected-application link drives impact |
| Launcher workflow, My Work, Command Centre, notifications | Approvals, assigned next actions, summary metrics | One workflow action ID; projection only, no duplicate task status |
| Regulatory Inbox and ERM External Context | Sourced change, issuer, date, effective date, reviewed impact | Existing inbox owner confirms applicability and actions |

Adapter candidates must be verified against the current schema and existing route authorization before coding. PLAN-37 identifies missing process-to-application and structured BCM affected-system edges, a missing AIMS application reference, and incomplete link type registries. Those are implementation prerequisites, not assumptions that a graph can infer them.

## 4. Relationship service and event contract

Use PLAN-37's single permission-checked relationship service, seeded from the Vault resolver and replacing the current divergent Related Items/core links registries. Allow typed edges such as `application uses data_asset`, `application provided_by vendor`, `application supports process`, `AIIA assesses application`, `AIMS assessment covers application`, `control mitigates risk`, `evidence supports control`, `incident affects application`, and `regulatory change impacts application`. Each edge has source, target, relation, actor, provenance (`manual`, `imported`, `system candidate`), confirmation state, source version/time, and audit history. An inferred candidate is never a confirmed link.

On create/read/remove, validate both endpoints against the actor's tenant, BU, role and module capability; a link cannot grant access. Preserve a generic response for unknown and unauthorized targets. Resolve titles and counts after authorization, including graph traversals, exports, notifications, AI retrieval, and cached projections. Bound traversal depth and result size. Scope the vendor cross-module profile before it can feed this workspace.

Use `core/events.py` after PLAN-37 closes its atomicity and retry gaps. Candidate event types include `ai_use.submitted`, `ai_use.approved`, `ai_use.material_change`, `ai_use.retired`, `aiia.completed`, `ai_control.failed`, `evidence.expired`, `evaluation.failed`, `vendor.incident`, `bcm.incident`, and `regulation.reviewed`. Each event carries tenant, BU, source ID/version, actor, type, timestamp and dedupe key. Enqueue within the source transaction or a transactional outbox; workers retry idempotently and expose dead letters. Consumers update My Work, notifications and workspace projections, never specialist truth. Failed projection = stale/unknown with retry visibility, not an all-clear state.

## 5. Authorization and AI-service guardrails

- Capabilities should separate `ai_use.submit`, `ai_use.review`, `ai_use.view`, `ai_use.link`, `ai_use.decide`, and `ai_governance.policy.manage`; map roles explicitly during implementation. A submitter cannot approve their own consequential request when tenant policy requires separation. Every transition rechecks source version and capability.
- Tenant scope must be enforced by the server and, where applicable, PostgreSQL policy. BU focus in the UI cannot widen rights. Add an actor-by-record-type matrix covering list, detail, counts, search, link create/delete, exports, notifications, audit packs, and AI prompt/citations. Include records with NULL or legacy BU deliberately.
- The planned shared AI-call wrapper receives actor, tenant, feature, approved provider, permitted data categories, source IDs/versions, retention choice and budget. Enforce policy before transmission, redact/minimize fields, use bounded timeouts, log usage and cost, and refuse direct client calls elsewhere. Disable the AI action when policy or provider blocks it; keep manual paths usable.
- Treat uploaded documents, OCR text, external pages and vendor responses as untrusted data. Retrieval verifies scope before ranking and again before rendering. No model output can establish legal applicability, approve an AI use, change a risk score, publish a policy, or mark proof accepted. Save only an explicitly reviewed draft with source provenance.
- Maintain separate platform-operator governance for ThemisIQ's own AI features. A platform inventory may record a feature and version, while customer-level provider/data-category policies remain isolated per organization. Do not combine customer prompts or evidence across tenants for oversight metrics.

## 6. API and UX contract for the first slice

Proposed routes: `GET/POST /ai-governance/intakes`, `GET/PUT /ai-governance/intakes/{id}`, `POST /ai-governance/intakes/{id}/submit`, `POST /ai-governance/intakes/{id}/review`, `GET /ai-governance/systems`, `GET /ai-governance/systems/{application_id}`. Exact names and HTTP method conventions are decided against existing router patterns before implementation. Mutation responses include the authoritative record ID/version and a safe return URL; retries need idempotency keys and optimistic concurrency. List filters are URL-addressable and server-paginated. A denied source record must not be revealed by a workspace card, selector, badge count, or error message.
