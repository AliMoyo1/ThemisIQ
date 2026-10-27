# 03. Delivery sequence and acceptance

**Status:** Planned, not built. Do not label the three registers or the shared source spine as shipped because existing fragments are present. Verify the target branch and production schema before writing migrations.

## 1. Dependencies and concrete implementation areas

| Slice | Existing code to reuse or change | New contract/output |
| --- | --- | --- |
| A. Source registry | `modules/sentinel/living_law.py`, `modules/sentinel/scheduler.py`, `config.py` | Typed, reviewed source metadata; exact URL and rights/citation-domain projections; tenant subscriptions with preserved Sentinel keys/cadence |
| B. Fetch/capture | `core/outbound_http.py` security primitives, Sentinel fetch/extract/capture, evidence PDF child, `database.py` | Dedicated `core/source_fetch.py` or equivalent; immutable capture API with parser version, raw/text hashes, bounded section anchors and honest outcome states |
| C. Interpretation | `core/ai_client.py`, org AI policy, Sentinel inspector | Optional capture-bound candidate claims, deterministic passage validator, cost/privacy log and manual abstention |
| D. Governance and ERM | `modules/governance/data_service.py`, Regulatory Inbox, `modules/erm/ai_service.py` | Reviewed regulatory candidates before drift tasks; exact-ref matching retained; separate horizon leads and sourced emerging risks |
| E. Framework register | ARIA framework/policy services and `export_report.py`, Vault evidence links/proof, GRID audit context, report kit and saved runs | One scoped builder plus full detail XLSX/PDF, manifest, gaps and report-run controls |
| F. AI systems register | `modules/ai_governance/workspace.py`, routes, `applications`, `ai_use_profiles`, vendors, linked assessments | In-app maintenance and complete scoped export; reviewed XLSX import preview/confirm |
| G. AI risk register | `modules/orm/data_service.py`, AIMS routes, linked applications, AI Governance workspace, report kit | Risk-to-system links, scoring/rubric reconciliation, in-app risk desk, complete scoped export/import |

Use additive schema changes in SQLite and PostgreSQL tenant schemas through the repository's migration conventions. A global/public authority catalogue never contains private tenant facts. Preserve `sentinel_law_captures`, `regulatory_updates`, existing report runs, ARIA/Vault IDs, AI profiles and AIMS risks; any crosswalk is audited and reversible. No existing AI-use, policy or risk row is automatically renamed or promoted.

### Suggested APIs, refined against route conventions before coding

- Read-only: `GET /api/authority/sources`, `GET /api/authority/sources/{key}/captures`, `GET /api/authority/captures/{id}`, `GET /api/frameworks/{id}/auditor-register/preview`, `GET /ai-governance/api/registers/systems/preview`, `GET /ai-governance/api/registers/risks/preview`.
- Mutations: source subscription/cadence under the owning admin route; `POST /api/authority/captures/{id}/review`; Governance candidate approve/dismiss; `POST /api/reports/definitions` or a register-specific run that calls the same saved-report service; AI systems/risk workbook `preview-import` then version-checked `confirm-import`.
- Exports: existing `/api/reports/runs/{run_id}/export` and `/document` paths after registration of the new report types, or scoped module wrappers that call those same frozen-run and `report_kit` services. Never invent a second unsigned download path.

Every endpoint declares owning capability and record scope. Review and import endpoints use optimistic version checks, CSRF protection and idempotency keys. Background tasks return a job/run ID, progress, last successful stage and a failure state; no request holds a web worker open for thousands of rows.

## 2. Ordered build slices and exits

### Slice 0: Truth/permission baseline

Inventory live source keys, capture counts/states, regulatory updates, AI-use profiles, AIMS assessments/risks, ARIA documents/versions and Vault link outcomes per organization without reading secrets into logs. Record existing permission contracts, report sign-off/retention behavior, framework version identity and how AIMS assessments link applications. Freeze the three supplied workbooks as **test fixtures only** with names and hashes; do not bulk import. Exit: a mapping table labels every export field `authoritative`, `derived with method`, `manual attestation` or `not currently recorded`.

### Slice 1: S1/S2, source registry and guarded capture

Move Sentinel's starter catalogue behind a shared typed registry without changing its keys or first-user UX. Add rights and parser metadata, exact-URL fetch policy and normalized capture states. Run old and new comparisons on fixture sources, then shadow compare against authorized non-production or explicitly selected real sources. Exit: no incorrect `unchanged` after a failed fetch; navigation-only edits create no obligation task; existing captures and cadence remain readable.

### Slice 2: Governance candidate review

Create a pending regulatory candidate from a source capture, then wire explicit reviewer acceptance to the existing regulatory update and drift task. Preserve manual entry but label its source verification state. Replace the ungrounded `create_message` drift summary with a capture-bound draft or no AI summary. Exit: an unchanged/error/irrelevant source yields no task; only a reviewed candidate can claim an authoritative source-based update; exact control-ref equality regression passes.

### Slice 3: S3 and Sentinel/ERM consumers

Add optional locally captured diff interpretation with quote/capture validation, and DPO review beside Sentinel's existing inspector. Derive ERM horizon domains from the registry's horizon projection while keeping news distinct from legal authorities; keep uncited model-knowledge leads isolated. Exit: every displayed grounded claim reopens an exact source passage or says `cannot verify`; provider off/outage costs zero tokens and still shows the source diff.

### Slice 4: Framework auditor register

Add selected-framework preview and full-detail report builder using the existing ARIA, Vault, GRID and report-kit reads. Add report type/parameter validation, issue snapshot manifest, integrate saved-run sign-off, retention and permission-aware sharing. Exit: every authorized control, document and evidence relationship appears; summary counts agree with detailed rows; superseded/expired/unreviewed proof cannot be counted as accepted; denied-unit records leave no existence signal.

### Slice 5: AI systems register

Complete the field-source mapping, add missing versioned facts/aliases only where needed, add in-app completeness view and complete export. Build a bounded deterministic XLSX import with preview, mapping, conflict resolution and atomic confirmation. Exit: all eight rows of the supplied systems fixture appear as staged rows with the cover/inventory version conflict flagged; no imported row becomes approved solely from workbook text; export reads live scoped records.

### Slice 6: AI risk register

Add typed risk-to-system relationships and a joined AI Governance view backed by ORM AIMS. Make the scoring method explicit and versioned. Add complete workbook/PDF export and reviewed import of risk/treatment rows. Exit: all ten fixture risks appear in preview, the missing treatment and inconsistent 16-point/CRITICAL label are flagged, and a shared multi-system risk is counted once while linked to every authorized system.

### Slice 7: Pilot and release

Run a pilot with a governance specialist, an independent report sign-off role and an auditor-view role in two business-unit scopes and two tenant schemas. Have the specialist reconcile at least one source diff and one workbook conflict; produce the framework, AI systems and AI risk registers; verify every file opens and all links/records respect recipient rights. Keep external auditor invitation/bundling disabled until the narrower sharing contract passes review.

## 3. Verification matrix

| Gate | Required proof |
| --- | --- |
| Provenance | Raw and extracted hashes, parser version, capture date and exact source URL survive fetch, diff, review, report and rerun; tampering refuses an integrity claim |
| Interpretation | No model-detected change, no unsupported quote, no stale passage presented as current, no approval by model; source/rights/policy refusal has a usable manual path |
| Security | Exact URL/SSRF/redirect/MIME/size/PDF isolation, prompt-injection, cross-tenant and wrong-unit negatives; every preview, count, export and download uses the same scope |
| Import | Malformed ZIP/XLSX, formula/external-link, hidden data, duplicate ID, unknown system, scored/rubric conflict and stale form version fail safely; imported source text cannot assign roles or approve itself |
| Export | Every authorized detail row appears, even above UI page size and previous 60-row limits; counts, denominators and manifest agree; CSV/XLSX formula injection is neutralized |
| Workflow | An independent reviewer can sign or challenge a frozen run; later source edits do not mutate it; retention/legal hold and access revocation work; unresolved gaps remain visible |
| Accessibility and UX | Keyboard and narrow-screen preview, clear `Unknown` and `Not assessed` states, column explanations, progress/error recovery and human-readable source citations |
| Engines | Focused SQLite tests and disposable real PostgreSQL public + tenant-schema migrations/queries; production release gets a fresh verified backup, current role/RLS check and a rollback path |

Tests should exercise source services and route responses, not mirror implementation details. Use fixed fixture bytes/pages and workbook copies with deliberately conflicting metadata. Add a large fixture above 500 records for pagination/export equality and background generation. Avoid a full suite rerun until this stage is assembled unless the repository's CI gate requires it; report exactly which checks ran.

## 4. Release boundaries and remaining decisions

- **Legal/source owner:** A named governance or privacy specialist approves each new authority, source rights and interpretation; a DPO remains Sentinel's rule approver. No bulk publication of jurisdictions from research attachments.
- **Auditor authority:** A report generator cannot sign their own issued register where independent sign-off is configured. Reuse `platform.report.signoff` initially; organization administrators may assign eligible reviewers without changing the truth of a source row.
- **Retention:** Use the existing organization-editable report retention and hold controls. The default is a product setting, not a statement of statutory retention. Retain original import evidence and approved source versions under their separate Vault/source policies.
- **AI data policy:** External model use starts disabled for source content that lacks rights or organization approval. No Gemini adapter, external auditor invitation or automatic framework-rule modification is part of the initial release.
- **Backfill:** Existing ARIA/Vault, AI profiles and AIMS risk links need an inventory and reviewed crosswalk. Do not “fix” spreadsheet discrepancies or infer system links from names during migration.
- **Operational reporting:** Source check failures, stale capture age, pending review, denied AI calls, report job failure, incomplete export and reconciliation backlog need separate observability. Alert people on actionable changes, not every raw byte diff.

## 5. Completion definition

The programme is complete only when the three in-app register journeys and imports work against authorized live records, all three exports are full-detail and reproducible, source-driven updates are captured and reviewed without model-made change facts, citations bind to retained bytes, and the permission/quality/security matrix above passes. A polished screen or a successful download by itself is not completion.
