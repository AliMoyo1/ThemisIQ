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
