# 03. Delivery, migration, and acceptance

**Status:** Proposed sequencing. Use the [programme index](README.md) and [domain contract](01-domain-and-integrations.md) with the [feature journeys](02-feature-journeys.md). A slice is ready only when its named functional, security, accessibility, PostgreSQL, and operational checks have evidence. Writing code or passing a SQLite-only test does not mark it complete.

## 1. Dependencies and build slices

These are dependency gates, not a promise that every earlier portfolio track must finish before a useful pilot. Work on the CISO quality inspector and GRID/ERM improvements may run alongside AI Governance when their own prerequisites are met.

| Slice | Work and owning plans | Deliverable and exit evidence |
| --- | --- | --- |
| **G0. Current-state and policy decisions** | Reconcile branch, uncommitted changes, PLAN-36, Vault phase, current PostgreSQL schema and live role/BU behavior. Observe staff, DPO/risk, AI owner and auditor journeys. Inventory existing AIIA/AIMS/application links, data sources, candidate framework content rights and ThemisIQ AI providers. | A field ownership matrix, entity and capability matrix, 2-3 pilot uses, baseline task time/errors, migration inventory, agreed risk/applicability policy. No production changes. |
| **G1. Trust and common contracts** | PLAN-37 Slice 1, SBU work, Vault scope/version gates and Slice 1b AI service policy. Fix global search/Related Items/vendor-profile disclosure before reuse. Implement relationship resolver, authorized source adapters, event transaction/retry, scoped retrieval and AI-call wrapper. | Wrong-org/BU/user access is denied for title, count, link, search, export, notification and prompt. Link create/delete audited. Event retries do not duplicate work. AI calls have tenant/provider/data-category policy and usage records. |
| **G2. Intake and read-only workspace** | VerifyWise 01-02 and PLAN-37 Slices 2a-2b. Add intake, AI profile keyed by application, duplicate resolution, vendor/process AI flags, reviewed AIIA/application link, authorized list and source-adapter workspace. | Staff can draft/submit/resume; reviewer can promote/link exactly one application; AIIA opens the same system. Every displayed related item is openable by that actor. Empty/stale/denied states are distinct. Pilot with 2-3 systems. |
| **G3. Guided assessment and evidence** | PLAN-19/20/21, ARIA, Vault, CISO 01 and VerifyWise 03 prerequisites. Add versioned, explainable requirement rules and deep links to existing forms; map ORM AI controls to canonical controls; show current proof and inspector findings. | A reviewer can trace every required or inapplicable step to a rule and responsible module; no duplicated AIIA/DPIA/AIMS. A proof item shows exact version and review state; quality findings identify a real fix route. |
| **G3b. The AIIA moves into AI Governance** | Owner instruction 2026-10-11, planned in [06](06-aiia-in-ai-governance.md). Move the AIIA screens, API and service from Sentinel into AI Governance with its own capabilities, unit scope, audit, version check and redirects; keep the tables and link identity. | Every former operation works at the new address with equal or stricter scope; old addresses redirect; row counts unchanged; the checklist starts and reads the assessment in place. Runs after G3 and before G4, because a decision manifest needs the assessment's version and status in the module that owns them. |
| **G4. Decision and action lifecycle** | VerifyWise 03, PLAN-37 Slice 3, CISO 04 where risk acceptance is needed. Add workflow template, frozen decision manifest, conditions/expiry, material-change detection, one My Work action and notification per source event. | Approval refuses unresolved mandatory steps, honors separation of duties and concurrency, survives retry, and reopens after change without altering the old decision. ERM risk acceptance remains a separate signed exposure decision. |
| **G5. Operational intelligence and AI** | VerifyWise 04-05 and 08; PLAN-37 Slices 4-5. Start evaluations with Ask ARIA, then one consented customer AI use; add reviewed regulatory impact; release Find/Explain before Prepare/Suggest. | Evaluations preserve versions and failed-run state. Regulatory items cite current primary sources and human confirmation. AI citations resolve to permitted versions; no policy bypass, prompt-injection success or unauthorized prompt content in the evaluation set. |
| **G6. Expansion after pilot evidence** | VerifyWise 06-07, optional model components, CISO assurance and sharing plans. Add named auditor packs, role-based literacy, and, if needed, component lineage. VerifyWise 09 stays discovery until a real authorized feed exists. | Pack manifest and recipient rights proven; training completion is genuine; component changes re-open decisions. Shadow AI coverage is not claimed without an agreed source. Public trust publication requires separate approval. |
| **G7. Conditional EU content pilot** | After G3-G5 prove applicability rules, versioned decisions and monitoring, pilot the [EU AI Act extension](04-eu-ai-act-and-operational-assurance.md) with a confirmed provider and deployer use case. Separate the provider binder/post-market plan from the deployer FRIA/operation path as applicable. | Legal/content owner approves current rule version and effective dates. Role-specific tasks, human oversight, incident clocks, exact-version artifacts and denied-scope surfaces work; an out-of-scope use does not receive false obligations. |

Within each slice, ship a useful manual workflow before AI assistance or rich visualization. A feature flag may hide incomplete navigation but cannot restore insecure legacy routes. Enabling flags is a release decision with rollback behavior.

## 2. Migration and data-quality sequence

1. Read production schema and row counts without modifying it. Confirm tenant-schema versus shared-table location, `org_id` ownership, existing RLS policies, NULL BU semantics, FK/index state, and how many AIIA, AIMS, applications, vendors and evidence links exist. Do not infer live status from the local SQLite database.
2. Write a mapping of each existing field to profile, AIIA, RoPA, DPIA, application, vendor or model component. Identify duplicate names and conflicting owners. Choose the authoritative record with an owner; keep unknowns in a review queue.
3. Add new nullable fields/tables and indexes in a backward-compatible migration. Deploy read-only adapters first. Use dual-read only if necessary, with one write owner. Validate SQLite and actual PostgreSQL syntax/transaction behavior before release.
4. Backfill candidate `sentinel_aiia.application_id` and AIMS application links only after a reviewer verifies each association. Record migration actor/source/time. Never manufacture historical approval, training completion, risk acceptance, proof verification or model version.
5. Turn on intake for one permitted pilot organization, then workspace, then decisions. Retain old module routes and deep links. Rollback hides new views and stops new event consumers while preserving submitted requests and signed decisions for recovery; do not delete audit history.
6. For any generated export, decision or pack, record source IDs/versions, tenant/BU, actor, rule version and generation time. A later source change marks current view for re-review but does not rewrite a past snapshot.

## 3. Permission and data-flow acceptance matrix

For each source adapter and new endpoint, enumerate anonymous, signed-in submitter, AI owner, DPO, risk owner, module reviewer, auditor, tenant administrator and platform operator. Repeat across same BU, other BU, same org with shared visibility, other org, legacy NULL-BU record, retired record and deleted/dangling edge. For every actor/record pair, cover list, detail, counts, picker, related-items list/graph, search, citation, export, audit pack, notification, link create/remove, update and decision. The invariant is **no unauthorized title, count, ID or existence signal**. An unauthorized and nonexistent target have equivalent outward behavior.

Data flows requiring explicit review before implementation:

- **User -> intake -> application/profile:** validate inputs, idempotency and reviewer capability; staff draft and submit, reviewer creates/links system, neither route bypasses tenant and BU scope.
- **Module -> AI workspace:** server adapter filters before aggregation; cache keys include tenant, actor/capability scope and source version or are omitted for sensitive results. A cross-module link is never an access grant.
- **Module -> event -> My Work/Command Centre:** source transaction or outbox commits once; idempotent consumers and a dead-letter review path keep due work accurate.
- **Source records -> AI provider:** organization AI policy checks provider, allowed data categories and destination; minimize payload, bound retention, log usage; source document text is data, not instructions.
- **Vault/GRID -> pack -> recipient:** freeze exact selected versions; authorize each view/download; expire/revoke and audit access. No raw object URL bypass.
- **External source -> Regulatory Inbox -> confirmed impact:** store issuer, URL, retrieval/effective dates and amendment status; reviewers decide applicability and task creation. Untrusted text cannot direct the workflow.

## 4. Verification planned for implementation slices

This is a future acceptance plan; no tests are run by creating these documents.

- **Unit and contract:** rule versioning, missing-data handling, status projection, event idempotency, decision preconditions, duplicate intake, frozen manifests, trained-versus-assigned distinction, invalid/expired proof, and safe failure states.
- **Real PostgreSQL:** migrations, FK/index constraints, transactional event/outbox behavior, concurrent review, tenant schema/RLS behavior, legacy NULL-BU rows, rollback after errors, and scope matrix. Use only the repository's controlled disposable test database; never production data.
- **Browser:** staff registration/resume, reviewer return/approve, source deep link/return, monitoring comparison, filters and saved views, denied and stale states, manually accessible path when AI is disabled. Cover desktop, true mobile viewport, keyboard, 200% zoom, screen reader landmarks, focus, reduced motion and drag-free equivalents.
- **Security and AI:** wrong-org/BU/module access at all output surfaces; prompt-injection documents and web text; no-match/hallucination/citation validity; provider-policy refusal; export/download and invitation permission loss; cost, timeout and retry limits; upload and content sanitization.
- **Load and reliability:** 500 and 5,000 evidence items, representative number of AI systems and edges, bounded list/graph queries, slow or unavailable provider, stale regulatory source, failed event consumer and recovery. Measure on the target VPS class after baseline; do not invent a latency SLO before measuring.

Do not call a feature complete when PostgreSQL, browser, source-access, or rollback checks were skipped. Record exact limitations and keep the relevant flag off.

## 5. Pilot outcomes and operational metrics

Set actual targets after G0 measurements. Proposed pilot measures are: time to register and resume an AI use; share of pilot systems with confirmed owner/provider/data mapping; share with a reviewed assessment and current decision; time from material change to assigned re-review; rate of duplicate or invalid links; reviewer time spent finding evidence; precision of quality issues; evaluation failure and correction rates; citation validity and unauthorized-result rate; AI usage and cost per tenant; and auditor time to find a named proof version. All denominators, exclusions and data freshness are shown on dashboards.

The pilot is successful when representative staff complete the journey without module knowledge, reviewers can trace every approval to exact versions, owners can explain why a system needs action, and scope checks pass across every linked surface. An attractive overview alone does not satisfy this gate.

## 6. Decisions to resolve before code

| Decision | Recommended default | Owner to confirm |
| --- | --- | --- |
| What qualifies as one AI use versus component? | One business deployment is one application; optional versioned components under it | Product and customer pilot |
| Who can see an AI system across business units? | Only granted BU/module scope; define explicit org-wide exceptions | Security and tenant administrator |
| Who may submit, review, approve and override? | Broad authenticated submit, narrow specialist review, separation of duties for consequential approval | Tenant governance owner |
| When are AIIA, DPIA, vendor, evaluation and training mandatory? | Organization policy and reviewed jurisdiction/framework applicability; `unknown` requires review | DPO, risk and AI governance owner |
| Which change reopens a decision? | Purpose, data, model/provider, autonomy, deployment, jurisdiction, serious incident, failed critical control or expired required proof | AI governance owner |
| What data may ThemisIQ send to an AI provider? | Deny until tenant provider/data-category policy authorizes the feature; manual path available | Tenant admin and security |
| What may appear in auditor or public views? | Named authenticated packs first; public claims require separate publication approval | Audit owner and communications/legal |
| How are imported framework controls licensed and versioned? | Start with content the customer is authorized to use; freeze edition in assessment history | Framework owner and legal |

## 7. Change log for execution

When implementation begins, record each slice's baseline commit and production version, schema changes, chosen decisions, review evidence, skipped checks, known limitations, rollout flag, rollback result and owner in a companion execution ledger. Keep these design plans as proposals until that evidence exists.
