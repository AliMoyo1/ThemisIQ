# PLAN-37: Connected compliance and contextual AI experience

**Status:** Product and implementation proposal, 2026-10-07. No application code, schema, deployment, or production configuration is changed by this plan. The sequence below is proposed; it does not mark any feature complete. Reviewed against the code on 2026-10-07; the findings are folded in below and itemized in Appendix A.

**Goal:** Make ThemisIQ the place where a person can register a concern once, understand which obligations and records it affects, complete the next action with guidance, and show the exact proof behind a decision. The differentiator is one connected compliance journey across ARIA, GRID, BCM, Sentinel, ERM, ORM, Evidence Vault, and the Command Centre, with AI assisting at the point of work.

**Delivery navigation:** The [plan portfolio](ROADMAP-2026-10.md) sequences this programme with [Evidence Vault](../design/evidence-vault/PLAN.md), [VerifyWise-inspired features](verifywise-features/README.md), and [CISO Assistant-inspired assurance features](ciso-assistant-features/README.md). Those feature plans extend the journeys here without creating parallel records or changing this proposal's current status.

## 1. Product thesis

The user should not have to know which module owns a task before starting it. They should be able to ask “We want to use an AI assistant with customer data”, “A critical vendor has failed”, or “What proof do we have for this control?” ThemisIQ should identify the relevant records and next steps, reuse existing information, and let the accountable people confirm decisions. A task has one owner and status even when several modules depend on it.

Five promises define the experience:

1. **Enter once, reuse deliberately.** Shared organization, business unit, application, data asset, vendor, control, and evidence records supply linked workflows; show prefilled values and their source before saving.
2. **Show why.** Every risk signal, compliance status, AI suggestion, and dashboard count opens the underlying record, rule, date, owner, and evidence version.
3. **Guide the next action.** The Command Centre and entity workspaces surface relevant work, prerequisites, and a clear route to finish it. Existing My Work, Task Board, workflows, and campaigns remain the action systems.
4. **Keep people accountable.** Deterministic rules establish obligations, deadlines, and statuses. AI helps find, draft, compare, and explain; a qualified person accepts consequential classifications, links, approvals, and reports.
5. **Stay usable as data grows.** Search, filters, saved views, pagination, accessible record drawers, and precise deep links come before novel visualization or broad chat.

## 2. Verified starting point and boundaries

This is based on a read of the repository on 2026-10-07, not a claim about every production configuration. Recheck the checkout and live tenant before implementation.

| Existing ThemisIQ foundation | Extend it for this plan |
| --- | --- |
| `applications`, `data_assets`, business units, departments, processes, canonical vendors and controls in `database.py` and `modules/governance` | Keep `applications` as the canonical application identity. Add an AI-specific profile only for AI-specific fields; link existing assets and vendors rather than making parallel registries. |
| `cross_module_links`, Related Items, entity deep links, global search | Add typed, permission-checked relationships and useful context views on top of these; no second generic graph table or search bar. |
| Sentinel AIIA, DPIA, RoPA, jurisdictions, breach workflows | Link the assessment to the canonical application and prefill from approved application/data records; preserve Sentinel's assessment lifecycle. |
| ORM AI Controls Catalogue and AIMS/ORAAT; ERM risk/controls, scenarios, external context and predictive signals | Connect these to the application and shared controls. Reuse the existing scoring conventions and distinguish risk signals from reviewed findings. |
| ARIA managed policies, generation and Ask ARIA | Extend policy and control links; keep approval/publication in ARIA. Verify and close retrieval-scope gaps before giving an assistant cross-module access. |
| Evidence Vault, evidence campaigns, verification, versions, confidence, and Phase 1a/1b roadmap | Reuse canonical evidence and requests. [Evidence Vault plan](../design/evidence-vault/PLAN.md) owns its library, scope, search, and guided intake; this plan supplies cross-module use cases. |
| Command Centre, My Work, Task Board, workflow engine, Regulatory Inbox, advisories | Improve the journey and projections through these surfaces. Do not create a second tasks table, reminders engine, or regulatory inbox. |

`PLAN-36` still records open release acceptance work. Evidence Vault Phase 1a is built and verified locally but not committed, and its PostgreSQL test lane has not been run, so it is not yet a shipped capability. The first implementation slice below begins only after the applicable stabilization and tenant-scope gates are satisfied. Old plan text can be stale; source and fresh acceptance evidence decide current status.

**Verified limits of these foundations.** Code read on 2026-10-07; the first item was also reproduced on a throwaway database; evidence in Appendix A. They change what the early slices must do.

1. **Scope gaps already exist in the layers this plan extends.** Related Items and topbar search show another business unit's titles to a user who cannot open the record. The linking API checks that a record exists but not that the caller may see it, so creating a link and reading it back reveals the title and existence of 10 entity kinds. Neither path checks module access, and link creation and removal are not audited. Cross-module aggregators such as the vendor cross-module profile ignore the viewer's scope. These are Slice 1 defects, not future risks.
2. **Three registries of linkable record types exist** (Evidence Vault's resolvers, Related Items, and `core/links.py`), and none includes application, data asset, AIIA, AIMS assessment, or workflow instance. `cross_module_links` has no scope, provenance, or status columns.
3. **Some edges the journeys assume are not stored.** There is no process-to-application dependency; BCM incidents record affected systems as free text; AIMS assessments carry no application reference; ORM's AI control catalogue is separate from canonical controls.
4. **AIIA already stores most of the proposed AI profile** (autonomy, data categories, deployment, third party, stakeholders). `sentinel_aiia.application_id` has no foreign key and no screen sets it, so expect it empty.
5. **Application access does not fit the intake journey as written.** Five roles can create applications; every role can list all of them, and all data assets, with no business-unit filter. There is no duplicate check, and deletion is a hard delete.
6. **The event bus and the AI client are only partly built.** `core/events.py` persists events with a dedupe key and an event ID, but writes outside the caller's transaction, never retries failed events, and lacks the event types this plan needs. About 70 references in 15 files call the AI client, whose signature carries no user, organization, or feature; usage is not logged (except Ask ARIA's Q&A log) and there is no per-organization AI policy.

## 3. Four reference journeys

### A. Register and govern an AI system

1. A staff member chooses **Register an AI use** from the Command Centre or application inventory. A short guided form captures purpose, owner, business unit, provider/vendor, model or service, data categories, affected people, autonomy, intended jurisdictions, and planned deployment. Save a draft after the essentials; ask deeper questions only when triggered.
2. Submitting the draft creates an intake request. When a permitted reviewer approves it, the system creates or links one canonical `applications` record and an AI profile, with a stable reference and lifecycle state; staff do not write `applications` directly. Duplicate detection is new work: it checks for a likely duplicate before creating another application. Once the AI service foundation (Slice 1b) exists, AI may suggest a classification, showing the answered facts and uncertainty; until then the form shows a rule-based provisional tier.
3. A generated checklist points to the existing AIIA, DPIA/RoPA where applicable, ERM/ORM risk work, AI controls, policy, vendor review, evaluation evidence, and approval workflow. Each step opens the owning module at the exact record and returns to the AI system workspace.
4. Reviewers see what changed since the last decision, the current evidence versions, open high risks, missing owners, and uncompleted prerequisites. Their approval captures a snapshot and any conditions. Deployment/approval labels change only through a permission-checked decision, not a model response.
5. Post-approval review dates, incidents, model changes, vendor changes, and evidence expiry can reopen the relevant work. The history explains why the system's status changed.

### B. Prepare an audit or answer a control question

From a control, audit, framework requirement, or natural-language query, show the same canonical evidence items, current versions, verification, owner, linked assessments, last review, and gaps. **Attach existing evidence** precedes upload. An auditor pack is a reviewed snapshot with a manifest, exact versions, and a scope-safe export; a pack never implies an unreviewed control is satisfied. Build on the [Evidence Vault plan](../design/evidence-vault/PLAN.md) and existing GRID workflows.

### C. React to an incident, breach, or vendor failure

Start from the event in BCM, Sentinel, or ORM. An **Impact** panel walks the person through connected processes, applications, data assets, vendors, risks, controls, plans, audits, and evidence. It proposes relevant cross-module actions such as assess privacy notification, invoke a continuity plan, or create a corrective task. Each proposed action has an owner and explicit confirmation. The originating event remains the source of truth; linked modules keep their own specialist records. The walk needs stored edges that do not exist today (Section 2): a process-to-application dependency, structured affected applications and vendors on the incident, and an application reference on AIMS assessments. Until they exist, show only the edges that are stored and say which are unknown.

### D. Respond to a regulatory or emerging-risk change

Extend the existing manually governed Regulatory Inbox and ERM External Context. Record the primary source, jurisdiction, effective date, reviewer, and change summary. Deterministic mappings find likely frameworks/controls and linked applications; optional AI proposes an impact explanation with citations. A reviewer accepts affected records before tasks are assigned. Watchlist choices and a dated history prevent irrelevant change noise.

## 4. Product surfaces and usability work

### Command Centre: from summary to action

Keep the customizable dashboard. Add a compact **Start work** action and role-aware “Needs my decision”, “At risk soon”, and “Recently changed” views that deep-link to records. Every card must answer *what*, *why now*, *owner*, and *next action*. Keep module health available as an optional card. Avoid duplicate alerts from My Work, briefing, and module dashboards by deduplicating on a canonical source record and event.

### AI system workspace: one case, many module lenses

Within the canonical application's page, use tabs or sections for Overview, Assessments, Risks & Controls, Data & Vendors, Evidence, Approvals, Monitoring, and Activity. Show a small completion path and missing prerequisites before detailed tables. Module records remain editable in their home modules; the workspace presents their latest state, actions, and deep links. Show “not started”, “needs review”, “blocked”, “approved with conditions”, and “not applicable” distinctly. Build each tab on a source adapter that applies the viewer's own module and business-unit scope; never reuse another module's unscoped aggregate. The existing vendor cross-module profile (`core/vendor_link.py`) is a good model for deterministic flags and a warning on scope: it returns GRID and Sentinel fields to any BCM user.

### Impact explorer: relationships without a hairball

Start with an accessible **Related to this record** list grouped by relationship and problem state. Add a focused graph as a secondary view: one or two hops by default, filters by entity type, “show gaps”, search, keyboard controls, and a details panel. A relationship click explains whether the link is automatic, imported, or user-confirmed and where it came from. Do not use a full graph as the default navigation method.

### Consistent interaction contract

Use one term for each concept; give long forms a progress indicator and resume path; show prefill provenance and editable overrides; preserve context when crossing modules; provide useful empty states and reversible actions where possible. Loading, errors, permissions, and unavailable AI should use the shared capability and request-state vocabulary. Support keyboard, screen reader, reduced motion, zoom, and narrow screens at every release gate. Keep search/filter state in the URL or saved view when returning to a list.

## 5. Contextual AI: small assistants inside work

| Assistant action | Entry point and output | Boundary |
| --- | --- | --- |
| **Find** | Search evidence, policy, control, risk, or application in ordinary language; return ranked, cited, permission-checked records and editable filters | Read only; no invented record or unsupported compliance statement. Evidence-specific design lives in the Vault plan. |
| **Explain** | “Why is this red?”, “What changed?”, “What must I do next?” on a record; cite rule, source record, date, and owner | Deterministic state and score are calculated outside the model. |
| **Prepare** | Draft a DPIA/AIIA section, BCP outline, policy revision, control response, or audit narrative from selected records | Preview source facts, gaps, and citations. Save as a draft only after user confirmation; specialist module owns workflow. |
| **Suggest connections** | Candidate evidence reuse, relevant controls, affected records after an event or regulatory change | Show rationale and confidence; verify both ends' access; user confirms links. |
| **Monitor** | Flag stale evidence, upcoming reviews, changed vendors/models, control drift, or worsening risk signals | Rules produce the alert; AI may summarize it. Deduplicate and let users dismiss with a reason. |

Use a single, scoped retrieval and citation layer for these actions rather than giving each module a separate unbounded chatbot. An assistant must know the user's current record, permitted org/BU scope, source versions, and the action it may propose. Keep a normal non-AI path when the model or provider is unavailable. Record cost, invocation, source IDs, user feedback, and decision outcomes without retaining unnecessary sensitive prompts or excerpts.

**Trust gate:** before broad cross-module retrieval, verify and fix the Ask ARIA indexing/scope concern noted in [Evidence Vault Phase 1a](../design/evidence-vault/PHASE-1A.md). Treat uploaded documents, external pages, and OCR text as untrusted content. Validate every result, snippet, citation, and action against current permissions after retrieval and before display or write. AI cannot approve, publish, classify legal applicability, close a finding, or change a compliance score on its own.

**Two more gates, both verified as open (Section 2).** First, close the live scope gaps in Related Items and topbar search before any assistant reads through them. Second, build the AI service foundation (Slice 1b): one wrapper through which every model call passes, carrying the actor, organization, feature, and source record IDs; a per-organization policy for permitted providers and data categories, enforced at the wrapper; and usage and cost records. Add a guard test that fails when code calls the model outside the wrapper. Today the roughly 70 call sites cannot enforce a per-organization policy or attribute usage, so this is a prerequisite build, not only a decision (Section 9, item 8). It comes before Slice 4 and before any AI classification suggestion in Slice 2.

## 6. Data and service design

### Canonical identity and relationships

- Extend `applications` as the stable identity of an AI system; avoid a parallel `ai_systems` table with duplicated name, owner, BU, vendor, and status. Add an AI-specific profile keyed to application ID for purpose, autonomy, deployment context, risk tier rationale, model/service details, and review cadence. Confirm whether model components need their own versioned records after discovery; do not flatten several models into one text field if customer use cases require lineage. Write a field-ownership table before any schema work: `sentinel_aiia` already stores autonomy, data categories, deployment environment, third-party details, and stakeholders, so the profile should own the stable facts about the system, and the AIIA should reference the application and snapshot the values it assessed rather than ask for them again. Retire an application (`is_active = 0`) rather than deleting it once it has approvals or evidence; today's delete is a hard delete and would leave AIIA references dangling.
- Link an AI system to existing `data_assets`, `canonical_vendors`, `canonical_controls`, AIIA/DPIA/RoPA, ERM/ORM risks, GRID audits, ARIA policies, evidence items, and workflow instances. Use the existing `cross_module_links` table as storage for edges initially, but not as the policy: it has no scope, provenance, or status columns, and its create helper only checks module names, so validation and authorization move into the relationship service below. Preserve `sentinel_aiia.application_id` as the direct foreign-key path where it is already meaningful (it is probably empty today, so backfill by reviewed name match, never by guess). Add the stored edges the journeys assume: a process-to-application dependency, structured affected applications and vendors on BCM incidents, an application reference on AIMS assessments, and a mapping between ORM's AI control catalogue and `canonical_controls`.
- Define a canonical relationship vocabulary such as *uses data*, *provided by*, *assessed by*, *mitigated by*, *evidenced by*, *depends on*, and *affected by*. Each edge has source type/ID, target type/ID, org/BU access policy, provenance, creator, status, and date. Audit both creation and removal. Do not assume that a graph edge alone proves effectiveness or applicability. Start from the nine verbs `core/links.py` already allows (related, triggers, evidence_for, implements, mitigates, escalated_to, derived_from, audits, elevated_to): store each edge once, in one direction, with an active verb, and render the inverse label (for example “mitigated by”) from the incoming side instead of storing both. Its module list has no governance entry, so applications, data assets, and vendors need one rather than a second vocabulary.
- Put existence checks, tenant/BU/module authorization, deep-link resolution, and title summaries behind one relationship service. Audit legacy `cross_module_links` for dangling and out-of-scope references before using them in broad views. Use existing readiness diagnostics to surface broken edges. Seed the service from Evidence Vault's resolver (`_ENTITY_RESOLVERS`, `_target_scope_sql`, and `_visible_target` in `modules/evidence/routes.py`), the only one of the three registries that already checks scope and visibility and resolves URLs, and fold the Related Items and `core/links.py` registries into it. Say where an edge lives: `applications`, `data_assets`, `cross_module_links`, and `sentinel_aiia` have no `org_id` column or row-level-security policy (isolation rests on tenant schemas and module code), whereas `evidence_items` is a shared table with `org_id` and a policy. Back the service with a scope test matrix (users by entity types) that runs in CI and covers Related Items, search, and every workspace tab.

### Workflow and event contract

- The owning module emits a domain event after a successful transaction for material changes: AI system submitted/approved/changed, AIIA completed, evidence expired, control failed, vendor incident, breach declared, regulation accepted, and so on. Build on `core/events.py` instead of adding a second bus: it already persists each event with a status, a dedupe key, and an event ID that handlers use for idempotency. Close its three gaps: let `emit` write inside the caller's transaction (today it uses its own connection, so a crash between the source commit and the emit loses the event), add a sweeper job that retries `pending` and `failed` events with a retry cap and a dead-letter state (today failed handlers are only logged), and add the missing event types. Do not rely on in-request best-effort writes for critical actions.
- Event handlers update projections into existing My Work, Task Board, notifications, calendar, briefing, and impact explorer. Define one owner/status source for each action so a change in one view does not leave another stale. Track event ID, org, actor, source record/version, and processing result. Retry safely without generating duplicate tasks or messages.
- The approval service captures the assessed record version, required reviewers, decision, conditions, and source evidence manifest. Changes after approval trigger a scoped re-review rule, not silent status carryover.

### Search, evidence, and reporting

- Build on the Vault's permission-safe pagination and full-text work. Share a scoped search service across global search, record pickers, and AI retrieval. Search must return stable deep links, result type, freshness, and why matched.
- Create reproducible audit/board packs from selected records and versions. The pack lists scope, generation time, reviewer, included records, unresolved gaps, and source manifest. Re-opened findings or expired evidence should not retroactively mutate an exported snapshot.
- Report compliance as separate dimensions: requirement applicable, control implemented, control tested, evidence current, and reviewer accepted. A single percentage must show its denominator and rules; missing data is “unknown”, never “compliant”.

## 7. Delivery roadmap

Each slice should be independently reviewable. Work already in another plan keeps its own owner and acceptance gates.

| Slice | Deliverable | Dependencies and acceptance gate |
| --- | --- | --- |
| **0. Discovery and baseline** | Observe four reference journeys with representative users; inventory current routes/data, permissions, duplicate concepts, and existing open tasks. Define vocabulary, statuses, relationship types, and an anonymized query set. | Reconcile `PLAN-36` and Evidence Vault Phase 1a status. Produce journey maps and current-state measurements; no schema yet. |
| **1. Trust and navigation foundation** | Finish applicable stabilization and Vault scope/search gates; fix the Related Items and topbar search scope gaps and audit link create and remove; build the relationship service (seeded from the Vault resolver) and the scope test matrix; unify scoped deep links, entity summaries, link validation, and user-facing errors. | Same record/count/permission result from every entry point; no wrong-org/BU title, snippet, link, or existence signal; the matrix passes for every searchable and linkable entity type; keyboard and mobile route review. |
| **1b. AI service foundation** | One model-call wrapper (actor, organization, feature, source IDs), a per-organization provider and data-category policy enforced there, usage and cost records, and a guard against direct calls; migrate the existing call sites. | No call bypasses the wrapper; a disallowed provider or data category is refused before the call; usage is attributable per organization and feature. Can run beside Slice 1; blocks Slice 4 and any AI suggestion in Slice 2. |
| **2a. AI intake and inventory** | Field-ownership table (profile versus AIIA); AI profile keyed to `applications`; intake request and reviewer approval; duplicate check; retire instead of delete; decision on inventory read scope. | Two users cannot create unintended duplicates; staff submit without write access to `applications`; the AIIA references the application instead of re-asking; no AI suggestion yet. |
| **2b. Read-only AI-use workspace** | One workspace on the application with tabs built on scoped source adapters; links to AIIA, DPIA, risk, controls, vendor/data assets, and evidence; the missing stored edges added where the pilot needs them. Pilot with one controlled organization and 2–3 realistic use cases. | Every tab and “next step” reaches a valid permitted record; prefill provenance visible; no tab reveals a title, count, or ID the viewer could not open in its home module. |
| **2c. Link actions from the workspace** | Create and confirm links, and open the specialist record to continue, through the relationship service; unresolved legacy links go to readiness review. | No duplicate specialist records; every link records actor, source, and time; removals are audited. Approvals stay in Slice 3. |
| **3. Decisions and proactive work** | Attach existing workflow approvals, source-version snapshots, review triggers, and My Work/briefing projections to the pilot. Add impact explorer list; graph optional after list usability proof. | Submitted/approved/changed lifecycle is auditable; events retry without duplicate tasks; no unapproved change appears approved. |
| **4. Contextual AI** | Start with Find + Explain over scoped search. Add Prepare and Suggest only for selected workflows, with preview/accept feedback. | Requires Slice 1b and the Section 5 trust gates. Evaluation set checks citation resolution, unauthorized-result leakage, no-match behavior, factuality, user correction, latency, and cost. Human confirmation on writes. |
| **5. Operational intelligence** | Regulatory impact queue on existing Inbox/External Context, evaluation-result records, evidence freshness and reuse recommendations, incident impact walks, reviewed board/audit packs. | Each alert identifies its source and action owner; false positives reviewed; pack manifest reproduces exact source versions. |
| **6. Optional expansion** | AI app/model component registry, dataset lineage, AI literacy records, customer trust centre, expiring auditor share, and shadow-AI/LLM-gateway integrations where demand justifies them. | Separate product discovery, data-source and privacy model, operational support and security review before scope approval. |

## 8. Outcomes to measure

Collect a baseline in Slice 0; the figures below are *proposed acceptance targets*, not current results.

| Outcome | Proposed target / method |
| --- | --- |
| Start and resume work | At least 80% of pilot users can register an AI use case and locate their next action without guidance; test with realistic tasks, not a tour. |
| Reuse and navigation | A known policy/evidence/control can be found in under 30 seconds; at least 90% of agreed search questions contain the expected accessible record in the top five. |
| Connectedness | Every pilot AI system has a visible owner, lifecycle state, and its applicable linked assessments; all displayed relationship links resolve to a permitted target. |
| Work quality | No duplicate task for one triggering event; approval snapshots retain exact record/evidence versions; users can distinguish missing, expired, superseded, and reviewed proof. |
| Scope safety | The users-by-entity-types scope matrix runs in CI and passes for Related Items, global search, record pickers, and every workspace tab; a wrong-business-unit user gets no title, count, ID, or existence signal. |
| AI trust | Zero unauthorized titles/snippets/citations in scoped evaluations; every generated factual claim points to a resolvable source or is marked as a suggestion; correction/acceptance rates are recorded. |
| Performance and accessibility | Search and workspaces remain usable with 500 and 5,000 evidence items; check desktop/mobile, keyboard, screen reader, 200% zoom, and reduced motion. Set latency SLOs after measuring the VPS. |

## 9. Product decisions before build

1. Define what counts as an AI system, an AI use case, a model component, and an AI app so the registry does not split one asset across multiple names.
2. Decide which lifecycle state is authoritative when `applications`, AIIA, a workflow, and a policy each have their own status. Prefer a derived workspace status with named source states over overwriting specialist statuses.
3. Agree when an AIIA/DPIA is required and who may mark one not applicable. Keep legal and policy applicability reviewed; AI may flag candidate triggers only.
4. Set the org/BU visibility rule for shared evidence and links, including system-wide records and cross-BU users. Resolve the Vault plan's Phase 0 decisions before broad reuse.
5. Choose pilot organizations, reviewers, representative workflows, and non-sensitive evaluation data. Decide which model providers and data categories each organization permits for AI assistance (item 8 covers enforcement).
6. Agree the minimal evidence needed for “approved”, the meaning of approval with conditions, and which changes trigger re-review.
7. Agree the field-ownership table between the AI profile and the AIIA: which facts the profile owns, and which values the AIIA snapshots when it assesses.
8. Agree the per-organization AI policy: which providers and data categories are allowed, who administers it, and what happens to an AI feature when the policy forbids the call. This is built in Slice 1b, not only decided.
9. Agree who may submit an AI use, who reviews and promotes it into `applications`, and whether the application and data-asset inventory stays visible to every role across business units (it is today) or becomes business-unit scoped. The sensitive workspace tabs follow the business-unit rule either way.

## 10. Risks and constraints

- **Feature sprawl:** a new AI portal, task centre, evidence hub, regulatory feed, or control inventory would compete with existing modules. Each new surface must have one canonical owner and a clear navigation role.
- **False certainty:** attractive coverage scores can conceal missing, stale, or unreviewed proof. Show source, denominator, review state, and gaps. Do not let generated text mark an obligation satisfied.
- **Cross-scope leakage:** a graph or AI retrieval layer can expose another org/BU's titles and snippets even when the source page is protected. Scope at every read, count, relationship, cache, and export. This already happens in Related Items, topbar search, and the vendor cross-module profile (Section 2), so the foundation must be fixed before the graph or an assistant is built on it. Prove it with the CI scope matrix rather than by review.
- **Noise:** unfiltered external signals and duplicate reminders reduce trust. Watchlists, relevance rules, deduplication, ownership, and dismissal reasons are part of the feature, not later polish.
- **Migration:** historical application and link rows may be incomplete. Backfill only high-confidence matches; unresolved links appear in readiness review rather than being guessed.
- **Competitive inspiration:** borrow product patterns, not VerifyWise source code, copy, or branding. Its published repository uses BSL 1.1; per its licence page, the grant is for internal, non-production business use and production deployment needs a commercial licence, so treat its source as off limits and implement ThemisIQ code independently. Re-read the licence text before relying on this summary.

## 11. Reference material

- Feature-level build plans for this vision: [verifywise-features](verifywise-features/README.md) (nine briefs; each states its own gates).
- Existing ThemisIQ work: [PLAN-36](PLAN-36-themisiq-stabilization-and-product-improvements/task_plan.md), [Evidence Vault](../design/evidence-vault/PLAN.md), [cross-module links](PLAN-07-related-items-cross-module-linking.md), [unified controls](PLAN-05-governance-t12-unified-controls.md), [regulatory inbox](PLAN-13-drift-detection-regulatory-inbox.md).
- VerifyWise public documentation reviewed for inspiration: [intake](https://verifywise.ai/user-guide/ai-governance/intake-forms), [entity graph](https://verifywise.ai/user-guide/ai-governance/entity-graph), [approvals](https://verifywise.ai/user-guide/ai-governance/approval-workflows), [evidence](https://verifywise.ai/user-guide/ai-governance/evidence-collection), [LLM evaluations](https://verifywise.ai/user-guide/llm-evals/llm-evals-overview), [regulation impact](https://verifywise.ai/user-guide/regulations-tracker/settings), and [repository license](https://github.com/verifywise-ai/verifywise/blob/develop/LICENSE.md). Public descriptions are not a hands-on validation of every VerifyWise feature.

## Appendix A. Code review folded into this plan (2026-10-07)

Method: read the repository at HEAD (eec119f) plus the uncommitted Evidence Vault Phase 1a work, and ran one throwaway script against a fresh SQLite database kept outside the repository; nothing in the application was changed. “Reproduced” means that script showed it; “read” means the code was read but not run. PostgreSQL was not available, so anything that depends on PostgreSQL or on production data is unverified.

| # | Finding | Verified | Folded into |
| --- | --- | --- | --- |
| 1 | Related Items (`_LINKABLE`, `api_links_get`, `api_links_create`, `api_links_delete` in `modules/launcher/routes_platform.py`) returns another business unit's titles, answers for a record the caller cannot open, and lets create-then-read reveal title and existence for 10 entity kinds. No module check; create and remove are not audited. | Reproduced | Section 2 item 1; Section 5; Slice 1; Section 8; Section 10 |
| 2 | Topbar search (`api_global_search`) returns a unit B breach title to a unit A user while Sentinel's own list hides it. | Reproduced | Same |
| 3 | `get_cross_module_profile` (`core/vendor_link.py`) has no scope parameter and is reachable by any BCM user; it returns GRID audit findings and Sentinel AI assessment text. | Read | Section 2 item 1; Section 4 |
| 4 | Three linkable-type registries: Evidence Vault `_ENTITY_RESOLVERS` (19 keys, with scope and URL resolution), Related Items `_LINKABLE` (11, no scope), `core/links.py` (8 modules, 9 verbs, no governance entry). None has application, data asset, AIIA, AIMS assessment, or workflow instance. | Read | Section 2 item 2; Section 6 |
| 5 | `cross_module_links` has no org, scope, provenance, or status column; its create helper validates module names only. | Read | Section 6 |
| 6 | No process-to-application edge; `bcm_incidents.affected_systems` is free text; `aims_assessments` has no application reference; `ai_control_catalogue` is separate from `canonical_controls`. | Read | Section 2 item 3; Journey C; Section 6 |
| 7 | `sentinel_aiia` stores system name, autonomy, data categories, deployment, third-party details, and stakeholders. `application_id` has no foreign key and no screen sets it (only the data service's field list names it). | Read | Section 2 item 4; Section 6; Section 9 item 7 |
| 8 | `governance.entities.manage` is limited to five roles while `governance.entities.view` is every role; `list_applications` filters by a client-chosen `bu_id`, not the caller's scope; no duplicate check; hard delete. | Read | Section 2 item 5; Journey A; Section 9 item 9 |
| 9 | `core/events.py` persists events (status, dedupe key, event ID) but writes on its own connection, only logs failed handlers, never retries `failed` or `pending`, and has no event types for AI system, AIIA, evidence expiry, vendor incident, or regulation. | Read | Section 6 |
| 10 | About 70 references in 15 files call `create_message` or `_call_ai`; the signature has no actor, organization, or feature; the only usage log is `aria_ask_log`; no per-organization AI policy exists. | Read and searched | Section 5; Slice 1b; Section 9 item 8 |
| 11 | Evidence Vault Phase 1a is built and verified locally, not committed, PostgreSQL lane not run. | Read | Section 2 |
| 12 | VerifyWise licence page: BSL 1.1, internal non-production business use, production needs a commercial licence. | Read through a web fetch summary; re-read the text before relying on it | Section 10 |

Confirmed accurate and left unchanged: `applications`, `data_assets`, canonical vendors (the Sentinel, GRID, and BCM vendor tables all link through `canonical_id`) and canonical controls; Sentinel AIIA; the ORM AI control catalogue and AIMS tables; workflow instances (generic entity references and `org_id`); the Regulatory Inbox (`regulatory_updates`); ERM External Context; My Work (it already lists workflow actions and ARIA approvals, so a “Needs my decision” card is feasible); and every linked plan file.

Not verified: PostgreSQL behavior; production data, for example how many AIIA rows reference an application or whether any tenant has several business units; and VerifyWise behavior beyond its public pages.
