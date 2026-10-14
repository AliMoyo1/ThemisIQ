# 04. Platform truth, navigation and reporting

**Status:** Proposed shared product contract and repair plan. No application change is made here. Read with the [programme index](README.md), [module journeys](03-specialist-module-journeys.md), [Vault plan](02-evidence-vault-and-assurance.md), [PLAN-37](../PLAN-37-connected-compliance-experience.md), and [delivery gates](05-delivery-and-acceptance.md).

## 1. The shared experience

ThemisIQ should feel like one connected system even though each module owns different records. A person sees the same record title, owner, scope and state in My Work, related items, search, module dashboards, Vault links and reports. A link opens the source record with a useful return path. One source action closes the corresponding task and updates its projections. Derived views do not become new competing stores of decisions.

The first screen for a specialist should answer **what needs action today, what changed, what lacks proof, and what can be reported**. A manager sees trends and bottlenecks. A board view emphasizes exposure, decisions, exceptions and assurance limits. Every number is clickable to a filtered, authorized list of the records that produced it. If that list cannot be produced, the number should not appear as a precise KPI.

## 2. Metric and dashboard contract

Define a metric registry before adding visual cards. Each metric has a stable key, plain-language definition, owning service, row eligibility, denominator, date window, time zone, business-unit and role scope, refresh method, last successful source read, exclusions and drilldown query. Store its query/definition version with report snapshots. Source modules publish permitted records or aggregate queries through a shared scoped read contract; the dashboard does not scrape rendered HTML or rely on client constants.

| State | Display behavior | Example |
| --- | --- | --- |
| Measured zero | Show `0`, the window, and the eligible denominator | Zero open breaches from an available Sentinel source. |
| No baseline | Show `Not measured` and a setup action | An organization has no defined continuity exercise frequency. |
| Unavailable | Show `Unavailable` and source failure time; retain last good value only as explicitly dated history | Sentinel API call fails. |
| Partial | Show `Partial`, contributing modules and omitted modules | Cross-module board view while one source is unavailable. |
| Stale | Show prior value with its as-of date and next refresh action | A cached risk score outlives its freshness window. |
| Hidden by permission | Omit source detail; do not leak count or existence | A business unit outside the viewer's scope. |

The Command Centre presents personal work first, then organization portfolio. Module dashboards present their own actionable queue and source-backed trend. Role preset changes layout, not authorization. A custom dashboard stores selected cards and filters, not a privileged snapshot shared with a lower-role user. Chart axes, denominator, cohort and exclusions appear in accessible text. Time comparisons use the same population and rule version or disclose that they differ.

### Known truth repairs from reviewed source

1. Replace BCM and Sentinel example-data fallbacks after failed reads with unavailable or partial states. Sentinel currently has hardcoded RoPA coverage/total activity values even after a successful request; replace them with a defined source and denominator.
2. Separate Vault `linked`, `current proof` and `accepted as sufficient` measures. Its current coverage query can include expired or superseded items, and its metadata confidence is not assurance.
3. ARIA's dashboard Generate Report success toast is timer based. Connect it to a real report job/output or remove the action until supported.
4. BCM dashboard report requests must use supported shared report types; implement and register those types with scoped queries or disable the unsupported buttons.
5. Saved report runs need a frozen authorized output. In the reviewed route a non-super-admin read can recompute current data, so a historical run may change when its source changes. Preserve the snapshot and verify access to the snapshot separately.

These repairs should precede any premium board dashboard claim. The findings refer to source code, and a release gate must reproduce and verify each against the target environment.

## 3. My Work, notifications and actions

Keep the existing My Work service as the shared action projection. Every actionable item has a source record ID, canonical action kind, responsible role or person, due date or trigger, priority basis, current source state and deep link. The projection may add display metadata and filters but cannot close or approve an item itself. Deduplicate the same underlying action across module, notification and Command Centre views while retaining distinct obligations where their legal or workflow owner differs.

Design views for **Mine**, **My team's**, **Waiting on others**, **Overdue**, **Due soon**, and **Recently changed**. A governance specialist can group by AI use, vendor, process, audit or business unit. Notifications should summarize the precise change and route to the source action; digest and quieting preferences should not suppress legally critical clocks. A completed, withdrawn or reassigned action must disappear or update promptly. A failed event delivery is visible to operators and can be retried idempotently without generating a duplicate task.

Email reuses these actions and role checks rather than adding a parallel task lifecycle. See [06 Email notifications and delivery](06-email-notifications-and-delivery.md) for recipient rules, provider outcomes, urgent fallback and templates.

## 4. Search and related items

Offer a single global search entry that returns authorized entity, case, policy, audit, risk, event, AI use and evidence results with type, owning module, business unit, status, date and a short permitted snippet. Search result counts obey the same scope as the rows. The regular search path works without AI. Advanced search adds scoped facets, saved searches and an explicit **Search this case** mode.

AI-assisted navigation may answer questions such as “Which current evidence supports this control?” or “Why is this AI use awaiting approval?” It retrieves only records the current user may read at retrieval, citation generation and prompt construction. It cites exact source/version, date and access-controlled link; it states when evidence is missing or stale. No answer is allowed to infer the existence of a hidden record from totals or absent citations. The system should never send full Vault documents or external form responses to a model merely to power a navigation hint. Keep a non-AI search and filters for every journey.

The related-item view should use the existing relationship service and support a compact graph or list. It distinguishes recorded, suggested and disputed relationships. An AI suggestion needs a human confirmation and record of its source. A vendor alias or similar title cannot cause an automatic identity merge. Filtering a parent case must not show inaccessible neighboring nodes or their count.

## 5. Reports and viewpoints

Provide four report presets over the same scoped definitions: **case** (what happened and proof), **specialist portfolio** (queue, gaps, decisions), **management** (trend, aging, accountable owners), and **board** (material exposure, assurance, exceptions and explicit limitations). Presets are templates, not new stores. Every report includes organization, business-unit scope, selected period, generation time, user, definition versions, source-system manifest, source freshness, exclusions, incomplete data and decision status. Export should preserve labels and citations in a readable layout, with accessible tables as well as charts.

### Snapshot lifecycle

1. User previews a scoped query with a definition version and selected filters. Display the included record count without exposing inaccessible records.
2. The run freezes permitted input identifiers and versions, aggregate values, chart series, narrative text, source availability, selected scope, actor and generation time. Hash the canonical snapshot or file where needed for audit integrity.
3. Authorization to open/download a saved run is checked against its recipient and classification policy. A user is never given a freshly recomputed, wider or narrower result under the label of a historic run. If access is revoked, hide the saved output and retain an auditable denial.
4. Re-running creates a new run linked to the earlier one with a change summary; it does not edit the earlier run. AI narrative is draft text with model/prompt policy version, citations and reviewer approval state.
5. Generation, export, sharing, expiry, revocation and deletion follow retention rules. External response packs and auditor packs keep their narrower recipient controls.

Define separate measures for framework mapping, implementation, current proof, reviewed assurance and certification. A bar cannot silently mix those meanings. Executive summaries prioritize decisions and limitations over attractive but unsupported percentages.

## 6. AI assistance as a governed platform service

The existing AI call policy is the common gate for all module assistants. Each use case declares task, source record classes, allowed provider/model, input minimization, output storage/retention, logging, user role, human approval and fallback. For example, a DPIA draft may read the confirmed processing record and cited policy versions; an external context signal may read approved public sources and relevant internal risk metadata; a Vault navigation hint may read authorized metadata and approved extracts. The same guard applies to imported external form content and to policy chat.

Prefer equations for clocks, status, thresholds, evidence freshness, workflow eligibility and simple calculations. Use AI to summarize, map candidates, draft questions, compare changes and explain signals, with citations and visible uncertainty. It may not make a legal applicability decision, accept risk, approve an AI use, close an audit finding, declare proof sufficient, sign a report or override an owner. A human reviewer can inspect the underlying facts and record the decision. Provider failure, disallowed use or unavailable retrieval falls back to the deterministic workflow.

Support evaluation of assistant usefulness and safety: citation validity, retrieval scope, answer abstention, inappropriate legal certainty, draft edit rate, cost and latency. Prompt injection in uploaded files or external context is treated as untrusted content, never instructions. Access events and AI calls are auditable without placing sensitive content into routine logs.

## 7. Security and operational quality

- One authorization contract applies at SQL/query, API, projection, search chunk, citation, prompt, graph edge, notification, export and cached report. A wrong-unit user sees no title, count, ID or existence signal. Shared organization-wide records and `NULL` business-unit semantics follow the existing policy, not an ad hoc dashboard shortcut.
- Mutations remain in source modules with capability checks, CSRF protections, audit events, optimistic version checks where needed and idempotency for import/event retry. A visible action is not evidence of permission to call its API.
- Heavy searches and dashboards have pagination, bounded time ranges and indexes appropriate for 500 to 5,000 Vault items and growing event histories. Avoid rendering all result cards or loading all files into AI context.
- A module failure does not break the Command Centre; the response carries per-source availability and no fabricated substitute. Health and data freshness are different indicators.
- Accessibility and mobile behavior are requirements: keyboard access, focus state, readable chart alternatives, labels, clear loading/error states and reduced-motion support.

## 8. Other platform functions and ownership

The reviewed launcher routes and module directory include projects, frameworks, workflows, task board, calendar/reminders, analytics, readiness, saved views, evidence campaigns, user administration, API keys, webhooks, audit log, bulk import/export and a trainer endpoint. These functions need explicit roles in the connected experience. This is a proposed journey review, not a claim that every endpoint has been security audited.

| Function | Proposed improvement and source contract | Acceptance question |
| --- | --- | --- |
| Compliance projects and framework catalogue | Projects group an assurance objective, selected framework edition, owners, deadlines and source assessments. Frameworks keep provenance and edition; activate or map them without copying control text into a project-specific source of truth. | Can a lead navigate project to live control, review, evidence and report, while a previous report retains its earlier edition? |
| Readiness | Treat readiness as a calculated, scoped work view over applicable controls, proof, findings and open actions. Declare denominator and exclusions; do not treat a framework mapping or uploaded document as completed implementation. | Can a user drill each gap to its owning control or review and reconcile every readiness count? |
| Workflows and SLA definitions | Keep the existing workflow/decision and SLA engines as execution tools. A source module creates a typed action with eligibility, owner, due rule and idempotency key. A workflow step cannot bypass its source module's approval or legal rule. | Does completing or delegating a workflow step update exactly one source action and preserve history and role separation? |
| Task board, calendar and reminders | Display the same canonical obligations as My Work. Manual tasks have their own source identity; imported module actions retain theirs. Calendar shows due dates and change history; reminder delivery is deduplicated and subject to escalation policy. | Is one overdue review counted once, with a single responsible owner and a correct deep link from all three views? |
| Saved views and analytics | Save filter/sort/column choices, time window and metric definition for the requesting user's scope. Do not save a privileged result set for later unauthorized viewers. Analytics snapshots state their source availability and refresh time. | Can permissions change without exposing old results, and do analytics and source lists reconcile? |
| Evidence campaigns | Use the existing request/collection lifecycle for missing proof. Connect campaigns to Vault claim and source-module reviewer; avoid duplicate generic tasks or reminder schedules. | Does a requested artifact land in the right claim and wait for acceptance by the right reviewer? |
| Bulk import and export | Apply per-entity schemas, preview, row error reporting, access checks and safe retry. Exports state scope and as-of time. External Forms import is a specialist AI Governance adapter to this pattern, not an unrestricted generic import. | Can malformed or cross-unit rows be rejected before partial writes, and can a permitted export be reconciled to visible rows? |
| User and role administration | Provide clear effective-capability and business-unit previews before assignment. Changes take effect across search, packs and caches; preserve approval separation. | Can an administrator see the exact access effect without exposing another tenant's data, and does revocation remove derived access? |
| API keys and webhooks | Scope keys to explicit capabilities and tenant, rotate/revoke with audit, sign outbound events, bound payloads and retry idempotently. Do not put report files or sensitive case text in a generic event. | Can a revoked key no longer read a derived view, and can a replayed webhook be safely identified? |
| Audit log and timeline | Show actor, source, action, version and correlation across modules without leaking private payloads. Keep the log immutable under the existing retention policy and permit a scoped case timeline. | Can a specialist reconstruct who imported, reviewed, decided, exported and recorded an external response? |
| Trainer and staff-facing learning routes | Inventory callers and data before moving AI literacy to another project. Keep any operational trainer aid distinct from employee course assignment and completion. | Can learner navigation be removed without losing old attestations or creating an undisclosed duplicate training workflow? |

Before implementation, trace every function's current readers, writers and permissions to the source schema. Record functions that are unused or unsafe as candidates for deprecation rather than leaving misleading controls visible. The [delivery plan](05-delivery-and-acceptance.md) puts source truth and authorization ahead of cosmetic changes.

## 9. Acceptance scenarios

1. A specialist opens a board card, sees its definition and as-of state, clicks to exactly the authorized source rows, exports a report, and later opens the same frozen numbers despite subsequent source changes.
2. A Sentinel source fails. The privacy cards and cross-module totals show unavailable/partial; no sample or hardcoded value appears. Other modules still work.
3. An ARIA report button and every BCM report action either return a valid scoped report job/file or are absent with a clear reason. No timer-based success message remains.
4. A wrong-unit user cannot infer a hidden AI use, breach, evidence item or vendor from counts, suggestions, related edges, snippets, notifications or AI answer citations.
5. A reviewer can trace a predictive risk or coverage number to its source records, eligibility rule, period and freshness and can dispute it without modifying the source by editing a chart.
6. A user with AI disabled can complete intake, find evidence, review a case, make an authorized decision and create an accurate report.
