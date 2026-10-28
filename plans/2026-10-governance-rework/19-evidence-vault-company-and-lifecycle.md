# 19. Evidence Vault: company navigation, filing and assurance at scale

**Status:** Proposed implementation plan, 2026-10-28, revised the same day after review (see section 13). First release is V0 plus a minimal V1; V2 to V5 stay as direction and are not committed. No behavior in this document is claimed to be built, tested or deployed. This extends [02 Evidence Vault and assurance](02-evidence-vault-and-assurance.md), the [Vault product plan](../../design/evidence-vault/PLAN.md), and [18 existing-policy intake](18-policy-intake-and-document-composition.md). It does not replace their proof, policy-approval or scope contracts.

## 1. Outcome and current baseline

**Scope of the first release.** Finding a subsidiary's policies by company is mostly an inventory (V0) and a small company filter built from the existing business-unit tree (minimal V1). Ownership is metadata only: nothing in V1 changes `business_unit_id`, so no one gains or loses access. The applicability relation, the legal-entity catalogue, the staging queue and the AI gates are deferred until V0 shows they are needed.

A specialist at a parent company can move from **Econet Group**, **OmniContact** or **EcoCash** to an authorized document, its exact current version, its source and the claims it supports in a few actions. A subsidiary specialist sees only authorized material. The same Vault artifact may appear in a company view, an audit, an incident, a framework register and an evidence request without another file copy.

Verified in the reviewed checkout: the Vault already has paginated scoped results, virtual folders by linked record/type, saved views, card/list display, detail inspector, exact-hash duplicate detection, version history, pending/accepted link reviews, Find evidence, generated-record semantic deduplication and report-run sign-off/retention infrastructure elsewhere. The default search checks metadata and optionally a version-bound text index. The text index needs explicit Linux sandbox and operator opt-in; a disabled index must be shown as unavailable, not as evidence that no document contains the search term. The upload form is still single-file and has no company selector. The item list has no company facet. Existing `evidence_items.business_unit_id` is an authorization field; its null value currently means organization-wide visibility. Source filenames mentioning a subsidiary are not ownership evidence.

**Exposure finding (to be confirmed by V0).** Because a null unit means organization-wide, any subsidiary-confidential document that was filed without a unit is visible today to every business unit of the tenant. The rest of this plan guards against *widening* access; this is the opposite risk and it already exists. V0 therefore also flags null-unit items whose name, source record or linked record suggests one subsidiary, as candidates for **narrowing**. Narrowing is the safe direction and is a security finding in its own right, handled by a specialist review before any change.

The screenshot shows several apparently subsidiary-named policies in one flat result set. It does not prove whether those files belong to a business unit in the parent tenant or to a separate tenant. Inventory this before changing ownership or visibility.

## 2. Product decisions and vocabulary

| Concept | Meaning and rule |
| --- | --- |
| Organization/tenant | Hard data boundary. A parent login does not acquire another tenant's documents by name or corporate relationship. |
| Owning company | The entity accountable for the artifact. For the first release it is derived from the business-unit tree (the company ancestor of the item's unit) and is **metadata only**: V1 never writes `business_unit_id`. A reviewer's explicit confirmation is recorded separately. |
| Access unit | Existing `business_unit_id` authorization scope. Semantic applicability never widens access. |
| Applicable companies | Companies for which a group-owned policy or proof is relevant. **Deferred** until V0 shows that group policies really need several applicable companies; until then a group-owned policy is found by the Group-wide view. |
| Group-wide | Explicitly confirmed parent-owned record with organization-wide scope. Do not infer this from a legacy null unit. |
| Ownership unconfirmed | A legacy or new artifact whose owner company cannot be established. Its current access remains unchanged while a permitted specialist reviews it. |
| Artifact family/version | One logical document and immutable bytes or generated snapshot per version. **The family already exists:** versions are `evidence_items` rows chained by `parent_id` and `version`, and the family is identified by the root item (the row whose `parent_id` is null). There is no `artifact_family_id` column and none is to be created; do not add a parallel table, which would be the second document repository this plan forbids. The UI normally shows the current row of each family. |
| Link and verdict | A proposed/confirmed relationship to an authorized target; the target reviewer decides whether that exact version proves the claim for the relevant period. |

**Gate: open decision 1 comes first.** If EcoCash and OmniContact are separate tenants rather than business units of one tenant, the first release has a different shape (sharing or federation, not a company facet). Resolve it, from the real records, before any V1 design work starts.

**First release boundary:** company grouping within one tenant and its existing authorized business-unit hierarchy. If subsidiaries are separate tenant organizations, build an explicit sharing/federation design with bilateral grants, source-tenant enforcement, per-recipient permission checks, revocation, logging and pack rules before showing cross-tenant rollups. Do not relax `org_id` predicates or copy hidden titles/counts into the parent's tenant.

**Phase 0 decision:** confirm whether the existing business-unit tree represents legal companies or operational departments. If it does, resolve each unit to a stable company ancestor. If it does not, a tenant-scoped legal-entity catalogue and a unit-to-entity mapping become necessary; that is the only point at which the catalogue is built, and ownership stays separate from access. Avoid using a free-text company label or filename as a security principal.

## 3. Information architecture and screen contract

### Main library

1. Header: Evidence Vault, one large search field, **Add evidence**, and **Find evidence**. Preserve the current list/card toggle.
2. Entry switcher: **By company**, **By work**, **Needs attention**, **All documents**. This is navigation state, not four stores. Restore the user's last view when returning.
3. By company: cards for each visible company plus **Group-wide** and **Ownership unconfirmed**. Show authorized current-family count and separately labeled counts for needs filing, review due and pending verdicts. A zero is displayed only if the corresponding source query succeeded. A card opens the list with a company facet; nested business units appear in a light hierarchy or searchable switcher, not an endlessly deep folder tree.
4. By work: reuse Audits, Incidents, Privacy records, Continuity plans, AI assessments, Reports, Policies and Generated records. Within a company, the same work view is available. Breadcrumb: `All companies / EcoCash / Audits / Audit 42`. Each record folder applies source-module permissions.
5. Needs attention: **My filing**, **My reviews**, **Renewals**, **Requests**, **Ownership unconfirmed**, **Index failures**. Show a count, responsible person/team, age and next action. Keep archived and superseded versions reachable through explicit history views.
6. Results toolbar: company, linked module/record, framework/control, category, owner, period covered, link verdict, freshness, status and sort. Active chips can be removed individually or cleared together. Saved views store these query definitions; they never store copies of files or grant access.
7. Results list defaults to compact rows with full title on focus/hover, owning company, applicable-company indicator, source, current version, period, linked claims, review due and plain-language state. Keep the premium folder cards for browsing and a card result view for images. No truncation that hides the only distinguishing part of a document name.
8. Opening the inspector preserves search, active facets, selected row, page and scroll. Back/close returns to the same place. Responsive layout uses an inline side panel on wide screens and a full-screen panel on narrow screens.

Every company card, work badge, saved-view total, search result and pagination total must be derived from the same authorized scope as the underlying list. Clicking a number must open precisely the rows counted. Do not expose an inaccessible company's name, count or existence through autocomplete, search latency or empty-state wording.

### Empty and failure states

- **No files in this company:** offer upload or a permitted evidence request.
- **No matches with these filters:** show applied chips and a one-click broaden action, without silently clearing the company.
- **No access:** use the normal masked response for a direct record or company ID; never show a partial title.
- **Text index off/failed:** metadata search remains available and the UI says which uploaded formats are not searchable inside. No false `0 results in contents` claim.
- **Source module unavailable:** show unavailable for its linked-record count, not zero.

## 4. Ownership data and migration

Keep `evidence_items.org_id` and `business_unit_id` as the existing security scope. Add an explicit, tenant-scoped ownership confirmation state and reviewer audit fields to the current artifact family. If a legal-entity catalogue is needed, store `owning_entity_id` as semantic metadata with a checked mapping to the allowed access unit. If an applicability relationship is later approved (deferred, see section 9), key it to the family root `evidence_items.id`, with `company_id`, reason, status, actor and timestamp; it never authorizes downloads. A source record's unit is inherited when filing from a module. A user filing an unlinked item selects only an authorized unit; a group-wide choice requires the corresponding capability and an explicit confirmation.

Before migration, create an inventory by tenant, current unit, linked source record, source-module unit, title-derived suggestion, file hash and version family. Classify as confirmed, likely match or ambiguous. Suggestions from names such as `EcoCash` are review hints only. Legacy null-unit rows begin **Ownership unconfirmed** unless an authoritative source establishes group-wide ownership. Because null is the default, most legacy items are expected to land there, so V0 **sizes the queue** (counts by tenant, unit, document type and age) before V1 is designed, and the bulk **confirm group-wide** path, with preview, per-row failures, reason and a reversible audit trail, ships **with V1**, not later. Otherwise the queue is unusable on day one. Do not silently change their current visibility. Bulk confirmation requires a preview, per-row failures, reason, actor and reversible audit trail. Reassignment that would change access must recheck existing links, saved packs, search-index scope, generated records and author/reviewer permissions; sensitive items need specialist review before any broadening. Do not move or delete bytes to create company views.

If a company later moves in the hierarchy, preserve stable entity IDs and recalculate visibility and counts transactionally. Do not bind provenance to a mutable company name. Maintain a crosswalk for any legacy GRID/BCM or ARIA policy copies before replacing readers.

## 5. Guided intake and filing

Create a staging queue that accepts multiple permitted files and exposes each file's state: received, validating, extracting, suggested, needs review, filed, duplicate, failed or quarantined. The original remains intact until the specialist commits an authorized filing choice. The queue can be resumed after a browser refresh and has an explicit discard action. Per-file errors do not discard other files.

1. **Preflight:** stream and bound upload size and total batch size; validate actual format, filename, archive expansion and malware policy; hash bytes in the correct tenant scope. Do not execute active document content or fetch URLs embedded in it.
2. **Extract:** use the existing isolated worker for permitted formats. Record source hash, parser version, page/section spans and extraction status. If extraction fails, allow metadata-only filing and show the failure. OCR for images or scans is a separate, bounded worker gate; no third-party OCR by default.
3. **Suggest:** infer title, type, version, owner, dates, company and candidate framework/record links from the visible file and current tenant catalogues. Show the exact source passage or deterministic rule behind each suggestion, confidence/uncertainty and a blank value when unverifiable. Do not infer company from author alone. Reuse ARIA's existing-policy intake suggestions rather than building a second policy parser.
4. **Resolve identity:** exact hash offers **Use existing** and a new link. Similar title/content offers **Potential revision**, with source/version comparison. A changed document is a new immutable version, never an overwrite. The existing generated-record path already avoids repeat generations and keeps current plus two prior copies prominent; preserve that rule, while retention and legal hold govern older bytes.
5. **Review and file:** confirm owner company and access unit, applicable companies, sensitivity, period, review due, expiry, source, owner person and candidate target links. Minimal required fields depend on document type. A proposal never enters approved coverage before the appropriate target reviewer accepts it. A successfully staged but unfiled item belongs in a visible queue, not an unexplained Vault card.

Support bulk confirmation only for fields genuinely shared across the selected files; never stamp one company, classification or reviewer verdict onto unrelated documents by accident. Provide undo/review for metadata edits, not destructive byte rollback.

## 6. Search, AI and item inspection

Search title, filename, controlled reference, owner, confirmed company, linked target, framework/control and permitted indexed text. Prefer exact reference/name matches, then metadata, then text matches. Show **why matched** and source/version/page or section. Use stable pagination and an authorized count query; measure indexes and PostgreSQL search plans before adopting semantic retrieval. Preserve a non-AI path at every stage.

Find evidence may translate a request into editable filters and return scoped candidates. The next AI gate may answer questions over document passages only after item and source-record authorization, with exact version/page citations, classification and organization AI-policy checks, prompt-injection handling and an explicit `I cannot verify this from accessible records` result. AI may suggest filing, ownership or links; it cannot assign access, accept proof, sign off an audit or present a policy as implemented. Provider use follows the existing per-organization policy and cost controls. Avoid logging raw personal search text unnecessarily.

Inspector order: preview/source deep link; owning and applicable companies; current status, version and period; linked claims with independent verdicts and reasons; owner and renewal; version comparison and impact; source/hash/integrity; activity; candidate suggestions. Generated source records show their generating event rather than `0 B` or a nonexistent original. If preview is restricted or fails, preserve authorized metadata and offer the safe original download where allowed. A new version proposes carry-forward links and resets their review; the previous acceptance stays attributed to the old version.

Use a visible **proof ladder**: Unfiled, Linked awaiting review, Accepted for this claim and period, Returned, Expired, Superseded, Archived. The same artifact can have different verdicts for different controls. Keep metadata completeness or integrity checks separate from assurance so a hash, link count or extraction success never becomes a compliance score.

## 7. Work, cross-module use and outputs

| Consumer | Vault connection and module-owned decision |
| --- | --- |
| ARIA and Governance | Published policy version and framework/control mapping reference exact Vault versions. ARIA approves policy content; control operation still needs its own proof. |
| GRID | An audit sees current candidate evidence and the auditor's acceptance for its test. An accepted link in ARIA does not approve an audit test. |
| BCM | Plan, exercise and incident records attach the canonical file; BCM keeps plan/exercise approvals. |
| Sentinel | DPIA, breach and DSR attachments inherit case permission and classification in every search, preview, export and AI path. |
| ERM, ORM and AI Governance | Treatment, event closure, model evaluation, oversight and decision packs cite the exact version and reviewer outcome. |
| Platform reports and My Work | Work items and exports deep-link to the scoped source; a metric can drill into the exact authorized set it counted. |

An evidence request starts from the source record with an assignee, due date, scope and reviewer. Its progress appears in the Vault work queue and My Work without a duplicate reminder stream. The owner can supply an existing current artifact or upload a version. Reminders and escalations follow the shared notification service; email remains optional until sender cutover. Failed delivery does not complete work.

For an auditor, select framework, company/unit, audit or period, and an as-of time. Produce a **document control/evidence register** containing all authorized in-scope rows, the precise artifact/version ID, title, owner, source, period, linked requirement, verdict, reviewer/date, gaps and exceptions. Offer complete workbook plus a readable PDF/HTML summary; pagination in the UI must never truncate the export. Before issue, show missing proof, superseded/expired versions, unreviewed links and sensitive items requiring redaction. Reuse platform report-run sign-off, sharing and tenant-configurable retention where the saved report is the record. Freeze a manifest with hashes, source IDs, permission/redaction decisions and as-of timestamp so reopening an issued pack does not substitute the latest version. External sharing is explicitly scoped, expiring, logged and revocable; no public link by default.

## 8. Security, retention and operational rules

- Centralize visibility across list, folder/company count, search, snippet, preview, download, duplicate hint, link target, AI context and export. Enforce tenant, business-unit, module/record capability and classification before ranking or formatting. RLS is additional protection. Use masked 404 for foreign direct IDs.
- Permission changes, archive, redaction and deletion must invalidate or remove current text-index snippets, previews, thumbnails, search caches and AI retrieval promptly. Preserve immutable audit history and held exports according to tenant policy. Avoid placing sensitive queries in URL logs where a POST search is appropriate.
- Retention defaults are product starting points, not asserted legal periods. Tenant administrators set permitted periods, holds and reviewers; the system records the basis and shows a review queue before any purge. Artifact bytes, versions, extracted text, previews, indexes, report manifests and generated copies each need a documented retention relationship. A legal hold stops purge.
- Constrain worker time, memory, extraction size, nested archives and network. Quarantine suspicious files and show a retriable status. Worker accounts need no broad database or provider credential access. No new package or external processing service is implied by this plan.
- Audit upload, company assignment/change, link proposal, verdict, version, preview/download where required, pack issue/share/revoke and retention action. Audit metadata should avoid unnecessary file content.
- Preserve keyboard navigation, readable text at 200% zoom, focus management for the inspector, reduced motion, mobile touch targets and a usable table at narrow widths. Premium folder cards can remain visual, but task completion must not depend on animation or hover.

## 9. Delivery slices and dependencies

| Slice | Build | Dependencies and completion gate |
| --- | --- | --- |
| V0 Inventory and decisions | Map real tenant/business-unit/company structure, legacy null ownership, existing ARIA/GRID/BCM copies, current file/index settings and report authority. Size the Ownership unconfirmed queue. Flag null-unit items that look subsidiary-specific as narrowing candidates (the exposure finding in section 1). Record the first-release company mapping and answer open decision 1. | Read-only inventory and specialist sign-off; no data mutation. |
| V1 Company browse (minimal) | A company facet and counts built from the existing business-unit tree; Group-wide and Unconfirmed views; explicit ownership confirmation with the bulk confirm path and preview; company breadcrumb and filter chips; saved-view schema update. **Never changes `business_unit_id`.** | Same scope query across counts/list; two-tenant and sibling-unit non-disclosure tests; the confirm path is reversible. |
| V2 Intake | Staging queue, batch validation/extraction, evidence-backed suggestions, exact duplicate/use-existing/new-version choices, owner/applicability review. Reuse ARIA intake and existing version logic. | Files remain intact on partial failure; unauthorized company/target rejected before mutation; malformed input tested. |
| V3 Find and inspect | Link-aware search, exact version/page snippets where indexing is enabled, inspector ordering, preview, proof ladder, version impact and mobile/keyboard flow. | Target-specific verdict tests, index-off/worker-failure tests, browser review at 500+ records. |
| V4 Work and reports | Consolidated filing/review/renewal queue, requests, complete register, frozen pack manifest, sign-off/share/retention integration. | Export row count equals scoped query, issued pack reproducible, sensitive omissions documented. |
| V5 Controlled intelligence | Scoped candidate ranking and source-cited answers after privacy review and retrieval quality measurement. | Wrong-unit/tenant adversarial tests, prompt-injection tests, provider-off fallback, human review gates. |

Likely code seams: `modules/evidence/{scope,routes,vault_views,proof,indexer,inspector,generated_records}.py`, `templates/evidence_index.html`, the shared saved-view schema, entity-scope and relationship services, ARIA policy intake, `modules/launcher/routes_reports.py`, plus focused SQLite, browser and disposable PostgreSQL tests. Keep one canonical implementation of scope and proof state; do not create a second document repository or acceptance model.

## 10. Acceptance and rollout

1. A parent user can find an EcoCash policy by company, type, framework and period; closing its inspector returns to the same row and filters. A subsidiary user cannot infer sibling or separate-tenant documents from names, counts, snippets, suggestions, duplicate warnings, packs or AI.
2. A group-wide policy appears once in canonical storage, under its owner and relevant applicable-company views. A subsidiary view never widens access because of applicability. Historical ambiguous files remain visible only under their preexisting access until reviewed.
3. Fifty mixed files can be staged with per-file results. An exact duplicate reuses the authorized artifact; a revision creates an immutable version and pending link reviews; failed extraction leaves a metadata-only route. No accepted verdict is silently inherited.
4. A reviewer can distinguish linked, current, accepted, expired and superseded proof for each target and period. A control score changes only through its documented target-specific review rule.
5. At 500 and 5,000 mixed files, measure p95 scoped metadata search under one second and known-item discovery under 30 seconds in the target environment. Report actual measurements, not estimates. Check keyboard, narrow screen, 200% zoom and reduced motion.
6. A framework export includes **every** authorized detailed row and freezes exact versions, hashes, verdicts, scope, exceptions and redactions. The workbook is complete even when a PDF chooses summary layout. Reopening after a new version produces the original manifest and permitted bytes.
7. A deactivated company, archived item, revoked share, denied case or changed business-unit membership is removed from current list/search/snippets/AI and returns a masked direct lookup while authorized held audit records remain reproducible.

V2 to V5 are not committed by this plan: each is re-planned after V1 is in use and V0 shows the need.

Release behind a tenant feature flag, beginning with a synthetic group and subsidiary pilot. Run read-only inventory, schema migration dry run and backup/restore check; migrate ownership metadata in small auditable batches; compare counts and hashes before and after; run focused, browser, security and disposable PostgreSQL tests; review a real specialist's filing and audit-pack journey. On failure, turn off the new view and intake, keep old bytes/links and restore the prior reader. Do not treat an old database backup as an automatic rollback after new records have been accepted. Production enablement needs a named owner for ownership decisions, an auditor to check the register, and a privacy reviewer for sensitive-case search/export.

## 11. Open decisions

1. **Decide first; it changes the shape of everything else.** Are Econet Group, OmniContact and EcoCash represented as business units within one tenant, separate tenants, or both? Confirm against actual records in V0.
2. Does the business-unit tree identify legal companies or operational departments? If mixed, approve a separate legal-entity catalogue and mapping.
3. Which roles may mark an item Group-wide, reassign its company, confirm applicability, approve a link, issue/share a pack and override retention? Record these as separate capabilities.
4. Which file types require mandatory classification, period, owner or independent review? Agree minimums per policy, audit proof, privacy case and generated record.
5. Which active documents may be text indexed and sent to an approved AI provider? Default sensitive content to local search only until privacy approval.

## 12. External design research and dependency decision

This is pattern research, not a proposal to install a third-party document server or copy its implementation.

| Project | Observed useful approach | Licence, maintenance and fit | Decision |
| --- | --- | --- | --- |
| [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) and its [usage documentation](https://github.com/paperless-ngx/paperless-ngx/blob/dev/docs/usage.md) | Distinct correspondent, type, tags, saved views, bulk metadata editing, content search and document versions. | GPL-3.0; active releases around this plan's date. Python/Django backend but a separate application and frontend. | Reuse navigation and intake concepts only. Do not copy GPL code into ThemisIQ without licence review. |
| [Mayan EDMS](https://github.com/mayan-edms/Mayan-EDMS) | Controlled metadata, OCR, permissions and document workflow. | The inspected GitHub repository is a mirror; its code identifies Apache 2.0 licensing. Full Django DMS adoption would add considerable operational complexity. | Reference workflow ideas only; no runtime dependency. |
| [Docspell](https://github.com/eikek/docspell) | Suggested dates, correspondents and tags from document contents. | AGPL-3.0, Scala and a different stack; maintained repository at inspection time. | Reference human-review suggestion UX only; no code reuse. |

Supply-chain screen for this plan: no package, installer, container or plugin from these projects was executed or copied, and no data would be sent to them. Any later implementation that adopts code or binaries must independently review the exact tagged version, license obligations, dependency lock, build and postinstall scripts, unexpected network/telemetry and environment reads, provenance and maintenance before approval. This plan favors ThemisIQ's existing Vault, ARIA intake and isolated indexer to avoid a second trust boundary.

## 13. Review log

2026-10-28, after external review. Accepted and applied above:

1. **Exposure problem named.** Null-unit means organization-wide, so subsidiary-confidential files filed without a unit are visible to every unit today. V0 flags such items as narrowing candidates (section 1, slice V0).
2. **Family means the root evidence item.** Checked against the code: versions are `evidence_items` rows linked by `parent_id` and `version`; there is no `evidence_versions` table for the Vault (that name exists only for GRID) and no `artifact_family_id`. The plan now says so and forbids a parallel table. The review's wording of "evidence_versions children" was slightly off; the family is the `parent_id` chain.
3. **Smaller first release.** V0 plus a minimal V1 that never changes `business_unit_id`. The applicability relation and the legal-entity catalogue wait for V0 evidence. V2 to V5 are direction only.
4. **Open decision 1 gates V1 design** (tenants versus business units).
5. **Unconfirmed queue sized in V0;** the bulk confirm group-wide path with preview ships with V1.
6. **Branch hygiene.** The plan was committed on `codex/landing-seo-title-2026-10-28` (worktree `login-video-fonts-build`) on top of an unrelated SEO commit. It now lives on its own branch `claude/plan-19-evidence-company`, off master, with its own PR. The copy on the SEO branch should be dropped (or the SEO branch rebased by its owner) so the plan is not merged twice.
