# PLAN-36 findings register

Status: SOURCE-BACKED AUDIT INPUT. This file records why work exists; it is not evidence that any remediation has been implemented.

- Audit date: 2026-09-24
- Repository: ThemisIQ only
- Audited baseline: `2b98cc4549e5e74decab32e7bafa79985008b17b`
- Production model: Hetzner Ubuntu VPS, PostgreSQL, `themisiq-app.service`
- Development model: Windows checkout at `C:\Projects\One For All\One For All`

## 1. Audit scope and evidence

The audit combined:

- current-source inspection of routes, templates, JavaScript, database DDL, operational scripts, tests, and GitHub workflows;
- an isolated authenticated browser crawl using a temporary database and headless Edge;
- representative interaction checks for shared modal and button behavior;
- static mapping of approximately 993 buttons, 398 links, 48 forms, and 1,341 inline `onclick` handlers;
- the full Python regression suite, branch coverage, Python compilation, dependency consistency, and dependency vulnerability scanning;
- Jinja compilation of all 60 templates with the application's registered filters;
- primary-page mobile overflow checks at 390 by 844 pixels.

The audit did not submit every destructive action and did not exercise live production data, external email destinations, real generic webhook destinations, production AI billing, or production LibreOffice conversion. Those checks belong to controlled acceptance tasks, not an unauthorised audit.

## 2. Confirmed defects

### F01 — Managed ARIA metadata edits are rejected by the client/server contract

Severity: release blocker.

- `modules/aria/templates/documents.html:882` disables `status`, `version`, `owner`, and `approver` for workflow-managed documents.
- `modules/aria/templates/documents.html:1107` manually appends those disabled values to `FormData` anyway.
- `modules/aria/routes.py:1181` correctly rejects any managed-document request that contains those lifecycle fields.
- Result: editing an otherwise permitted title, date, location, comment, or control reference can return HTTP 409 with the warning seen by the user.

The backend guard is correct and must remain. The client must omit workflow-owned fields. Metadata editing and revision/lifecycle actions also need clearer visual separation.

### F02 — Incompatible modal contracts make multiple buttons appear inert

Severity: release blocker.

`templates/base_shell.html:533` defines the shared contract as outer `.modal-overlay` plus inner `.modal`. Several templates instead use outer `.modal`, inner `.modal-content`, and add an `open` class for which the shared shell has no matching rule. The element stays in normal document flow and does not become an overlay.

Runtime-confirmed affected actions:

- New Task;
- Create Report;
- Register New Risk;
- Upload Evidence;
- Create Webhook.

The same source pattern affects New/Edit Calendar Event, Generate/Reveal API Key, and Link Evidence. Affected templates are:

- `modules/launcher/templates/task_board.html`;
- `modules/launcher/templates/reports.html`;
- `modules/launcher/templates/risk_register.html`;
- `modules/launcher/templates/calendar.html`;
- `modules/launcher/templates/admin_api_keys.html`;
- `modules/launcher/templates/admin_webhooks.html`;
- `modules/evidence/templates/evidence_index.html`.

ARIA uses another overlay convention, and `admin_frameworks.html` carries a local workaround. The app therefore has multiple incompatible modal systems.

### F03 — ERM Add Template is inaccessible and calls a missing function

Severity: high.

`modules/erm/templates/index.html:473` permanently hides `libAdminBtn` and calls `ermOpenLibraryModal()`, but that function is undefined. The backend CRUD endpoints already exist at `/erm/api/library` and require `erm.library.manage`. The page currently exposes `can_manage_frameworks`, not an explicit library-management capability.

Implementation must render the button from `erm.library.manage`, supply create/edit UI and validation, and reuse the existing API instead of creating a parallel endpoint.

### F04 — Email Settings Reset calls a non-global function

Severity: high.

`modules/launcher/templates/admin_email.html:209` uses inline `onclick="loadConfig()"`. `loadConfig` is declared inside an IIFE around line 325 and is not attached to `window`; `saveConfig` is explicitly attached. The Reset action can throw `ReferenceError` and appear inert.

### F05 — ERM schema-name drift affects user and recovery paths

Severity: high.

The canonical table is `erm_enterprise_risks`, with its display field named `title`. Stale consumers still use `erm_risks` and sometimes `name`:

- `modules/evidence/routes.py:970` — AI evidence-link suggestions;
- `database.py:4696` — stale migration indexes that warn on clean startup;
- `scripts/restore_backup.py:119` — restore validation;
- `scripts/weekly_restore_drill.py:41` — weekly recovery parity;
- `scripts/warm_replay.py:108` — warm replay report.

This is a query correction, not a compatibility-view or data migration requirement. Every replacement must preserve the consuming code's expected aliases, for example `title AS name` where the prompt expects `name`.

### F06 — Webhook Test reports success without delivering anything

Severity: high.

`modules/launcher/routes_admin.py:1260` claims to send a test ping but only inserts a `webhook_logs` row with response code 200 and success 1. It never invokes `core.webhooks` and therefore provides false assurance.

### F07 — Webhook/connector URL validation permits DNS-based SSRF

Severity: security release blocker.

`modules/launcher/routes_admin.py:85` blocks literal private addresses but accepts unresolved hostnames. `core/webhooks.py:80` later sends directly to the stored URL. A hostname resolving to loopback, private, link-local, reserved, or metadata space can therefore bypass validation. Redirects and DNS changes also need explicit treatment.

The current string prefix `172.` over-blocks public 172.x addresses instead of only `172.16.0.0/12`.

The fix must cover generic webhooks plus Slack, Teams, and WhatsApp connector test/delivery paths. Application validation must be paired with a documented VPS egress policy; application DNS checks alone cannot completely eliminate rebinding risk.

### F08 — Silent client-side failure patterns explain “nothing happened” reports

Severity: systemic high.

Multiple templates use empty catches, `if (!response.ok) return`, or unconditional `response.json()`. This converts server, proxy, network, and content-type failures into missing UI feedback or secondary JavaScript errors. Confirmed examples exist in ARIA, ERM, Evidence, GRID, Sentinel, Task Board, My Dashboard, Command Centre, and Email Settings.

The solution is a shared request/error contract and incremental migration of user-triggered mutations. Background best-effort reads may remain quiet only when the UI explicitly represents the unavailable state.

### F09 — Accessibility and keyboard contracts are incomplete

Severity: systemic medium, with high impact for keyboard and assistive-technology users.

Observed patterns include:

- no semantic `main` landmark across crawled authenticated pages;
- unlabeled notification and trainer controls;
- clickable `div`/`span` elements without keyboard semantics;
- SPA anchors without `href`;
- dialogs without `role=dialog`, `aria-modal`, accessible names, initial focus, focus trapping, focus restoration, or reliable Escape close;
- visual labels not programmatically associated with inputs.

### F10 — Green tests do not protect the browser/application boundary

Severity: systemic release-process blocker.

- Overall branch coverage was approximately 35 percent.
- BCM, GRID, Evidence, Governance, ORM, Sentinel, and much of Launcher had effectively no route coverage.
- Existing ARIA browser-state tests use a small simulated DOM, not an HTTP server and browser.
- No Playwright/Selenium equivalent protects primary user actions.
- GitHub Actions contains a PostgreSQL schema job and a manually dispatched ARIA preview-image job, but no full-suite or browser workflow on each push/PR.

### F11 — Large inline templates and global handlers create regression pressure

Severity: maintainability high.

The codebase contains very large Python modules and templates, including module pages over 3,000 lines and service/route files over 2,000 lines. Heavy inline JavaScript and global function lookup directly contributed to F03 and F04. This should be reduced incrementally after release blockers are covered by tests; a big-bang rewrite is prohibited.

### F12 — Product documentation is not authoritative

Severity: planning medium.

`FEATURE_INVENTORY.md`, `ROADMAP.md`, and operational trackers contain claims that no longer match current source. Capability documentation must be generated or verified against routes, capability gates, feature flags, and deployment prerequisites before it is used for sales, planning, or acceptance.

### F13 — ERM library administration is globally mutable across tenants

Severity: security and tenant-isolation blocker for enabling F03.

`erm_risk_library` has no `org_id`, `business_unit_id`, or creator scope. The create/update/delete services operate by unscoped integer ID. `erm.library.manage` is granted to `RISK_OWNER`, so an organization-level risk owner could mutate or retire the same global catalogue used by every organization if the hidden button were merely exposed.

F03 must therefore not be fixed by only showing the button. The data model and routes must distinguish platform-owned global templates from organization-owned custom templates. Organization users may read global active templates but only manage templates belonging to their organization. Only a platform super administrator may mutate the global catalogue.

## 3. Positive controls that must not regress

- All 133 discovered authenticated page GET routes returned HTTP 200 in the isolated crawl.
- All 60 Jinja templates compiled with application filters.
- The full Python suite passed at the audited baseline, with 10 expected skips.
- Python compilation and dependency consistency passed.
- Declared Python dependencies had no known vulnerabilities in the audit scan.
- Primary mobile pages had no body-level horizontal overflow in the sampled viewport.
- Current ARIA confirmation browser-state protection is present and must remain.
- ARIA's backend lifecycle guard, tenant/BU access checks, immutable version model, and feature gates must not be weakened to fix F01.

## 4. Product-improvement opportunities

These are post-stabilization opportunities, not permission to build duplicates:

1. A role-aware My Work action centre aggregating approvals, evidence requests, policy revisions, overdue controls, tasks, and reviews.
2. A sanitised administration diagnostics/readiness page for DB, AI, preview worker, LibreOffice, schedulers, queues, email, connectors, feature flags, and backup freshness.
3. An ARIA policy workbench that clearly separates current publication, editable revision, candidate version, approval, comparison, and next action.
4. A data-readiness centre for unowned, unscoped, unresolved, stale, or cross-module-invalid records.
5. Evidence collection campaigns with ownership, due dates, reminders, coverage gaps, and chain-of-custody history.
6. Saved views and safe bulk actions across risks, tasks, evidence, policies, vendors, and findings.
7. ERM scenario/KRI/control linkage and immutable board-pack snapshots, extending the existing ERM register, objectives, KRIs, assessments, and reports.
8. BCM exercise after-action and corrective-action improvements, extending the existing exercise/scenario capability rather than recreating it.
9. Consistent capability states: available, disabled by policy, not configured, temporarily unavailable, or forbidden.

Each feature phase in `task_plan.md` begins with a source-and-user discovery gate. If equivalent behavior already exists, improve or expose it; do not create a second model, route family, or navigation item.

## 5. Constraints for implementation

- ThemisIQ only. Do not add EcoAegis or ODIN material.
- Preserve organization and SBU isolation everywhere.
- Never relax a backend authorization or workflow rule to make a button work.
- Do not perform production writes, migrations, restarts, deployments, commits, or pushes without the user's separate instruction.
- SQLite tests do not prove PostgreSQL behavior; run the guarded PostgreSQL suite for schema/query changes.
- Real browser evidence is required for browser claims.
- External delivery tests require controlled destinations owned by the user; do not send to arbitrary third parties.
- Production acceptance requires a fresh verified backup and rollback point, but repeated checks may be reused within their explicitly documented freshness window.

## 6. Addendum: findings discovered after the 2026-09-24 audit

Findings below were not part of the original audit and are dated separately.
They are recorded here, in this register, so this file stays the single
place every confirmed defect is tracked -- but each is explicitly marked
with its own discovery date rather than folded into section 2's original,
dated audit scope.

### F14 — Evidence repository has no tenant/organization scoping (discovered 2026-09-30)

Severity: security and tenant-isolation blocker, same class as F13, more severe in practice.

Discovered while building T08 download-contract tests, not by a targeted security review. `evidence_items` (`database.py`) had no `org_id`, `business_unit_id`, or creator-scope column at all, and none of `modules/evidence/routes.py`'s list, get, download, download-pdf, update, delete/archive, restore, or permanent-delete routes filtered by organization -- every one of them reached the row by a plain, unscoped `id`. `evidence.delete` is granted to `COMPLIANCE_MGR`, an org-scoped role, and list/get/download only required `@require_auth` (any authenticated user, any organization, no extra capability). In effect, any logged-in user in any tenant could list, read, download, rename, archive, restore, or permanently delete any other tenant's evidence -- compliance documents, audit evidence, and policy attachments -- simply by knowing or guessing an id, with no cross-tenant defense anywhere in the stack. PostgreSQL's RLS layer (`core/rls.py`) did not cover this table either, so the gap was live on both SQLite (always) and PostgreSQL (for any organization not otherwise isolated by a dedicated tenant schema).

Fixed the same session it was found (see `progress.md` 2026-09-30 T08 session 5 for full verification evidence): `org_id` added via the existing `_COLUMN_MIGRATIONS` schema-evolution mechanism plus an idempotent `_backfill_evidence_org_id` data migration (backfills from the uploader's own `org_id`, so existing deployed evidence is not silently hidden from its own organization on upgrade); every route above now goes through a shared `_scoped_evidence_item` fail-closed lookup (same shape as `_get_webhook_for_admin`); RLS extended to cover `evidence_items` for Postgres defense-in-depth; upload's cross-org duplicate-detection-by-hash and `replace_id` version-chain lookup (two smaller, adjacent information/write leaks in the same function) fixed alongside it. Each mechanism has a red/green proof.

All `evidence_items` read/write touchpoints that expose row content are now fixed, across four same-session follow-up rounds (versions, verify, confidence-verify x2, links-create, links-delete, suggest-links, linked, auto-evidence, stats). `links-delete` had no ownership check of any kind before the fix, not even the plain-`@require_auth` pattern the others had; `suggest-links` had leaked another org's evidence metadata into an AI prompt; `stats`' `recently_added` field returned real title/category/file_name for the platform's 5 most-recently-uploaded items, not just a count as first assumed -- re-checked and fixed once that was noticed. `/api/resolve-links`, `/api/coverage`, and `/api/search-entities` were read directly and confirmed to never query `evidence_items` for content (they resolve/count/search OTHER modules' entities), so are genuinely out of this finding's scope -- every touchpoint that does query evidence_items is now fixed. See `progress.md` for the complete list, including two pre-existing tests this fix's correct new behavior broke (both fixed the same session: a stale test fixture in `test_modal_contract.py` that seeded evidence with no org_id, and a test-authoring bug introduced while adding this fix's own test coverage).

### F15 — ORM event CSV export used a capability string granted to no role, and a column that does not exist (discovered 2026-09-30)

Severity: functional, not security -- the effect was fail-closed (nobody could use the feature), not fail-open.

Discovered by T10's new `scripts/capability_inventory.py` (a read-only generator that introspects the real, running route table rather than source text -- see the script's own docstring). Its output flagged exactly one capability string, `orm.event.view`, granted to no role anywhere in `core/rbac.py`'s `CAPABILITIES` table. `core/rbac.py`'s own `has_capability()` returns `False` immediately for an unrecognized capability string, before ever checking the caller's roles (`if allowed is None: return False`), with no super-admin bypass at that layer -- so `GET /orm/api/export/csv` (`modules/orm/routes.py:576`) was unreachable by every single account on the platform, including a platform super admin, since the day it shipped.

Fixing the capability string alone (to `module.orm.access`, matching every other read-only GET route in the same file) surfaced a second, previously-masked bug in the same handler: its query selected a `reporter_name` column that does not exist on `orm_events` at all (the table has `reported_by`, a user-id foreign key, not a name string) -- a 500 that the capability bug had made completely unreachable, and therefore untested and unnoticed, until the auth layer was fixed. Fixed by joining `users` and aliasing `u.full_name AS reporter_name`, the same pattern the codebase's other CSV exports already use.

Both fixes are red/green-proved in `tests/ui/test_download_contracts.py` (see `progress.md` T10 session 1). This is recorded as its own finding, separate from T10's other work, because it is a genuine, previously-shipped, user-facing defect that a documentation-generation task incidentally uncovered -- not something T10 set out to fix.

### F16 — Several core business tables have no tenant/BU scoping, same class as F14 (discovered 2026-09-30)

Severity: security and tenant-isolation blocker, same class as F14.

Discovered while checking whether P01 (My Work action centre) could safely build on the existing `/api/my-dashboard/data` and `/api/command-centre/stats` queries -- those widget queries touch `bcm_incidents`, `sentinel_dsr`, `grid_non_conformances`, `erm_enterprise_risks`, and `orm_events` with no visible scoping, which raised the question of whether the underlying tables are scoped at all anywhere. Checked by reading each module's own primary list/get/update/delete routes directly, not assumed:

- **`bcm_incidents`**: no `business_unit_id` (or any scoping column) existed at all. `list_incidents`/`get_incident`/`update_incident`/`delete_incident`/the CSV export all queried by plain id/no filter. `module.bcm.access` (the capability gating list/get) is held by `EMPLOYEE`, so this was reachable by any authenticated staff member in any business unit, in any organization. **Fixed** (see `progress.md` T08 session 7): `business_unit_id` column added, every touchpoint now scoped via `bu_scope_ids()` (the same convention `bcm_plans`/`bcm_bia_records` already use), `get_incident`/`update_incident`/`delete_incident` fail closed (return `None`/`False`) outside scope. No backfill: `commander`/`assigned_to` are free-text names, not user FKs, so there is no reliable column to derive an existing row's business unit from; a fuzzy name-match was rejected as riskier than leaving it for a human to assign. Red/green proved for get/update/delete/list independently.
- **`sentinel_dsr`** (GDPR data-subject requests -- real requester names/emails/request details, gated by `sentinel.dsr.manage`: DPO, PRIVACY_ANALYST): same shape as `bcm_incidents` -- no scoping column at all, `list_dsrs()` took no `bu_scope` parameter, and neither did the AI-draft endpoint (`POST /api/ai/dsr-draft/{dsr_id}`, gated by the separate, broader `sentinel.ai.assess` capability) or the audit evidence-pack ZIP export (`GET /api/audit-export`, gated by the broad `module.sentinel.access`) -- the latter was also found to unscope `list_ropa()`/`list_dpias()`/`list_breaches()` in the same function, fixed alongside it even though RoPA/DPIA/breach listing elsewhere already scope correctly. **Fixed**, same pattern and no-backfill reasoning as `bcm_incidents` (no user-id column on this table either). Red/green proved for get/update/delete/list independently.
- **`grid_non_conformances`** (gated by `grid.nc.manage`): unscoped whenever `GET /grid/api/ncs` was called without a specific `audit_id`, an optional parameter. **Fixed** differently from the other two: `audit_id` is a required (`NOT NULL`), not-nullable foreign key to `grid_audits`, which already has its own `business_unit_id` (from earlier T-work) and its own correctly-`bu_scope_ids()`-scoped listing -- so this needed no new column and no backfill at all. Scoped by joining through the audit relationship the query already had (for `audit_name` display), using `a.business_unit_id`. Red/green proved for get/update/delete/list independently. **Named, not-yet-fixed gap**: `create_nc` does not verify the caller's `bu_scope` actually includes the `audit_id` supplied in the request body, so a user could still create a non-conformance record under another business unit's audit (a write-side gap distinct from the read/update/delete-by-id gap this finding fixes).
- **Confirmed correctly scoped already** (checked, not assumed): `erm_enterprise_risks` (`api_risks_list` passes `bu_scope=bu_scope_ids(...)`), `orm_events` (same), and most of Sentinel's other record types (DPIAs, breaches, AI impact assessments) already pass `bu_scope` on their primary routes. This is not a uniform, app-wide failure -- it is concentrated in specific tables that were missed when each module's own scoping convention was built out.

All three confirmed gaps above are now fixed, red/green-proved, and confirmed against a full clean backend + browser suite run (see `progress.md` T08 sessions 7-9).

A separate, broader, **not yet resolved** observation surfaced while investigating this: the established `(business_unit_id IN (scope) OR business_unit_id IS NULL)` convention used throughout this codebase (confirmed via `modules/governance/data_service.py`'s `bu_scope_ids()` docstring: "A list means: only rows whose business_unit_id is in the list, or NULL") means a NULL-business_unit_id row is visible to every business unit within an org that reaches it -- but `bu_scope_ids()` itself only derives a BU subtree, with no org-level check layered on top of the "OR IS NULL" branch. Whether this could let a NULL-BU row from one organization become visible to a *different* organization's users was not confirmed or ruled out this session; it would affect every table using this convention, not just the three named above, and needs its own dedicated investigation before being treated as either a non-issue or another F14/F16-class finding.

### F17 — Write-path BU-scope gaps on ERM/ORM/GRID, and no BU scoping at all on Task Board (discovered 2026-09-30)

Severity: same class as F14/F16 -- authorization bypass on a mutating path, not just a display/visibility gap.

Discovered while researching P06 (saved views and permission-safe bulk actions): investigating existing bulk-action patterns required reading every module's list/detail/update/delete route pair side by side, which surfaced that F16's own note "confirmed correctly scoped already: `erm_enterprise_risks`, `orm_events`" was true only of their **list/detail (read)** routes -- their **update/delete (write)** routes had no equivalent check at all, a narrower but real gap F16 did not catch because it did not compare read and write paths directly.

- **ERM**: `PUT`/`DELETE /erm/api/risks/{risk_id}` (`modules/erm/routes.py`) called `update_enterprise_risk`/`delete_enterprise_risk` directly with no `bu_scope_ids()` check, unlike the file's own `GET .../{risk_id}` a few lines above, which does check. A holder of the broad `erm.risk.manage` capability (not itself BU-restricted) could mutate or delete any risk company-wide by id, bypassing the same boundary the read path enforces. **Fixed**: extracted the read path's own check into `_risk_in_scope_or_404()`, called from both `PUT` and `DELETE` before the mutation (404, not 403 -- never confirm an out-of-scope id exists). Red/green proved.
- **ORM**: identical gap and identical fix on `PUT`/`DELETE /orm/api/events/{event_id}` (`modules/orm/routes.py`), via a new `_event_in_scope_or_404()`.
- **GRID**: `PUT /grid/api/evidence/bulk-approve` (`modules/grid/routes.py` → `bulk_approve_evidence` in `modules/grid/data_service.py`) took the posted evidence-file id list on complete trust -- no ownership, org, or BU check of any kind before approving/rejecting each one. **Fixed**: `bulk_approve_evidence` now takes `bu_scope` and, per id, joins `grid_evidence_files -> grid_controls -> grid_audits.business_unit_id` (no new column needed, both FKs are required) to silently exclude an out-of-scope id rather than applying it; the route now passes `bu_scope_ids(request.state.user)`. The endpoint's own return value (`count`) already reports how many were actually applied, so an excluded id is visible to the caller as a smaller count, not a silent full success. Red/green proved.
- **Task Board**: `GET /api/tasks` (`modules/launcher/routes_platform.py`) had `where = ["1=1"]` -- no scoping of any kind, despite `task_board.business_unit_id` existing as a column. Any authenticated user (`@require_auth` only) saw every business unit's tasks within reach, up to the hardcoded `LIMIT 500`. **Fixed**: added a `(business_unit_id IS NULL OR business_unit_id IN (scope))` clause using `bu_scope_ids()`, the same NULL-is-org-wide-visible convention used throughout this codebase. Not red/green proved individually (covered by the same positive-exclusion test as the others); confirmed by seeding a task in a second BU and asserting it does not appear for a persona outside that BU.

Note on severity calibration: `task_board`, like `grid_controls`/`erm_enterprise_risks`, has no `org_id` column and is provisioned as a genuinely separate table per tenant schema on PostgreSQL (confirmed via `database.py`'s `_apply_tenant_schema_ddl`/`_PLATFORM_TABLES_PG`) -- so the missing filter was never a **cross-organization** leak in production, only a **cross-business-unit** one within a single org. This is real and worth fixing (a Finance BU employee should not see Legal BU's tasks), but is a materially smaller blast radius than F14 (evidence_items, a genuinely shared/public-schema table with a real `org_id` column that was missing its filter in production). The ERM/ORM/GRID write-path gaps are full authorization bypasses regardless of this distinction, since they let a user actively mutate/delete a specific record they could not otherwise even see.

All four fixed, red/green-proved (ERM and GRID directly; ORM by the identical code path; Task Board by direct positive-exclusion test), and confirmed against a full clean backend + browser suite run (see `progress.md`'s P06 discovery session entry).
